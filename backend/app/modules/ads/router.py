from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import func, select

from app.common.audit import audit
from app.common.crud import get_or_404, keyword_filter
from app.common.currency import get_rate
from app.common.excel import as_date, read_upload, template_response
from app.common.pagination import PageParams, page_params, paginate
from app.common.schemas import ORMOut, Page
from app.core.deps import Ctx, perm
from app.core.types import Money, q2
from app.integrations.dto import AdMetricDTO
from app.modules.ads.models import AdCampaign, AdMetricDaily
from app.modules.product.schemas import ImportResult
from app.modules.shop.models import Shop

router = APIRouter(prefix="/ads", tags=["广告管理"])


class CampaignOut(ORMOut):
    shop_id: int
    shop_name: str | None = None
    campaign_id: str
    name: str
    ad_type: str
    state: str
    targeting_type: str | None = None
    daily_budget: Money
    currency: str
    start_date: date | None = None
    end_date: date | None = None


def upsert_metrics(ctx: Ctx, shop: Shop, rows: list[AdMetricDTO]) -> tuple[int, int]:
    """写入广告日报（平台同步与 Excel 导入共用），并维护广告活动。"""
    db = ctx.db
    created = updated = 0
    campaigns = {c.campaign_id: c for c in db.execute(select(AdCampaign).where(AdCampaign.shop_id == shop.id)).scalars().all()}
    dates = {r.metric_date for r in rows}
    existing = {}
    if dates:
        for m in db.execute(select(AdMetricDaily).where(AdMetricDaily.shop_id == shop.id,
                                                         AdMetricDaily.metric_date.in_(dates))).scalars().all():
            existing[(m.metric_date, m.campaign_id, m.ad_group, m.msku)] = m
    for r in rows:
        key = (r.metric_date, r.campaign_id, r.ad_group or "", r.msku or "")
        m = existing.get(key)
        if m is None:
            m = AdMetricDaily(shop_id=shop.id, metric_date=r.metric_date, campaign_id=r.campaign_id,
                              ad_group=r.ad_group or "", msku=r.msku or "")
            db.add(m)
            existing[key] = m
            created += 1
        else:
            updated += 1
        for f in ("campaign_name", "ad_type", "asin", "impressions", "clicks", "spend", "sales", "orders", "units"):
            setattr(m, f, getattr(r, f))
        m.currency = (r.currency or shop.currency).upper()
        if r.campaign_id not in campaigns:
            c = AdCampaign(shop_id=shop.id, campaign_id=r.campaign_id, name=r.campaign_name or r.campaign_id,
                           ad_type=r.ad_type, currency=m.currency)
            db.add(c)
            campaigns[r.campaign_id] = c
    db.flush()
    return created, updated


@router.get("/campaigns", response_model=Page[CampaignOut], summary="广告活动")
def list_campaigns(
    keyword: str | None = None,
    shop_id: int | None = None,
    state: str | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("ads:view")),
):
    stmt = select(AdCampaign).order_by(AdCampaign.id.desc())
    stmt = keyword_filter(stmt, keyword, [AdCampaign.name, AdCampaign.campaign_id])
    if shop_id:
        stmt = stmt.where(AdCampaign.shop_id == shop_id)
    if state:
        stmt = stmt.where(AdCampaign.state == state)
    if ctx.shop_ids is not None:
        stmt = stmt.where(AdCampaign.shop_id.in_(ctx.shop_ids))
    page = paginate(ctx.db, stmt, params)
    names = dict(ctx.db.execute(select(Shop.id, Shop.name)).all())
    page["items"] = [{**{c.key: getattr(x, c.key) for c in AdCampaign.__table__.columns}, "shop_name": names.get(x.shop_id)}
                     for x in page["items"]]
    return page


def _ratios(impr, clicks, spend, sales, orders) -> dict:
    return {
        "ctr": round(clicks / impr * 100, 2) if impr else None,
        "cpc": float(q2(spend / clicks)) if clicks else None,
        "cvr": round(orders / clicks * 100, 2) if clicks else None,
        "acos": round(float(spend / sales) * 100, 2) if sales else None,
        "roas": round(float(sales / spend), 2) if spend else None,
    }


