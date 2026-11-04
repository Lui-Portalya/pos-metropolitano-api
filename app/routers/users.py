from fastapi import APIRouter

from app.deps import AdminUser, Db
from app.errors import ApiError
from app.schemas import (
    CreateUserRequest,
    OkResponse,
    ResetPasswordRequest,
    SetActiveRequest,
    UserResponse,
    UsersResponse,
)
from app.services import users as users_service

router = APIRouter(prefix="/users", tags=["Users (admin)"])


@router.get("", response_model=UsersResponse)
def list_users(_: AdminUser, db: Db) -> dict:
    return {"users": users_service.list_users(db)}


@router.post("", response_model=UserResponse, status_code=201)
def create_user(body: CreateUserRequest, _: AdminUser, db: Db) -> dict:
    user = users_service.create_user(
        db, username=body.username, name=body.name, password=body.password, role=body.role
    )
    return {"user": user}


@router.patch("/{user_id}/active", response_model=UserResponse)
def set_active(user_id: int, body: SetActiveRequest, admin: AdminUser, db: Db) -> dict:
    user = users_service.set_user_active(db, admin.user["id"], user_id, body.active)
    return {"user": user}


@router.put("/{user_id}/password", response_model=OkResponse)
def reset_password(user_id: int, body: ResetPasswordRequest, _: AdminUser, db: Db) -> OkResponse:
    users_service.reset_password(db, user_id, body.password)
    return OkResponse()
