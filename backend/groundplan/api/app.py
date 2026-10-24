"""FastAPI application: /api/v1, OpenAPI at /docs, problem+json errors, CORS for the twin front ends (SPEC §8.1)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from groundplan import __version__
from groundplan.api import problems
from groundplan.api.routers import documents, engine, households, misc, properties, workspace
from groundplan.config import get_settings

API_PREFIX = "/api/v1"
log = logging.getLogger("groundplan")


def _sweep_once() -> None:
    from groundplan.db import base
    from groundplan.services import workspace as ws

    gen = base.get_session()
    s = next(gen)
    try:
        ws.sweep(s)
    except Exception:  # noqa: BLE001 - housekeeping must never take the API down
        log.exception("workspace_sweep_failed")
    finally:
        gen.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    st = get_settings()
    task = None
    if st.sweep_enabled:
        async def loop():
            while True:
                await asyncio.to_thread(_sweep_once)
                await asyncio.sleep(st.sweep_interval_hours * 3600)

        task = asyncio.create_task(loop())
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    st = get_settings()
    app = FastAPI(title="Groundplan API", version=__version__, lifespan=lifespan,
                  description="Real estate planning engine for financial advisors. Every number is a Figure with provenance; "
                              "money is integer cents; errors are RFC 7807 problem+json. Tenancy: every request (except "
                              "/health, /meta, /eval/latest) carries `X-Workspace-Id` (a UUID); unknown workspaces are "
                              "provisioned and seeded with the demo household on first use.",
                  docs_url="/docs", openapi_url="/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=st.cors_origins, allow_origin_regex=st.cors_origin_regex,
                       allow_credentials=False, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                       allow_headers=["X-Workspace-Id", "Content-Type"], expose_headers=["Content-Disposition"], max_age=600)

    @app.middleware("http")
    async def body_limit(request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > st.max_body_mb * 1024 * 1024:
            return problems.problem_response(413, "Request body too large", f"max {st.max_body_mb} MB", request.url.path,
                                             "https://groundplan.dev/problems/body-too-large")
        return await call_next(request)

    problems.install(app)
    for r in (workspace.router, misc.router, households.router, properties.router, documents.router):
        app.include_router(r, prefix=API_PREFIX)
    app.include_router(engine.router)  # /engine/analyze, /engine/strategies: the wire API the Go port also serves
    return app


app = create_app()
