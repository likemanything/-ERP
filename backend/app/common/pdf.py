"""PDF 打印：条码标签、箱唛、拣货单 / 装箱单等文档。

基于 reportlab，使用内置中文 CID 字体（STSong-Light），无需额外安装字体文件；
条码统一使用 Code128（亚马逊 FNSKU 标签要求的码制）。
"""

from __future__ import annotations

import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from urllib.parse import quote

from fastapi.responses import StreamingResponse
from reportlab.graphics.barcode.code128 import Code128
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Table, TableStyle

from app.core.errors import BizError


def _register_font() -> str:
    """优先嵌入配置的 TTF/TTC 字体（打印机/无中文字体的电脑也能正确显示），否则使用内置 CID 字体。"""
    from pathlib import Path

    from reportlab.pdfbase.ttfonts import TTFont

    from app.core.config import settings

    path = settings.pdf_font_path
    if path and Path(path).is_file():
        try:
            pdfmetrics.registerFont(TTFont("ERPFont", path, subfontIndex=0))
            return "ERPFont"
        except Exception:  # noqa: BLE001 - 字体损坏时回退到内置字体
            pass
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light"


FONT = _register_font()


def pdf_response(content: bytes, filename: str, *, inline: bool = True) -> StreamingResponse:
    disposition = "inline" if inline else "attachment"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}"},
    )


def fit_text(text: str, size: float, max_width: float) -> str:
    """按宽度截断文本（超出加省略号）。"""
    text = text or ""
    if pdfmetrics.stringWidth(text, FONT, size) <= max_width:
        return text
    while text and pdfmetrics.stringWidth(text + "…", FONT, size) > max_width:
        text = text[:-1]
    return text + "…"


def wrap_text(text: str, size: float, max_width: float, max_lines: int) -> list[str]:
    """按宽度逐字符折行（兼容中英文），超过行数时末行截断加省略号。"""
    text = text or ""
    lines: list[str] = []
    cur = ""
    for i, ch in enumerate(text):
        if cur and pdfmetrics.stringWidth(cur + ch, FONT, size) > max_width:
            if len(lines) == max_lines - 1:
                return lines + [fit_text(cur + text[i:], size, max_width)]
            carry = ""
            cut = cur.rfind(" ")
            if ch != " " and cut > len(cur) // 2:  # 英文按单词换行
                cur, carry = cur[:cut], cur[cut + 1:]
            lines.append(cur)
            cur = carry if ch == " " else carry + ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def _barcode(value: str, max_width: float, height: float) -> Code128:
    probe = Code128(value, barWidth=1, barHeight=height, quiet=False)
    bar_width = min(0.36 * mm, max_width / probe.width)
    if bar_width < 0.12 * mm:
        raise BizError(f"条码内容过长，无法在标签宽度内清晰打印：{value}")
    return Code128(value, barWidth=bar_width, barHeight=height, quiet=False)


def draw_barcode(c: canvas.Canvas, value: str, cx: float, y: float, max_width: float, height: float) -> None:
    """以 cx 为中心绘制条码，y 为条码底边。"""
    b = _barcode(value, max_width, height)
    b.drawOn(c, cx - b.width / 2, y)


# ================================================================ 条码标签
@dataclass(frozen=True)
class LabelSize:
    key: str
    name: str
    width: float  # mm
    height: float  # mm
    cols: int = 1
    rows: int = 1
    gap_x: float = 0  # mm
    gap_y: float = 0  # mm

    @property
    def sheet(self) -> bool:
        return self.cols * self.rows > 1


LABEL_SIZES: dict[str, LabelSize] = {s.key: s for s in [
    LabelSize("60x30", "60×30mm 热敏标签", 60, 30),
    LabelSize("50x25", "50×25mm 热敏标签", 50, 25),
    LabelSize("70x30", "70×30mm 热敏标签", 70, 30),
    LabelSize("100x30", "100×30mm 热敏标签", 100, 30),
    LabelSize("a4_21", "A4 21 格（63.5×38.1mm）", 63.5, 38.1, 3, 7, 2.5, 0),
    LabelSize("a4_24", "A4 24 格（70×37mm）", 70, 37, 3, 8),
    LabelSize("a4_30", "A4 30 格（70×29.7mm）", 70, 29.7, 3, 10),
    LabelSize("a4_40", "A4 40 格（52.5×29.7mm）", 52.5, 29.7, 4, 10),
    LabelSize("a4_44", "A4 44 格（48.5×25.4mm）", 48.5, 25.4, 4, 11),
]}


