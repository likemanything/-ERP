from pydantic import Field

from app.common.schemas import ORMOut, Schema


class SupplierOut(ORMOut):
    code: str
    name: str
    contact: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    website: str | None = None
    settlement_type: str
    payment_days: int
    currency: str
    bank_name: str | None = None
    bank_account: str | None = None
    account_name: str | None = None
    tax_no: str | None = None
    rating: int
    status: str
    purchaser_id: int | None = None
    remark: str | None = None


class SupplierIn(Schema):
    code: str | None = Field(default=None, max_length=32, description="为空自动生成")
    name: str = Field(min_length=1, max_length=128)
    contact: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    website: str | None = None
    settlement_type: str = "cash"
    payment_days: int = Field(default=0, ge=0)
    currency: str = "CNY"
    bank_name: str | None = None
    bank_account: str | None = None
    account_name: str | None = None
    tax_no: str | None = None
    rating: int = Field(default=3, ge=1, le=5)
    status: str = "active"
    purchaser_id: int | None = None
    remark: str | None = None


class SupplierUpdate(Schema):
    code: str | None = None
    name: str | None = None
    contact: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    website: str | None = None
    settlement_type: str | None = None
    payment_days: int | None = Field(default=None, ge=0)
    currency: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None
    account_name: str | None = None
    tax_no: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    status: str | None = None
    purchaser_id: int | None = None
    remark: str | None = None
