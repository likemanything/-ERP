from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import Field
from sqlalchemy import select

from app.common.pagination import PageParams, page_params, paginate
from app.common.schemas import ORMOut, Page, Schema
from app.core.db import tenant_session
from app.core.deps import Ctx, perm, system_ctx
from app.core.errors import BizError
from app.integrations.base import ALL_JOB_TYPES
from app.integrations.registry import platform_capabilities
from app.modules.integration import service
from app.modules.integration.models import SyncJob
from app.modules.shop.models import Shop

router = APIRouter(tags=["平台对接"])


class SyncIn(Schema):
    job_types: list[str] | None = Field(default=None, description="orders/listings/fba_inventory/finances/ads，为空全部")
    background: bool = True


class SyncJobOut(ORMOut):
    shop_id: int
    shop_name: str | None = None
    job_type: str
    status: str
    trigger: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    stats: dict | None = None
    error: str | None = None


def _run_in_background(tenant_id: int, user_id: int | None, shop_id: int, job_types: list[str] | None) -> None:
    with tenant_session(tenant_id, user_id) as db:
        service.sync_shop(system_ctx(db, tenant_id), shop_id, job_types, trigger="manual")


@router.get("/integrations/platforms", summary="已接入平台及能力")
def platforms(_: Ctx = Depends(perm("shop:view"))):
    return platform_capabilities()


@router.post("/shops/{shop_id}/test-connection", summary="测试平台授权")
def test_connection(shop_id: int, ctx: Ctx = Depends(perm("shop:edit"))):
    ctx.require_shop(shop_id)
    return service.test_connection(ctx, shop_id)


@router.post("/shops/{shop_id}/sync", summary="立即同步店铺数据")
def sync(shop_id: int, body: SyncIn, background: BackgroundTasks, ctx: Ctx = Depends(perm("shop:sync"))):
    ctx.require_shop(shop_id)
    shop = ctx.db.get(Shop, shop_id)
    if shop is None:
        raise BizError("店铺不存在")
    if body.job_types:
        bad = set(body.job_types) - set(ALL_JOB_TYPES)
        if bad:
            raise BizError(f"无效的同步类型: {', '.join(bad)}")
    if body.background:
        background.add_task(_run_in_background, ctx.tenant_id, ctx.user_id, shop_id, body.job_types)
        return {"message": "已提交后台同步", "queued": True}
    jobs = service.sync_shop(ctx, shop_id, body.job_types)
    return {"message": "同步完成", "queued": False,
            "jobs": [{"job_type": j.job_type, "status": j.status, "stats": j.stats, "error": j.error} for j in jobs]}


@router.get("/sync-jobs", response_model=Page[SyncJobOut], summary="同步记录")
def list_jobs(
    shop_id: int | None = None,
    status: str | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("shop:view")),
):
    stmt = select(SyncJob).order_by(SyncJob.id.desc())
    if shop_id:
        stmt = stmt.where(SyncJob.shop_id == shop_id)
    if status:
        stmt = stmt.where(SyncJob.status == status)
    if ctx.shop_ids is not None:
        stmt = stmt.where(SyncJob.shop_id.in_(ctx.shop_ids))
    page = paginate(ctx.db, stmt, params)
    names = dict(ctx.db.execute(select(Shop.id, Shop.name)).all())
    page["items"] = [{**{c.key: getattr(j, c.key) for c in SyncJob.__table__.columns}, "shop_name": names.get(j.shop_id)}
                     for j in page["items"]]
    return page
