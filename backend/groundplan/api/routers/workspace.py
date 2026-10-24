"""System endpoints that need no workspace (/health, /meta) and the workspace endpoints (SPEC §8.1, §8.2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from groundplan import __version__
from groundplan.api.deps import Ctx, db
from groundplan.config import get_settings
from groundplan.meta import STARTED_AT, git_sha, runtime
from groundplan.services import workspace as ws

router = APIRouter()
_pg_major: list[str] = []


@router.get("/health", tags=["system"], summary="Liveness + DB check (no workspace needed)")
def health(s: Session = Depends(db)):
    s.execute(text("select 1"))
    st = get_settings()
    return {"status": "ok", "version": __version__, "db": "ok", "engine": st.engine,
            "narrative_provider": st.llm_provider or "template", "retain_uploads_seconds": st.retain_uploads_seconds}


@router.get("/meta", tags=["system"], summary="Which backend is this (footer badge; no workspace needed)")
def meta(s: Session = Depends(db)):
    if not _pg_major:
        try:
            num = int(s.execute(text("show server_version_num")).scalar_one())
            _pg_major.append(f"postgres {num // 10000}")
        except Exception:  # noqa: BLE001 - meta must answer even if the DB is down
            return _meta("postgres")
    return _meta(_pg_major[0])


def _meta(db_label: str) -> dict:
    st = get_settings()
    return {"backend": "python", "version": git_sha(), "engine": "go" if st.engine == "go" else "python",
            "runtime": runtime(), "started_at": STARTED_AT, "db": db_label}


@router.get("/workspace", tags=["workspace"], summary="This workspace: id, created_at, household and document counts")
def get_workspace(c: Ctx = Depends()):
    return ws.summary(c.s, c.aid)


@router.post("/workspace/reset", tags=["workspace"], summary="Delete this workspace's data and re-seed the demo household")
def reset_workspace(c: Ctx = Depends()):
    ws.reset(c.s, c.aid)
    return ws.summary(c.s, c.aid)
