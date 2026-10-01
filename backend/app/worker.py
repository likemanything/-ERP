"""后台同步 Worker：按店铺设置的同步间隔定时拉取平台数据。

运行：python -m app.worker
多实例部署时依赖 PostgreSQL 的 SKIP LOCKED 避免重复同步同一店铺。
"""

import logging
import signal
import time
from datetime import timedelta

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.config import settings
from app.core.db import SessionLocal, engine, tenant_session
from app.core.deps import system_ctx
from app.core.types import utcnow
from app.modules.integration.service import sync_shop
from app.modules.shop.models import Shop

log = logging.getLogger("erp.worker")
_running = True


def _stop(*_):
    global _running
    _running = False


def due_shops() -> list[tuple[int, int]]:
    """返回需要同步的 (tenant_id, shop_id)。"""
    with SessionLocal() as db:
        shops = db.execute(
            select(Shop).where(Shop.sync_enabled.is_(True), Shop.status == "active").execution_options(skip_tenant_filter=True)
        ).scalars().all()
        now = utcnow()
        return [
            (s.tenant_id, s.id) for s in shops
            if s.last_sync_at is None or s.last_sync_at + timedelta(minutes=s.sync_interval_minutes or 60) <= now
        ]


def claim(tenant_id: int, shop_id: int) -> bool:
    """在 PostgreSQL 上用行锁 + 更新时间抢占，避免多个 worker 同时同步。"""
    if engine.dialect.name != "postgresql":
        return True
    with SessionLocal() as db:
        row = db.execute(
            select(Shop).where(Shop.id == shop_id).with_for_update(skip_locked=True).execution_options(skip_tenant_filter=True)
        ).scalar_one_or_none()
        if row is None:
            return False
        if row.last_sync_at and row.last_sync_at + timedelta(minutes=row.sync_interval_minutes or 60) > utcnow():
            return False
        row.last_sync_at = utcnow()
        db.commit()
        return True


def run_once() -> int:
    n = 0
    for tenant_id, shop_id in due_shops():
        if not claim(tenant_id, shop_id):
            continue
        with tenant_session(tenant_id) as db:
            try:
                sync_shop(system_ctx(db, tenant_id), shop_id, trigger="schedule")
                n += 1
            except Exception:  # noqa: BLE001
                log.exception("店铺 %s 同步异常", shop_id)
    return n


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("同步 worker 启动，轮询间隔 %ss", settings.worker_poll_seconds)
    while _running:
        try:
            n = run_once()
            if n:
                log.info("本轮同步店铺 %s 个", n)
        except Exception:  # noqa: BLE001
            log.exception("worker 轮询异常")
        for _ in range(settings.worker_poll_seconds):
            if not _running:
                break
            time.sleep(1)
    log.info("worker 已停止")


if __name__ == "__main__":
    main()
