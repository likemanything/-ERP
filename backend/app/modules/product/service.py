from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.common.audit import audit
from app.common.crud import ensure_not_referenced, ensure_unique, get_or_404
from app.common.enums import ProductStatus, ProductType
from app.core.deps import Ctx
from app.core.errors import BizError
from app.modules.product.models import Brand, BundleItem, Category, Listing, Product, ProductSupplier


def validate_product_fields(data: dict) -> None:
    if "product_type" in data and data["product_type"] not in {t.value for t in ProductType}:
        raise BizError(f"无效的产品类型: {data['product_type']}")
    if "status" in data and data["status"] not in {s.value for s in ProductStatus}:
        raise BizError(f"无效的产品状态: {data['status']}")


def _set_bundle_items(db: Session, product: Product, items: list[dict]) -> None:
    if product.product_type != ProductType.BUNDLE:
        if items:
            raise BizError("只有组合产品可以设置子产品")
        product.bundle_items = []
        return
    if not items:
        raise BizError("组合产品至少需要一个子产品")
    ids = [i["component_id"] for i in items]
    if len(set(ids)) != len(ids):
        raise BizError("子产品不能重复")
    comps = {p.id: p for p in db.execute(select(Product).where(Product.id.in_(ids))).scalars().all()}
    for i in items:
        comp = comps.get(i["component_id"])
        if comp is None:
            raise BizError(f"子产品不存在: {i['component_id']}")
        if comp.product_type == ProductType.BUNDLE:
            raise BizError(f"子产品 {comp.sku} 不能是组合产品")
        if product.id is not None and comp.id == product.id:
            raise BizError("组合产品不能包含自身")
    product.bundle_items = [BundleItem(component_id=i["component_id"], quantity=i["quantity"]) for i in items]
    db.flush()
    # 组合产品成本 = 子产品成本之和（未手工填写时）
    if not product.purchase_cost:
        product.purchase_cost = sum(
            (comps[i["component_id"]].purchase_cost or Decimal(0)) * i["quantity"] for i in items
        )


def create_product(ctx: Ctx, data: dict) -> Product:
    validate_product_fields(data)
    ensure_unique(ctx.db, Product, "sku", data["sku"], label="SKU")
    items = data.pop("bundle_items", []) or []
    product = Product(**data)
    ctx.db.add(product)
    ctx.db.flush()
    _set_bundle_items(ctx.db, product, items)
    audit(ctx, "create", "product", product.id, f"新增产品 {product.sku}")
    ctx.db.commit()
    return product


def update_product(ctx: Ctx, product_id: int, data: dict) -> Product:
    product = get_or_404(ctx.db, Product, product_id, "产品")
    validate_product_fields(data)
    if "sku" in data and data["sku"] != product.sku:
        ensure_unique(ctx.db, Product, "sku", data["sku"], exclude_id=product.id, label="SKU")
    if "product_type" in data and data["product_type"] != product.product_type:
        from app.modules.warehouse.models import InventoryBalance

        has_stock = ctx.db.execute(
            select(func.coalesce(func.sum(InventoryBalance.qty_on_hand), 0)).where(InventoryBalance.product_id == product.id)
        ).scalar_one()
        if has_stock:
            raise BizError("产品存在库存，不能修改产品类型")
    items = data.pop("bundle_items", None)
    for k, v in data.items():
        setattr(product, k, v)
    if items is not None or "product_type" in data:
        _set_bundle_items(ctx.db, product, items if items is not None else [
            {"component_id": b.component_id, "quantity": b.quantity} for b in product.bundle_items
        ])
    if "sku" in data:
        from app.modules.order.models import SalesOrderItem

        ctx.db.execute(update(SalesOrderItem).where(SalesOrderItem.product_id == product.id).values(sku=product.sku))
    audit(ctx, "update", "product", product.id, f"修改产品 {product.sku}", {"fields": list(data.keys())})
    ctx.db.commit()
    return product


