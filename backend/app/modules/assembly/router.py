"""加工单（组装 / 拆分）。"""

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.common.crud import get_or_404
from app.common.pagination import PageParams, page_params, paginate
from app.common.schemas import Msg, Page
from app.core.deps import Ctx, perm
from app.core.errors import BizError
from app.modules.assembly import service
from app.modules.assembly.models import AssemblyOrder
from app.modules.assembly.schemas import AssemblyIn, AssemblyOut, AssemblyUpdate
from app.modules.product.models import Product
from app.modules.warehouse.models import InventoryBalance, Warehouse

router = APIRouter(tags=["加工单"])


def order_out(ctx: Ctx, orders) -> list[dict]:
    orders = list(orders)
    db = ctx.db
    pids = {o.product_id for o in orders} | {ln.product_id for o in orders for ln in o.lines}
    products = {p.id: p for p in db.execute(select(Product).where(Product.id.in_(pids))).scalars().all()} if pids else {}
    whs = dict(db.execute(select(Warehouse.id, Warehouse.name).where(Warehouse.id.in_({o.warehouse_id for o in orders}))).all()) if orders else {}
    avail: dict[tuple[int, int], int] = {}
    drafts = [o for o in orders if o.status == "draft"]
    if drafts:
        rows = db.execute(select(InventoryBalance).where(
            InventoryBalance.warehouse_id.in_({o.warehouse_id for o in drafts}), InventoryBalance.product_id.in_(pids))).scalars().all()
        avail = {(b.warehouse_id, b.product_id): b.qty_available for b in rows}
    show_cost = ctx.can("product:cost:view")
    out = []
    for o in orders:
        p = products.get(o.product_id)
        d = {c.key: getattr(o, c.key) for c in AssemblyOrder.__table__.columns}
        d.update(warehouse_name=whs.get(o.warehouse_id), sku=p.sku if p else None, product_name=p.name if p else None,
                 image_url=p.image_url if p else None)
        if not show_cost:
            d["unit_cost"] = d["total_cost"] = None
        d["lines"] = []
        for ln in o.lines:
            cp = products.get(ln.product_id)
            d["lines"].append({
                "id": ln.id, "product_id": ln.product_id, "sku": cp.sku if cp else None, "name": cp.name if cp else None,
                "image_url": cp.image_url if cp else None, "qty_per_unit": ln.qty_per_unit, "qty": ln.qty,
                "available": avail.get((o.warehouse_id, ln.product_id)) if o.status == "draft" else None,
                "unit_cost": ln.unit_cost if show_cost else None, "amount": ln.amount if show_cost else None,
            })
        out.append(d)
    return out


@router.get("/assembly-orders", response_model=Page[AssemblyOut], summary="加工单列表")
def list_orders(
    keyword: str | None = None,
    status: str | None = None,
    order_type: str | None = None,
    warehouse_id: int | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("inventory:doc:view")),
):
    stmt = select(AssemblyOrder).order_by(AssemblyOrder.id.desc())
    if keyword:
        sub = select(Product.id).where(Product.sku.ilike(f"%{keyword}%") | Product.name.ilike(f"%{keyword}%"))
        stmt = stmt.where(AssemblyOrder.order_no.ilike(f"%{keyword}%") | AssemblyOrder.product_id.in_(sub))
    if status:
        stmt = stmt.where(AssemblyOrder.status == status)
    if order_type:
        stmt = stmt.where(AssemblyOrder.order_type == order_type)
    if warehouse_id:
        stmt = stmt.where(AssemblyOrder.warehouse_id == warehouse_id)
    page = paginate(ctx.db, stmt, params)
    page["items"] = order_out(ctx, page["items"])
    return page


@router.get("/assembly-orders/recipe", summary="成品最近一次加工配方")
def recipe(product_id: int, ctx: Ctx = Depends(perm("inventory:doc:view"))):
    return service.last_recipe(ctx.db, product_id)


@router.get("/assembly-orders/{order_id}", response_model=AssemblyOut, summary="加工单详情")
def get_order(order_id: int, ctx: Ctx = Depends(perm("inventory:doc:view"))):
    return order_out(ctx, [get_or_404(ctx.db, AssemblyOrder, order_id, "加工单")])[0]


@router.post("/assembly-orders", response_model=AssemblyOut, summary="新建加工单")
def create_order(body: AssemblyIn, ctx: Ctx = Depends(perm("inventory:assembly"))):
    return order_out(ctx, [service.create_order(ctx, body.model_dump())])[0]


@router.put("/assembly-orders/{order_id}", response_model=AssemblyOut, summary="修改加工单（草稿）")
def update_order(order_id: int, body: AssemblyUpdate, ctx: Ctx = Depends(perm("inventory:assembly"))):
    return order_out(ctx, [service.update_order(ctx, order_id, body.model_dump(exclude_unset=True))])[0]


@router.post("/assembly-orders/{order_id}/complete", response_model=AssemblyOut, summary="完成加工（扣子件、入成品）")
def complete_order(order_id: int, ctx: Ctx = Depends(perm("inventory:assembly"))):
    return order_out(ctx, [service.complete_order(ctx, order_id)])[0]


@router.post("/assembly-orders/{order_id}/cancel", response_model=AssemblyOut, summary="作废加工单")
def cancel_order(order_id: int, ctx: Ctx = Depends(perm("inventory:assembly"))):
    return order_out(ctx, [service.cancel_order(ctx, order_id)])[0]


@router.delete("/assembly-orders/{order_id}", response_model=Msg, summary="删除草稿加工单")
def delete_order(order_id: int, ctx: Ctx = Depends(perm("inventory:assembly"))):
    order = get_or_404(ctx.db, AssemblyOrder, order_id, "加工单")
    if order.status != "draft":
        raise BizError("只能删除草稿加工单")
    ctx.db.delete(order)
    ctx.db.commit()
    return Msg(message="已删除")
