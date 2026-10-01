"""财务：平台交易明细、费用、利润报表、库存估值。

利润（本位币）=
    销售额（商品 + 买家运费 - 促销折扣）
  - 退款
  - 平台佣金 - FBA 配送费 - 其他订单费用
  - 广告费
  - 采购成本 - 头程成本（FIFO 结转）+ 退货回库成本
  - 自发货物流费
  - 平台其他费用（仓储费、月租等，来自交易明细）
  - 其他费用（费用单）
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.common.audit import audit
from app.common.currency import get_rate
from app.common.numbering import next_doc_no
from app.core.deps import Ctx
from app.core.errors import BizError
from app.core.types import q2
from app.integrations.dto import TransactionDTO
from app.modules.ads.models import AdMetricDaily
from app.modules.finance.models import Expense, PlatformTransaction
from app.modules.order.models import ReturnOrder, ReturnOrderLine, SalesOrder, SalesOrderItem
from app.modules.order.service import local_date_of
from app.modules.product.models import Listing, Product
from app.modules.shop.models import Shop

# 交易费用类型归类（兼容 Amazon Finances / 结算报告字段）
REVENUE_TYPES = {"principal", "shipping", "giftwrap", "tax", "shippingtax", "giftwraptax"}
COMMISSION_TYPES = {"commission", "refundcommission", "referralfee"}
FULFILLMENT_TYPES = {"fbaperunitfulfillmentfee", "fbaperorderfulfillmentfee", "fbaweightbasedfee", "fulfillmentfee"}
PROMOTION_TYPES = {"promotion", "promotionmetadatadefinitionvalue", "promotionshipping"}


def classify_amount_type(amount_type: str) -> str:
    t = (amount_type or "").replace(" ", "").replace("_", "").lower()
    if t in REVENUE_TYPES:
        return "revenue"
    if t in COMMISSION_TYPES:
        return "commission"
    if t in FULFILLMENT_TYPES:
        return "fulfillment"
    if t in PROMOTION_TYPES:
        return "promotion"
    return "other"


# ================================================================ 交易明细
def upsert_transactions(ctx: Ctx, shop: Shop, rows: list[TransactionDTO]) -> tuple[int, int]:
    db = ctx.db
    ext_ids = [r.external_id for r in rows]
    existing = {
        t.external_id: t
        for t in db.execute(
            select(PlatformTransaction).where(PlatformTransaction.shop_id == shop.id, PlatformTransaction.external_id.in_(ext_ids))
        ).scalars().all()
    } if ext_ids else {}
    created = updated = 0
    for r in rows:
        t = existing.get(r.external_id)
        if t is None:
            t = PlatformTransaction(shop_id=shop.id, external_id=r.external_id)
            db.add(t)
            existing[r.external_id] = t
            created += 1
        else:
            updated += 1
        t.posted_at = r.posted_at
        t.posted_date = local_date_of(r.posted_at, shop.timezone)
        t.event_type = r.event_type
        t.amount_type = r.amount_type
        t.amount = r.amount
        t.currency = (r.currency or shop.currency).upper()
        t.platform_order_id = r.platform_order_id
        t.msku = r.msku
        t.quantity = r.quantity
        t.settlement_id = r.settlement_id
        t.description = r.description
    db.flush()
    return created, updated


def apply_transactions_to_orders(ctx: Ctx, shop_id: int, order_ids: list[str] | None = None) -> int:
    """用实际结算费用替换订单行的预估佣金 / 配送费。"""
    db = ctx.db
    stmt = select(PlatformTransaction).where(
        PlatformTransaction.shop_id == shop_id, PlatformTransaction.event_type == "order",
        PlatformTransaction.platform_order_id.is_not(None),
    )
    if order_ids:
        stmt = stmt.where(PlatformTransaction.platform_order_id.in_(order_ids))
    fees: dict[tuple[str, str], dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for t in db.execute(stmt).scalars().all():
        cat = classify_amount_type(t.amount_type)
        if cat in ("commission", "fulfillment", "other"):
            fees[(t.platform_order_id, t.msku or "")][cat] += -Decimal(t.amount)
    if not fees:
        return 0
    pids = {k[0] for k in fees}
    orders = db.execute(
        select(SalesOrder).where(SalesOrder.shop_id == shop_id, SalesOrder.platform_order_id.in_(pids))
    ).scalars().all()
    n = 0
    for o in orders:
        for item in o.items:
            f = fees.get((o.platform_order_id, item.msku)) or (fees.get((o.platform_order_id, "")) if len(o.items) == 1 else None)
            if not f:
                continue
            item.commission_fee = q2(f.get("commission", 0))
            item.fulfillment_fee = q2(f.get("fulfillment", 0))
            item.other_fee = q2(f.get("other", 0))
            item.fee_estimated = False
            n += 1
    db.flush()
    return n


# ================================================================ 费用
def create_expense(ctx: Ctx, data: dict) -> Expense:
    if data.get("shop_id"):
        ctx.require_shop(data["shop_id"])
    exp = Expense(expense_no=next_doc_no(ctx.db, "EX"), **data)
    exp.currency = (exp.currency or "CNY").upper()
    ctx.db.add(exp)
    ctx.db.flush()
    audit(ctx, "create", "expense", exp.id, f"新增费用 {exp.expense_no} {exp.amount} {exp.currency}")
    ctx.db.commit()
    return exp


# ================================================================ 利润报表
METRICS = (
    "units", "orders", "sales", "refunds", "commission", "fulfillment_fee", "other_order_fee", "ad_spend",
    "ad_sales", "cost_purchase", "cost_freight", "restock_cost", "logistics", "platform_other_fee", "expenses",
)


@dataclass
class Row:
    key: tuple
    m: dict = field(default_factory=lambda: defaultdict(Decimal))


GROUPS = {"shop", "msku", "sku", "day", "month", "total"}


def _key(group_by: str, shop_id, msku, product_id, d: date | None):
    if group_by == "shop":
        return (shop_id,)
    if group_by == "msku":
        return (shop_id, msku or "")
    if group_by == "sku":
        return (product_id,)
    if group_by == "day":
        return (d,)
    if group_by == "month":
        return (d.strftime("%Y-%m") if d else None,)
    return ("total",)


def profit_report(
    ctx: Ctx,
    *,
    date_from: date,
    date_to: date,
    group_by: str = "msku",
    shop_id: int | None = None,
    keyword: str | None = None,
) -> dict:
    if group_by not in GROUPS:
        raise BizError(f"不支持的维度: {group_by}")
    if date_to < date_from:
        raise BizError("结束日期不能早于开始日期")
    db = ctx.db
    shop_filter = []
    if shop_id:
        ctx.require_shop(shop_id)
        shop_filter = [shop_id]
    elif ctx.shop_ids is not None:
        shop_filter = list(ctx.shop_ids)

    rows: dict[tuple, Row] = {}

    def row(key) -> Row:
        if key not in rows:
            rows[key] = Row(key)
        return rows[key]

    def conv(amount, currency, d) -> Decimal:
        return Decimal(amount or 0) * get_rate(db, currency, d)

    # ---- 订单（已发货口径）
    o, i = SalesOrder, SalesOrderItem
    stmt = (
        select(o.id, o.shop_id, i.msku, i.product_id, o.local_date, o.currency, i.quantity, i.item_amount,
               i.shipping_amount, i.discount_amount, i.commission_fee, i.fulfillment_fee, i.other_fee,
               i.cost_purchase, i.cost_freight, o.actual_freight, o.item_amount)
        .join(i, i.order_id == o.id)
        .where(o.status.in_(["shipped", "delivered"]), o.local_date >= date_from, o.local_date <= date_to)
    )
    if shop_filter:
        stmt = stmt.where(o.shop_id.in_(shop_filter))
    order_keys: dict[tuple, set] = defaultdict(set)
    for (oid, sid, msku, pid, d, cur, qty, amt, ship, disc, comm, ful, oth, cp, cf, freight, order_amt) in db.execute(stmt).all():
        r = row(_key(group_by, sid, msku, pid, d))
        m = r.m
        m["units"] += qty
        order_keys[r.key].add(oid)
        m["sales"] += conv(Decimal(amt) + Decimal(ship) - Decimal(disc), cur, d)
        m["commission"] += conv(comm, cur, d)
        m["fulfillment_fee"] += conv(ful, cur, d)
        m["other_order_fee"] += conv(oth, cur, d)
        m["cost_purchase"] += Decimal(cp or 0)
        m["cost_freight"] += Decimal(cf or 0)
        if freight:
            share = (Decimal(amt) / Decimal(order_amt)) if order_amt else Decimal(1)
            m["logistics"] += Decimal(freight) * share
    for key, ids in order_keys.items():
        rows[key].m["orders"] += len(ids)

    # ---- 退款 / 退货回库
    r_stmt = (
        select(ReturnOrder.shop_id, ReturnOrderLine.msku, ReturnOrderLine.product_id, ReturnOrder.return_date,
               ReturnOrder.currency, ReturnOrderLine.refund_amount, ReturnOrder.restock_cost, ReturnOrder.refund_amount)
        .join(ReturnOrderLine, ReturnOrderLine.return_id == ReturnOrder.id)
        .where(ReturnOrder.status == "completed", ReturnOrder.return_date >= date_from, ReturnOrder.return_date <= date_to)
    )
    if shop_filter:
        r_stmt = r_stmt.where(ReturnOrder.shop_id.in_(shop_filter))
    for sid, msku, pid, d, cur, refund, restock, total_refund in db.execute(r_stmt).all():
        m = row(_key(group_by, sid, msku, pid, d)).m
        m["refunds"] += conv(refund, cur, d)
        if restock:
            share = (Decimal(refund) / Decimal(total_refund)) if total_refund else Decimal(1)
            m["restock_cost"] += Decimal(restock) * share

    # ---- 广告
    listing_product = {
        (lst.shop_id, lst.msku): lst.product_id for lst in db.execute(select(Listing)).scalars().all()
    } if group_by == "sku" else {}
    a_stmt = (
        select(AdMetricDaily.shop_id, AdMetricDaily.msku, AdMetricDaily.metric_date, AdMetricDaily.currency,
               func.sum(AdMetricDaily.spend), func.sum(AdMetricDaily.sales))
        .where(AdMetricDaily.metric_date >= date_from, AdMetricDaily.metric_date <= date_to)
        .group_by(AdMetricDaily.shop_id, AdMetricDaily.msku, AdMetricDaily.metric_date, AdMetricDaily.currency)
    )
    if shop_filter:
        a_stmt = a_stmt.where(AdMetricDaily.shop_id.in_(shop_filter))
    for sid, msku, d, cur, spend, sales in db.execute(a_stmt).all():
        pid = listing_product.get((sid, msku))
        m = row(_key(group_by, sid, msku, pid, d)).m
        m["ad_spend"] += conv(spend, cur, d)
        m["ad_sales"] += conv(sales, cur, d)

    # ---- 平台其他费用（与订单无关的交易：仓储费、月租、调整等）
    t_stmt = (
        select(PlatformTransaction.shop_id, PlatformTransaction.msku, PlatformTransaction.posted_date,
               PlatformTransaction.currency, func.sum(PlatformTransaction.amount))
        .where(PlatformTransaction.event_type.notin_(["order", "refund", "transfer", "ads"]),
               PlatformTransaction.posted_date >= date_from, PlatformTransaction.posted_date <= date_to)
        .group_by(PlatformTransaction.shop_id, PlatformTransaction.msku, PlatformTransaction.posted_date,
                  PlatformTransaction.currency)
    )
    if shop_filter:
        t_stmt = t_stmt.where(PlatformTransaction.shop_id.in_(shop_filter))
    for sid, msku, d, cur, amount in db.execute(t_stmt).all():
        pid = listing_product.get((sid, msku)) if msku else None
        m = row(_key(group_by, sid, msku if msku else None, pid, d)).m
        m["platform_other_fee"] += -conv(amount, cur, d)

    # ---- 费用单
    e_stmt = select(Expense).where(Expense.status == "confirmed", Expense.expense_date >= date_from,
                                   Expense.expense_date <= date_to)
    if shop_filter:
        e_stmt = e_stmt.where(Expense.shop_id.in_(shop_filter))
    for e in db.execute(e_stmt).scalars().all():
        m = row(_key(group_by, e.shop_id, e.msku, e.product_id, e.expense_date)).m
        m["expenses"] += conv(e.amount, e.currency, e.expense_date)

    result = _finalize(ctx, group_by, rows)
    if keyword:
        kw = keyword.lower()
        result = [r for r in result if any(kw in str(r.get(f) or "").lower() for f in ("msku", "sku", "product_name", "shop_name", "asin"))]
    totals = _totals(result)
    return {"items": result, "totals": totals, "base_currency": _base(ctx)}


def _base(ctx: Ctx) -> str:
    from app.common.currency import base_currency

    return base_currency(ctx.db)


def _calc(m: dict) -> dict:
    out = {k: (int(m.get(k, 0)) if k in ("units", "orders") else q2(m.get(k, 0))) for k in METRICS}
    cost = out["cost_purchase"] + out["cost_freight"] - out["restock_cost"]
    profit = (out["sales"] - out["refunds"] - out["commission"] - out["fulfillment_fee"] - out["other_order_fee"]
              - out["ad_spend"] - cost - out["logistics"] - out["platform_other_fee"] - out["expenses"])
    out["cogs"] = q2(cost)
    out["profit"] = q2(profit)
    out["margin"] = float(round(profit / out["sales"] * 100, 2)) if out["sales"] else None
    out["roi"] = float(round(profit / cost * 100, 2)) if cost else None
    out["acos"] = float(round(out["ad_spend"] / out["ad_sales"] * 100, 2)) if out["ad_sales"] else None
    out["tacos"] = float(round(out["ad_spend"] / out["sales"] * 100, 2)) if out["sales"] else None
    return out


def _finalize(ctx: Ctx, group_by: str, rows: dict[tuple, Row]) -> list[dict]:
    db = ctx.db
    shop_names = dict(db.execute(select(Shop.id, Shop.name)).all())
    result = []
    if group_by == "msku":
        listings = {(x.shop_id, x.msku): x for x in db.execute(select(Listing)).scalars().all()}
    if group_by == "sku":
        pids = {k[0] for k in rows if k[0]}
        products = {p.id: p for p in db.execute(select(Product).where(Product.id.in_(pids))).scalars().all()} if pids else {}
    for key, r in rows.items():
        d = _calc(r.m)
        if group_by == "shop":
            d.update(shop_id=key[0], shop_name=shop_names.get(key[0]) if key[0] else "公共费用")
        elif group_by == "msku":
            lst = listings.get(key)
            d.update(shop_id=key[0], shop_name=shop_names.get(key[0]) if key[0] else "公共费用", msku=key[1] or None,
                     asin=lst.asin if lst else None, title=lst.title if lst else None,
                     image_url=lst.image_url if lst else None,
                     sku=lst.product.sku if lst and lst.product else None)
        elif group_by == "sku":
            p = products.get(key[0])
            d.update(product_id=key[0], sku=p.sku if p else None, product_name=p.name if p else ("未配对/公共" if not key[0] else None),
                     image_url=p.image_url if p else None)
        elif group_by in ("day", "month"):
            d.update(period=str(key[0]) if key[0] else None)
        result.append(d)
    if group_by in ("day", "month"):
        result.sort(key=lambda x: x.get("period") or "")
    else:
        result.sort(key=lambda x: x["sales"], reverse=True)
    return result


def _totals(items: list[dict]) -> dict:
    m: dict = defaultdict(Decimal)
    for it in items:
        for k in METRICS:
            m[k] += Decimal(it.get(k) or 0)
    return _calc(m)


# ================================================================ 库存估值
def inventory_valuation(ctx: Ctx) -> dict:
    from app.modules.warehouse.models import InventoryBatch, Warehouse

    db = ctx.db
    rows = db.execute(
        select(
            Warehouse.id, Warehouse.name, Warehouse.warehouse_type,
            func.sum(InventoryBatch.qty_remaining),
            func.sum(InventoryBatch.qty_remaining * InventoryBatch.unit_purchase_cost),
            func.sum(InventoryBatch.qty_remaining * InventoryBatch.unit_freight_cost),
        )
        .join(InventoryBatch, InventoryBatch.warehouse_id == Warehouse.id)
        .where(InventoryBatch.qty_remaining > 0)
        .group_by(Warehouse.id, Warehouse.name, Warehouse.warehouse_type)
        .order_by(Warehouse.id)
    ).all()
    items = [
        {"warehouse_id": wid, "warehouse_name": name, "warehouse_type": wtype, "qty": int(qty or 0),
         "purchase_value": q2(pv or 0), "freight_value": q2(fv or 0), "total_value": q2((pv or 0) + (fv or 0))}
        for wid, name, wtype, qty, pv, fv in rows
    ]
    # 调拨/头程在途价值
    from app.modules.fba.models import FbaShipment, FbaShipmentLine

    transit = db.execute(
        select(func.sum((FbaShipmentLine.qty_shipped - FbaShipmentLine.qty_received)
                        * (FbaShipmentLine.unit_purchase_cost + FbaShipmentLine.unit_freight_cost)),
               func.sum(FbaShipmentLine.qty_shipped - FbaShipmentLine.qty_received))
        .join(FbaShipment, FbaShipment.id == FbaShipmentLine.shipment_id)
        .where(FbaShipment.status.in_(["shipped", "receiving"]))
    ).one()
    totals = {
        "qty": sum(x["qty"] for x in items),
        "purchase_value": q2(sum((x["purchase_value"] for x in items), Decimal(0))),
        "freight_value": q2(sum((x["freight_value"] for x in items), Decimal(0))),
        "total_value": q2(sum((x["total_value"] for x in items), Decimal(0))),
        "in_transit_qty": int(transit[1] or 0),
        "in_transit_value": q2(transit[0] or 0),
    }
    return {"items": items, "totals": totals, "base_currency": _base(ctx)}