def delete_product(ctx: Ctx, product_id: int) -> None:
    from app.modules.order.models import SalesOrderItem
    from app.modules.purchase.models import PurchaseOrderLine
    from app.modules.warehouse.models import InventoryBalance, InventoryLedger

    product = get_or_404(ctx.db, Product, product_id, "产品")
    ensure_not_referenced(
        ctx.db,
        [
            (InventoryBalance, (InventoryBalance.product_id == product.id) & (InventoryBalance.qty_on_hand != 0), "库存"),
            (InventoryLedger, InventoryLedger.product_id == product.id, "库存流水"),
            (PurchaseOrderLine, PurchaseOrderLine.product_id == product.id, "采购单"),
            (SalesOrderItem, SalesOrderItem.product_id == product.id, "订单"),
            (BundleItem, BundleItem.component_id == product.id, "组合产品"),
        ],
    )
    from sqlalchemy import delete as sa_delete

    ctx.db.execute(sa_delete(InventoryBalance).where(InventoryBalance.product_id == product.id))
    ctx.db.execute(update(Listing).where(Listing.product_id == product.id).values(product_id=None))
    ctx.db.delete(product)
    audit(ctx, "delete", "product", product_id, f"删除产品 {product.sku}")
    ctx.db.commit()


def product_out(db: Session, products: Iterable[Product], *, show_cost: bool, with_stock: bool = False) -> list[dict]:
    products = list(products)
    if not products:
        return []
    cat_ids = {p.category_id for p in products if p.category_id}
    brand_ids = {p.brand_id for p in products if p.brand_id}
    cats = dict(db.execute(select(Category.id, Category.name).where(Category.id.in_(cat_ids))).all()) if cat_ids else {}
    brands = dict(db.execute(select(Brand.id, Brand.name).where(Brand.id.in_(brand_ids))).all()) if brand_ids else {}
    stock: dict[int, int] = {}
    if with_stock:
        stock = available_stock(db, [p.id for p in products])
    result = []
    for p in products:
        d = {c.key: getattr(p, c.key) for c in Product.__table__.columns}
        if not show_cost:
            d["purchase_cost"] = None
        d["category_name"] = cats.get(p.category_id)
        d["brand_name"] = brands.get(p.brand_id)
        d["bundle_items"] = [
            {
                "component_id": b.component_id,
                "quantity": b.quantity,
                "component_sku": b.component.sku if b.component else None,
                "component_name": b.component.name if b.component else None,
            }
            for b in p.bundle_items
        ]
        d["stock_available"] = stock.get(p.id, 0) if with_stock else None
        result.append(d)
    return result


def available_stock(db: Session, product_ids: list[int], *, local_only: bool = True) -> dict[int, int]:
    from app.modules.warehouse.models import InventoryBalance, Warehouse

    if not product_ids:
        return {}
    stmt = (
        select(
            InventoryBalance.product_id,
            func.sum(InventoryBalance.qty_on_hand - InventoryBalance.qty_locked),
        )
        .join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id)
        .where(InventoryBalance.product_id.in_(product_ids))
        .group_by(InventoryBalance.product_id)
    )
    if local_only:
        stmt = stmt.where(Warehouse.warehouse_type.in_(["local", "overseas", "third_party"]))
    return {pid: int(q or 0) for pid, q in db.execute(stmt).all()}


def expand_bundle(db: Session, product_id: int, qty: int) -> list[tuple[int, int]]:
    """组合产品展开为 [(子产品ID, 数量)]，普通产品原样返回。"""
    product = get_or_404(db, Product, product_id, "产品")
    if product.product_type == ProductType.BUNDLE and product.bundle_items:
        return [(b.component_id, b.quantity * qty) for b in product.bundle_items]
    return [(product.id, qty)]


