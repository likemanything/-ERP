from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update

from app.common.crud import build_crud_router, ensure_not_referenced, get_or_404, keyword_filter
from app.common.excel import export_xlsx
from app.common.pagination import PageParams, page_params, paginate
from app.common.schemas import Page
from app.core.deps import Ctx, perm
from app.core.errors import BizError
from app.core.types import utcnow
from app.modules.product.models import Product
from app.modules.warehouse import service
from app.modules.warehouse.models import (
    InventoryBalance,
    InventoryBatch,
    InventoryLedger,
    StockDocument,
    Warehouse,
    WarehouseBin,
)
from app.modules.warehouse.schemas import (
    BatchOut,
    BinIn,
    BinOut,
    BinUpdate,
    InventoryRow,
    InventorySettingIn,
    LedgerOut,
    StockDocIn,
    StockDocOut,
    StockDocUpdate,
    TransferReceiveIn,
    WarehouseIn,
    WarehouseOut,
    WarehouseUpdate,
)

router = APIRouter(tags=["仓库管理"])


# ------------------------------------------------------------------ 仓库 / 库位
def _wh_before_save(ctx: Ctx, obj, data: dict) -> None:
    if data.get("warehouse_type") and data["warehouse_type"] not in ("local", "overseas", "fba", "third_party"):
        raise BizError("无效的仓库类型")
    if data.get("is_default"):
        ctx.db.execute(update(Warehouse).values(is_default=False))


def _wh_before_delete(ctx: Ctx, wh: Warehouse) -> None:
    ensure_not_referenced(
        ctx.db,
        [
            (InventoryLedger, InventoryLedger.warehouse_id == wh.id, "库存流水"),
            (StockDocument, StockDocument.warehouse_id == wh.id, "库存单据"),
        ],
    )
    from sqlalchemy import delete

    ctx.db.execute(delete(InventoryBalance).where(InventoryBalance.warehouse_id == wh.id))


router.include_router(
    build_crud_router(
        model=Warehouse, create_schema=WarehouseIn, update_schema=WarehouseUpdate, out_schema=WarehouseOut,
        resource="warehouse", label="仓库", view_perm="warehouse:view", edit_perm="warehouse:edit",
        search_fields=("code", "name"), filter_fields=("warehouse_type", "status", "shop_id"),
        unique_fields=("code",), default_order=("id",), option_label=lambda w: w.name,
        before_save=_wh_before_save, before_delete=_wh_before_delete,
    ),
    prefix="/warehouses",
)
router.include_router(
    build_crud_router(
        model=WarehouseBin, create_schema=BinIn, update_schema=BinUpdate, out_schema=BinOut,
        resource="warehouse_bin", label="库位", view_perm="warehouse:view", edit_perm="warehouse:edit",
        search_fields=("code", "zone"), filter_fields=("warehouse_id", "bin_type", "status"),
        default_order=("warehouse_id", "code"), option_label=lambda b: b.code,
    ),
    prefix="/warehouse-bins",
)


# ------------------------------------------------------------------ 库存查询
def _value_subq():
    return (
        select(
            InventoryBatch.warehouse_id.label("wid"),
            InventoryBatch.product_id.label("pid"),
            func.sum(
                InventoryBatch.qty_remaining * (InventoryBatch.unit_purchase_cost + InventoryBatch.unit_freight_cost)
            ).label("value"),
        )
        .where(InventoryBatch.qty_remaining > 0)
        .group_by(InventoryBatch.warehouse_id, InventoryBatch.product_id)
        .subquery()
    )


def _inventory_query(keyword, warehouse_id, warehouse_type, in_stock_only, low_stock_only):
    vq = _value_subq()
    stmt = (
        select(InventoryBalance, Product, Warehouse, vq.c.value)
        .join(Product, Product.id == InventoryBalance.product_id)
        .join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id)
        .outerjoin(vq, (vq.c.wid == InventoryBalance.warehouse_id) & (vq.c.pid == InventoryBalance.product_id))
        .order_by(InventoryBalance.id.desc())
    )
    stmt = keyword_filter(stmt, keyword, [Product.sku, Product.name])
    if warehouse_id:
        stmt = stmt.where(InventoryBalance.warehouse_id == warehouse_id)
    if warehouse_type:
        stmt = stmt.where(Warehouse.warehouse_type == warehouse_type)
    if in_stock_only:
        stmt = stmt.where(
            (InventoryBalance.qty_on_hand != 0) | (InventoryBalance.qty_defective != 0) | (InventoryBalance.qty_in_transit != 0)
        )
    if low_stock_only:
        stmt = stmt.where(
            InventoryBalance.safety_stock > 0,
            (InventoryBalance.qty_on_hand - InventoryBalance.qty_locked) < InventoryBalance.safety_stock,
        )
    return stmt


