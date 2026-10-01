from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.common.audit import audit
from app.common.crud import get_or_404, keyword_filter
from app.common.enums import PlanStatus, PurchaseStatus
from app.common.excel import export_xlsx
from app.common.pagination import PageParams, page_params, paginate
from app.common.schemas import IdsIn, Msg, Page
from app.core.deps import Ctx, get_ctx, perm
from app.core.errors import BizError
from app.core.types import q2
from app.modules.product.models import Product
from app.modules.purchase import service
from app.modules.purchase.models import (
    PaymentRequest,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchasePlan,
    PurchaseReceipt,
    PurchaseReturn,
)
from app.modules.purchase.schemas import (
    ApproveIn,
    MarkOrderedIn,
    PayableRow,
    PayIn,
    PaymentRequestIn,
    PaymentRequestOut,
    PlanIn,
    PlanOut,
    PlanToOrderIn,
    PlanUpdate,
    POIn,
    POOut,
    POUpdate,
    ReceiptOut,
    ReceiveIn,
    RejectIn,
    ReturnIn,
    ReturnOut,
)
from app.modules.supplier.models import Supplier
from app.modules.warehouse.models import Warehouse

router = APIRouter(tags=["采购管理"])


def _names(db, model, ids, attr="name") -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.execute(select(model.id, getattr(model, attr)).where(model.id.in_(ids))).all())


def _products(db, ids) -> dict[int, Product]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {p.id: p for p in db.execute(select(Product).where(Product.id.in_(ids))).scalars().all()}


# ================================================================ 采购计划
def plan_out(ctx: Ctx, plans) -> list[dict]:
    plans = list(plans)
    db = ctx.db
    products = _products(db, [p.product_id for p in plans])
    suppliers = _names(db, Supplier, [p.supplier_id for p in plans])
    whs = _names(db, Warehouse, [p.warehouse_id for p in plans])
    pos = _names(db, PurchaseOrder, [p.purchase_order_id for p in plans], "po_no")
    out = []
    for p in plans:
        d = {c.key: getattr(p, c.key) for c in PurchasePlan.__table__.columns}
        prod = products.get(p.product_id)
        d.update(
            sku=prod.sku if prod else None, product_name=prod.name if prod else None,
            image_url=prod.image_url if prod else None, supplier_name=suppliers.get(p.supplier_id),
            warehouse_name=whs.get(p.warehouse_id), po_no=pos.get(p.purchase_order_id),
        )
        out.append(d)
    return out


@router.get("/purchase-plans", response_model=Page[PlanOut], summary="采购计划列表")
def list_plans(
    keyword: str | None = None,
    status: str | None = None,
    supplier_id: int | None = None,
    source: str | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("purchase:plan:view")),
):
    stmt = select(PurchasePlan).join(Product, Product.id == PurchasePlan.product_id).order_by(PurchasePlan.id.desc())
    stmt = keyword_filter(stmt, keyword, [PurchasePlan.plan_no, Product.sku, Product.name])
    if status:
        stmt = stmt.where(PurchasePlan.status == status)
    if supplier_id:
        stmt = stmt.where(PurchasePlan.supplier_id == supplier_id)
    if source:
        stmt = stmt.where(PurchasePlan.source == source)
    page = paginate(ctx.db, stmt, params)
    page["items"] = plan_out(ctx, page["items"])
    return page


@router.post("/purchase-plans", response_model=PlanOut, summary="新建采购计划")
def create_plan(body: PlanIn, ctx: Ctx = Depends(perm("purchase:plan:edit"))):
    plan = service.create_plan(ctx, body.model_dump())
    ctx.db.commit()
    return plan_out(ctx, [plan])[0]


@router.put("/purchase-plans/{plan_id}", response_model=PlanOut, summary="修改采购计划")
def update_plan(plan_id: int, body: PlanUpdate, ctx: Ctx = Depends(perm("purchase:plan:edit"))):
    plan = get_or_404(ctx.db, PurchasePlan, plan_id, "采购计划")
    if plan.status != PlanStatus.PENDING:
        raise BizError("仅待处理的计划可修改")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(plan, k, v)
    ctx.db.commit()
    return plan_out(ctx, [plan])[0]


@router.post("/purchase-plans/cancel", response_model=Msg, summary="批量作废采购计划")
def cancel_plans(body: IdsIn, ctx: Ctx = Depends(perm("purchase:plan:edit"))):
    plans = ctx.db.execute(select(PurchasePlan).where(PurchasePlan.id.in_(body.ids))).scalars().all()
    n = 0
    for p in plans:
        if p.status == PlanStatus.PENDING:
            p.status = PlanStatus.CANCELLED
            n += 1
    audit(ctx, "cancel", "purchase_plan", None, f"作废采购计划 {n} 条")
    ctx.db.commit()
    return Msg(message=f"已作废 {n} 条")


