"""采购业务：计划 → 采购单（审批） → 下单 → 到货质检入库 → 退货 → 请款付款。"""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.common.audit import audit
from app.common.crud import get_or_404
from app.common.currency import get_rate
from app.common.enums import (
    LedgerType,
    PaymentRequestStatus,
    PaymentStatus,
    PlanStatus,
    ProductType,
    PurchaseStatus,
    StockType,
)
from app.common.numbering import next_doc_no
from app.core.deps import Ctx
from app.core.errors import BizError
from app.core.types import q2, q4, utcnow
from app.modules.approval import service as approval
from app.modules.product.models import Product, ProductSupplier
from app.modules.purchase.models import (
    PaymentRequest,
    PaymentRequestLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchasePlan,
    PurchaseReceipt,
    PurchaseReceiptLine,
    PurchaseReturn,
    PurchaseReturnLine,
)
from app.modules.supplier.models import Supplier
from app.modules.system.service import get_setting
from app.modules.warehouse.inventory import InventoryService, Ref
from app.modules.warehouse.models import Warehouse

EDITABLE = (PurchaseStatus.DRAFT, PurchaseStatus.REJECTED)
RECEIVABLE = (PurchaseStatus.APPROVED, PurchaseStatus.ORDERED, PurchaseStatus.PARTIAL)


def default_warehouse_id(ctx: Ctx) -> int:
    wh = ctx.db.execute(
        select(Warehouse).where(Warehouse.warehouse_type == "local", Warehouse.status == "active")
        .order_by(Warehouse.is_default.desc(), Warehouse.id)
    ).scalars().first()
    if wh is None:
        raise BizError("请先创建本地仓库")
    return wh.id


def quote_price(ctx: Ctx, product: Product, supplier_id: int | None, currency: str) -> Decimal:
    """取供应商报价（同币种），否则按参考成本折算。"""
    if supplier_id:
        q = ctx.db.execute(
            select(ProductSupplier).where(ProductSupplier.product_id == product.id, ProductSupplier.supplier_id == supplier_id)
        ).scalar_one_or_none()
        if q is not None and q.currency == currency:
            return Decimal(q.price)
    rate = get_rate(ctx.db, currency)
    return q4(Decimal(product.purchase_cost or 0) / rate) if rate else Decimal(0)


# ================================================================ 采购计划
def create_plan(ctx: Ctx, data: dict) -> PurchasePlan:
    product = get_or_404(ctx.db, Product, data["product_id"], "产品")
    if product.product_type == ProductType.BUNDLE:
        raise BizError("组合产品不能直接采购，请采购其子产品")
    if not data.get("supplier_id"):
        data["supplier_id"] = product.default_supplier_id
    if not data.get("purchaser_id"):
        data["purchaser_id"] = product.purchaser_id
    plan = PurchasePlan(plan_no=next_doc_no(ctx.db, "PP"), status=PlanStatus.PENDING, **data)
    ctx.db.add(plan)
    ctx.db.flush()
    audit(ctx, "create", "purchase_plan", plan.id, f"新建采购计划 {plan.plan_no} {product.sku}×{plan.qty}")
    return plan


