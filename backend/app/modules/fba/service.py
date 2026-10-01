"""FBA / 海外仓头程：发货计划 → 货件 → 发货出库 → 签收入库（头程费用分摊进成本）。

头程分摊：总费用（运费+关税+其他）× 汇率 → 按 计费重 / 体积 / 数量 / 货值 分摊到每个 SKU，
签收入库时与出库时的采购成本一起形成目的仓批次成本，后续 FBA 销售按 FIFO 结转。
费用后补（账单晚到）时可「重新分摊」，修正目的仓剩余批次的物流成本。
"""

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select

from app.common.audit import audit
from app.common.crud import get_or_404
from app.common.currency import get_rate
from app.common.enums import AllocationMethod, LedgerType, PlanStatus, ShipmentStatus
from app.common.numbering import next_doc_no
from app.core.deps import Ctx
from app.core.errors import BizError
from app.core.types import q4, utcnow
from app.modules.fba.models import FbaShipment, FbaShipmentLine, ShipmentPlan, ShipmentPlanLine
from app.modules.product.models import Listing, Product
from app.modules.product.service import expand_bundle
from app.modules.shop.models import Shop
from app.modules.system.service import get_setting
from app.modules.warehouse.inventory import InventoryService, Ref
from app.modules.warehouse.models import InventoryBatch, Warehouse


def fba_warehouse_of(ctx: Ctx, shop: Shop) -> Warehouse:
    wh = ctx.db.execute(
        select(Warehouse).where(Warehouse.shop_id == shop.id, Warehouse.warehouse_type == "fba")
    ).scalars().first()
    if wh is None:
        raise BizError(f"店铺 {shop.name} 没有 FBA 仓，请指定目的仓")
    return wh


def _resolve_lines(ctx: Ctx, shop: Shop, lines: list[dict]) -> list[dict]:
    """输入行（Listing 或产品 + MSKU 数量）→ SKU 级明细（展开配对数量与组合产品）。"""
    out: list[dict] = []
    for ln in lines:
        listing = None
        if ln.get("listing_id"):
            listing = get_or_404(ctx.db, Listing, ln["listing_id"], "Listing")
            if listing.shop_id != shop.id:
                raise BizError(f"MSKU {listing.msku} 不属于店铺 {shop.name}")
            if not listing.product_id:
                raise BizError(f"MSKU {listing.msku} 未配对本地 SKU")
            product_id = listing.product_id
            units = ln["qty"] * (listing.pair_quantity or 1)
        elif ln.get("product_id"):
            product_id = ln["product_id"]
            units = ln["qty"]
            if ln.get("msku"):
                listing = ctx.db.execute(
                    select(Listing).where(Listing.shop_id == shop.id, Listing.msku == ln["msku"])
                ).scalar_one_or_none()
        else:
            raise BizError("明细需指定 Listing 或产品")
        for comp_id, qty in expand_bundle(ctx.db, product_id, units):
            out.append({
                "listing_id": listing.id if listing else None,
                "msku": listing.msku if listing else ln.get("msku"),
                "fnsku": listing.fnsku if listing else ln.get("fnsku"),
                "product_id": comp_id,
                "qty": qty,
            })
    return out


# ================================================================ 发货计划
def create_plan(ctx: Ctx, data: dict) -> ShipmentPlan:
    shop = get_or_404(ctx.db, Shop, data["shop_id"], "店铺")
    ctx.require_shop(shop.id)
    get_or_404(ctx.db, Warehouse, data["ship_from_warehouse_id"], "发货仓")
    lines = _resolve_lines(ctx, shop, data.pop("lines"))
    plan = ShipmentPlan(plan_no=next_doc_no(ctx.db, "SP"), status=PlanStatus.PENDING, **data)
    plan.lines = [ShipmentPlanLine(listing_id=ln["listing_id"], msku=ln["msku"], fnsku=ln["fnsku"],
                                   product_id=ln["product_id"], qty=ln["qty"]) for ln in lines]
    ctx.db.add(plan)
    ctx.db.flush()
    audit(ctx, "create", "shipment_plan", plan.id, f"新建发货计划 {plan.plan_no}")
    return plan


