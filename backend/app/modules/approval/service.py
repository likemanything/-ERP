"""多级审批引擎。

业务单据提交时调用 :func:`start`：按单据类型 + 金额（本位币）匹配启用的审批流程，
命中则生成审批实例并通知第一级审批人；未命中返回 None，业务沿用原有的单级审批（按权限）。

审批 / 驳回时调用 :func:`act`：
* 返回 ``None``：该单据没有进行中的审批实例（走原有逻辑）
* ``"pending"``：本级已记录，等待本级其他人（会签）或下一级
* ``"approved"`` / ``"rejected"``：流程结束，调用方执行单据自身的通过 / 驳回逻辑
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.common.currency import to_base
from app.core.deps import Ctx
from app.core.errors import BizError, Forbidden
from app.core.types import q2, utcnow
from app.modules.approval.models import ApprovalFlow, ApprovalInstance, ApprovalRecord
from app.modules.system.models import Notification, User, UserRole

DOC_TYPES: dict[str, str] = {
    "purchase_order": "采购单",
    "payment_request": "请款单",
    "recharge": "分销商充值",
}


def validate_steps(db, steps: list[dict]) -> list[dict]:
    if not steps:
        raise BizError("请至少配置一个审批节点")
    out = []
    for i, st in enumerate(steps, 1):
        kind = st.get("approver_type") or "user"
        ids = [int(x) for x in st.get("approver_ids") or []]
        if kind not in ("user", "role"):
            raise BizError(f"第 {i} 级：审批人类型无效")
        if not ids:
            raise BizError(f"第 {i} 级：请选择审批人")
        mode = st.get("mode") or "any"
        if mode not in ("any", "all"):
            raise BizError(f"第 {i} 级：审批方式无效")
        if kind == "user":
            found = set(db.execute(select(User.id).where(User.id.in_(ids), User.user_type == "staff")).scalars().all())
            if missing := set(ids) - found:
                raise BizError(f"第 {i} 级：审批人不存在（ID={sorted(missing)}）")
        out.append({"name": (st.get("name") or f"第{i}级审批").strip(), "approver_type": kind, "approver_ids": ids, "mode": mode})
    return out


def match_flow(db, doc_type: str, amount_base: Decimal) -> ApprovalFlow | None:
    flows = db.execute(
        select(ApprovalFlow).where(ApprovalFlow.doc_type == doc_type, ApprovalFlow.is_active.is_(True))
        .order_by(ApprovalFlow.min_amount.desc(), ApprovalFlow.id.desc())
    ).scalars().all()
    return next((f for f in flows if f.steps and amount_base >= Decimal(f.min_amount or 0)), None)


def _amount_base(db, amount, currency: str | None) -> Decimal:
    try:
        return q2(to_base(db, amount, currency) if currency else Decimal(str(amount or 0)))
    except BizError:  # 缺少汇率时按原币比较
        return q2(Decimal(str(amount or 0)))


def requires_approval(db, doc_type: str, amount, currency: str | None) -> bool:
    return match_flow(db, doc_type, _amount_base(db, amount, currency)) is not None


def step_approvers(db, step: dict) -> set[int]:
    ids = [int(x) for x in step.get("approver_ids") or []]
    if step.get("approver_type") == "role":
        rows = db.execute(
            select(UserRole.user_id).join(User, User.id == UserRole.user_id)
            .where(UserRole.role_id.in_(ids), User.is_active.is_(True))
        ).scalars().all()
        return set(rows)
    return set(ids)


def _notify(db, inst: ApprovalInstance, user_ids: set[int], title: str) -> None:
    for uid in user_ids:
        db.add(Notification(user_id=uid, category="approval", title=title, content=inst.summary, link="/approvals"))


def _notify_step(db, inst: ApprovalInstance) -> None:
    step = inst.steps[inst.current_step]
    label = DOC_TYPES.get(inst.doc_type, inst.doc_type)
    _notify(db, inst, step_approvers(db, step), f"{label} {inst.doc_no or ''} 待您审批（{step['name']}）")


def pending_instance(db, doc_type: str, doc_id: int, *, lock: bool = False) -> ApprovalInstance | None:
    stmt = select(ApprovalInstance).where(ApprovalInstance.doc_type == doc_type, ApprovalInstance.doc_id == doc_id,
                                          ApprovalInstance.status == "pending")
    if lock:
        stmt = stmt.with_for_update(of=ApprovalInstance)
    return db.execute(stmt.order_by(ApprovalInstance.id.desc())).scalars().first()


def cancel_pending(db, doc_type: str, doc_id: int) -> None:
    for inst in db.execute(select(ApprovalInstance).where(
            ApprovalInstance.doc_type == doc_type, ApprovalInstance.doc_id == doc_id,
            ApprovalInstance.status == "pending")).scalars().all():
        inst.status = "cancelled"
        inst.finished_at = utcnow()


def start(ctx: Ctx, doc_type: str, doc_id: int, *, doc_no: str | None, amount, currency: str | None,
          summary: str, link: str | None = None, submitter_name: str | None = None) -> ApprovalInstance | None:
    """单据提交审批：命中流程则创建审批实例，否则返回 None。"""
    db = ctx.db
    amount_base = _amount_base(db, amount, currency)
    flow = match_flow(db, doc_type, amount_base)
    if flow is None:
        return None
    cancel_pending(db, doc_type, doc_id)
    user = ctx.user
    staff = getattr(user, "user_type", "staff") == "staff" and getattr(user, "id", None)
    inst = ApprovalInstance(
        doc_type=doc_type, doc_id=doc_id, doc_no=doc_no, flow_id=flow.id, flow_name=flow.name,
        steps=[dict(s) for s in flow.steps], current_step=0, status="pending", amount=q2(Decimal(str(amount or 0))),
        currency=currency, amount_base=amount_base, summary=summary[:255], link=link,
        submitted_by=user.id if staff else None,
        submitter_name=submitter_name or getattr(user, "real_name", None) or getattr(user, "username", None),
    )
    db.add(inst)
    db.flush()
    _notify_step(db, inst)
    return inst


def _step_done(db, inst: ApprovalInstance, step: dict) -> bool:
    approved = {r.user_id for r in inst.records if r.step_index == inst.current_step and r.action == "approve"}
    if step.get("mode") != "all":
        return bool(approved)
    if step.get("approver_type") == "role":
        for role_id in step["approver_ids"]:
            members = step_approvers(db, {"approver_type": "role", "approver_ids": [role_id]})
            if members and not (members & approved):
                return False
        return True
    return set(step["approver_ids"]) <= approved


def act(ctx: Ctx, doc_type: str, doc_id: int, approve: bool, comment: str | None = None) -> str | None:
    """记录当前用户的审批意见。不提交事务，由调用方统一提交。"""
    db = ctx.db
    inst = pending_instance(db, doc_type, doc_id, lock=True)
    if inst is None:
        return None
    step = inst.steps[inst.current_step]
    user = ctx.user
    is_approver = user.id in step_approvers(db, step)
    if not is_approver and not user.is_superuser:
        raise Forbidden(f"您不是当前审批节点「{step['name']}」的审批人")
    if any(r.step_index == inst.current_step and r.user_id == user.id for r in inst.records):
        raise BizError("您已审批过该节点，请等待其他审批人")
    if not approve and not (comment or "").strip():
        raise BizError("请填写驳回原因")
    override = not is_approver
    inst.records.append(ApprovalRecord(
        step_index=inst.current_step, step_name=step["name"], user_id=user.id,
        user_name=user.real_name or user.username, action="approve" if approve else "reject",
        comment=((comment or "").strip() + ("（管理员代审批）" if override else "")) or None,
    ))
    label = DOC_TYPES.get(inst.doc_type, inst.doc_type)
    submitter = {inst.submitted_by} if inst.submitted_by else set()
    if not approve:
        inst.status = "rejected"
        inst.finished_at = utcnow()
        _notify(db, inst, submitter, f"{label} {inst.doc_no or ''} 被驳回：{comment}")
        return "rejected"
    db.flush()
    if not (override or _step_done(db, inst, step)):
        return "pending"
    if inst.current_step + 1 >= len(inst.steps):
        inst.status = "approved"
        inst.finished_at = utcnow()
        _notify(db, inst, submitter, f"{label} {inst.doc_no or ''} 已审批通过")
        return "approved"
    inst.current_step += 1
    _notify_step(db, inst)
    return "pending"


def instance_out(db, inst: ApprovalInstance, user=None) -> dict:
    steps = []
    for i, st in enumerate(inst.steps):
        ids = step_approvers(db, st)
        names = dict(db.execute(select(User.id, User.real_name).where(User.id.in_(ids))).all()) if ids else {}
        state = "done" if i < inst.current_step or inst.status == "approved" else (
            "current" if i == inst.current_step and inst.status == "pending" else
            "rejected" if i == inst.current_step and inst.status == "rejected" else "waiting")
        steps.append({**st, "approver_names": [names.get(x) or str(x) for x in ids], "state": state})
    can_act = False
    if user is not None and inst.status == "pending":
        cur = inst.steps[inst.current_step]
        acted = any(r.step_index == inst.current_step and r.user_id == user.id for r in inst.records)
        can_act = not acted and (user.id in step_approvers(db, cur) or bool(user.is_superuser))
    return {
        **{c.key: getattr(inst, c.key) for c in ApprovalInstance.__table__.columns if c.key != "steps"},
        "doc_label": DOC_TYPES.get(inst.doc_type, inst.doc_type),
        "steps": steps,
        "records": [{c.key: getattr(r, c.key) for c in ApprovalRecord.__table__.columns} for r in inst.records],
        "can_act": can_act,
    }
