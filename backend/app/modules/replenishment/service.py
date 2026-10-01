"""智能补货。

日均销量 = (近7天日均 × w7 + 近14天日均 × w14 + 近30天日均 × w30) × 增长系数

FBA 发货建议（按 Listing）：
    需求 = 日均 × (头程时效 + 安全天数 + 备货天数)
    建议发货量 = 需求 - (FBA 可售 + 预留 + 入库在途)
    可售天数 = (FBA 可售 + 预留) / 日均；断货日 = 今天 + 可售天数
    建议发货日 = 今天 + max(0, 可售天数 - 头程时效 - 安全天数)

采购建议（按 SKU）：
    需求 = Σ(Listing 日均 × 配对数量 × 组合数量) × (采购交期 + 质检 + 头程 + 安全 + 备货)
    供给 = 本地可用 + FBA 总库存（含在途）+ 采购在途 + 待处理采购计划
    建议采购量 = 需求 - 供给，向上取整到起订量
"""

import math
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import case, func, select

from app.common.audit import audit
from app.common.enums import PlanStatus, ProductType, PurchaseStatus
from app.core.deps import Ctx
from app.core.errors import BizError
from app.core.types import utcnow
from app.modules.fba.models import FbaInventory
from app.modules.fba.service import shipment_summary_by_listing
from app.modules.order.models import SalesOrder, SalesOrderItem
from app.modules.product.models import BundleItem, Listing, Product
from app.modules.product.service import available_stock
from app.modules.purchase.models import PurchaseOrder, PurchaseOrderLine, PurchasePlan
from app.modules.replenishment.models import DEFAULT_RULE_VALUES, ReplenishmentRule
from app.modules.shop.models import Shop
from app.modules.warehouse.models import InventoryBalance, Warehouse

RULE_FIELDS = ("purchase_lead_days", "inspection_days", "transit_days", "safety_days", "cover_days",
               "weight_7d", "weight_14d", "weight_30d", "growth_factor")


def default_rule(ctx: Ctx) -> ReplenishmentRule:
    rule = ctx.db.execute(
        select(ReplenishmentRule).where(ReplenishmentRule.listing_id.is_(None)).order_by(ReplenishmentRule.id)
    ).scalars().first()
    if rule is None:
        rule = ReplenishmentRule.make_default()
        ctx.db.add(rule)
        ctx.db.flush()
    return rule


def _rule_dict(rule: ReplenishmentRule) -> dict:
    out = {}
    for f in RULE_FIELDS:
        v = getattr(rule, f)
        out[f] = DEFAULT_RULE_VALUES[f] if v is None else v
    return out


def rules_by_listing(ctx: Ctx) -> dict[int, dict]:
    base = _rule_dict(default_rule(ctx))
    out: dict[int, dict] = defaultdict(lambda: dict(base))
    for r in ctx.db.execute(select(ReplenishmentRule).where(ReplenishmentRule.listing_id.is_not(None))).scalars().all():
        merged = dict(base)
        for f in RULE_FIELDS:
            v = getattr(r, f)
            if v is not None:
                merged[f] = v
        out[r.listing_id] = merged
    return out


def sales_windows(ctx: Ctx, today: date | None = None) -> dict[tuple[int, str], tuple[int, int, int]]:
    """(店铺, MSKU) → (近7天, 近14天, 近30天) 销量，统计完整自然日（不含今天）。"""
    today = today or utcnow().date()
    d7, d14, d30 = today - timedelta(days=7), today - timedelta(days=14), today - timedelta(days=30)
    q = SalesOrderItem.quantity
    rows = ctx.db.execute(
        select(
            SalesOrder.shop_id,
            SalesOrderItem.msku,
            func.sum(case((SalesOrder.local_date >= d7, q), else_=0)),
            func.sum(case((SalesOrder.local_date >= d14, q), else_=0)),
            func.sum(q),
        )
        .join(SalesOrderItem, SalesOrderItem.order_id == SalesOrder.id)
        .where(SalesOrder.local_date >= d30, SalesOrder.local_date < today, SalesOrder.status != "cancelled")
        .group_by(SalesOrder.shop_id, SalesOrderItem.msku)
    ).all()
    return {(sid, msku): (int(a or 0), int(b or 0), int(c or 0)) for sid, msku, a, b, c in rows}


