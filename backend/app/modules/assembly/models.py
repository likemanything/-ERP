from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import TenantModel
from app.core.types import MoneyColumn, UTCDateTime


class AssemblyOrder(TenantModel):
    """加工单：组装（子件 → 成品）或拆分（成品 → 子件），按 FIFO 成本结转。"""

    __tablename__ = "assembly_orders"
    __label__ = "加工单"

    order_no: Mapped[str] = mapped_column(String(32), index=True)
    order_type: Mapped[str] = mapped_column(String(16), default="assemble", doc="assemble 组装 / disassemble 拆分")
    warehouse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("warehouses.id"), index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), index=True, doc="成品")
    qty: Mapped[int] = mapped_column(Integer)
    processing_fee: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="加工费合计（本位币），计入成品 / 子件成本")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True, doc="draft/completed/cancelled")
    plan_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_by: Mapped[int | None] = mapped_column(BigInteger)
    unit_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="组装：成品单位成本；拆分：成品出库单位成本")
    total_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    remark: Mapped[str | None] = mapped_column(String(500))

    lines: Mapped[list["AssemblyLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin", order_by="AssemblyLine.id"
    )


class AssemblyLine(TenantModel):
    __tablename__ = "assembly_lines"

    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("assembly_orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"))
    qty_per_unit: Mapped[int] = mapped_column(Integer, default=1, doc="每件成品用量")
    qty: Mapped[int] = mapped_column(Integer, doc="合计数量")
    unit_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="实际单位成本（本位币）")
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)

    order: Mapped[AssemblyOrder] = relationship(back_populates="lines")