@dataclass
class LabelItem:
    code: str
    lines: list[str] = field(default_factory=list)
    copies: int = 1


def _draw_label(c: canvas.Canvas, x: float, y: float, w: float, h: float, item: LabelItem) -> None:
    pad = 1.5 * mm
    inner_w = w - 2 * pad
    small = h < 28 * mm
    code_size = 7 if small else 8
    text_size = 6 if small else 7
    bar_h = h * (0.36 if item.lines else 0.55)
    top = y + h - pad
    bar_y = top - bar_h
    draw_barcode(c, item.code, x + w / 2, bar_y, inner_w, bar_h)
    c.setFont(FONT, code_size)
    cur = bar_y - code_size - 0.5 * mm
    c.drawCentredString(x + w / 2, cur, item.code)
    c.setFont(FONT, text_size)
    lines: list[str] = []
    for i, line in enumerate(item.lines):
        lines += wrap_text(line, text_size, inner_w, 2 if i == 0 and not small else 1)
    for line in lines:
        cur -= text_size + 1
        if cur < y + pad * 0.5:
            break
        c.drawString(x + pad, cur, line)


def labels_pdf(items: Sequence[LabelItem], size_key: str = "60x30", *, skip: int = 0) -> bytes:
    """批量生成条码标签。热敏规格每页一张；A4 规格按格子排版，skip 可跳过已用掉的格子。"""
    size = LABEL_SIZES.get(size_key)
    if size is None:
        raise BizError(f"不支持的标签规格：{size_key}")
    expanded = [it for it in items for _ in range(max(int(it.copies), 0))]
    if not expanded:
        raise BizError("没有需要打印的标签")
    if len(expanded) > 5000:
        raise BizError("单次最多打印 5000 张标签")
    buf = io.BytesIO()
    w, h = size.width * mm, size.height * mm
    if not size.sheet:
        c = canvas.Canvas(buf, pagesize=(w, h))
        for it in expanded:
            _draw_label(c, 0, 0, w, h, it)
            c.showPage()
        c.save()
        return buf.getvalue()

    page_w, page_h = A4
    gap_x, gap_y = size.gap_x * mm, size.gap_y * mm
    grid_w = size.cols * w + (size.cols - 1) * gap_x
    grid_h = size.rows * h + (size.rows - 1) * gap_y
    left, top = (page_w - grid_w) / 2, page_h - (page_h - grid_h) / 2
    per_page = size.cols * size.rows
    c = canvas.Canvas(buf, pagesize=A4)
    slot = skip % per_page
    for it in expanded:
        if slot == per_page:
            c.showPage()
            slot = 0
        row, col = divmod(slot, size.cols)
        x = left + col * (w + gap_x)
        y = top - (row + 1) * h - row * gap_y
        _draw_label(c, x, y, w, h, it)
        slot += 1
    c.showPage()
    c.save()
    return buf.getvalue()


# ================================================================ 箱唛
@dataclass
class CartonLabel:
    barcode: str
    title: str
    box_no: int
    box_total: int
    ship_from: str = ""
    ship_to: str = ""
    weight_kg: float | None = None
    dims_cm: str | None = None
    contents: list[tuple[str, int]] = field(default_factory=list)
    footer: str = ""


