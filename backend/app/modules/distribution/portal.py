"""分销商门户 API（/api/v1/portal）。

认证方式（二选一）：
* 分销商登录账号的 Bearer Token（门户页面使用）
* 请求头 ``X-Api-Key: dk_xxx``（分销商自有系统对接，如批量推单）

门户接口只返回分销商自己的数据，绝不返回成本、内部库存明细等敏感信息。
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Depends, File, Header, Request, UploadFile
from sqlalchemy import func, select

from app.common.excel import export_xlsx, read_upload, template_response
from app.common.pagination import PageParams, page_params, paginate
from app.common.schemas import Msg, Page
from app.core.db import get_db
from app.core.deps import Ctx, _load_ctx, oauth2_scheme
from app.core.errors import BizError, Forbidden, Unauthorized
from app.modules.distribution import service
from app.modules.distribution.models import (
    DistributionProduct,
    Distributor,
    DistributorTransaction,
    RechargeRequest,
)
from app.modules.distribution.schemas import (
    PortalCatalogItem,
    PortalMe,
    PortalOrderIn,
    PortalOrderOut,
    QuoteIn,
    QuoteOut,
    RechargeIn,
    RechargeOut,
    StatementOut,
    TxnOut,
)
from app.modules.logistics.models import LogisticsChannel
from app.modules.order.models import SalesOrder
from app.modules.product.models import Category, Product
from app.modules.product.schemas import ImportResult
from app.modules.system.models import Tenant, User
from app.modules.system.service import get_setting

router = APIRouter(prefix="/portal", tags=["分销商门户"])


class _PortalUser:
    """以分销商身份执行业务操作时的操作人（用于操作日志）。"""

    is_superuser = False
    all_shops = False
    user_type = "distributor"
    token_version = 0

    def __init__(self, user: User | None, d: Distributor):
        self.id = user.id if user else None
        self.username = f"{user.username}（分销商 {d.code}）" if user else f"API（分销商 {d.code}）"
        self.real_name = user.real_name if user else d.name


@dataclass
class PortalCtx:
    ctx: Ctx
    distributor: Distributor
    user: User | None
    via_api_key: bool = False

    @property
    def db(self):
        return self.ctx.db


def get_portal_ctx(
    request: Request,
    db=Depends(get_db),
    token: str | None = Depends(oauth2_scheme),
    x_api_key: str | None = Header(default=None),
) -> PortalCtx:
    user = None
    if x_api_key:
        d = service.find_by_api_key(db, x_api_key)
        if d is None:
            raise Unauthorized("API Key 无效或已停用")
        db.info["tenant_id"] = d.tenant_id
        db.info["user_id"] = None
        tenant = db.get(Tenant, d.tenant_id)
        if tenant is None or not tenant.is_active:
            raise Unauthorized("企业账号已停用")
    else:
        base = _load_ctx(request, db, token)
        if base.user.user_type != "distributor" or not base.user.distributor_id:
            raise Forbidden("仅分销商账号可访问分销门户")
        user = base.user
        d = db.get(Distributor, user.distributor_id)
    if d is None or d.status != "active":
        raise Forbidden("分销商账户已停用，请联系客户经理")
    ctx = Ctx(db=db, user=_PortalUser(user, d), tenant_id=d.tenant_id, permissions=frozenset(), shop_ids=None,
              ip=request.client.host if request.client else None)
    return PortalCtx(ctx=ctx, distributor=d, user=user, via_api_key=bool(x_api_key))


def _distributor_out(d: Distributor) -> dict:
    return {
        "id": d.id, "code": d.code, "name": d.name, "contact": d.contact, "phone": d.phone, "email": d.email,
        "country": d.country, "address": d.address, "currency": d.currency, "balance": d.balance,
        "credit_limit": d.credit_limit, "available_funds": d.available_funds,
        "level_name": d.level.name if d.level else None, "allow_dropship": d.allow_dropship,
        "allow_wholesale": d.allow_wholesale, "has_api_key": bool(d.api_key_hash),
    }


@router.get("/me", response_model=PortalMe, summary="当前分销商信息")
def me(p: PortalCtx = Depends(get_portal_ctx)):
    tenant = p.db.get(Tenant, p.distributor.tenant_id)
    return {"distributor": _distributor_out(p.distributor), "username": p.user.username if p.user else None,
            "real_name": p.user.real_name if p.user else None, "via_api_key": p.via_api_key,
            "company_name": tenant.name if tenant else None}


@router.get("/dashboard", summary="门户首页")
def dashboard(p: PortalCtx = Depends(get_portal_ctx)):
    db, d = p.db, p.distributor
    counts = dict(db.execute(
        select(SalesOrder.status, func.count()).where(SalesOrder.distributor_id == d.id).group_by(SalesOrder.status)
    ).all())
    month_start = date.today().replace(day=1)
    spend = db.execute(
        select(func.coalesce(func.sum(DistributorTransaction.amount), 0)).where(
            DistributorTransaction.distributor_id == d.id, DistributorTransaction.txn_type.in_(["order", "refund"]),
            func.date(DistributorTransaction.created_at) >= month_start)
    ).scalar_one()
    recent = db.execute(
        select(SalesOrder).where(SalesOrder.distributor_id == d.id).order_by(SalesOrder.id.desc()).limit(5)
    ).scalars().all()
    return {
        "distributor": _distributor_out(d),
        "status_counts": counts,
        "month_spend": float(-spend),
        "recent_orders": order_out(p, recent),
        "pending_recharges": db.execute(select(func.count()).select_from(RechargeRequest).where(
            RechargeRequest.distributor_id == d.id, RechargeRequest.status == "pending")).scalar_one(),
    }


# ================================================================ 商品目录
def _catalog_query(keyword: str | None, category_id: int | None):
    stmt = (
        select(DistributionProduct, Product)
        .join(Product, Product.id == DistributionProduct.product_id)
        .where(DistributionProduct.is_active.is_(True))
        .order_by(DistributionProduct.sort, Product.sku)
    )
    if keyword:
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(Product.sku.ilike(kw) | Product.name.ilike(kw) | Product.name_en.ilike(kw) | DistributionProduct.title.ilike(kw))
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    return stmt


def _catalog_rows(p: PortalCtx, rows) -> list[dict]:
    db, d = p.db, p.distributor
    pids = [prod.id for _, prod in rows]
    lp = service.level_price_map(db, pids, d.level_id)
    avail = service.available_qty(db, pids)
    cat_ids = {prod.category_id for _, prod in rows if prod.category_id}
    cats = dict(db.execute(select(Category.id, Category.name).where(Category.id.in_(cat_ids))).all()) if cat_ids else {}
    out = []
    for dp, prod in rows:
        qty = avail.get(prod.id, 0)
        stock: int | None = qty
        if dp.stock_display == "capped":
            stock = min(qty, dp.stock_cap or 0)
        elif dp.stock_display == "status":
            stock = None
        out.append({
            "product_id": prod.id, "sku": prod.sku, "title": dp.title or prod.name, "name_en": prod.name_en,
            "image_url": prod.image_url, "category_name": cats.get(prod.category_id), "weight_kg": prod.weight_kg,
            "length_cm": prod.length_cm, "width_cm": prod.width_cm, "height_cm": prod.height_cm,
            "units_per_carton": prod.units_per_carton or 0, "price": service.unit_price(db, d, dp, lp),
            "currency": d.currency, "min_qty": dp.min_qty, "stock": stock, "in_stock": qty > 0,
            "description": dp.description or prod.description,
        })
    return out


@router.get("/catalog", response_model=Page[PortalCatalogItem], summary="分销商品目录（含您的价格与可售库存）")
def catalog(
    keyword: str | None = None,
    category_id: int | None = None,
    in_stock_only: bool = False,
    params: PageParams = Depends(page_params),
    p: PortalCtx = Depends(get_portal_ctx),
):
    stmt = _catalog_query(keyword, category_id)
    if in_stock_only:
        rows = _catalog_rows(p, p.db.execute(stmt).all())
        rows = [r for r in rows if r["in_stock"]]
        start = params.offset
        return {"items": rows[start:start + params.page_size], "total": len(rows), "page": params.page, "page_size": params.page_size}
    page = paginate(p.db, stmt, params, scalars=False)
    page["items"] = _catalog_rows(p, page["items"])
    return page


@router.get("/catalog/export", summary="导出商品目录")
def export_catalog(p: PortalCtx = Depends(get_portal_ctx)):
    rows = _catalog_rows(p, p.db.execute(_catalog_query(None, None)).all())
    for r in rows:
        r["stock_text"] = r["stock"] if r["stock"] is not None else ("有货" if r["in_stock"] else "缺货")
    cols = [("sku", "SKU"), ("title", "商品名称"), ("name_en", "英文名"), ("category_name", "分类"), ("price", "单价"),
            ("currency", "币种"), ("min_qty", "批发起订量"), ("stock_text", "可售库存"), ("weight_kg", "重量kg"),
            ("length_cm", "长cm"), ("width_cm", "宽cm"), ("height_cm", "高cm"), ("units_per_carton", "单箱数量"), ("image_url", "图片")]
    return export_xlsx("分销商品目录.xlsx", cols, rows)


@router.get("/categories", summary="目录分类")
def categories(p: PortalCtx = Depends(get_portal_ctx)):
    rows = p.db.execute(
        select(Category.id, Category.name).join(Product, Product.category_id == Category.id)
        .join(DistributionProduct, DistributionProduct.product_id == Product.id)
        .where(DistributionProduct.is_active.is_(True)).group_by(Category.id, Category.name).order_by(Category.name)
    ).all()
    return [{"value": i, "label": n} for i, n in rows]


@router.get("/channels", summary="可选物流渠道")
def channels(p: PortalCtx = Depends(get_portal_ctx)):
    return [{"value": c.id, "label": c.name, "transit_days": c.transit_days, "transport_mode": c.transport_mode}
            for c in service.allowed_channels(p.db)]


@router.post("/quote", response_model=QuoteOut, summary="下单前报价（货款 + 运费 + 操作费）")
def quote(body: QuoteIn, p: PortalCtx = Depends(get_portal_ctx)):
    q = service.quote(p.db, p.distributor, [i.model_dump() for i in body.items], body.channel_id, body.order_type)
    q.pop("_lines")
    return q


# ================================================================ 订单
def order_out(p: PortalCtx, orders) -> list[dict]:
    orders = list(orders)
    ch_ids = {o.logistics_channel_id for o in orders if o.logistics_channel_id}
    chs = dict(p.db.execute(select(LogisticsChannel.id, LogisticsChannel.name).where(LogisticsChannel.id.in_(ch_ids))).all()) if ch_ids else {}
    allow_after = bool(get_setting(p.db, "distribution.allow_cancel_after_audit"))
    out = []
    for o in orders:
        can_cancel = o.status in ("pending", "to_audit") or (o.status == "to_ship" and allow_after)
        note = None
        if o.status == "cancelled":
            note = o.cancel_reason
        elif o.status == "to_audit" and "待人工审核" in (o.tags or []):
            note = "等待仓库人工审核"
        out.append({
            "id": o.id, "order_no": o.order_no, "reference_no": o.platform_order_id, "status": o.status,
            "distribution_type": o.distribution_type, "created_at": o.created_at, "shipped_at": o.shipped_at,
            "ship_name": o.ship_name, "ship_phone": o.ship_phone, "ship_country": o.ship_country, "ship_state": o.ship_state,
            "ship_city": o.ship_city, "ship_address1": o.ship_address1, "ship_address2": o.ship_address2,
            "ship_postcode": o.ship_postcode, "channel_name": chs.get(o.logistics_channel_id), "carrier": o.carrier,
            "tracking_no": o.tracking_no, "currency": o.currency, "charge_detail": o.charge_detail, "note": note,
            "can_cancel": can_cancel,
            "items": [{"sku": i.sku, "title": i.title, "quantity": i.quantity, "unit_price": i.unit_price,
                       "item_amount": i.item_amount} for i in o.items],
        })
    return out


@router.get("/orders", response_model=Page[PortalOrderOut], summary="我的订单")
def list_orders(
    status: str | None = None,
    keyword: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    params: PageParams = Depends(page_params),
    p: PortalCtx = Depends(get_portal_ctx),
):
    stmt = select(SalesOrder).where(SalesOrder.distributor_id == p.distributor.id).order_by(SalesOrder.id.desc())
    if status:
        stmt = stmt.where(SalesOrder.status.in_(status.split(",")))
    if keyword:
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(SalesOrder.platform_order_id.ilike(kw) | SalesOrder.order_no.ilike(kw)
                          | SalesOrder.ship_name.ilike(kw) | SalesOrder.tracking_no.ilike(kw))
    if date_from:
        stmt = stmt.where(SalesOrder.local_date >= date_from)
    if date_to:
        stmt = stmt.where(SalesOrder.local_date <= date_to)
    page = paginate(p.db, stmt, params)
    page["items"] = order_out(p, page["items"])
    return page


@router.get("/orders/import-template", summary="订单导入模板")
def import_template(_: PortalCtx = Depends(get_portal_ctx)):
    return template_response("分销订单导入模板.xlsx", IMPORT_COLUMNS, {
        "reference_no": "MY-ORDER-001", "order_type": "dropship", "sku": "SKU-001", "qty": 1, "channel": "USPS 小包",
        "name": "John Smith", "phone": "1-555-0100", "country": "US", "state": "CA", "city": "Los Angeles",
        "address1": "123 Main St", "postcode": "90001",
    })


@router.get("/orders/{order_id}", response_model=PortalOrderOut, summary="订单详情")
def get_order(order_id: int, p: PortalCtx = Depends(get_portal_ctx)):
    o = p.db.execute(select(SalesOrder).where(SalesOrder.id == order_id, SalesOrder.distributor_id == p.distributor.id)).scalar_one_or_none()
    if o is None:
        raise BizError("订单不存在")
    return order_out(p, [o])[0]


@router.post("/orders", response_model=PortalOrderOut, summary="提交订单（实时扣款）")
def create_order(body: PortalOrderIn, p: PortalCtx = Depends(get_portal_ctx)):
    data = body.model_dump()
    data["items"] = [i for i in data["items"]]
    order = service.place_order(p.ctx, p.distributor, data)
    p.db.commit()
    return order_out(p, [order])[0]


@router.post("/orders/{order_id}/cancel", response_model=PortalOrderOut, summary="取消订单（自动退款）")
def cancel_order(order_id: int, p: PortalCtx = Depends(get_portal_ctx)):
    return order_out(p, [service.cancel_by_distributor(p.ctx, p.distributor, order_id)])[0]


IMPORT_COLUMNS = [
    ("reference_no", "订单号"), ("order_type", "类型"), ("sku", "SKU"), ("qty", "数量"), ("channel", "物流渠道"),
    ("name", "收件人"), ("phone", "电话"), ("country", "国家"), ("state", "州/省"), ("city", "城市"),
    ("address1", "地址1"), ("address2", "地址2"), ("postcode", "邮编"), ("remark", "备注"),
]


@router.post("/orders/import", response_model=ImportResult, summary="Excel 批量下单（同订单号多行合并）")
def import_orders(file: UploadFile = File(...), p: PortalCtx = Depends(get_portal_ctx)):
    rows = read_upload(file, IMPORT_COLUMNS, max_rows=5000)
    channels = {c.name: c.id for c in service.allowed_channels(p.db)}
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[str(r.get("reference_no") or f"ROW{r['_row']}").strip()].append(r)
    result = ImportResult()
    for ref, lines in groups.items():
        first = lines[0]
        sp = p.db.begin_nested()
        try:
            ch = first.get("channel")
            channel_id = None
            if ch not in (None, ""):
                channel_id = channels.get(str(ch)) or (int(ch) if str(ch).isdigit() else None)
                if channel_id is None:
                    raise BizError(f"物流渠道不存在：{ch}")
            order_type = str(first.get("order_type") or "dropship").strip().lower()
            order_type = {"一件代发": "dropship", "代发": "dropship", "批发": "wholesale"}.get(order_type, order_type)
            service.place_order(p.ctx, p.distributor, {
                "reference_no": None if ref.startswith("ROW") else ref, "order_type": order_type, "channel_id": channel_id,
                "items": [{"sku": str(x.get("sku") or "").strip(), "qty": int(x.get("qty") or 0)} for x in lines],
                "address": {k: (str(first[k]) if first.get(k) is not None else None)
                            for k in ("name", "phone", "country", "state", "city", "address1", "address2", "postcode")},
                "remark": first.get("remark"),
            })
            sp.commit()
            result.created += 1
        except Exception as exc:  # noqa: BLE001
            sp.rollback()
            result.skipped += 1
            result.errors.append(f"订单 {ref}: {getattr(exc, 'message', None) or exc}")
    p.db.commit()
    return result


# ================================================================ 资金
@router.get("/transactions", response_model=Page[TxnOut], summary="资金流水")
def transactions(txn_type: str | None = None, params: PageParams = Depends(page_params), p: PortalCtx = Depends(get_portal_ctx)):
    T = DistributorTransaction
    stmt = select(T).where(T.distributor_id == p.distributor.id).order_by(T.id.desc())
    if txn_type:
        stmt = stmt.where(T.txn_type == txn_type)
    page = paginate(p.db, stmt, params)
    page["items"] = [{c.key: getattr(t, c.key) for c in T.__table__.columns} for t in page["items"]]
    return page


@router.get("/recharges", response_model=Page[RechargeOut], summary="充值记录")
def recharges(params: PageParams = Depends(page_params), p: PortalCtx = Depends(get_portal_ctx)):
    stmt = select(RechargeRequest).where(RechargeRequest.distributor_id == p.distributor.id).order_by(RechargeRequest.id.desc())
    page = paginate(p.db, stmt, params)
    page["items"] = [{c.key: getattr(r, c.key) for c in RechargeRequest.__table__.columns} for r in page["items"]]
    return page


@router.post("/recharges", response_model=RechargeOut, summary="提交充值申请（线下打款后提交，财务确认后到账）")
def create_recharge(body: RechargeIn, p: PortalCtx = Depends(get_portal_ctx)):
    req = service.create_recharge(p.db, p.distributor, body.model_dump())
    from app.modules.system.models import Notification

    p.db.add(Notification(category="approval", title=f"分销商 {p.distributor.name} 提交充值申请",
                          content=f"{req.amount} {req.currency}，{req.payment_method or ''} {req.transaction_no or ''}",
                          link="/distribution/recharges"))
    p.db.commit()
    return {c.key: getattr(req, c.key) for c in RechargeRequest.__table__.columns}


@router.get("/statement", response_model=StatementOut, summary="对账单")
def statement(date_from: date, date_to: date, p: PortalCtx = Depends(get_portal_ctx)):
    data = service.statement(p.db, p.distributor.id, date_from, date_to)
    data["transactions"] = [{c.key: getattr(t, c.key) for c in DistributorTransaction.__table__.columns} for t in data["transactions"]]
    return data


@router.post("/api-key", summary="生成 / 重置 API Key（仅显示一次）")
def generate_key(p: PortalCtx = Depends(get_portal_ctx)):
    if p.via_api_key:
        raise Forbidden("请登录门户后操作")
    key = service.generate_api_key(p.db, p.distributor)
    p.db.commit()
    return {"api_key": key}


@router.delete("/api-key", response_model=Msg, summary="停用 API Key")
def revoke_key(p: PortalCtx = Depends(get_portal_ctx)):
    if p.via_api_key:
        raise Forbidden("请登录门户后操作")
    p.distributor.api_key_hash = p.distributor.api_key_prefix = None
    p.db.commit()
    return Msg(message="已停用")
