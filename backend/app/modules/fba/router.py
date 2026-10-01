from datetime import timedelta

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import func, select

from app.common.audit import audit
from app.common.crud import get_or_404, keyword_filter
from app.common.enums import PlanStatus
from app.common.excel import read_upload, template_response
from app.common.pagination import PageParams, page_params, paginate
from app.common.schemas import IdsIn, Msg, Page
from app.core.deps import Ctx, perm
from app.core.errors import BizError
from app.core.types import utcnow
from app.integrations.dto import FbaInventoryDTO
from app.modules.fba import service
from app.modules.fba.models import FbaInventory, FbaShipment, FbaShipmentLine, ShipmentPlan
from app.modules.fba.schemas import (
    CostUpdateIn,
    FbaInventoryOut,
    ShipmentIn,
    ShipmentOut,
    ShipmentPlanIn,
    ShipmentPlanOut,
    ShipmentPlanUpdate,
    ShipmentReceiveIn,
    ShipmentUpdate,
)
from app.modules.logistics.models import LogisticsChannel
from app.modules.order.models import SalesOrder, SalesOrderItem
from app.modules.product.models import Listing, Product
from app.modules.product.schemas import ImportResult
from app.modules.product.service import available_stock
from app.modules.shop.models import Shop
from app.modules.warehouse.models import Warehouse

router = APIRouter(tags=["FBA 管理"])


def _names(db, model, ids, attr="name") -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.execute(select(model.id, getattr(model, attr)).where(model.id.in_(ids))).all())


def _products(db, ids) -> dict[int, Product]:
    ids = {i for i in ids if i}
    return {p.id: p for p in db.execute(select(Product).where(Product.id.in_(ids))).scalars().all()} if ids else {}


# ================================================================ 发货计划
def plan_out(ctx: Ctx, plans) -> list[dict]:
    plans = list(plans)
    db = ctx.db
    shops = _names(db, Shop, [p.shop_id for p in plans])
    whs = _names(db, Warehouse, [p.ship_from_warehouse_id for p in plans])
    products = _products(db, [ln.product_id for p in plans for ln in p.lines])
    stock = available_stock(db, list({ln.product_id for p in plans for ln in p.lines}))
    out = []
    for p in plans:
        d = {c.key: getattr(p, c.key) for c in ShipmentPlan.__table__.columns}
        d.update(shop_name=shops.get(p.shop_id), ship_from_warehouse_name=whs.get(p.ship_from_warehouse_id),
                 total_qty=sum(ln.qty for ln in p.lines))
        d["lines"] = [
            {"id": ln.id, "listing_id": ln.listing_id, "msku": ln.msku, "fnsku": ln.fnsku, "product_id": ln.product_id,
             "sku": products[ln.product_id].sku if ln.product_id in products else None,
             "product_name": products[ln.product_id].name if ln.product_id in products else None,
             "qty": ln.qty, "stock_available": stock.get(ln.product_id, 0)}
            for ln in p.lines
        ]
        out.append(d)
    return out


@router.get("/shipment-plans", response_model=Page[ShipmentPlanOut], summary="发货计划列表")
def list_plans(
    keyword: str | None = None,
    shop_id: int | None = None,
    status: str | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("fba:plan:view")),
):
    stmt = select(ShipmentPlan).order_by(ShipmentPlan.id.desc())
    stmt = keyword_filter(stmt, keyword, [ShipmentPlan.plan_no, ShipmentPlan.remark])
    if shop_id:
        stmt = stmt.where(ShipmentPlan.shop_id == shop_id)
    if status:
        stmt = stmt.where(ShipmentPlan.status == status)
    if ctx.shop_ids is not None:
        stmt = stmt.where(ShipmentPlan.shop_id.in_(ctx.shop_ids))
    page = paginate(ctx.db, stmt, params)
    page["items"] = plan_out(ctx, page["items"])
    return page


@router.post("/shipment-plans", response_model=ShipmentPlanOut, summary="新建发货计划")
def create_plan(body: ShipmentPlanIn, ctx: Ctx = Depends(perm("fba:plan:edit"))):
    plan = service.create_plan(ctx, body.model_dump())
    ctx.db.commit()
    return plan_out(ctx, [plan])[0]