def plans_to_orders(ctx: Ctx, plan_ids: list[int], warehouse_id: int | None) -> list[PurchaseOrder]:
    """采购计划按「供应商 + 收货仓」合并生成采购单。"""
    plans = ctx.db.execute(
        select(PurchasePlan).where(PurchasePlan.id.in_(plan_ids)).with_for_update(of=PurchasePlan)
    ).scalars().all()
    if len(plans) != len(set(plan_ids)):
        raise BizError("部分采购计划不存在")
    groups: dict[tuple[int, int], list[PurchasePlan]] = defaultdict(list)
    for p in plans:
        if p.status != PlanStatus.PENDING:
            raise BizError(f"计划 {p.plan_no} 状态不是待处理")
        if not p.supplier_id:
            raise BizError(f"计划 {p.plan_no} 未指定供应商")
        wid = warehouse_id or p.warehouse_id or default_warehouse_id(ctx)
        groups[(p.supplier_id, wid)].append(p)
    orders = []
    for (supplier_id, wid), items in groups.items():
        supplier = get_or_404(ctx.db, Supplier, supplier_id, "供应商")
        merged: dict[int, dict] = {}
        for p in items:
            ln = merged.setdefault(p.product_id, {"product_id": p.product_id, "qty": 0, "plan_id": p.id,
                                                   "expected_date": p.expected_date})
            ln["qty"] += p.qty
        po = _new_order(
            ctx,
            {"supplier_id": supplier.id, "warehouse_id": wid, "currency": supplier.currency,
             "purchaser_id": items[0].purchaser_id, "remark": "由采购计划生成：" + ",".join(p.plan_no for p in items)},
            list(merged.values()),
        )
        for p in items:
            p.status = PlanStatus.CONVERTED
            p.purchase_order_id = po.id
        orders.append(po)
    ctx.db.commit()
    return orders


# ================================================================ 采购单
def _build_lines(ctx: Ctx, po: PurchaseOrder, lines: list[dict]) -> None:
    ids = [ln["product_id"] for ln in lines]
    products = {p.id: p for p in ctx.db.execute(select(Product).where(Product.id.in_(ids))).scalars().all()}
    new_lines = []
    for ln in lines:
        product = products.get(ln["product_id"])
        if product is None:
            raise BizError(f"产品不存在（ID={ln['product_id']}）")
        if product.product_type == ProductType.BUNDLE:
            raise BizError(f"组合产品 {product.sku} 不能直接采购")
        price = ln.get("unit_price")
        if price is None:
            price = quote_price(ctx, product, po.supplier_id, po.currency)
        price = q4(price)
        new_lines.append(
            PurchaseOrderLine(
                product_id=product.id, qty=ln["qty"], unit_price=price, amount=q2(price * ln["qty"]),
                plan_id=ln.get("plan_id"), expected_date=ln.get("expected_date"), remark=ln.get("remark"),
            )
        )
    po.lines = new_lines
    _recalc(po)


def _recalc(po: PurchaseOrder) -> None:
    po.goods_amount = q2(sum((ln.amount for ln in po.lines), Decimal(0)))
    po.total_amount = q2(po.goods_amount + (po.shipping_fee or 0) + (po.other_fee or 0) - (po.discount or 0))
    if po.total_amount < 0:
        raise BizError("折扣不能大于订单金额")


def _new_order(ctx: Ctx, data: dict, lines: list[dict]) -> PurchaseOrder:
    supplier = get_or_404(ctx.db, Supplier, data["supplier_id"], "供应商")
    if supplier.status != "active":
        raise BizError(f"供应商 {supplier.name} 已停用")
    get_or_404(ctx.db, Warehouse, data["warehouse_id"], "仓库")
    currency = (data.get("currency") or supplier.currency or "CNY").upper()
    data["currency"] = currency
    data.setdefault("settlement_type", supplier.settlement_type)
    data.setdefault("purchaser_id", ctx.user_id)
    po = PurchaseOrder(
        po_no=next_doc_no(ctx.db, "PO"),
        status=PurchaseStatus.DRAFT,
        exchange_rate=get_rate(ctx.db, currency),
        **{k: v for k, v in data.items() if v is not None},
    )
    ctx.db.add(po)
    _build_lines(ctx, po, lines)
    ctx.db.flush()
    audit(ctx, "create", "purchase_order", po.id, f"新建采购单 {po.po_no}，金额 {po.total_amount} {po.currency}")
    return po


def create_order(ctx: Ctx, data: dict) -> PurchaseOrder:
    lines = data.pop("lines")
    po = _new_order(ctx, data, lines)
    ctx.db.commit()
    return po


