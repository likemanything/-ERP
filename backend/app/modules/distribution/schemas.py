from datetime import date, datetime
from decimal import Decimal

from pydantic import Field

from app.common.schemas import ORMOut, Schema
from app.core.types import Money


# ------------------------------------------------------------------ 等级
class LevelOut(ORMOut):
    code: str
    name: str
    discount_rate: Money
    sort: int
    remark: str | None = None


class LevelIn(Schema):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    discount_rate: Decimal = Field(default=Decimal(1), gt=0, le=10)
    sort: int = 0
    remark: str | None = None


class LevelUpdate(Schema):
    code: str | None = None
    name: str | None = None
    discount_rate: Decimal | None = Field(default=None, gt=0, le=10)
    sort: int | None = None
    remark: str | None = None


# ------------------------------------------------------------------ 分销商
class DistributorIn(Schema):
    code: str | None = Field(default=None, max_length=32, description="为空自动生成")
    name: str = Field(min_length=1, max_length=128)
    contact: str | None = None
    phone: str | None = None
    email: str | None = None
    country: str | None = None
    address: str | None = None
    level_id: int | None = None
    currency: str = "CNY"
    credit_limit: Decimal = Field(default=Decimal(0), ge=0)
    status: str = "active"
    allow_dropship: bool = True
    allow_wholesale: bool = True
    sales_rep_id: int | None = None
    remark: str | None = None
    username: str | None = Field(default=None, description="同时开通的门户登录账号")
    password: str | None = None


class DistributorUpdate(Schema):
    name: str | None = None
    contact: str | None = None
    phone: str | None = None
    email: str | None = None
    country: str | None = None
    address: str | None = None
    level_id: int | None = None
    currency: str | None = None
    credit_limit: Decimal | None = Field(default=None, ge=0)
    status: str | None = None
    allow_dropship: bool | None = None
    allow_wholesale: bool | None = None
    sales_rep_id: int | None = None
    remark: str | None = None


class DistributorOut(ORMOut):
    code: str
    name: str
    contact: str | None = None
    phone: str | None = None
    email: str | None = None
    country: str | None = None
    address: str | None = None
    level_id: int | None = None
    level_name: str | None = None
    currency: str
    balance: Money
    credit_limit: Money
    available_funds: Money
    status: str
    allow_dropship: bool
    allow_wholesale: bool
    shop_id: int | None = None
    sales_rep_id: int | None = None
    remark: str | None = None
    user_count: int = 0
    has_api_key: bool = False


class PortalUserIn(Schema):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=6, max_length=128)
    real_name: str = ""


class PortalUserOut(ORMOut):
    username: str
    real_name: str
    is_active: bool
    last_login_at: datetime | None = None


class PortalUserUpdate(Schema):
    is_active: bool | None = None
    real_name: str | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)


class AdjustIn(Schema):
    amount: Decimal = Field(description="正数增加余额，负数扣减")
    remark: str = Field(min_length=1, max_length=255)


class StaffRechargeIn(Schema):
    amount: Decimal = Field(gt=0)
    payment_method: str | None = None
    transaction_no: str | None = None
    remark: str | None = None


class TxnOut(ORMOut):
    distributor_id: int
    distributor_name: str | None = None
    txn_type: str
    amount: Money
    balance_after: Money
    currency: str
    ref_type: str | None = None
    ref_id: int | None = None
    ref_no: str | None = None
    remark: str | None = None


class RechargeIn(Schema):
    amount: Decimal = Field(gt=0)
    payment_method: str | None = None
    transaction_no: str | None = None
    proof_url: str | None = None
    remark: str | None = None


class RechargeOut(ORMOut):
    request_no: str
    distributor_id: int
    distributor_name: str | None = None
    amount: Money
    currency: str
    payment_method: str | None = None
    transaction_no: str | None = None
    proof_url: str | None = None
    status: str
    reviewed_at: datetime | None = None
    reject_reason: str | None = None
    remark: str | None = None


class ReviewIn(Schema):
    approve: bool
    reason: str | None = None


# ------------------------------------------------------------------ 商品目录
class CatalogItemIn(Schema):
    product_id: int
    base_price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None
    min_qty: int | None = Field(default=None, ge=1)
    is_active: bool | None = None
    stock_display: str | None = Field(default=None, pattern="^(real|capped|status)$")
    stock_cap: int | None = Field(default=None, ge=0)
    title: str | None = None
    description: str | None = None
    sort: int | None = None


class CatalogUpsertIn(Schema):
    items: list[CatalogItemIn] = Field(min_length=1)