def weighted_daily(s7: int, s14: int, s30: int, rule: dict) -> float:
    w7, w14, w30 = float(rule["weight_7d"] or 0), float(rule["weight_14d"] or 0), float(rule["weight_30d"] or 0)
    total_w = w7 + w14 + w30 or 1.0
    daily = (s7 / 7 * w7 + s14 / 14 * w14 + s30 / 30 * w30) / total_w
    return daily * float(rule["growth_factor"] or 1)


def listing_suggestions(ctx: Ctx, *, shop_id: int | None = None, keyword: str | None = None,
                        only_need: bool = False) -> list[dict]:
    db = ctx.db
    today = utcnow().date()
    stmt = select(Listing).where(Listing.fulfillment == "FBA", Listing.status != "deleted")
    if shop_id:
        stmt = stmt.where(Listing.shop_id == shop_id)
    if ctx.shop_ids is not None:
        stmt = stmt.where(Listing.shop_id.in_(ctx.shop_ids))
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(Listing.msku.ilike(kw) | Listing.asin.ilike(kw) | Listing.title.ilike(kw))
    listings = db.execute(stmt.order_by(Listing.shop_id, Listing.msku)).scalars().all()
    if not listings:
        return []
    shops = {s.id: s for s in db.execute(select(Shop)).scalars().all()}
    sales = sales_windows(ctx, today)
    rules = rules_by_listing(ctx)
    snapshots = {(x.shop_id, x.msku): x for x in db.execute(select(FbaInventory)).scalars().all()}
    in_transit = shipment_summary_by_listing(ctx)
    product_ids = list({x.product_id for x in listings if x.product_id})
    local = available_stock(db, product_ids)
    fba_wh_stock = _fba_warehouse_stock(ctx, product_ids)
    result = []
    for lst in listings:
        rule = rules[lst.id]
        s7, s14, s30 = sales.get((lst.shop_id, lst.msku), (0, 0, 0))
        daily = weighted_daily(s7, s14, s30, rule)
        snap = snapshots.get((lst.shop_id, lst.msku))
        pair = lst.pair_quantity or 1
        if snap is not None:
            fba_available = snap.fulfillable + snap.reserved
            fba_inbound = snap.inbound_total
        else:
            fba_available = max(0, fba_wh_stock.get((lst.shop_id, lst.product_id), 0) // pair) if lst.product_id else 0
            fba_inbound = in_transit.get((lst.shop_id, lst.msku), 0) // pair
        local_available = local.get(lst.product_id, 0) // pair if lst.product_id else 0
        horizon = int(rule["transit_days"]) + int(rule["safety_days"]) + int(rule["cover_days"])
        need = math.ceil(daily * horizon)
        suggest = max(0, need - fba_available - fba_inbound)
        available_days = (fba_available / daily) if daily > 0 else None
        total_days = ((fba_available + fba_inbound) / daily) if daily > 0 else None
        ship_by = None
        if available_days is not None:
            ship_by = today + timedelta(days=max(0, int(available_days - rule["transit_days"] - rule["safety_days"])))
        if only_need and suggest <= 0:
            continue
        shop = shops.get(lst.shop_id)
        result.append({
            "listing_id": lst.id, "shop_id": lst.shop_id, "shop_name": shop.name if shop else None,
            "msku": lst.msku, "asin": lst.asin, "fnsku": lst.fnsku, "title": lst.title, "image_url": lst.image_url,
            "product_id": lst.product_id, "sku": lst.product.sku if lst.product else None,
            "sales_7d": s7, "sales_14d": s14, "sales_30d": s30, "daily_sales": round(daily, 2),
            "fba_available": fba_available, "fba_inbound": fba_inbound, "local_available": local_available,
            "available_days": round(available_days, 1) if available_days is not None else None,
            "total_days": round(total_days, 1) if total_days is not None else None,
            "out_of_stock_date": (today + timedelta(days=int(available_days))) if available_days is not None else None,
            "suggest_ship_qty": suggest, "suggest_ship_date": ship_by,
            "transit_days": rule["transit_days"], "safety_days": rule["safety_days"], "cover_days": rule["cover_days"],
            "has_custom_rule": lst.id in _custom_rule_ids(ctx),
        })
    result.sort(key=lambda r: (r["available_days"] is None, r["available_days"] or 0))
    return result


def _custom_rule_ids(ctx: Ctx) -> set[int]:
    cache = ctx.extra.get("_custom_rule_ids")
    if cache is None:
        cache = set(ctx.db.execute(select(ReplenishmentRule.listing_id).where(ReplenishmentRule.listing_id.is_not(None))).scalars().all())
        ctx.extra["_custom_rule_ids"] = cache
    return cache


def _fba_warehouse_stock(ctx: Ctx, product_ids: list[int]) -> dict[tuple[int, int], int]:
    if not product_ids:
        return {}
    rows = ctx.db.execute(
        select(Warehouse.shop_id, InventoryBalance.product_id, InventoryBalance.qty_on_hand)
        .join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id)
        .where(Warehouse.warehouse_type == "fba", InventoryBalance.product_id.in_(product_ids))
    ).all()
    return {(sid, pid): int(q or 0) for sid, pid, q in rows}