def _inventory_rows(rows, show_cost: bool) -> list[dict]:
    result = []
    for bal, product, wh, value in rows:
        value = value or 0
        result.append(
            {
                "id": bal.id,
                "warehouse_id": wh.id,
                "warehouse_name": wh.name,
                "warehouse_type": wh.warehouse_type,
                "product_id": product.id,
                "sku": product.sku,
                "product_name": product.name,
                "image_url": product.image_url,
                "qty_on_hand": bal.qty_on_hand,
                "qty_locked": bal.qty_locked,
                "qty_available": bal.qty_available,
                "qty_defective": bal.qty_defective,
                "qty_in_transit": bal.qty_in_transit,
                "safety_stock": bal.safety_stock,
                "bin_code": bal.bin_code,
                "unit_cost": (value / bal.qty_on_hand if bal.qty_on_hand > 0 else 0) if show_cost else None,
                "stock_value": value if show_cost else None,
                "updated_at": bal.updated_at,
            }
        )
    return result


@router.get("/inventory", response_model=Page[InventoryRow], summary="库存明细（仓库 × SKU）")
def list_inventory(
    keyword: str | None = None,
    warehouse_id: int | None = None,
    warehouse_type: str | None = None,
    in_stock_only: bool = True,
    low_stock_only: bool = False,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("inventory:view")),
):
    stmt = _inventory_query(keyword, warehouse_id, warehouse_type, in_stock_only, low_stock_only)
    page = paginate(ctx.db, stmt, params, scalars=False)
    page["items"] = _inventory_rows(page["items"], ctx.can("product:cost:view"))
    return page


@router.get("/inventory/export", summary="导出库存")
def export_inventory(
    keyword: str | None = None,
    warehouse_id: int | None = None,
    warehouse_type: str | None = None,
    in_stock_only: bool = True,
    ctx: Ctx = Depends(perm("inventory:view")),
):
    rows = ctx.db.execute(_inventory_query(keyword, warehouse_id, warehouse_type, in_stock_only, False)).all()
    cols = [
        ("warehouse_name", "仓库"), ("sku", "SKU"), ("product_name", "品名"), ("qty_on_hand", "实物库存"),
        ("qty_locked", "锁定"), ("qty_available", "可用"), ("qty_defective", "次品"), ("qty_in_transit", "调拨在途"),
        ("safety_stock", "安全库存"), ("unit_cost", "单位成本"), ("stock_value", "库存金额"),
    ]
    return export_xlsx("库存明细.xlsx", cols, _inventory_rows(rows, ctx.can("product:cost:view")))


@router.get("/inventory/summary", summary="库存汇总（按 SKU 跨仓汇总）")
def inventory_summary(
    keyword: str | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("inventory:view")),
):
    local = Warehouse.warehouse_type.in_(["local", "overseas", "third_party"])
    stmt = (
        select(
            Product.id,
            Product.sku,
            Product.name,
            Product.image_url,
            func.sum(func.coalesce(InventoryBalance.qty_on_hand, 0)).filter(local).label("local_on_hand"),
            func.sum(InventoryBalance.qty_on_hand - InventoryBalance.qty_locked).filter(local).label("local_available"),
            func.sum(func.coalesce(InventoryBalance.qty_locked, 0)).filter(local).label("local_locked"),
            func.sum(func.coalesce(InventoryBalance.qty_defective, 0)).label("defective"),
            func.sum(func.coalesce(InventoryBalance.qty_in_transit, 0)).label("in_transit"),
            func.sum(func.coalesce(InventoryBalance.qty_on_hand, 0)).filter(Warehouse.warehouse_type == "fba").label("fba_on_hand"),
        )
        .join(InventoryBalance, InventoryBalance.product_id == Product.id)
        .join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id)
        .group_by(Product.id, Product.sku, Product.name, Product.image_url)
        .order_by(Product.sku)
    )
    stmt = keyword_filter(stmt, keyword, [Product.sku, Product.name])
    page = paginate(ctx.db, stmt, params, scalars=False)
    page["items"] = [
        {
            "product_id": r[0], "sku": r[1], "product_name": r[2], "image_url": r[3],
            "local_on_hand": int(r[4] or 0), "local_available": int(r[5] or 0), "local_locked": int(r[6] or 0),
            "defective": int(r[7] or 0), "in_transit": int(r[8] or 0), "fba_on_hand": int(r[9] or 0),
        }
        for r in page["items"]
    ]
    return page


