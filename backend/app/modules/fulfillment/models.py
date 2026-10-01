from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantModel
from app.core.types import UTCDateTime


class PickWave(TenantModel):
    """拣货波次：把同一发货仓的待发货订单合并拣货，按库位生成拣货单。"""

    __tablename__ = "pick_waves"
    __label__ = "拣货波次"

    wave_no: Mapped[str] = mapped_column(String(32), index=True)
    warehouse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("warehouses.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="picking", index=True, doc="picking/picked/completed/cancelled")
    order_count: Mapped[int] = mapped_column(Integer, default=0)
    sku_count: Mapped[int] = mapped_column(Integer, default=0)
    unit_count: Mapped[int] = mapped_column(Integer, default=0)
    picker_id: Mapped[int | None] = mapped_column(BigInteger, doc="拣货员")
    print_count: Mapped[int] = mapped_column(Integer, default=0)
    picked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    remark: Mapped[str | None] = mapped_column(String(255))
