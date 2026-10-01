"""订单处理：平台订单落库（幂等）、自发货审单/锁库/发货、FBA 成本核算、退货退款。

自发货（FBM）流程：待审核 → 审核（分配仓库、锁定库存）→ 待发货 → 发货（FIFO 出库核算成本）→ 已发货
FBA 订单：平台发货后，从对应 FBA 虚拟仓按 FIFO 出库，获得含头程的落地成本。
"""

import secrets
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.common.audit import audit
from app.common.crud import get_or_404
from app.common.currency import to_base
from app.common.enums import LedgerType, OrderStatus, ReturnStatus
from app.common.numbering import next_doc_no
from app.core.deps import Ctx
from app.core.errors import BizError
from app.core.types import q2, utcnow
from app.integrations.dto import OrderDTO
from app.modules.logistics.models import LogisticsChannel
from app.modules.logistics.service import calc_freight
from app.modules.order.models import ReturnOrder, ReturnOrderLine, SalesOrder, SalesOrderItem
from app.modules.product.models import Listing, Product
from app.modules.product.service import expand_bundle
from app.modules.shop.models import Shop
from app.modules.system.service import get_setting
from app.modules.warehouse.inventory import InventoryService, Ref
from app.modules.warehouse.models import Warehouse

FBM_ACTIVE = (OrderStatus.PENDING, OrderStatus.TO_AUDIT, OrderStatus.TO_SHIP)


def local_date_of(dt: datetime, tz: str | None):
    try:
        return dt.astimezone(ZoneInfo(tz or "UTC")).date()
    except Exception:  # noqa: BLE001
        return dt.date()


def _commission_rate(db) -> Decimal:
    return Decimal(str(get_setting(db, "finance.fee_estimate_commission_rate") or 0))


def _recalc_totals(order: SalesOrder) -> None:
    order.item_amount = q2(sum((i.item_amount for i in order.items), Decimal(0)))
    order.shipping_amount = q2(sum((i.shipping_amount for i in order.items), Decimal(0)))
    order.tax_amount = q2(sum((i.tax_amount for i in order.items), Decimal(0)))
    order.discount_amount = q2(sum((i.discount_amount for i in order.items), Decimal(0)))
    order.total_amount = q2(order.item_amount + order.shipping_amount + order.tax_amount - order.discount_amount)


def _pair_item(db, shop_id: int, item: SalesOrderItem, cache: dict) -> None:
    key = (shop_id, item.msku)
    if key not in cache:
        cache[key] = db.execute(select(Listing).where(Listing.shop_id == shop_id, Listing.msku == item.msku)).scalar_one_or_none()
    listing = cache[key]
    if listing is not None:
        item.listing_id = listing.id
        item.asin = item.asin or listing.asin
        item.title = item.title or listing.title
        if listing.product_id:
            item.product_id = listing.product_id
            item.sku = listing.product.sku if listing.product else None


def _apply_item_fees(db, item: SalesOrderItem, dto_item, rate: Decimal) -> None:
    if dto_item.commission_fee is not None or dto_item.fulfillment_fee is not None:
        item.commission_fee = abs(Decimal(dto_item.commission_fee or 0))
        item.fulfillment_fee = abs(Decimal(dto_item.fulfillment_fee or 0))
        item.other_fee = abs(Decimal(dto_item.other_fee or 0))
        item.fee_estimated = False
    elif item.fee_estimated:
        item.commission_fee = q2((item.item_amount - item.discount_amount) * rate)


