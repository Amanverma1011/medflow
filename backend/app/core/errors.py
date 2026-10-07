"""Structured error envelope: {"error": {"code", "message", "details"}}."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("medflow")

CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
         409: "conflict", 413: "payload_too_large", 422: "validation_error", 429: "rate_limited"}


class AppError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None, details=None, headers=None):
        self.status, self.message, self.details, self.headers = status, message, details, headers
        self.code = code or CODES.get(status, "error")


def _body(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app(_: Request, exc: AppError):
        return JSONResponse(_body(exc.code, exc.message, exc.details), exc.status, headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return JSONResponse(_body(CODES.get(exc.status_code, "error"), str(exc.detail)), exc.status_code,
                            headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(_body("validation_error", "The request was not valid.", details), 422)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Log the type and route only: exception text can carry user-supplied medical content.
        log.error("unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path, exc_info=exc)
        return JSONResponse(_body("internal_error", "Something went wrong on our side."), 500)
