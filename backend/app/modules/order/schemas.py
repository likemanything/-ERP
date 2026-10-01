from datetime import date, datetime
from decimal import Decimal

from pydantic import Field

from app.common.schemas import ORMOut, Schema
from app.core.types import Money


class OrderItemOut(Schema):
    id: int
    platform_item_id: str | None = None
    listing_id: int | None = None
    msku: str
    asin: str | None = None
    product_id: int | None = None
    sku: str | None = None
    title: str | None = None
    image_url: str | None = None
    quantity: int
    quantity_shipped: int
    unit_price: Money
    item_amount: Money
    shipping_amount: Money
    tax_amount: Money
    discount_amount: Money
    commission_fee: Money
    fulfillment_fee: Money
    other_fee: Money
    fee_estimated: bool
    refund_qty: int
    refund_amount: Money
    cost_purchase: Money | None = None
    cost_freight: Money | None = None
    cost_settled: bool


class OrderOut(ORMOut):
    order_no: str
    shop_id: int
    shop_name: str | None = None
    platform: str
    platform_order_id: str
    fulfillment: str
    status: str
    platform_status: str | None = None
    is_on_hold: bool
    hold_reason: str | None = None
    tags: list | None = None
    purchase_at: datetime
    local_date: date
    paid_at: datetime | None = None
    latest_ship_at: datetime | None = None
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None
    audited_at: datetime | None = None
    buyer_name: str | None = None
    buyer_email: str | None = None
    ship_name: str | None = None
    ship_phone: str | None = None
    ship_country: str | None = None
    ship_state: str | None = None
    ship_city: str | None = None
    ship_address1: str | None = None
    ship_address2: str | None = None
    ship_postcode: str | None = None
    currency: str
    item_amount: Money
    shipping_amount: Money
    tax_amount: Money
    discount_amount: Money
    total_amount: Money
    warehouse_id: int | None = None
    warehouse_name: str | None = None
    logistics_channel_id: int | None = None
    logistics_channel_name: str | None = None
    carrier: str | None = None
    tracking_no: str | None = None
    weight_kg: Money
    est_freight: Money
    actual_freight: Money
    buyer_note: str | None = None
    remark: str | None = None
    cancel_reason: str | None = None
    has_unpaired: bool = False
    est_profit: Money | None = None
    items: list[OrderItemOut] = []


class OrderItemIn(Schema):
    msku: str | None = None
    product_id: int | None = None
    quantity: int = Field(default=1, ge=1)
    unit_price: Decimal = Field(default=Decimal(0), ge=0)
    shipping_amount: Decimal = Decimal(0)
    tax_amount: Decimal = Decimal(0)
    discount_amount: Decimal = Decimal(0)
    title: str | None = None


class OrderIn(Schema):
    shop_id: int
    platform_order_id: str | None = Field(default=None, description="为空自动生成")
    fulfillment: str = "FBM"
    purchase_at: datetime | None = None
    currency: str | None = None
    buyer_name: str | None = None
    buyer_email: str | None = None
    ship_name: str | None = None
    ship_phone: str | None = None
    ship_country: str | None = None
    ship_state: str | None = None
    ship_city: str | None = None
    ship_address1: str | None = None
    ship_address2: str | None = None
    ship_postcode: str | None = None
    buyer_note: str | None = None
    remark: str | None = None
    items: list[OrderItemIn] = Field(min_length=1)


class OrderUpdate(Schema):
    ship_name: str | None = None
    ship_phone: str | None = None
    ship_country: str | None = None
    ship_state: str | None = None
    ship_city: str | None = None
    ship_address1: str | None = None
    ship_address2: str | None = None
    ship_postcode: str | None = None
    warehouse_id: int | None = None
    logistics_channel_id: int | None = None
    remark: str | None = None
    tags: list | None = None


class AuditIn(Schema):
    order_ids: list[int] = Field(min_length=1)
    warehouse_id: int | None = None
    logistics_channel_id: int | None = None


class ShipIn(Schema):
    carrier: str | None = None
    tracking_no: str | None = None
    actual_freight: Decimal | None = Field(default=None, ge=0, description="实际运费（本位币）")


class BatchShipItem(Schema):
    order_id: int
    tracking_no: str | None = None
    carrier: str | None = None
    actual_freight: Decimal | None = None


class BatchShipIn(Schema):
    orders: list[BatchShipItem] = Field(min_length=1)


class HoldIn(Schema):
    order_ids: list[int] = Field(min_length=1)
    hold: bool = True
    reason: str | None = None


class CancelIn(Schema):
    order_ids: list[int] = Field(min_length=1)
    reason: str | None = None


class BatchResult(Schema):
    success: list[int] = []
    failed: list[dict] = []


class ReturnLineIn(Schema):
    order_item_id: int | None = None
    product_id: int | None = None
    msku: str | None = None
    qty: int = Field(default=1, ge=1)
    refund_amount: Decimal = Field(default=Decimal(0), ge=0)
    qty_good: int = Field(default=0, ge=0)
    qty_defective: int = Field(default=0, ge=0)


class ReturnIn(Schema):
    order_id: int | None = None
    shop_id: int | None = None
    platform_return_id: str | None = None
    return_type: str = "return_refund"
    reason: str | None = None
    currency: str | None = None
    return_date: date | None = None
    warehouse_id: int | None = None
    remark: str | None = None
    lines: list[ReturnLineIn] = Field(min_length=1)


class ReturnCompleteIn(Schema):
    warehouse_id: int | None = None
    lines: list[dict] | None = Field(default=None, description="[{line_id, qty_good, qty_defective}] 为空按创建时数量")


class ReturnLineOut(Schema):
    id: int
    order_item_id: int | None = None
    product_id: int | None = None
    sku: str | None = None
    msku: str | None = None
    qty: int
    refund_amount: Money
    qty_good: int
    qty_defective: int


class ReturnOut(ORMOut):
    return_no: str
    order_id: int | None = None
    order_no: str | None = None
    platform_order_id: str | None = None
    shop_id: int
    shop_name: str | None = None
    platform_return_id: str | None = None
    return_type: str
    status: str
    reason: str | None = None
    currency: str
    refund_amount: Money
    return_date: date
    warehouse_id: int | None = None
    completed_at: datetime | None = None
    restock_cost: Money | None = None
    remark: str | None = None
    lines: list[ReturnLineOut] = []