# ================================================================ 平台订单落库
def upsert_order(ctx: Ctx, shop: Shop, dto: OrderDTO) -> tuple[SalesOrder, bool]:
    """按 (店铺, 平台订单号) 幂等写入订单，并推进状态。返回 (订单, 是否新建)。"""
    db = ctx.db
    order = db.execute(
        select(SalesOrder).where(SalesOrder.shop_id == shop.id, SalesOrder.platform_order_id == dto.platform_order_id)
    ).scalar_one_or_none()
    created = order is None
    rate = _commission_rate(db)
    pair_cache: dict = {}
    if created:
        order = SalesOrder(
            order_no=next_doc_no(db, "SO"),
            shop_id=shop.id,
            platform=shop.platform,
            platform_order_id=dto.platform_order_id,
            fulfillment=dto.fulfillment,
            status=OrderStatus.PENDING if dto.status == "pending" else (
                OrderStatus.TO_AUDIT if dto.fulfillment == "FBM" else OrderStatus.PENDING
            ),
            purchase_at=dto.purchase_at,
            local_date=local_date_of(dto.purchase_at, shop.timezone),
            currency=(dto.currency or shop.currency).upper(),
        )
        db.add(order)
    # 可更新字段
    for f in ("platform_status", "paid_at", "latest_ship_at", "buyer_name", "buyer_email", "ship_name", "ship_phone",
              "ship_country", "ship_state", "ship_city", "ship_address1", "ship_address2", "ship_postcode", "buyer_note"):
        v = getattr(dto, f)
        if v is not None:
            setattr(order, f, v)
    if dto.carrier:
        order.carrier = dto.carrier
    if dto.tracking_no:
        order.tracking_no = dto.tracking_no

    existing = {(i.platform_item_id or i.msku): i for i in order.items}
    can_add_items = created or order.status in (OrderStatus.PENDING, OrderStatus.TO_AUDIT)
    for di in dto.items:
        key = di.platform_item_id or di.msku
        item = existing.get(key)
        if item is None:
            if not can_add_items:
                continue
            item = SalesOrderItem(shop_id=shop.id, msku=di.msku, platform_item_id=di.platform_item_id, fee_estimated=True)
            order.items.append(item)
            existing[key] = item
        item.asin = di.asin or item.asin
        item.title = di.title or item.title
        if not item.cost_settled:
            item.quantity = di.quantity
        item.item_amount = q2(di.item_amount)
        item.unit_price = q2(di.item_amount / di.quantity) if di.quantity else Decimal(0)
        item.shipping_amount = q2(di.shipping_amount)
        item.tax_amount = q2(di.tax_amount)
        item.discount_amount = q2(di.discount_amount)
        _apply_item_fees(db, item, di, rate)
        if item.product_id is None:
            _pair_item(db, shop.id, item, pair_cache)
    _recalc_totals(order)
    db.flush()
    _advance_status(ctx, shop, order, dto)
    return order, created


def _advance_status(ctx: Ctx, shop: Shop, order: SalesOrder, dto: OrderDTO) -> None:
    db = ctx.db
    st = dto.status
    if st == "cancelled":
        if order.status in FBM_ACTIVE:
            _do_cancel(ctx, order, "平台已取消")
        elif order.status != OrderStatus.CANCELLED:
            order.tags = sorted(set(order.tags or []) | {"平台已取消(发货后)"})
        return
    if order.fulfillment == "FBA":
        if st in ("shipped", "delivered") and order.status not in (OrderStatus.SHIPPED, OrderStatus.DELIVERED):
            order.status = OrderStatus.SHIPPED
            order.shipped_at = dto.shipped_at or order.purchase_at
            settle_fba_cost(ctx, shop, order)
        elif st == "unshipped" and order.status == OrderStatus.PENDING:
            order.status = OrderStatus.PENDING
        if st == "delivered":
            order.status = OrderStatus.DELIVERED
        return
    # FBM
    if st == "unshipped" and order.status == OrderStatus.PENDING:
        order.status = OrderStatus.TO_AUDIT
    if order.status == OrderStatus.TO_AUDIT and get_setting(db, "order.auto_audit") and not order.is_on_hold:
        try:
            with db.begin_nested():
                audit_order(ctx, order, None, None)
        except BizError as exc:
            order.tags = sorted(set(order.tags or []) | {"自动审核失败"})
            order.remark = (order.remark or "") + f" [自动审核失败:{exc.message}]"
    if st in ("shipped", "delivered") and order.status in (OrderStatus.TO_AUDIT, OrderStatus.PENDING, OrderStatus.TO_SHIP):
        # 卖家在平台后台直接发货：系统补扣库存
        if order.status != OrderStatus.TO_SHIP:
            audit_order(ctx, order, None, None, force=True)
        ship_order(ctx, order, {"carrier": dto.carrier, "tracking_no": dto.tracking_no}, shipped_at=dto.shipped_at)
    if st == "delivered" and order.status == OrderStatus.SHIPPED:
        order.status = OrderStatus.DELIVERED
        order.delivered_at = utcnow()


# ================================================================ 库存与成本
def stock_components(db, order: SalesOrder) -> list[dict]:
    """订单行 → 需要出库的本地 SKU（考虑配对数量与组合产品）。"""
    plan = []
    for item in order.items:
        if not item.product_id:
            raise BizError(f"订单 {order.platform_order_id} 的 MSKU {item.msku} 未配对本地 SKU")
        pair_qty = 1
        if item.listing_id:
            listing = db.get(Listing, item.listing_id)
            pair_qty = listing.pair_quantity if listing else 1
        units = item.quantity * pair_qty
        for comp_id, qty in expand_bundle(db, item.product_id, units):
            plan.append({"item_id": item.id, "product_id": comp_id, "qty": qty})
    return plan


def _aggregate(plan: list[dict]) -> dict[int, int]:
    agg: dict[int, int] = defaultdict(int)
    for p in plan:
        agg[p["product_id"]] += p["qty"]
    return agg


def default_ship_warehouse(db) -> int:
    wid = get_setting(db, "order.default_warehouse_id")
    if wid and db.get(Warehouse, int(wid)):
        return int(wid)
    wh = db.execute(
        select(Warehouse).where(Warehouse.warehouse_type.in_(["local", "overseas", "third_party"]), Warehouse.status == "active")
        .order_by(Warehouse.is_default.desc(), Warehouse.id)
    ).scalars().first()
    if wh is None:
        raise BizError("没有可用的发货仓库")
    return wh.id


def _estimate_freight(db, order: SalesOrder, plan: list[dict]) -> None:
    weight = Decimal(0)
    for p in plan:
        prod = db.get(Product, p["product_id"])
        weight += Decimal(prod.weight_kg or 0) * p["qty"]
    order.weight_kg = weight
    if order.logistics_channel_id:
        ch = db.get(LogisticsChannel, order.logistics_channel_id)
        if ch:
            _, fee = calc_freight(ch, weight_kg=weight)
            order.est_freight = q2(to_base(db, fee, ch.currency))


def audit_order(ctx: Ctx, order: SalesOrder, warehouse_id: int | None, channel_id: int | None, *, force: bool = False) -> SalesOrder:
    """审核：分配仓库与物流，锁定库存。force=True 用于平台已发货补扣（允许负库存）。"""
    db = ctx.db
    if order.fulfillment != "FBM":
        raise BizError("FBA 订单无需审核")
    if order.status not in (OrderStatus.TO_AUDIT, OrderStatus.PENDING):
        raise BizError(f"订单 {order.platform_order_id} 当前状态不能审核")
    if order.is_on_hold and not force:
        raise BizError(f"订单 {order.platform_order_id} 已挂起")
    wid = warehouse_id or order.warehouse_id or default_ship_warehouse(db)
    wh = get_or_404(db, Warehouse, wid, "仓库")
    if wh.warehouse_type == "fba":
        raise BizError("自发货订单不能从 FBA 仓发货")
    order.warehouse_id = wid
    if channel_id:
        order.logistics_channel_id = channel_id
    plan = stock_components(db, order)
    inv = InventoryService(db)
    ref = Ref("sales_order", order.id, order.order_no, f"订单 {order.platform_order_id}", order.local_date)
    for pid, qty in _aggregate(plan).items():
        if force:
            bal = inv.balance(wid, pid)
            bal.qty_locked += qty
        else:
            inv.lock(wid, pid, qty, ref)
    order.stock_plan = plan
    _estimate_freight(db, order, plan)
    order.status = OrderStatus.TO_SHIP
    order.audited_at = utcnow()
    order.audited_by = ctx.user_id
    return order


def ship_order(ctx: Ctx, order: SalesOrder, data: dict, *, shipped_at: datetime | None = None) -> SalesOrder:
    db = ctx.db
    if order.status != OrderStatus.TO_SHIP:
        raise BizError(f"订单 {order.platform_order_id} 不在待发货状态")
    inv = InventoryService(db)
    ref = Ref("sales_order", order.id, order.order_no, f"订单 {order.platform_order_id}", order.local_date)
    items = {i.id: i for i in order.items}
    for i in items.values():
        i.cost_purchase = Decimal(0)
        i.cost_freight = Decimal(0)
    for p in order.stock_plan or []:
        res = inv.outbound(order.warehouse_id, p["product_id"], p["qty"], ref, change_type=LedgerType.SALE_OUT,
                           from_locked=True, allow_negative=True)
        item = items.get(p["item_id"])
        if item is not None:
            item.cost_purchase += q2(res.purchase_cost)
            item.cost_freight += q2(res.freight_cost)
    for i in items.values():
        i.cost_settled = True
        i.quantity_shipped = i.quantity
    order.carrier = data.get("carrier") or order.carrier
    order.tracking_no = data.get("tracking_no") or order.tracking_no
    if data.get("actual_freight") is not None:
        order.actual_freight = q2(data["actual_freight"])
    elif not order.actual_freight:
        order.actual_freight = order.est_freight
    order.status = OrderStatus.SHIPPED
    order.shipped_at = shipped_at or utcnow()
    return order


def settle_fba_cost(ctx: Ctx, shop: Shop, order: SalesOrder) -> None:
    """FBA 订单发货：从店铺 FBA 虚拟仓 FIFO 出库，记录落地成本（无批次时按参考成本）。"""
    db = ctx.db
    fba_wh = db.execute(
        select(Warehouse).where(Warehouse.shop_id == shop.id, Warehouse.warehouse_type == "fba")
    ).scalars().first()
    inv = InventoryService(db)
    ref = Ref("sales_order", order.id, order.order_no, f"FBA订单 {order.platform_order_id}", order.local_date)
    for item in order.items:
        if item.cost_settled:
            continue
        if not item.product_id:
            continue  # 未配对：配对后可重新核算
        item.cost_purchase = Decimal(0)
        item.cost_freight = Decimal(0)
        pair_qty = 1
        if item.listing_id:
            listing = db.get(Listing, item.listing_id)
            pair_qty = listing.pair_quantity if listing else 1
        for comp_id, qty in expand_bundle(db, item.product_id, item.quantity * pair_qty):
            if fba_wh is not None:
                res = inv.outbound(fba_wh.id, comp_id, qty, ref, change_type=LedgerType.SALE_OUT, allow_negative=True)
                item.cost_purchase += q2(res.purchase_cost)
                item.cost_freight += q2(res.freight_cost)
            else:
                prod = db.get(Product, comp_id)
                item.cost_purchase += q2(Decimal(prod.purchase_cost or 0) * qty)
        item.cost_settled = True
        item.quantity_shipped = item.quantity


