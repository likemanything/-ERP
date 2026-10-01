from decimal import Decimal

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select

from app.common.audit import audit
from app.common.crud import build_crud_router, ensure_not_referenced, get_or_404, keyword_filter
from app.common.excel import export_xlsx, read_upload, template_response
from app.common.pagination import PageParams, page_params, paginate
from app.common.schemas import Msg, Page
from app.core.deps import Ctx, get_ctx, perm
from app.core.errors import BizError
from app.modules.product import service
from app.modules.product.models import Brand, Category, Listing, Product, ProductSupplier
from app.modules.product.schemas import (
    BrandIn,
    BrandOut,
    BrandUpdate,
    CategoryIn,
    CategoryOut,
    CategoryUpdate,
    ImportResult,
    ListingIn,
    ListingOut,
    ListingUpdate,
    PairIn,
    ProductBrief,
    ProductIn,
    ProductOut,
    ProductSupplierIn,
    ProductSupplierOut,
    ProductUpdate,
)
from app.modules.shop.models import Shop

router = APIRouter(tags=["产品管理"])


# ------------------------------------------------------------------ 分类 / 品牌
def _category_before_delete(ctx: Ctx, cat: Category) -> None:
    ensure_not_referenced(
        ctx.db,
        [(Product, Product.category_id == cat.id, "产品"), (Category, Category.parent_id == cat.id, "下级分类")],
    )


def _brand_before_delete(ctx: Ctx, brand: Brand) -> None:
    ensure_not_referenced(ctx.db, [(Product, Product.brand_id == brand.id, "产品")])


router.include_router(
    build_crud_router(
        model=Category, create_schema=CategoryIn, update_schema=CategoryUpdate, out_schema=CategoryOut,
        resource="category", label="产品分类", view_perm="product:view", edit_perm="product:edit",
        search_fields=("name", "code"), filter_fields=("parent_id",), default_order=("sort", "id"),
        before_delete=_category_before_delete,
    ),
    prefix="/product-categories",
)
router.include_router(
    build_crud_router(
        model=Brand, create_schema=BrandIn, update_schema=BrandUpdate, out_schema=BrandOut,
        resource="brand", label="品牌", view_perm="product:view", edit_perm="product:edit",
        search_fields=("name", "code"), unique_fields=("name",), default_order=("id",),
        before_delete=_brand_before_delete,
    ),
    prefix="/product-brands",
)


# ------------------------------------------------------------------ 产品
PRODUCT_COLUMNS = [
    ("sku", "SKU"), ("name", "品名"), ("name_en", "英文名"), ("barcode", "商品条码"), ("spu", "SPU"), ("category_name", "分类"),
    ("brand_name", "品牌"), ("product_type", "类型"), ("status", "状态"), ("unit", "单位"),
    ("purchase_cost", "采购成本"), ("purchase_lead_days", "采购交期"), ("moq", "起订量"),
    ("weight_kg", "单品重量kg"), ("length_cm", "长cm"), ("width_cm", "宽cm"), ("height_cm", "高cm"),
    ("units_per_carton", "单箱数量"), ("carton_weight_kg", "箱重kg"), ("carton_length_cm", "箱长cm"),
    ("carton_width_cm", "箱宽cm"), ("carton_height_cm", "箱高cm"), ("declare_name_cn", "中文报关名"),
    ("declare_name_en", "英文报关名"), ("declare_value_usd", "申报价值USD"), ("hs_code", "海关编码"),
    ("material", "材质"), ("usage", "用途"), ("image_url", "图片链接"), ("remark", "备注"),
]


def _product_query(keyword, category_id, brand_id, status, product_type, spu):
    stmt = select(Product).order_by(Product.id.desc())
    stmt = keyword_filter(stmt, keyword, [Product.sku, Product.name, Product.name_en, Product.spu, Product.barcode])
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    if brand_id:
        stmt = stmt.where(Product.brand_id == brand_id)
    if status:
        stmt = stmt.where(Product.status == status)
    if product_type:
        stmt = stmt.where(Product.product_type == product_type)
    if spu:
        stmt = stmt.where(Product.spu == spu)
    return stmt


@router.get("/products", response_model=Page[ProductOut], summary="产品列表")
def list_products(
    keyword: str | None = None,
    category_id: int | None = None,
    brand_id: int | None = None,
    status: str | None = None,
    product_type: str | None = None,
    spu: str | None = None,
    with_stock: bool = True,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("product:view")),
):
    page = paginate(ctx.db, _product_query(keyword, category_id, brand_id, status, product_type, spu), params)
    page["items"] = service.product_out(ctx.db, page["items"], show_cost=ctx.can("product:cost:view"), with_stock=with_stock)
    return page


