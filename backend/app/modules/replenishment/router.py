from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import Field

from app.common.excel import export_xlsx
from app.common.schemas import Msg, Schema
from app.core.deps import Ctx, perm
from app.modules.replenishment import service
from app.modules.replenishment.models import ReplenishmentRule

router = APIRouter(prefix="/replenishment", tags=["补货建议"])


class RuleIn(Schema):
    purchase_lead_days: int | None = Field(default=None, ge=0)
    inspection_days: int | None = Field(default=None, ge=0)
    transit_days: int | None = Field(default=None, ge=0)
    safety_days: int | None = Field(default=None, ge=0)
    cover_days: int | None = Field(default=None, ge=0)
    weight_7d: Decimal | None = Field(default=None, ge=0)
    weight_14d: Decimal | None = Field(default=None, ge=0)
    weight_30d: Decimal | None = Field(default=None, ge=0)
    growth_factor: Decimal | None = Field(default=None, gt=0)
    remark: str | None = None


class RuleOut(RuleIn):
    id: int
    listing_id: int | None = None


class ListingSuggestion(Schema):
    listing_id: int
    shop_id: int
    shop_name: str | None = None
    msku: str
    asin: str | None = None
    fnsku: str | None = None
    title: str | None = None
    image_url: str | None = None
    product_id: int | None = None
    sku: str | None = None
    sales_7d: int
    sales_14d: int
    sales_30d: int
    daily_sales: float
    fba_available: int
    fba_inbound: int
    local_available: int
    available_days: float | None = None
    total_days: float | None = None
    out_of_stock_date: date | None = None
    suggest_ship_qty: int
    suggest_ship_date: date | None = None
    transit_days: int
    safety_days: int
    cover_days: int
    has_custom_rule: bool = False


class PurchaseSuggestion(Schema):
    product_id: int
    sku: str
    product_name: str
    image_url: str | None = None
    supplier_id: int | None = None
    moq: int
    purchase_lead_days: int
    sales_30d: int
    daily_sales: float
    local_available: int
    fba_total: int
    purchase_in_transit: int
    planned_qty: int
    total_supply: int
    supply_days: float | None = None
    suggest_purchase_qty: int
    latest_order_date: date | None = None


class PlanItem(Schema):
    product_id: int
    qty: int
    supplier_id: int | None = None


class ToPurchasePlansIn(Schema):
    items: list[PlanItem] = Field(min_length=1)
    warehouse_id: int | None = None


class ShipItem(Schema):
    listing_id: int
    qty: int


class ToShipmentPlansIn(Schema):
    items: list[ShipItem] = Field(min_length=1)
    ship_from_warehouse_id: int


@router.get("/rule", response_model=RuleOut, summary="默认补货参数")
def get_default_rule(ctx: Ctx = Depends(perm("replenish:view"))):
    rule = service.default_rule(ctx)
    ctx.db.commit()
    return rule


@router.put("/rule", response_model=RuleOut, summary="修改默认补货参数")
def put_default_rule(body: RuleIn, ctx: Ctx = Depends(perm("replenish:edit"))):
    return service.save_rule(ctx, None, body.model_dump(exclude_unset=True))


@router.get("/rules/{listing_id}", response_model=RuleOut | None, summary="Listing 个性化补货参数")
def get_listing_rule(listing_id: int, ctx: Ctx = Depends(perm("replenish:view"))):
    from sqlalchemy import select

    return ctx.db.execute(select(ReplenishmentRule).where(ReplenishmentRule.listing_id == listing_id)).scalar_one_or_none()


@router.put("/rules/{listing_id}", response_model=RuleOut, summary="设置 Listing 个性化补货参数（空字段继承默认）")
def put_listing_rule(listing_id: int, body: RuleIn, ctx: Ctx = Depends(perm("replenish:edit"))):
    return service.save_rule(ctx, listing_id, body.model_dump())


@router.get("/listings", response_model=list[ListingSuggestion], summary="FBA 发货建议（按 Listing）")
def listing_suggestions(shop_id: int | None = None, keyword: str | None = None, only_need: bool = False,
                        ctx: Ctx = Depends(perm("replenish:view"))):
    return service.listing_suggestions(ctx, shop_id=shop_id, keyword=keyword, only_need=only_need)


@router.get("/listings/export", summary="导出发货建议")
def export_listing_suggestions(shop_id: int | None = None, only_need: bool = False, ctx: Ctx = Depends(perm("replenish:view"))):
    rows = service.listing_suggestions(ctx, shop_id=shop_id, only_need=only_need)
    cols = [("shop_name", "店铺"), ("msku", "MSKU"), ("asin", "ASIN"), ("sku", "SKU"), ("sales_7d", "7天销量"),
            ("sales_14d", "14天销量"), ("sales_30d", "30天销量"), ("daily_sales", "日均"), ("fba_available", "FBA可售"),
            ("fba_inbound", "FBA在途"), ("local_available", "本地可用"), ("available_days", "可售天数"),
            ("out_of_stock_date", "预计断货"), ("suggest_ship_qty", "建议发货量"), ("suggest_ship_date", "建议发货日")]
    return export_xlsx("FBA发货建议.xlsx", cols, rows)


@router.get("/products", response_model=list[PurchaseSuggestion], summary="采购建议（按 SKU）")
def purchase_suggestions(keyword: str | None = None, only_need: bool = False, ctx: Ctx = Depends(perm("replenish:view"))):
    return service.purchase_suggestions(ctx, keyword=keyword, only_need=only_need)


@router.post("/to-purchase-plans", response_model=Msg, summary="按建议生成采购计划")
def to_purchase_plans(body: ToPurchasePlansIn, ctx: Ctx = Depends(perm("replenish:edit"))):
    ctx.require("purchase:plan:edit")
    n = service.create_purchase_plans(ctx, [i.model_dump() for i in body.items], body.warehouse_id)
    return Msg(message=f"已生成 {n} 条采购计划")


@router.post("/to-shipment-plans", response_model=Msg, summary="按建议生成发货计划")
def to_shipment_plans(body: ToShipmentPlansIn, ctx: Ctx = Depends(perm("replenish:edit"))):
    ctx.require("fba:plan:edit")
    n = service.create_shipment_plans(ctx, [i.model_dump() for i in body.items], body.ship_from_warehouse_id)
    return Msg(message=f"已生成 {n} 张发货计划")
