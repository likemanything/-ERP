"""分销管理（后台）。"""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.common.audit import audit
from app.common.crud import build_crud_router, ensure_not_referenced, get_or_404, keyword_filter
from app.common.excel import export_xlsx
from app.common.pagination import PageParams, page_params, paginate
from app.common.schemas import Msg, Option, Page
from app.core.deps import Ctx, perm
from app.core.errors import BizError
from app.core.security import hash_password
from app.core.types import q2, utcnow
from app.modules.distribution import service
from app.modules.distribution.models import (
    DistributionLevelPrice,
    DistributionProduct,
    Distributor,
    DistributorLevel,
    DistributorTransaction,
    RechargeRequest,
)
from app.modules.distribution.schemas import (
    AdjustIn,
    CatalogOut,
    CatalogUpsertIn,
    ChargeAdjustIn,
    DistributionSettings,
    DistributorIn,
    DistributorOut,
    DistributorUpdate,
    LevelIn,
    LevelOut,
    LevelPricesIn,
    LevelUpdate,
    PortalUserIn,
    PortalUserOut,
    PortalUserUpdate,
    RechargeOut,
    ReviewIn,
    StaffRechargeIn,
    StatementOut,
    TxnOut,
)
from app.modules.order.models import SalesOrder
from app.modules.product.models import Product
from app.modules.system.models import User
from app.modules.system.service import get_setting, update_settings

router = APIRouter(prefix="/distribution", tags=["分销管理"])


# ================================================================ 等级
def _level_before_delete(ctx: Ctx, level: DistributorLevel) -> None:
    ensure_not_referenced(ctx.db, [(Distributor, Distributor.level_id == level.id, "分销商")])


router.include_router(
    build_crud_router(
        model=DistributorLevel, create_schema=LevelIn, update_schema=LevelUpdate, out_schema=LevelOut,
        resource="distributor_level", label="分销等级", view_perm="distribution:view", edit_perm="distribution:edit",
        search_fields=("code", "name"), unique_fields=("code",), default_order=("sort", "id"),
        before_delete=_level_before_delete,
    ),
    prefix="/levels",
)


# ================================================================ 分销商
def distributor_out(ctx: Ctx, rows) -> list[dict]:
    rows = list(rows)
    ids = [d.id for d in rows]
    users = dict(ctx.db.execute(
        select(User.distributor_id, func.count()).where(User.distributor_id.in_(ids)).group_by(User.distributor_id)
    ).all()) if ids else {}
    out = []
    for d in rows:
        x = {c.key: getattr(d, c.key) for c in Distributor.__table__.columns if c.key not in ("api_key_hash",)}
        x.update(level_name=d.level.name if d.level else None, available_funds=d.available_funds,
                 user_count=users.get(d.id, 0), has_api_key=bool(d.api_key_hash))
        out.append(x)
    return out


@router.get("/distributors", response_model=Page[DistributorOut], summary="分销商列表")
def list_distributors(
    keyword: str | None = None,
    status: str | None = None,
    level_id: int | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("distribution:view")),
):
    stmt = select(Distributor).order_by(Distributor.id.desc())
    stmt = keyword_filter(stmt, keyword, [Distributor.code, Distributor.name, Distributor.contact, Distributor.phone])
    if status:
        stmt = stmt.where(Distributor.status == status)
    if level_id:
        stmt = stmt.where(Distributor.level_id == level_id)
    page = paginate(ctx.db, stmt, params)
    page["items"] = distributor_out(ctx, page["items"])
    return page


@router.get("/distributors/options", response_model=list[Option], summary="分销商下拉")
def distributor_options(ctx: Ctx = Depends(perm("distribution:view"))):
    rows = ctx.db.execute(select(Distributor).order_by(Distributor.id)).scalars().all()
    return [Option(value=d.id, label=f"{d.code} {d.name}") for d in rows]


@router.get("/distributors/{distributor_id}", response_model=DistributorOut, summary="分销商详情")
def get_distributor(distributor_id: int, ctx: Ctx = Depends(perm("distribution:view"))):
    return distributor_out(ctx, [get_or_404(ctx.db, Distributor, distributor_id, "分销商")])[0]


@router.post("/distributors", response_model=DistributorOut, summary="新增分销商（可同时开通登录账号）")
def create_distributor(body: DistributorIn, ctx: Ctx = Depends(perm("distribution:edit"))):
    data = body.model_dump()
    if data.get("username"):
        ctx.require("distribution:account")
    if data["status"] not in ("active", "disabled"):
        raise BizError("无效的状态")
    return distributor_out(ctx, [service.create_distributor(ctx, data)])[0]


