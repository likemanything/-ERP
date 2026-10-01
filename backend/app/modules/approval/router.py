"""审批中心：流程配置、我的待审批、单据审批记录。"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.common.audit import audit
from app.common.crud import get_or_404
from app.common.pagination import PageParams, page_params, paginate
from app.common.schemas import Msg, Page
from app.core.deps import Ctx, get_ctx, perm
from app.core.errors import BizError
from app.modules.approval import service
from app.modules.approval.models import ApprovalFlow, ApprovalInstance
from app.modules.approval.schemas import ActIn, FlowIn, FlowOut, FlowUpdate, InstanceOut

router = APIRouter(prefix="/approval", tags=["审批中心"])


@router.get("/doc-types", summary="可配置审批的单据类型")
def doc_types(_: Ctx = Depends(get_ctx)):
    return [{"value": k, "label": v} for k, v in service.DOC_TYPES.items()]


@router.get("/flows", response_model=list[FlowOut], summary="审批流程列表")
def list_flows(doc_type: str | None = None, ctx: Ctx = Depends(perm("system:approval"))):
    stmt = select(ApprovalFlow).order_by(ApprovalFlow.doc_type, ApprovalFlow.min_amount)
    if doc_type:
        stmt = stmt.where(ApprovalFlow.doc_type == doc_type)
    return ctx.db.execute(stmt).scalars().all()


@router.post("/flows", response_model=FlowOut, summary="新增审批流程")
def create_flow(body: FlowIn, ctx: Ctx = Depends(perm("system:approval"))):
    data = body.model_dump()
    data["steps"] = service.validate_steps(ctx.db, data["steps"])
    flow = ApprovalFlow(**data)
    ctx.db.add(flow)
    ctx.db.flush()
    audit(ctx, "create", "approval_flow", flow.id, f"新增审批流程 {flow.name}")
    ctx.db.commit()
    return flow


@router.put("/flows/{flow_id}", response_model=FlowOut, summary="修改审批流程（不影响进行中的审批）")
def update_flow(flow_id: int, body: FlowUpdate, ctx: Ctx = Depends(perm("system:approval"))):
    flow = get_or_404(ctx.db, ApprovalFlow, flow_id, "审批流程")
    data = body.model_dump(exclude_unset=True)
    if "steps" in data:
        data["steps"] = service.validate_steps(ctx.db, data["steps"])
    for k, v in data.items():
        setattr(flow, k, v)
    audit(ctx, "update", "approval_flow", flow.id, f"修改审批流程 {flow.name}")
    ctx.db.commit()
    return flow


@router.delete("/flows/{flow_id}", response_model=Msg, summary="删除审批流程")
def delete_flow(flow_id: int, ctx: Ctx = Depends(perm("system:approval"))):
    flow = get_or_404(ctx.db, ApprovalFlow, flow_id, "审批流程")
    pending = ctx.db.execute(select(func.count()).select_from(ApprovalInstance).where(
        ApprovalInstance.flow_id == flow.id, ApprovalInstance.status == "pending")).scalar_one()
    if pending:
        raise BizError(f"该流程有 {pending} 个进行中的审批，可先停用")
    ctx.db.delete(flow)
    audit(ctx, "delete", "approval_flow", flow_id, f"删除审批流程 {flow.name}")
    ctx.db.commit()
    return Msg(message="已删除")


def _my_pending_ids(ctx: Ctx) -> list[int]:
    """当前用户可审批的进行中实例（管理员可见全部）。"""
    rows = ctx.db.execute(select(ApprovalInstance).where(ApprovalInstance.status == "pending")).scalars().all()
    out = []
    for inst in rows:
        step = inst.steps[inst.current_step]
        acted = any(r.step_index == inst.current_step and r.user_id == ctx.user.id for r in inst.records)
        if not acted and ctx.user.id in service.step_approvers(ctx.db, step):
            out.append(inst.id)
    return out


@router.get("/pending/count", summary="我的待审批数量")
def pending_count(ctx: Ctx = Depends(get_ctx)):
    return {"count": len(_my_pending_ids(ctx))}


@router.get("/instances", response_model=Page[InstanceOut], summary="审批列表（mine=待我审批 / submitted=我提交的 / all=全部）")
def list_instances(
    scope: str = "mine",
    status: str | None = None,
    doc_type: str | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(get_ctx),
):
    stmt = select(ApprovalInstance).order_by(ApprovalInstance.id.desc())
    if scope == "mine":
        stmt = stmt.where(ApprovalInstance.id.in_(_my_pending_ids(ctx) or [0]))
    elif scope == "submitted":
        stmt = stmt.where(ApprovalInstance.submitted_by == ctx.user.id)
    elif scope == "done":
        from app.modules.approval.models import ApprovalRecord

        stmt = stmt.where(ApprovalInstance.id.in_(select(ApprovalRecord.instance_id).where(ApprovalRecord.user_id == ctx.user.id)))
    else:
        ctx.require("system:approval")
    if status:
        stmt = stmt.where(ApprovalInstance.status == status)
    if doc_type:
        stmt = stmt.where(ApprovalInstance.doc_type == doc_type)
    page = paginate(ctx.db, stmt, params)
    page["items"] = [service.instance_out(ctx.db, i, ctx.user) for i in page["items"]]
    return page


@router.get("/documents/{doc_type}/{doc_id}", response_model=list[InstanceOut], summary="单据的审批记录")
def document_history(doc_type: str, doc_id: int, ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.execute(select(ApprovalInstance).where(
        ApprovalInstance.doc_type == doc_type, ApprovalInstance.doc_id == doc_id).order_by(ApprovalInstance.id.desc())).scalars().all()
    return [service.instance_out(ctx.db, i, ctx.user) for i in rows]


@router.post("/instances/{instance_id}/act", response_model=InstanceOut, summary="审批（通过 / 驳回）")
def act(instance_id: int, body: ActIn, ctx: Ctx = Depends(get_ctx)):
    inst = get_or_404(ctx.db, ApprovalInstance, instance_id, "审批")
    if inst.status != "pending":
        raise BizError("该审批已结束")
    if inst.doc_type == "purchase_order":
        from app.modules.purchase import service as purchase

        if body.approve:
            purchase.approve_order(ctx, inst.doc_id, body.comment)
        else:
            purchase.reject_order(ctx, inst.doc_id, body.comment or "")
    elif inst.doc_type == "payment_request":
        from app.modules.purchase import service as purchase

        if body.approve:
            purchase.approve_payment(ctx, inst.doc_id, body.comment)
        else:
            purchase.reject_payment(ctx, inst.doc_id, body.comment or "")
    elif inst.doc_type == "recharge":
        from app.modules.distribution import service as dist

        dist.staff_review(ctx, inst.doc_id, body.approve, body.comment)
    else:
        raise BizError("不支持的单据类型")
    ctx.db.refresh(inst)
    return service.instance_out(ctx.db, inst, ctx.user)
