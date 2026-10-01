from datetime import date, datetime
from decimal import Decimal

from pydantic import Field

from app.common.schemas import ORMOut, Schema
from app.core.types import Money


class WarehouseOut(ORMOut):
    code: str
    name: str
    warehouse_type: str
    country: str | None = None
    address: str | None = None
    contact: str | None = None
    phone: str | None = None
    shop_id: int | None = None
    is_default: bool
    status: str
    remark: str | None = None


class WarehouseIn(Schema):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    warehouse_type: str = "local"
    country: str | None = None
    address: str | None = None
    contact: str | None = None
    phone: str | None = None
    shop_id: int | None = None
    is_default: bool = False
    status: str = "active"
    remark: str | None = None


class WarehouseUpdate(Schema):
    code: str | None = None
    name: str | None = None
    warehouse_type: str | None = None
    country: str | None = None
    address: str | None = None
    contact: str | None = None
    phone: str | None = None
    shop_id: int | None = None
    is_default: bool | None = None
    status: str | None = None
    remark: str | None = None


class BinOut(ORMOut):
    warehouse_id: int
    code: str
    zone: str | None = None
    bin_type: str
    status: str
    remark: str | None = None


class BinIn(Schema):
    warehouse_id: int
    code: str = Field(min_length=1, max_length=32)
    zone: str | None = None
    bin_type: str = "storage"
    status: str = "active"
    remark: str | None = None


class BinUpdate(Schema):
    code: str | None = None
    zone: str | None = None
    bin_type: str | None = None
    status: str | None = None
    remark: str | None = None


class InventoryRow(Schema):
    id: int
    warehouse_id: int
    warehouse_name: str | None = None
    warehouse_type: str | None = None
    product_id: int
    sku: str | None = None
    product_name: str | None = None
    image_url: str | None = None
    qty_on_hand: int
    qty_locked: int
    qty_available: int
    qty_defective: int
    qty_in_transit: int
    safety_stock: int
    bin_code: str | None = None
    unit_cost: Money | None = None
    stock_value: Money | None = None
    updated_at: datetime | None = None


class InventorySettingIn(Schema):
    safety_stock: int | None = Field(default=None, ge=0)
    bin_code: str | None = None


class LedgerOut(ORMOut):
    warehouse_id: int
    warehouse_name: str | None = None
    product_id: int
    sku: str | None = None
    product_name: str | None = None
    batch_id: int | None = None
    change_type: str
    stock_type: str
    qty_change: int
    qty_after: int
    unit_purchase_cost: Money | None = None
    unit_freight_cost: Money | None = None
    amount: Money | None = None
    ref_type: str | None = None
    ref_id: int | None = None
    ref_no: str | None = None
    biz_date: date | None = None
    remark: str | None = None
    created_by: int | None = None


class BatchOut(ORMOut):
    warehouse_id: int
    warehouse_name: str | None = None
    product_id: int
    sku: str | None = None
    product_name: str | None = None
    batch_no: str
    source_type: str
    source_no: str | None = None
    received_at: datetime
    qty_in: int
    qty_remaining: int
    unit_purchase_cost: Money | None = None
    unit_freight_cost: Money | None = None
    age_days: int = 0


class StockDocLineIn(Schema):
    product_id: int
    qty: int = Field(default=0, ge=0)
    unit_cost: Decimal | None = Field(default=None, ge=0, description="其他入库单价（本位币），为空取参考成本")
    counted_qty: int | None = Field(default=None, ge=0, description="盘点实盘数量")
    remark: str | None = None


class StockDocLineOut(Schema):
    id: int
    product_id: int
    sku: str | None = None
    product_name: str | None = None
    qty: int
    unit_cost: Money | None = None
    unit_freight_cost: Money | None = None
    qty_received: int
    system_qty: int | None = None
    counted_qty: int | None = None
    remark: str | None = None


class StockDocIn(Schema):
    doc_type: str = Field(description="in 其他入库 / out 其他出库 / transfer 调拨 / stocktake 盘点")
    biz_type: str | None = None
    warehouse_id: int
    to_warehouse_id: int | None = None
    stock_type: str = "good"
    logistics_channel_id: int | None = None
    tracking_no: str | None = None
    freight_cost: Decimal = Field(default=Decimal(0), ge=0)
    remark: str | None = None
    lines: list[StockDocLineIn] = []
    fill_all: bool = Field(default=False, description="盘点单：自动带出仓库全部有库存的 SKU")


class StockDocUpdate(Schema):
    biz_type: str | None = None
    to_warehouse_id: int | None = None
    stock_type: str | None = None
    logistics_channel_id: int | None = None
    tracking_no: str | None = None
    freight_cost: Decimal | None = Field(default=None, ge=0)
    remark: str | None = None
    lines: list[StockDocLineIn] | None = None


class StockDocOut(ORMOut):
    doc_no: str
    doc_type: str
    biz_type: str | None = None
    warehouse_id: int
    warehouse_name: str | None = None
    to_warehouse_id: int | None = None
    to_warehouse_name: str | None = None
    status: str
    stock_type: str
    logistics_channel_id: int | None = None
    tracking_no: str | None = None
    freight_cost: Money
    shipped_at: datetime | None = None
    completed_at: datetime | None = None
    remark: str | None = None
    created_by: int | None = None
    total_qty: int = 0
    lines: list[StockDocLineOut] = []


class ReceiveLineIn(Schema):
    line_id: int
    qty_received: int = Field(ge=0)


class TransferReceiveIn(Schema):
    lines: list[ReceiveLineIn] | None = Field(default=None, description="为空表示按发货数量全部签收")
