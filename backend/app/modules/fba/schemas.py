from datetime import date, datetime
from decimal import Decimal

from pydantic import Field

from app.common.schemas import ORMOut, Schema
from app.core.types import Money


class PlanLineIn(Schema):
    listing_id: int | None = None
    product_id: int | None = None
    qty: int = Field(gt=0, description="发货数量（MSKU 单位）")


class ShipmentPlanIn(Schema):
    shop_id: int
    ship_from_warehouse_id: int
    to_warehouse_id: int | None = None
    logistics_channel_id: int | None = None
    expected_ship_date: date | None = None
    remark: str | None = None
    lines: list[PlanLineIn] = Field(min_length=1)


class ShipmentPlanUpdate(Schema):
    ship_from_warehouse_id: int | None = None
    to_warehouse_id: int | None = None
    logistics_channel_id: int | None = None
    expected_ship_date: date | None = None
    remark: str | None = None
    lines: list[PlanLineIn] | None = None


class PlanLineOut(Schema):
    id: int
    listing_id: int | None = None
    msku: str | None = None
    fnsku: str | None = None
    product_id: int
    sku: str | None = None
    product_name: str | None = None
    qty: int
    stock_available: int = 0


class ShipmentPlanOut(ORMOut):
    plan_no: str
    shop_id: int
    shop_name: str | None = None
    ship_from_warehouse_id: int
    ship_from_warehouse_name: str | None = None
    to_warehouse_id: int | None = None
    logistics_channel_id: int | None = None
    status: str
    expected_ship_date: date | None = None
    shipment_id: int | None = None
    remark: str | None = None
    created_by: int | None = None
    total_qty: int = 0
    lines: list[PlanLineOut] = []


class BoxItem(Schema):
    msku: str
    qty: int


class Box(Schema):
    box_no: str | None = None
    weight_kg: Decimal = Decimal(0)
    length_cm: Decimal = Decimal(0)
    width_cm: Decimal = Decimal(0)
    height_cm: Decimal = Decimal(0)
    items: list[BoxItem] = []


class ShipmentLineIn(Schema):
    listing_id: int | None = None
    product_id: int | None = None
    msku: str | None = None
    fnsku: str | None = None
    qty: int = Field(gt=0, description="发货数量（MSKU 单位，自动换算为 SKU 数量）")


class ShipmentIn(Schema):
    shop_id: int
    ship_from_warehouse_id: int
    to_warehouse_id: int | None = Field(default=None, description="为空则发往店铺 FBA 仓")
    plan_id: int | None = None
    platform_shipment_id: str | None = None
    destination_fc: str | None = None
    logistics_channel_id: int | None = None
    tracking_no: str | None = None
    ship_date: date | None = None
    eta: date | None = None
    boxes: list[Box] | None = None
    cost_currency: str = "CNY"
    freight_cost: Decimal = Field(default=Decimal(0), ge=0)
    customs_duty: Decimal = Field(default=Decimal(0), ge=0)
    other_cost: Decimal = Field(default=Decimal(0), ge=0)
    allocation_method: str | None = None
    remark: str | None = None
    lines: list[ShipmentLineIn] = Field(min_length=1)


class ShipmentUpdate(Schema):
    platform_shipment_id: str | None = None
    destination_fc: str | None = None
    to_warehouse_id: int | None = None
    logistics_channel_id: int | None = None
    tracking_no: str | None = None
    ship_date: date | None = None
    eta: date | None = None
    boxes: list[Box] | None = None
    cost_currency: str | None = None
    freight_cost: Decimal | None = Field(default=None, ge=0)
    customs_duty: Decimal | None = Field(default=None, ge=0)
    other_cost: Decimal | None = Field(default=None, ge=0)
    allocation_method: str | None = None
    remark: str | None = None
    lines: list[ShipmentLineIn] | None = None


class ShipmentLineOut(Schema):
    id: int
    listing_id: int | None = None
    msku: str | None = None
    fnsku: str | None = None
    product_id: int
    sku: str | None = None
    product_name: str | None = None
    image_url: str | None = None
    qty_shipped: int
    qty_received: int
    unit_weight_kg: Money
    unit_volume_cbm: Money
    unit_purchase_cost: Money | None = None
    unit_freight_cost: Money | None = None
    allocated_cost: Money | None = None
    allocated_unit_cost: Money | None = None


class ShipmentOut(ORMOut):
    shipment_no: str
    platform_shipment_id: str | None = None
    shop_id: int
    shop_name: str | None = None
    plan_id: int | None = None
    ship_from_warehouse_id: int
    ship_from_warehouse_name: str | None = None
    to_warehouse_id: int
    to_warehouse_name: str | None = None
    destination_fc: str | None = None
    status: str
    logistics_channel_id: int | None = None
    logistics_channel_name: str | None = None
    tracking_no: str | None = None
    ship_date: date | None = None
    eta: date | None = None
    shipped_at: datetime | None = None
    closed_at: datetime | None = None
    box_count: int
    total_weight_kg: Money
    total_volume_cbm: Money
    chargeable_weight_kg: Money
    boxes: list | None = None
    cost_currency: str
    freight_cost: Money
    customs_duty: Money
    other_cost: Money
    allocation_method: str
    cost_allocated: bool
    remark: str | None = None
    created_by: int | None = None
    total_qty: int = 0
    received_qty: int = 0
    lines: list[ShipmentLineOut] = []


class ReceiveLine(Schema):
    line_id: int
    qty_received: int = Field(ge=0, description="本次签收数量")


class ShipmentReceiveIn(Schema):
    lines: list[ReceiveLine] | None = Field(default=None, description="为空表示按未签收数量全部签收")
    close: bool = Field(default=False, description="签收后直接完结货件")


class CostUpdateIn(Schema):
    cost_currency: str | None = None
    freight_cost: Decimal | None = Field(default=None, ge=0)
    customs_duty: Decimal | None = Field(default=None, ge=0)
    other_cost: Decimal | None = Field(default=None, ge=0)
    allocation_method: str | None = None


class FbaInventoryOut(ORMOut):
    shop_id: int
    shop_name: str | None = None
    msku: str
    fnsku: str | None = None
    asin: str | None = None
    listing_id: int | None = None
    product_id: int | None = None
    sku: str | None = None
    title: str | None = None
    image_url: str | None = None
    fulfillable: int
    inbound_working: int
    inbound_shipped: int
    inbound_receiving: int
    reserved: int
    unfulfillable: int
    inbound_total: int = 0
    snapshot_at: datetime | None = None
    daily_sales: float = 0
    days_of_supply: float | None = None
