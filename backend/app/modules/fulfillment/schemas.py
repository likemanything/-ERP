from datetime import datetime

from pydantic import Field

from app.common.schemas import ORMOut, Schema


class WaveCreateIn(Schema):
    order_ids: list[int] | None = Field(default=None, description="指定订单；为空则按仓库取全部待发货订单")
    warehouse_id: int | None = None
    max_orders: int = Field(default=100, ge=1, le=1000, description="每个波次最多订单数")
    remark: str | None = None


class WaveOut(ORMOut):
    wave_no: str
    warehouse_id: int
    warehouse_name: str | None = None
    status: str
    order_count: int
    sku_count: int
    unit_count: int
    shipped_count: int = 0
    picker_id: int | None = None
    picker_name: str | None = None
    print_count: int
    picked_at: datetime | None = None
    completed_at: datetime | None = None
    remark: str | None = None


class WaveCreateOut(Schema):
    waves: list[WaveOut]
    skipped: int = 0


class PickLineOut(Schema):
    product_id: int
    sku: str
    name: str
    image_url: str | None = None
    barcode: str | None = None
    bin_code: str | None = None
    qty: int
    orders: list[dict]


class WaveOrderOut(Schema):
    id: int
    order_no: str
    platform_order_id: str
    shop_name: str | None = None
    status: str
    ship_name: str | None = None
    ship_country: str | None = None
    tracking_no: str | None = None
    units: int = 0


class WaveDetailOut(WaveOut):
    lines: list[PickLineOut] = []
    orders: list[WaveOrderOut] = []


class WaveOrdersIn(Schema):
    order_ids: list[int] = Field(min_length=1)


class PickedIn(Schema):
    picker_id: int | None = None


class ScanLineOut(Schema):
    product_id: int
    sku: str
    name: str
    image_url: str | None = None
    qty: int
    codes: list[str]


class ScanOrderOut(Schema):
    id: int
    order_no: str
    platform_order_id: str
    shop_name: str | None = None
    status: str
    is_on_hold: bool
    hold_reason: str | None = None
    ship_name: str | None = None
    ship_country: str | None = None
    ship_address1: str | None = None
    logistics_channel_name: str | None = None
    carrier: str | None = None
    tracking_no: str | None = None
    est_freight: float = 0
    buyer_note: str | None = None
    wave_no: str | None = None
    lines: list[ScanLineOut]


class ScanShipIn(Schema):
    order_id: int
    tracking_no: str | None = None
    carrier: str | None = None
    actual_freight: float | None = Field(default=None, ge=0)


class LabelLineIn(Schema):
    listing_id: int | None = None
    product_id: int | None = None
    code: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=255)
    qty: int = Field(default=1, ge=0, le=5000)


class LabelPrintIn(Schema):
    kind: str = Field(default="fnsku", pattern="^(fnsku|sku|barcode)$")
    size: str = "60x30"
    skip: int = Field(default=0, ge=0, le=100, description="A4 标签纸跳过已使用的格子数")
    condition: str | None = Field(default="New", max_length=32)
    extra: str | None = Field(default=None, max_length=64, description="附加文字，如 Made in China")
    items: list[LabelLineIn] = Field(min_length=1)


class PackingSlipIn(Schema):
    order_ids: list[int] = Field(min_length=1, max_length=1000)
    size: str = Field(default="a4", pattern="^(a4|100x150)$")
