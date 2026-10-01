"""平台连接器与 ERP 之间的标准数据结构（与具体平台无关）。"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class OrderItemDTO(BaseModel):
    msku: str
    quantity: int = 1
    item_amount: Decimal = Decimal(0)  # 商品金额（单价 × 数量）
    shipping_amount: Decimal = Decimal(0)
    tax_amount: Decimal = Decimal(0)
    discount_amount: Decimal = Decimal(0)
    commission_fee: Decimal | None = None  # 为空则按比例预估
    fulfillment_fee: Decimal | None = None
    other_fee: Decimal | None = None
    asin: str | None = None
    title: str | None = None
    platform_item_id: str | None = None


class OrderDTO(BaseModel):
    platform_order_id: str
    fulfillment: str = "FBM"  # FBA / FBM
    platform_status: str | None = None
    # 标准化状态：pending / unshipped / shipped / delivered / cancelled
    status: str = "unshipped"
    purchase_at: datetime
    paid_at: datetime | None = None
    latest_ship_at: datetime | None = None
    shipped_at: datetime | None = None
    currency: str = "USD"
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
    carrier: str | None = None
    tracking_no: str | None = None
    items: list[OrderItemDTO] = Field(default_factory=list)


class ListingDTO(BaseModel):
    msku: str
    asin: str | None = None
    parent_asin: str | None = None
    fnsku: str | None = None
    title: str | None = None
    image_url: str | None = None
    price: Decimal = Decimal(0)
    currency: str | None = None
    status: str = "active"
    fulfillment: str = "FBA"
    open_date: date | None = None
    quantity: int | None = None


class FbaInventoryDTO(BaseModel):
    msku: str
    fnsku: str | None = None
    asin: str | None = None
    fulfillable: int = 0
    inbound_working: int = 0
    inbound_shipped: int = 0
    inbound_receiving: int = 0
    reserved: int = 0
    unfulfillable: int = 0


class TransactionDTO(BaseModel):
    external_id: str
    posted_at: datetime
    event_type: str
    amount_type: str
    amount: Decimal
    currency: str
    platform_order_id: str | None = None
    msku: str | None = None
    quantity: int = 0
    settlement_id: str | None = None
    description: str | None = None


class AdMetricDTO(BaseModel):
    metric_date: date
    campaign_id: str
    campaign_name: str | None = None
    ad_group: str = ""
    ad_type: str = "SP"
    msku: str = ""
    asin: str | None = None
    impressions: int = 0
    clicks: int = 0
    spend: Decimal = Decimal(0)
    sales: Decimal = Decimal(0)
    orders: int = 0
    units: int = 0
    currency: str = "USD"