class LevelPriceIn(Schema):
    level_id: int
    price: Decimal = Field(ge=0)


class LevelPricesIn(Schema):
    prices: list[LevelPriceIn]


class CatalogOut(ORMOut):
    product_id: int
    sku: str
    product_name: str
    image_url: str | None = None
    base_price: Money
    currency: str
    min_qty: int
    is_active: bool
    stock_display: str
    stock_cap: int
    title: str | None = None
    description: str | None = None
    sort: int
    available: int = 0
    purchase_cost: Money | None = None
    level_prices: list[dict] = []


class ChargeAdjustIn(Schema):
    amount: Decimal = Field(description="正数补扣，负数退款")
    remark: str = Field(min_length=1, max_length=255)


class DistributionSettings(Schema):
    warehouse_ids: list[int] = []
    channel_ids: list[int] = []
    handling_fee_per_order: Decimal = Field(default=Decimal(0), ge=0)
    handling_fee_per_item: Decimal = Field(default=Decimal(0), ge=0)
    freight_markup_rate: Decimal = Field(default=Decimal(0), ge=0, le=10)
    auto_audit: bool = True
    allow_cancel_after_audit: bool = True


# ------------------------------------------------------------------ 门户
class PortalDistributor(Schema):
    id: int
    code: str
    name: str
    contact: str | None = None
    phone: str | None = None
    email: str | None = None
    country: str | None = None
    address: str | None = None
    currency: str
    balance: Money
    credit_limit: Money
    available_funds: Money
    level_name: str | None = None
    allow_dropship: bool
    allow_wholesale: bool
    has_api_key: bool = False


class PortalMe(Schema):
    distributor: PortalDistributor
    username: str | None = None
    real_name: str | None = None
    via_api_key: bool = False
    company_name: str | None = None


class PortalCatalogItem(Schema):
    product_id: int
    sku: str
    title: str
    name_en: str | None = None
    image_url: str | None = None
    category_name: str | None = None
    weight_kg: Money
    length_cm: Money
    width_cm: Money
    height_cm: Money
    units_per_carton: int = 0
    price: Money
    currency: str
    min_qty: int
    stock: int | None = None
    in_stock: bool
    description: str | None = None


class QuoteItem(Schema):
    product_id: int | None = None
    sku: str | None = None
    qty: int = Field(ge=1)


class QuoteIn(Schema):
    order_type: str = Field(default="dropship", pattern="^(dropship|wholesale)$")
    channel_id: int | None = None
    items: list[QuoteItem] = Field(min_length=1)


class QuoteLineOut(Schema):
    product_id: int
    sku: str
    name: str
    qty: int
    unit_price: Money
    amount: Money
    in_stock: bool


class QuoteOut(Schema):
    currency: str
    lines: list[QuoteLineOut]
    weight_kg: Money
    goods: Money
    freight: Money
    handling: Money
    total: Money
    channel_id: int | None = None
    channel_name: str | None = None
    transit_days: int | None = None
    available_funds: Money
    sufficient: bool


class Address(Schema):
    name: str | None = None
    phone: str | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None
    address1: str | None = None
    address2: str | None = None
    postcode: str | None = None


class PortalOrderIn(QuoteIn):
    reference_no: str | None = Field(default=None, max_length=64, description="您的订单号（防重复提交），为空自动生成")
    address: Address | None = None
    remark: str | None = Field(default=None, max_length=500)


class PortalOrderItemOut(Schema):
    sku: str | None = None
    title: str | None = None
    quantity: int
    unit_price: Money
    item_amount: Money


class PortalOrderOut(Schema):
    id: int
    order_no: str
    reference_no: str
    status: str
    distribution_type: str | None = None
    created_at: datetime
    shipped_at: datetime | None = None
    ship_name: str | None = None
    ship_phone: str | None = None
    ship_country: str | None = None
    ship_state: str | None = None
    ship_city: str | None = None
    ship_address1: str | None = None
    ship_address2: str | None = None
    ship_postcode: str | None = None
    channel_name: str | None = None
    carrier: str | None = None
    tracking_no: str | None = None
    currency: str
    charge_detail: dict | None = None
    note: str | None = None
    can_cancel: bool = False
    items: list[PortalOrderItemOut] = []


class StatementOut(Schema):
    distributor_id: int
    distributor_name: str
    currency: str
    date_from: date
    date_to: date
    opening_balance: Money
    closing_balance: Money
    recharge: Money
    order: Money
    refund: Money
    adjust: Money
    order_count: int
    units: int
    transactions: list[TxnOut]
