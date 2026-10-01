"""币种与汇率换算。汇率按月维护：1 单位外币 = rate 单位本位币。"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BizError

_CACHE_KEY = "_fx_cache"


def base_currency(db: Session) -> str:
    cache = db.info.setdefault(_CACHE_KEY, {})
    if "__base__" not in cache:
        from app.modules.system.models import Tenant

        tid = db.info.get("tenant_id")
        tenant = db.get(Tenant, tid) if tid else None
        cache["__base__"] = tenant.base_currency if tenant else "CNY"
    return cache["__base__"]


def get_rate(db: Session, currency: str, on: date | None = None) -> Decimal:
    """返回 currency → 本位币 的汇率（取 on 所在月份或之前最近一个月的汇率）。"""
    from app.modules.shop.marketplaces import DEFAULT_RATES_TO_CNY
    from app.modules.system.models import ExchangeRate

    currency = (currency or "").upper()
    base = base_currency(db)
    if not currency or currency == base:
        return Decimal(1)
    month = (on or date.today()).strftime("%Y-%m")
    cache = db.info.setdefault(_CACHE_KEY, {})
    key = (currency, month)
    if key in cache:
        return cache[key]
    rate = db.execute(
        select(ExchangeRate.rate)
        .where(ExchangeRate.currency == currency, ExchangeRate.month <= month)
        .order_by(ExchangeRate.month.desc())
        .limit(1)
    ).scalar_one_or_none()
    if rate is None:
        rate = db.execute(
            select(ExchangeRate.rate).where(ExchangeRate.currency == currency).order_by(ExchangeRate.month.asc()).limit(1)
        ).scalar_one_or_none()
    if rate is None and base == "CNY" and currency in DEFAULT_RATES_TO_CNY:
        rate = Decimal(DEFAULT_RATES_TO_CNY[currency])
    if rate is None:
        raise BizError(f"缺少币种 {currency} 的汇率，请先在【财务-汇率管理】中维护")
    rate = Decimal(rate)
    cache[key] = rate
    return rate


def to_base(db: Session, amount: Decimal | int | float | None, currency: str, on: date | None = None) -> Decimal:
    if not amount:
        return Decimal(0)
    return Decimal(str(amount)) * get_rate(db, currency, on)


def clear_rate_cache(db: Session) -> None:
    db.info.pop(_CACHE_KEY, None)
