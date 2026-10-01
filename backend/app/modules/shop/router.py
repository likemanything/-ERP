from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.common.audit import audit
from app.common.crud import ensure_not_referenced, ensure_unique, get_or_404, keyword_filter
from app.common.enums import Platform
from app.common.pagination import PageParams, page_params, paginate
from app.common.schemas import Msg, Option, Page
from app.core.deps import Ctx, get_ctx, perm
from app.core.errors import BizError
from app.core.security import decrypt_json, encrypt_json
from app.modules.shop.marketplaces import get_marketplace, list_marketplaces
from app.modules.shop.models import Shop
from app.modules.shop.schemas import ShopIn, ShopOut, ShopUpdate

router = APIRouter(prefix="/shops", tags=["店铺授权"])

PLATFORM_NAMES = {
    "amazon": "亚马逊 Amazon", "shopify": "Shopify", "walmart": "沃尔玛 Walmart", "ebay": "eBay",
    "tiktok": "TikTok Shop", "temu": "Temu", "shein": "SHEIN", "aliexpress": "速卖通", "manual": "线下/手工",
    "distribution": "分销渠道",
}


def shop_out(shop: Shop) -> dict:
    creds = decrypt_json(shop.credentials_enc)
    data = {c.key: getattr(shop, c.key) for c in Shop.__table__.columns if c.key != "credentials_enc"}
    data["has_credentials"] = bool(creds)
    data["credential_keys"] = sorted(creds.keys())
    return data


def _apply_marketplace(shop: Shop, code: str | None) -> None:
    mp = get_marketplace(code)
    if code and mp is None:
        raise BizError(f"未知站点: {code}")
    if mp:
        if mp.platform != shop.platform:
            raise BizError("站点与平台不匹配")
        shop.country = mp.country
        shop.region = mp.region
        shop.currency = shop.currency or mp.currency
        shop.timezone = shop.timezone or mp.timezone


#: 支持平台仓发货的平台 → 虚拟仓名称前缀（Amazon FBA / Walmart WFS / TikTok FBT）
PLATFORM_WAREHOUSES = {Platform.AMAZON: "FBA", Platform.WALMART: "WFS", Platform.TIKTOK: "FBT"}


def ensure_fba_warehouse(ctx: Ctx, shop: Shop):
    """平台仓发货的店铺自动创建对应的平台虚拟仓（warehouse_type=fba），平台仓订单从这里结转成本。"""
    from app.modules.warehouse.models import Warehouse

    label = PLATFORM_WAREHOUSES.get(shop.platform)
    if label is None:
        return None
    wh = ctx.db.execute(
        select(Warehouse).where(Warehouse.shop_id == shop.id, Warehouse.warehouse_type == "fba")
    ).scalar_one_or_none()
    if wh is None:
        wh = Warehouse(
            code=f"{label}-{shop.id}",
            name=f"{label}仓-{shop.name}",
            warehouse_type="fba",
            country=shop.country,
            shop_id=shop.id,
        )
        ctx.db.add(wh)
        ctx.db.flush()
    return wh


@router.get("/platforms", summary="支持的平台")
def platforms(_: Ctx = Depends(get_ctx)):
    return [{"code": p.value, "name": PLATFORM_NAMES.get(p.value, p.value)} for p in Platform]


@router.get("/marketplaces", summary="平台站点")
def marketplaces(platform: str | None = None, _: Ctx = Depends(get_ctx)):
    return list_marketplaces(platform)


@router.get("", response_model=Page[ShopOut], summary="店铺列表")
def list_shops(
    keyword: str | None = None,
    platform: str | None = None,
    status: str | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("shop:view")),
):
    stmt = select(Shop).order_by(Shop.id)
    stmt = keyword_filter(stmt, keyword, [Shop.name, Shop.seller_id])
    if platform:
        stmt = stmt.where(Shop.platform == platform)
    if status:
        stmt = stmt.where(Shop.status == status)
    if ctx.shop_ids is not None:
        stmt = stmt.where(Shop.id.in_(ctx.shop_ids))
    page = paginate(ctx.db, stmt, params)
    page["items"] = [shop_out(s) for s in page["items"]]
    return page


