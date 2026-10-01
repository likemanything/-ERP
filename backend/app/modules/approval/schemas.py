from datetime import datetime
from decimal import Decimal

from pydantic import Field

from app.common.schemas import ORMOut, Schema
from app.core.types import Money


class StepIn(Schema):
    name: str | None = Field(default=None, max_length=64)
    approver_type: str = Field(default="user", pattern="^(user|role)$")
    approver_ids: list[int] = Field(min_length=1)
    mode: str = Field(default="any", pattern="^(any|all)$", description="any 或签：一人通过即可；all 会签：全部通过")


class FlowIn(Schema):
    doc_type: str = Field(pattern="^(purchase_order|payment_request|recharge)$")
    name: str = Field(min_length=1, max_length=64)
    min_amount: Decimal = Field(default=Decimal(0), ge=0)
    is_active: bool = True
    steps: list[StepIn] = Field(min_length=1, max_length=10)
    remark: str | None = None


class FlowUpdate(Schema):
    name: str | None = None
    min_amount: Decimal | None = Field(default=None, ge=0)
    is_active: bool | None = None
    steps: list[StepIn] | None = Field(default=None, min_length=1, max_length=10)
    remark: str | None = None


class FlowOut(ORMOut):
    doc_type: str
    name: str
    min_amount: Money
    is_active: bool
    steps: list[dict]
    remark: str | None = None


class InstanceOut(Schema):
    id: int
    doc_type: str
    doc_label: str
    doc_id: int
    doc_no: str | None = None
    flow_name: str
    current_step: int
    status: str
    amount: Money
    currency: str | None = None
    amount_base: Money
    summary: str | None = None
    link: str | None = None
    submitter_name: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
    steps: list[dict]
    records: list[dict]
    can_act: bool = False


class ActIn(Schema):
    approve: bool
    comment: str | None = Field(default=None, max_length=255)