@router.put("/distributors/{distributor_id}", response_model=DistributorOut, summary="修改分销商")
def update_distributor(distributor_id: int, body: DistributorUpdate, ctx: Ctx = Depends(perm("distribution:edit"))):
    data = body.model_dump(exclude_unset=True)
    if "credit_limit" in data:
        ctx.require("distribution:finance")
    return distributor_out(ctx, [service.update_distributor(ctx, distributor_id, data)])[0]


@router.get("/distributors/{distributor_id}/users", response_model=list[PortalUserOut], summary="分销商登录账号")
def list_portal_users(distributor_id: int, ctx: Ctx = Depends(perm("distribution:view"))):
    return ctx.db.execute(select(User).where(User.distributor_id == distributor_id).order_by(User.id)).scalars().all()


@router.post("/distributors/{distributor_id}/users", response_model=PortalUserOut, summary="开通分销商登录账号")
def add_portal_user(distributor_id: int, body: PortalUserIn, ctx: Ctx = Depends(perm("distribution:account"))):
    d = get_or_404(ctx.db, Distributor, distributor_id, "分销商")
    user = service.create_portal_user(ctx, d, body.username, body.password, body.real_name)
    ctx.db.commit()
    return user


@router.put("/distribution-users/{user_id}", response_model=PortalUserOut, summary="修改分销商账号（启用/禁用/重置密码）")
def update_portal_user(user_id: int, body: PortalUserUpdate, ctx: Ctx = Depends(perm("distribution:account"))):
    user = get_or_404(ctx.db, User, user_id, "账号")
    if user.user_type != "distributor":
        raise BizError("只能管理分销商账号")
    data = body.model_dump(exclude_unset=True)
    if "password" in data and data["password"]:
        user.password_hash = hash_password(data.pop("password"))
        user.token_version += 1
    data.pop("password", None)
    if data.get("is_active") is False and user.is_active:
        user.token_version += 1
    for k, v in data.items():
        setattr(user, k, v)
    audit(ctx, "update", "distributor_user", user.id, f"修改分销商账号 {user.username}")
    ctx.db.commit()
    return user


@router.post("/distributors/{distributor_id}/api-key", summary="为分销商生成 API Key（仅显示一次）")
def staff_generate_key(distributor_id: int, ctx: Ctx = Depends(perm("distribution:account"))):
    d = get_or_404(ctx.db, Distributor, distributor_id, "分销商")
    key = service.generate_api_key(ctx.db, d)
    audit(ctx, "update", "distributor", d.id, f"重置分销商 {d.code} API Key")
    ctx.db.commit()
    return {"api_key": key}


@router.delete("/distributors/{distributor_id}/api-key", response_model=Msg, summary="停用分销商 API Key")
def staff_revoke_key(distributor_id: int, ctx: Ctx = Depends(perm("distribution:account"))):
    d = get_or_404(ctx.db, Distributor, distributor_id, "分销商")
    d.api_key_hash = d.api_key_prefix = None
    ctx.db.commit()
    return Msg(message="已停用")


# ================================================================ 资金
@router.post("/distributors/{distributor_id}/adjust", response_model=TxnOut, summary="调整余额")
def adjust(distributor_id: int, body: AdjustIn, ctx: Ctx = Depends(perm("distribution:finance"))):
    if not body.amount:
        raise BizError("金额不能为 0")
    t = service.adjust_balance(ctx, distributor_id, body.amount, body.remark)
    return {**{c.key: getattr(t, c.key) for c in DistributorTransaction.__table__.columns}}


@router.post("/distributors/{distributor_id}/recharge", response_model=RechargeOut, summary="后台代充值（直接入账）")
def staff_recharge(distributor_id: int, body: StaffRechargeIn, ctx: Ctx = Depends(perm("distribution:finance"))):
    d = get_or_404(ctx.db, Distributor, distributor_id, "分销商")
    req = service.create_recharge(ctx.db, d, body.model_dump())
    return recharge_out(ctx, [service.review_recharge(ctx, req.id, True)])[0]


def _names(ctx: Ctx, ids) -> dict:
    ids = {i for i in ids if i}
    return dict(ctx.db.execute(select(Distributor.id, Distributor.name).where(Distributor.id.in_(ids))).all()) if ids else {}