@router.get("/options", response_model=list[Option], summary="店铺下拉（按数据权限）")
def shop_options(platform: str | None = None, ctx: Ctx = Depends(get_ctx)):
    stmt = select(Shop).order_by(Shop.id)
    if platform:
        stmt = stmt.where(Shop.platform == platform)
    if ctx.shop_ids is not None:
        stmt = stmt.where(Shop.id.in_(ctx.shop_ids))
    return [Option(value=s.id, label=s.name) for s in ctx.db.execute(stmt).scalars().all()]


@router.get("/{shop_id}", response_model=ShopOut, summary="店铺详情")
def get_shop(shop_id: int, ctx: Ctx = Depends(perm("shop:view"))):
    ctx.require_shop(shop_id)
    return shop_out(get_or_404(ctx.db, Shop, shop_id, "店铺"))


@router.post("", response_model=ShopOut, summary="新增店铺")
def create_shop(body: ShopIn, ctx: Ctx = Depends(perm("shop:edit"))):
    if body.platform not in {p.value for p in Platform}:
        raise BizError(f"不支持的平台: {body.platform}")
    ensure_unique(ctx.db, Shop, "name", body.name, label="店铺名称")
    data = body.model_dump(exclude={"credentials"})
    shop = Shop(**data)
    _apply_marketplace(shop, body.marketplace_code)
    shop.currency = (shop.currency or "USD").upper()
    shop.timezone = shop.timezone or "UTC"
    shop.credentials_enc = encrypt_json(body.credentials)
    ctx.db.add(shop)
    ctx.db.flush()
    ensure_fba_warehouse(ctx, shop)
    audit(ctx, "create", "shop", shop.id, f"新增店铺 {shop.name}")
    ctx.db.commit()
    return shop_out(shop)


@router.put("/{shop_id}", response_model=ShopOut, summary="修改店铺")
def update_shop(shop_id: int, body: ShopUpdate, ctx: Ctx = Depends(perm("shop:edit"))):
    ctx.require_shop(shop_id)
    shop = get_or_404(ctx.db, Shop, shop_id, "店铺")
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        ensure_unique(ctx.db, Shop, "name", data["name"], exclude_id=shop.id, label="店铺名称")
    creds = data.pop("credentials", None)
    for k, v in data.items():
        setattr(shop, k, v)
    if "marketplace_code" in data:
        _apply_marketplace(shop, data["marketplace_code"])
    if creds is not None:
        # 合并更新：值为空字符串表示删除该键
        merged = decrypt_json(shop.credentials_enc)
        for k, v in creds.items():
            if v == "":
                merged.pop(k, None)
            else:
                merged[k] = v
        shop.credentials_enc = encrypt_json(merged)
        if shop.status == "auth_expired":
            shop.status = "active"
    ensure_fba_warehouse(ctx, shop)
    audit(ctx, "update", "shop", shop.id, f"修改店铺 {shop.name}", {"fields": list(data.keys())})
    ctx.db.commit()
    return shop_out(shop)


@router.delete("/{shop_id}", response_model=Msg, summary="删除店铺")
def delete_shop(shop_id: int, ctx: Ctx = Depends(perm("shop:edit"))):
    from app.modules.order.models import SalesOrder
    from app.modules.product.models import Listing
    from app.modules.warehouse.models import InventoryBalance, Warehouse

    shop = get_or_404(ctx.db, Shop, shop_id, "店铺")
    ensure_not_referenced(
        ctx.db,
        [
            (SalesOrder, SalesOrder.shop_id == shop.id, "订单"),
            (Listing, Listing.shop_id == shop.id, "Listing"),
        ],
    )
    fba_wh = ctx.db.execute(select(Warehouse).where(Warehouse.shop_id == shop.id)).scalars().all()
    for wh in fba_wh:
        ensure_not_referenced(ctx.db, [(InventoryBalance, InventoryBalance.warehouse_id == wh.id, "库存")])
        ctx.db.delete(wh)
    ctx.db.delete(shop)
    audit(ctx, "delete", "shop", shop_id, f"删除店铺 {shop.name}")
    ctx.db.commit()
    return Msg(message="已删除")