@router.get("/summary", summary="广告数据汇总（按活动 / MSKU / 日期，本位币）")
def summary(
    date_from: date,
    date_to: date,
    group_by: str = "campaign",
    shop_id: int | None = None,
    keyword: str | None = None,
    ctx: Ctx = Depends(perm("ads:view")),
):
    dims = {
        "campaign": [AdMetricDaily.shop_id, AdMetricDaily.campaign_id, AdMetricDaily.campaign_name, AdMetricDaily.ad_type],
        "msku": [AdMetricDaily.shop_id, AdMetricDaily.msku, AdMetricDaily.asin],
        "day": [AdMetricDaily.metric_date],
        "shop": [AdMetricDaily.shop_id],
    }
    if group_by not in dims:
        group_by = "campaign"
    cols = dims[group_by]
    stmt = (
        select(*cols, AdMetricDaily.currency, AdMetricDaily.metric_date,
               func.sum(AdMetricDaily.impressions), func.sum(AdMetricDaily.clicks), func.sum(AdMetricDaily.spend),
               func.sum(AdMetricDaily.sales), func.sum(AdMetricDaily.orders), func.sum(AdMetricDaily.units))
        .where(AdMetricDaily.metric_date >= date_from, AdMetricDaily.metric_date <= date_to)
        .group_by(*cols, AdMetricDaily.currency, AdMetricDaily.metric_date)
    )
    stmt = keyword_filter(stmt, keyword, [AdMetricDaily.campaign_name, AdMetricDaily.msku, AdMetricDaily.asin])
    if shop_id:
        stmt = stmt.where(AdMetricDaily.shop_id == shop_id)
    if ctx.shop_ids is not None:
        stmt = stmt.where(AdMetricDaily.shop_id.in_(ctx.shop_ids))
    names = dict(ctx.db.execute(select(Shop.id, Shop.name)).all())
    agg: dict[tuple, dict] = {}
    n = len(cols)
    for row in ctx.db.execute(stmt).all():
        key = tuple(row[:n])
        cur, d = row[n], row[n + 1]
        impr, clicks, spend, sales, orders, units = row[n + 2:]
        rate = get_rate(ctx.db, cur, d)
        a = agg.setdefault(key, {"impressions": 0, "clicks": 0, "spend": Decimal(0), "sales": Decimal(0), "orders": 0, "units": 0})
        a["impressions"] += int(impr or 0)
        a["clicks"] += int(clicks or 0)
        a["spend"] += Decimal(spend or 0) * rate
        a["sales"] += Decimal(sales or 0) * rate
        a["orders"] += int(orders or 0)
        a["units"] += int(units or 0)
    items = []
    for key, a in agg.items():
        d = {"impressions": a["impressions"], "clicks": a["clicks"], "spend": float(q2(a["spend"])),
             "sales": float(q2(a["sales"])), "orders": a["orders"], "units": a["units"]}
        d.update(_ratios(a["impressions"], a["clicks"], a["spend"], a["sales"], a["orders"]))
        if group_by == "campaign":
            d.update(shop_id=key[0], shop_name=names.get(key[0]), campaign_id=key[1], campaign_name=key[2], ad_type=key[3])
        elif group_by == "msku":
            d.update(shop_id=key[0], shop_name=names.get(key[0]), msku=key[1], asin=key[2])
        elif group_by == "day":
            d.update(date=str(key[0]))
        else:
            d.update(shop_id=key[0], shop_name=names.get(key[0]))
        items.append(d)
    if group_by == "day":
        items.sort(key=lambda x: x["date"])
    else:
        items.sort(key=lambda x: -x["spend"])
    tot = {k: sum(Decimal(str(i[k])) for i in items) for k in ("impressions", "clicks", "spend", "sales", "orders", "units")}
    totals = {"impressions": int(tot["impressions"]), "clicks": int(tot["clicks"]), "spend": float(tot["spend"]),
              "sales": float(tot["sales"]), "orders": int(tot["orders"]), "units": int(tot["units"])}
    totals.update(_ratios(totals["impressions"], totals["clicks"], tot["spend"], tot["sales"], totals["orders"]))
    return {"items": items, "totals": totals}


