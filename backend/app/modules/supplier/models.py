from sqlalchemy import BigInteger, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TenantModel


class Supplier(TenantModel):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    contact: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(128))
    address: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(255), doc="网店/1688 链接")
    settlement_type: Mapped[str] = mapped_column(String(16), default="cash", doc="cash 现结 / prepaid 预付 / monthly 月结 / half_monthly 半月结")
    payment_days: Mapped[int] = mapped_column(Integer, default=0, doc="账期天数")
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    bank_name: Mapped[str | None] = mapped_column(String(128))
    bank_account: Mapped[str | None] = mapped_column(String(64))
    account_name: Mapped[str | None] = mapped_column(String(128))
    tax_no: Mapped[str | None] = mapped_column(String(64))
    rating: Mapped[int] = mapped_column(Integer, default=3, doc="供应商评级 1-5")
    status: Mapped[str] = mapped_column(String(16), default="active")
    purchaser_id: Mapped[int | None] = mapped_column(BigInteger)
    remark: Mapped[str | None] = mapped_column(String(500))