def purchase_suggestions(ctx: Ctx, *, keyword: str | None = None, only_need: bool = False) -> list[dict]:
    db = ctx.db
    today = utcnow().date()
    rule = _rule_dict(default_rule(ctx))
    listing_rules = rules_by_listing(ctx)
    sales = sales_windows(ctx, today)
    listings = db.execute(select(Listing).where(Listing.product_id.is_not(None))).scalars().all()
    bundles: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for b in db.execute(select(BundleItem)).scalars().all():
        bundles[b.bundle_id].append((b.component_id, b.quantity))
    snapshots = {(x.shop_id, x.msku): x for x in db.execute(select(FbaInventory)).scalars().all()}

    demand: dict[int, float] = defaultdict(float)
    fba_units: dict[int, int] = defaultdict(int)
    sales30: dict[int, int] = defaultdict(int)
    for lst in listings:
        s7, s14, s30 = sales.get((lst.shop_id, lst.msku), (0, 0, 0))
        daily = weighted_daily(s7, s14, s30, listing_rules[lst.id])
        snap = snapshots.get((lst.shop_id, lst.msku))
        fba_total = (snap.fulfillable + snap.reserved + snap.inbound_total) if snap else 0
        comps = bundles.get(lst.product_id) or [(lst.product_id, 1)]
        for comp_id, cq in comps:
            mult = (lst.pair_quantity or 1) * cq
            demand[comp_id] += daily * mult
            fba_units[comp_id] += fba_total * mult
            sales30[comp_id] += s30 * mult

    pstmt = select(Product).where(Product.product_type != ProductType.BUNDLE, Product.status != "discontinued")
    if keyword:
        kw = f"%{keyword}%"
        pstmt = pstmt.where(Product.sku.ilike(kw) | Product.name.ilike(kw))
    products = db.execute(pstmt).scalars().all()
    pids = [p.id for p in products]
    local = available_stock(db, pids)
    po_transit = dict(db.execute(
        select(PurchaseOrderLine.product_id, func.sum(PurchaseOrderLine.qty - PurchaseOrderLine.qty_received))
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.order_id)
        .where(PurchaseOrder.status.in_([PurchaseStatus.PENDING_APPROVAL, PurchaseStatus.APPROVED,
                                         PurchaseStatus.ORDERED, PurchaseStatus.PARTIAL, PurchaseStatus.DRAFT]))
        .group_by(PurchaseOrderLine.product_id)
    ).all())
    planned = dict(db.execute(
        select(PurchasePlan.product_id, func.sum(PurchasePlan.qty))
        .where(PurchasePlan.status == PlanStatus.PENDING).group_by(PurchasePlan.product_id)
    ).all())
    result = []
    for p in products:
        daily = demand.get(p.id, 0.0)
        local_avail = local.get(p.id, 0)
        transit = int(po_transit.get(p.id) or 0)
        plan_qty = int(planned.get(p.id) or 0)
        fba_total = fba_units.get(p.id, 0)
        if not daily and not local_avail and not transit and not fba_total:
            continue
        lead = int(p.purchase_lead_days or rule["purchase_lead_days"] or 15)
        horizon = lead + int(rule["inspection_days"]) + int(rule["transit_days"]) + int(rule["safety_days"]) + int(rule["cover_days"])
        supply = local_avail + fba_total + transit + plan_qty
        need = math.ceil(daily * horizon)
        suggest = max(0, need - supply)
        if suggest and p.moq and suggest < p.moq:
            suggest = p.moq
        if only_need and suggest <= 0:
            continue
        days = (supply / daily) if daily > 0 else None
        result.append({
            "product_id": p.id, "sku": p.sku, "product_name": p.name, "image_url": p.image_url,
            "supplier_id": p.default_supplier_id, "moq": p.moq, "purchase_lead_days": lead,
            "sales_30d": sales30.get(p.id, 0), "daily_sales": round(daily, 2), "local_available": local_avail,
            "fba_total": fba_total, "purchase_in_transit": transit, "planned_qty": plan_qty, "total_supply": supply,
            "supply_days": round(days, 1) if days is not None else None,
            "suggest_purchase_qty": suggest,
            "latest_order_date": (today + timedelta(days=max(0, int(days - horizon + int(rule["cover_days"])))))
            if days is not None else None,
        })
    result.sort(key=lambda r: (r["supply_days"] is None, r["supply_days"] or 0))
    return result