@router.put("/shipment-plans/{plan_id}", response_model=ShipmentPlanOut, summary="修改发货计划")
def update_plan(plan_id: int, body: ShipmentPlanUpdate, ctx: Ctx = Depends(perm("fba:plan:edit"))):
    return plan_out(ctx, [service.update_plan(ctx, plan_id, body.model_dump(exclude_unset=True))])[0]


@router.post("/shipment-plans/cancel", response_model=Msg, summary="作废发货计划")
def cancel_plans(body: IdsIn, ctx: Ctx = Depends(perm("fba:plan:edit"))):
    n = 0
    for p in ctx.db.execute(select(ShipmentPlan).where(ShipmentPlan.id.in_(body.ids))).scalars().all():
        ctx.require_shop(p.shop_id)
        if p.status == PlanStatus.PENDING:
            p.status = PlanStatus.CANCELLED
            n += 1
    ctx.db.commit()
    return Msg(message=f"已作废 {n} 条")


@router.post("/shipment-plans/{plan_id}/to-shipment", response_model=ShipmentOut, summary="发货计划生成货件")
def plan_to_shipment(plan_id: int, ctx: Ctx = Depends(perm("fba:shipment:edit"))):
    return shipment_out(ctx, [service.plan_to_shipment(ctx, plan_id)])[0]


# ================================================================ 货件
def shipment_out(ctx: Ctx, shipments) -> list[dict]:
    shipments = list(shipments)
    db = ctx.db
    shops = _names(db, Shop, [s.shop_id for s in shipments])
    whs = _names(db, Warehouse, [s.ship_from_warehouse_id for s in shipments] + [s.to_warehouse_id for s in shipments])
    chs = _names(db, LogisticsChannel, [s.logistics_channel_id for s in shipments])
    products = _products(db, [ln.product_id for s in shipments for ln in s.lines])
    show_cost = ctx.can("product:cost:view")
    out = []
    for s in shipments:
        d = {c.key: getattr(s, c.key) for c in FbaShipment.__table__.columns}
        d.update(shop_name=shops.get(s.shop_id), ship_from_warehouse_name=whs.get(s.ship_from_warehouse_id),
                 to_warehouse_name=whs.get(s.to_warehouse_id), logistics_channel_name=chs.get(s.logistics_channel_id),
                 total_qty=sum(ln.qty_shipped for ln in s.lines), received_qty=sum(ln.qty_received for ln in s.lines))
        lines = []
        for ln in s.lines:
            p = products.get(ln.product_id)
            ld = {c.key: getattr(ln, c.key) for c in FbaShipmentLine.__table__.columns}
            ld.update(sku=p.sku if p else None, product_name=p.name if p else None, image_url=p.image_url if p else None,
                      allocated_unit_cost=service._allocated_unit(ln))
            if not show_cost:
                ld.update(unit_purchase_cost=None, unit_freight_cost=None, allocated_cost=None, allocated_unit_cost=None)
            lines.append(ld)
        d["lines"] = lines
        out.append(d)
    return out


@router.get("/fba-shipments", response_model=Page[ShipmentOut], summary="货件列表")
def list_shipments(
    keyword: str | None = None,
    shop_id: int | None = None,
    status: str | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("fba:shipment:view")),
):
    stmt = select(FbaShipment).order_by(FbaShipment.id.desc())
    if keyword:
        kw = f"%{keyword.strip()}%"
        sub = select(FbaShipmentLine.shipment_id).where(FbaShipmentLine.msku.ilike(kw) | FbaShipmentLine.fnsku.ilike(kw))
        stmt = stmt.where(FbaShipment.shipment_no.ilike(kw) | FbaShipment.platform_shipment_id.ilike(kw)
                          | FbaShipment.tracking_no.ilike(kw) | FbaShipment.id.in_(sub))
    if shop_id:
        stmt = stmt.where(FbaShipment.shop_id == shop_id)
    if status:
        stmt = stmt.where(FbaShipment.status.in_(status.split(",")))
    if ctx.shop_ids is not None:
        stmt = stmt.where(FbaShipment.shop_id.in_(ctx.shop_ids))
    page = paginate(ctx.db, stmt, params)
    page["items"] = shipment_out(ctx, page["items"])
    return page


@router.get("/fba-shipments/{shipment_id}", response_model=ShipmentOut, summary="货件详情")
def get_shipment(shipment_id: int, ctx: Ctx = Depends(perm("fba:shipment:view"))):
    s = get_or_404(ctx.db, FbaShipment, shipment_id, "货件")
    ctx.require_shop(s.shop_id)
    return shipment_out(ctx, [s])[0]


