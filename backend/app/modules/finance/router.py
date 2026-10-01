from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import Field
from sqlalchemy import func, select

from app.common.audit import audit
from app.common.crud import get_or_404, keyword_filter
from app.common.excel import export_xlsx, read_upload, template_response
from app.common.pagination import PageParams, page_params, paginate
from app.common.schemas import Msg, ORMOut, Page, Schema
from app.core.deps import Ctx, perm
from app.core.errors import BizError
from app.core.types import Money, utcnow
from app.integrations.dto import TransactionDTO
from app.modules.finance import service
from app.modules.finance.models import Expense, PlatformTransaction
from app.modules.product.schemas import ImportResult
from app.modules.shop.models import Shop

router = APIRouter(prefix="/finance", tags=["财务管理"])


# ================================================================ schemas
class TransactionOut(ORMOut):
    shop_id: int
    shop_name: str | None = None
    external_id: str
    settlement_id: str | None = None
    posted_at: datetime
    posted_date: date
    event_type: str
    amount_type: str
    category: str | None = None
    platform_order_id: str | None = None
    msku: str | None = None
    quantity: int
    amount: Money
    currency: str
    description: str | None = None


class ExpenseIn(Schema):
    category: str = "other"
    shop_id: int | None = None
    product_id: int | None = None
    msku: str | None = None
    expense_date: date
    currency: str = "CNY"
    amount: Decimal = Field(gt=0)
    status: str = "confirmed"
    description: str | None = None


class ExpenseUpdate(Schema):
    category: str | None = None
    shop_id: int | None = None
    product_id: int | None = None
    msku: str | None = None
    expense_date: date | None = None
    currency: str | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    status: str | None = None
    description: str | None = None


class ExpenseOut(ORMOut):
    expense_no: str
    category: str
    shop_id: int | None = None
    shop_name: str | None = None
    product_id: int | None = None
    msku: str | None = None
    expense_date: date
    currency: str
    amount: Money
    status: str
    description: str | None = None
    created_by: int | None = None


EXPENSE_CATEGORIES = {
    "rent": "房租水电", "salary": "人员工资", "software": "软件服务", "marketing": "站外推广", "logistics": "物流杂费",
    "office": "办公费用", "tax": "税费", "sample": "样品费", "testing": "认证检测", "other": "其他",
}


# ================================================================ 交易明细
def _shop_names(db) -> dict:
    return dict(db.execute(select(Shop.id, Shop.name)).all())


@router.get("/transactions", response_model=Page[TransactionOut], summary="平台交易明细")
def list_transactions(
    keyword: str | None = None,
    shop_id: int | None = None,
    event_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("finance:transaction:view")),
):
    stmt = select(PlatformTransaction).order_by(PlatformTransaction.posted_at.desc(), PlatformTransaction.id.desc())
    stmt = keyword_filter(stmt, keyword, [PlatformTransaction.platform_order_id, PlatformTransaction.msku,
                                          PlatformTransaction.settlement_id, PlatformTransaction.amount_type])
    if shop_id:
        stmt = stmt.where(PlatformTransaction.shop_id == shop_id)
    if event_type:
        stmt = stmt.where(PlatformTransaction.event_type == event_type)
    if date_from:
        stmt = stmt.where(PlatformTransaction.posted_date >= date_from)
    if date_to:
        stmt = stmt.where(PlatformTransaction.posted_date <= date_to)
    if ctx.shop_ids is not None:
        stmt = stmt.where(PlatformTransaction.shop_id.in_(ctx.shop_ids))
    page = paginate(ctx.db, stmt, params)
    names = _shop_names(ctx.db)
    page["items"] = [
        {**{c.key: getattr(t, c.key) for c in PlatformTransaction.__table__.columns}, "shop_name": names.get(t.shop_id),
         "category": service.classify_amount_type(t.amount_type)}
        for t in page["items"]
    ]
    return page


