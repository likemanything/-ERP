from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantModel
from app.core.types import UTCDateTime


class Shop(TenantModel):
    """店铺（平台账号 + 站点）。"""

    __tablename__ = "shops"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    name: Mapped[str] = mapped_column(String(128))
    platform: Mapped[str] = mapped_column(String(32), index=True)
    marketplace_code: Mapped[str | None] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(16))
    region: Mapped[str | None] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    seller_id: Mapped[str | None] = mapped_column(String(64), doc="平台卖家 ID / Merchant Token")
    store_domain: Mapped[str | None] = mapped_column(String(255), doc="独立站域名，如 xxx.myshopify.com")
    credentials_enc: Mapped[str | None] = mapped_column(Text, doc="加密后的授权凭证")
    status: Mapped[str] = mapped_column(String(16), default="active")
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    last_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_sync_status: Mapped[str | None] = mapped_column(String(16))
    last_sync_message: Mapped[str | None] = mapped_column(String(500))
    manager_id: Mapped[int | None] = mapped_column(BigInteger, doc="店铺负责人")
    remark: Mapped[str | None] = mapped_column(String(500))
