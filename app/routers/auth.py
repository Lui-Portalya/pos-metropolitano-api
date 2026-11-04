from fastapi import APIRouter, Response

from app.config import SESSION_COOKIE
from app.deps import AnyUser, AppSettings, Db
from app.errors import ApiError
from app.schemas import LoginRequest, LoginResponse, MeResponse
from app.services import sessions
from app.services import settings as settings_service
from app.services import users as users_service

router = APIRouter(prefix="/auth", tags=["Auth & Session"])

ALL_MODULES = ["sell", "kitchen", "prepare", "sales", "summary", "menu", "restock", "admin"]
_ROLE_MODULES = {
    "admin": set(ALL_MODULES),
    "cashier": {"sell", "kitchen", "prepare", "sales", "summary"},
    "cook": {"kitchen", "prepare"},
}


def home_for(role: str) -> str:
    return "/kitchen" if role == "cook" else "/"


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, response: Response, db: Db, cfg: AppSettings) -> LoginResponse:
    user = users_service.verify_credentials(db, body.username, body.password)
    if user is None:
        raise ApiError(401, "Incorrect username or password.")
    token, expires = sessions.create_session(db, user["id"])
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=cfg.cookie_secure,
        path="/",
        expires=expires,
    )
    return LoginResponse(
        token=token,
        expires_at=sessions.iso_utc(expires),
        user=user,
        home=home_for(user["role"]),
    )


@router.post("/logout", status_code=204)
def logout(principal: AnyUser, db: Db, cfg: AppSettings) -> Response:
    sessions.destroy_session(db, principal.token)
    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=cfg.cookie_secure
    )
    return response


@router.get("/me", response_model=MeResponse)
def me(principal: AnyUser, db: Db) -> MeResponse:
    role = principal.user["role"]
    return MeResponse(
        user=principal.user,
        store_name=settings_service.get_settings(db)["store_name"],
        home=home_for(role),
        allowed_modules=[m for m in ALL_MODULES if m in _ROLE_MODULES[role]],
    )
