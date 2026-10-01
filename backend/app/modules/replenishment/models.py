from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantModel


class ReplenishmentRule(TenantModel):
    """补货参数。listing_id 为空表示企业默认规则；否则为单个 Listing 的个性化规则。"""

    __tablename__ = "replenishment_rules"
    __table_args__ = (UniqueConstraint("tenant_id", "listing_id"),)

    listing_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("listings.id", ondelete="CASCADE"))
    purchase_lead_days: Mapped[int | None] = mapped_column(Integer, doc="采购交期，空则取产品设置")
    inspection_days: Mapped[int] = mapped_column(Integer, default=2, doc="质检/备货处理天数")
    transit_days: Mapped[int] = mapped_column(Integer, default=30, doc="头程时效")
    safety_days: Mapped[int] = mapped_column(Integer, default=15, doc="安全库存天数")
    cover_days: Mapped[int] = mapped_column(Integer, default=30, doc="每次备货可售天数")
    weight_7d: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.5"))
    weight_14d: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.3"))
    weight_30d: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.2"))
    growth_factor: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("1.0"), doc="销量增长系数（旺季可调高）")
    remark: Mapped[str | None] = mapped_column(String(255))