@router.post("/purchase-plans/to-orders", response_model=list[POOut], summary="采购计划生成采购单（按供应商合并）")
def plans_to_orders(body: PlanToOrderIn, ctx: Ctx = Depends(perm("purchase:order:edit"))):
    orders = service.plans_to_orders(ctx, body.plan_ids, body.warehouse_id)
    return [po_out(ctx, o) for o in orders]


# ================================================================ 采购单
def po_out(ctx: Ctx, po: PurchaseOrder) -> dict:
    return po_out_many(ctx, [po])[0]


def po_out_many(ctx: Ctx, pos) -> list[dict]:
    pos = list(pos)
    db = ctx.db
    suppliers = _names(db, Supplier, [p.supplier_id for p in pos])
    whs = _names(db, Warehouse, [p.warehouse_id for p in pos])
    products = _products(db, [ln.product_id for p in pos for ln in p.lines])
    out = []
    for po in pos:
        d = {c.key: getattr(po, c.key) for c in PurchaseOrder.__table__.columns}
        d["supplier_name"] = suppliers.get(po.supplier_id)
        d["warehouse_name"] = whs.get(po.warehouse_id)
        d["total_qty"] = sum(ln.qty for ln in po.lines)
        d["received_qty"] = sum(ln.qty_received for ln in po.lines)
        lines = []
        for ln in po.lines:
            prod = products.get(ln.product_id)
            ld = {c.key: getattr(ln, c.key) for c in PurchaseOrderLine.__table__.columns}
            ld.update(sku=prod.sku if prod else None, product_name=prod.name if prod else None,
                      image_url=prod.image_url if prod else None, qty_pending=ln.qty_pending)
            lines.append(ld)
        d["lines"] = lines
        out.append(d)
    return out


def _po_query(ctx: Ctx, keyword, status, supplier_id, warehouse_id, payment_status, date_from, date_to, product_id):
    stmt = select(PurchaseOrder).order_by(PurchaseOrder.id.desc())
    if keyword:
        kw = f"%{keyword.strip()}%"
        sub = (
            select(PurchaseOrderLine.order_id)
            .join(Product, Product.id == PurchaseOrderLine.product_id)
            .where(Product.sku.ilike(kw) | Product.name.ilike(kw))
        )
        stmt = stmt.where(
            PurchaseOrder.po_no.ilike(kw) | PurchaseOrder.supplier_order_no.ilike(kw)
            | PurchaseOrder.tracking_no.ilike(kw) | PurchaseOrder.id.in_(sub)
        )
    if status:
        stmt = stmt.where(PurchaseOrder.status.in_(status.split(",")))
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    if warehouse_id:
        stmt = stmt.where(PurchaseOrder.warehouse_id == warehouse_id)
    if payment_status:
        stmt = stmt.where(PurchaseOrder.payment_status == payment_status)
    if date_from:
        stmt = stmt.where(PurchaseOrder.created_at >= date_from)
    if date_to:
        stmt = stmt.where(func.date(PurchaseOrder.created_at) <= date_to)
    if product_id:
        stmt = stmt.where(PurchaseOrder.id.in_(select(PurchaseOrderLine.order_id).where(PurchaseOrderLine.product_id == product_id)))
    return stmt


@router.get("/purchase-orders", response_model=Page[POOut], summary="采购单列表")
def list_orders(
    keyword: str | None = None,
    status: str | None = None,
    supplier_id: int | None = None,
    warehouse_id: int | None = None,
    payment_status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    product_id: int | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("purchase:order:view")),
):
    stmt = _po_query(ctx, keyword, status, supplier_id, warehouse_id, payment_status, date_from, date_to, product_id)
    page = paginate(ctx.db, stmt, params)
    page["items"] = po_out_many(ctx, page["items"])
    return page


@router.get("/purchase-orders/status-counts", summary="各状态采购单数量")
def po_status_counts(ctx: Ctx = Depends(perm("purchase:order:view"))):
    rows = ctx.db.execute(select(PurchaseOrder.status, func.count()).group_by(PurchaseOrder.status)).all()
    return {s: c for s, c in rows}


