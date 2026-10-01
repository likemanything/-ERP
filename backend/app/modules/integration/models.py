from datetime import datetime

from sqlalchemy import JSON, BigInteger, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantModel
from app.core.types import UTCDateTime


class SyncJob(TenantModel):
    """平台数据同步任务记录。"""

    __tablename__ = "sync_jobs"

    shop_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    job_type: Mapped[str] = mapped_column(String(32), doc="orders/listings/fba_inventory/finances/ads")
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    trigger: Mapped[str] = mapped_column(String(16), default="schedule", doc="schedule/manual")
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    stats: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)


class SyncCursor(TenantModel):
    """增量同步游标。"""

    __tablename__ = "sync_cursors"
    __table_args__ = (UniqueConstraint("shop_id", "job_type"),)

    shop_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    job_type: Mapped[str] = mapped_column(String(32))
    cursor: Mapped[str | None] = mapped_column(String(255))
