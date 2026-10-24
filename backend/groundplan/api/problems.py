"""RFC 7807 problem+json for every error."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM = "application/problem+json"


class Problem(Exception):
    def __init__(self, status: int, title: str, detail: str | None = None, type_: str = "about:blank", **extra):
        self.status, self.title, self.detail, self.type, self.extra = status, title, detail, type_, extra


def problem_response(status: int, title: str, detail: str | None, instance: str, type_: str = "about:blank", **extra) -> JSONResponse:
    body = {"type": type_, "title": title, "status": status, "instance": instance}
    if detail:
        body["detail"] = detail
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM)


def not_found(what: str, id_: str) -> Problem:
    return Problem(404, f"{what} not found", f"No {what.lower()} {id_!r} in this workspace", "https://groundplan.dev/problems/not-found")


def install(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def _problem(request: Request, exc: Problem):
        return problem_response(exc.status, exc.title, exc.detail, request.url.path, exc.type, **exc.extra)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        return problem_response(exc.status_code, str(exc.detail) if exc.status_code != 404 else "Not Found",
                                None if exc.status_code == 404 else None, request.url.path)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return problem_response(422, "Validation failed", f"{len(errors)} invalid field(s)", request.url.path,
                                "https://groundplan.dev/problems/validation", errors=errors)