def update_plan(ctx: Ctx, plan_id: int, data: dict) -> ShipmentPlan:
    plan = get_or_404(ctx.db, ShipmentPlan, plan_id, "发货计划", for_update=True)
    ctx.require_shop(plan.shop_id)
    if plan.status != PlanStatus.PENDING:
        raise BizError("仅待处理计划可修改")
    lines = data.pop("lines", None)
    for k, v in data.items():
        setattr(plan, k, v)
    if lines is not None:
        shop = ctx.db.get(Shop, plan.shop_id)
        plan.lines = [ShipmentPlanLine(listing_id=ln["listing_id"], msku=ln["msku"], fnsku=ln["fnsku"],
                                       product_id=ln["product_id"], qty=ln["qty"]) for ln in _resolve_lines(ctx, shop, lines)]
    ctx.db.commit()
    return plan


def plan_to_shipment(ctx: Ctx, plan_id: int) -> FbaShipment:
    plan = get_or_404(ctx.db, ShipmentPlan, plan_id, "发货计划", for_update=True)
    ctx.require_shop(plan.shop_id)
    if plan.status != PlanStatus.PENDING:
        raise BizError("仅待处理计划可生成货件")
    shipment = _new_shipment(
        ctx,
        {"shop_id": plan.shop_id, "ship_from_warehouse_id": plan.ship_from_warehouse_id,
         "to_warehouse_id": plan.to_warehouse_id, "logistics_channel_id": plan.logistics_channel_id,
         "plan_id": plan.id, "remark": f"由发货计划 {plan.plan_no} 生成"},
        [{"listing_id": ln.listing_id, "msku": ln.msku, "fnsku": ln.fnsku, "product_id": ln.product_id, "qty": ln.qty}
         for ln in plan.lines],
    )
    plan.status = PlanStatus.CONVERTED
    plan.shipment_id = shipment.id
    ctx.db.commit()
    return shipment


# ================================================================ 货件
def _snapshot_line(db, ln: FbaShipmentLine) -> None:
    p = db.get(Product, ln.product_id)
    ln.unit_weight_kg = Decimal(p.weight_kg or 0)
    ln.unit_volume_cbm = q4(Decimal(p.length_cm or 0) * Decimal(p.width_cm or 0) * Decimal(p.height_cm or 0) / Decimal(1_000_000))


def _build_shipment_lines(ctx: Ctx, shipment: FbaShipment, resolved: list[dict]) -> None:
    merged: dict[tuple, dict] = {}
    for ln in resolved:
        key = (ln["msku"], ln["product_id"])
        if key in merged:
            merged[key]["qty"] += ln["qty"]
        else:
            merged[key] = dict(ln)
    shipment.lines = []
    for ln in merged.values():
        line = FbaShipmentLine(listing_id=ln["listing_id"], msku=ln["msku"], fnsku=ln["fnsku"],
                               product_id=ln["product_id"], qty_shipped=ln["qty"])
        _snapshot_line(ctx.db, line)
        shipment.lines.append(line)


def _apply_boxes(db, shipment: FbaShipment) -> None:
    """根据装箱信息（无则按产品规格）计算总重、总体积与计费重。"""
    from app.modules.logistics.models import LogisticsChannel

    boxes = shipment.boxes or []
    if boxes:
        shipment.box_count = len(boxes)
        shipment.total_weight_kg = sum((Decimal(str(b.get("weight_kg") or 0)) for b in boxes), Decimal(0))
        shipment.total_volume_cbm = q4(sum(
            (Decimal(str(b.get("length_cm") or 0)) * Decimal(str(b.get("width_cm") or 0)) * Decimal(str(b.get("height_cm") or 0))
             for b in boxes), Decimal(0)) / Decimal(1_000_000))
    else:
        shipment.total_weight_kg = sum((ln.unit_weight_kg * ln.qty_shipped for ln in shipment.lines), Decimal(0))
        shipment.total_volume_cbm = q4(sum((ln.unit_volume_cbm * ln.qty_shipped for ln in shipment.lines), Decimal(0)))
    divisor = Decimal(6000)
    if shipment.logistics_channel_id:
        ch = db.get(LogisticsChannel, shipment.logistics_channel_id)
        if ch is not None and ch.volume_divisor:
            divisor = Decimal(ch.volume_divisor)
    vol_weight = Decimal(shipment.total_volume_cbm or 0) * Decimal(1_000_000) / divisor
    shipment.chargeable_weight_kg = max(Decimal(shipment.total_weight_kg or 0), vol_weight).quantize(Decimal("0.001"))


