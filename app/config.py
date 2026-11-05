from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

API_PREFIX = "/api/v1"
SESSION_COOKIE = "pos_session"
SESSION_DAYS = 7


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables / `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    # SQLite file shared with the Node app. POS_DB_PATH is the variable the Node app
    # uses, so the same value works for both; DATABASE_PATH is accepted as an alias.
    database_path: str = Field(
        "data/pos.db", validation_alias=AliasChoices("POS_DB_PATH", "DATABASE_PATH")
    )
    # Same flag the web app uses for the `Secure` attribute of the session cookie.
    cookie_secure: bool = False
    # Comma-separated list of allowed browser origins (web app). Empty = no CORS.
    cors_origins: str = ""
    # First-run users (admin, cashier, kitchen/cook), only created when the users table is empty.
    seed_admin_username: str = "admin"
    seed_admin_password: str = "admin123"
    seed_admin_name: str = "Administrator"
    seed_cashier_username: str = "cashier"
    seed_cashier_password: str = "cashier123"
    seed_cashier_name: str = "Cashier"
    seed_cook_username: str = "kitchen"
    seed_cook_password: str = "kitchen123"
    seed_cook_name: str = "Kitchen"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
