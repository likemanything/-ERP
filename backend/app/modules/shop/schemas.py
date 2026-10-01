from datetime import datetime

from pydantic import Field

from app.common.schemas import ORMOut, Schema


class ShopOut(ORMOut):
    name: str
    platform: str
    marketplace_code: str | None = None
    country: str | None = None
    region: str | None = None
    currency: str
    timezone: str
    seller_id: str | None = None
    store_domain: str | None = None
    status: str
    sync_enabled: bool
    sync_interval_minutes: int
    last_sync_at: datetime | None = None
    last_sync_status: str | None = None
    last_sync_message: str | None = None
    manager_id: int | None = None
    remark: str | None = None
    has_credentials: bool = False
    credential_keys: list[str] = []


class ShopIn(Schema):
    name: str = Field(min_length=1, max_length=128)
    platform: str
    marketplace_code: str | None = None
    currency: str | None = None
    timezone: str | None = None
    seller_id: str | None = None
    store_domain: str | None = None
    credentials: dict[str, str] | None = Field(default=None, description="平台授权凭证，如 SP-API refresh_token")
    status: str = "active"
    sync_enabled: bool = False
    sync_interval_minutes: int = Field(default=60, ge=10, le=1440)
    manager_id: int | None = None
    remark: str | None = None


class ShopUpdate(Schema):
    name: str | None = None
    marketplace_code: str | None = None
    currency: str | None = None
    timezone: str | None = None
    seller_id: str | None = None
    store_domain: str | None = None
    credentials: dict[str, str] | None = None
    status: str | None = None
    sync_enabled: bool | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=10, le=1440)
    manager_id: int | None = None
    remark: str | None = None