# ---------------------------------------------------------------- 供应商报价
def upsert_product_supplier(ctx: Ctx, product_id: int, data: dict, quote_id: int | None = None) -> ProductSupplier:
    from app.modules.supplier.models import Supplier

    product = get_or_404(ctx.db, Product, product_id, "产品")
    get_or_404(ctx.db, Supplier, data["supplier_id"], "供应商")
    if quote_id:
        quote = get_or_404(ctx.db, ProductSupplier, quote_id, "供应商报价")
        if quote.product_id != product.id:
            raise BizError("报价不属于该产品")
        for k, v in data.items():
            setattr(quote, k, v)
    else:
        exists = ctx.db.execute(
            select(ProductSupplier).where(
                ProductSupplier.product_id == product.id, ProductSupplier.supplier_id == data["supplier_id"]
            )
        ).scalar_one_or_none()
        if exists:
            raise BizError("该供应商报价已存在，请直接修改")
        quote = ProductSupplier(product_id=product.id, **data)
        ctx.db.add(quote)
    ctx.db.flush()
    if quote.is_default:
        ctx.db.execute(
            update(ProductSupplier)
            .where(ProductSupplier.product_id == product.id, ProductSupplier.id != quote.id)
            .values(is_default=False)
        )
        product.default_supplier_id = quote.supplier_id
        product.purchase_lead_days = quote.lead_days
        product.moq = quote.moq
    audit(ctx, "update", "product", product.id, f"维护供应商报价 {product.sku}")
    ctx.db.commit()
    return quote


# ---------------------------------------------------------------- Listing 配对
def pair_listing(ctx: Ctx, listing: Listing, product_id: int | None, pair_quantity: int = 1, apply_to_history: bool = True) -> Listing:
    from app.modules.order.models import SalesOrderItem

    ctx.require_shop(listing.shop_id)
    sku = None
    if product_id:
        product = get_or_404(ctx.db, Product, product_id, "产品")
        sku = product.sku
    listing.product_id = product_id
    listing.pair_quantity = pair_quantity
    if apply_to_history:
        ctx.db.execute(
            update(SalesOrderItem)
            .where(SalesOrderItem.shop_id == listing.shop_id, SalesOrderItem.msku == listing.msku)
            .values(product_id=product_id, sku=sku, listing_id=listing.id)
        )
    audit(ctx, "pair", "listing", listing.id, f"MSKU {listing.msku} 配对 SKU {sku or '（解除）'}")
    return listing


def auto_pair(ctx: Ctx, shop_id: int | None = None) -> int:
    """MSKU 与本地 SKU 完全一致时自动配对。"""
    stmt = select(Listing).where(Listing.product_id.is_(None))
    if shop_id:
        stmt = stmt.where(Listing.shop_id == shop_id)
    if ctx.shop_ids is not None:
        stmt = stmt.where(Listing.shop_id.in_(ctx.shop_ids))
    listings = ctx.db.execute(stmt).scalars().all()
    if not listings:
        return 0
    skus = {lst.msku for lst in listings}
    products = {p.sku: p for p in ctx.db.execute(select(Product).where(Product.sku.in_(skus))).scalars().all()}
    count = 0
    for lst in listings:
        p = products.get(lst.msku)
        if p:
            pair_listing(ctx, lst, p.id, 1, True)
            count += 1
    ctx.db.commit()
    return count


def upsert_listings(ctx: Ctx, shop, rows) -> tuple[int, int]:
    """平台 Listing 同步写入（按 店铺+MSKU）。新 Listing 若 MSKU 与本地 SKU 相同则自动配对。"""
    db = ctx.db
    existing = {x.msku: x for x in db.execute(select(Listing).where(Listing.shop_id == shop.id)).scalars().all()}
    new_mskus = [r.msku for r in rows if r.msku not in existing]
    products = {p.sku: p for p in db.execute(select(Product).where(Product.sku.in_(new_mskus))).scalars().all()} if new_mskus else {}
    created = updated = 0
    for r in rows:
        lst = existing.get(r.msku)
        if lst is None:
            lst = Listing(shop_id=shop.id, msku=r.msku, currency=r.currency or shop.currency)
            p = products.get(r.msku)
            if p is not None:
                lst.product_id = p.id
            db.add(lst)
            existing[r.msku] = lst
            created += 1
        else:
            updated += 1
        for f in ("asin", "parent_asin", "fnsku", "title", "image_url", "open_date"):
            v = getattr(r, f)
            if v is not None:
                setattr(lst, f, v)
        lst.price = r.price
        lst.status = r.status
        lst.fulfillment = r.fulfillment
        if r.currency:
            lst.currency = r.currency
    db.flush()
    return created, updated