@router.get("/transactions/summary", summary="交易汇总（按店铺 × 月份 × 费用类别）")
def transaction_summary(
    date_from: date, date_to: date, shop_id: int | None = None, ctx: Ctx = Depends(perm("finance:transaction:view"))
):
    stmt = (
        select(PlatformTransaction.shop_id, PlatformTransaction.currency, PlatformTransaction.event_type,
               PlatformTransaction.amount_type, func.sum(PlatformTransaction.amount))
        .where(PlatformTransaction.posted_date >= date_from, PlatformTransaction.posted_date <= date_to)
        .group_by(PlatformTransaction.shop_id, PlatformTransaction.currency, PlatformTransaction.event_type,
                  PlatformTransaction.amount_type)
    )
    if shop_id:
        stmt = stmt.where(PlatformTransaction.shop_id == shop_id)
    if ctx.shop_ids is not None:
        stmt = stmt.where(PlatformTransaction.shop_id.in_(ctx.shop_ids))
    names = _shop_names(ctx.db)
    agg: dict[tuple, dict] = {}
    for sid, cur, ev, at, amt in ctx.db.execute(stmt).all():
        r = agg.setdefault((sid, cur), {"shop_id": sid, "shop_name": names.get(sid), "currency": cur, "revenue": Decimal(0),
                                         "commission": Decimal(0), "fulfillment": Decimal(0), "promotion": Decimal(0),
                                         "refund": Decimal(0), "other": Decimal(0), "transfer": Decimal(0), "net": Decimal(0)})
        amt = Decimal(amt or 0)
        if ev == "transfer":
            r["transfer"] += amt
            continue
        if ev == "refund":
            r["refund"] += amt
        else:
            r[service.classify_amount_type(at)] += amt
        r["net"] += amt
    return [{k: (float(v) if isinstance(v, Decimal) else v) for k, v in r.items()} for r in agg.values()]


TX_COLUMNS = [
    ("external_id", "交易ID"), ("posted_at", "日期"), ("event_type", "交易类型"), ("amount_type", "费用类型"),
    ("platform_order_id", "订单号"), ("msku", "MSKU"), ("quantity", "数量"), ("amount", "金额"), ("currency", "币种"),
    ("settlement_id", "结算ID"), ("description", "描述"),
]


@router.get("/transactions/import-template", summary="交易明细导入模板")
def tx_template(_: Ctx = Depends(perm("finance:transaction:edit"))):
    return template_response("交易明细导入模板.xlsx", TX_COLUMNS, {
        "external_id": "S1-113-1-Principal", "posted_at": "2026-09-01 10:00:00", "event_type": "order",
        "amount_type": "Principal", "platform_order_id": "113-1", "msku": "MSKU-1", "quantity": 1, "amount": 19.99,
        "currency": "USD",
    })


@router.post("/transactions/import", response_model=ImportResult, summary="导入交易明细（结算报告）")
def import_transactions(
    shop_id: int = Form(...),
    file: UploadFile = File(...),
    apply_fees: bool = Form(True),
    ctx: Ctx = Depends(perm("finance:transaction:edit")),
):
    shop = get_or_404(ctx.db, Shop, shop_id, "店铺")
    ctx.require_shop(shop.id)
    rows = read_upload(file, TX_COLUMNS)
    result = ImportResult()
    dtos = []
    for r in rows:
        try:
            posted = r.get("posted_at")
            if isinstance(posted, str):
                posted = datetime.fromisoformat(posted)
            elif isinstance(posted, date) and not isinstance(posted, datetime):
                posted = datetime.combine(posted, datetime.min.time())
            ext = r.get("external_id") or f"{r.get('settlement_id') or ''}-{r.get('platform_order_id') or ''}-{r.get('amount_type')}-{r['_row']}"
            dtos.append(TransactionDTO(
                external_id=str(ext), posted_at=posted or utcnow(), event_type=str(r.get("event_type") or "other"),
                amount_type=str(r.get("amount_type") or "Other"), amount=Decimal(str(r.get("amount") or 0)),
                currency=str(r.get("currency") or shop.currency), platform_order_id=r.get("platform_order_id") and str(r["platform_order_id"]),
                msku=r.get("msku") and str(r["msku"]), quantity=int(r.get("quantity") or 0),
                settlement_id=r.get("settlement_id") and str(r["settlement_id"]), description=r.get("description"),
            ))
        except Exception as exc:  # noqa: BLE001
            result.skipped += 1
            result.errors.append(f"第 {r['_row']} 行: {exc}")
    created, updated = service.upsert_transactions(ctx, shop, dtos)
    result.created, result.updated = created, updated
    if apply_fees:
        service.apply_transactions_to_orders(ctx, shop.id, list({d.platform_order_id for d in dtos if d.platform_order_id}))
    audit(ctx, "import", "platform_transaction", shop.id, f"导入交易明细 {created + updated} 条")
    ctx.db.commit()
    return result


@router.post("/transactions/apply-fees", response_model=Msg, summary="按结算数据更新订单实际费用")
def apply_fees(shop_id: int, ctx: Ctx = Depends(perm("finance:transaction:edit"))):
    ctx.require_shop(shop_id)
    n = service.apply_transactions_to_orders(ctx, shop_id)
    ctx.db.commit()
    return Msg(message=f"已更新 {n} 个订单行的实际费用")


# ================================================================ 费用
@router.get("/expense-categories", summary="费用类别")
def expense_categories(_: Ctx = Depends(perm("finance:expense:view"))):
    return [{"value": k, "label": v} for k, v in EXPENSE_CATEGORIES.items()]


