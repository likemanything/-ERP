from decimal import Decimal

from sqlalchemy import select

from app.common.audit import audit
from app.common.crud import get_or_404
from app.common.enums import DocStatus, LedgerType, ProductType, StockDocType, StockType
from app.common.numbering import next_doc_no
from app.core.deps import Ctx
from app.core.errors import BizError
from app.core.types import q4, utcnow
from app.modules.product.models import Product
from app.modules.warehouse.inventory import InventoryService, Ref
from app.modules.warehouse.models import InventoryBalance, StockDocument, StockDocumentLine, Warehouse

DOC_PREFIX = {
    StockDocType.IN: "RK",
    StockDocType.OUT: "CK",
    StockDocType.TRANSFER: "DB",
    StockDocType.STOCKTAKE: "PD",
}
DOC_LABEL = {
    StockDocType.IN: "其他入库单",
    StockDocType.OUT: "其他出库单",
    StockDocType.TRANSFER: "调拨单",
    StockDocType.STOCKTAKE: "盘点单",
}


def _validate_lines(ctx: Ctx, doc_type: str, lines: list[dict]) -> None:
    if not lines:
        raise BizError("请添加产品明细")
    ids = [ln["product_id"] for ln in lines]
    if len(set(ids)) != len(ids):
        raise BizError("明细中存在重复的产品")
    products = {p.id: p for p in ctx.db.execute(select(Product).where(Product.id.in_(ids))).scalars().all()}
    for ln in lines:
        p = products.get(ln["product_id"])
        if p is None:
            raise BizError(f"产品不存在（ID={ln['product_id']}）")
        if p.product_type == ProductType.BUNDLE:
            raise BizError(f"组合产品 {p.sku} 不能直接出入库，请操作子产品")
        if doc_type == StockDocType.STOCKTAKE:
            if ln.get("counted_qty") is None:
                raise BizError(f"{p.sku} 未填写实盘数量")
        elif (ln.get("qty") or 0) <= 0:
            raise BizError(f"{p.sku} 数量必须大于 0")


def _build_lines(doc: StockDocument, lines: list[dict]) -> None:
    doc.lines = [
        StockDocumentLine(
            product_id=ln["product_id"],
            qty=ln.get("qty") or 0,
            unit_cost=ln.get("unit_cost") if ln.get("unit_cost") is not None else Decimal(0),
            counted_qty=ln.get("counted_qty"),
            remark=ln.get("remark"),
        )
        for ln in lines
    ]


def create_document(ctx: Ctx, data: dict) -> StockDocument:
    doc_type = data["doc_type"]
    if doc_type not in {t.value for t in StockDocType}:
        raise BizError(f"无效的单据类型: {doc_type}")
    if data.get("stock_type", "good") not in {s.value for s in StockType}:
        raise BizError("无效的库存类型")
    wh = get_or_404(ctx.db, Warehouse, data["warehouse_id"], "仓库")
    if wh.status != "active":
        raise BizError("仓库已停用")
    if doc_type == StockDocType.TRANSFER:
        if not data.get("to_warehouse_id"):
            raise BizError("调拨单需选择目的仓")
        if data["to_warehouse_id"] == wh.id:
            raise BizError("调出仓与调入仓不能相同")
        get_or_404(ctx.db, Warehouse, data["to_warehouse_id"], "目的仓")
    lines = data.pop("lines", [])
    fill_all = data.pop("fill_all", False)
    if doc_type == StockDocType.STOCKTAKE and fill_all and not lines:
        bals = ctx.db.execute(
            select(InventoryBalance).where(InventoryBalance.warehouse_id == wh.id, InventoryBalance.qty_on_hand != 0)
        ).scalars().all()
        lines = [{"product_id": b.product_id, "counted_qty": b.qty_on_hand} for b in bals]
    _validate_lines(ctx, doc_type, lines)
    doc = StockDocument(doc_no=next_doc_no(ctx.db, DOC_PREFIX[doc_type]), status=DocStatus.DRAFT, **data)
    _build_lines(doc, lines)
    ctx.db.add(doc)
    ctx.db.flush()
    _snapshot_stocktake(ctx, doc)
    audit(ctx, "create", "stock_document", doc.id, f"新建{DOC_LABEL[doc_type]} {doc.doc_no}")
    ctx.db.commit()
    return doc


def _snapshot_stocktake(ctx: Ctx, doc: StockDocument) -> None:
    if doc.doc_type != StockDocType.STOCKTAKE:
        return
    inv = InventoryService(ctx.db)
    for ln in doc.lines:
        ln.system_qty = inv.balance(doc.warehouse_id, ln.product_id, lock=False).qty_on_hand


def update_document(ctx: Ctx, doc_id: int, data: dict) -> StockDocument:
    doc = get_or_404(ctx.db, StockDocument, doc_id, "库存单据", for_update=True)
    if doc.status not in (DocStatus.DRAFT, DocStatus.PENDING):
        raise BizError("仅草稿/待审核单据可修改")
    lines = data.pop("lines", None)
    for k, v in data.items():
        setattr(doc, k, v)
    if doc.doc_type == StockDocType.TRANSFER and doc.to_warehouse_id == doc.warehouse_id:
        raise BizError("调出仓与调入仓不能相同")
    if lines is not None:
        _validate_lines(ctx, doc.doc_type, lines)
        _build_lines(doc, lines)
        ctx.db.flush()
        _snapshot_stocktake(ctx, doc)
    audit(ctx, "update", "stock_document", doc.id, f"修改库存单据 {doc.doc_no}")
    ctx.db.commit()
    return doc


