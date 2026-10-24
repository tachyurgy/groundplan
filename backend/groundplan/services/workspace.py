"""No-login workspaces (SPEC §8.1).

A workspace IS an advisor row: the browser mints a UUIDv4, sends it as `X-Workspace-Id`, and every query is filtered by
it. The first request with an unknown id provisions the advisor and seeds the demo household in ONE transaction.

Concurrency: two first requests for the same id race on `INSERT ... ON CONFLICT (id) DO NOTHING RETURNING id`. Postgres
makes the loser wait on the winner's uncommitted primary-key entry; when the winner commits, the loser's insert returns
no row, it rolls back (undoing its own provisioning-counter bump) and simply uses the seeded workspace. Exactly one seed.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from groundplan.config import get_settings
from groundplan.db import models as m

log = logging.getLogger("groundplan.workspace")

TOUCH_EVERY = timedelta(minutes=5)  # last_seen_at is refreshed at most this often per workspace


class WorkspaceError(Exception):
    def __init__(self, status: int, title: str, detail: str, kind: str):
        super().__init__(detail)
        self.status, self.title, self.detail, self.kind = status, title, detail, kind


@dataclass
class Workspace:
    id: str
    created: bool


def parse_id(raw: str | None) -> str:
    """Canonical lowercase UUID string, or WorkspaceError(400)."""
    if not raw:
        raise WorkspaceError(400, "Missing workspace", "send a random UUIDv4 as the X-Workspace-Id header", "workspace-required")
    try:
        u = uuid.UUID(raw.strip())
    except ValueError as e:
        raise WorkspaceError(400, "Invalid workspace", "X-Workspace-Id must be a UUID (e.g. crypto.randomUUID())",
                             "workspace-invalid") from e
    return str(u)


def client_ip(headers, peer: str | None) -> str:
    """CF-Connecting-IP, else the first X-Forwarded-For hop, else the socket peer. (Client-supplied headers are
    spoofable when the request does not come through Cloudflare; this is an abuse speed bump, not authentication.)"""
    ip = headers.get("cf-connecting-ip") or (headers.get("x-forwarded-for") or "").split(",")[0].strip() or peer or "unknown"
    return ip[:64]


def ensure(s: Session, workspace_id: str, ip: str) -> Workspace:
    """Return the workspace, provisioning + seeding it if it does not exist yet. Commits."""
    now = datetime.now(UTC)
    seen = s.execute(select(m.Advisor.last_seen_at).where(m.Advisor.id == workspace_id)).first()
    if seen is not None:
        if seen[0] is None or seen[0] < now - TOUCH_EVERY:
            s.execute(text("UPDATE advisors SET last_seen_at = now() WHERE id = :id"), {"id": workspace_id})
            s.commit()
        return Workspace(workspace_id, False)

    limit = get_settings().max_workspaces_per_ip_per_day
    count = s.execute(text(
        "INSERT INTO workspace_provisions (ip, day, count) VALUES (:ip, (now() AT TIME ZONE 'utc')::date, 1) "
        "ON CONFLICT (ip, day) DO UPDATE SET count = workspace_provisions.count + 1 RETURNING count"), {"ip": ip}).scalar_one()
    if count > limit:
        s.rollback()
        raise WorkspaceError(429, "Too many new workspaces", f"at most {limit} new workspaces per client IP per day; "
                             "reuse your existing workspace id or try again tomorrow", "workspace-rate-limit")
    won = s.execute(text(
        "INSERT INTO advisors (id, advisor_id, firm_name, name, email, created_at, last_seen_at, created_ip) "
        "VALUES (:id, :id, 'Demo workspace', 'Demo advisor', '', now(), now(), :ip) "
        "ON CONFLICT (id) DO NOTHING RETURNING id"), {"id": workspace_id, "ip": ip}).first()
    if won is None:  # a concurrent first request created (and committed) it; ours must not count
        s.rollback()
        return Workspace(workspace_id, False)
    from scripts.seed import seed  # the same seed as `python -m scripts.seed`

    seed(s, workspace_id)
    s.commit()
    log.info("workspace_provisioned id=%s ip=%s", workspace_id, ip)
    return Workspace(workspace_id, True)


def counts(s: Session, workspace_id: str) -> tuple[int, int]:
    hh = s.execute(select(func.count()).select_from(m.Household).where(m.Household.advisor_id == workspace_id)).scalar_one()
    docs = s.execute(select(func.count()).select_from(m.Document).where(m.Document.advisor_id == workspace_id)).scalar_one()
    return hh, docs


def summary(s: Session, workspace_id: str) -> dict:
    adv = s.get(m.Advisor, workspace_id)
    hh, docs = counts(s, workspace_id)
    created = adv.created_at if adv is not None else None
    return {"id": workspace_id, "created_at": created.isoformat() if created else None, "households": hh, "documents": docs}


def reset(s: Session, workspace_id: str) -> None:
    """Delete everything the workspace owns (FK cascades take properties, loans, years, documents, fields, findings...)
    and re-seed the demo household. One transaction."""
    s.execute(delete(m.Household).where(m.Household.advisor_id == workspace_id))
    s.expunge_all()
    from scripts.seed import seed

    seed(s, workspace_id)
    s.execute(text("UPDATE advisors SET last_seen_at = now() WHERE id = :id"), {"id": workspace_id})
    s.commit()


def sweep(s: Session, idle_days: int | None = None) -> int:
    """Delete workspaces idle longer than `idle_days` (default GP_WORKSPACE_IDLE_DAYS = 14) and old IP counters."""
    st = get_settings()
    days = st.workspace_idle_days if idle_days is None else idle_days
    cutoff = datetime.now(UTC) - timedelta(days=days)
    gone = s.execute(text("DELETE FROM advisors WHERE last_seen_at < :cutoff AND id <> :dev RETURNING id"),
                     {"cutoff": cutoff, "dev": st.dev_advisor_id}).all()
    s.execute(text("DELETE FROM workspace_provisions WHERE day < (now() AT TIME ZONE 'utc')::date - 2"))
    s.commit()
    if gone:
        log.info("workspace_sweep deleted=%d idle_days=%d", len(gone), days)
    return len(gone)
