from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import BaseModel, TenantModel
from app.core.types import RateColumn, UTCDateTime


class Tenant(BaseModel):
    """企业（租户）。"""

    __tablename__ = "tenants"

    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    base_currency: Mapped[str] = mapped_column(String(8), default="CNY")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    contact_name: Mapped[str | None] = mapped_column(String(64))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    expire_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Department(TenantModel):
    __tablename__ = "departments"

    name: Mapped[str] = mapped_column(String(64))
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("departments.id"))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    leader_id: Mapped[int | None] = mapped_column(BigInteger)


class Role(TenantModel):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(255))
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)


class UserRole(TenantModel):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), index=True)


class UserShop(TenantModel):
    """数据权限：用户可访问的店铺（user.all_shops=False 时生效）。"""

    __tablename__ = "user_shops"
    __table_args__ = (UniqueConstraint("user_id", "shop_id"),)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), index=True)


class User(TenantModel):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    real_name: Mapped[str] = mapped_column(String(64), default="")
    email: Mapped[str | None] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32))
    dept_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("departments.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, doc="企业管理员，拥有全部权限")
    all_shops: Mapped[bool] = mapped_column(Boolean, default=True, doc="是否可访问全部店铺数据")
    token_version: Mapped[int] = mapped_column(Integer, default=0, doc="修改密码/禁用后使旧 token 失效")
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    roles: Mapped[list[Role]] = relationship(secondary="user_roles", lazy="selectin", viewonly=True)
    dept: Mapped[Department | None] = relationship(lazy="joined")


class AuditLog(TenantModel):
    __tablename__ = "audit_logs"

    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[str | None] = mapped_column(String(500))
    detail: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))


class Sequence(TenantModel):
    """单据编号序列，按 前缀+周期 递增。"""

    __tablename__ = "sequences"
    __table_args__ = (UniqueConstraint("tenant_id", "prefix", "period"),)

    prefix: Mapped[str] = mapped_column(String(16))
    period: Mapped[str] = mapped_column(String(16))
    value: Mapped[int] = mapped_column(Integer, default=0)


class SystemSetting(TenantModel):
    __tablename__ = "system_settings"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)

    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)


class ExchangeRate(TenantModel):
    """月度汇率：1 单位 currency = rate 单位本位币。"""

    __tablename__ = "exchange_rates"
    __table_args__ = (UniqueConstraint("tenant_id", "currency", "month"),)

    currency: Mapped[str] = mapped_column(String(8))
    month: Mapped[str] = mapped_column(String(7), doc="YYYY-MM")
    rate: Mapped[float] = mapped_column(RateColumn)
    remark: Mapped[str | None] = mapped_column(Text)


class Notification(TenantModel):
    """站内消息（审批待办、库存预警、同步失败等）。"""

    __tablename__ = "notifications"

    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True, doc="为空表示企业全员可见")
    category: Mapped[str] = mapped_column(String(32), default="system")
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(255))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
