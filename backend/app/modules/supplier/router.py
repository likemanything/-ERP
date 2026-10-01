from fastapi import APIRouter
from sqlalchemy import func, select

from app.common.crud import build_crud_router, ensure_not_referenced
from app.core.deps import Ctx
from app.modules.supplier.models import Supplier
from app.modules.supplier.schemas import SupplierIn, SupplierOut, SupplierUpdate

router = APIRouter(tags=["供应商"])


def _before_save(ctx: Ctx, obj, data: dict) -> None:
    if obj is None and not data.get("code"):
        n = ctx.db.execute(select(func.count()).select_from(Supplier)).scalar_one()
        while True:
            n += 1
            code = f"SUP{n:04d}"
            if not ctx.db.execute(select(Supplier.id).where(Supplier.code == code)).first():
                break
        data["code"] = code
    if data.get("currency"):
        data["currency"] = data["currency"].upper()


def _before_delete(ctx: Ctx, supplier: Supplier) -> None:
    from app.modules.product.models import ProductSupplier
    from app.modules.purchase.models import PurchaseOrder

    ensure_not_referenced(
        ctx.db,
        [
            (PurchaseOrder, PurchaseOrder.supplier_id == supplier.id, "采购单"),
            (ProductSupplier, ProductSupplier.supplier_id == supplier.id, "产品报价"),
        ],
    )


router.include_router(
    build_crud_router(
        model=Supplier,
        create_schema=SupplierIn,
        update_schema=SupplierUpdate,
        out_schema=SupplierOut,
        resource="supplier",
        label="供应商",
        view_perm="supplier:view",
        edit_perm="supplier:edit",
        search_fields=("code", "name", "contact", "phone"),
        filter_fields=("status", "settlement_type", "purchaser_id"),
        unique_fields=("code",),
        option_label=lambda s: f"{s.name}",
        before_save=_before_save,
        before_delete=_before_delete,
    ),
    prefix="/suppliers",
)
