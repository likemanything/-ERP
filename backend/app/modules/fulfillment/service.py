"""仓储作业：拣货波次、拣货汇总、扫码验货发货、运单号导入。"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, or_, select

from app.common.audit import audit
from app.common.enums import OrderStatus
from app.common.numbering import next_doc_no
from app.core.deps import Ctx
from app.core.errors import BizError
from app.core.types import utcnow
from app.modules.fulfillment.models import PickWave
from app.modules.order.models import SalesOrder
from app.modules.product.models import Listing, Product
from app.modules.warehouse.models import InventoryBalance

ACTIVE = ("picking", "picked")


def _free_order_filter():
    """未进入进行中波次的订单。"""
    active_ids = select(PickWave.id).where(PickWave.status.in_(ACTIVE))
    return or_(SalesOrder.wave_id.is_(None), SalesOrder.wave_id.not_in(active_ids))


def _plan(order: SalesOrder) -> list[dict]:
    return list(order.stock_plan or [])


def _wave_stats(orders: list[SalesOrder]) -> tuple[int, int]:
    skus: set[int] = set()
    units = 0
    for o in orders:
        for p in _plan(o):
            skus.add(p["product_id"])
            units += int(p["qty"])
    return len(skus), units


def create_waves(ctx: Ctx, *, order_ids: list[int] | None, warehouse_id: int | None, max_orders: int,
                 remark: str | None) -> dict:
    """按发货仓把待发货订单生成拣货波次（每个波次最多 max_orders 单）。"""
    db = ctx.db
    stmt = (
        select(SalesOrder)
        .where(SalesOrder.status == OrderStatus.TO_SHIP, SalesOrder.fulfillment == "FBM",
               SalesOrder.is_on_hold.is_(False), SalesOrder.warehouse_id.is_not(None), _free_order_filter())
        .order_by(SalesOrder.warehouse_id, SalesOrder.purchase_at, SalesOrder.id)
        .with_for_update(of=SalesOrder)
    )
    if order_ids:
        stmt = stmt.where(SalesOrder.id.in_(order_ids))
    if warehouse_id:
        stmt = stmt.where(SalesOrder.warehouse_id == warehouse_id)
    if ctx.shop_ids is not None:
        stmt = stmt.where(SalesOrder.shop_id.in_(ctx.shop_ids))
    orders = db.execute(stmt).scalars().all()
    if not orders:
        raise BizError("没有可生成波次的订单（需为待发货、未挂起、未在进行中的波次内的自发货订单）")
    groups: dict[int, list[SalesOrder]] = defaultdict(list)
    for o in orders:
        groups[o.warehouse_id].append(o)
    waves = []
    for wh_id, group in groups.items():
        for start in range(0, len(group), max_orders):
            chunk = group[start:start + max_orders]
            sku_count, units = _wave_stats(chunk)
            wave = PickWave(wave_no=next_doc_no(db, "BC"), warehouse_id=wh_id, status="picking", order_count=len(chunk),
                            sku_count=sku_count, unit_count=units, remark=remark)
            db.add(wave)
            db.flush()
            for o in chunk:
                o.wave_id = wave.id
            audit(ctx, "create", "pick_wave", wave.id, f"生成拣货波次 {wave.wave_no}（{len(chunk)} 单）")
            waves.append(wave)
    skipped = len(order_ids) - len(orders) if order_ids else 0
    db.commit()
    return {"waves": waves, "skipped": max(skipped, 0)}


def wave_orders(db, wave_id: int) -> list[SalesOrder]:
    return list(db.execute(
        select(SalesOrder).where(SalesOrder.wave_id == wave_id).order_by(SalesOrder.purchase_at, SalesOrder.id)
    ).scalars().all())


def pick_lines(db, wave: PickWave, orders: list[SalesOrder] | None = None) -> list[dict]:
    """拣货汇总：按库位 + SKU 合并（已取消订单不计入）。"""
    orders = orders if orders is not None else wave_orders(db, wave.id)
    agg: dict[int, dict] = {}
    for o in orders:
        if o.status not in (OrderStatus.TO_SHIP, OrderStatus.SHIPPED):
            continue
        for p in _plan(o):
            line = agg.setdefault(p["product_id"], {"product_id": p["product_id"], "qty": 0, "orders": []})
            line["qty"] += int(p["qty"])
            line["orders"].append({"order_no": o.order_no, "platform_order_id": o.platform_order_id, "qty": int(p["qty"])})
    if not agg:
        return []
    pids = list(agg)
    products = {p.id: p for p in db.execute(select(Product).where(Product.id.in_(pids))).scalars().all()}
    bins = dict(db.execute(
        select(InventoryBalance.product_id, InventoryBalance.bin_code)
        .where(InventoryBalance.warehouse_id == wave.warehouse_id, InventoryBalance.product_id.in_(pids))
    ).all())
    out = []
    for pid, line in agg.items():
        prod = products.get(pid)
        out.append({**line, "sku": prod.sku if prod else str(pid), "name": prod.name if prod else "-",
                    "image_url": prod.image_url if prod else None, "barcode": prod.barcode if prod else None,
                    "bin_code": bins.get(pid)})
    out.sort(key=lambda x: (x["bin_code"] is None, x["bin_code"] or "", x["sku"]))
    return out


def get_wave(db, wave_id: int, *, lock: bool = False) -> PickWave:
    stmt = select(PickWave).where(PickWave.id == wave_id)
    if lock:
        stmt = stmt.with_for_update(of=PickWave)
    wave = db.execute(stmt).scalar_one_or_none()
    if wave is None:
        raise BizError("拣货波次不存在")
    return wave


def mark_picked(ctx: Ctx, wave_id: int, picker_id: int | None) -> PickWave:
    wave = get_wave(ctx.db, wave_id, lock=True)
    if wave.status != "picking":
        raise BizError("只有拣货中的波次可以标记拣货完成")
    wave.status = "picked"
    wave.picked_at = utcnow()
    wave.picker_id = picker_id or ctx.user.id
    audit(ctx, "update", "pick_wave", wave.id, f"波次 {wave.wave_no} 拣货完成")
    ctx.db.commit()
    return wave


def complete_wave(ctx: Ctx, wave_id: int) -> PickWave:
    db = ctx.db
    wave = get_wave(db, wave_id, lock=True)
    if wave.status not in ACTIVE:
        raise BizError("波次已完成或已取消")
    pending = db.execute(select(func.count()).select_from(SalesOrder).where(
        SalesOrder.wave_id == wave.id, SalesOrder.status == OrderStatus.TO_SHIP)).scalar_one()
    if pending:
        raise BizError(f"波次内还有 {pending} 单未发货，请先发货或移出波次")
    wave.status = "completed"
    wave.completed_at = utcnow()
    audit(ctx, "update", "pick_wave", wave.id, f"波次 {wave.wave_no} 完成")
    db.commit()
    return wave


def cancel_wave(ctx: Ctx, wave_id: int) -> PickWave:
    db = ctx.db
    wave = get_wave(db, wave_id, lock=True)
    if wave.status not in ACTIVE:
        raise BizError("波次已完成或已取消")
    for o in wave_orders(db, wave.id):
        if o.status == OrderStatus.TO_SHIP:
            o.wave_id = None
    wave.status = "cancelled"
    audit(ctx, "cancel", "pick_wave", wave.id, f"取消波次 {wave.wave_no}，订单退回待发货")
    db.commit()
    return wave


def remove_orders(ctx: Ctx, wave_id: int, order_ids: list[int]) -> PickWave:
    db = ctx.db
    wave = get_wave(db, wave_id, lock=True)
    if wave.status not in ACTIVE:
        raise BizError("波次已完成或已取消")
    orders = [o for o in wave_orders(db, wave.id) if o.id in set(order_ids)]
    for o in orders:
        if o.status == OrderStatus.SHIPPED:
            raise BizError(f"订单 {o.platform_order_id} 已发货，不能移出波次")
        o.wave_id = None
    db.flush()
    remaining = wave_orders(db, wave.id)
    wave.order_count = len(remaining)
    wave.sku_count, wave.unit_count = _wave_stats([o for o in remaining if o.status != OrderStatus.CANCELLED])
    if not remaining:
        wave.status = "cancelled"
    audit(ctx, "update", "pick_wave", wave.id, f"波次 {wave.wave_no} 移出 {len(orders)} 单")
    db.commit()
    return wave


def after_ship(db, order: SalesOrder) -> None:
    """订单发货后：波次内订单全部处理完则自动完成波次。"""
    if not order.wave_id:
        return
    wave = db.get(PickWave, order.wave_id)
    if wave is None or wave.status not in ACTIVE:
        return
    db.flush()
    pending = db.execute(select(func.count()).select_from(SalesOrder).where(
        SalesOrder.wave_id == wave.id, SalesOrder.status == OrderStatus.TO_SHIP)).scalar_one()
    if not pending:
        wave.status = "completed"
        wave.completed_at = utcnow()


# ================================================================ 扫码验货
def find_order_by_code(ctx: Ctx, code: str) -> SalesOrder:
    """按系统单号 / 平台单号 / 运单号查找订单（扫描面单或装箱单条码）。"""
    code = (code or "").strip()
    if not code:
        raise BizError("请扫描或输入单号")
    stmt = select(SalesOrder).where(or_(SalesOrder.order_no == code, SalesOrder.platform_order_id == code,
                                        SalesOrder.tracking_no == code))
    if ctx.shop_ids is not None:
        stmt = stmt.where(SalesOrder.shop_id.in_(ctx.shop_ids))
    rows = ctx.db.execute(stmt.order_by(SalesOrder.id.desc()).limit(5)).scalars().all()
    if not rows:
        raise BizError(f"未找到订单：{code}")
    if len(rows) > 1:
        to_ship = [o for o in rows if o.status == OrderStatus.TO_SHIP]
        if len(to_ship) != 1:
            raise BizError(f"单号 {code} 匹配到多个订单，请使用系统单号")
        return to_ship[0]
    return rows[0]


def scan_codes(db, order: SalesOrder) -> list[dict]:
    """订单待验货清单：每个出库 SKU 可被识别的条码（SKU / 商品条码 / FNSKU / MSKU）。"""
    plan = _plan(order)
    if not plan:
        return []
    pids = {p["product_id"] for p in plan}
    products = {p.id: p for p in db.execute(select(Product).where(Product.id.in_(pids))).scalars().all()}
    item_codes: dict[int, set[str]] = defaultdict(set)
    listing_ids = {i.listing_id for i in order.items if i.listing_id}
    listings = {x.id: x for x in db.execute(select(Listing).where(Listing.id.in_(listing_ids))).scalars().all()} if listing_ids else {}
    for i in order.items:
        if i.msku:
            item_codes[i.id].add(i.msku)
        lst = listings.get(i.listing_id)
        if lst and lst.fnsku:
            item_codes[i.id].add(lst.fnsku)
    agg: dict[int, dict] = {}
    for p in plan:
        prod = products.get(p["product_id"])
        line = agg.setdefault(p["product_id"], {
            "product_id": p["product_id"], "sku": prod.sku if prod else str(p["product_id"]),
            "name": prod.name if prod else "-", "image_url": prod.image_url if prod else None, "qty": 0, "codes": set(),
        })
        line["qty"] += int(p["qty"])
        if prod:
            line["codes"].update(c for c in (prod.sku, prod.barcode) if c)
        # 单品订单行（非组合）可用 MSKU / FNSKU 识别
        item = next((i for i in order.items if i.id == p["item_id"]), None)
        if item is not None and item.product_id == p["product_id"]:
            line["codes"].update(item_codes.get(item.id, set()))
    return [{**x, "codes": sorted(x["codes"])} for x in agg.values()]


# ================================================================ 运单号导入
TRACKING_COLUMNS = [
    ("order", "订单号（系统单号或平台单号）"), ("carrier", "物流商"), ("tracking_no", "运单号"),
    ("actual_freight", "实际运费（本位币）"), ("ship", "是否发货(Y/N)"),
]


def import_tracking(ctx: Ctx, rows: list[dict], default_ship: bool) -> tuple[dict, list[int]]:
    """批量回填运单号：待发货订单（默认）直接发货，已发货订单仅更新运单信息。"""
    from app.modules.order.service import ship_order

    db = ctx.db
    result = {"created": 0, "updated": 0, "skipped": 0, "errors": []}
    shipped: list[int] = []
    for row in rows:
        code = str(row.get("order") or "").strip()
        sp = db.begin_nested()
        try:
            if not code:
                raise BizError("订单号不能为空")
            tracking = str(row.get("tracking_no") or "").strip()
            if not tracking:
                raise BizError("运单号不能为空")
            order = find_order_by_code(ctx, code)
            db.execute(select(SalesOrder.id).where(SalesOrder.id == order.id).with_for_update(of=SalesOrder))
            freight = row.get("actual_freight")
            try:
                freight = Decimal(str(freight)) if freight not in (None, "") else None
            except InvalidOperation as exc:
                raise BizError(f"运费格式错误：{freight}") from exc
            flag = str(row.get("ship") or "").strip().upper()
            do_ship = default_ship if not flag else flag in ("Y", "YES", "1", "是", "TRUE")
            data = {"carrier": str(row.get("carrier") or "").strip() or None, "tracking_no": tracking, "actual_freight": freight}
            if order.status == OrderStatus.TO_SHIP and do_ship:
                ship_order(ctx, order, data)
                audit(ctx, "发货", "sales_order", order.id, f"导入运单号发货 {order.platform_order_id}")
                shipped.append(order.id)
                result["created"] += 1
            elif order.status in (OrderStatus.TO_SHIP, OrderStatus.SHIPPED, OrderStatus.DELIVERED):
                order.tracking_no = tracking
                order.carrier = data["carrier"] or order.carrier
                if freight is not None:
                    order.actual_freight = freight
                result["updated"] += 1
            else:
                raise BizError(f"订单状态为 {order.status}，不能回填运单号")
            sp.commit()
        except BizError as exc:
            sp.rollback()
            result["skipped"] += 1
            result["errors"].append(f"第 {row.get('_row')} 行 {code}: {exc.message}")
    db.commit()
    return result, shipped
