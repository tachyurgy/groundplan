"""API tests run against the local groundplan_test database (unix socket, no network). The schema is built by
running the Alembic migrations, so the migration itself is under test."""

from __future__ import annotations

import os

import pytest

TEST_URL = os.environ.get("GP_TEST_DATABASE_URL", "postgresql+psycopg://@/groundplan_test?host=/tmp")
os.environ["GP_DATABASE_URL"] = TEST_URL

from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from groundplan.db import base  # noqa: E402

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEV_ADVISOR = "00000000-0000-4000-8000-000000000001"
OTHER_ADVISOR = "00000000-0000-4000-8000-0000000000b2"


@pytest.fixture(scope="session")
def db_session_factory():
    Session = base.configure(TEST_URL)
    with base.engine().begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(os.path.join(BACKEND, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND, "alembic"))
    cfg.attributes["url"] = TEST_URL
    command.upgrade(cfg, "head")
    return Session


@pytest.fixture()
def seeded(db_session_factory):
    from scripts.seed import ensure_advisor, seed

    with db_session_factory() as s:
        for aid in (DEV_ADVISOR, OTHER_ADVISOR):
            s.execute(text("DELETE FROM households WHERE advisor_id = :a"), {"a": aid})
        h = seed(s, DEV_ADVISOR)
        ensure_advisor(s, OTHER_ADVISOR, name="Other Advisor", firm="Other Firm")
        s.commit()
        return h.id


@pytest.fixture()
def client(seeded):
    from fastapi.testclient import TestClient

    from groundplan.api import app

    return TestClient(app, headers={"X-Workspace-Id": DEV_ADVISOR})
