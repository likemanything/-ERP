"""平台数据同步。"""

import logging
from datetime import timedelta

from sqlalchemy import select

from app.common.audit import audit
from app.core.deps import Ctx
from app.core.errors import BizError
from app.core.types import utcnow
from app.integrations.base import (
    ADS,
    ALL_JOB_TYPES,
    FBA_INVENTORY,
    FINANCES,
    LISTINGS,
    ORDERS,
    ConnectorError,
)
from app.integrations.registry import get_connector
from app.modules.integration.models import SyncCursor, SyncJob
from app.modules.shop.models import Shop

log = logging.getLogger("erp.sync")

DEFAULT_LOOKBACK_DAYS = {ORDERS: 30, FINANCES: 30, ADS: 30}
COMMIT_EVERY = 50


def _cursor(ctx: Ctx, shop_id: int, job_type: str) -> SyncCursor:
    cur = ctx.db.execute(
        select(SyncCursor).where(SyncCursor.shop_id == shop_id, SyncCursor.job_type == job_type)
    ).scalar_one_or_none()
    if cur is None:
        cur = SyncCursor(shop_id=shop_id, job_type=job_type)
        ctx.db.add(cur)
        ctx.db.flush()
    return cur


def _since(ctx: Ctx, shop_id: int, job_type: str):
    from datetime import datetime

    cur = _cursor(ctx, shop_id, job_type)
    if cur.cursor:
        return datetime.fromisoformat(cur.cursor)
    return utcnow() - timedelta(days=DEFAULT_LOOKBACK_DAYS.get(job_type, 30))


def sync_shop(ctx: Ctx, shop_id: int, job_types: list[str] | None = None, trigger: str = "manual", client=None) -> list[SyncJob]:
    """同步一个店铺的数据。每类数据独立事务，单类失败不影响其他类型。"""
    from app.modules.ads.router import upsert_metrics
    from app.modules.fba.router import upsert_fba_inventory
    from app.modules.finance.service import apply_transactions_to_orders, upsert_transactions
    from app.modules.order.service import upsert_order
    from app.modules.product.service import upsert_listings

    db = ctx.db
    shop = db.get(Shop, shop_id)
    if shop is None:
        raise BizError("店铺不存在")
    connector = get_connector(shop, client)
    jobs: list[SyncJob] = []
    overall_ok = True
    try:
        for job_type in job_types or list(ALL_JOB_TYPES):
            if not connector.supports(job_type):
                continue
            job = SyncJob(shop_id=shop.id, job_type=job_type, status="running", trigger=trigger, started_at=utcnow())
            db.add(job)
            db.commit()
            stats = {"created": 0, "updated": 0}
            started = utcnow()
            try:
                if job_type == LISTINGS:
                    c, u = upsert_listings(ctx, shop, list(connector.fetch_listings()))
                    stats.update(created=c, updated=u)
                elif job_type == ORDERS:
                    since = _since(ctx, shop.id, ORDERS)
                    errors: list[str] = []
                    for n, dto in enumerate(connector.fetch_orders(since - timedelta(minutes=10)), start=1):
                        try:
                            with db.begin_nested():
                                _, created = upsert_order(ctx, shop, dto)
                            stats["created" if created else "updated"] += 1
                        except BizError as exc:
                            # 单个订单失败不影响整批同步
                            errors.append(f"{dto.platform_order_id}: {exc.message}")
                        if n % COMMIT_EVERY == 0:
                            db.commit()
                    if errors:
                        stats["errors"] = len(errors)
                        stats["error_samples"] = errors[:10]
                    _cursor(ctx, shop.id, ORDERS).cursor = started.isoformat()
                elif job_type == FBA_INVENTORY:
                    stats["updated"] = upsert_fba_inventory(ctx, shop, list(connector.fetch_fba_inventory()))
                elif job_type == FINANCES:
                    since = _since(ctx, shop.id, FINANCES)
                    rows = list(connector.fetch_transactions(since - timedelta(hours=1)))
                    c, u = upsert_transactions(ctx, shop, rows)
                    stats.update(created=c, updated=u)
                    stats["fees_applied"] = apply_transactions_to_orders(
                        ctx, shop.id, list({r.platform_order_id for r in rows if r.platform_order_id}))
                    _cursor(ctx, shop.id, FINANCES).cursor = started.isoformat()
                elif job_type == ADS:
                    since = _since(ctx, shop.id, ADS)
                    # 广告归因有延迟，回看 3 天重新拉取
                    start = (since - timedelta(days=3)).date()
                    c, u = upsert_metrics(ctx, shop, list(connector.fetch_ad_metrics(start, started.date())))
                    stats.update(created=c, updated=u)
                    _cursor(ctx, shop.id, ADS).cursor = started.isoformat()
                job.status = "success"
                job.stats = stats
                job.finished_at = utcnow()
                db.commit()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                overall_ok = False
                msg = str(exc)
                log.exception("同步失败 shop=%s job=%s", shop.id, job_type)
                job = db.get(SyncJob, job.id)
                job.status = "failed"
                job.error = msg[:2000]
                job.stats = stats
                job.finished_at = utcnow()
                if isinstance(exc, ConnectorError) and exc.auth:
                    shop.status = "auth_expired"
                db.commit()
            jobs.append(job)
    finally:
        connector.close()
    shop = db.get(Shop, shop_id)
    shop.last_sync_at = utcnow()
    shop.last_sync_status = "success" if overall_ok else "failed"
    failed = [j for j in jobs if j.status == "failed"]
    shop.last_sync_message = "; ".join(f"{j.job_type}: {j.error[:120]}" for j in failed)[:500] if failed else None
    if failed:
        from app.modules.system.models import Notification

        db.add(Notification(category="sync", title=f"店铺 {shop.name} 数据同步失败",
                            content=shop.last_sync_message, link="/shops"))
    audit(ctx, "sync", "shop", shop.id, f"同步店铺 {shop.name}：" + ", ".join(f"{j.job_type}={j.status}" for j in jobs))
    db.commit()
    return jobs


def test_connection(ctx: Ctx, shop_id: int) -> dict:
    shop = ctx.db.get(Shop, shop_id)
    if shop is None:
        raise BizError("店铺不存在")
    try:
        connector = get_connector(shop)
        try:
            return connector.test_connection()
        finally:
            connector.close()
    except ConnectorError as exc:
        return {"ok": False, "message": str(exc), "auth": exc.auth}


def push_tracking(ctx: Ctx, order) -> None:
    """自发货订单发货后回传运单号到平台（失败不影响本地发货）。"""
    shop = ctx.db.get(Shop, order.shop_id)
    if shop is None or not shop.credentials_enc or not order.tracking_no:
        return
    try:
        connector = get_connector(shop)
        try:
            connector.confirm_shipment(order)
        finally:
            connector.close()
    except (ConnectorError, NotImplementedError) as exc:
        order.tags = sorted(set(order.tags or []) | {"回传失败"})
        order.remark = ((order.remark or "") + f" [回传运单失败:{exc}]")[:500]
