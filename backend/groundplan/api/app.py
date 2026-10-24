"""FastAPI application: /api/v1, OpenAPI at /docs, problem+json errors, CORS for the Vite dev server."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from groundplan import __version__
from groundplan.api import problems
from groundplan.api.routers import documents, households, misc, properties
from groundplan.config import get_settings

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(title="Groundplan API", version=__version__,
                  description="Real estate planning engine for financial advisors. Every number is a Figure with provenance; "
                              "money is integer cents; errors are RFC 7807 problem+json.",
                  docs_url="/docs", openapi_url="/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    problems.install(app)
    for r in (misc.router, households.router, properties.router, documents.router):
        app.include_router(r, prefix=API_PREFIX)
    return app


app = create_app()