def update_order(ctx: Ctx, po_id: int, data: dict) -> PurchaseOrder:
    po = get_or_404(ctx.db, PurchaseOrder, po_id, "采购单", for_update=True)
    if po.status not in EDITABLE:
        raise BizError("仅草稿或已驳回的采购单可修改")
    lines = data.pop("lines", None)
    if "currency" in data and data["currency"]:
        data["currency"] = data["currency"].upper()
        po.exchange_rate = get_rate(ctx.db, data["currency"])
    for k, v in data.items():
        setattr(po, k, v)
    if lines is not None:
        _build_lines(ctx, po, lines)
    else:
        _recalc(po)
    audit(ctx, "update", "purchase_order", po.id, f"修改采购单 {po.po_no}")
    ctx.db.commit()
    return po


def submit_order(ctx: Ctx, po_id: int) -> PurchaseOrder:
    po = get_or_404(ctx.db, PurchaseOrder, po_id, "采购单", for_update=True)
    if po.status not in EDITABLE:
        raise BizError("仅草稿或已驳回的采购单可提交")
    if not po.lines:
        raise BizError("采购单没有明细")
    po.submitted_at = utcnow()
    po.reject_reason = None
    if get_setting(ctx.db, "purchase.require_approval") or approval.requires_approval(ctx.db, "purchase_order", po.total_amount, po.currency):
        po.status = PurchaseStatus.PENDING_APPROVAL
        supplier = ctx.db.get(Supplier, po.supplier_id)
        inst = approval.start(ctx, "purchase_order", po.id, doc_no=po.po_no, amount=po.total_amount, currency=po.currency,
                              summary=f"{supplier.name if supplier else ''} {po.total_amount} {po.currency}",
                              link=f"/purchase/orders?id={po.id}")
        if inst is None:
            _notify_approvers(ctx, po)
    else:
        po.status = PurchaseStatus.APPROVED
        po.approved_at = utcnow()
        po.approved_by = ctx.user_id
    audit(ctx, "submit", "purchase_order", po.id, f"提交采购单 {po.po_no}")
    ctx.db.commit()
    return po


def _notify_approvers(ctx: Ctx, po: PurchaseOrder) -> None:
    from app.modules.system.models import Notification

    ctx.db.add(
        Notification(
            category="approval",
            title=f"采购单 {po.po_no} 待审批",
            content=f"金额 {po.total_amount} {po.currency}，提交人 {ctx.user.real_name or ctx.user.username}",
            link=f"/purchase/orders?id={po.id}",
        )
    )


def approve_order(ctx: Ctx, po_id: int, comment: str | None = None) -> PurchaseOrder:
    po = get_or_404(ctx.db, PurchaseOrder, po_id, "采购单", for_update=True)
    if po.status != PurchaseStatus.PENDING_APPROVAL:
        raise BizError("采购单不在待审批状态")
    res = approval.act(ctx, "purchase_order", po.id, True, comment)
    if res is None:
        ctx.require("purchase:order:approve")
    elif res == "pending":
        audit(ctx, "approve", "purchase_order", po.id, f"采购单 {po.po_no} 审批通过一级，流转下一级")
        ctx.db.commit()
        return po
    po.status = PurchaseStatus.APPROVED
    po.approved_by = ctx.user_id
    po.approved_at = utcnow()
    audit(ctx, "approve", "purchase_order", po.id, f"审批通过采购单 {po.po_no}")
    ctx.db.commit()
    return po


def reject_order(ctx: Ctx, po_id: int, reason: str) -> PurchaseOrder:
    po = get_or_404(ctx.db, PurchaseOrder, po_id, "采购单", for_update=True)
    if po.status != PurchaseStatus.PENDING_APPROVAL:
        raise BizError("采购单不在待审批状态")
    if approval.act(ctx, "purchase_order", po.id, False, reason) is None:
        ctx.require("purchase:order:approve")
    po.status = PurchaseStatus.REJECTED
    po.reject_reason = reason
    audit(ctx, "reject", "purchase_order", po.id, f"驳回采购单 {po.po_no}：{reason}")
    ctx.db.commit()
    return po