def _with_json_boxes(body, data: dict) -> dict:
    if "boxes" in data:
        data["boxes"] = [b.model_dump(mode="json") for b in body.boxes] if body.boxes else None
    return data


@router.post("/fba-shipments", response_model=ShipmentOut, summary="新建货件")
def create_shipment(body: ShipmentIn, ctx: Ctx = Depends(perm("fba:shipment:edit"))):
    data = _with_json_boxes(body, body.model_dump())
    return shipment_out(ctx, [service.create_shipment(ctx, data)])[0]


@router.put("/fba-shipments/{shipment_id}", response_model=ShipmentOut, summary="修改货件（发货后可补录费用）")
def update_shipment(shipment_id: int, body: ShipmentUpdate, ctx: Ctx = Depends(perm("fba:shipment:edit"))):
    data = _with_json_boxes(body, body.model_dump(exclude_unset=True))
    return shipment_out(ctx, [service.update_shipment(ctx, shipment_id, data)])[0]


@router.post("/fba-shipments/{shipment_id}/ship", response_model=ShipmentOut, summary="确认发货（出库）")
def ship(shipment_id: int, ctx: Ctx = Depends(perm("fba:shipment:edit"))):
    return shipment_out(ctx, [service.ship(ctx, shipment_id)])[0]


@router.post("/fba-shipments/{shipment_id}/receive", response_model=ShipmentOut, summary="签收入库")
def receive(shipment_id: int, body: ShipmentReceiveIn, ctx: Ctx = Depends(perm("fba:shipment:edit"))):
    lines = [x.model_dump() for x in body.lines] if body.lines else None
    return shipment_out(ctx, [service.receive(ctx, shipment_id, lines, body.close)])[0]


@router.post("/fba-shipments/{shipment_id}/close", response_model=ShipmentOut, summary="完结货件")
def close(shipment_id: int, ctx: Ctx = Depends(perm("fba:shipment:edit"))):
    return shipment_out(ctx, [service.close(ctx, shipment_id)])[0]


@router.post("/fba-shipments/{shipment_id}/cancel", response_model=ShipmentOut, summary="取消货件")
def cancel(shipment_id: int, ctx: Ctx = Depends(perm("fba:shipment:edit"))):
    return shipment_out(ctx, [service.cancel(ctx, shipment_id)])[0]


@router.post("/fba-shipments/{shipment_id}/costs", response_model=ShipmentOut, summary="补录头程费用并重新分摊")
def update_costs(shipment_id: int, body: CostUpdateIn, ctx: Ctx = Depends(perm("fba:shipment:edit"))):
    return shipment_out(ctx, [service.update_shipment(ctx, shipment_id, body.model_dump(exclude_unset=True))])[0]


# ================================================================ FBA 库存
def _daily_sales(ctx: Ctx, days: int = 30) -> dict[tuple[int, str], float]:
    since = utcnow().date() - timedelta(days=days)
    rows = ctx.db.execute(
        select(SalesOrder.shop_id, SalesOrderItem.msku, func.sum(SalesOrderItem.quantity))
        .join(SalesOrderItem, SalesOrderItem.order_id == SalesOrder.id)
        .where(SalesOrder.local_date >= since, SalesOrder.status != "cancelled")
        .group_by(SalesOrder.shop_id, SalesOrderItem.msku)
    ).all()
    return {(sid, msku): float(q or 0) / days for sid, msku, q in rows}


@router.get("/fba-inventory", response_model=Page[FbaInventoryOut], summary="FBA 库存")
def list_fba_inventory(
    keyword: str | None = None,
    shop_id: int | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("fba:inventory:view")),
):
    stmt = select(FbaInventory).order_by(FbaInventory.fulfillable.desc(), FbaInventory.id)
    stmt = keyword_filter(stmt, keyword, [FbaInventory.msku, FbaInventory.fnsku, FbaInventory.asin])
    if shop_id:
        stmt = stmt.where(FbaInventory.shop_id == shop_id)
    if ctx.shop_ids is not None:
        stmt = stmt.where(FbaInventory.shop_id.in_(ctx.shop_ids))
    page = paginate(ctx.db, stmt, params)
    rows = page["items"]
    shops = _names(ctx.db, Shop, [r.shop_id for r in rows])
    listing_ids = {r.listing_id for r in rows if r.listing_id}
    listings = {x.id: x for x in ctx.db.execute(select(Listing).where(Listing.id.in_(listing_ids))).scalars().all()} if listing_ids else {}
    sales = _daily_sales(ctx)
    items = []
    for r in rows:
        d = {c.key: getattr(r, c.key) for c in FbaInventory.__table__.columns}
        lst = listings.get(r.listing_id)
        daily = sales.get((r.shop_id, r.msku), 0)
        d.update(shop_name=shops.get(r.shop_id), inbound_total=r.inbound_total,
                 sku=lst.product.sku if lst and lst.product else None, title=lst.title if lst else None,
                 image_url=lst.image_url if lst else None, daily_sales=round(daily, 2),
                 days_of_supply=round((r.fulfillable + r.reserved) / daily, 1) if daily else None)
        items.append(d)
    page["items"] = items
    return page


