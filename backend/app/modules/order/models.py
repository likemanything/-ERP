from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import TenantModel
from app.core.types import MoneyColumn, UTCDateTime


class SalesOrder(TenantModel):
    """多平台统一订单。金额字段为订单币种，成本字段为本位币。"""

    __tablename__ = "sales_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "shop_id", "platform_order_id"),
        Index("ix_sales_orders_shop_date", "shop_id", "local_date"),
    )

    order_no: Mapped[str] = mapped_column(String(32), index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shops.id"), index=True)
    platform: Mapped[str] = mapped_column(String(32))
    platform_order_id: Mapped[str] = mapped_column(String(64))
    fulfillment: Mapped[str] = mapped_column(String(8), default="FBM", index=True)
    status: Mapped[str] = mapped_column(String(16), default="to_audit", index=True)
    platform_status: Mapped[str | None] = mapped_column(String(32))
    is_on_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    hold_reason: Mapped[str | None] = mapped_column(String(255))
    tags: Mapped[list | None] = mapped_column(JSON)

    purchase_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    local_date: Mapped[date] = mapped_column(Date, index=True, doc="站点当地日期，用于报表统计")
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    latest_ship_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    shipped_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    audited_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    audited_by: Mapped[int | None] = mapped_column(BigInteger)

    buyer_name: Mapped[str | None] = mapped_column(String(128))
    buyer_email: Mapped[str | None] = mapped_column(String(128))
    ship_name: Mapped[str | None] = mapped_column(String(128))
    ship_phone: Mapped[str | None] = mapped_column(String(64))
    ship_country: Mapped[str | None] = mapped_column(String(8))
    ship_state: Mapped[str | None] = mapped_column(String(64))
    ship_city: Mapped[str | None] = mapped_column(String(64))
    ship_address1: Mapped[str | None] = mapped_column(String(255))
    ship_address2: Mapped[str | None] = mapped_column(String(255))
    ship_postcode: Mapped[str | None] = mapped_column(String(32))

    currency: Mapped[str] = mapped_column(String(8), default="USD")
    item_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="商品金额")
    shipping_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="买家支付运费")
    tax_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    discount_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="促销折扣")
    total_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)

    warehouse_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("warehouses.id"))
    logistics_channel_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("logistics_channels.id"))
    carrier: Mapped[str | None] = mapped_column(String(64))
    tracking_no: Mapped[str | None] = mapped_column(String(128))
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    est_freight: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="预估运费（本位币）")
    actual_freight: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="实际运费（本位币，计入利润）")

    buyer_note: Mapped[str | None] = mapped_column(String(500))
    remark: Mapped[str | None] = mapped_column(String(500))
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    stock_plan: Mapped[list | None] = mapped_column(JSON, doc="审核时锁定的库存明细 [{item_id, product_id, qty}]")
    distributor_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("distributors.id"), index=True, doc="分销订单所属分销商")
    distribution_type: Mapped[str | None] = mapped_column(String(16), doc="dropship 一件代发 / wholesale 批发")
    charge_detail: Mapped[dict | None] = mapped_column(JSON, doc="分销扣费明细 {goods, freight, handling, adjust, total, currency}")

    items: Mapped[list["SalesOrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin", order_by="SalesOrderItem.id"
    )


class SalesOrderItem(TenantModel):
    __tablename__ = "sales_order_items"
    __table_args__ = (Index("ix_sales_order_items_shop_msku", "shop_id", "msku"),)

    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sales_orders.id", ondelete="CASCADE"), index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, index=True)
    platform_item_id: Mapped[str | None] = mapped_column(String(64), doc="平台订单行 ID")
    listing_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    msku: Mapped[str] = mapped_column(String(128))
    asin: Mapped[str | None] = mapped_column(String(64))
    product_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("products.id"), index=True)
    sku: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(500))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    quantity_shipped: Mapped[int] = mapped_column(Integer, default=0)
    unit_price: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    item_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    shipping_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    tax_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    discount_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    commission_fee: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="平台佣金（正数）")
    fulfillment_fee: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="FBA 配送费（正数）")
    other_fee: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    fee_estimated: Mapped[bool] = mapped_column(Boolean, default=True, doc="费用是否为预估值（结算后更新）")
    refund_qty: Mapped[int] = mapped_column(Integer, default=0)
    refund_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    cost_purchase: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="采购成本合计（本位币）")
    cost_freight: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="头程成本合计（本位币）")
    cost_settled: Mapped[bool] = mapped_column(Boolean, default=False, doc="是否已按出库批次核算成本")

    order: Mapped[SalesOrder] = relationship(back_populates="items")


class ReturnOrder(TenantModel):
    """销售退货 / 退款。"""

    __tablename__ = "return_orders"
    __table_args__ = (UniqueConstraint("tenant_id", "return_no"),)

    return_no: Mapped[str] = mapped_column(String(32))
    order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("sales_orders.id"), index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shops.id"), index=True)
    platform_return_id: Mapped[str | None] = mapped_column(String(64))
    return_type: Mapped[str] = mapped_column(String(16), default="return_refund", doc="refund_only 仅退款 / return_refund 退货退款")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    reason: Mapped[str | None] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    refund_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    return_date: Mapped[date] = mapped_column(Date, index=True)
    warehouse_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("warehouses.id"), doc="退货入库仓")
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    restock_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="退回良品重新入库的成本（本位币），冲减销售成本")
    remark: Mapped[str | None] = mapped_column(String(500))

    lines: Mapped[list["ReturnOrderLine"]] = relationship(
        back_populates="ret", cascade="all, delete-orphan", lazy="selectin"
    )


class ReturnOrderLine(TenantModel):
    __tablename__ = "return_order_lines"

    return_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("return_orders.id", ondelete="CASCADE"), index=True)
    order_item_id: Mapped[int | None] = mapped_column(BigInteger)
    product_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("products.id"))
    msku: Mapped[str | None] = mapped_column(String(128))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    refund_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    qty_good: Mapped[int] = mapped_column(Integer, default=0, doc="退回良品入库数")
    qty_defective: Mapped[int] = mapped_column(Integer, default=0, doc="退回次品入库数")

    ret: Mapped[ReturnOrder] = relationship(back_populates="lines")