def mark_ordered(ctx: Ctx, po_id: int, data: dict) -> PurchaseOrder:
    po = get_or_404(ctx.db, PurchaseOrder, po_id, "采购单", for_update=True)
    if po.status != PurchaseStatus.APPROVED:
        raise BizError("仅审批通过的采购单可确认下单")
    for k, v in data.items():
        if v is not None:
            setattr(po, k, v)
    po.order_date = po.order_date or date.today()
    po.status = PurchaseStatus.ORDERED
    audit(ctx, "order", "purchase_order", po.id, f"确认下单 {po.po_no}")
    ctx.db.commit()
    return po


def receive(ctx: Ctx, po_id: int, data: dict) -> PurchaseReceipt:
    """到货质检入库。良品按落地成本（采购价×汇率，运杂费按金额分摊）生成批次。"""
    db = ctx.db
    po = get_or_404(db, PurchaseOrder, po_id, "采购单", for_update=True)
    if po.status not in RECEIVABLE:
        raise BizError("采购单当前状态不能收货")
    lines_by_id = {ln.id: ln for ln in po.lines}
    receipt = PurchaseReceipt(
        receipt_no=next_doc_no(db, "RC"),
        order_id=po.id,
        supplier_id=po.supplier_id,
        warehouse_id=po.warehouse_id,
        status="completed",
        received_at=utcnow(),
        tracking_no=data.get("tracking_no"),
        remark=data.get("remark"),
    )
    db.add(receipt)
    db.flush()
    inv = InventoryService(db)
    ref = Ref("purchase_receipt", receipt.id, receipt.receipt_no, f"采购单 {po.po_no}")
    rate = Decimal(po.exchange_rate or 1)
    goods = Decimal(po.goods_amount or 0)
    discount_ratio = (Decimal(po.discount or 0) / goods) if goods else Decimal(0)
    fees = Decimal(po.shipping_fee or 0) + Decimal(po.other_fee or 0)
    total_in = 0
    for item in data["lines"]:
        ln = lines_by_id.get(item["order_line_id"])
        if ln is None:
            raise BizError(f"采购明细不存在（ID={item['order_line_id']}）")
        qty = item["qty_good"] + item["qty_defective"]
        if qty <= 0:
            continue
        if qty > ln.qty_pending:
            product = db.get(Product, ln.product_id)
            raise BizError(f"{product.sku} 到货数量 {qty} 超过未到货数量 {ln.qty_pending}")
        unit_purchase = q4(Decimal(ln.unit_price) * (1 - discount_ratio) * rate)
        unit_freight = q4(fees * (Decimal(ln.amount) / goods) / ln.qty * rate) if goods and ln.qty else Decimal(0)
        batch_no = None
        if item["qty_good"]:
            batch = inv.inbound(
                po.warehouse_id, ln.product_id, item["qty_good"], ref, change_type=LedgerType.PURCHASE_IN,
                unit_purchase_cost=unit_purchase, unit_freight_cost=unit_freight,
                batch_no=receipt.receipt_no, supplier_id=po.supplier_id, purchase_order_id=po.id,
            )
            batch_no = batch.batch_no
        if item["qty_defective"]:
            inv.inbound_defective(po.warehouse_id, ln.product_id, item["qty_defective"], ref)
        ln.qty_received += qty
        ln.qty_good += item["qty_good"]
        ln.qty_defective += item["qty_defective"]
        receipt.lines.append(
            PurchaseReceiptLine(
                order_line_id=ln.id, product_id=ln.product_id, qty_good=item["qty_good"],
                qty_defective=item["qty_defective"], unit_purchase_cost=unit_purchase,
                unit_freight_cost=unit_freight, batch_no=batch_no,
            )
        )
        total_in += qty
    if total_in == 0:
        raise BizError("请填写到货数量")
    po.status = PurchaseStatus.RECEIVED if all(ln.qty_pending == 0 for ln in po.lines) else PurchaseStatus.PARTIAL
    if data.get("tracking_no"):
        po.tracking_no = data["tracking_no"]
    audit(ctx, "receive", "purchase_order", po.id, f"采购到货 {po.po_no}，入库单 {receipt.receipt_no}，共 {total_in} 件")
    db.commit()
    return receipt


