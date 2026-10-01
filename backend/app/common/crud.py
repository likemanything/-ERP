"""通用 CRUD 工具与主数据路由工厂。

注意：本文件不能使用 ``from __future__ import annotations``，
因为路由工厂需要在运行期把传入的 Pydantic 类型作为注解交给 FastAPI。
"""

from collections.abc import Callable, Iterable, Sequence
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.common.audit import audit
from app.common.pagination import PageParams, page_params, paginate
from app.common.schemas import Msg, Option, Page
from app.core.deps import Ctx, perm
from app.core.errors import Conflict, NotFound


def get_or_404(db: Session, model: type, obj_id: int, label: str | None = None, *, for_update: bool = False):
    stmt = select(model).where(model.id == obj_id)
    if for_update:
        stmt = stmt.with_for_update()
    obj = db.execute(stmt).scalar_one_or_none()
    if obj is None:
        raise NotFound(f"{label or getattr(model, '__label__', model.__name__)}不存在（ID={obj_id}）")
    return obj


def apply_updates(obj: Any, data: dict, *, exclude: Iterable[str] = ()) -> Any:
    skip = set(exclude)
    for key, value in data.items():
        if key in skip:
            continue
        if hasattr(obj, key):
            setattr(obj, key, value)
    return obj


def ensure_unique(db: Session, model: type, field: str, value: Any, *, exclude_id: int | None = None, label: str = "") -> None:
    if value is None:
        return
    stmt = select(func.count()).select_from(model).where(getattr(model, field) == value)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    if db.execute(stmt).scalar_one() > 0:
        raise Conflict(f"{label or field} “{value}” 已存在")


def keyword_filter(stmt: Select, keyword: str | None, columns: Sequence) -> Select:
    if keyword:
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(*[c.ilike(kw) for c in columns]))
    return stmt


def build_crud_router(
    *,
    model: type,
    create_schema: type[BaseModel],
    update_schema: type[BaseModel],
    out_schema: type[BaseModel],
    resource: str,
    label: str,
    view_perm: str,
    edit_perm: str,
    search_fields: Sequence[str] = (),
    filter_fields: Sequence[str] = (),
    unique_fields: Sequence[str] = (),
    option_label: Callable[[Any], str] | None = None,
    default_order: Sequence[str] = ("-id",),
    before_delete: Callable[[Ctx, Any], None] | None = None,
    before_save: Callable[[Ctx, Any, dict], None] | None = None,
) -> APIRouter:
    """为简单主数据生成 列表/选项/详情/新增/修改/删除 接口。"""

    router = APIRouter()

    def _order(stmt: Select) -> Select:
        for key in default_order:
            col = getattr(model, key.lstrip("-"))
            stmt = stmt.order_by(col.desc() if key.startswith("-") else col.asc())
        return stmt

    def _filtered(request: Request, keyword: str | None) -> Select:
        stmt = select(model)
        stmt = keyword_filter(stmt, keyword, [getattr(model, f) for f in search_fields])
        for f in filter_fields:
            raw = request.query_params.get(f)
            if raw not in (None, ""):
                col = getattr(model, f)
                py_type = col.type.python_type
                if py_type is bool:
                    value: Any = raw.lower() in ("1", "true", "yes")
                elif py_type is int:
                    value = int(raw)
                else:
                    value = raw
                stmt = stmt.where(col == value)
        return _order(stmt)

    @router.get("", response_model=Page[out_schema], summary=f"{label}列表")
    def list_items(
        request: Request,
        keyword: str | None = None,
        params: PageParams = Depends(page_params),
        ctx: Ctx = Depends(perm(view_perm)),
    ):
        return paginate(ctx.db, _filtered(request, keyword), params)

    @router.get("/options", response_model=list[Option], summary=f"{label}下拉选项")
    def options(request: Request, keyword: str | None = None, ctx: Ctx = Depends(perm(view_perm))):
        rows = ctx.db.execute(_filtered(request, keyword).limit(1000)).scalars().all()
        fmt = option_label or (lambda o: getattr(o, "name", str(o.id)))
        return [Option(value=o.id, label=fmt(o)) for o in rows]

    @router.get("/{item_id}", response_model=out_schema, summary=f"{label}详情")
    def get_item(item_id: int, ctx: Ctx = Depends(perm(view_perm))):
        return get_or_404(ctx.db, model, item_id, label)

    @router.post("", response_model=out_schema, summary=f"新增{label}")
    def create_item(body: create_schema, ctx: Ctx = Depends(perm(edit_perm))):  # type: ignore[valid-type]
        data = body.model_dump()
        for f in unique_fields:
            ensure_unique(ctx.db, model, f, data.get(f), label=f"{label}{f}")
        if before_save:
            before_save(ctx, None, data)
        obj = model(**data)
        ctx.db.add(obj)
        ctx.db.flush()
        audit(ctx, "create", resource, obj.id, f"新增{label}")
        ctx.db.commit()
        ctx.db.refresh(obj)
        return obj

    @router.put("/{item_id}", response_model=out_schema, summary=f"修改{label}")
    def update_item(item_id: int, body: update_schema, ctx: Ctx = Depends(perm(edit_perm))):  # type: ignore[valid-type]
        obj = get_or_404(ctx.db, model, item_id, label)
        data = body.model_dump(exclude_unset=True)
        for f in unique_fields:
            if f in data:
                ensure_unique(ctx.db, model, f, data[f], exclude_id=obj.id, label=f"{label}{f}")
        if before_save:
            before_save(ctx, obj, data)
        apply_updates(obj, data)
        audit(ctx, "update", resource, obj.id, f"修改{label}", {"fields": list(data.keys())})
        ctx.db.commit()
        ctx.db.refresh(obj)
        return obj

    @router.delete("/{item_id}", response_model=Msg, summary=f"删除{label}")
    def delete_item(item_id: int, ctx: Ctx = Depends(perm(edit_perm))):
        obj = get_or_404(ctx.db, model, item_id, label)
        if before_delete:
            before_delete(ctx, obj)
        ctx.db.delete(obj)
        audit(ctx, "delete", resource, item_id, f"删除{label}")
        ctx.db.commit()
        return Msg(message="已删除")

    return router


def ensure_not_referenced(db: Session, checks: Sequence[tuple[type, Any, str]]) -> None:
    """删除前检查引用：checks 为 (模型, 条件, 描述)。"""
    for ref_model, condition, desc in checks:
        cnt = db.execute(select(func.count()).select_from(ref_model).where(condition)).scalar_one()
        if cnt:
            raise Conflict(f"已被{desc}引用（{cnt} 条），无法删除，可改为停用")