@router.put("/inventory/{balance_id}", response_model=InventoryRow, summary="设置安全库存/默认库位")
def update_inventory_setting(balance_id: int, body: InventorySettingIn, ctx: Ctx = Depends(perm("warehouse:edit"))):
    bal = get_or_404(ctx.db, InventoryBalance, balance_id, "库存记录")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(bal, k, v)
    ctx.db.commit()
    row = ctx.db.execute(
        _inventory_query(None, None, None, False, False).where(InventoryBalance.id == bal.id)
    ).one()
    return _inventory_rows([row], ctx.can("product:cost:view"))[0]


@router.get("/inventory/ledger", response_model=Page[LedgerOut], summary="库存流水")
def list_ledger(
    keyword: str | None = None,
    warehouse_id: int | None = None,
    product_id: int | None = None,
    change_type: str | None = None,
    ref_no: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("inventory:ledger:view")),
):
    stmt = (
        select(InventoryLedger, Product.sku, Product.name, Warehouse.name)
        .join(Product, Product.id == InventoryLedger.product_id)
        .join(Warehouse, Warehouse.id == InventoryLedger.warehouse_id)
        .order_by(InventoryLedger.id.desc())
    )
    stmt = keyword_filter(stmt, keyword, [Product.sku, Product.name, InventoryLedger.ref_no])
    if warehouse_id:
        stmt = stmt.where(InventoryLedger.warehouse_id == warehouse_id)
    if product_id:
        stmt = stmt.where(InventoryLedger.product_id == product_id)
    if change_type:
        stmt = stmt.where(InventoryLedger.change_type == change_type)
    if ref_no:
        stmt = stmt.where(InventoryLedger.ref_no == ref_no)
    if date_from:
        stmt = stmt.where(InventoryLedger.biz_date >= date_from)
    if date_to:
        stmt = stmt.where(InventoryLedger.biz_date <= date_to)
    page = paginate(ctx.db, stmt, params, scalars=False)
    show_cost = ctx.can("product:cost:view")
    items = []
    for led, sku, pname, whname in page["items"]:
        d = {c.key: getattr(led, c.key) for c in InventoryLedger.__table__.columns}
        d.update(sku=sku, product_name=pname, warehouse_name=whname)
        if not show_cost:
            d.update(unit_purchase_cost=None, unit_freight_cost=None, amount=None)
        items.append(d)
    page["items"] = items
    return page


@router.get("/inventory/batches", response_model=Page[BatchOut], summary="库存批次（库龄）")
def list_batches(
    keyword: str | None = None,
    warehouse_id: int | None = None,
    product_id: int | None = None,
    remaining_only: bool = True,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("inventory:view")),
):
    stmt = (
        select(InventoryBatch, Product.sku, Product.name, Warehouse.name)
        .join(Product, Product.id == InventoryBatch.product_id)
        .join(Warehouse, Warehouse.id == InventoryBatch.warehouse_id)
        .order_by(InventoryBatch.received_at.asc(), InventoryBatch.id.asc())
    )
    stmt = keyword_filter(stmt, keyword, [Product.sku, Product.name, InventoryBatch.batch_no])
    if warehouse_id:
        stmt = stmt.where(InventoryBatch.warehouse_id == warehouse_id)
    if product_id:
        stmt = stmt.where(InventoryBatch.product_id == product_id)
    if remaining_only:
        stmt = stmt.where(InventoryBatch.qty_remaining > 0)
    page = paginate(ctx.db, stmt, params, scalars=False)
    now = utcnow()
    show_cost = ctx.can("product:cost:view")
    items = []
    for b, sku, pname, whname in page["items"]:
        d = {c.key: getattr(b, c.key) for c in InventoryBatch.__table__.columns}
        d.update(sku=sku, product_name=pname, warehouse_name=whname, age_days=(now - b.received_at).days)
        if not show_cost:
            d.update(unit_purchase_cost=None, unit_freight_cost=None)
        items.append(d)
    page["items"] = items
    return page


