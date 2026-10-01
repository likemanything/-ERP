"""仓储作业：拣货波次、拣货单、装箱单、扫码验货发货、运单号导入、标签打印。"""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import func, select

from app.common.audit import audit
from app.common.crud import get_or_404
from app.common.enums import OrderStatus
from app.common.excel import read_upload, template_response
from app.common.pagination import PageParams, page_params, paginate
from app.common.pdf import LABEL_SIZES, pdf_response
from app.common.schemas import Page
from app.core.deps import Ctx, perm
from app.core.errors import BizError
from app.modules.fba.models import FbaShipment
from app.modules.fulfillment import printing, service
from app.modules.fulfillment.models import PickWave
from app.modules.fulfillment.schemas import (
    LabelPrintIn,
    PackingSlipIn,
    PickedIn,
    ScanOrderOut,
    ScanShipIn,
    WaveCreateIn,
    WaveCreateOut,
    WaveDetailOut,
    WaveOrdersIn,
    WaveOut,
)
from app.modules.logistics.models import LogisticsChannel
from app.modules.order.models import SalesOrder
from app.modules.product.schemas import ImportResult
from app.modules.shop.models import Shop
from app.modules.system.models import Tenant, User
from app.modules.warehouse.models import Warehouse

router = APIRouter(tags=["仓储作业与打印"])


def _names(db, model, ids, attr="name") -> dict:
    ids = {i for i in ids if i}
    return dict(db.execute(select(model.id, getattr(model, attr)).where(model.id.in_(ids))).all()) if ids else {}


def wave_out(ctx: Ctx, waves) -> list[dict]:
    waves = list(waves)
    db = ctx.db
    whs = _names(db, Warehouse, [w.warehouse_id for w in waves])
    users = _names(db, User, [w.picker_id for w in waves], "real_name")
    ids = [w.id for w in waves]
    shipped = dict(db.execute(
        select(SalesOrder.wave_id, func.count()).where(SalesOrder.wave_id.in_(ids), SalesOrder.status == OrderStatus.SHIPPED)
        .group_by(SalesOrder.wave_id)).all()) if ids else {}
    return [{**{c.key: getattr(w, c.key) for c in PickWave.__table__.columns}, "warehouse_name": whs.get(w.warehouse_id),
             "picker_name": users.get(w.picker_id), "shipped_count": shipped.get(w.id, 0)} for w in waves]


def _company(ctx: Ctx) -> str | None:
    t = ctx.db.get(Tenant, ctx.tenant_id)
    return t.name if t else None


# ================================================================ 拣货波次
@router.get("/fulfillment/waves", response_model=Page[WaveOut], summary="拣货波次列表")
def list_waves(status: str | None = None, warehouse_id: int | None = None, keyword: str | None = None,
               params: PageParams = Depends(page_params), ctx: Ctx = Depends(perm("order:view"))):
    stmt = select(PickWave).order_by(PickWave.id.desc())
    if status:
        stmt = stmt.where(PickWave.status.in_(status.split(",")))
    if warehouse_id:
        stmt = stmt.where(PickWave.warehouse_id == warehouse_id)
    if keyword:
        sub = select(SalesOrder.wave_id).where(SalesOrder.order_no.ilike(f"%{keyword}%")
                                               | SalesOrder.platform_order_id.ilike(f"%{keyword}%"))
        stmt = stmt.where(PickWave.wave_no.ilike(f"%{keyword}%") | PickWave.id.in_(sub))
    page = paginate(ctx.db, stmt, params)
    page["items"] = wave_out(ctx, page["items"])
    return page


@router.post("/fulfillment/waves", response_model=WaveCreateOut, summary="生成拣货波次（按发货仓自动分组）")
def create_waves(body: WaveCreateIn, ctx: Ctx = Depends(perm("order:ship"))):
    res = service.create_waves(ctx, order_ids=body.order_ids, warehouse_id=body.warehouse_id,
                               max_orders=body.max_orders, remark=body.remark)
    return {"waves": wave_out(ctx, res["waves"]), "skipped": res["skipped"]}


@router.get("/fulfillment/waves/{wave_id}", response_model=WaveDetailOut, summary="波次详情（拣货汇总 + 订单）")
def get_wave(wave_id: int, ctx: Ctx = Depends(perm("order:view"))):
    wave = service.get_wave(ctx.db, wave_id)
    orders = service.wave_orders(ctx.db, wave.id)
    shops = _names(ctx.db, Shop, [o.shop_id for o in orders])
    data = wave_out(ctx, [wave])[0]
    data["lines"] = service.pick_lines(ctx.db, wave, orders)
    data["orders"] = [{"id": o.id, "order_no": o.order_no, "platform_order_id": o.platform_order_id,
                       "shop_name": shops.get(o.shop_id), "status": o.status, "ship_name": o.ship_name,
                       "ship_country": o.ship_country, "tracking_no": o.tracking_no,
                       "units": sum(int(x["qty"]) for x in (o.stock_plan or []))} for o in orders]
    return data