@router.get("/products/options", response_model=list[ProductBrief], summary="产品搜索下拉")
def product_options(
    keyword: str | None = None,
    product_type: str | None = None,
    exclude_bundle: bool = False,
    ids: str | None = None,
    ctx: Ctx = Depends(get_ctx),
):
    stmt = select(Product).order_by(Product.sku)
    if ids:
        stmt = stmt.where(Product.id.in_([int(x) for x in ids.split(",") if x.strip().isdigit()]))
    else:
        stmt = keyword_filter(stmt, keyword, [Product.sku, Product.name]).limit(50)
    if product_type:
        stmt = stmt.where(Product.product_type == product_type)
    if exclude_bundle:
        stmt = stmt.where(Product.product_type != "bundle")
    return ctx.db.execute(stmt).scalars().all()


@router.get("/products/export", summary="导出产品")
def export_products(
    keyword: str | None = None,
    category_id: int | None = None,
    brand_id: int | None = None,
    status: str | None = None,
    product_type: str | None = None,
    spu: str | None = None,
    ctx: Ctx = Depends(perm("product:view")),
):
    rows = ctx.db.execute(_product_query(keyword, category_id, brand_id, status, product_type, spu)).scalars().all()
    data = service.product_out(ctx.db, rows, show_cost=ctx.can("product:cost:view"))
    return export_xlsx("产品列表.xlsx", PRODUCT_COLUMNS, data)


@router.get("/products/import-template", summary="产品导入模板")
def product_template(_: Ctx = Depends(perm("product:edit"))):
    sample = {"sku": "SKU-001", "name": "示例产品", "product_type": "normal", "status": "on_sale", "unit": "个",
              "purchase_cost": 12.5, "weight_kg": 0.35, "units_per_carton": 40}
    return template_response("产品导入模板.xlsx", PRODUCT_COLUMNS, sample)


@router.post("/products/import", response_model=ImportResult, summary="导入产品（按 SKU 新增或更新）")
def import_products(file: UploadFile = File(...), ctx: Ctx = Depends(perm("product:edit"))):
    rows = read_upload(file, PRODUCT_COLUMNS)
    result = ImportResult()
    cats = {c.name: c.id for c in ctx.db.execute(select(Category)).scalars().all()}
    brands = {b.name: b.id for b in ctx.db.execute(select(Brand)).scalars().all()}
    numeric = {"purchase_cost", "weight_kg", "length_cm", "width_cm", "height_cm", "carton_weight_kg",
               "carton_length_cm", "carton_width_cm", "carton_height_cm", "declare_value_usd"}
    ints = {"purchase_lead_days", "moq", "units_per_carton"}
    for row in rows:
        new_cats: list[str] = []
        new_brands: list[str] = []
        sp = ctx.db.begin_nested()
        try:
            sku = str(row.get("sku") or "").strip()
            if not sku:
                raise BizError("SKU 不能为空")
            data: dict = {}
            for key, _title in PRODUCT_COLUMNS:
                if key in ("sku", "category_name", "brand_name") or key not in row or row[key] in (None, ""):
                    continue
                v = row[key]
                if key in numeric:
                    v = Decimal(str(v))
                elif key in ints:
                    v = int(v)
                else:
                    v = str(v)
                data[key] = v
            if row.get("category_name"):
                name = str(row["category_name"])
                if name not in cats:
                    cat = Category(name=name)
                    ctx.db.add(cat)
                    ctx.db.flush()
                    cats[name] = cat.id
                    new_cats.append(name)
                data["category_id"] = cats[name]
            if row.get("brand_name"):
                name = str(row["brand_name"])
                if name not in brands:
                    brand = Brand(name=name)
                    ctx.db.add(brand)
                    ctx.db.flush()
                    brands[name] = brand.id
                    new_brands.append(name)
                data["brand_id"] = brands[name]
            if data.get("product_type") == "bundle":
                raise BizError("组合产品请在页面中创建")
            service.validate_product_fields(data)
            existing = ctx.db.execute(select(Product).where(Product.sku == sku)).scalar_one_or_none()
            if existing:
                for k, v in data.items():
                    setattr(existing, k, v)
                result.updated += 1
            else:
                if not data.get("name"):
                    raise BizError("品名不能为空")
                ctx.db.add(Product(sku=sku, **data))
                result.created += 1
            ctx.db.flush()
            sp.commit()
        except Exception as exc:  # noqa: BLE001
            sp.rollback()
            for name in new_cats:
                cats.pop(name, None)
            for name in new_brands:
                brands.pop(name, None)
            result.skipped += 1
            msg = exc.message if isinstance(exc, BizError) else str(exc)
            result.errors.append(f"第 {row['_row']} 行: {msg}")
    audit(ctx, "import", "product", None, f"导入产品：新增 {result.created}，更新 {result.updated}，失败 {result.skipped}")
    ctx.db.commit()
    return result


