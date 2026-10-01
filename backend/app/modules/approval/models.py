from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import TenantModel
from app.core.types import MoneyColumn, UTCDateTime


class ApprovalFlow(TenantModel):
    """审批流程：按单据类型 + 金额门槛匹配，支持多级审批（每级可指定人员或角色，或签 / 会签）。"""

    __tablename__ = "approval_flows"
    __label__ = "审批流程"

    doc_type: Mapped[str] = mapped_column(String(32), index=True, doc="purchase_order/payment_request/recharge")
    name: Mapped[str] = mapped_column(String(64))
    min_amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="金额（本位币）≥ 该值时适用；多个流程取门槛最高的")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    steps: Mapped[list] = mapped_column(JSON, doc="[{name, approver_type: user|role, approver_ids: [], mode: any|all}]")
    remark: Mapped[str | None] = mapped_column(String(255))


class ApprovalInstance(TenantModel):
    """单据的一次审批过程（提交时按流程快照生成）。"""

    __tablename__ = "approval_instances"
    __table_args__ = (Index("ix_approval_instances_doc", "doc_type", "doc_id"),)

    doc_type: Mapped[str] = mapped_column(String(32))
    doc_id: Mapped[int] = mapped_column(BigInteger)
    doc_no: Mapped[str | None] = mapped_column(String(64))
    flow_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("approval_flows.id", ondelete="SET NULL"))
    flow_name: Mapped[str] = mapped_column(String(64))
    steps: Mapped[list] = mapped_column(JSON)
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True, doc="pending/approved/rejected/cancelled")
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    currency: Mapped[str | None] = mapped_column(String(8))
    amount_base: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    summary: Mapped[str | None] = mapped_column(String(255))
    link: Mapped[str | None] = mapped_column(String(255))
    submitted_by: Mapped[int | None] = mapped_column(BigInteger)
    submitter_name: Mapped[str | None] = mapped_column(String(64))
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    records: Mapped[list["ApprovalRecord"]] = relationship(
        back_populates="instance", cascade="all, delete-orphan", lazy="selectin", order_by="ApprovalRecord.id"
    )


class ApprovalRecord(TenantModel):
    __tablename__ = "approval_records"

    instance_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("approval_instances.id", ondelete="CASCADE"), index=True)
    step_index: Mapped[int] = mapped_column(Integer)
    step_name: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    user_name: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(16), doc="approve/reject")
    comment: Mapped[str | None] = mapped_column(String(500))

    instance: Mapped[ApprovalInstance] = relationship(back_populates="records")
