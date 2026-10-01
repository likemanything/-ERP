from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import TenantModel
from app.core.types import MoneyColumn


class LogisticsProvider(TenantModel):
    """物流商 / 货代。"""

    __tablename__ = "logistics_providers"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    provider_type: Mapped[str] = mapped_column(String(16), default="forwarder", doc="express/forwarder/postal/platform")
    contact: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(32))
    website: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="active")
    remark: Mapped[str | None] = mapped_column(String(500))


class LogisticsChannel(TenantModel):
    """物流渠道及计费规则。

    计费：计费重 = max(实重, 体积重)，体积重 = 长*宽*高 / volume_divisor；
    运费 = 首重价 + ceil((计费重 - 首重) / 续重单位) * 续重价，或按 unit_price * 计费重。
    """

    __tablename__ = "logistics_channels"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    provider_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("logistics_providers.id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    usage: Mapped[str] = mapped_column(String(16), default="first_mile", doc="first_mile 头程 / last_mile 尾程 / both")
    transport_mode: Mapped[str] = mapped_column(String(16), default="express")
    billing_type: Mapped[str] = mapped_column(String(16), default="weight", doc="weight 按重量 / volume 按体积 / piece 按件")
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    unit_price: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="单价（每 kg / 每 cbm / 每件）")
    first_weight_kg: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=0)
    first_price: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    extra_unit_kg: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=0)
    extra_price: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    volume_divisor: Mapped[int] = mapped_column(Integer, default=6000)
    min_charge: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    surcharge: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="每票固定附加费")
    transit_days: Mapped[int] = mapped_column(Integer, default=10)
    status: Mapped[str] = mapped_column(String(16), default="active")
    remark: Mapped[str | None] = mapped_column(String(500))

    provider: Mapped[LogisticsProvider] = relationship(lazy="joined")