@router.get("/purchase-orders/export", summary="导出采购单明细")
def export_orders(
    keyword: str | None = None,
    status: str | None = None,
    supplier_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    ctx: Ctx = Depends(perm("purchase:order:view")),
):
    pos = ctx.db.execute(_po_query(ctx, keyword, status, supplier_id, None, None, date_from, date_to, None)).scalars().all()
    rows = []
    for d in po_out_many(ctx, pos):
        for ln in d["lines"]:
            rows.append({**d, **{f"line_{k}": v for k, v in ln.items()}})
    cols = [
        ("po_no", "采购单号"), ("supplier_name", "供应商"), ("warehouse_name", "收货仓"), ("status", "状态"),
        ("currency", "币种"), ("line_sku", "SKU"), ("line_product_name", "品名"), ("line_qty", "采购数量"),
        ("line_unit_price", "单价"), ("line_amount", "金额"), ("line_qty_received", "已到货"),
        ("line_qty_pending", "未到货"), ("total_amount", "单据总额"), ("paid_amount", "已付款"),
        ("expected_date", "预计到货"), ("created_at", "创建时间"),
    ]
    return export_xlsx("采购单.xlsx", cols, rows)


@router.get("/purchase-orders/{po_id}", response_model=POOut, summary="采购单详情")
def get_order(po_id: int, ctx: Ctx = Depends(perm("purchase:order:view"))):
    return po_out(ctx, get_or_404(ctx.db, PurchaseOrder, po_id, "采购单"))


@router.post("/purchase-orders", response_model=POOut, summary="新建采购单")
def create_order(body: POIn, ctx: Ctx = Depends(perm("purchase:order:edit"))):
    return po_out(ctx, service.create_order(ctx, body.model_dump()))


@router.put("/purchase-orders/{po_id}", response_model=POOut, summary="修改采购单")
def update_order(po_id: int, body: POUpdate, ctx: Ctx = Depends(perm("purchase:order:edit"))):
    return po_out(ctx, service.update_order(ctx, po_id, body.model_dump(exclude_unset=True)))


@router.post("/purchase-orders/{po_id}/submit", response_model=POOut, summary="提交审批")
def submit_order(po_id: int, ctx: Ctx = Depends(perm("purchase:order:edit"))):
    return po_out(ctx, service.submit_order(ctx, po_id))


@router.post("/purchase-orders/{po_id}/approve", response_model=POOut, summary="审批通过（多级审批时流转下一级）")
def approve_order(po_id: int, body: ApproveIn | None = None, ctx: Ctx = Depends(get_ctx)):
    # 权限：配置了审批流程时由流程节点决定，否则需要 purchase:order:approve
    return po_out(ctx, service.approve_order(ctx, po_id, body.comment if body else None))


@router.post("/purchase-orders/{po_id}/reject", response_model=POOut, summary="驳回")
def reject_order(po_id: int, body: RejectIn, ctx: Ctx = Depends(get_ctx)):
    return po_out(ctx, service.reject_order(ctx, po_id, body.reason))


@router.post("/purchase-orders/{po_id}/ordered", response_model=POOut, summary="确认已下单")
def mark_ordered(po_id: int, body: MarkOrderedIn, ctx: Ctx = Depends(perm("purchase:order:edit"))):
    return po_out(ctx, service.mark_ordered(ctx, po_id, body.model_dump()))


@router.post("/purchase-orders/{po_id}/receive", response_model=ReceiptOut, summary="到货质检入库")
def receive(po_id: int, body: ReceiveIn, ctx: Ctx = Depends(perm("purchase:receive"))):
    receipt = service.receive(ctx, po_id, body.model_dump())
    return receipt_out(ctx, [receipt])[0]


@router.post("/purchase-orders/{po_id}/close", response_model=POOut, summary="结单")
def close_order(po_id: int, ctx: Ctx = Depends(perm("purchase:order:edit"))):
    return po_out(ctx, service.close_order(ctx, po_id))


@router.post("/purchase-orders/{po_id}/cancel", response_model=POOut, summary="作废")
def cancel_order(po_id: int, ctx: Ctx = Depends(perm("purchase:order:edit"))):
    return po_out(ctx, service.cancel_order(ctx, po_id))


@router.delete("/purchase-orders/{po_id}", response_model=Msg, summary="删除采购单")
def delete_order(po_id: int, ctx: Ctx = Depends(perm("purchase:order:edit"))):
    service.delete_order(ctx, po_id)
    return Msg(message="已删除")


