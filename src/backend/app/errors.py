from __future__ import annotations

import uuid

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, details: list[str] | None = None,
                 retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or []
        self.retryable = retryable


def error_body(code: str, message: str, details: list[str] | None = None, retryable: bool = False) -> dict:
    return {"error": {"code": code, "message": message, "details": details or [],
                      "retryable": retryable, "request_id": uuid.uuid4().hex[:12]}}


def not_found(kind: str) -> AppError:
    return AppError(404, "NOT_FOUND", f"{kind} not found")


def conflict(code: str, message: str, details: list[str] | None = None) -> AppError:
    return AppError(409, code, message, details)


def install(app) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(error_body(exc.code, exc.message, exc.details, exc.retryable), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [f"{'.'.join(str(x) for x in e.get('loc', []))}: {e.get('msg')}" for e in exc.errors()]
        return JSONResponse(error_body("VALIDATION_FAILED", "Request did not match the contract", details),
                            status_code=422)
