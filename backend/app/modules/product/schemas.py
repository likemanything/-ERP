from datetime import date
from decimal import Decimal

from pydantic import Field

from app.common.schemas import ORMOut, Schema
from app.core.types import Money


class CategoryOut(ORMOut):
    name: str
    parent_id: int | None = None
    code: str | None = None
    sort: int = 0


class CategoryIn(Schema):
    name: str = Field(min_length=1, max_length=64)
    parent_id: int | None = None
    code: str | None = None
    sort: int = 0


class CategoryUpdate(Schema):
    name: str | None = None
    parent_id: int | None = None
    code: str | None = None
    sort: int | None = None


class BrandOut(ORMOut):
    name: str
    code: str | None = None
    remark: str | None = None


class BrandIn(Schema):
    name: str = Field(min_length=1, max_length=64)
    code: str | None = None
    remark: str | None = None


class BrandUpdate(Schema):
    name: str | None = None
    code: str | None = None
    remark: str | None = None


class BundleItemIn(Schema):
    component_id: int
    quantity: int = Field(default=1, ge=1)


class BundleItemOut(Schema):
    component_id: int
    quantity: int
    component_sku: str | None = None
    component_name: str | None = None


class ProductBase(Schema):
    name: str = Field(min_length=1, max_length=255)
    name_en: str | None = None
    barcode: str | None = Field(default=None, max_length=64)
    spu: str | None = None
    attributes: dict | None = None
    category_id: int | None = None
    brand_id: int | None = None
    product_type: str = "normal"
    status: str = "on_sale"
    unit: str = "个"
    image_url: str | None = None
    purchase_cost: Decimal = Decimal(0)
    default_supplier_id: int | None = None
    purchase_lead_days: int = 15
    moq: int = 1
    weight_kg: Decimal = Decimal(0)
    length_cm: Decimal = Decimal(0)
    width_cm: Decimal = Decimal(0)
    height_cm: Decimal = Decimal(0)
    units_per_carton: int = 0
    carton_weight_kg: Decimal = Decimal(0)
    carton_length_cm: Decimal = Decimal(0)
    carton_width_cm: Decimal = Decimal(0)
    carton_height_cm: Decimal = Decimal(0)
    declare_name_cn: str | None = None
    declare_name_en: str | None = None
    declare_value_usd: Decimal = Decimal(0)
    hs_code: str | None = None
    material: str | None = None
    usage: str | None = None
    developer_id: int | None = None
    purchaser_id: int | None = None
    description: str | None = None
    remark: str | None = None


class ProductIn(ProductBase):
    sku: str = Field(min_length=1, max_length=64)
    bundle_items: list[BundleItemIn] = []


class ProductUpdate(Schema):
    sku: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = None
    name_en: str | None = None
    barcode: str | None = Field(default=None, max_length=64)
    spu: str | None = None
    attributes: dict | None = None
    category_id: int | None = None
    brand_id: int | None = None
    product_type: str | None = None
    status: str | None = None
    unit: str | None = None
    image_url: str | None = None
    purchase_cost: Decimal | None = None
    default_supplier_id: int | None = None
    purchase_lead_days: int | None = None
    moq: int | None = None
    weight_kg: Decimal | None = None
    length_cm: Decimal | None = None
    width_cm: Decimal | None = None
    height_cm: Decimal | None = None
    units_per_carton: int | None = None
    carton_weight_kg: Decimal | None = None
    carton_length_cm: Decimal | None = None
    carton_width_cm: Decimal | None = None
    carton_height_cm: Decimal | None = None
    declare_name_cn: str | None = None
    declare_name_en: str | None = None
    declare_value_usd: Decimal | None = None
    hs_code: str | None = None
    material: str | None = None
    usage: str | None = None
    developer_id: int | None = None
    purchaser_id: int | None = None
    description: str | None = None
    remark: str | None = None
    bundle_items: list[BundleItemIn] | None = None


class ProductOut(ORMOut):
    sku: str
    name: str
    name_en: str | None = None
    barcode: str | None = Field(default=None, max_length=64)
    spu: str | None = None
    attributes: dict | None = None
    category_id: int | None = None
    brand_id: int | None = None
    product_type: str
    status: str
    unit: str
    image_url: str | None = None
    purchase_cost: Money | None = None
    default_supplier_id: int | None = None
    purchase_lead_days: int
    moq: int
    weight_kg: Money
    length_cm: Money
    width_cm: Money
    height_cm: Money
    units_per_carton: int
    carton_weight_kg: Money
    carton_length_cm: Money
    carton_width_cm: Money
    carton_height_cm: Money
    declare_name_cn: str | None = None
    declare_name_en: str | None = None
    declare_value_usd: Money
    hs_code: str | None = None
    material: str | None = None
    usage: str | None = None
    developer_id: int | None = None
    purchaser_id: int | None = None
    description: str | None = None
    remark: str | None = None
    bundle_items: list[BundleItemOut] = []
    category_name: str | None = None
    brand_name: str | None = None
    stock_available: int | None = None


class ProductBrief(Schema):
    id: int
    sku: str
    name: str
    image_url: str | None = None
    product_type: str
    unit: str = "个"


class ProductSupplierOut(ORMOut):
    product_id: int
    supplier_id: int
    supplier_name: str | None = None
    price: Money
    currency: str
    moq: int
    lead_days: int
    is_default: bool
    purchase_url: str | None = None
    remark: str | None = None


class ProductSupplierIn(Schema):
    supplier_id: int
    price: Decimal = Field(ge=0)
    currency: str = "CNY"
    moq: int = Field(default=1, ge=1)
    lead_days: int = Field(default=15, ge=0)
    is_default: bool = False
    purchase_url: str | None = None
    remark: str | None = None


class ListingOut(ORMOut):
    shop_id: int
    shop_name: str | None = None
    msku: str
    asin: str | None = None
    parent_asin: str | None = None
    fnsku: str | None = None
    title: str | None = None
    image_url: str | None = None
    price: Money
    currency: str
    status: str
    fulfillment: str
    product_id: int | None = None
    pair_quantity: int
    sku: str | None = None
    product_name: str | None = None
    principal_id: int | None = None
    open_date: date | None = None
    sales_rank: int | None = None
    review_count: int | None = None
    rating: Money | None = None
    tags: list | None = None
    remark: str | None = None


class ListingIn(Schema):
    shop_id: int
    msku: str = Field(min_length=1, max_length=128)
    asin: str | None = None
    parent_asin: str | None = None
    fnsku: str | None = None
    title: str | None = None
    image_url: str | None = None
    price: Decimal = Decimal(0)
    currency: str | None = None
    status: str = "active"
    fulfillment: str = "FBA"
    product_id: int | None = None
    pair_quantity: int = Field(default=1, ge=1)
    principal_id: int | None = None
    open_date: date | None = None
    tags: list | None = None
    remark: str | None = None


class ListingUpdate(Schema):
    asin: str | None = None
    parent_asin: str | None = None
    fnsku: str | None = None
    title: str | None = None
    image_url: str | None = None
    price: Decimal | None = None
    status: str | None = None
    fulfillment: str | None = None
    principal_id: int | None = None
    open_date: date | None = None
    tags: list | None = None
    remark: str | None = None


class PairIn(Schema):
    product_id: int | None = Field(description="为空表示解除配对")
    pair_quantity: int = Field(default=1, ge=1)
    apply_to_history: bool = Field(default=True, description="同时更新历史订单明细的配对 SKU")


class ImportResult(Schema):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = []
