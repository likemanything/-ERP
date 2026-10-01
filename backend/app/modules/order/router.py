from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import func, select

from app.common.audit import audit
from app.common.crud import get_or_404
from app.common.excel import export_xlsx, read_upload, template_response
from app.common.pagination import PageParams, page_params, paginate
from app.common.schemas import Msg, Page
from app.core.deps import Ctx, perm
from app.core.errors import BizError
from app.core.types import utcnow
from app.integrations.dto import OrderDTO, OrderItemDTO
from app.modules.logistics.models import LogisticsChannel
from app.modules.order import service
from app.modules.order.models import ReturnOrder, SalesOrder, SalesOrderItem
from app.modules.order.schemas import (
    AuditIn,
    BatchResult,
    BatchShipIn,
    CancelIn,
    HoldIn,
    OrderIn,
    OrderOut,
    OrderUpdate,
    ReturnCompleteIn,
    ReturnIn,
    ReturnOut,
    ShipIn,
)
from app.modules.product.models import Listing, Product
from app.modules.product.schemas import ImportResult
from app.modules.shop.models import Shop
from app.modules.warehouse.models import Warehouse

router = APIRouter(tags=["订单管理"])


def _names(db, model, ids, attr="name") -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.execute(select(model.id, getattr(model, attr)).where(model.id.in_(ids))).all())


def order_out_many(ctx: Ctx, orders) -> list[dict]:
    orders = list(orders)
    db = ctx.db
    shops = _names(db, Shop, [o.shop_id for o in orders])
    whs = _names(db, Warehouse, [o.warehouse_id for o in orders])
    chs = _names(db, LogisticsChannel, [o.logistics_channel_id for o in orders])
    from app.modules.distribution.models import Distributor

    dists = _names(db, Distributor, [o.distributor_id for o in orders])
    listing_ids = {i.listing_id for o in orders for i in o.items if i.listing_id}
    images = dict(db.execute(select(Listing.id, Listing.image_url).where(Listing.id.in_(listing_ids))).all()) if listing_ids else {}
    show_cost = ctx.can("product:cost:view")
    out = []
    for o in orders:
        d = {c.key: getattr(o, c.key) for c in SalesOrder.__table__.columns}
        d.update(shop_name=shops.get(o.shop_id), warehouse_name=whs.get(o.warehouse_id),
                 logistics_channel_name=chs.get(o.logistics_channel_id), distributor_name=dists.get(o.distributor_id))
        d["has_unpaired"] = any(i.product_id is None for i in o.items)
        d["est_profit"] = service.estimate_profit(db, o) if show_cost else None
        items = []
        for i in o.items:
            it = {c.key: getattr(i, c.key) for c in SalesOrderItem.__table__.columns}
            it["image_url"] = images.get(i.listing_id)
            if not show_cost:
                it["cost_purchase"] = it["cost_freight"] = None
            items.append(it)
        d["items"] = items
        out.append(d)
    return out


def _order_query(ctx: Ctx, *, keyword=None, shop_id=None, status=None, fulfillment=None, date_from=None,
                 date_to=None, on_hold=None, unpaired=None, country=None, warehouse_id=None, distributor_id=None,
                 distribution_only=None):
    stmt = select(SalesOrder).order_by(SalesOrder.purchase_at.desc(), SalesOrder.id.desc())
    if keyword:
        kw = f"%{keyword.strip()}%"
        sub = select(SalesOrderItem.order_id).where(
            SalesOrderItem.msku.ilike(kw) | SalesOrderItem.sku.ilike(kw) | SalesOrderItem.asin.ilike(kw)
        )
        stmt = stmt.where(
            SalesOrder.platform_order_id.ilike(kw) | SalesOrder.order_no.ilike(kw) | SalesOrder.buyer_name.ilike(kw)
            | SalesOrder.tracking_no.ilike(kw) | SalesOrder.ship_name.ilike(kw) | SalesOrder.id.in_(sub)
        )
    if shop_id:
        stmt = stmt.where(SalesOrder.shop_id == shop_id)
    if status:
        stmt = stmt.where(SalesOrder.status.in_(status.split(",")))
    if fulfillment:
        stmt = stmt.where(SalesOrder.fulfillment == fulfillment)
    if date_from:
        stmt = stmt.where(SalesOrder.local_date >= date_from)
    if date_to:
        stmt = stmt.where(SalesOrder.local_date <= date_to)
    if on_hold is not None:
        stmt = stmt.where(SalesOrder.is_on_hold.is_(on_hold))
    if unpaired:
        stmt = stmt.where(SalesOrder.id.in_(select(SalesOrderItem.order_id).where(SalesOrderItem.product_id.is_(None))))
    if country:
        stmt = stmt.where(SalesOrder.ship_country == country)
    if warehouse_id:
        stmt = stmt.where(SalesOrder.warehouse_id == warehouse_id)
    if distributor_id:
        stmt = stmt.where(SalesOrder.distributor_id == distributor_id)
    if distribution_only is not None:
        stmt = stmt.where(SalesOrder.distributor_id.is_not(None) if distribution_only else SalesOrder.distributor_id.is_(None))
    if ctx.shop_ids is not None:
        stmt = stmt.where(SalesOrder.shop_id.in_(ctx.shop_ids))
    return stmt


@router.get("/orders", response_model=Page[OrderOut], summary="订单列表")
def list_orders(
    keyword: str | None = None,
    shop_id: int | None = None,
    status: str | None = None,
    fulfillment: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    on_hold: bool | None = None,
    unpaired: bool | None = None,
    country: str | None = None,
    warehouse_id: int | None = None,
    distributor_id: int | None = None,
    distribution_only: bool | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("order:view")),
):
    stmt = _order_query(ctx, keyword=keyword, shop_id=shop_id, status=status, fulfillment=fulfillment,
                        date_from=date_from, date_to=date_to, on_hold=on_hold, unpaired=unpaired, country=country,
                        warehouse_id=warehouse_id, distributor_id=distributor_id, distribution_only=distribution_only)
    page = paginate(ctx.db, stmt, params)
    page["items"] = order_out_many(ctx, page["items"])
    return page


@router.get("/orders/status-counts", summary="订单状态统计（页签角标）")
def status_counts(fulfillment: str | None = None, shop_id: int | None = None, distribution_only: bool | None = None,
                  ctx: Ctx = Depends(perm("order:view"))):
    stmt = select(SalesOrder.status, func.count()).group_by(SalesOrder.status)
    if distribution_only is not None:
        stmt = stmt.where(SalesOrder.distributor_id.is_not(None) if distribution_only else SalesOrder.distributor_id.is_(None))
    if fulfillment:
        stmt = stmt.where(SalesOrder.fulfillment == fulfillment)
    if shop_id:
        stmt = stmt.where(SalesOrder.shop_id == shop_id)
    if ctx.shop_ids is not None:
        stmt = stmt.where(SalesOrder.shop_id.in_(ctx.shop_ids))
    counts = {s: c for s, c in ctx.db.execute(stmt).all()}
    hold_stmt = select(func.count()).select_from(SalesOrder).where(SalesOrder.is_on_hold.is_(True),
                                                                    SalesOrder.status.in_(service.FBM_ACTIVE))
    if fulfillment:
        hold_stmt = hold_stmt.where(SalesOrder.fulfillment == fulfillment)
    if shop_id:
        hold_stmt = hold_stmt.where(SalesOrder.shop_id == shop_id)
    if ctx.shop_ids is not None:
        hold_stmt = hold_stmt.where(SalesOrder.shop_id.in_(ctx.shop_ids))
    counts["on_hold"] = ctx.db.execute(hold_stmt).scalar_one()
    return counts


ORDER_EXPORT_COLUMNS = [
    ("shop_name", "店铺"), ("platform_order_id", "平台订单号"), ("order_no", "系统单号"), ("fulfillment", "配送方式"),
    ("status", "状态"), ("purchase_at", "下单时间"), ("local_date", "站点日期"), ("i_msku", "MSKU"), ("i_sku", "SKU"),
    ("i_quantity", "数量"), ("currency", "币种"), ("i_item_amount", "商品金额"), ("i_shipping_amount", "运费收入"),
    ("i_discount_amount", "折扣"), ("i_commission_fee", "佣金"), ("i_fulfillment_fee", "配送费"),
    ("i_cost_purchase", "采购成本"), ("i_cost_freight", "头程成本"), ("buyer_name", "买家"), ("ship_country", "国家"),
    ("tracking_no", "运单号"),
]


@router.get("/orders/export", summary="导出订单（按订单行）")
def export_orders(
    keyword: str | None = None,
    shop_id: int | None = None,
    status: str | None = None,
    fulfillment: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    ctx: Ctx = Depends(perm("order:view")),
):
    stmt = _order_query(ctx, keyword=keyword, shop_id=shop_id, status=status, fulfillment=fulfillment,
                        date_from=date_from, date_to=date_to).limit(50000)
    rows = []
    for o in order_out_many(ctx, ctx.db.execute(stmt).scalars().all()):
        for i in o["items"]:
            rows.append({**o, **{f"i_{k}": v for k, v in i.items()}})
    return export_xlsx("订单.xlsx", ORDER_EXPORT_COLUMNS, rows)


IMPORT_COLUMNS = [
    ("shop_name", "店铺"), ("platform_order_id", "订单号"), ("purchase_at", "下单时间"), ("msku", "MSKU"),
    ("quantity", "数量"), ("unit_price", "单价"), ("shipping_amount", "运费"), ("currency", "币种"),
    ("fulfillment", "配送方式"), ("status", "状态"), ("buyer_name", "买家"), ("ship_name", "收件人"),
    ("ship_phone", "电话"), ("ship_country", "国家"), ("ship_state", "州/省"), ("ship_city", "城市"),
    ("ship_address1", "地址1"), ("ship_address2", "地址2"), ("ship_postcode", "邮编"),
]


@router.get("/orders/import-template", summary="订单导入模板")
def order_template(_: Ctx = Depends(perm("order:edit"))):
    return template_response("订单导入模板.xlsx", IMPORT_COLUMNS, {
        "shop_name": "店铺名", "platform_order_id": "113-0000000-0000000", "purchase_at": "2026-01-01 10:00:00",
        "msku": "MSKU-1", "quantity": 1, "unit_price": 19.99, "currency": "USD", "fulfillment": "FBM", "status": "unshipped",
    })


@router.post("/orders/import", response_model=ImportResult, summary="导入订单（多行同订单号自动合并）")
def import_orders(file: UploadFile = File(...), ctx: Ctx = Depends(perm("order:edit"))):
    rows = read_upload(file, IMPORT_COLUMNS)
    shops = {s.name: s for s in ctx.db.execute(select(Shop)).scalars().all()}
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(str(r.get("shop_name") or ""), str(r.get("platform_order_id") or ""))].append(r)
    result = ImportResult()
    for (shop_name, pid), lines in groups.items():
        sp = ctx.db.begin_nested()
        try:
            shop = shops.get(shop_name)
            if shop is None:
                raise BizError(f"店铺不存在: {shop_name}")
            ctx.require_shop(shop.id)
            if not pid:
                raise BizError("订单号不能为空")
            first = lines[0]
            pa = first.get("purchase_at")
            if isinstance(pa, str):
                pa = datetime.fromisoformat(pa)
            elif isinstance(pa, date) and not isinstance(pa, datetime):
                pa = datetime.combine(pa, datetime.min.time())
            items = []
            for ln in lines:
                qty = int(ln.get("quantity") or 1)
                items.append(OrderItemDTO(
                    msku=str(ln.get("msku") or ""), quantity=qty,
                    item_amount=Decimal(str(ln.get("unit_price") or 0)) * qty,
                    shipping_amount=Decimal(str(ln.get("shipping_amount") or 0)),
                ))
            dto = OrderDTO(
                platform_order_id=pid, fulfillment=str(first.get("fulfillment") or "FBM").upper(),
                status=str(first.get("status") or "unshipped"), purchase_at=pa or utcnow(),
                currency=str(first.get("currency") or shop.currency),
                **{k: (str(first[k]) if first.get(k) is not None else None) for k in (
                    "buyer_name", "ship_name", "ship_phone", "ship_country", "ship_state", "ship_city",
                    "ship_address1", "ship_address2", "ship_postcode")},
                items=items,
            )
            _, created = service.upsert_order(ctx, shop, dto)
            sp.commit()
            if created:
                result.created += 1
            else:
                result.updated += 1
        except Exception as exc:  # noqa: BLE001
            sp.rollback()
            result.skipped += 1
            result.errors.append(f"订单 {pid}: {exc.message if isinstance(exc, BizError) else exc}")
    audit(ctx, "import", "sales_order", None, f"导入订单：新增 {result.created}，更新 {result.updated}，失败 {result.skipped}")
    ctx.db.commit()
    return result


@router.get("/orders/{order_id}", response_model=OrderOut, summary="订单详情")
def get_order(order_id: int, ctx: Ctx = Depends(perm("order:view"))):
    order = get_or_404(ctx.db, SalesOrder, order_id, "订单")
    ctx.require_shop(order.shop_id)
    return order_out_many(ctx, [order])[0]


@router.post("/orders", response_model=OrderOut, summary="手工创建订单")
def create_order(body: OrderIn, ctx: Ctx = Depends(perm("order:edit"))):
    return order_out_many(ctx, [service.create_manual_order(ctx, body.model_dump())])[0]


@router.put("/orders/{order_id}", response_model=OrderOut, summary="修改订单（地址/仓库/物流/备注）")
def update_order(order_id: int, body: OrderUpdate, ctx: Ctx = Depends(perm("order:edit"))):
    order = get_or_404(ctx.db, SalesOrder, order_id, "订单")
    ctx.require_shop(order.shop_id)
    data = body.model_dump(exclude_unset=True)
    if ("warehouse_id" in data or "logistics_channel_id" in data) and order.status == "to_ship":
        raise BizError("已审核订单请先反审核再修改仓库/物流")
    if order.status in ("shipped", "delivered", "cancelled") and set(data) - {"remark", "tags"}:
        raise BizError("已发货/已取消订单只能修改备注")
    for k, v in data.items():
        setattr(order, k, v)
    audit(ctx, "update", "sales_order", order.id, f"修改订单 {order.platform_order_id}")
    ctx.db.commit()
    return order_out_many(ctx, [order])[0]


@router.post("/orders/audit", response_model=BatchResult, summary="批量审核（分配仓库、锁定库存）")
def audit_orders(body: AuditIn, ctx: Ctx = Depends(perm("order:audit"))):
    return service.batch(ctx, body.order_ids,
                         lambda o: service.audit_order(ctx, o, body.warehouse_id, body.logistics_channel_id), "审核")


@router.post("/orders/revert-audit", response_model=BatchResult, summary="批量反审核（释放库存）")
def revert_audit(body: CancelIn, ctx: Ctx = Depends(perm("order:audit"))):
    return service.batch(ctx, body.order_ids, lambda o: service.revert_audit(ctx, o), "反审核")


def _push_tracking(ctx: Ctx, order_ids: list[int]) -> None:
    from app.modules.integration.service import push_tracking

    for oid in order_ids:
        order = ctx.db.get(SalesOrder, oid)
        if order is not None and order.fulfillment == "FBM":
            push_tracking(ctx, order)
    ctx.db.commit()


@router.post("/orders/{order_id}/ship", response_model=OrderOut, summary="发货（扣减库存、核算成本，回传运单号）")
def ship(order_id: int, body: ShipIn, ctx: Ctx = Depends(perm("order:ship"))):
    res = service.batch(ctx, [order_id], lambda o: service.ship_order(ctx, o, body.model_dump()), "发货")
    if res["failed"]:
        raise BizError(res["failed"][0]["message"])
    _push_tracking(ctx, res["success"])
    return order_out_many(ctx, [get_or_404(ctx.db, SalesOrder, order_id, "订单")])[0]


@router.post("/orders/ship", response_model=BatchResult, summary="批量发货（可逐单填写运单号）")
def batch_ship(body: BatchShipIn, ctx: Ctx = Depends(perm("order:ship"))):
    data = {x.order_id: x.model_dump() for x in body.orders}
    res = service.batch(ctx, list(data), lambda o: service.ship_order(ctx, o, data[o.id]), "发货")
    _push_tracking(ctx, res["success"])
    return res


@router.post("/orders/cancel", response_model=BatchResult, summary="批量取消")
def cancel_orders(body: CancelIn, ctx: Ctx = Depends(perm("order:cancel"))):
    return service.batch(ctx, body.order_ids, lambda o: service.cancel(ctx, o, body.reason), "取消")


@router.post("/orders/hold", response_model=BatchResult, summary="挂起/取消挂起")
def hold_orders(body: HoldIn, ctx: Ctx = Depends(perm("order:edit"))):
    def _fn(o: SalesOrder):
        if o.status not in service.FBM_ACTIVE:
            raise BizError("仅未发货订单可挂起")
        o.is_on_hold = body.hold
        o.hold_reason = body.reason if body.hold else None

    return service.batch(ctx, body.order_ids, _fn, "挂起" if body.hold else "取消挂起")


@router.post("/orders/{order_id}/deliver", response_model=OrderOut, summary="标记已签收")
def deliver(order_id: int, ctx: Ctx = Depends(perm("order:ship"))):
    order = get_or_404(ctx.db, SalesOrder, order_id, "订单")
    ctx.require_shop(order.shop_id)
    if order.status != "shipped":
        raise BizError("仅已发货订单可标记签收")
    order.status = "delivered"
    order.delivered_at = utcnow()
    ctx.db.commit()
    return order_out_many(ctx, [order])[0]


@router.post("/orders/resettle-cost", response_model=Msg, summary="重新核算未核算成本的 FBA 订单（配对后使用）")
def resettle(shop_id: int | None = None, ctx: Ctx = Depends(perm("order:edit"))):
    n = service.resettle_unpaired(ctx, shop_id)
    return Msg(message=f"已重新核算 {n} 个订单")


# ================================================================ 退货
def return_out_many(ctx: Ctx, rets) -> list[dict]:
    rets = list(rets)
    db = ctx.db
    shops = _names(db, Shop, [r.shop_id for r in rets])
    orders = {o.id: o for o in db.execute(select(SalesOrder).where(SalesOrder.id.in_({r.order_id for r in rets if r.order_id}))).scalars().all()} if rets else {}
    pids = {ln.product_id for r in rets for ln in r.lines if ln.product_id}
    skus = dict(db.execute(select(Product.id, Product.sku).where(Product.id.in_(pids))).all()) if pids else {}
    show_cost = ctx.can("product:cost:view")
    out = []
    for r in rets:
        d = {c.key: getattr(r, c.key) for c in ReturnOrder.__table__.columns}
        o = orders.get(r.order_id)
        d.update(shop_name=shops.get(r.shop_id), order_no=o.order_no if o else None,
                 platform_order_id=o.platform_order_id if o else None)
        if not show_cost:
            d["restock_cost"] = None
        d["lines"] = [{"id": ln.id, "order_item_id": ln.order_item_id, "product_id": ln.product_id,
                       "sku": skus.get(ln.product_id), "msku": ln.msku, "qty": ln.qty, "refund_amount": ln.refund_amount,
                       "qty_good": ln.qty_good, "qty_defective": ln.qty_defective} for ln in r.lines]
        out.append(d)
    return out


@router.get("/returns", response_model=Page[ReturnOut], summary="退货单列表")
def list_returns(
    keyword: str | None = None,
    shop_id: int | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("return:view")),
):
    stmt = select(ReturnOrder).order_by(ReturnOrder.id.desc())
    if keyword:
        kw = f"%{keyword.strip()}%"
        sub = select(SalesOrder.id).where(SalesOrder.platform_order_id.ilike(kw))
        stmt = stmt.where(ReturnOrder.return_no.ilike(kw) | ReturnOrder.platform_return_id.ilike(kw) | ReturnOrder.order_id.in_(sub))
    if shop_id:
        stmt = stmt.where(ReturnOrder.shop_id == shop_id)
    if status:
        stmt = stmt.where(ReturnOrder.status == status)
    if date_from:
        stmt = stmt.where(ReturnOrder.return_date >= date_from)
    if date_to:
        stmt = stmt.where(ReturnOrder.return_date <= date_to)
    if ctx.shop_ids is not None:
        stmt = stmt.where(ReturnOrder.shop_id.in_(ctx.shop_ids))
    page = paginate(ctx.db, stmt, params)
    page["items"] = return_out_many(ctx, page["items"])
    return page


@router.post("/returns", response_model=ReturnOut, summary="新建退货单")
def create_return(body: ReturnIn, ctx: Ctx = Depends(perm("return:edit"))):
    return return_out_many(ctx, [service.create_return(ctx, body.model_dump())])[0]


@router.post("/returns/{ret_id}/complete", response_model=ReturnOut, summary="完成退货（入库）")
def complete_return(ret_id: int, body: ReturnCompleteIn, ctx: Ctx = Depends(perm("return:edit"))):
    return return_out_many(ctx, [service.complete_return(ctx, ret_id, body.warehouse_id, body.lines)])[0]


@router.post("/returns/{ret_id}/cancel", response_model=ReturnOut, summary="取消退货单")
def cancel_return(ret_id: int, ctx: Ctx = Depends(perm("return:edit"))):
    return return_out_many(ctx, [service.cancel_return(ctx, ret_id)])[0]