# ================================================================ 入库单
def receipt_out(ctx: Ctx, receipts) -> list[dict]:
    receipts = list(receipts)
    db = ctx.db
    suppliers = _names(db, Supplier, [r.supplier_id for r in receipts])
    whs = _names(db, Warehouse, [r.warehouse_id for r in receipts])
    pos = _names(db, PurchaseOrder, [r.order_id for r in receipts], "po_no")
    products = _products(db, [ln.product_id for r in receipts for ln in r.lines])
    show_cost = ctx.can("product:cost:view")
    out = []
    for r in receipts:
        d = {c.key: getattr(r, c.key) for c in PurchaseReceipt.__table__.columns}
        d.update(supplier_name=suppliers.get(r.supplier_id), warehouse_name=whs.get(r.warehouse_id), po_no=pos.get(r.order_id))
        d["lines"] = [
            {
                "id": ln.id, "order_line_id": ln.order_line_id, "product_id": ln.product_id,
                "sku": products[ln.product_id].sku if ln.product_id in products else None,
                "product_name": products[ln.product_id].name if ln.product_id in products else None,
                "qty_good": ln.qty_good, "qty_defective": ln.qty_defective,
                "unit_purchase_cost": ln.unit_purchase_cost if show_cost else None,
                "unit_freight_cost": ln.unit_freight_cost if show_cost else None, "batch_no": ln.batch_no,
            }
            for ln in r.lines
        ]
        out.append(d)
    return out


@router.get("/purchase-receipts", response_model=Page[ReceiptOut], summary="采购入库单列表")
def list_receipts(
    keyword: str | None = None,
    order_id: int | None = None,
    supplier_id: int | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("purchase:order:view")),
):
    stmt = select(PurchaseReceipt).order_by(PurchaseReceipt.id.desc())
    stmt = keyword_filter(stmt, keyword, [PurchaseReceipt.receipt_no, PurchaseReceipt.tracking_no])
    if order_id:
        stmt = stmt.where(PurchaseReceipt.order_id == order_id)
    if supplier_id:
        stmt = stmt.where(PurchaseReceipt.supplier_id == supplier_id)
    page = paginate(ctx.db, stmt, params)
    page["items"] = receipt_out(ctx, page["items"])
    return page


# ================================================================ 采购退货
def return_out(ctx: Ctx, rets) -> list[dict]:
    rets = list(rets)
    db = ctx.db
    suppliers = _names(db, Supplier, [r.supplier_id for r in rets])
    pos = _names(db, PurchaseOrder, [r.order_id for r in rets], "po_no")
    products = _products(db, [ln.product_id for r in rets for ln in r.lines])
    out = []
    for r in rets:
        d = {c.key: getattr(r, c.key) for c in PurchaseReturn.__table__.columns}
        d.update(supplier_name=suppliers.get(r.supplier_id), po_no=pos.get(r.order_id))
        d["lines"] = [
            {"id": ln.id, "order_line_id": ln.order_line_id, "product_id": ln.product_id,
             "sku": products[ln.product_id].sku if ln.product_id in products else None,
             "product_name": products[ln.product_id].name if ln.product_id in products else None,
             "qty": ln.qty, "unit_price": ln.unit_price}
            for ln in r.lines
        ]
        out.append(d)
    return out


@router.get("/purchase-returns", response_model=Page[ReturnOut], summary="采购退货列表")
def list_returns(
    keyword: str | None = None,
    supplier_id: int | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("purchase:order:view")),
):
    stmt = select(PurchaseReturn).order_by(PurchaseReturn.id.desc())
    stmt = keyword_filter(stmt, keyword, [PurchaseReturn.return_no, PurchaseReturn.reason])
    if supplier_id:
        stmt = stmt.where(PurchaseReturn.supplier_id == supplier_id)
    page = paginate(ctx.db, stmt, params)
    page["items"] = return_out(ctx, page["items"])
    return page


@router.post("/purchase-returns", response_model=ReturnOut, summary="新建采购退货（直接出库）")
def create_return(body: ReturnIn, ctx: Ctx = Depends(perm("purchase:return"))):
    return return_out(ctx, [service.create_return(ctx, body.model_dump())])[0]


# ================================================================ 请款付款
def payment_out(ctx: Ctx, reqs) -> list[dict]:
    reqs = list(reqs)
    db = ctx.db
    suppliers = _names(db, Supplier, [r.supplier_id for r in reqs])
    pos = _names(db, PurchaseOrder, [ln.purchase_order_id for r in reqs for ln in r.lines], "po_no")
    out = []
    for r in reqs:
        d = {c.key: getattr(r, c.key) for c in PaymentRequest.__table__.columns}
        d["supplier_name"] = suppliers.get(r.supplier_id)
        d["lines"] = [{"id": ln.id, "purchase_order_id": ln.purchase_order_id, "po_no": pos.get(ln.purchase_order_id),
                       "amount": ln.amount} for ln in r.lines]
        out.append(d)
    return out