def _new_shipment(ctx: Ctx, data: dict, resolved_lines: list[dict]) -> FbaShipment:
    shop = get_or_404(ctx.db, Shop, data["shop_id"], "店铺")
    ctx.require_shop(shop.id)
    src = get_or_404(ctx.db, Warehouse, data["ship_from_warehouse_id"], "发货仓")
    if src.warehouse_type == "fba":
        raise BizError("发货仓不能是 FBA 仓")
    if not data.get("to_warehouse_id"):
        data["to_warehouse_id"] = fba_warehouse_of(ctx, shop).id
    else:
        get_or_404(ctx.db, Warehouse, data["to_warehouse_id"], "目的仓")
    if data["to_warehouse_id"] == src.id:
        raise BizError("发货仓与目的仓不能相同")
    data["allocation_method"] = data.get("allocation_method") or get_setting(ctx.db, "fba.default_allocation") or "weight"
    if data["allocation_method"] not in {m.value for m in AllocationMethod}:
        raise BizError("无效的分摊方式")
    boxes = data.pop("boxes", None)
    shipment = FbaShipment(shipment_no=next_doc_no(ctx.db, "FS"), status=ShipmentStatus.DRAFT,
                           **{k: v for k, v in data.items() if v is not None})
    shipment.boxes = [b if isinstance(b, dict) else b.model_dump(mode="json") for b in boxes] if boxes else None
    _build_shipment_lines(ctx, shipment, resolved_lines)
    _apply_boxes(ctx.db, shipment)
    ctx.db.add(shipment)
    ctx.db.flush()
    audit(ctx, "create", "fba_shipment", shipment.id, f"新建货件 {shipment.shipment_no}")
    return shipment


def create_shipment(ctx: Ctx, data: dict) -> FbaShipment:
    shop = get_or_404(ctx.db, Shop, data["shop_id"], "店铺")
    lines = _resolve_lines(ctx, shop, data.pop("lines"))
    shipment = _new_shipment(ctx, data, lines)
    ctx.db.commit()
    return shipment


def update_shipment(ctx: Ctx, shipment_id: int, data: dict) -> FbaShipment:
    db = ctx.db
    s = get_or_404(db, FbaShipment, shipment_id, "货件", for_update=True)
    ctx.require_shop(s.shop_id)
    lines = data.pop("lines", None)
    boxes = data.pop("boxes", None) if "boxes" in data else ...
    if s.status != ShipmentStatus.DRAFT:
        locked = {"lines", "to_warehouse_id"} & (set(data) | ({"lines"} if lines is not None else set()))
        if locked:
            raise BizError("已发货货件不能修改明细与目的仓")
    for k, v in data.items():
        setattr(s, k, v)
    if boxes is not ...:
        s.boxes = list(boxes) if boxes else None
    if lines is not None:
        shop = db.get(Shop, s.shop_id)
        _build_shipment_lines(ctx, s, _resolve_lines(ctx, shop, lines))
    _apply_boxes(db, s)
    cost_changed = {"freight_cost", "customs_duty", "other_cost", "cost_currency", "allocation_method"} & set(data)
    if cost_changed and s.status != ShipmentStatus.DRAFT:
        reallocate(ctx, s)
    audit(ctx, "update", "fba_shipment", s.id, f"修改货件 {s.shipment_no}")
    db.commit()
    return s


