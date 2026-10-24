from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from groundplan.config import get_settings
from groundplan.db import base
from groundplan.db import models as m
from groundplan.services.portfolio import get_owned

from .problems import not_found


def db() -> Iterator[Session]:
    yield from base.get_session()


def advisor_id(x_advisor_id: str | None = Header(default=None, description="Optional; defaults to the dev advisor")) -> str:
    return x_advisor_id or get_settings().dev_advisor_id


def owned(s: Session, model, id_: str, aid: str, what: str):
    obj = get_owned(s, model, id_, aid)
    if obj is None:
        raise not_found(what, id_)
    return obj


class Ctx:
    def __init__(self, s: Session = Depends(db), aid: str = Depends(advisor_id)):
        self.s = s
        self.aid = aid

    def household(self, id_: str) -> m.Household:
        return owned(self.s, m.Household, id_, self.aid, "Household")

    def property(self, id_: str) -> m.Property:
        return owned(self.s, m.Property, id_, self.aid, "Property")