@router.get("/transactions", response_model=Page[TxnOut], summary="资金流水")
def list_transactions(
    distributor_id: int | None = None,
    txn_type: str | None = None,
    keyword: str | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("distribution:view")),
):
    T = DistributorTransaction
    stmt = select(T).order_by(T.id.desc())
    stmt = keyword_filter(stmt, keyword, [T.ref_no, T.remark])
    if distributor_id:
        stmt = stmt.where(T.distributor_id == distributor_id)
    if txn_type:
        stmt = stmt.where(T.txn_type == txn_type)
    page = paginate(ctx.db, stmt, params)
    names = _names(ctx, [t.distributor_id for t in page["items"]])
    page["items"] = [{**{c.key: getattr(t, c.key) for c in T.__table__.columns}, "distributor_name": names.get(t.distributor_id)}
                     for t in page["items"]]
    return page


def recharge_out(ctx: Ctx, rows) -> list[dict]:
    rows = list(rows)
    names = _names(ctx, [r.distributor_id for r in rows])
    return [{**{c.key: getattr(r, c.key) for c in RechargeRequest.__table__.columns}, "distributor_name": names.get(r.distributor_id)}
            for r in rows]


@router.get("/recharges", response_model=Page[RechargeOut], summary="充值申请")
def list_recharges(
    status: str | None = None,
    distributor_id: int | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("distribution:view")),
):
    stmt = select(RechargeRequest).order_by(RechargeRequest.id.desc())
    if status:
        stmt = stmt.where(RechargeRequest.status == status)
    if distributor_id:
        stmt = stmt.where(RechargeRequest.distributor_id == distributor_id)
    page = paginate(ctx.db, stmt, params)
    page["items"] = recharge_out(ctx, page["items"])
    return page


@router.post("/recharges/{req_id}/review", response_model=RechargeOut, summary="审核充值（确认到账 / 驳回）")
def review_recharge(req_id: int, body: ReviewIn, ctx: Ctx = Depends(perm("distribution:finance"))):
    if not body.approve and not body.reason:
        raise BizError("请填写驳回原因")
    return recharge_out(ctx, [service.review_recharge(ctx, req_id, body.approve, body.reason)])[0]


@router.get("/statement", response_model=StatementOut, summary="分销商对账单")
def get_statement(distributor_id: int, date_from: date, date_to: date, ctx: Ctx = Depends(perm("distribution:view"))):
    data = service.statement(ctx.db, distributor_id, date_from, date_to)
    data["transactions"] = [{c.key: getattr(t, c.key) for c in DistributorTransaction.__table__.columns} for t in data["transactions"]]
    return data


TXN_LABEL = {"recharge": "充值", "order": "订单扣款", "refund": "退款", "adjust": "调整"}


@router.get("/statement/export", summary="导出对账单")
def export_statement(distributor_id: int, date_from: date, date_to: date, ctx: Ctx = Depends(perm("distribution:view"))):
    data = service.statement(ctx.db, distributor_id, date_from, date_to)
    rows = [{"time": t.created_at, "type": TXN_LABEL.get(t.txn_type, t.txn_type), "ref_no": t.ref_no, "amount": t.amount,
             "balance": t.balance_after, "remark": t.remark} for t in data["transactions"]]
    rows.insert(0, {"type": "期初余额", "balance": data["opening_balance"]})
    rows.append({"type": "期末余额", "balance": data["closing_balance"]})
    cols = [("time", "时间"), ("type", "类型"), ("ref_no", "单号"), ("amount", f"金额({data['currency']})"), ("balance", "余额"), ("remark", "备注")]
    return export_xlsx(f"对账单_{data['distributor_name']}_{date_from}_{date_to}.xlsx", cols, rows)


# ================================================================ 分销商品
def catalog_out(ctx: Ctx, rows) -> list[dict]:
    rows = list(rows)
    pids = [r.product_id for r in rows]
    products = {p.id: p for p in ctx.db.execute(select(Product).where(Product.id.in_(pids))).scalars().all()} if pids else {}
    avail = service.available_qty(ctx.db, pids)
    lp: dict[int, list[dict]] = defaultdict(list)
    if pids:
        for x in ctx.db.execute(select(DistributionLevelPrice).where(DistributionLevelPrice.product_id.in_(pids))).scalars().all():
            lp[x.product_id].append({"level_id": x.level_id, "price": float(x.price)})
    show_cost = ctx.can("product:cost:view")
    out = []
    for r in rows:
        p = products.get(r.product_id)
        d = {c.key: getattr(r, c.key) for c in DistributionProduct.__table__.columns}
        d.update(sku=p.sku if p else "-", product_name=p.name if p else "-", image_url=p.image_url if p else None,
                 available=avail.get(r.product_id, 0), level_prices=lp.get(r.product_id, []),
                 purchase_cost=(p.purchase_cost if p and show_cost else None))
        out.append(d)
    return out