def close_order(ctx: Ctx, po_id: int) -> PurchaseOrder:
    po = get_or_404(ctx.db, PurchaseOrder, po_id, "采购单", for_update=True)
    if po.status not in (PurchaseStatus.ORDERED, PurchaseStatus.PARTIAL, PurchaseStatus.APPROVED):
        raise BizError("当前状态不能结单")
    if not any(ln.qty_received for ln in po.lines):
        raise BizError("尚未到货的采购单请使用作废")
    po.status = PurchaseStatus.CLOSED
    audit(ctx, "close", "purchase_order", po.id, f"结单 {po.po_no}（剩余未到货不再收货）")
    ctx.db.commit()
    return po


def cancel_order(ctx: Ctx, po_id: int) -> PurchaseOrder:
    po = get_or_404(ctx.db, PurchaseOrder, po_id, "采购单", for_update=True)
    allowed = (*EDITABLE, PurchaseStatus.PENDING_APPROVAL, PurchaseStatus.APPROVED, PurchaseStatus.ORDERED)
    if po.status not in allowed or any(ln.qty_received for ln in po.lines):
        raise BizError("已到货的采购单不能作废，请使用结单")
    if po.paid_amount or po.requested_amount:
        raise BizError("采购单存在请款/付款记录，请先处理请款单")
    po.status = PurchaseStatus.CANCELLED
    approval.cancel_pending(ctx.db, "purchase_order", po.id)
    # 关联的采购计划退回待处理
    for plan in ctx.db.execute(select(PurchasePlan).where(PurchasePlan.purchase_order_id == po.id)).scalars().all():
        plan.status = PlanStatus.PENDING
        plan.purchase_order_id = None
    audit(ctx, "cancel", "purchase_order", po.id, f"作废采购单 {po.po_no}")
    ctx.db.commit()
    return po


def delete_order(ctx: Ctx, po_id: int) -> None:
    po = get_or_404(ctx.db, PurchaseOrder, po_id, "采购单", for_update=True)
    if po.status not in (PurchaseStatus.DRAFT, PurchaseStatus.CANCELLED):
        raise BizError("仅草稿或已作废的采购单可删除")
    if ctx.db.execute(select(PurchaseReceipt.id).where(PurchaseReceipt.order_id == po.id)).first():
        raise BizError("存在入库记录，不能删除")
    if ctx.db.execute(select(PaymentRequestLine.id).where(PaymentRequestLine.purchase_order_id == po.id)).first():
        raise BizError("存在请款记录，不能删除（可保留为已作废）")
    for plan in ctx.db.execute(select(PurchasePlan).where(PurchasePlan.purchase_order_id == po.id)).scalars().all():
        plan.status = PlanStatus.PENDING
        plan.purchase_order_id = None
    ctx.db.delete(po)
    audit(ctx, "delete", "purchase_order", po_id, f"删除采购单 {po.po_no}")
    ctx.db.commit()


# ================================================================ 采购退货
def create_return(ctx: Ctx, data: dict) -> PurchaseReturn:
    db = ctx.db
    po = get_or_404(db, PurchaseOrder, data["order_id"], "采购单", for_update=True)
    stock_type = data.get("stock_type", StockType.DEFECTIVE)
    if stock_type not in (StockType.GOOD, StockType.DEFECTIVE):
        raise BizError("无效的库存类型")
    lines_by_id = {ln.id: ln for ln in po.lines}
    ret = PurchaseReturn(
        return_no=next_doc_no(db, "PR"),
        order_id=po.id,
        supplier_id=po.supplier_id,
        warehouse_id=po.warehouse_id,
        stock_type=stock_type,
        status="completed",
        reason=data.get("reason"),
        remark=data.get("remark"),
    )
    db.add(ret)
    db.flush()
    inv = InventoryService(db)
    ref = Ref("purchase_return", ret.id, ret.return_no, f"采购单 {po.po_no}")
    auto_refund = Decimal(0)
    for item in data["lines"]:
        ln = lines_by_id.get(item["order_line_id"])
        if ln is None:
            raise BizError("采购明细不存在")
        returnable = ln.qty_received - ln.qty_returned
        if item["qty"] > returnable:
            raise BizError(f"退货数量 {item['qty']} 超过可退数量 {returnable}")
        if stock_type == StockType.DEFECTIVE:
            inv.outbound_defective(po.warehouse_id, ln.product_id, item["qty"], ref, change_type=LedgerType.PURCHASE_RETURN)
        else:
            inv.outbound(po.warehouse_id, ln.product_id, item["qty"], ref, change_type=LedgerType.PURCHASE_RETURN)
        ln.qty_returned += item["qty"]
        auto_refund += Decimal(ln.unit_price) * item["qty"]
        ret.lines.append(PurchaseReturnLine(order_line_id=ln.id, product_id=ln.product_id, qty=item["qty"], unit_price=ln.unit_price))
    ret.refund_amount = q2(data["refund_amount"] if data.get("refund_amount") is not None else auto_refund)
    po.returned_amount = q2(Decimal(po.returned_amount or 0) + ret.refund_amount)
    _refresh_payment_status(po)
    audit(ctx, "create", "purchase_return", ret.id, f"采购退货 {ret.return_no}（{po.po_no}），退款 {ret.refund_amount}")
    db.commit()
    return ret


