"""打印模板：拣货单、装箱单（发货清单）、FNSKU / SKU 标签、FBA 箱唛。"""

from __future__ import annotations

from collections import defaultdict

from reportlab.lib.pagesizes import A4
from reportlab.platypus import PageBreak, Spacer, Table, TableStyle
from sqlalchemy import select

from app.common.pdf import (
    BarcodeFlowable,
    CartonLabel,
    LabelItem,
    carton_labels_pdf,
    doc_pdf,
    grid,
    labels_pdf,
    mm,
    p,
)
from app.core.errors import BizError
from app.core.types import utcnow
from app.modules.fba.models import FbaShipment
from app.modules.fulfillment.models import PickWave
from app.modules.order.models import SalesOrder
from app.modules.product.models import Listing, Product
from app.modules.warehouse.models import Warehouse

ORDER_STATUS_CN = {"to_ship": "待发货", "shipped": "已发货", "cancelled": "已取消", "to_audit": "待审核", "delivered": "已签收"}


def _header(title: str, code: str, info: list[tuple[str, object]], width: float) -> Table:
    left = [p(title, 16)] + [p(f"{k}{': ' if k.isascii() else '：'}{v if v not in (None, '') else '-'}", 9) for k, v in info]
    left_tbl = Table([[x] for x in left], colWidths=[width * 0.58])
    left_tbl.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 1),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    t = Table([[left_tbl, BarcodeFlowable(code, width * 0.4, 14 * mm)]], colWidths=[width * 0.6, width * 0.4])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return t


# ================================================================ 拣货单
def pick_list_pdf(db, wave: PickWave, lines: list[dict], orders: list[SalesOrder]) -> bytes:
    width = A4[0] - 24 * mm
    wh = db.get(Warehouse, wave.warehouse_id)
    active = [o for o in orders if o.status != "cancelled"]
    story: list = [
        _header("拣货单 Pick List", wave.wave_no, [
            ("仓库", wh.name if wh else wave.warehouse_id), ("订单数", len(active)),
            ("SKU 数 / 件数", f"{len(lines)} / {sum(x['qty'] for x in lines)}"),
            ("打印时间", utcnow().strftime("%Y-%m-%d %H:%M UTC")),
        ], width),
        Spacer(1, 4 * mm),
    ]
    data = [["#", "库位", "SKU / 品名", "数量", "订单分布", "√"]]
    for idx, ln in enumerate(lines, 1):
        dist = "，".join(f"{x['order_no']}×{x['qty']}" for x in ln["orders"][:12])
        if len(ln["orders"]) > 12:
            dist += f" 等 {len(ln['orders'])} 单"
        data.append([str(idx), p(ln["bin_code"] or "-", 10), p(f"{ln['sku']} / {ln['name']}", 9),
                     p(str(ln["qty"]), 13, align=1), p(dist, 7), "□"])
    story.append(grid(data, [8 * mm, 22 * mm, width - 8 * mm - 22 * mm - 16 * mm - 55 * mm - 8 * mm, 16 * mm, 55 * mm, 8 * mm], zebra=True))
    # 二次分拣：按订单列出
    story += [Spacer(1, 6 * mm), p("按订单分拣 Sorting by order", 11), Spacer(1, 2 * mm)]
    data = [["#", "系统单号", "平台单号", "收件人 / 国家", "商品", "状态"]]
    products = {x["product_id"]: x["sku"] for x in lines}
    for idx, o in enumerate(orders, 1):
        agg: dict[int, int] = defaultdict(int)
        for pl in o.stock_plan or []:
            agg[pl["product_id"]] += int(pl["qty"])
        items = "，".join(f"{products.get(pid, pid)}×{q}" for pid, q in agg.items())
        data.append([str(idx), p(o.order_no, 8), p(o.platform_order_id, 8), p(f"{o.ship_name or '-'} / {o.ship_country or '-'}", 8),
                     p(items, 8), p(ORDER_STATUS_CN.get(o.status, o.status), 8)])
    story.append(grid(data, [8 * mm, 32 * mm, 36 * mm, 36 * mm, width - 8 * mm - 32 * mm - 36 * mm - 36 * mm - 16 * mm, 16 * mm]))
    return doc_pdf(story, title=f"拣货单 {wave.wave_no}", footer=f"波次 {wave.wave_no}")


