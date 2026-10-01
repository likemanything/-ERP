from typing import Any

from app.core.deps import Ctx


def audit(ctx: Ctx, action: str, resource: str, resource_id: Any = None, summary: str | None = None, detail: dict | None = None) -> None:
    """记录操作日志（随业务事务一同提交）。"""
    from app.modules.system.models import AuditLog

    ctx.db.add(
        AuditLog(
            user_id=ctx.user.id,
            username=ctx.user.username,
            action=action,
            resource=resource,
            resource_id=str(resource_id) if resource_id is not None else None,
            summary=(summary or "")[:500] or None,
            detail=detail,
            ip=ctx.ip,
        )
    )