# ================================================================ 请款 / 付款
def _refresh_payment_status(po: PurchaseOrder) -> None:
    payable = Decimal(po.total_amount or 0) - Decimal(po.returned_amount or 0)
    paid = Decimal(po.paid_amount or 0)
    if paid <= 0:
        po.payment_status = PaymentStatus.UNPAID
    elif paid >= payable:
        po.payment_status = PaymentStatus.PAID
    else:
        po.payment_status = PaymentStatus.PARTIAL


def create_payment_request(ctx: Ctx, data: dict) -> PaymentRequest:
    db = ctx.db
    supplier = get_or_404(db, Supplier, data["supplier_id"], "供应商")
    lines = data.pop("lines")
    po_ids = [ln["purchase_order_id"] for ln in lines]
    if len(set(po_ids)) != len(po_ids):
        raise BizError("同一采购单不能重复请款")
    pos = {p.id: p for p in db.execute(select(PurchaseOrder).where(PurchaseOrder.id.in_(po_ids)).with_for_update(of=PurchaseOrder)).scalars().all()}
    currency = None
    req = PaymentRequest(request_no=next_doc_no(db, "PAY"), status=PaymentRequestStatus.PENDING, **data)
    total = Decimal(0)
    for ln in lines:
        po = pos.get(ln["purchase_order_id"])
        if po is None:
            raise BizError("采购单不存在")
        if po.supplier_id != supplier.id:
            raise BizError(f"采购单 {po.po_no} 不属于该供应商")
        if po.status in (PurchaseStatus.DRAFT, PurchaseStatus.CANCELLED, PurchaseStatus.REJECTED, PurchaseStatus.PENDING_APPROVAL):
            raise BizError(f"采购单 {po.po_no} 未审批，不能请款")
        if currency and po.currency != currency:
            raise BizError("同一请款单的采购单币种必须一致")
        currency = po.currency
        outstanding = Decimal(po.total_amount) - Decimal(po.returned_amount or 0) - Decimal(po.requested_amount or 0)
        amount = q2(ln["amount"])
        if amount > outstanding:
            raise BizError(f"采购单 {po.po_no} 请款金额 {amount} 超过可请款金额 {q2(outstanding)}")
        po.requested_amount = q2(Decimal(po.requested_amount or 0) + amount)
        req.lines.append(PaymentRequestLine(purchase_order_id=po.id, amount=amount))
        total += amount
    req.currency = currency or supplier.currency
    req.amount = q2(total)
    need_flow = approval.requires_approval(db, "payment_request", req.amount, req.currency)
    if not get_setting(db, "payment.require_approval") and not need_flow:
        req.status = PaymentRequestStatus.APPROVED
        req.approved_by = ctx.user_id
        req.approved_at = utcnow()
    db.add(req)
    db.flush()
    if req.status == PaymentRequestStatus.PENDING:
        approval.start(ctx, "payment_request", req.id, doc_no=req.request_no, amount=req.amount, currency=req.currency,
                       summary=f"{supplier.name} 请款 {req.amount} {req.currency}", link="/purchase/payments")
    audit(ctx, "create", "payment_request", req.id, f"请款单 {req.request_no}，{req.amount} {req.currency}")
    db.commit()
    return req