def upsert_fba_inventory(ctx: Ctx, shop: Shop, rows: list[FbaInventoryDTO]) -> int:
    """写入 FBA 库存快照（平台同步与 Excel 导入共用）。"""
    now = utcnow()
    listings = {x.msku: x for x in ctx.db.execute(select(Listing).where(Listing.shop_id == shop.id)).scalars().all()}
    existing = {x.msku: x for x in ctx.db.execute(select(FbaInventory).where(FbaInventory.shop_id == shop.id)).scalars().all()}
    for dto in rows:
        rec = existing.get(dto.msku)
        if rec is None:
            rec = FbaInventory(shop_id=shop.id, msku=dto.msku)
            ctx.db.add(rec)
            existing[dto.msku] = rec
        for f in ("fnsku", "asin", "fulfillable", "inbound_working", "inbound_shipped", "inbound_receiving", "reserved",
                  "unfulfillable"):
            v = getattr(dto, f)
            if v is not None:
                setattr(rec, f, v)
        lst = listings.get(dto.msku)
        if lst is not None:
            rec.listing_id = lst.id
            rec.product_id = lst.product_id
            if dto.fnsku and not lst.fnsku:
                lst.fnsku = dto.fnsku
        rec.snapshot_at = now
    ctx.db.flush()
    return len(rows)


FBA_INV_COLUMNS = [
    ("shop_name", "店铺"), ("msku", "MSKU"), ("fnsku", "FNSKU"), ("asin", "ASIN"), ("fulfillable", "可售"),
    ("inbound_working", "计划入库"), ("inbound_shipped", "在途"), ("inbound_receiving", "入库中"),
    ("reserved", "预留"), ("unfulfillable", "不可售"),
]


@router.get("/fba-inventory/import-template", summary="FBA 库存导入模板")
def fba_inv_template(_: Ctx = Depends(perm("fba:inventory:view"))):
    return template_response("FBA库存导入模板.xlsx", FBA_INV_COLUMNS, {"shop_name": "店铺名", "msku": "MSKU-1", "fulfillable": 100})


@router.post("/fba-inventory/import", response_model=ImportResult, summary="导入 FBA 库存（按店铺+MSKU 覆盖）")
def import_fba_inventory(file: UploadFile = File(...), ctx: Ctx = Depends(perm("fba:shipment:edit"))):
    rows = read_upload(file, FBA_INV_COLUMNS)
    shops = {s.name: s for s in ctx.db.execute(select(Shop)).scalars().all()}
    by_shop: dict[str, list[FbaInventoryDTO]] = {}
    result = ImportResult()
    for r in rows:
        name = str(r.get("shop_name") or "")
        if name not in shops:
            result.skipped += 1
            result.errors.append(f"第 {r['_row']} 行: 店铺不存在 {name}")
            continue
        try:
            dto = FbaInventoryDTO(**{k: v for k, v in r.items() if k not in ("_row", "shop_name") and v is not None})
        except Exception as exc:  # noqa: BLE001
            result.skipped += 1
            result.errors.append(f"第 {r['_row']} 行: {exc}")
            continue
        by_shop.setdefault(name, []).append(dto)
    for name, dtos in by_shop.items():
        ctx.require_shop(shops[name].id)
        result.updated += upsert_fba_inventory(ctx, shops[name], dtos)
    if not by_shop and not result.errors:
        raise BizError("没有可导入的数据")
    audit(ctx, "import", "fba_inventory", None, f"导入 FBA 库存 {result.updated} 条")
    ctx.db.commit()
    return result
