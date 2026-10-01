from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ORMOut(Schema):
    id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Page(Schema, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class IdsIn(Schema):
    ids: list[int] = Field(min_length=1)


class Msg(Schema):
    message: str = "ok"


class Option(Schema):
    value: int | str
    label: str
