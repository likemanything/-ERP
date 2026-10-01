from datetime import date, datetime
from decimal import Decimal

from pydantic import Field

from app.common.schemas import ORMOut, Schema
from app.core.types import Money


# ------------------------------------------------------------------ 采购计划
class PlanIn(Schema):
    product_id: int
    qty: int = Field(gt=0)
    supplier_id: int | None = None
    warehouse_id: int | None = None
    shop_id: int | None = None
    listing_id: int | None = None
    expected_date: date | None = None
    purchaser_id: int | None = None
    source: str = "manual"
    remark: str | None = None


class PlanUpdate(Schema):
    qty: int | None = Field(default=None, gt=0)
    supplier_id: int | None = None
    warehouse_id: int | None = None
    expected_date: date | None = None
    purchaser_id: int | None = None
    remark: str | None = None


class PlanOut(ORMOut):
    plan_no: str
    product_id: int
    sku: str | None = None
    product_name: str | None = None
    image_url: str | None = None
    supplier_id: int | None = None
    supplier_name: str | None = None
    warehouse_id: int | None = None
    warehouse_name: str | None = None
    shop_id: int | None = None
    listing_id: int | None = None
    qty: int
    expected_date: date | None = None
    status: str
    source: str
    purchaser_id: int | None = None
    purchase_order_id: int | None = None
    po_no: str | None = None
    remark: str | None = None
    created_by: int | None = None


class PlanToOrderIn(Schema):
    plan_ids: list[int] = Field(min_length=1)
    warehouse_id: int | None = Field(default=None, description="收货仓，为空取计划上的仓库或默认仓")


# ------------------------------------------------------------------ 采购单
class POLineIn(Schema):
    product_id: int
    qty: int = Field(gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0, description="为空取供应商报价/参考成本")
    expected_date: date | None = None
    remark: str | None = None


class POIn(Schema):
    supplier_id: int
    warehouse_id: int
    purchaser_id: int | None = None
    currency: str | None = None
    order_date: date | None = None
    expected_date: date | None = None
    shipping_fee: Decimal = Field(default=Decimal(0), ge=0)
    other_fee: Decimal = Field(default=Decimal(0), ge=0)
    discount: Decimal = Field(default=Decimal(0), ge=0)
    settlement_type: str | None = None
    supplier_order_no: str | None = None
    tracking_no: str | None = None
    remark: str | None = None
    lines: list[POLineIn] = Field(min_length=1)


class POUpdate(Schema):
    supplier_id: int | None = None
    warehouse_id: int | None = None
    purchaser_id: int | None = None
    currency: str | None = None
    order_date: date | None = None
    expected_date: date | None = None
    shipping_fee: Decimal | None = Field(default=None, ge=0)
    other_fee: Decimal | None = Field(default=None, ge=0)
    discount: Decimal | None = Field(default=None, ge=0)
    settlement_type: str | None = None
    supplier_order_no: str | None = None
    tracking_no: str | None = None
    remark: str | None = None
    lines: list[POLineIn] | None = None


class POLineOut(Schema):
    id: int
    product_id: int
    sku: str | None = None
    product_name: str | None = None
    image_url: str | None = None
    plan_id: int | None = None
    qty: int
    unit_price: Money
    amount: Money
    qty_received: int
    qty_good: int
    qty_defective: int
    qty_returned: int
    qty_pending: int
    expected_date: date | None = None
    remark: str | None = None


class POOut(ORMOut):
    po_no: str
    supplier_id: int
    supplier_name: str | None = None
    warehouse_id: int
    warehouse_name: str | None = None
    purchaser_id: int | None = None
    status: str
    currency: str
    exchange_rate: Money
    order_date: date | None = None
    expected_date: date | None = None
    goods_amount: Money
    shipping_fee: Money
    other_fee: Money
    discount: Money
    total_amount: Money
    paid_amount: Money
    requested_amount: Money
    returned_amount: Money
    payment_status: str
    settlement_type: str | None = None
    supplier_order_no: str | None = None
    tracking_no: str | None = None
    submitted_at: datetime | None = None
    approved_by: int | None = None
    approved_at: datetime | None = None
    reject_reason: str | None = None
    remark: str | None = None
    created_by: int | None = None
    total_qty: int = 0
    received_qty: int = 0
    lines: list[POLineOut] = []