# ------------------------------------------------------------------ 库存单据
def doc_out(ctx: Ctx, doc: StockDocument) -> dict:
    wh_ids = {doc.warehouse_id, doc.to_warehouse_id} - {None}
    whs = dict(ctx.db.execute(select(Warehouse.id, Warehouse.name).where(Warehouse.id.in_(wh_ids))).all())
    pids = {ln.product_id for ln in doc.lines}
    products = {p.id: p for p in ctx.db.execute(select(Product).where(Product.id.in_(pids))).scalars().all()} if pids else {}
    show_cost = ctx.can("product:cost:view")
    d = {c.key: getattr(doc, c.key) for c in StockDocument.__table__.columns}
    d["warehouse_name"] = whs.get(doc.warehouse_id)
    d["to_warehouse_name"] = whs.get(doc.to_warehouse_id)
    d["total_qty"] = sum(ln.qty for ln in doc.lines)
    d["lines"] = [
        {
            "id": ln.id, "product_id": ln.product_id,
            "sku": products[ln.product_id].sku if ln.product_id in products else None,
            "product_name": products[ln.product_id].name if ln.product_id in products else None,
            "qty": ln.qty, "unit_cost": ln.unit_cost if show_cost else None,
            "unit_freight_cost": ln.unit_freight_cost if show_cost else None,
            "qty_received": ln.qty_received, "system_qty": ln.system_qty, "counted_qty": ln.counted_qty,
            "remark": ln.remark,
        }
        for ln in doc.lines
    ]
    return d


@router.get("/stock-documents", response_model=Page[StockDocOut], summary="库存单据列表")
def list_documents(
    keyword: str | None = None,
    doc_type: str | None = None,
    status: str | None = None,
    warehouse_id: int | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("inventory:doc:view")),
):
    stmt = select(StockDocument).order_by(StockDocument.id.desc())
    stmt = keyword_filter(stmt, keyword, [StockDocument.doc_no, StockDocument.remark, StockDocument.tracking_no])
    if doc_type:
        stmt = stmt.where(StockDocument.doc_type == doc_type)
    if status:
        stmt = stmt.where(StockDocument.status == status)
    if warehouse_id:
        stmt = stmt.where((StockDocument.warehouse_id == warehouse_id) | (StockDocument.to_warehouse_id == warehouse_id))
    page = paginate(ctx.db, stmt, params)
    page["items"] = [doc_out(ctx, d) for d in page["items"]]
    return page


@router.get("/stock-documents/{doc_id}", response_model=StockDocOut, summary="库存单据详情")
def get_document(doc_id: int, ctx: Ctx = Depends(perm("inventory:doc:view"))):
    return doc_out(ctx, get_or_404(ctx.db, StockDocument, doc_id, "库存单据"))


@router.post("/stock-documents", response_model=StockDocOut, summary="新建库存单据")
def create_document(body: StockDocIn, ctx: Ctx = Depends(perm("inventory:doc:edit"))):
    return doc_out(ctx, service.create_document(ctx, body.model_dump()))


@router.put("/stock-documents/{doc_id}", response_model=StockDocOut, summary="修改库存单据")
def update_document(doc_id: int, body: StockDocUpdate, ctx: Ctx = Depends(perm("inventory:doc:edit"))):
    return doc_out(ctx, service.update_document(ctx, doc_id, body.model_dump(exclude_unset=True)))


@router.post("/stock-documents/{doc_id}/submit", response_model=StockDocOut, summary="提交审核")
def submit_document(doc_id: int, ctx: Ctx = Depends(perm("inventory:doc:edit"))):
    return doc_out(ctx, service.submit_document(ctx, doc_id))


@router.post("/stock-documents/{doc_id}/approve", response_model=StockDocOut, summary="审核过账")
def approve_document(doc_id: int, ctx: Ctx = Depends(perm("inventory:doc:approve"))):
    return doc_out(ctx, service.approve_document(ctx, doc_id))


@router.post("/stock-documents/{doc_id}/receive", response_model=StockDocOut, summary="调拨签收")
def receive_transfer(doc_id: int, body: TransferReceiveIn, ctx: Ctx = Depends(perm("inventory:doc:approve"))):
    lines = [ln.model_dump() for ln in body.lines] if body.lines else None
    return doc_out(ctx, service.receive_transfer(ctx, doc_id, lines))


@router.post("/stock-documents/{doc_id}/cancel", response_model=StockDocOut, summary="作废")
def cancel_document(doc_id: int, ctx: Ctx = Depends(perm("inventory:doc:edit"))):
    return doc_out(ctx, service.cancel_document(ctx, doc_id))


