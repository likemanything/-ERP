from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field, field_validator

from app.common.schemas import ORMOut, Schema
from app.core.types import Money


class LoginIn(Schema):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RefreshIn(Schema):
    refresh_token: str


class RegisterIn(Schema):
    company_name: str = Field(min_length=2, max_length=128)
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=6, max_length=128)
    real_name: str = Field(default="", max_length=64)
    phone: str | None = None
    base_currency: str = "CNY"


class ChangePasswordIn(Schema):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)


class TenantOut(ORMOut):
    code: str
    name: str
    base_currency: str
    timezone: str
    contact_name: str | None = None
    contact_phone: str | None = None


class TenantUpdate(Schema):
    name: str | None = None
    base_currency: str | None = None
    timezone: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None


class RoleBrief(Schema):
    id: int
    code: str
    name: str


class UserOut(ORMOut):
    username: str
    real_name: str
    email: str | None = None
    phone: str | None = None
    dept_id: int | None = None
    is_active: bool
    is_superuser: bool
    all_shops: bool
    last_login_at: datetime | None = None
    roles: list[RoleBrief] = []
    shop_ids: list[int] = []


class UserCreate(Schema):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=6, max_length=128)
    real_name: str = ""
    email: str | None = None
    phone: str | None = None
    dept_id: int | None = None
    is_active: bool = True
    is_superuser: bool = False
    all_shops: bool = True
    role_ids: list[int] = []
    shop_ids: list[int] = []


class UserUpdate(Schema):
    real_name: str | None = None
    email: str | None = None
    phone: str | None = None
    dept_id: int | None = None
    is_active: bool | None = None
    is_superuser: bool | None = None
    all_shops: bool | None = None
    role_ids: list[int] | None = None
    shop_ids: list[int] | None = None


class ResetPasswordIn(Schema):
    password: str = Field(min_length=6, max_length=128)


class MeOut(Schema):
    user: UserOut
    tenant: TenantOut
    permissions: list[str]


class TokenOut(Schema):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut | None = None


class RoleOut(ORMOut):
    code: str
    name: str
    description: str | None = None
    permissions: list[str] = []
    is_system: bool = False


class RoleIn(Schema):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    description: str | None = None
    permissions: list[str] = []


class RoleUpdate(Schema):
    name: str | None = None
    description: str | None = None
    permissions: list[str] | None = None


class DepartmentOut(ORMOut):
    name: str
    parent_id: int | None = None
    sort: int = 0
    leader_id: int | None = None


class DepartmentIn(Schema):
    name: str = Field(min_length=1, max_length=64)
    parent_id: int | None = None
    sort: int = 0
    leader_id: int | None = None


class DepartmentUpdate(Schema):
    name: str | None = None
    parent_id: int | None = None
    sort: int | None = None
    leader_id: int | None = None


class AuditLogOut(ORMOut):
    user_id: int | None = None
    username: str | None = None
    action: str
    resource: str
    resource_id: str | None = None
    summary: str | None = None
    detail: dict | None = None
    ip: str | None = None


class ExchangeRateOut(ORMOut):
    currency: str
    month: str
    rate: Money
    remark: str | None = None


class ExchangeRateIn(Schema):
    currency: str = Field(min_length=3, max_length=8)
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    rate: Decimal = Field(gt=0)
    remark: str | None = None

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


class ExchangeRateUpdate(Schema):
    rate: Decimal | None = Field(default=None, gt=0)
    remark: str | None = None


class SettingItem(Schema):
    key: str
    value: Any = None
    label: str | None = None
    description: str | None = None


class SettingsUpdate(Schema):
    values: dict[str, Any]


class NotificationOut(ORMOut):
    category: str
    title: str
    content: str | None = None
    link: str | None = None
    is_read: bool
