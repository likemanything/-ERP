"""物流计费。"""

import math
from decimal import Decimal

from app.core.types import q2
from app.modules.logistics.models import LogisticsChannel


def volume_weight(length_cm: Decimal, width_cm: Decimal, height_cm: Decimal, divisor: int) -> Decimal:
    if not divisor:
        return Decimal(0)
    return Decimal(length_cm) * Decimal(width_cm) * Decimal(height_cm) / Decimal(divisor)


def chargeable_weight(
    channel: LogisticsChannel, weight_kg: Decimal, volume_cbm: Decimal | None = None,
    length_cm: Decimal = Decimal(0), width_cm: Decimal = Decimal(0), height_cm: Decimal = Decimal(0),
) -> Decimal:
    if volume_cbm is not None and volume_cbm > 0:
        vol_w = Decimal(volume_cbm) * Decimal(1_000_000) / Decimal(channel.volume_divisor or 6000)
    else:
        vol_w = volume_weight(length_cm, width_cm, height_cm, channel.volume_divisor)
    return max(Decimal(weight_kg), vol_w)


def calc_freight(
    channel: LogisticsChannel, *, weight_kg: Decimal, volume_cbm: Decimal | None = None,
    length_cm: Decimal = Decimal(0), width_cm: Decimal = Decimal(0), height_cm: Decimal = Decimal(0), pieces: int = 1,
) -> tuple[Decimal, Decimal]:
    """返回 (计费重, 运费[渠道币种])。"""
    cw = chargeable_weight(channel, weight_kg, volume_cbm, length_cm, width_cm, height_cm)
    if channel.billing_type == "piece":
        fee = Decimal(channel.unit_price or 0) * pieces
    elif channel.billing_type == "volume":
        vol = volume_cbm if volume_cbm is not None else (
            Decimal(length_cm) * Decimal(width_cm) * Decimal(height_cm) / Decimal(1_000_000)
        )
        fee = Decimal(channel.unit_price or 0) * Decimal(vol)
    elif channel.first_weight_kg and channel.extra_unit_kg:
        fee = Decimal(channel.first_price or 0)
        extra = cw - Decimal(channel.first_weight_kg)
        if extra > 0:
            units = math.ceil(extra / Decimal(channel.extra_unit_kg))
            fee += Decimal(units) * Decimal(channel.extra_price or 0)
    else:
        fee = Decimal(channel.unit_price or 0) * cw
    fee += Decimal(channel.surcharge or 0)
    fee = max(fee, Decimal(channel.min_charge or 0))
    return q2(cw), q2(fee)
