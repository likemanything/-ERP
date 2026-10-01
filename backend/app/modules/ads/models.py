from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Date, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantModel
from app.core.types import MoneyColumn


class AdCampaign(TenantModel):
    __tablename__ = "ad_campaigns"
    __table_args__ = (UniqueConstraint("tenant_id", "shop_id", "campaign_id"),)

    shop_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shops.id"), index=True)
    campaign_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    ad_type: Mapped[str] = mapped_column(String(8), default="SP", doc="SP/SB/SD")
    state: Mapped[str] = mapped_column(String(16), default="enabled")
    targeting_type: Mapped[str | None] = mapped_column(String(16), doc="auto/manual")
    daily_budget: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)


class AdMetricDaily(TenantModel):
    """广告日报（按 活动 / 广告组 / 广告商品 维度）。"""

    __tablename__ = "ad_metrics_daily"
    __table_args__ = (
        UniqueConstraint("tenant_id", "shop_id", "metric_date", "campaign_id", "ad_group", "msku"),
        Index("ix_ad_metrics_shop_date", "shop_id", "metric_date"),
    )

    shop_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shops.id"))
    metric_date: Mapped[date] = mapped_column(Date)
    campaign_id: Mapped[str] = mapped_column(String(64))
    campaign_name: Mapped[str | None] = mapped_column(String(255))
    ad_group: Mapped[str] = mapped_column(String(255), default="")
    ad_type: Mapped[str] = mapped_column(String(8), default="SP")
    msku: Mapped[str] = mapped_column(String(128), default="")
    asin: Mapped[str | None] = mapped_column(String(64))
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    spend: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    sales: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    orders: Mapped[int] = mapped_column(Integer, default=0)
    units: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