def resettle_unpaired(ctx: Ctx, shop_id: int | None = None) -> int:
    """配对后对已发货但未核算成本的 FBA 订单重新核算。"""
    db = ctx.db
    stmt = (
        select(SalesOrder)
        .join(SalesOrderItem, SalesOrderItem.order_id == SalesOrder.id)
        .where(SalesOrder.fulfillment == "FBA", SalesOrder.status.in_([OrderStatus.SHIPPED, OrderStatus.DELIVERED]),
               SalesOrderItem.cost_settled.is_(False), SalesOrderItem.product_id.is_not(None))
        .distinct()
    )
    if shop_id:
        stmt = stmt.where(SalesOrder.shop_id == shop_id)
    n = 0
    for order in db.execute(stmt).scalars().all():
        settle_fba_cost(ctx, db.get(Shop, order.shop_id), order)
        n += 1
    db.commit()
    return n


def _do_cancel(ctx: Ctx, order: SalesOrder, reason: str | None) -> None:
    if order.status == OrderStatus.TO_SHIP:
        _release_lock(ctx, order)
    order.status = OrderStatus.CANCELLED
    order.cancel_reason = reason


def _release_lock(ctx: Ctx, order: SalesOrder) -> None:
    inv = InventoryService(ctx.db)
    ref = Ref("sales_order", order.id, order.order_no, f"订单 {order.platform_order_id}")
    for pid, qty in _aggregate(order.stock_plan or []).items():
        inv.unlock(order.warehouse_id, pid, qty, ref)
    order.stock_plan = None


# ================================================================ 对外操作
def _load_orders(ctx: Ctx, ids: list[int]) -> list[SalesOrder]:
    orders = ctx.db.execute(select(SalesOrder).where(SalesOrder.id.in_(ids)).with_for_update()).scalars().all()
    for o in orders:
        ctx.require_shop(o.shop_id)
    return orders


def batch(ctx: Ctx, ids: list[int], fn, action: str) -> dict:
    """批量执行：每单独立事务，返回成功/失败列表。"""
    result = {"success": [], "failed": []}
    for oid in ids:
        try:
            with ctx.db.begin_nested():
                orders = _load_orders(ctx, [oid])
                if not orders:
                    raise BizError("订单不存在")
                fn(orders[0])
                audit(ctx, action, "sales_order", oid, f"{action} 订单 {orders[0].platform_order_id}")
            result["success"].append(oid)
        except BizError as exc:
            result["failed"].append({"order_id": oid, "message": exc.message})
    ctx.db.commit()
    return result


def revert_audit(ctx: Ctx, order: SalesOrder) -> None:
    if order.status != OrderStatus.TO_SHIP:
        raise BizError("仅待发货订单可反审核")
    _release_lock(ctx, order)
    order.status = OrderStatus.TO_AUDIT
    order.audited_at = None


def cancel(ctx: Ctx, order: SalesOrder, reason: str | None) -> None:
    if order.status not in FBM_ACTIVE:
        raise BizError(f"订单 {order.platform_order_id} 当前状态不能取消")
    _do_cancel(ctx, order, reason)