@router.get("/products/{product_id}", response_model=ProductOut, summary="产品详情")
def get_product(product_id: int, ctx: Ctx = Depends(perm("product:view"))):
    p = get_or_404(ctx.db, Product, product_id, "产品")
    return service.product_out(ctx.db, [p], show_cost=ctx.can("product:cost:view"), with_stock=True)[0]


@router.post("/products", response_model=ProductOut, summary="新增产品")
def create_product(body: ProductIn, ctx: Ctx = Depends(perm("product:edit"))):
    p = service.create_product(ctx, body.model_dump())
    return service.product_out(ctx.db, [p], show_cost=ctx.can("product:cost:view"))[0]


@router.put("/products/{product_id}", response_model=ProductOut, summary="修改产品")
def update_product(product_id: int, body: ProductUpdate, ctx: Ctx = Depends(perm("product:edit"))):
    data = body.model_dump(exclude_unset=True)
    if "purchase_cost" in data and not ctx.can("product:cost:view"):
        data.pop("purchase_cost")
    p = service.update_product(ctx, product_id, data)
    return service.product_out(ctx.db, [p], show_cost=ctx.can("product:cost:view"))[0]


@router.delete("/products/{product_id}", response_model=Msg, summary="删除产品")
def delete_product(product_id: int, ctx: Ctx = Depends(perm("product:delete"))):
    service.delete_product(ctx, product_id)
    return Msg(message="已删除")


# ------------------------------------------------------------------ 供应商报价
def _quote_out(db, quotes):
    from app.modules.supplier.models import Supplier

    ids = {q.supplier_id for q in quotes}
    names = dict(db.execute(select(Supplier.id, Supplier.name).where(Supplier.id.in_(ids))).all()) if ids else {}
    return [{**{c.key: getattr(q, c.key) for c in ProductSupplier.__table__.columns}, "supplier_name": names.get(q.supplier_id)} for q in quotes]


@router.get("/products/{product_id}/suppliers", response_model=list[ProductSupplierOut], summary="产品供应商报价")
def list_product_suppliers(product_id: int, ctx: Ctx = Depends(perm("product:view"))):
    quotes = ctx.db.execute(
        select(ProductSupplier).where(ProductSupplier.product_id == product_id).order_by(ProductSupplier.id)
    ).scalars().all()
    return _quote_out(ctx.db, quotes)


@router.post("/products/{product_id}/suppliers", response_model=ProductSupplierOut, summary="新增供应商报价")
def add_product_supplier(product_id: int, body: ProductSupplierIn, ctx: Ctx = Depends(perm("product:edit"))):
    q = service.upsert_product_supplier(ctx, product_id, body.model_dump())
    return _quote_out(ctx.db, [q])[0]


@router.put("/products/{product_id}/suppliers/{quote_id}", response_model=ProductSupplierOut, summary="修改供应商报价")
def update_product_supplier(product_id: int, quote_id: int, body: ProductSupplierIn, ctx: Ctx = Depends(perm("product:edit"))):
    q = service.upsert_product_supplier(ctx, product_id, body.model_dump(), quote_id)
    return _quote_out(ctx.db, [q])[0]


@router.delete("/products/{product_id}/suppliers/{quote_id}", response_model=Msg, summary="删除供应商报价")
def delete_product_supplier(product_id: int, quote_id: int, ctx: Ctx = Depends(perm("product:edit"))):
    q = get_or_404(ctx.db, ProductSupplier, quote_id, "供应商报价")
    if q.product_id != product_id:
        raise BizError("报价不属于该产品")
    ctx.db.delete(q)
    ctx.db.commit()
    return Msg(message="已删除")