@router.post("/fulfillment/waves/{wave_id}/picked", response_model=WaveOut, summary="标记拣货完成")
def wave_picked(wave_id: int, body: PickedIn, ctx: Ctx = Depends(perm("order:ship"))):
    return wave_out(ctx, [service.mark_picked(ctx, wave_id, body.picker_id)])[0]


@router.post("/fulfillment/waves/{wave_id}/complete", response_model=WaveOut, summary="完成波次")
def wave_complete(wave_id: int, ctx: Ctx = Depends(perm("order:ship"))):
    return wave_out(ctx, [service.complete_wave(ctx, wave_id)])[0]


@router.post("/fulfillment/waves/{wave_id}/cancel", response_model=WaveOut, summary="取消波次（订单退回待发货）")
def wave_cancel(wave_id: int, ctx: Ctx = Depends(perm("order:ship"))):
    return wave_out(ctx, [service.cancel_wave(ctx, wave_id)])[0]


@router.post("/fulfillment/waves/{wave_id}/remove-orders", response_model=WaveOut, summary="从波次移出订单（如缺货）")
def wave_remove_orders(wave_id: int, body: WaveOrdersIn, ctx: Ctx = Depends(perm("order:ship"))):
    return wave_out(ctx, [service.remove_orders(ctx, wave_id, body.order_ids)])[0]


@router.get("/fulfillment/waves/{wave_id}/pick-list.pdf", summary="打印拣货单（PDF）")
def wave_pick_list(wave_id: int, ctx: Ctx = Depends(perm("order:view"))):
    wave = service.get_wave(ctx.db, wave_id)
    orders = service.wave_orders(ctx.db, wave.id)
    content = printing.pick_list_pdf(ctx.db, wave, service.pick_lines(ctx.db, wave, orders), orders)
    wave.print_count += 1
    ctx.db.commit()
    return pdf_response(content, f"拣货单_{wave.wave_no}.pdf")


@router.get("/fulfillment/waves/{wave_id}/packing-slips.pdf", summary="打印波次装箱单（PDF）")
def wave_packing_slips(wave_id: int, size: str = "a4", ctx: Ctx = Depends(perm("order:view"))):
    wave = service.get_wave(ctx.db, wave_id)
    orders = [o for o in service.wave_orders(ctx.db, wave.id) if o.status != OrderStatus.CANCELLED]
    content = printing.packing_slips_pdf(ctx.db, orders, company=_company(ctx), size=size)
    return pdf_response(content, f"装箱单_{wave.wave_no}.pdf")


@router.post("/fulfillment/packing-slips.pdf", summary="按订单打印装箱单（PDF）")
def packing_slips(body: PackingSlipIn, ctx: Ctx = Depends(perm("order:view"))):
    orders = ctx.db.execute(select(SalesOrder).where(SalesOrder.id.in_(body.order_ids))).scalars().all()
    for o in orders:
        ctx.require_shop(o.shop_id)
    index = {oid: i for i, oid in enumerate(body.order_ids)}
    orders = sorted(orders, key=lambda o: index.get(o.id, 0))
    return pdf_response(printing.packing_slips_pdf(ctx.db, orders, company=_company(ctx), size=body.size), "装箱单.pdf")


# ================================================================ 扫码验货发货
def _scan_out(ctx: Ctx, o: SalesOrder) -> dict:
    db = ctx.db
    wave = db.get(PickWave, o.wave_id) if o.wave_id else None
    return {
        "id": o.id, "order_no": o.order_no, "platform_order_id": o.platform_order_id,
        "shop_name": _names(db, Shop, [o.shop_id]).get(o.shop_id), "status": o.status, "is_on_hold": o.is_on_hold,
        "hold_reason": o.hold_reason, "ship_name": o.ship_name, "ship_country": o.ship_country,
        "ship_address1": o.ship_address1,
        "logistics_channel_name": _names(db, LogisticsChannel, [o.logistics_channel_id]).get(o.logistics_channel_id),
        "carrier": o.carrier, "tracking_no": o.tracking_no, "est_freight": float(o.est_freight or 0),
        "buyer_note": o.buyer_note, "wave_no": wave.wave_no if wave else None, "lines": service.scan_codes(db, o),
    }


