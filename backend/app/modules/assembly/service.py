"""加工单：组装 / 拆分，成本按 FIFO 结转。

* 组装：按 FIFO 消耗子件（含头程等物流成本），成品入库单位成本 = (子件成本 + 加工费) / 成品数量。
* 拆分：按 FIFO 消耗成品，成本 + 加工费按子件参考采购成本 × 数量的比例分摊到子件入库。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.common.audit import audit
from app.common.crud import get_or_404
from app.common.enums import LedgerType, ProductType
from app.common.numbering import next_doc_no
from app.core.deps import Ctx
from app.core.errors import BizError
from app.core.types import q2, q4, utcnow
from app.modules.assembly.models import AssemblyLine, AssemblyOrder
from app.modules.product.models import Product
from app.modules.warehouse.inventory import InventoryService, Ref
from app.modules.warehouse.models import Warehouse

TYPE_LABEL = {"assemble": "组装", "disassemble": "拆分"}


def _validate(db, data: dict) -> tuple[Product, list[dict]]:
    if data.get("order_type", "assemble") not in TYPE_LABEL:
        raise BizError("无效的加工类型")
    qty = int(data.get("qty") or 0)
    if qty <= 0:
        raise BizError("成品数量必须大于 0")
    wh = get_or_404(db, Warehouse, data["warehouse_id"], "仓库")
    if wh.warehouse_type == "fba":
        raise BizError("FBA 仓不能做加工单")
    product = get_or_404(db, Product, data["product_id"], "成品")
    if product.product_type != ProductType.NORMAL:
        raise BizError(f"{product.sku} 不是普通产品；组合产品为虚拟套装，发货时自动拆分，无需加工")
    lines = data.get("lines") or []
    if not lines:
        raise BizError("请添加子件明细")
    seen: set[int] = set()
    out = []
    for ln in lines:
        pid = ln["product_id"]
        per = int(ln.get("qty_per_unit") or 0)
        if per <= 0:
            raise BizError("子件用量必须大于 0")
        if pid == product.id:
            raise BizError("子件不能与成品相同")
        if pid in seen:
            raise BizError("子件重复，请合并为一行")
        seen.add(pid)
        comp = get_or_404(db, Product, pid, "子件")
        if comp.product_type == ProductType.BUNDLE:
            raise BizError(f"组合产品 {comp.sku} 不能作为子件，请直接使用其子产品")
        out.append({"product_id": pid, "qty_per_unit": per, "qty": per * qty})
    return product, out


def _apply(db, order: AssemblyOrder, data: dict) -> None:
    _, lines = _validate(db, data)
    for k in ("order_type", "warehouse_id", "product_id", "qty", "processing_fee", "plan_date", "remark"):
        if k in data:
            setattr(order, k, data[k] if k != "processing_fee" else q2(data[k] or 0))
    order.lines = [AssemblyLine(**ln) for ln in lines]


def create_order(ctx: Ctx, data: dict) -> AssemblyOrder:
    order = AssemblyOrder(order_no=next_doc_no(ctx.db, "JG"), status="draft")
    _apply(ctx.db, order, data)
    ctx.db.add(order)
    ctx.db.flush()
    audit(ctx, "create", "assembly_order", order.id, f"新建{TYPE_LABEL[order.order_type]}单 {order.order_no}")
    ctx.db.commit()
    return order


def update_order(ctx: Ctx, order_id: int, data: dict) -> AssemblyOrder:
    order = get_or_404(ctx.db, AssemblyOrder, order_id, "加工单", for_update=True)
    if order.status != "draft":
        raise BizError("只有草稿状态的加工单可以修改")
    merged = {"order_type": order.order_type, "warehouse_id": order.warehouse_id, "product_id": order.product_id,
              "qty": order.qty, "processing_fee": order.processing_fee, **data}
    if "lines" not in data:
        merged["lines"] = [{"product_id": ln.product_id, "qty_per_unit": ln.qty_per_unit} for ln in order.lines]
    _apply(ctx.db, order, merged)
    audit(ctx, "update", "assembly_order", order.id, f"修改加工单 {order.order_no}")
    ctx.db.commit()
    return order


def _allocation_weights(db, lines: list[AssemblyLine]) -> list[Decimal]:
    products = {p.id: p for p in db.execute(select(Product).where(Product.id.in_([ln.product_id for ln in lines]))).scalars().all()}
    weights = [Decimal(products[ln.product_id].purchase_cost or 0) * ln.qty for ln in lines]
    if sum(weights) <= 0:
        weights = [Decimal(ln.qty) for ln in lines]
    total = sum(weights)
    return [w / total for w in weights]


def complete_order(ctx: Ctx, order_id: int) -> AssemblyOrder:
    """执行加工：扣减 / 增加库存并结转成本。"""
    db = ctx.db
    order = get_or_404(db, AssemblyOrder, order_id, "加工单", for_update=True)
    if order.status != "draft":
        raise BizError("加工单已完成或已作废")
    inv = InventoryService(db)
    ref = Ref("assembly_order", order.id, order.order_no, f"{TYPE_LABEL[order.order_type]}单 {order.order_no}")
    fee = Decimal(order.processing_fee or 0)
    if order.order_type == "assemble":
        purchase = fee
        freight = Decimal(0)
        for ln in order.lines:
            res = inv.outbound(order.warehouse_id, ln.product_id, ln.qty, ref, change_type=LedgerType.ASSEMBLY_OUT,
                               allow_negative=False)
            ln.amount = q4(res.total_cost)
            ln.unit_cost = q4(res.total_cost / ln.qty)
            purchase += res.purchase_cost
            freight += res.freight_cost
        inv.inbound(order.warehouse_id, order.product_id, order.qty, ref, change_type=LedgerType.ASSEMBLY_IN,
                    unit_purchase_cost=purchase / order.qty, unit_freight_cost=freight / order.qty)
        order.total_cost = q4(purchase + freight)
        order.unit_cost = q4((purchase + freight) / order.qty)
    else:
        res = inv.outbound(order.warehouse_id, order.product_id, order.qty, ref, change_type=LedgerType.ASSEMBLY_OUT,
                           allow_negative=False)
        order.total_cost = q4(res.total_cost + fee)
        order.unit_cost = q4(res.total_cost / order.qty)
        for ln, w in zip(order.lines, _allocation_weights(db, order.lines), strict=True):
            purchase = (res.purchase_cost + fee) * w
            freight = res.freight_cost * w
            inv.inbound(order.warehouse_id, ln.product_id, ln.qty, ref, change_type=LedgerType.ASSEMBLY_IN,
                        unit_purchase_cost=purchase / ln.qty, unit_freight_cost=freight / ln.qty)
            ln.amount = q4(purchase + freight)
            ln.unit_cost = q4((purchase + freight) / ln.qty)
    order.status = "completed"
    order.completed_at = utcnow()
    order.completed_by = ctx.user_id
    audit(ctx, "complete", "assembly_order", order.id,
          f"完成{TYPE_LABEL[order.order_type]}单 {order.order_no}，成本 {q2(order.total_cost)}")
    db.commit()
    return order


def cancel_order(ctx: Ctx, order_id: int) -> AssemblyOrder:
    order = get_or_404(ctx.db, AssemblyOrder, order_id, "加工单", for_update=True)
    if order.status != "draft":
        raise BizError("只有草稿状态的加工单可以作废")
    order.status = "cancelled"
    audit(ctx, "cancel", "assembly_order", order.id, f"作废加工单 {order.order_no}")
    ctx.db.commit()
    return order


def last_recipe(db, product_id: int) -> list[dict]:
    """该成品最近一次加工单的子件配方，用于新建时自动带出。"""
    order = db.execute(
        select(AssemblyOrder).where(AssemblyOrder.product_id == product_id, AssemblyOrder.status != "cancelled")
        .order_by(AssemblyOrder.id.desc()).limit(1)
    ).scalar_one_or_none()
    if order is None:
        return []
    return [{"product_id": ln.product_id, "qty_per_unit": ln.qty_per_unit} for ln in order.lines]