def create_manual_order(ctx: Ctx, data: dict) -> SalesOrder:
    db = ctx.db
    shop = get_or_404(db, Shop, data["shop_id"], "店铺")
    ctx.require_shop(shop.id)
    items = []
    raw_items = data.pop("items")
    for it in raw_items:
        msku = it.get("msku")
        if not msku and it.get("product_id"):
            msku = get_or_404(db, Product, it["product_id"], "产品").sku
        if not msku:
            raise BizError("订单行需填写 MSKU 或选择产品")
        items.append({
            "msku": msku, "quantity": it["quantity"], "item_amount": Decimal(it["unit_price"]) * it["quantity"],
            "shipping_amount": it.get("shipping_amount") or 0, "tax_amount": it.get("tax_amount") or 0,
            "discount_amount": it.get("discount_amount") or 0, "title": it.get("title"), "_product_id": it.get("product_id"),
        })
    if len({i["msku"] for i in items}) != len(items):
        raise BizError("同一订单中 MSKU 不能重复，请合并数量")
    pid = data.get("platform_order_id") or f"M{utcnow():%y%m%d}{secrets.token_hex(3).upper()}"
    if db.execute(select(SalesOrder.id).where(SalesOrder.shop_id == shop.id, SalesOrder.platform_order_id == pid)).first():
        raise BizError(f"订单号 {pid} 已存在")
    dto = OrderDTO(
        platform_order_id=pid,
        fulfillment=data.get("fulfillment") or "FBM",
        status="unshipped",
        purchase_at=data.get("purchase_at") or utcnow(),
        currency=data.get("currency") or shop.currency,
        **{k: data.get(k) for k in ("buyer_name", "buyer_email", "ship_name", "ship_phone", "ship_country", "ship_state",
                                    "ship_city", "ship_address1", "ship_address2", "ship_postcode", "buyer_note")},
        items=[{k: v for k, v in i.items() if not k.startswith("_")} for i in items],
    )
    order, _ = upsert_order(ctx, shop, dto)
    order.remark = data.get("remark")
    # 直接选择产品的行：未配对时直接绑定产品
    for item, src in zip(order.items, items, strict=False):
        if item.product_id is None and src.get("_product_id"):
            prod = db.get(Product, src["_product_id"])
            item.product_id = prod.id
            item.sku = prod.sku
    audit(ctx, "create", "sales_order", order.id, f"手工创建订单 {order.platform_order_id}")
    db.commit()
    return order


# ================================================================ 退货
def create_return(ctx: Ctx, data: dict) -> ReturnOrder:
    db = ctx.db
    order = None
    if data.get("order_id"):
        order = get_or_404(db, SalesOrder, data["order_id"], "订单")
        shop_id = order.shop_id
        currency = order.currency
    else:
        if not data.get("shop_id"):
            raise BizError("请选择订单或店铺")
        shop_id = data["shop_id"]
        currency = data.get("currency") or get_or_404(db, Shop, shop_id, "店铺").currency
    ctx.require_shop(shop_id)
    ret = ReturnOrder(
        return_no=next_doc_no(db, "RT"),
        order_id=order.id if order else None,
        shop_id=shop_id,
        platform_return_id=data.get("platform_return_id"),
        return_type=data.get("return_type") or "return_refund",
        status=ReturnStatus.PENDING,
        reason=data.get("reason"),
        currency=currency,
        return_date=data.get("return_date") or utcnow().date(),
        warehouse_id=data.get("warehouse_id"),
        remark=data.get("remark"),
    )
    items = {i.id: i for i in order.items} if order else {}
    total = Decimal(0)
    for ln in data["lines"]:
        item = items.get(ln.get("order_item_id")) if ln.get("order_item_id") else None
        if ln.get("order_item_id") and item is None:
            raise BizError("订单行不存在")
        if item is not None and ln["qty"] > item.quantity - item.refund_qty:
            raise BizError(f"MSKU {item.msku} 退货数量超过可退数量")
        if ln["qty_good"] + ln["qty_defective"] > ln["qty"]:
            raise BizError("入库数量不能超过退货数量")
        ret.lines.append(
            ReturnOrderLine(
                order_item_id=item.id if item else None,
                product_id=(item.product_id if item else ln.get("product_id")),
                msku=(item.msku if item else ln.get("msku")),
                qty=ln["qty"],
                refund_amount=q2(ln["refund_amount"]),
                qty_good=ln["qty_good"],
                qty_defective=ln["qty_defective"],
            )
        )
        total += Decimal(ln["refund_amount"])
    ret.refund_amount = q2(total)
    db.add(ret)
    db.flush()
    audit(ctx, "create", "return_order", ret.id, f"新建退货单 {ret.return_no}")
    db.commit()
    return ret