def ship(ctx: Ctx, shipment_id: int) -> FbaShipment:
    """发货：发货仓 FIFO 出库，记录采购成本，目的仓增加在途。"""
    db = ctx.db
    s = get_or_404(db, FbaShipment, shipment_id, "货件", for_update=True)
    ctx.require_shop(s.shop_id)
    if s.status != ShipmentStatus.DRAFT:
        raise BizError("货件不是待发货状态")
    inv = InventoryService(db)
    ref = Ref("fba_shipment", s.id, s.shipment_no, f"头程发货 {s.platform_shipment_id or ''}".strip())
    for ln in s.lines:
        res = inv.outbound(s.ship_from_warehouse_id, ln.product_id, ln.qty_shipped, ref, change_type=LedgerType.FBA_OUT)
        ln.unit_purchase_cost = res.unit_purchase_cost
        ln.unit_freight_cost = res.unit_freight_cost
        inv.add_in_transit(s.to_warehouse_id, ln.product_id, ln.qty_shipped)
    s.status = ShipmentStatus.SHIPPED
    s.shipped_at = utcnow()
    s.ship_date = s.ship_date or utcnow().date()
    allocate(ctx, s)
    audit(ctx, "ship", "fba_shipment", s.id, f"货件发货 {s.shipment_no}")
    db.commit()
    return s


def _total_cost_base(ctx: Ctx, s: FbaShipment) -> Decimal:
    total = Decimal(s.freight_cost or 0) + Decimal(s.customs_duty or 0) + Decimal(s.other_cost or 0)
    if not total:
        return Decimal(0)
    return total * get_rate(ctx.db, s.cost_currency or "CNY", s.ship_date)


def allocate(ctx: Ctx, s: FbaShipment) -> None:
    """按分摊方式计算每行头程费用（本位币）。"""
    total = _total_cost_base(ctx, s)
    method = s.allocation_method or AllocationMethod.WEIGHT
    weights: dict[int, Decimal] = {}
    for ln in s.lines:
        if method == AllocationMethod.WEIGHT:
            # 计费重：实重与体积重取大
            vol_w = Decimal(ln.unit_volume_cbm or 0) * Decimal(1_000_000) / Decimal(6000)
            w = max(Decimal(ln.unit_weight_kg or 0), vol_w) * ln.qty_shipped
        elif method == AllocationMethod.VOLUME:
            w = Decimal(ln.unit_volume_cbm or 0) * ln.qty_shipped
        elif method == AllocationMethod.VALUE:
            w = Decimal(ln.unit_purchase_cost or 0) * ln.qty_shipped
        else:
            w = Decimal(ln.qty_shipped)
        weights[id(ln)] = w
    denom = sum(weights.values(), Decimal(0))
    if denom <= 0:
        # 无重量/体积数据时退化为按数量分摊
        weights = {id(ln): Decimal(ln.qty_shipped) for ln in s.lines}
        denom = sum(weights.values(), Decimal(0))
    for ln in s.lines:
        ln.allocated_cost = q4(total * weights[id(ln)] / denom) if denom else Decimal(0)
    s.cost_allocated = bool(total)


def _allocated_unit(ln: FbaShipmentLine) -> Decimal:
    return q4(Decimal(ln.allocated_cost or 0) / ln.qty_shipped) if ln.qty_shipped else Decimal(0)


def receive(ctx: Ctx, shipment_id: int, lines: list[dict] | None, close: bool = False) -> FbaShipment:
    """签收：按实收数量入目的仓，成本 = 出库采购成本 + 原物流成本 + 本次头程分摊。"""
    db = ctx.db
    s = get_or_404(db, FbaShipment, shipment_id, "货件", for_update=True)
    ctx.require_shop(s.shop_id)
    if s.status not in (ShipmentStatus.SHIPPED, ShipmentStatus.RECEIVING):
        raise BizError("货件不是在途/签收中状态")
    by_id = {ln.id: ln for ln in s.lines}
    if lines:
        req = {x["line_id"]: x["qty_received"] for x in lines}
        for lid in req:
            if lid not in by_id:
                raise BizError(f"货件明细不存在: {lid}")
    else:
        req = {ln.id: ln.qty_shipped - ln.qty_received for ln in s.lines}
    inv = InventoryService(db)
    ref = Ref("fba_shipment", s.id, s.shipment_no, f"头程签收 {s.platform_shipment_id or ''}".strip())
    for lid, qty in req.items():
        if qty <= 0:
            continue
        ln = by_id[lid]
        if ln.qty_received + qty > ln.qty_shipped:
            raise BizError(f"{ln.msku or ln.product_id} 签收数量超过发货数量")
        inv.inbound(
            s.to_warehouse_id, ln.product_id, qty, ref, change_type=LedgerType.FBA_IN,
            unit_purchase_cost=ln.unit_purchase_cost,
            unit_freight_cost=Decimal(ln.unit_freight_cost or 0) + _allocated_unit(ln),
            batch_no=s.platform_shipment_id or s.shipment_no,
        )
        inv.add_in_transit(s.to_warehouse_id, ln.product_id, -qty)
        ln.qty_received += qty
    s.status = ShipmentStatus.RECEIVING
    if close or all(ln.qty_received >= ln.qty_shipped for ln in s.lines):
        _close(ctx, s)
    audit(ctx, "receive", "fba_shipment", s.id, f"货件签收 {s.shipment_no}")
    db.commit()
    return s