@router.get("/payment-requests", response_model=Page[PaymentRequestOut], summary="请款单列表")
def list_payments(
    keyword: str | None = None,
    status: str | None = None,
    supplier_id: int | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("purchase:payment:view")),
):
    stmt = select(PaymentRequest).order_by(PaymentRequest.id.desc())
    stmt = keyword_filter(stmt, keyword, [PaymentRequest.request_no, PaymentRequest.transaction_no, PaymentRequest.remark])
    if status:
        stmt = stmt.where(PaymentRequest.status.in_(status.split(",")))
    if supplier_id:
        stmt = stmt.where(PaymentRequest.supplier_id == supplier_id)
    page = paginate(ctx.db, stmt, params)
    page["items"] = payment_out(ctx, page["items"])
    return page


@router.post("/payment-requests", response_model=PaymentRequestOut, summary="发起请款")
def create_payment(body: PaymentRequestIn, ctx: Ctx = Depends(perm("purchase:payment:edit"))):
    return payment_out(ctx, [service.create_payment_request(ctx, body.model_dump())])[0]


@router.post("/payment-requests/{req_id}/approve", response_model=PaymentRequestOut, summary="审批请款（多级审批时流转下一级）")
def approve_payment(req_id: int, body: ApproveIn | None = None, ctx: Ctx = Depends(get_ctx)):
    return payment_out(ctx, [service.approve_payment(ctx, req_id, body.comment if body else None)])[0]


@router.post("/payment-requests/{req_id}/reject", response_model=PaymentRequestOut, summary="驳回请款")
def reject_payment(req_id: int, body: RejectIn, ctx: Ctx = Depends(get_ctx)):
    return payment_out(ctx, [service.reject_payment(ctx, req_id, body.reason)])[0]


@router.post("/payment-requests/{req_id}/pay", response_model=PaymentRequestOut, summary="确认付款")
def pay(req_id: int, body: PayIn, ctx: Ctx = Depends(perm("purchase:payment:approve"))):
    return payment_out(ctx, [service.pay(ctx, req_id, body.model_dump())])[0]


@router.post("/payment-requests/{req_id}/cancel", response_model=PaymentRequestOut, summary="取消请款")
def cancel_payment(req_id: int, ctx: Ctx = Depends(perm("purchase:payment:edit"))):
    return payment_out(ctx, [service.cancel_payment(ctx, req_id)])[0]


@router.get("/payables", response_model=list[PayableRow], summary="应付账款（按供应商汇总）")
def payables(supplier_id: int | None = None, ctx: Ctx = Depends(perm("purchase:payment:view"))):
    active = PurchaseOrder.status.notin_([PurchaseStatus.DRAFT, PurchaseStatus.CANCELLED, PurchaseStatus.REJECTED,
                                          PurchaseStatus.PENDING_APPROVAL])
    stmt = select(PurchaseOrder).where(active)
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    pos = ctx.db.execute(stmt).scalars().all()
    suppliers = _names(ctx.db, Supplier, [p.supplier_id for p in pos])
    agg: dict[tuple[int, str], dict] = {}
    for po in pos:
        key = (po.supplier_id, po.currency)
        row = agg.setdefault(key, {
            "supplier_id": po.supplier_id, "supplier_name": suppliers.get(po.supplier_id), "currency": po.currency,
            "order_count": 0, "total_amount": Decimal(0), "received_value": Decimal(0), "returned_amount": Decimal(0),
            "paid_amount": Decimal(0), "requested_amount": Decimal(0),
        })
        row["order_count"] += 1
        row["total_amount"] += Decimal(po.total_amount)
        goods = Decimal(po.goods_amount or 0)
        recv_goods = sum((Decimal(ln.unit_price) * ln.qty_received for ln in po.lines), Decimal(0))
        ratio = recv_goods / goods if goods else Decimal(0)
        row["received_value"] += q2(Decimal(po.total_amount) * ratio)
        row["returned_amount"] += Decimal(po.returned_amount or 0)
        row["paid_amount"] += Decimal(po.paid_amount or 0)
        row["requested_amount"] += Decimal(po.requested_amount or 0)
    result = []
    for row in agg.values():
        row["unpaid_amount"] = q2(row["total_amount"] - row["returned_amount"] - row["paid_amount"])
        # 已到货部分对应的应付（不含预付）
        row["payable_now"] = q2(max(Decimal(0), row["received_value"] - row["returned_amount"] - row["paid_amount"]))
        result.append(row)
    result.sort(key=lambda r: r["unpaid_amount"], reverse=True)
    return result
