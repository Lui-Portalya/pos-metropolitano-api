from fastapi import APIRouter

from app.deps import AdminUser, AnyUser, Db
from app.schemas import SettingsIn, SettingsOut
from app.services import settings as settings_service

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("", response_model=SettingsOut)
def get_settings(_: AnyUser, db: Db) -> dict:
    return settings_service.get_settings(db)


@router.put("", response_model=SettingsOut)
def put_settings(body: SettingsIn, _: AdminUser, db: Db) -> dict:
    return settings_service.update_settings(
        db,
        store_name=body.store_name,
        tax_rate_percent=body.tax_rate_percent,
        receipt_footer=body.receipt_footer,
    )
