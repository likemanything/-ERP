from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.common.crud import build_crud_router, ensure_not_referenced
from app.common.currency import to_base
from app.core.deps import Ctx, perm
from app.core.types import q2
from app.modules.logistics.models import LogisticsChannel, LogisticsProvider
from app.modules.logistics.schemas import (
    ChannelIn,
    ChannelOut,
    ChannelUpdate,
    FreightQuoteIn,
    FreightQuoteOut,
    ProviderIn,
    ProviderOut,
    ProviderUpdate,
)
from app.modules.logistics.service import calc_freight

router = APIRouter(tags=["物流管理"])


def _provider_before_delete(ctx: Ctx, provider: LogisticsProvider) -> None:
    ensure_not_referenced(ctx.db, [(LogisticsChannel, LogisticsChannel.provider_id == provider.id, "物流渠道")])


def _channel_before_delete(ctx: Ctx, channel: LogisticsChannel) -> None:
    from app.modules.fba.models import FbaShipment
    from app.modules.order.models import SalesOrder

    ensure_not_referenced(
        ctx.db,
        [
            (FbaShipment, FbaShipment.logistics_channel_id == channel.id, "头程货件"),
            (SalesOrder, SalesOrder.logistics_channel_id == channel.id, "订单"),
        ],
    )


router.include_router(
    build_crud_router(
        model=LogisticsProvider, create_schema=ProviderIn, update_schema=ProviderUpdate, out_schema=ProviderOut,
        resource="logistics_provider", label="物流商", view_perm="logistics:view", edit_perm="logistics:edit",
        search_fields=("code", "name"), filter_fields=("status", "provider_type"), unique_fields=("code",),
        default_order=("id",), before_delete=_provider_before_delete,
    ),
    prefix="/logistics-providers",
)
router.include_router(
    build_crud_router(
        model=LogisticsChannel, create_schema=ChannelIn, update_schema=ChannelUpdate, out_schema=ChannelOut,
        resource="logistics_channel", label="物流渠道", view_perm="logistics:view", edit_perm="logistics:edit",
        search_fields=("code", "name"), filter_fields=("provider_id", "usage", "transport_mode", "status"),
        unique_fields=("code",), default_order=("id",), option_label=lambda c: c.name,
        before_delete=_channel_before_delete,
    ),
    prefix="/logistics-channels",
)


@router.post("/logistics/quote", response_model=list[FreightQuoteOut], summary="运费试算（多渠道比价）")
def freight_quote(body: FreightQuoteIn, ctx: Ctx = Depends(perm("logistics:view"))):
    stmt = select(LogisticsChannel).where(LogisticsChannel.status == "active")
    if body.channel_ids:
        stmt = stmt.where(LogisticsChannel.id.in_(body.channel_ids))
    result = []
    for ch in ctx.db.execute(stmt).scalars().all():
        cw, fee = calc_freight(
            ch, weight_kg=body.weight_kg, volume_cbm=body.volume_cbm, length_cm=body.length_cm,
            width_cm=body.width_cm, height_cm=body.height_cm, pieces=body.pieces,
        )
        result.append(
            {
                "channel_id": ch.id, "channel_name": ch.name, "provider_name": ch.provider.name if ch.provider else None,
                "transport_mode": ch.transport_mode, "chargeable_weight_kg": cw, "freight": fee,
                "currency": ch.currency, "freight_base": q2(to_base(ctx.db, fee, ch.currency)),
                "transit_days": ch.transit_days,
            }
        )
    result.sort(key=lambda x: x["freight_base"])
    return result