def _release_requested(db, req: PaymentRequest) -> None:
    for ln in req.lines:
        po = db.get(PurchaseOrder, ln.purchase_order_id)
        po.requested_amount = q2(max(Decimal(0), Decimal(po.requested_amount or 0) - Decimal(ln.amount)))


def approve_payment(ctx: Ctx, req_id: int, comment: str | None = None) -> PaymentRequest:
    req = get_or_404(ctx.db, PaymentRequest, req_id, "请款单", for_update=True)
    if req.status != PaymentRequestStatus.PENDING:
        raise BizError("请款单不在待审批状态")
    res = approval.act(ctx, "payment_request", req.id, True, comment)
    if res is None:
        ctx.require("purchase:payment:approve")
    elif res == "pending":
        audit(ctx, "approve", "payment_request", req.id, f"请款单 {req.request_no} 审批通过一级，流转下一级")
        ctx.db.commit()
        return req
    req.status = PaymentRequestStatus.APPROVED
    req.approved_by = ctx.user_id
    req.approved_at = utcnow()
    audit(ctx, "approve", "payment_request", req.id, f"审批通过请款单 {req.request_no}")
    ctx.db.commit()
    return req


def reject_payment(ctx: Ctx, req_id: int, reason: str) -> PaymentRequest:
    req = get_or_404(ctx.db, PaymentRequest, req_id, "请款单", for_update=True)
    if req.status != PaymentRequestStatus.PENDING:
        raise BizError("请款单不在待审批状态")
    if approval.act(ctx, "payment_request", req.id, False, reason) is None:
        ctx.require("purchase:payment:approve")
    req.status = PaymentRequestStatus.REJECTED
    req.reject_reason = reason
    _release_requested(ctx.db, req)
    audit(ctx, "reject", "payment_request", req.id, f"驳回请款单 {req.request_no}：{reason}")
    ctx.db.commit()
    return req


def pay(ctx: Ctx, req_id: int, data: dict) -> PaymentRequest:
    req = get_or_404(ctx.db, PaymentRequest, req_id, "请款单", for_update=True)
    if req.status != PaymentRequestStatus.APPROVED:
        raise BizError("请款单未审批或已付款")
    req.status = PaymentRequestStatus.PAID
    req.paid_by = ctx.user_id
    req.paid_at = data.get("paid_at") or utcnow()
    req.transaction_no = data.get("transaction_no") or req.transaction_no
    req.payment_method = data.get("payment_method") or req.payment_method
    for ln in req.lines:
        po = get_or_404(ctx.db, PurchaseOrder, ln.purchase_order_id, "采购单", for_update=True)
        po.paid_amount = q2(Decimal(po.paid_amount or 0) + Decimal(ln.amount))
        po.requested_amount = q2(max(Decimal(0), Decimal(po.requested_amount or 0) - Decimal(ln.amount)))
        _refresh_payment_status(po)
    audit(ctx, "pay", "payment_request", req.id, f"确认付款 {req.request_no}，{req.amount} {req.currency}")
    ctx.db.commit()
    return req


def cancel_payment(ctx: Ctx, req_id: int) -> PaymentRequest:
    req = get_or_404(ctx.db, PaymentRequest, req_id, "请款单", for_update=True)
    if req.status not in (PaymentRequestStatus.PENDING, PaymentRequestStatus.APPROVED):
        raise BizError("当前状态不能取消")
    req.status = PaymentRequestStatus.CANCELLED
    approval.cancel_pending(ctx.db, "payment_request", req.id)
    _release_requested(ctx.db, req)
    audit(ctx, "cancel", "payment_request", req.id, f"取消请款单 {req.request_no}")
    ctx.db.commit()
    return req