def carton_labels_pdf(labels: Iterable[CartonLabel], *, width_mm: float = 100, height_mm: float = 100) -> bytes:
    """箱唛（外箱标签），默认 100×100mm，每箱一张。"""
    buf = io.BytesIO()
    w, h = width_mm * mm, height_mm * mm
    c = canvas.Canvas(buf, pagesize=(w, h))
    pad = 4 * mm
    count = 0
    for lb in labels:
        count += 1
        c.setLineWidth(1)
        c.rect(pad / 2, pad / 2, w - pad, h - pad)
        y = h - pad - 14
        c.setFont(FONT, 16)
        c.drawString(pad, y, fit_text(lb.title, 16, w - 2 * pad - 30 * mm))
        c.setFont(FONT, 20)
        c.drawRightString(w - pad, y - 2, f"{lb.box_no}/{lb.box_total}")
        c.setFont(FONT, 8)
        y -= 14
        for label, value in (("FROM", lb.ship_from), ("TO", lb.ship_to)):
            if value:
                c.drawString(pad, y, fit_text(f"{label}: {value}", 8, w - 2 * pad))
                y -= 11
        meta = []
        if lb.weight_kg:
            meta.append(f"G.W. {lb.weight_kg:.2f} kg")
        if lb.dims_cm:
            meta.append(f"DIM {lb.dims_cm} cm")
        if meta:
            c.drawString(pad, y, "   ".join(meta))
            y -= 11
        c.line(pad, y + 4, w - pad, y + 4)
        y -= 6
        bar_h = 16 * mm
        bottom_limit = pad + bar_h + 14
        c.setFont(FONT, 8)
        shown = 0
        for sku, qty in lb.contents:
            if y < bottom_limit + 10:
                break
            c.drawString(pad, y, fit_text(sku, 8, w - 2 * pad - 18 * mm))
            c.drawRightString(w - pad, y, f"× {qty}")
            y -= 10
            shown += 1
        if shown < len(lb.contents):
            c.drawString(pad, y, f"… +{len(lb.contents) - shown} SKU")
        draw_barcode(c, lb.barcode, w / 2, pad + 10, w - 2 * pad, bar_h)
        c.setFont(FONT, 8)
        c.drawCentredString(w / 2, pad + 2, lb.barcode + (f"   {lb.footer}" if lb.footer else ""))
        c.showPage()
    if not count:
        raise BizError("没有可打印的箱唛")
    c.save()
    return buf.getvalue()


# ================================================================ 文档（拣货单 / 装箱单）
def style(size: float = 9, leading: float | None = None, align: int = 0) -> ParagraphStyle:
    return ParagraphStyle(f"s{size}-{align}", fontName=FONT, fontSize=size, leading=leading or size * 1.35, alignment=align)


def esc(text: object) -> str:
    return str(text if text is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def p(text: object, size: float = 9, align: int = 0) -> Paragraph:
    return Paragraph(esc(text), style(size, align=align))


class BarcodeFlowable(Flowable):
    def __init__(self, value: str, width: float, height: float, *, show_text: bool = True):
        super().__init__()
        self.value, self.max_width, self.bar_height, self.show_text = value, width, height, show_text
        self._bar = _barcode(value, width, height)
        self.width = self._bar.width
        self.height = height + (10 if show_text else 0)

    def draw(self) -> None:
        self._bar.drawOn(self.canv, 0, 10 if self.show_text else 0)
        if self.show_text:
            self.canv.setFont(FONT, 8)
            self.canv.drawCentredString(self.width / 2, 0, self.value)


def grid(data: list[list], col_widths: Sequence[float], *, header: bool = True, font_size: float = 8.5,
         zebra: bool = False) -> Table:
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    cmds = [
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        cmds.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")))
    if zebra:
        cmds += [("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f7f7f7")) for i in range(2 if header else 1, len(data), 2)]
    t.setStyle(TableStyle(cmds))
    return t


def doc_pdf(story: list, *, pagesize=A4, margin_mm: float = 12, title: str = "", footer: str = "") -> bytes:
    buf = io.BytesIO()
    m = margin_mm * mm

    def _decorate(c: canvas.Canvas, doc) -> None:
        c.saveState()
        c.setFont(FONT, 7)
        c.setFillColor(colors.HexColor("#888888"))
        text = f"{footer}  ·  第 {doc.page} 页" if footer else f"第 {doc.page} 页"
        c.drawRightString(pagesize[0] - m, m / 2, text)
        c.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=pagesize, leftMargin=m, rightMargin=m, topMargin=m, bottomMargin=m, title=title)
    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    return buf.getvalue()


__all__ = [
    "A4", "BarcodeFlowable", "CartonLabel", "Drawing", "FONT", "LABEL_SIZES", "LabelItem", "carton_labels_pdf",
    "doc_pdf", "draw_barcode", "esc", "fit_text", "grid", "labels_pdf", "mm", "p", "pdf_response", "style", "wrap_text",
]