def _close(ctx: Ctx, s: FbaShipment) -> None:
    inv = InventoryService(ctx.db)
    for ln in s.lines:
        short = ln.qty_shipped - ln.qty_received
        if short > 0:
            inv.add_in_transit(s.to_warehouse_id, ln.product_id, -short)
    s.status = ShipmentStatus.CLOSED
    s.closed_at = utcnow()


def close(ctx: Ctx, shipment_id: int) -> FbaShipment:
    s = get_or_404(ctx.db, FbaShipment, shipment_id, "货件", for_update=True)
    ctx.require_shop(s.shop_id)
    if s.status not in (ShipmentStatus.SHIPPED, ShipmentStatus.RECEIVING):
        raise BizError("货件当前状态不能完结")
    _close(ctx, s)
    audit(ctx, "close", "fba_shipment", s.id, f"完结货件 {s.shipment_no}")
    ctx.db.commit()
    return s


def cancel(ctx: Ctx, shipment_id: int) -> FbaShipment:
    s = get_or_404(ctx.db, FbaShipment, shipment_id, "货件", for_update=True)
    ctx.require_shop(s.shop_id)
    if s.status != ShipmentStatus.DRAFT:
        raise BizError("仅待发货货件可取消")
    s.status = ShipmentStatus.CANCELLED
    if s.plan_id:
        plan = ctx.db.get(ShipmentPlan, s.plan_id)
        if plan and plan.shipment_id == s.id:
            plan.status = PlanStatus.PENDING
            plan.shipment_id = None
    audit(ctx, "cancel", "fba_shipment", s.id, f"取消货件 {s.shipment_no}")
    ctx.db.commit()
    return s


def reallocate(ctx: Ctx, s: FbaShipment) -> None:
    """费用变更后重新分摊，并修正目的仓中本货件形成的剩余批次的物流成本。"""
    old_unit = {ln.id: _allocated_unit(ln) for ln in s.lines}
    allocate(ctx, s)
    for ln in s.lines:
        delta = _allocated_unit(ln) - old_unit[ln.id]
        if not delta:
            continue
        batches = ctx.db.execute(
            select(InventoryBatch).where(
                InventoryBatch.source_type == "fba_shipment", InventoryBatch.source_id == s.id,
                InventoryBatch.product_id == ln.product_id, InventoryBatch.warehouse_id == s.to_warehouse_id,
            )
        ).scalars().all()
        for b in batches:
            b.unit_freight_cost = max(Decimal(0), Decimal(b.unit_freight_cost) + delta)


def shipment_summary_by_listing(ctx: Ctx, shop_id: int | None = None) -> dict[tuple[int, str], int]:
    """在途数量（已发货未签收）按 (店铺, MSKU) 汇总，用于补货计算。"""
    stmt = (
        select(FbaShipment.shop_id, FbaShipmentLine.msku, FbaShipmentLine.qty_shipped, FbaShipmentLine.qty_received)
        .join(FbaShipmentLine, FbaShipmentLine.shipment_id == FbaShipment.id)
        .where(FbaShipment.status.in_([ShipmentStatus.SHIPPED, ShipmentStatus.RECEIVING]))
    )
    if shop_id:
        stmt = stmt.where(FbaShipment.shop_id == shop_id)
    agg: dict[tuple[int, str], int] = defaultdict(int)
    for sid, msku, shipped, received in ctx.db.execute(stmt).all():
        agg[(sid, msku)] += max(0, shipped - received)
    return agg