# ------------------------------------------------------------------ Listing
LISTING_COLUMNS = [
    ("shop_name", "店铺"), ("msku", "MSKU"), ("asin", "ASIN"), ("fnsku", "FNSKU"), ("title", "标题"),
    ("price", "售价"), ("currency", "币种"), ("status", "状态"), ("fulfillment", "配送方式"),
    ("sku", "配对SKU"), ("pair_quantity", "配对数量"),
]


def listing_out(db, listings) -> list[dict]:
    listings = list(listings)
    shop_ids = {x.shop_id for x in listings}
    shops = dict(db.execute(select(Shop.id, Shop.name).where(Shop.id.in_(shop_ids))).all()) if shop_ids else {}
    result = []
    for x in listings:
        d = {c.key: getattr(x, c.key) for c in Listing.__table__.columns}
        d["shop_name"] = shops.get(x.shop_id)
        d["sku"] = x.product.sku if x.product else None
        d["product_name"] = x.product.name if x.product else None
        result.append(d)
    return result


def _listing_query(ctx: Ctx, keyword, shop_id, status, fulfillment, paired, product_id):
    stmt = select(Listing).order_by(Listing.id.desc())
    stmt = keyword_filter(stmt, keyword, [Listing.msku, Listing.asin, Listing.fnsku, Listing.title, Listing.parent_asin])
    if shop_id:
        stmt = stmt.where(Listing.shop_id == shop_id)
    if status:
        stmt = stmt.where(Listing.status == status)
    if fulfillment:
        stmt = stmt.where(Listing.fulfillment == fulfillment)
    if paired is not None:
        stmt = stmt.where(Listing.product_id.is_not(None) if paired else Listing.product_id.is_(None))
    if product_id:
        stmt = stmt.where(Listing.product_id == product_id)
    if ctx.shop_ids is not None:
        stmt = stmt.where(Listing.shop_id.in_(ctx.shop_ids))
    return stmt


@router.get("/listings", response_model=Page[ListingOut], summary="Listing 列表")
def list_listings(
    keyword: str | None = None,
    shop_id: int | None = None,
    status: str | None = None,
    fulfillment: str | None = None,
    paired: bool | None = None,
    product_id: int | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("listing:view")),
):
    page = paginate(ctx.db, _listing_query(ctx, keyword, shop_id, status, fulfillment, paired, product_id), params)
    page["items"] = listing_out(ctx.db, page["items"])
    return page


@router.get("/listings/options", summary="Listing 搜索下拉")
def listing_options(keyword: str | None = None, shop_id: int | None = None, ctx: Ctx = Depends(get_ctx)):
    stmt = _listing_query(ctx, keyword, shop_id, None, None, None, None).limit(50)
    return [
        {"value": x["id"], "label": f"{x['msku']} ({x['asin'] or '-'})", "msku": x["msku"], "fnsku": x["fnsku"],
         "product_id": x["product_id"], "sku": x["sku"], "shop_id": x["shop_id"]}
        for x in listing_out(ctx.db, ctx.db.execute(stmt).scalars().all())
    ]


@router.get("/listings/export", summary="导出 Listing")
def export_listings(
    keyword: str | None = None,
    shop_id: int | None = None,
    status: str | None = None,
    fulfillment: str | None = None,
    paired: bool | None = None,
    ctx: Ctx = Depends(perm("listing:view")),
):
    rows = ctx.db.execute(_listing_query(ctx, keyword, shop_id, status, fulfillment, paired, None)).scalars().all()
    return export_xlsx("Listing.xlsx", LISTING_COLUMNS, listing_out(ctx.db, rows))


@router.post("/listings", response_model=ListingOut, summary="新增 Listing（手工）")
def create_listing(body: ListingIn, ctx: Ctx = Depends(perm("listing:edit"))):
    ctx.require_shop(body.shop_id)
    shop = get_or_404(ctx.db, Shop, body.shop_id, "店铺")
    exists = ctx.db.execute(select(Listing.id).where(Listing.shop_id == shop.id, Listing.msku == body.msku)).first()
    if exists:
        raise BizError(f"店铺下 MSKU {body.msku} 已存在")
    data = body.model_dump()
    data["currency"] = data.get("currency") or shop.currency
    product_id = data.pop("product_id")
    pair_quantity = data.pop("pair_quantity")
    listing = Listing(**data)
    ctx.db.add(listing)
    ctx.db.flush()
    if product_id:
        service.pair_listing(ctx, listing, product_id, pair_quantity)
    audit(ctx, "create", "listing", listing.id, f"新增 Listing {listing.msku}")
    ctx.db.commit()
    ctx.db.refresh(listing)
    return listing_out(ctx.db, [listing])[0]


