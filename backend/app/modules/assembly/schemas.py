from datetime import date, datetime

from pydantic import Field

from app.common.schemas import ORMOut, Schema
from app.core.types import Money


class AssemblyLineIn(Schema):
    product_id: int
    qty_per_unit: int = Field(default=1, ge=1)


class AssemblyIn(Schema):
    order_type: str = Field(default="assemble", pattern="^(assemble|disassemble)$")
    warehouse_id: int
    product_id: int
    qty: int = Field(ge=1)
    processing_fee: float = Field(default=0, ge=0)
    plan_date: date | None = None
    remark: str | None = None
    lines: list[AssemblyLineIn] = Field(min_length=1)


class AssemblyUpdate(Schema):
    order_type: str | None = Field(default=None, pattern="^(assemble|disassemble)$")
    warehouse_id: int | None = None
    product_id: int | None = None
    qty: int | None = Field(default=None, ge=1)
    processing_fee: float | None = Field(default=None, ge=0)
    plan_date: date | None = None
    remark: str | None = None
    lines: list[AssemblyLineIn] | None = None


class AssemblyLineOut(Schema):
    id: int
    product_id: int
    sku: str | None = None
    name: str | None = None
    image_url: str | None = None
    qty_per_unit: int
    qty: int
    available: int | None = None
    unit_cost: Money | None = None
    amount: Money | None = None


class AssemblyOut(ORMOut):
    order_no: str
    order_type: str
    warehouse_id: int
    warehouse_name: str | None = None
    product_id: int
    sku: str | None = None
    product_name: str | None = None
    image_url: str | None = None
    qty: int
    processing_fee: Money
    status: str
    plan_date: date | None = None
    completed_at: datetime | None = None
    unit_cost: Money | None = None
    total_cost: Money | None = None
    remark: str | None = None
    lines: list[AssemblyLineOut] = []