class RejectIn(Schema):
    reason: str = Field(min_length=1, max_length=255)


class MarkOrderedIn(Schema):
    supplier_order_no: str | None = None
    order_date: date | None = None
    expected_date: date | None = None
    tracking_no: str | None = None


class ReceiveLineIn(Schema):
    order_line_id: int
    qty_good: int = Field(default=0, ge=0)
    qty_defective: int = Field(default=0, ge=0)


class ReceiveIn(Schema):
    lines: list[ReceiveLineIn] = Field(min_length=1)
    tracking_no: str | None = None
    remark: str | None = None


class ReceiptLineOut(Schema):
    id: int
    order_line_id: int
    product_id: int
    sku: str | None = None
    product_name: str | None = None
    qty_good: int
    qty_defective: int
    unit_purchase_cost: Money | None = None
    unit_freight_cost: Money | None = None
    batch_no: str | None = None


class ReceiptOut(ORMOut):
    receipt_no: str
    order_id: int
    po_no: str | None = None
    supplier_id: int
    supplier_name: str | None = None
    warehouse_id: int
    warehouse_name: str | None = None
    status: str
    received_at: datetime | None = None
    tracking_no: str | None = None
    remark: str | None = None
    created_by: int | None = None
    lines: list[ReceiptLineOut] = []


class ReturnLineIn(Schema):
    order_line_id: int
    qty: int = Field(gt=0)


class ReturnIn(Schema):
    order_id: int
    stock_type: str = "defective"
    refund_amount: Decimal | None = Field(default=None, ge=0, description="为空按 数量×单价 计算")
    reason: str | None = None
    remark: str | None = None
    lines: list[ReturnLineIn] = Field(min_length=1)


class ReturnLineOut(Schema):
    id: int
    order_line_id: int
    product_id: int
    sku: str | None = None
    product_name: str | None = None
    qty: int
    unit_price: Money


class ReturnOut(ORMOut):
    return_no: str
    order_id: int
    po_no: str | None = None
    supplier_id: int
    supplier_name: str | None = None
    warehouse_id: int
    stock_type: str
    status: str
    refund_amount: Money
    reason: str | None = None
    remark: str | None = None
    created_by: int | None = None
    lines: list[ReturnLineOut] = []


# ------------------------------------------------------------------ 请款付款
class PaymentLineIn(Schema):
    purchase_order_id: int
    amount: Decimal = Field(gt=0)


class PaymentRequestIn(Schema):
    supplier_id: int
    pay_type: str = "balance"
    payment_method: str | None = None
    payee_account: str | None = None
    remark: str | None = None
    lines: list[PaymentLineIn] = Field(min_length=1)


class PayIn(Schema):
    transaction_no: str | None = None
    payment_method: str | None = None
    paid_at: datetime | None = None


class PaymentLineOut(Schema):
    id: int
    purchase_order_id: int
    po_no: str | None = None
    amount: Money


class PaymentRequestOut(ORMOut):
    request_no: str
    supplier_id: int
    supplier_name: str | None = None
    currency: str
    amount: Money
    pay_type: str
    status: str
    payment_method: str | None = None
    payee_account: str | None = None
    transaction_no: str | None = None
    approved_by: int | None = None
    approved_at: datetime | None = None
    paid_by: int | None = None
    paid_at: datetime | None = None
    reject_reason: str | None = None
    remark: str | None = None
    created_by: int | None = None
    lines: list[PaymentLineOut] = []


class PayableRow(Schema):
    supplier_id: int
    supplier_name: str | None = None
    currency: str
    order_count: int
    total_amount: Money
    received_value: Money
    returned_amount: Money
    paid_amount: Money
    requested_amount: Money
    unpaid_amount: Money
    payable_now: Money