@router.put("/listings/{listing_id}", response_model=ListingOut, summary="修改 Listing")
def update_listing(listing_id: int, body: ListingUpdate, ctx: Ctx = Depends(perm("listing:edit"))):
    listing = get_or_404(ctx.db, Listing, listing_id, "Listing")
    ctx.require_shop(listing.shop_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(listing, k, v)
    ctx.db.commit()
    ctx.db.refresh(listing)
    return listing_out(ctx.db, [listing])[0]


@router.post("/listings/{listing_id}/pair", response_model=ListingOut, summary="MSKU 配对本地 SKU")
def pair(listing_id: int, body: PairIn, ctx: Ctx = Depends(perm("listing:edit"))):
    listing = get_or_404(ctx.db, Listing, listing_id, "Listing")
    service.pair_listing(ctx, listing, body.product_id, body.pair_quantity, body.apply_to_history)
    ctx.db.commit()
    ctx.db.refresh(listing)
    return listing_out(ctx.db, [listing])[0]


@router.post("/listings/auto-pair", response_model=Msg, summary="自动配对（MSKU 与 SKU 相同）")
def auto_pair(shop_id: int | None = None, ctx: Ctx = Depends(perm("listing:edit"))):
    n = service.auto_pair(ctx, shop_id)
    return Msg(message=f"已自动配对 {n} 个 Listing")


PAIR_COLUMNS = [("shop_name", "店铺"), ("msku", "MSKU"), ("sku", "SKU"), ("pair_quantity", "配对数量")]


@router.post("/listings/import-pair", response_model=ImportResult, summary="Excel 批量配对")
def import_pair(file: UploadFile = File(...), ctx: Ctx = Depends(perm("listing:edit"))):
    rows = read_upload(file, PAIR_COLUMNS)
    shops = {s.name: s.id for s in ctx.db.execute(select(Shop)).scalars().all()}
    result = ImportResult()
    for row in rows:
        sp = ctx.db.begin_nested()
        try:
            shop_id = shops.get(str(row.get("shop_name") or ""))
            if not shop_id:
                raise BizError(f"店铺不存在: {row.get('shop_name')}")
            listing = ctx.db.execute(
                select(Listing).where(Listing.shop_id == shop_id, Listing.msku == str(row.get("msku") or ""))
            ).scalar_one_or_none()
            if listing is None:
                raise BizError(f"MSKU 不存在: {row.get('msku')}")
            product = ctx.db.execute(select(Product).where(Product.sku == str(row.get("sku") or ""))).scalar_one_or_none()
            if product is None:
                raise BizError(f"SKU 不存在: {row.get('sku')}")
            service.pair_listing(ctx, listing, product.id, int(row.get("pair_quantity") or 1))
            sp.commit()
            result.updated += 1
        except Exception as exc:  # noqa: BLE001
            sp.rollback()
            result.skipped += 1
            result.errors.append(f"第 {row['_row']} 行: {exc.message if isinstance(exc, BizError) else exc}")
    ctx.db.commit()
    return result


@router.get("/listings/pair-template", summary="批量配对模板")
def pair_template(_: Ctx = Depends(perm("listing:edit"))):
    return template_response("Listing配对模板.xlsx", PAIR_COLUMNS, {"shop_name": "店铺名", "msku": "MSKU-1", "sku": "SKU-001", "pair_quantity": 1})


@router.delete("/listings/{listing_id}", response_model=Msg, summary="删除 Listing")
def delete_listing(listing_id: int, ctx: Ctx = Depends(perm("listing:edit"))):
    listing = get_or_404(ctx.db, Listing, listing_id, "Listing")
    ctx.require_shop(listing.shop_id)
    ctx.db.delete(listing)
    audit(ctx, "delete", "listing", listing_id, f"删除 Listing {listing.msku}")
    ctx.db.commit()
    return Msg(message="已删除")


@router.get("/listings/{listing_id}", response_model=ListingOut, summary="Listing 详情")
def get_listing(listing_id: int, ctx: Ctx = Depends(perm("listing:view"))):
    listing = get_or_404(ctx.db, Listing, listing_id, "Listing")
    ctx.require_shop(listing.shop_id)
    return listing_out(ctx.db, [listing])[0]