AD_COLUMNS = [
    ("metric_date", "日期"), ("campaign_id", "广告活动ID"), ("campaign_name", "广告活动"), ("ad_group", "广告组"),
    ("ad_type", "广告类型"), ("msku", "MSKU"), ("asin", "ASIN"), ("impressions", "曝光"), ("clicks", "点击"),
    ("spend", "花费"), ("sales", "销售额"), ("orders", "订单"), ("units", "销量"), ("currency", "币种"),
]


@router.get("/import-template", summary="广告数据导入模板")
def ad_template(_: Ctx = Depends(perm("ads:edit"))):
    return template_response("广告数据导入模板.xlsx", AD_COLUMNS, {
        "metric_date": "2026-09-01", "campaign_id": "C1", "campaign_name": "SP-自动", "ad_type": "SP", "msku": "MSKU-1",
        "impressions": 1000, "clicks": 20, "spend": 15.5, "sales": 59.9, "orders": 2, "units": 2, "currency": "USD",
    })


@router.post("/import", response_model=ImportResult, summary="导入广告日报（按 日期+活动+广告组+MSKU 覆盖）")
def import_metrics(shop_id: int = Form(...), file: UploadFile = File(...), ctx: Ctx = Depends(perm("ads:edit"))):
    shop = get_or_404(ctx.db, Shop, shop_id, "店铺")
    ctx.require_shop(shop.id)
    rows = read_upload(file, AD_COLUMNS)
    result = ImportResult()
    dtos = []
    for r in rows:
        try:
            dtos.append(AdMetricDTO(
                metric_date=as_date(r.get("metric_date")), campaign_id=str(r.get("campaign_id") or r.get("campaign_name")),
                campaign_name=r.get("campaign_name"), ad_group=str(r.get("ad_group") or ""), ad_type=str(r.get("ad_type") or "SP"),
                msku=str(r.get("msku") or ""), asin=r.get("asin"), impressions=int(r.get("impressions") or 0),
                clicks=int(r.get("clicks") or 0), spend=Decimal(str(r.get("spend") or 0)),
                sales=Decimal(str(r.get("sales") or 0)), orders=int(r.get("orders") or 0), units=int(r.get("units") or 0),
                currency=str(r.get("currency") or shop.currency),
            ))
        except Exception as exc:  # noqa: BLE001
            result.skipped += 1
            result.errors.append(f"第 {r['_row']} 行: {exc}")
    result.created, result.updated = upsert_metrics(ctx, shop, dtos)
    audit(ctx, "import", "ad_metrics", shop.id, f"导入广告数据 {len(dtos)} 条")
    ctx.db.commit()
    return result


@router.get("/metrics", summary="广告日报明细")
def list_metrics(
    keyword: str | None = None,
    shop_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("ads:view")),
):
    stmt = select(AdMetricDaily).order_by(AdMetricDaily.metric_date.desc(), AdMetricDaily.id.desc())
    stmt = keyword_filter(stmt, keyword, [AdMetricDaily.campaign_name, AdMetricDaily.msku, AdMetricDaily.asin])
    if shop_id:
        stmt = stmt.where(AdMetricDaily.shop_id == shop_id)
    if date_from:
        stmt = stmt.where(AdMetricDaily.metric_date >= date_from)
    if date_to:
        stmt = stmt.where(AdMetricDaily.metric_date <= date_to)
    if ctx.shop_ids is not None:
        stmt = stmt.where(AdMetricDaily.shop_id.in_(ctx.shop_ids))
    page = paginate(ctx.db, stmt, params)
    page["items"] = [
        {**{c.key: (float(getattr(m, c.key)) if isinstance(getattr(m, c.key), Decimal) else getattr(m, c.key))
            for c in AdMetricDaily.__table__.columns},
         **_ratios(m.impressions, m.clicks, Decimal(m.spend), Decimal(m.sales), m.orders)}
        for m in page["items"]
    ]
    return page