def submit_document(ctx: Ctx, doc_id: int) -> StockDocument:
    doc = get_or_404(ctx.db, StockDocument, doc_id, "库存单据", for_update=True)
    if doc.status != DocStatus.DRAFT:
        raise BizError("仅草稿单据可提交")
    doc.status = DocStatus.PENDING
    audit(ctx, "submit", "stock_document", doc.id, f"提交库存单据 {doc.doc_no}")
    ctx.db.commit()
    return doc


def approve_document(ctx: Ctx, doc_id: int) -> StockDocument:
    """审核过账：入库/出库/盘点直接完成；调拨单出库后进入在途。"""
    db = ctx.db
    doc = get_or_404(db, StockDocument, doc_id, "库存单据", for_update=True)
    if doc.status not in (DocStatus.DRAFT, DocStatus.PENDING):
        raise BizError("单据状态不允许审核")
    inv = InventoryService(db)
    ref = Ref("stock_document", doc.id, doc.doc_no, doc.remark)
    defective = doc.stock_type == StockType.DEFECTIVE

    if doc.doc_type == StockDocType.IN:
        change = LedgerType.INITIAL if doc.biz_type == "initial" else LedgerType.OTHER_IN
        for ln in doc.lines:
            if defective:
                inv.inbound_defective(doc.warehouse_id, ln.product_id, ln.qty, ref)
            else:
                unit = ln.unit_cost if ln.unit_cost else None
                batch = inv.inbound(doc.warehouse_id, ln.product_id, ln.qty, ref, change_type=change, unit_purchase_cost=unit)
                ln.unit_cost = batch.unit_purchase_cost
        doc.status = DocStatus.COMPLETED
        doc.completed_at = utcnow()

    elif doc.doc_type == StockDocType.OUT:
        for ln in doc.lines:
            if defective:
                inv.outbound_defective(doc.warehouse_id, ln.product_id, ln.qty, ref)
            else:
                res = inv.outbound(doc.warehouse_id, ln.product_id, ln.qty, ref, change_type=LedgerType.OTHER_OUT)
                ln.unit_cost = res.unit_purchase_cost
                ln.unit_freight_cost = res.unit_freight_cost
        doc.status = DocStatus.COMPLETED
        doc.completed_at = utcnow()

    elif doc.doc_type == StockDocType.TRANSFER:
        if defective:
            raise BizError("暂不支持次品调拨，请先做次品出库/入库")
        for ln in doc.lines:
            res = inv.outbound(doc.warehouse_id, ln.product_id, ln.qty, ref, change_type=LedgerType.TRANSFER_OUT)
            ln.unit_cost = res.unit_purchase_cost
            ln.unit_freight_cost = res.unit_freight_cost
            inv.add_in_transit(doc.to_warehouse_id, ln.product_id, ln.qty)
        doc.status = DocStatus.IN_TRANSIT
        doc.shipped_at = utcnow()

    elif doc.doc_type == StockDocType.STOCKTAKE:
        for ln in doc.lines:
            ln.system_qty = inv.balance(doc.warehouse_id, ln.product_id).qty_on_hand
            diff = inv.adjust_to(doc.warehouse_id, ln.product_id, ln.counted_qty or 0, ref)
            ln.qty = diff
        doc.status = DocStatus.COMPLETED
        doc.completed_at = utcnow()

    doc.approved_by = ctx.user_id
    audit(ctx, "approve", "stock_document", doc.id, f"审核过账 {doc.doc_no}")
    db.commit()
    return doc


def receive_transfer(ctx: Ctx, doc_id: int, lines: list[dict] | None) -> StockDocument:
    """调拨签收：按实收数量入目的仓，调拨运费按数量分摊进入库成本。"""
    db = ctx.db
    doc = get_or_404(db, StockDocument, doc_id, "库存单据", for_update=True)
    if doc.doc_type != StockDocType.TRANSFER or doc.status != DocStatus.IN_TRANSIT:
        raise BizError("仅在途调拨单可签收")
    received = {ln["line_id"]: ln["qty_received"] for ln in lines} if lines else {}
    for line_id in received:
        if line_id not in {ln.id for ln in doc.lines}:
            raise BizError(f"明细不存在: {line_id}")
    inv = InventoryService(db)
    ref = Ref("stock_document", doc.id, doc.doc_no, doc.remark)
    total_received = sum(received.get(ln.id, ln.qty) for ln in doc.lines)
    unit_extra = q4(Decimal(doc.freight_cost or 0) / total_received) if total_received else Decimal(0)
    for ln in doc.lines:
        qty = received.get(ln.id, ln.qty)
        if qty > ln.qty:
            raise BizError("实收数量不能大于调拨数量")
        ln.qty_received = qty
        inv.add_in_transit(doc.to_warehouse_id, ln.product_id, -ln.qty)
        if qty > 0:
            inv.inbound(
                doc.to_warehouse_id, ln.product_id, qty, ref, change_type=LedgerType.TRANSFER_IN,
                unit_purchase_cost=ln.unit_cost, unit_freight_cost=(ln.unit_freight_cost or Decimal(0)) + unit_extra,
            )
    doc.status = DocStatus.COMPLETED
    doc.completed_at = utcnow()
    audit(ctx, "receive", "stock_document", doc.id, f"调拨签收 {doc.doc_no}")
    db.commit()
    return doc


def cancel_document(ctx: Ctx, doc_id: int) -> StockDocument:
    doc = get_or_404(ctx.db, StockDocument, doc_id, "库存单据", for_update=True)
    if doc.status not in (DocStatus.DRAFT, DocStatus.PENDING):
        raise BizError("已过账的单据不能作废")
    doc.status = DocStatus.CANCELLED
    audit(ctx, "cancel", "stock_document", doc.id, f"作废库存单据 {doc.doc_no}")
    ctx.db.commit()
    return doc