# ================================================================ 装箱单 / 发货清单
def packing_slips_pdf(db, orders: list[SalesOrder], *, company: str | None, size: str = "a4") -> bytes:
    """每单一页的装箱单（不显示价格）。分销一件代发订单自动使用中性单据（不显示我方公司名）。"""
    if not orders:
        raise BizError("没有可打印的订单")
    if size == "100x150":
        pagesize, margin, base = (100 * mm, 150 * mm), 5, 7.5
    else:
        pagesize, margin, base = A4, 14, 9.5
    width = pagesize[0] - 2 * margin * mm
    pids = {pl["product_id"] for o in orders for pl in (o.stock_plan or [])}
    pids |= {i.product_id for o in orders for i in o.items if i.product_id}
    products = {x.id: x for x in db.execute(select(Product).where(Product.id.in_(pids))).scalars().all()} if pids else {}
    story: list = []
    for n, o in enumerate(orders):
        neutral = bool(o.distributor_id) and o.distribution_type == "dropship"
        title = "PACKING SLIP" if neutral or not company else f"{company}  PACKING SLIP"
        story.append(_header(title, o.order_no, [
            ("Order", o.platform_order_id), ("Date", o.purchase_at.strftime("%Y-%m-%d") if o.purchase_at else "-"),
            ("Ship via", " ".join(x for x in (o.carrier, o.tracking_no) if x) or "-"),
        ], width))
        story.append(Spacer(1, 3 * mm))
        addr = [o.ship_name, o.ship_phone, o.ship_address1, o.ship_address2,
                " ".join(x for x in (o.ship_city, o.ship_state, o.ship_postcode) if x), o.ship_country]
        story.append(grid([[p("SHIP TO", base)], [p(" / ".join(x for x in addr if x), base + 1)]], [width], font_size=base))
        story.append(Spacer(1, 3 * mm))
        data = [["#", "SKU", "Description", "Qty"]]
        for idx, it in enumerate(o.items, 1):
            prod = products.get(it.product_id)
            sku = it.sku or (prod.sku if prod else None) or it.msku
            desc = it.title or (prod.name_en or prod.name if prod else "") or "-"
            data.append([str(idx), p(sku, base), p(desc, base - 0.5), p(str(it.quantity), base + 2, align=1)])
        units = sum(i.quantity for i in o.items)
        data.append(["", "", p("Total units", base), p(str(units), base + 2, align=1)])
        story.append(grid(data, [8 * mm, width * 0.28, width - 8 * mm - width * 0.28 - 16 * mm, 16 * mm], font_size=base))
        note = o.buyer_note if not neutral else None
        if note:
            story += [Spacer(1, 3 * mm), p(f"Note: {note}", base)]
        story += [Spacer(1, 6 * mm), p("Thank you for your order!", base, align=1)]
        if n < len(orders) - 1:
            story.append(PageBreak())
    return doc_pdf(story, pagesize=pagesize, margin_mm=margin, title="装箱单")


