from decimal import Decimal

from pydantic import Field

from app.common.schemas import ORMOut, Schema
from app.core.types import Money


class ProviderOut(ORMOut):
    code: str
    name: str
    provider_type: str
    contact: str | None = None
    phone: str | None = None
    website: str | None = None
    status: str
    remark: str | None = None


class ProviderIn(Schema):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    provider_type: str = "forwarder"
    contact: str | None = None
    phone: str | None = None
    website: str | None = None
    status: str = "active"
    remark: str | None = None


class ProviderUpdate(Schema):
    code: str | None = None
    name: str | None = None
    provider_type: str | None = None
    contact: str | None = None
    phone: str | None = None
    website: str | None = None
    status: str | None = None
    remark: str | None = None


class ChannelOut(ORMOut):
    provider_id: int
    code: str
    name: str
    usage: str
    transport_mode: str
    billing_type: str
    currency: str
    unit_price: Money
    first_weight_kg: Money
    first_price: Money
    extra_unit_kg: Money
    extra_price: Money
    volume_divisor: int
    min_charge: Money
    surcharge: Money
    transit_days: int
    status: str
    remark: str | None = None


class ChannelIn(Schema):
    provider_id: int
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    usage: str = "first_mile"
    transport_mode: str = "express"
    billing_type: str = "weight"
    currency: str = "CNY"
    unit_price: Decimal = Decimal(0)
    first_weight_kg: Decimal = Decimal(0)
    first_price: Decimal = Decimal(0)
    extra_unit_kg: Decimal = Decimal(0)
    extra_price: Decimal = Decimal(0)
    volume_divisor: int = Field(default=6000, ge=1)
    min_charge: Decimal = Decimal(0)
    surcharge: Decimal = Decimal(0)
    transit_days: int = Field(default=10, ge=0)
    status: str = "active"
    remark: str | None = None


class ChannelUpdate(Schema):
    provider_id: int | None = None
    code: str | None = None
    name: str | None = None
    usage: str | None = None
    transport_mode: str | None = None
    billing_type: str | None = None
    currency: str | None = None
    unit_price: Decimal | None = None
    first_weight_kg: Decimal | None = None
    first_price: Decimal | None = None
    extra_unit_kg: Decimal | None = None
    extra_price: Decimal | None = None
    volume_divisor: int | None = Field(default=None, ge=1)
    min_charge: Decimal | None = None
    surcharge: Decimal | None = None
    transit_days: int | None = Field(default=None, ge=0)
    status: str | None = None
    remark: str | None = None


class FreightQuoteIn(Schema):
    weight_kg: Decimal = Field(ge=0, description="实重 kg")
    length_cm: Decimal = Decimal(0)
    width_cm: Decimal = Decimal(0)
    height_cm: Decimal = Decimal(0)
    volume_cbm: Decimal | None = Field(default=None, description="体积 m³（多箱合计时直接传入）")
    pieces: int = Field(default=1, ge=1)
    channel_ids: list[int] | None = Field(default=None, description="为空则对所有启用渠道报价")


class FreightQuoteOut(Schema):
    channel_id: int
    channel_name: str
    provider_name: str | None = None
    transport_mode: str
    chargeable_weight_kg: Money
    freight: Money
    currency: str
    freight_base: Money
    transit_days: int
