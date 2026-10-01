from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import TenantModel
from app.core.types import MoneyColumn, RateColumn, UTCDateTime


class PurchasePlan(TenantModel):
    """采购计划：由运营/补货建议生成，采购员合并转为采购单。"""

    __tablename__ = "purchase_plans"
    __table_args__ = (UniqueConstraint("tenant_id", "plan_no"),)

    plan_no: Mapped[str] = mapped_column(String(32))
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), index=True)
    supplier_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("suppliers.id"))
    warehouse_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("warehouses.id"))
    shop_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("shops.id"))
    listing_id: Mapped[int | None] = mapped_column(BigInteger)
    qty: Mapped[int] = mapped_column(Integer)
    expected_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    source: Mapped[str] = mapped_column(String(16), default="manual", doc="manual/replenishment")
    purchaser_id: Mapped[int | None] = mapped_column(BigInteger)
    purchase_order_id: Mapped[int | None] = mapped_column(BigInteger)
    remark: Mapped[str | None] = mapped_column(String(500))


class PurchaseOrder(TenantModel):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("tenant_id", "po_no"),)

    po_no: Mapped[str] = mapped_column(String(32))
    supplier_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("suppliers.id"), index=True)
    warehouse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("warehouses.id"), index=True)
    purchaser_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    exchange_rate: Mapped[Decimal] = mapped_column(RateColumn, default=1, doc="下单时 1 单位币种 = ? 本位币")
    order_date: Mapped[date | None] = mapped_column(Date)
    expected_date: Mapped[date | None] = mapped_column(Date)
    goods_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    shipping_fee: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="运费（分摊进入库成本）")
    other_fee: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    discount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    total_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    paid_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    requested_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="已请款金额（含审批中）")
    returned_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    payment_status: Mapped[str] = mapped_column(String(16), default="unpaid")
    settlement_type: Mapped[str | None] = mapped_column(String(16))
    supplier_order_no: Mapped[str | None] = mapped_column(String(64), doc="供应商/1688 订单号")
    tracking_no: Mapped[str | None] = mapped_column(String(128), doc="供应商发货物流单号")
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    approved_by: Mapped[int | None] = mapped_column(BigInteger)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reject_reason: Mapped[str | None] = mapped_column(String(255))
    remark: Mapped[str | None] = mapped_column(String(500))

    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin", order_by="PurchaseOrderLine.id"
    )


class PurchaseOrderLine(TenantModel):
    __tablename__ = "purchase_order_lines"

    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), index=True)
    plan_id: Mapped[int | None] = mapped_column(BigInteger)
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="含税单价（采购币种）")
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    qty_received: Mapped[int] = mapped_column(Integer, default=0, doc="已到货（良品+次品）")
    qty_good: Mapped[int] = mapped_column(Integer, default=0)
    qty_defective: Mapped[int] = mapped_column(Integer, default=0)
    qty_returned: Mapped[int] = mapped_column(Integer, default=0)
    expected_date: Mapped[date | None] = mapped_column(Date)
    remark: Mapped[str | None] = mapped_column(String(255))

    order: Mapped[PurchaseOrder] = relationship(back_populates="lines")

    @property
    def qty_pending(self) -> int:
        return max(0, (self.qty or 0) - (self.qty_received or 0))


class PurchaseReceipt(TenantModel):
    """到货/质检入库单。"""

    __tablename__ = "purchase_receipts"
    __table_args__ = (UniqueConstraint("tenant_id", "receipt_no"),)

    receipt_no: Mapped[str] = mapped_column(String(32))
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("purchase_orders.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("suppliers.id"))
    warehouse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("warehouses.id"))
    status: Mapped[str] = mapped_column(String(16), default="completed")
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    tracking_no: Mapped[str | None] = mapped_column(String(128))
    remark: Mapped[str | None] = mapped_column(String(500))

    lines: Mapped[list["PurchaseReceiptLine"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan", lazy="selectin", order_by="PurchaseReceiptLine.id"
    )


class PurchaseReceiptLine(TenantModel):
    __tablename__ = "purchase_receipt_lines"

    receipt_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("purchase_receipts.id", ondelete="CASCADE"), index=True)
    order_line_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("purchase_order_lines.id"))
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"))
    qty_good: Mapped[int] = mapped_column(Integer, default=0)
    qty_defective: Mapped[int] = mapped_column(Integer, default=0)
    unit_purchase_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="入库单位采购成本（本位币）")
    unit_freight_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="分摊运杂费（本位币）")
    batch_no: Mapped[str | None] = mapped_column(String(64))

    receipt: Mapped[PurchaseReceipt] = relationship(back_populates="lines")


class PurchaseReturn(TenantModel):
    """采购退货。"""

    __tablename__ = "purchase_returns"
    __table_args__ = (UniqueConstraint("tenant_id", "return_no"),)

    return_no: Mapped[str] = mapped_column(String(32))
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("purchase_orders.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("suppliers.id"))
    warehouse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("warehouses.id"))
    stock_type: Mapped[str] = mapped_column(String(16), default="defective")
    status: Mapped[str] = mapped_column(String(16), default="completed")
    refund_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="退款金额（采购币种）")
    reason: Mapped[str | None] = mapped_column(String(255))
    remark: Mapped[str | None] = mapped_column(String(500))

    lines: Mapped[list["PurchaseReturnLine"]] = relationship(
        back_populates="ret", cascade="all, delete-orphan", lazy="selectin", order_by="PurchaseReturnLine.id"
    )


class PurchaseReturnLine(TenantModel):
    __tablename__ = "purchase_return_lines"

    return_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("purchase_returns.id", ondelete="CASCADE"), index=True)
    order_line_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("purchase_order_lines.id"))
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)

    ret: Mapped[PurchaseReturn] = relationship(back_populates="lines")


class PaymentRequest(TenantModel):
    """请款单（采购付款）。"""

    __tablename__ = "payment_requests"
    __table_args__ = (UniqueConstraint("tenant_id", "request_no"),)

    request_no: Mapped[str] = mapped_column(String(32))
    supplier_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("suppliers.id"), index=True)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    pay_type: Mapped[str] = mapped_column(String(16), default="balance", doc="prepay 预付款 / balance 尾款 / full 全款")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    payment_method: Mapped[str | None] = mapped_column(String(32), doc="银行转账/支付宝/1688 等")
    payee_account: Mapped[str | None] = mapped_column(String(128))
    transaction_no: Mapped[str | None] = mapped_column(String(64))
    approved_by: Mapped[int | None] = mapped_column(BigInteger)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    paid_by: Mapped[int | None] = mapped_column(BigInteger)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reject_reason: Mapped[str | None] = mapped_column(String(255))
    remark: Mapped[str | None] = mapped_column(String(500))

    lines: Mapped[list["PaymentRequestLine"]] = relationship(
        back_populates="request", cascade="all, delete-orphan", lazy="selectin"
    )


class PaymentRequestLine(TenantModel):
    __tablename__ = "payment_request_lines"

    request_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("payment_requests.id", ondelete="CASCADE"), index=True)
    purchase_order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("purchase_orders.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)

    request: Mapped[PaymentRequest] = relationship(back_populates="lines")