def _expense_out(ctx: Ctx, rows) -> list[dict]:
    names = _shop_names(ctx.db)
    return [{**{c.key: getattr(e, c.key) for c in Expense.__table__.columns}, "shop_name": names.get(e.shop_id)} for e in rows]


@router.get("/expenses", response_model=Page[ExpenseOut], summary="费用列表")
def list_expenses(
    keyword: str | None = None,
    category: str | None = None,
    shop_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("finance:expense:view")),
):
    stmt = select(Expense).order_by(Expense.expense_date.desc(), Expense.id.desc())
    stmt = keyword_filter(stmt, keyword, [Expense.expense_no, Expense.description, Expense.msku])
    if category:
        stmt = stmt.where(Expense.category == category)
    if shop_id:
        stmt = stmt.where(Expense.shop_id == shop_id)
    if date_from:
        stmt = stmt.where(Expense.expense_date >= date_from)
    if date_to:
        stmt = stmt.where(Expense.expense_date <= date_to)
    page = paginate(ctx.db, stmt, params)
    page["items"] = _expense_out(ctx, page["items"])
    return page


@router.post("/expenses", response_model=ExpenseOut, summary="新增费用")
def create_expense(body: ExpenseIn, ctx: Ctx = Depends(perm("finance:expense:edit"))):
    if body.category not in EXPENSE_CATEGORIES:
        raise BizError("无效的费用类别")
    return _expense_out(ctx, [service.create_expense(ctx, body.model_dump())])[0]


@router.put("/expenses/{expense_id}", response_model=ExpenseOut, summary="修改费用")
def update_expense(expense_id: int, body: ExpenseUpdate, ctx: Ctx = Depends(perm("finance:expense:edit"))):
    e = get_or_404(ctx.db, Expense, expense_id, "费用")
    data = body.model_dump(exclude_unset=True)
    if "category" in data and data["category"] not in EXPENSE_CATEGORIES:
        raise BizError("无效的费用类别")
    for k, v in data.items():
        setattr(e, k, v.upper() if k == "currency" and v else v)
    audit(ctx, "update", "expense", e.id, f"修改费用 {e.expense_no}")
    ctx.db.commit()
    return _expense_out(ctx, [e])[0]


@router.delete("/expenses/{expense_id}", response_model=Msg, summary="删除费用")
def delete_expense(expense_id: int, ctx: Ctx = Depends(perm("finance:expense:edit"))):
    e = get_or_404(ctx.db, Expense, expense_id, "费用")
    ctx.db.delete(e)
    audit(ctx, "delete", "expense", expense_id, f"删除费用 {e.expense_no}")
    ctx.db.commit()
    return Msg(message="已删除")


# ================================================================ 利润报表
@router.get("/profit", summary="利润报表")
def profit(
    date_from: date,
    date_to: date,
    group_by: str = "msku",
    shop_id: int | None = None,
    keyword: str | None = None,
    ctx: Ctx = Depends(perm("finance:profit:view")),
):
    return service.profit_report(ctx, date_from=date_from, date_to=date_to, group_by=group_by, shop_id=shop_id, keyword=keyword)


PROFIT_COLUMNS = [
    ("shop_name", "店铺"), ("msku", "MSKU"), ("asin", "ASIN"), ("sku", "SKU"), ("product_name", "品名"),
    ("period", "日期"), ("units", "销量"), ("orders", "订单数"), ("sales", "销售额"), ("refunds", "退款"),
    ("commission", "平台佣金"), ("fulfillment_fee", "FBA配送费"), ("other_order_fee", "其他订单费"),
    ("ad_spend", "广告费"), ("cost_purchase", "采购成本"), ("cost_freight", "头程成本"), ("restock_cost", "退货回库成本"),
    ("logistics", "自发货运费"), ("platform_other_fee", "平台其他费用"), ("expenses", "其他费用"), ("profit", "毛利润"),
    ("margin", "毛利率%"), ("roi", "ROI%"), ("acos", "ACoS%"),
]


@router.get("/profit/export", summary="导出利润报表")
def export_profit(
    date_from: date,
    date_to: date,
    group_by: str = "msku",
    shop_id: int | None = None,
    ctx: Ctx = Depends(perm("finance:profit:view")),
):
    data = service.profit_report(ctx, date_from=date_from, date_to=date_to, group_by=group_by, shop_id=shop_id)
    rows = data["items"] + [{**data["totals"], "shop_name": "合计", "period": "合计"}]
    return export_xlsx(f"利润报表_{date_from}_{date_to}.xlsx", PROFIT_COLUMNS, rows)


@router.get("/inventory-valuation", summary="库存估值（按仓库）")
def inventory_valuation(ctx: Ctx = Depends(perm("finance:valuation:view"))):
    return service.inventory_valuation(ctx)
