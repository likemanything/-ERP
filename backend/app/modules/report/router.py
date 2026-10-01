"""首页看板与数据报表。"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.common.currency import get_rate
from app.common.excel import export_xlsx
from app.core.deps import Ctx, perm
from app.core.errors import BizError
from app.core.types import q2, utcnow
from app.modules.fba.models import FbaShipment, ShipmentPlan
from app.modules.order.models import SalesOrder, SalesOrderItem
from app.modules.product.models import Listing, Product
from app.modules.purchase.models import PaymentRequest, PurchaseOrder, PurchasePlan
from app.modules.shop.models import Shop
from app.modules.warehouse.models import InventoryBalance, InventoryBatch, InventoryLedger, Warehouse

router = APIRouter(tags=["数据报表"])

ACTIVE_ORDER = SalesOrder.status != "cancelled"


def _shop_scope(ctx: Ctx, stmt, col):
    if ctx.shop_ids is not None:
        stmt = stmt.where(col.in_(ctx.shop_ids))
    return stmt


def _sales_by(ctx: Ctx, date_from: date, date_to: date, dims: list, shop_id: int | None = None) -> dict:
    """按维度聚合销售（本位币）。dims 为 SQLAlchemy 列；返回 {key: {sales, orders, units}}。"""
    o, i = SalesOrder, SalesOrderItem
    stmt = (
        select(*dims, o.currency, o.local_date, func.count(func.distinct(o.id)), func.sum(i.quantity),
               func.sum(i.item_amount + i.shipping_amount - i.discount_amount))
        .join(i, i.order_id == o.id)
        .where(ACTIVE_ORDER, o.local_date >= date_from, o.local_date <= date_to)
        .group_by(*dims, o.currency, o.local_date)
    )
    if shop_id:
        stmt = stmt.where(o.shop_id == shop_id)
    stmt = _shop_scope(ctx, stmt, o.shop_id)
    n = len(dims)
    out: dict = defaultdict(lambda: {"sales": Decimal(0), "orders": 0, "units": 0})
    for row in ctx.db.execute(stmt).all():
        key = tuple(row[:n])
        cur, d, orders, units, amount = row[n:]
        a = out[key]
        a["sales"] += Decimal(amount or 0) * get_rate(ctx.db, cur, d)
        a["orders"] += int(orders or 0)
        a["units"] += int(units or 0)
    return out


def _period(ctx: Ctx, date_from: date, date_to: date) -> dict:
    agg = _sales_by(ctx, date_from, date_to, [])
    a = agg.get((), {"sales": Decimal(0), "orders": 0, "units": 0})
    return {"sales": float(q2(a["sales"])), "orders": a["orders"], "units": a["units"]}


@router.get("/dashboard/overview", summary="首页看板")
def overview(ctx: Ctx = Depends(perm("dashboard:view"))):
    db = ctx.db
    today = utcnow().date()
    yesterday = today - timedelta(days=1)
    month_start = today.replace(day=1)
    kpi = {
        "today": _period(ctx, today, today),
        "yesterday": _period(ctx, yesterday, yesterday),
        "last_7d": _period(ctx, today - timedelta(days=6), today),
        "last_30d": _period(ctx, today - timedelta(days=29), today),
        "month": _period(ctx, month_start, today),
    }
    # 近 30 天趋势
    daily = _sales_by(ctx, today - timedelta(days=29), today, [SalesOrder.local_date])
    trend = []
    for k in range(29, -1, -1):
        d = today - timedelta(days=k)
        a = daily.get((d,), {"sales": Decimal(0), "orders": 0, "units": 0})
        trend.append({"date": d.isoformat(), "sales": float(q2(a["sales"])), "orders": a["orders"], "units": a["units"]})
    # 店铺分布
    names = dict(db.execute(select(Shop.id, Shop.name)).all())
    by_shop = sorted(
        ({"shop_id": k[0], "shop_name": names.get(k[0]), "sales": float(q2(v["sales"])), "orders": v["orders"]}
         for k, v in _sales_by(ctx, today - timedelta(days=29), today, [SalesOrder.shop_id]).items()),
        key=lambda x: -x["sales"],
    )
    # 热销 Listing
    top = _sales_by(ctx, today - timedelta(days=29), today, [SalesOrder.shop_id, SalesOrderItem.msku])
    top_items = sorted(top.items(), key=lambda kv: -kv[1]["sales"])[:10]
    listings = {(x.shop_id, x.msku): x for x in db.execute(
        select(Listing).where(Listing.msku.in_([k[1] for k, _ in top_items]))).scalars().all()} if top_items else {}
    top_products = []
    for (sid, msku), v in top_items:
        lst = listings.get((sid, msku))
        top_products.append({"shop_name": names.get(sid), "msku": msku, "asin": lst.asin if lst else None,
                             "title": lst.title if lst else None, "image_url": lst.image_url if lst else None,
                             "sales": float(q2(v["sales"])), "units": v["units"], "orders": v["orders"]})

    def cnt(stmt) -> int:
        return int(db.execute(stmt).scalar_one() or 0)

    def so_scope(stmt):
        return _shop_scope(ctx, stmt, SalesOrder.shop_id)

    todo = {
        "orders_to_audit": cnt(so_scope(select(func.count()).select_from(SalesOrder).where(SalesOrder.status == "to_audit"))),
        "orders_to_ship": cnt(so_scope(select(func.count()).select_from(SalesOrder).where(SalesOrder.status == "to_ship"))),
        "po_pending_approval": cnt(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.status == "pending_approval")),
        "po_to_receive": cnt(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.status.in_(["ordered", "partial"]))),
        "purchase_plans_pending": cnt(select(func.count()).select_from(PurchasePlan).where(PurchasePlan.status == "pending")),
        "payments_pending": cnt(select(func.count()).select_from(PaymentRequest).where(PaymentRequest.status == "pending")),
        "payments_to_pay": cnt(select(func.count()).select_from(PaymentRequest).where(PaymentRequest.status == "approved")),
        "shipment_plans_pending": cnt(select(func.count()).select_from(ShipmentPlan).where(ShipmentPlan.status == "pending")),
        "shipments_in_transit": cnt(select(func.count()).select_from(FbaShipment).where(FbaShipment.status.in_(["shipped", "receiving"]))),
        "unpaired_listings": cnt(_shop_scope(ctx, select(func.count()).select_from(Listing).where(Listing.product_id.is_(None)), Listing.shop_id)),
        "low_stock": cnt(select(func.count()).select_from(InventoryBalance).where(
            InventoryBalance.safety_stock > 0,
            (InventoryBalance.qty_on_hand - InventoryBalance.qty_locked) < InventoryBalance.safety_stock)),
    }
    result = {"kpi": kpi, "trend": trend, "by_shop": by_shop, "top_products": top_products, "todo": todo}
    if ctx.can("finance:profit:view"):
        from app.modules.finance.service import profit_report

        mtd = profit_report(ctx, date_from=month_start, date_to=today, group_by="total")["totals"]
        result["month_profit"] = {"sales": float(mtd["sales"]), "profit": float(mtd["profit"]), "margin": mtd["margin"],
                                  "ad_spend": float(mtd["ad_spend"])}
    return result


# ------------------------------------------------------------------ 销售统计
@router.get("/reports/sales", summary="销售统计（下单口径，不含已取消）")
def sales_report(
    date_from: date,
    date_to: date,
    group_by: str = "msku",
    shop_id: int | None = None,
    ctx: Ctx = Depends(perm("report:view")),
):
    dims_map = {
        "shop": [SalesOrder.shop_id],
        "msku": [SalesOrder.shop_id, SalesOrderItem.msku],
        "sku": [SalesOrderItem.product_id],
        "day": [SalesOrder.local_date],
        "country": [SalesOrder.ship_country],
    }
    if group_by not in dims_map and group_by != "month":
        raise BizError("不支持的维度")
    dims = dims_map.get(group_by, [SalesOrder.local_date])
    agg = _sales_by(ctx, date_from, date_to, dims, shop_id)
    names = dict(ctx.db.execute(select(Shop.id, Shop.name)).all())
    items = []
    if group_by == "month":
        monthly: dict = defaultdict(lambda: {"sales": Decimal(0), "orders": 0, "units": 0})
        for (d,), v in agg.items():
            m = monthly[d.strftime("%Y-%m")]
            for k in v:
                m[k] += v[k]
        agg = {(k,): v for k, v in monthly.items()}
    pids = {k[0] for k in agg} if group_by == "sku" else set()
    products = {p.id: p for p in ctx.db.execute(select(Product).where(Product.id.in_(pids))).scalars().all()} if pids else {}
    for key, v in agg.items():
        d = {"sales": float(q2(v["sales"])), "orders": v["orders"], "units": v["units"],
             "avg_price": float(q2(v["sales"] / v["units"])) if v["units"] else None}
        if group_by == "shop":
            d.update(shop_id=key[0], shop_name=names.get(key[0]))
        elif group_by == "msku":
            d.update(shop_id=key[0], shop_name=names.get(key[0]), msku=key[1])
        elif group_by == "sku":
            p = products.get(key[0])
            d.update(product_id=key[0], sku=p.sku if p else "未配对", product_name=p.name if p else None)
        elif group_by == "country":
            d.update(country=key[0] or "未知")
        else:
            d.update(period=str(key[0]))
        items.append(d)
    if group_by in ("day", "month"):
        items.sort(key=lambda x: x["period"])
    else:
        items.sort(key=lambda x: -x["sales"])
    totals = {"sales": round(sum(x["sales"] for x in items), 2), "orders": sum(x["orders"] for x in items),
              "units": sum(x["units"] for x in items)}
    return {"items": items, "totals": totals}


@router.get("/reports/sales/export", summary="导出销售统计")
def export_sales(date_from: date, date_to: date, group_by: str = "msku", shop_id: int | None = None,
                 ctx: Ctx = Depends(perm("report:view"))):
    data = sales_report(date_from, date_to, group_by, shop_id, ctx)
    cols = [("shop_name", "店铺"), ("msku", "MSKU"), ("sku", "SKU"), ("product_name", "品名"), ("country", "国家"),
            ("period", "日期"), ("units", "销量"), ("orders", "订单数"), ("sales", "销售额"), ("avg_price", "均价")]
    return export_xlsx("销售统计.xlsx", cols, data["items"])


# ------------------------------------------------------------------ 库龄
AGE_BUCKETS = [(0, 30), (31, 60), (61, 90), (91, 180), (181, 365), (366, 100000)]


@router.get("/reports/inventory-aging", summary="库龄分析（按批次入库时间）")
def inventory_aging(warehouse_id: int | None = None, warehouse_type: str | None = None, keyword: str | None = None,
                    ctx: Ctx = Depends(perm("inventory:view"))):
    stmt = (
        select(InventoryBatch, Product.sku, Product.name)
        .join(Product, Product.id == InventoryBatch.product_id)
        .join(Warehouse, Warehouse.id == InventoryBatch.warehouse_id)
        .where(InventoryBatch.qty_remaining > 0)
    )
    if warehouse_id:
        stmt = stmt.where(InventoryBatch.warehouse_id == warehouse_id)
    if warehouse_type:
        stmt = stmt.where(Warehouse.warehouse_type == warehouse_type)
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(Product.sku.ilike(kw) | Product.name.ilike(kw))
    now = utcnow()
    show_cost = ctx.can("product:cost:view")
    rows: dict[int, dict] = {}
    summary = [{"bucket": f"{a}-{b}天" if b < 100000 else f">{a - 1}天", "qty": 0, "value": Decimal(0)} for a, b in AGE_BUCKETS]
    for batch, sku, name in ctx.db.execute(stmt).all():
        age = (now - batch.received_at).days
        idx = next(k for k, (a, b) in enumerate(AGE_BUCKETS) if a <= age <= b)
        value = batch.qty_remaining * (batch.unit_purchase_cost + batch.unit_freight_cost)
        r = rows.setdefault(batch.product_id, {"product_id": batch.product_id, "sku": sku, "product_name": name, "qty": 0,
                                               "value": Decimal(0), "buckets": [0] * len(AGE_BUCKETS), "max_age": 0,
                                               "weighted_age": 0})
        r["qty"] += batch.qty_remaining
        r["value"] += value
        r["buckets"][idx] += batch.qty_remaining
        r["max_age"] = max(r["max_age"], age)
        r["weighted_age"] += age * batch.qty_remaining
        summary[idx]["qty"] += batch.qty_remaining
        summary[idx]["value"] += value
    items = []
    for r in rows.values():
        r["avg_age"] = round(r.pop("weighted_age") / r["qty"], 1) if r["qty"] else 0
        r["value"] = float(q2(r["value"])) if show_cost else None
        items.append(r)
    items.sort(key=lambda x: -x["avg_age"])
    for s in summary:
        s["value"] = float(q2(s["value"])) if show_cost else None
    return {"items": items, "summary": summary, "buckets": [s["bucket"] for s in summary]}


# ------------------------------------------------------------------ 周转
@router.get("/reports/inventory-turnover", summary="库存周转（近 N 天出库 vs 当前结存）")
def inventory_turnover(days: int = 30, keyword: str | None = None, ctx: Ctx = Depends(perm("inventory:view"))):
    since = utcnow().date() - timedelta(days=days)
    out_types = ["sale_out", "fba_out", "other_out", "transfer_out"]
    sold = dict(ctx.db.execute(
        select(InventoryLedger.product_id, func.sum(-InventoryLedger.qty_change))
        .where(InventoryLedger.change_type.in_(["sale_out"]), InventoryLedger.biz_date >= since)
        .group_by(InventoryLedger.product_id)
    ).all())
    moved = dict(ctx.db.execute(
        select(InventoryLedger.product_id, func.sum(-InventoryLedger.qty_change))
        .where(InventoryLedger.change_type.in_(out_types), InventoryLedger.biz_date >= since)
        .group_by(InventoryLedger.product_id)
    ).all())
    stock_stmt = (
        select(Product.id, Product.sku, Product.name, func.sum(InventoryBalance.qty_on_hand))
        .join(InventoryBalance, InventoryBalance.product_id == Product.id)
        .group_by(Product.id, Product.sku, Product.name)
    )
    if keyword:
        kw = f"%{keyword}%"
        stock_stmt = stock_stmt.where(Product.sku.ilike(kw) | Product.name.ilike(kw))
    items = []
    for pid, sku, name, qty in ctx.db.execute(stock_stmt).all():
        qty = int(qty or 0)
        s = int(sold.get(pid) or 0)
        daily = s / days if days else 0
        items.append({
            "product_id": pid, "sku": sku, "product_name": name, "stock_qty": qty, "sold_qty": s,
            "moved_qty": int(moved.get(pid) or 0), "daily_sales": round(daily, 2),
            "days_of_inventory": round(qty / daily, 1) if daily else None,
            "turnover_rate": round(s / qty, 2) if qty > 0 else None,
            "slow_moving": daily == 0 and qty > 0,
        })
    items.sort(key=lambda x: (x["days_of_inventory"] is None, -(x["days_of_inventory"] or 0)))
    return {"items": items, "days": days}
