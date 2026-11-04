from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import API_PREFIX


class ApiError(Exception):
    """Raise anywhere; rendered as `{"error": message}` with the given status."""

    def __init__(self, status_code: int, message: str, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.headers = headers


def unauthorized() -> ApiError:
    return ApiError(401, "Unauthorized", {"WWW-Authenticate": "Bearer"})


def forbidden() -> ApiError:
    return ApiError(403, "Forbidden")


# Endpoints whose spec mandates one fixed 422 message regardless of which field failed.
FIXED_422 = {
    ("POST", f"{API_PREFIX}/auth/login"): "Enter your username and password.",
    ("PUT", f"{API_PREFIX}/settings"): "Check the settings values.",
}


def _first_message(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Invalid request."
    err = errors[0]
    field = ".".join(str(p) for p in err["loc"] if p not in ("body", "query", "path"))
    ctx_error = (err.get("ctx") or {}).get("error")
    if err["type"] == "value_error" and ctx_error is not None:
        return str(ctx_error)
    if err["type"] == "missing":
        return f"{field} is required." if field else "Request body is required."
    return f"Invalid value for {field}." if field else "Invalid request."


def _json(status: int, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status, headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _json(exc.status_code, exc.message, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fixed = FIXED_422.get((request.method, request.url.path))
        return _json(422, fixed or _first_message(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _json(exc.status_code, str(exc.detail), getattr(exc, "headers", None))
