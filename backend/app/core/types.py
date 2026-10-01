"""通用列类型与 Pydantic 类型。"""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import PlainSerializer
from sqlalchemy import DateTime, Numeric
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """始终以 UTC 存储、读取为带时区的 datetime（兼容 SQLite 与 PostgreSQL）。"""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        value = value.astimezone(UTC)
        if dialect.name == "sqlite":
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


# 金额：18 位总长、4 位小数；汇率：6 位小数
MoneyColumn = Numeric(18, 4)
RateColumn = Numeric(18, 6)

ZERO = Decimal("0")


def q2(value: Decimal | int | float | None) -> Decimal:
    """四舍五入到 2 位小数。"""
    if value is None:
        return Decimal("0.00")
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q4(value: Decimal | int | float | None) -> Decimal:
    if value is None:
        return Decimal("0.0000")
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def to_decimal(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# 输出 JSON 时金额序列化为 number，方便前端展示；内部计算始终使用 Decimal
Money = Annotated[Decimal, PlainSerializer(lambda v: float(v) if v is not None else None, return_type=float | None, when_used="json")]