def create_purchase_plans(ctx: Ctx, items: list[dict], warehouse_id: int | None) -> int:
    from app.modules.purchase.service import create_plan

    n = 0
    for it in items:
        if it["qty"] <= 0:
            continue
        create_plan(ctx, {"product_id": it["product_id"], "qty": it["qty"], "supplier_id": it.get("supplier_id"),
                          "warehouse_id": warehouse_id, "source": "replenishment", "remark": "由补货建议生成"})
        n += 1
    audit(ctx, "create", "purchase_plan", None, f"补货建议生成采购计划 {n} 条")
    ctx.db.commit()
    return n


def create_shipment_plans(ctx: Ctx, items: list[dict], ship_from_warehouse_id: int) -> int:
    from app.modules.fba.service import create_plan

    by_shop: dict[int, list[dict]] = defaultdict(list)
    for it in items:
        if it["qty"] <= 0:
            continue
        lst = ctx.db.get(Listing, it["listing_id"])
        if lst is None:
            raise BizError("Listing 不存在")
        by_shop[lst.shop_id].append({"listing_id": lst.id, "qty": it["qty"]})
    for shop_id, lines in by_shop.items():
        create_plan(ctx, {"shop_id": shop_id, "ship_from_warehouse_id": ship_from_warehouse_id, "lines": lines,
                          "remark": "由补货建议生成"})
    ctx.db.commit()
    return len(by_shop)


def save_rule(ctx: Ctx, listing_id: int | None, data: dict) -> ReplenishmentRule:
    if listing_id is None:
        rule = default_rule(ctx)
    else:
        lst = ctx.db.get(Listing, listing_id)
        if lst is None:
            raise BizError("Listing 不存在")
        ctx.require_shop(lst.shop_id)
        rule = ctx.db.execute(select(ReplenishmentRule).where(ReplenishmentRule.listing_id == listing_id)).scalar_one_or_none()
        if rule is None:
            rule = ReplenishmentRule(listing_id=listing_id)
            ctx.db.add(rule)
    for k, v in data.items():
        if k in RULE_FIELDS or k == "remark":
            setattr(rule, k, Decimal(str(v)) if k.startswith(("weight", "growth")) and v is not None else v)
    audit(ctx, "update", "replenishment_rule", listing_id, "修改补货参数")
    ctx.db.commit()
    return rule
