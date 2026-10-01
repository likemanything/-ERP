"""分销：分销商、等级定价、分销商品目录、资金账户（余额 + 授信）、充值。

分销订单直接落在 sales_orders（每个分销商对应一个 platform=distribution 的虚拟店铺），
复用审核锁库存、FIFO 出库核算成本、发货、退货与利润报表。
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import TenantModel
from app.core.types import MoneyColumn, UTCDateTime


class DistributorLevel(TenantModel):
    """分销等级：在分销基础价上打折，也可为单个商品设置等级价。"""

    __tablename__ = "distributor_levels"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))
    discount_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("1"), doc="1=原价，0.9=九折")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    remark: Mapped[str | None] = mapped_column(String(255))


class Distributor(TenantModel):
    __tablename__ = "distributors"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    contact: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(128))
    country: Mapped[str | None] = mapped_column(String(16))
    address: Mapped[str | None] = mapped_column(String(255))
    level_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("distributor_levels.id"))
    currency: Mapped[str] = mapped_column(String(8), default="CNY", doc="结算币种")
    balance: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="账户余额（可为负，不超过授信额度）")
    credit_limit: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="授信额度")
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    allow_dropship: Mapped[bool] = mapped_column(Boolean, default=True, doc="允许一件代发")
    allow_wholesale: Mapped[bool] = mapped_column(Boolean, default=True, doc="允许批发采购")
    shop_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("shops.id"), doc="对应的分销虚拟店铺")
    sales_rep_id: Mapped[int | None] = mapped_column(BigInteger, doc="对接业务员")
    api_key_prefix: Mapped[str | None] = mapped_column(String(16), index=True)
    api_key_hash: Mapped[str | None] = mapped_column(String(128))
    remark: Mapped[str | None] = mapped_column(String(500))

    level: Mapped[DistributorLevel | None] = relationship(lazy="joined")

    @property
    def available_funds(self) -> Decimal:
        return Decimal(self.balance or 0) + Decimal(self.credit_limit or 0)


class DistributionProduct(TenantModel):
    """分销商品目录（上架给分销商的产品及分销基础价）。"""

    __tablename__ = "distribution_products"
    __table_args__ = (UniqueConstraint("tenant_id", "product_id"),)

    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), index=True)
    base_price: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    min_qty: Mapped[int] = mapped_column(Integer, default=1, doc="批发最小起订量")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, doc="是否上架")
    stock_display: Mapped[str] = mapped_column(String(16), default="real", doc="real 实际 / capped 封顶 / status 仅显示有货无货")
    stock_cap: Mapped[int] = mapped_column(Integer, default=999)
    title: Mapped[str | None] = mapped_column(String(255), doc="分销展示标题（为空取产品名）")
    description: Mapped[str | None] = mapped_column(Text)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class DistributionLevelPrice(TenantModel):
    """商品等级价（优先于等级折扣）。"""

    __tablename__ = "distribution_level_prices"
    __table_args__ = (UniqueConstraint("product_id", "level_id"),)

    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id", ondelete="CASCADE"), index=True)
    level_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("distributor_levels.id", ondelete="CASCADE"), index=True)
    price: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="与分销商品同币种")


class DistributorTransaction(TenantModel):
    """分销商资金流水。amount 带符号：充值/退款为正，扣款为负。"""

    __tablename__ = "distributor_transactions"

    distributor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("distributors.id"), index=True)
    txn_type: Mapped[str] = mapped_column(String(16), index=True, doc="recharge/order/refund/adjust")
    amount: Mapped[Decimal] = mapped_column(MoneyColumn)
    balance_after: Mapped[Decimal] = mapped_column(MoneyColumn)
    currency: Mapped[str] = mapped_column(String(8))
    ref_type: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[int | None] = mapped_column(BigInteger)
    ref_no: Mapped[str | None] = mapped_column(String(64), index=True)
    remark: Mapped[str | None] = mapped_column(String(255))


class RechargeRequest(TenantModel):
    """充值申请（分销商线下打款后提交，财务确认后入账）。"""

    __tablename__ = "distributor_recharges"
    __table_args__ = (UniqueConstraint("tenant_id", "request_no"),)

    request_no: Mapped[str] = mapped_column(String(32))
    distributor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("distributors.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(MoneyColumn)
    currency: Mapped[str] = mapped_column(String(8))
    payment_method: Mapped[str | None] = mapped_column(String(32))
    transaction_no: Mapped[str | None] = mapped_column(String(64))
    proof_url: Mapped[str | None] = mapped_column(String(500), doc="付款凭证链接")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reject_reason: Mapped[str | None] = mapped_column(String(255))
    remark: Mapped[str | None] = mapped_column(String(255))
