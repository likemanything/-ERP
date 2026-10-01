from dataclasses import dataclass

from fastapi import Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


@dataclass
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=500, description="每页数量"),
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


def paginate(db: Session, stmt: Select, params: PageParams, *, scalars: bool = True) -> dict:
    """对任意 select 语句分页，返回 {items,total,page,page_size}。"""
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = db.execute(count_stmt).scalar_one()
    result = db.execute(stmt.limit(params.page_size).offset(params.offset))
    items = list(result.scalars().unique().all()) if scalars else list(result.all())
    return {"items": items, "total": total, "page": params.page, "page_size": params.page_size}
