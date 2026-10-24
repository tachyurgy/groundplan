from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from groundplan.db import base
from groundplan.db import models as m
from groundplan.services import workspace as ws
from groundplan.services.portfolio import get_owned

from .problems import Problem, not_found


def db() -> Iterator[Session]:
    yield from base.get_session()


def workspace_id(request: Request, x_workspace_id: str | None = Header(
        default=None, description="Workspace (tenant) id: a random UUIDv4 the client keeps in localStorage. "
                                  "Unknown ids are provisioned and seeded with the demo household on first use."),
        s: Session = Depends(db)) -> str:
    try:
        wid = ws.parse_id(x_workspace_id)
        ws.ensure(s, wid, ws.client_ip(request.headers, request.client.host if request.client else None))
    except ws.WorkspaceError as e:
        raise Problem(e.status, e.title, e.detail, f"https://groundplan.dev/problems/{e.kind}") from e
    return wid


def owned(s: Session, model, id_: str, aid: str, what: str):
    obj = get_owned(s, model, id_, aid)
    if obj is None:
        raise not_found(what, id_)
    return obj


class Ctx:
    def __init__(self, s: Session = Depends(db), aid: str = Depends(workspace_id)):
        self.s = s
        self.aid = aid

    def household(self, id_: str) -> m.Household:
        return owned(self.s, m.Household, id_, self.aid, "Household")

    def property(self, id_: str) -> m.Property:
        return owned(self.s, m.Property, id_, self.aid, "Property")