# ================================================================ 标签
def label_items(db, items: list[dict], kind: str, *, condition: str | None, extra: str | None) -> list[LabelItem]:
    """kind=fnsku：按 Listing 的 FNSKU；sku：按产品 SKU；barcode：按产品条码；也可直接传 code。"""
    out: list[LabelItem] = []
    for it in items:
        qty = int(it.get("qty") or 0)
        if qty <= 0:
            continue
        code, title = it.get("code"), it.get("title")
        if not code and it.get("listing_id"):
            lst = db.get(Listing, it["listing_id"])
            if lst is None:
                raise BizError(f"Listing 不存在（ID={it['listing_id']}）")
            if kind == "fnsku":
                code = lst.fnsku
                if not code:
                    raise BizError(f"{lst.msku} 没有 FNSKU，请先同步 Listing 或手工填写")
            else:
                prod = db.get(Product, lst.product_id) if lst.product_id else None
                if prod is None:
                    raise BizError(f"{lst.msku} 未配对本地产品")
                code = prod.barcode if kind == "barcode" else prod.sku
            title = title or lst.title
        if not code and it.get("product_id"):
            prod = db.get(Product, it["product_id"])
            if prod is None:
                raise BizError(f"产品不存在（ID={it['product_id']}）")
            code = prod.barcode if kind == "barcode" else prod.sku
            if not code:
                raise BizError(f"{prod.sku} 未维护商品条码")
            title = title or prod.name_en or prod.name
        if not code:
            raise BizError("缺少条码内容")
        lines = [title] if title else []
        tail = "   ".join(x for x in (condition, extra) if x)
        if tail:
            lines.append(tail)
        out.append(LabelItem(code=str(code).strip(), lines=lines, copies=qty))
    return out


def print_labels(db, items: list[dict], kind: str, size: str, *, condition: str | None, extra: str | None,
                 skip: int = 0) -> bytes:
    return labels_pdf(label_items(db, items, kind, condition=condition, extra=extra), size, skip=skip)


def shipment_label_items(db, shipment: FbaShipment) -> list[dict]:
    return [{"listing_id": ln.listing_id, "code": ln.fnsku, "title": None if ln.listing_id else ln.msku, "qty": ln.qty_shipped}
            for ln in shipment.lines]


def carton_labels(db, shipment: FbaShipment, *, company: str | None, size: str = "100x100") -> bytes:
    """FBA / 海外仓箱唛：按装箱信息每箱一张；未录入装箱信息时按箱数打印汇总内容。"""
    src = db.get(Warehouse, shipment.ship_from_warehouse_id)
    dst = db.get(Warehouse, shipment.to_warehouse_id)
    code = shipment.platform_shipment_id or shipment.shipment_no
    ship_to = " ".join(x for x in (shipment.destination_fc, dst.name if dst else None) if x)
    ship_from = " ".join(x for x in (company, src.name if src else None) if x)
    boxes = shipment.boxes or []
    labels: list[CartonLabel] = []
    if boxes:
        total = len(boxes)
        for idx, b in enumerate(boxes, 1):
            raw = str(b.get("box_no") or "").strip()
            box_no = int(raw) if raw.isdigit() else idx
            dims = "x".join(str(b.get(k) or 0) for k in ("length_cm", "width_cm", "height_cm"))
            contents = [(str(x.get("msku") or x.get("sku") or "-"), int(x.get("qty") or 0)) for x in b.get("items") or []]
            labels.append(CartonLabel(barcode=f"{code}U{box_no:06d}", title=code, box_no=box_no, box_total=total,
                                      ship_from=ship_from, ship_to=ship_to, weight_kg=float(b.get("weight_kg") or 0) or None,
                                      dims_cm=dims if dims != "0x0x0" else None, contents=contents))
    else:
        total = shipment.box_count or 0
        if total <= 0:  # 未录入箱数：按产品单箱数量估算
            per_carton = {p.id: p.units_per_carton for p in db.execute(
                select(Product).where(Product.id.in_({ln.product_id for ln in shipment.lines}))).scalars().all()}
            total = sum(-(-ln.qty_shipped // per_carton[ln.product_id]) if per_carton.get(ln.product_id) else 0
                        for ln in shipment.lines) or 1
        contents = [(ln.msku or ln.fnsku or "-", ln.qty_shipped) for ln in shipment.lines]
        per_box = float(shipment.total_weight_kg or 0) / total if shipment.total_weight_kg else None
        labels = [CartonLabel(barcode=f"{code}U{i:06d}", title=code, box_no=i, box_total=total, ship_from=ship_from,
                              ship_to=ship_to, weight_kg=per_box, contents=contents, footer="MIXED" if len(contents) > 1 else "")
                  for i in range(1, total + 1)]
    w, h = (100, 150) if size == "100x150" else (100, 100)
    return carton_labels_pdf(labels, width_mm=w, height_mm=h)