@router.get("/fulfillment/scan", response_model=ScanOrderOut, summary="扫描单号查找待验货订单")
def scan(code: str, ctx: Ctx = Depends(perm("order:view"))):
    return _scan_out(ctx, service.find_order_by_code(ctx, code))


@router.post("/fulfillment/scan-ship", response_model=ScanOrderOut, summary="验货完成后发货")
def scan_ship(body: ScanShipIn, ctx: Ctx = Depends(perm("order:ship"))):
    from app.modules.integration.service import push_tracking
    from app.modules.order.service import batch, ship_order

    order = get_or_404(ctx.db, SalesOrder, body.order_id, "订单")
    if order.is_on_hold:
        raise BizError(f"订单已挂起：{order.hold_reason or ''}，请先处理")
    res = batch(ctx, [order.id], lambda o: ship_order(ctx, o, body.model_dump()), "发货")
    if res["failed"]:
        raise BizError(res["failed"][0]["message"])
    order = ctx.db.get(SalesOrder, order.id)
    if order.fulfillment == "FBM":
        push_tracking(ctx, order)
        ctx.db.commit()
    return _scan_out(ctx, order)


# ================================================================ 运单号导入
@router.get("/fulfillment/tracking-template", summary="运单号导入模板")
def tracking_template(_: Ctx = Depends(perm("order:view"))):
    return template_response("运单号导入模板.xlsx", service.TRACKING_COLUMNS,
                             {"order": "SO2610010001", "carrier": "UPS", "tracking_no": "1Z999AA10123456784",
                              "actual_freight": 35.5, "ship": "Y"})


@router.post("/fulfillment/tracking-import", response_model=ImportResult, summary="导入运单号（可同时发货）")
def tracking_import(file: UploadFile = File(...), ship: bool = Form(True), ctx: Ctx = Depends(perm("order:ship"))):
    from app.modules.integration.service import push_tracking

    rows = read_upload(file, service.TRACKING_COLUMNS, max_rows=10000)
    result, shipped = service.import_tracking(ctx, rows, ship)
    for oid in shipped:
        order = ctx.db.get(SalesOrder, oid)
        if order is not None and order.fulfillment == "FBM":
            push_tracking(ctx, order)
    ctx.db.commit()
    return result


# ================================================================ 标签
@router.get("/print/label-sizes", summary="可用标签规格")
def label_sizes(_: Ctx = Depends(perm("product:view"))):
    return [{"value": s.key, "label": s.name, "sheet": s.sheet, "per_page": s.cols * s.rows} for s in LABEL_SIZES.values()]


@router.post("/print/labels.pdf", summary="打印 FNSKU / SKU / 商品条码标签（PDF）")
def print_labels(body: LabelPrintIn, ctx: Ctx = Depends(perm("product:view"))):
    content = printing.print_labels(ctx.db, [i.model_dump() for i in body.items], body.kind, body.size,
                                    condition=body.condition, extra=body.extra, skip=body.skip)
    audit(ctx, "print", "label", None, f"打印 {body.kind} 标签 {sum(i.qty for i in body.items)} 张")
    ctx.db.commit()
    return pdf_response(content, f"{body.kind}_labels.pdf")


@router.get("/print/fba-shipments/{shipment_id}/fnsku-labels.pdf", summary="打印货件 FNSKU 标签（按发货数量）")
def shipment_fnsku_labels(shipment_id: int, size: str = "60x30", skip: int = 0, extra: str | None = None,
                          ctx: Ctx = Depends(perm("fba:shipment:view"))):
    shipment = get_or_404(ctx.db, FbaShipment, shipment_id, "货件")
    ctx.require_shop(shipment.shop_id)
    items = printing.shipment_label_items(ctx.db, shipment)
    content = printing.print_labels(ctx.db, items, "fnsku", size, condition="New", extra=extra, skip=skip)
    return pdf_response(content, f"FNSKU_{shipment.shipment_no}.pdf")


@router.get("/print/fba-shipments/{shipment_id}/carton-labels.pdf", summary="打印货件箱唛（每箱一张）")
def shipment_carton_labels(shipment_id: int, size: str = "100x100", ctx: Ctx = Depends(perm("fba:shipment:view"))):
    shipment = get_or_404(ctx.db, FbaShipment, shipment_id, "货件")
    ctx.require_shop(shipment.shop_id)
    content = printing.carton_labels(ctx.db, shipment, company=_company(ctx), size=size)
    return pdf_response(content, f"箱唛_{shipment.shipment_no}.pdf")

