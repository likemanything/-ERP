from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantModel
from app.core.types import MoneyColumn, UTCDateTime


class PlatformTransaction(TenantModel):
    """平台交易/结算明细（来自 Finances API 或结算报告导入）。

    amount 为带符号金额：收入为正，费用为负。
    """

    __tablename__ = "platform_transactions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "shop_id", "external_id"),
        Index("ix_platform_tx_shop_date", "shop_id", "posted_date"),
    )

    shop_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shops.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(128), doc="去重键")
    settlement_id: Mapped[str | None] = mapped_column(String(64), index=True)
    posted_at: Mapped[datetime] = mapped_column(UTCDateTime)
    posted_date: Mapped[date] = mapped_column(Date)
    event_type: Mapped[str] = mapped_column(String(32), index=True, doc="order/refund/service_fee/adjustment/storage/ads/transfer/other")
    amount_type: Mapped[str] = mapped_column(String(64), doc="Principal/Tax/Shipping/Commission/FBAPerUnitFulfillmentFee/...")
    platform_order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    msku: Mapped[str | None] = mapped_column(String(128))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    description: Mapped[str | None] = mapped_column(String(255))


class Expense(TenantModel):
    """费用单（店铺/公司层面的其他费用，计入利润报表）。"""

    __tablename__ = "expenses"
    __table_args__ = (UniqueConstraint("tenant_id", "expense_no"),)

    expense_no: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(32), index=True, doc="rent/salary/software/marketing/logistics/office/tax/other")
    shop_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("shops.id"), index=True, doc="为空为公司公共费用")
    product_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("products.id"))
    msku: Mapped[str | None] = mapped_column(String(128))
    expense_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    status: Mapped[str] = mapped_column(String(16), default="confirmed")
    description: Mapped[str | None] = mapped_column(String(500))