def complete_return(ctx: Ctx, ret_id: int, warehouse_id: int | None, lines: list[dict] | None) -> ReturnOrder:
    """完成退货：良品/次品入库，更新订单行退款数据。良品按原出库成本回库并冲减销售成本。"""
    db = ctx.db
    ret = get_or_404(db, ReturnOrder, ret_id, "退货单", for_update=True)
    ctx.require_shop(ret.shop_id)
    if ret.status != ReturnStatus.PENDING:
        raise BizError("退货单不在待处理状态")
    if lines:
        by_id = {ln.id: ln for ln in ret.lines}
        for x in lines:
            ln = by_id.get(x.get("line_id"))
            if ln is None:
                raise BizError("退货明细不存在")
            ln.qty_good = int(x.get("qty_good") or 0)
            ln.qty_defective = int(x.get("qty_defective") or 0)
            if ln.qty_good + ln.qty_defective > ln.qty:
                raise BizError("入库数量不能超过退货数量")
    wid = warehouse_id or ret.warehouse_id
    need_stock = ret.return_type != "refund_only" and any(ln.qty_good or ln.qty_defective for ln in ret.lines)
    if need_stock and not wid:
        raise BizError("请选择退货入库仓库")
    ret.warehouse_id = wid
    inv = InventoryService(db)
    ref = Ref("return_order", ret.id, ret.return_no, ret.reason)
    order_items = {}
    if ret.order_id:
        order = db.get(SalesOrder, ret.order_id)
        order_items = {i.id: i for i in order.items}
    restock_cost = Decimal(0)
    for ln in ret.lines:
        item = order_items.get(ln.order_item_id)
        if item is not None:
            item.refund_qty += ln.qty
            item.refund_amount = q2(Decimal(item.refund_amount or 0) + Decimal(ln.refund_amount))
        if ret.return_type == "refund_only" or not ln.product_id:
            continue
        # 按原订单单位成本回库
        unit_pc = unit_fc = None
        if item is not None and item.cost_settled and item.quantity:
            unit_pc = Decimal(item.cost_purchase) / item.quantity
            unit_fc = Decimal(item.cost_freight) / item.quantity
        for comp_id, qty in expand_bundle(db, ln.product_id, ln.qty_good):
            batch = inv.inbound(wid, comp_id, qty, ref, change_type=LedgerType.RETURN_IN,
                                unit_purchase_cost=unit_pc if comp_id == ln.product_id else None,
                                unit_freight_cost=unit_fc if (unit_fc is not None and comp_id == ln.product_id) else Decimal(0))
            restock_cost += (batch.unit_purchase_cost + batch.unit_freight_cost) * qty
        for comp_id, qty in expand_bundle(db, ln.product_id, ln.qty_defective):
            inv.inbound_defective(wid, comp_id, qty, ref)
    ret.restock_cost = q2(restock_cost)
    ret.status = ReturnStatus.COMPLETED
    ret.completed_at = utcnow()
    audit(ctx, "complete", "return_order", ret.id, f"完成退货 {ret.return_no}")
    db.commit()
    return ret


def cancel_return(ctx: Ctx, ret_id: int) -> ReturnOrder:
    ret = get_or_404(ctx.db, ReturnOrder, ret_id, "退货单", for_update=True)
    ctx.require_shop(ret.shop_id)
    if ret.status != ReturnStatus.PENDING:
        raise BizError("仅待处理退货单可取消")
    ret.status = ReturnStatus.CANCELLED
    audit(ctx, "cancel", "return_order", ret.id, f"取消退货 {ret.return_no}")
    ctx.db.commit()
    return ret


def estimate_profit(db, order: SalesOrder) -> Decimal | None:
    """订单预估利润（本位币）。"""
    if order.status == OrderStatus.CANCELLED:
        return Decimal(0)
    try:
        revenue = sum((i.item_amount + i.shipping_amount - i.discount_amount - i.commission_fee - i.fulfillment_fee
                       - i.other_fee - i.refund_amount) for i in order.items)
        base = to_base(db, revenue, order.currency, order.local_date)
    except BizError:
        return None
    cost = sum((i.cost_purchase + i.cost_freight) for i in order.items)
    return q2(base - cost - Decimal(order.actual_freight or 0))
