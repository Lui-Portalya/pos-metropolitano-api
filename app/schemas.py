from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from pydantic.alias_generators import to_camel

Role = Literal["admin", "cashier", "cook"]
Home = Literal["/", "/kitchen"]


class CamelModel(BaseModel):
    """JSON is camelCase on the wire, snake_case in Python."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


def _strip(v: object) -> object:
    return v.strip() if isinstance(v, str) else v


# ---- shared shapes -------------------------------------------------------


class UserOut(CamelModel):
    id: int
    username: str
    name: str
    role: Role
    active: bool


# ---- auth ------------------------------------------------------------------


class LoginRequest(CamelModel):
    username: str
    password: str

    @field_validator("username", mode="before")
    @classmethod
    def _trim(cls, v: object) -> object:
        return _strip(v)

    @field_validator("username", "password")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("required")
        return v


class LoginResponse(CamelModel):
    token: str
    expires_at: str
    user: UserOut
    home: Home


class MeResponse(CamelModel):
    user: UserOut
    store_name: str
    home: Home
    allowed_modules: list[str]


# ---- settings --------------------------------------------------------------


class SettingsOut(CamelModel):
    store_name: str
    tax_rate_percent: float
    receipt_footer: str


class SettingsIn(CamelModel):
    store_name: str
    tax_rate_percent: Annotated[float, Field(strict=True, ge=0, le=100, allow_inf_nan=False)]
    receipt_footer: str

    @field_validator("store_name", "receipt_footer", mode="before")
    @classmethod
    def _trim(cls, v: object) -> object:
        return _strip(v)

    @field_validator("store_name")
    @classmethod
    def _store_name(cls, v: str) -> str:
        if not 1 <= len(v) <= 60:
            raise ValueError("Store name must be 1-60 characters")
        return v

    @field_validator("receipt_footer")
    @classmethod
    def _footer(cls, v: str) -> str:
        if len(v) > 120:
            raise ValueError("Receipt footer must be at most 120 characters")
        return v


# ---- users -----------------------------------------------------------------


class CreateUserRequest(CamelModel):
    username: str
    name: str
    password: str
    role: Role

    @field_validator("username", "name", mode="before")
    @classmethod
    def _trim(cls, v: object) -> object:
        return _strip(v)

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        if not 3 <= len(v) <= 32:
            raise ValueError("Username must be 3-32 characters")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not 1 <= len(v) <= 60:
            raise ValueError("Name must be 1-60 characters")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return validate_password(v)


def validate_password(v: str) -> str:
    if len(v) < 6:
        raise ValueError("Password must be at least 6 characters")
    return v


class SetActiveRequest(CamelModel):
    active: StrictBool


class ResetPasswordRequest(CamelModel):
    password: str

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return validate_password(v)


class UserResponse(CamelModel):
    user: UserOut


class UsersResponse(CamelModel):
    users: list[UserOut]


class OkResponse(CamelModel):
    ok: bool = True
