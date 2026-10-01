from datetime import date
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import TenantModel
from app.core.types import MoneyColumn

Dim = Numeric(12, 3)


class Category(TenantModel):
    __tablename__ = "product_categories"

    name: Mapped[str] = mapped_column(String(64))
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("product_categories.id"))
    code: Mapped[str | None] = mapped_column(String(32))
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Brand(TenantModel):
    __tablename__ = "product_brands"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    name: Mapped[str] = mapped_column(String(64))
    code: Mapped[str | None] = mapped_column(String(32))
    remark: Mapped[str | None] = mapped_column(String(255))


class Product(TenantModel):
    """本地产品（库存 SKU）。"""

    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("tenant_id", "sku"),)

    sku: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255))
    barcode: Mapped[str | None] = mapped_column(String(64), index=True, doc="商品条码（UPC/EAN 等），用于扫码验货")
    spu: Mapped[str | None] = mapped_column(String(64), index=True, doc="款号，多属性产品共用")
    attributes: Mapped[dict | None] = mapped_column(JSON, doc="变体属性，如 {颜色: 红, 尺码: L}")
    category_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("product_categories.id"))
    brand_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("product_brands.id"))
    product_type: Mapped[str] = mapped_column(String(16), default="normal")
    status: Mapped[str] = mapped_column(String(16), default="on_sale", index=True)
    unit: Mapped[str] = mapped_column(String(16), default="个")
    image_url: Mapped[str | None] = mapped_column(String(500))

    purchase_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="参考采购成本（本位币，含税）")
    default_supplier_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("suppliers.id"))
    purchase_lead_days: Mapped[int] = mapped_column(Integer, default=15, doc="采购交期（天）")
    moq: Mapped[int] = mapped_column(Integer, default=1, doc="最小起订量")

    # 单品规格
    weight_kg: Mapped[Decimal] = mapped_column(Dim, default=0)
    length_cm: Mapped[Decimal] = mapped_column(Dim, default=0)
    width_cm: Mapped[Decimal] = mapped_column(Dim, default=0)
    height_cm: Mapped[Decimal] = mapped_column(Dim, default=0)
    # 箱规
    units_per_carton: Mapped[int] = mapped_column(Integer, default=0)
    carton_weight_kg: Mapped[Decimal] = mapped_column(Dim, default=0)
    carton_length_cm: Mapped[Decimal] = mapped_column(Dim, default=0)
    carton_width_cm: Mapped[Decimal] = mapped_column(Dim, default=0)
    carton_height_cm: Mapped[Decimal] = mapped_column(Dim, default=0)
    # 报关信息
    declare_name_cn: Mapped[str | None] = mapped_column(String(128))
    declare_name_en: Mapped[str | None] = mapped_column(String(128))
    declare_value_usd: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    hs_code: Mapped[str | None] = mapped_column(String(32))
    material: Mapped[str | None] = mapped_column(String(128))
    usage: Mapped[str | None] = mapped_column(String(128))

    developer_id: Mapped[int | None] = mapped_column(BigInteger, doc="开发人员")
    purchaser_id: Mapped[int | None] = mapped_column(BigInteger, doc="采购员")
    description: Mapped[str | None] = mapped_column(Text)
    remark: Mapped[str | None] = mapped_column(String(500))

    bundle_items: Mapped[list["BundleItem"]] = relationship(
        foreign_keys="BundleItem.bundle_id", cascade="all, delete-orphan", lazy="selectin"
    )


class BundleItem(TenantModel):
    """组合产品明细：1 个组合品 = quantity 个子产品。"""

    __tablename__ = "product_bundle_items"
    __table_args__ = (UniqueConstraint("bundle_id", "component_id"),)

    bundle_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id", ondelete="CASCADE"), index=True)
    component_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    component: Mapped[Product] = relationship(foreign_keys=[component_id], lazy="joined")


class ProductSupplier(TenantModel):
    """供应商报价。"""

    __tablename__ = "product_suppliers"
    __table_args__ = (UniqueConstraint("product_id", "supplier_id"),)

    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id", ondelete="CASCADE"), index=True)
    supplier_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("suppliers.id"), index=True)
    price: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    moq: Mapped[int] = mapped_column(Integer, default=1)
    lead_days: Mapped[int] = mapped_column(Integer, default=15)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    purchase_url: Mapped[str | None] = mapped_column(String(500))
    remark: Mapped[str | None] = mapped_column(String(255))


class Listing(TenantModel):
    """平台在线商品（MSKU），通过 product_id 与本地 SKU 配对。"""

    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("tenant_id", "shop_id", "msku"),)

    shop_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shops.id"), index=True)
    msku: Mapped[str] = mapped_column(String(128))
    asin: Mapped[str | None] = mapped_column(String(64), index=True, doc="ASIN / 平台商品 ID")
    parent_asin: Mapped[str | None] = mapped_column(String(64), index=True)
    fnsku: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(500))
    image_url: Mapped[str | None] = mapped_column(String(500))
    price: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    fulfillment: Mapped[str] = mapped_column(String(8), default="FBA")
    product_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("products.id"), index=True)
    pair_quantity: Mapped[int] = mapped_column(Integer, default=1, doc="1 个 MSKU 对应的本地 SKU 数量")
    principal_id: Mapped[int | None] = mapped_column(BigInteger, doc="运营负责人")
    open_date: Mapped[date | None] = mapped_column(Date)
    sales_rank: Mapped[int | None] = mapped_column(Integer)
    review_count: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    tags: Mapped[list | None] = mapped_column(JSON)
    remark: Mapped[str | None] = mapped_column(String(500))

    product: Mapped[Product | None] = relationship(lazy="joined")
