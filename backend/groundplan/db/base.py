from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from groundplan.config import get_settings


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


_engine = None
_Session: sessionmaker | None = None


def configure(url: str | None = None) -> sessionmaker:
    global _engine, _Session
    _engine = create_engine(url or get_settings().database_url, pool_pre_ping=True, future=True)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _Session


def engine():
    if _engine is None:
        configure()
    return _engine


def get_session() -> Iterator[Session]:
    if _Session is None:
        configure()
    assert _Session is not None
    s = _Session()
    try:
        yield s
    finally:
        s.close()