@router.get("/catalog", response_model=Page[CatalogOut], summary="分销商品目录")
def list_catalog(
    keyword: str | None = None,
    is_active: bool | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("distribution:view")),
):
    stmt = select(DistributionProduct).join(Product, Product.id == DistributionProduct.product_id).order_by(
        DistributionProduct.sort, DistributionProduct.id.desc())
    stmt = keyword_filter(stmt, keyword, [Product.sku, Product.name, DistributionProduct.title])
    if is_active is not None:
        stmt = stmt.where(DistributionProduct.is_active.is_(is_active))
    page = paginate(ctx.db, stmt, params)
    page["items"] = catalog_out(ctx, page["items"])
    return page


@router.post("/catalog", response_model=Msg, summary="批量上架 / 更新分销商品")
def upsert_catalog(body: CatalogUpsertIn, ctx: Ctx = Depends(perm("distribution:edit"))):
    n = service.upsert_catalog(ctx, [i.model_dump(exclude_unset=True) for i in body.items])
    return Msg(message=f"已保存 {n} 个分销商品")


@router.put("/catalog/{product_id}/level-prices", response_model=Msg, summary="设置等级价")
def put_level_prices(product_id: int, body: LevelPricesIn, ctx: Ctx = Depends(perm("distribution:edit"))):
    service.set_level_prices(ctx, product_id, [p.model_dump() for p in body.prices])
    return Msg(message="已保存")


@router.delete("/catalog/{item_id}", response_model=Msg, summary="移出分销目录")
def delete_catalog(item_id: int, ctx: Ctx = Depends(perm("distribution:edit"))):
    dp = get_or_404(ctx.db, DistributionProduct, item_id, "分销商品")
    ctx.db.delete(dp)
    audit(ctx, "delete", "distribution_product", item_id, "移出分销目录")
    ctx.db.commit()
    return Msg(message="已移出")


# ================================================================ 订单费用调整 / 概览 / 设置
@router.post("/orders/{order_id}/charge", summary="分销订单补扣 / 部分退款")
def order_charge(order_id: int, body: ChargeAdjustIn, ctx: Ctx = Depends(perm("distribution:finance"))):
    order = service.charge_adjust(ctx, order_id, body.amount, body.remark)
    return {"message": "已调整", "charge_detail": order.charge_detail}


@router.get("/overview", summary="分销概览")
def overview(ctx: Ctx = Depends(perm("distribution:view"))):
    db = ctx.db
    month_start = utcnow().date().replace(day=1)
    balances = [{"currency": c, "balance": float(q2(b or 0)), "credit": float(q2(cr or 0)), "count": n}
                for c, b, cr, n in db.execute(
                    select(Distributor.currency, func.sum(Distributor.balance), func.sum(Distributor.credit_limit), func.count())
                    .group_by(Distributor.currency)).all()]
    month = db.execute(
        select(SalesOrder.currency, func.count(), func.sum(SalesOrder.total_amount))
        .where(SalesOrder.distributor_id.is_not(None), SalesOrder.status != "cancelled", SalesOrder.local_date >= month_start)
        .group_by(SalesOrder.currency)
    ).all()
    return {
        "distributors": db.execute(select(func.count()).select_from(Distributor)).scalar_one(),
        "active": db.execute(select(func.count()).select_from(Distributor).where(Distributor.status == "active")).scalar_one(),
        "pending_recharges": db.execute(select(func.count()).select_from(RechargeRequest).where(RechargeRequest.status == "pending")).scalar_one(),
        "to_audit": db.execute(select(func.count()).select_from(SalesOrder).where(
            SalesOrder.distributor_id.is_not(None), SalesOrder.status == "to_audit")).scalar_one(),
        "balances": balances,
        "month_orders": [{"currency": c, "orders": n, "amount": float(q2(a or 0))} for c, n, a in month],
    }


SETTING_KEYS = ("warehouse_ids", "channel_ids", "handling_fee_per_order", "handling_fee_per_item",
                "freight_markup_rate", "auto_audit", "allow_cancel_after_audit")


@router.get("/settings", response_model=DistributionSettings, summary="分销参数")
def get_settings(ctx: Ctx = Depends(perm("distribution:view"))):
    return {k: get_setting(ctx.db, f"distribution.{k}") for k in SETTING_KEYS}


@router.put("/settings", response_model=DistributionSettings, summary="修改分销参数")
def put_settings(body: DistributionSettings, ctx: Ctx = Depends(perm("distribution:setting"))):
    values = {}
    for k, v in body.model_dump().items():
        values[f"distribution.{k}"] = float(v) if isinstance(v, Decimal) else v
    update_settings(ctx, values)
    return get_settings(ctx)
