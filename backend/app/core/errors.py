from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


class BizError(AppError):
    """业务规则校验失败（如库存不足、状态不允许）。"""

    status_code = 422
    code = "business_error"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


def _body(code: str, message: str, details: Any = None) -> dict:
    return {"code": code, "message": message, "details": details}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        errors = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", []) if x != "body")
            errors.append({"field": loc, "message": err.get("msg")})
        first = errors[0] if errors else {"field": "", "message": "参数错误"}
        msg = f"参数错误: {first['field']} {first['message']}".strip()
        return JSONResponse(status_code=422, content=_body("validation_error", msg, errors))

    @app.exception_handler(IntegrityError)
    async def _integrity_error(_: Request, exc: IntegrityError):
        text = str(exc.orig) if exc.orig else str(exc)
        if "unique" in text.lower() or "duplicate" in text.lower():
            return JSONResponse(status_code=409, content=_body("duplicate", "数据重复，违反唯一性约束", text[:300]))
        return JSONResponse(status_code=409, content=_body("integrity_error", "数据完整性错误（可能存在关联数据）", text[:300]))
