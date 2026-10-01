from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.audit import audit
from app.common.crud import build_crud_router, get_or_404, keyword_filter
from app.common.currency import clear_rate_cache
from app.common.pagination import PageParams, page_params, paginate
from app.common.schemas import Msg, Option, Page
from app.core.config import settings
from app.core.db import get_db
from app.core.deps import Ctx, get_any_ctx, get_ctx, perm
from app.core.errors import Conflict, Forbidden
from app.core.permissions import permission_tree
from app.modules.shop.marketplaces import CURRENCIES
from app.modules.system import service
from app.modules.system.models import AuditLog, Department, ExchangeRate, Notification, Role, Tenant, User
from app.modules.system.schemas import (
    AuditLogOut,
    ChangePasswordIn,
    DepartmentIn,
    DepartmentOut,
    DepartmentUpdate,
    ExchangeRateIn,
    ExchangeRateOut,
    ExchangeRateUpdate,
    LoginIn,
    MeOut,
    NotificationOut,
    RefreshIn,
    RegisterIn,
    ResetPasswordIn,
    RoleIn,
    RoleOut,
    RoleUpdate,
    SettingItem,
    SettingsUpdate,
    TenantOut,
    TenantUpdate,
    TokenOut,
    UserCreate,
    UserOut,
    UserUpdate,
)

auth_router = APIRouter(prefix="/auth", tags=["认证"])
router = APIRouter(prefix="/system", tags=["系统设置"])


# ------------------------------------------------------------------ 认证
@auth_router.post("/login", response_model=TokenOut, summary="登录")
def login(body: LoginIn, db: Session = Depends(get_db)):
    tokens = service.login(db, body.username, body.password)
    user = db.execute(select(User).where(User.username == body.username)).scalar_one()
    return {**tokens, "user": service.user_to_out(db, user)}


@auth_router.post("/login/form", response_model=TokenOut, include_in_schema=False)
def login_form(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    return service.login(db, form.username, form.password)


@auth_router.post("/refresh", response_model=TokenOut, summary="刷新令牌")
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    return service.refresh(db, body.refresh_token)


@auth_router.post("/register", response_model=TokenOut, summary="注册企业（开通试用）")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if not settings.allow_registration:
        raise Forbidden("当前系统未开放注册")
    _, admin = service.bootstrap_tenant(db, **body.model_dump())
    return {**service.issue_tokens(admin), "user": service.user_to_out(db, admin)}


@auth_router.get("/me", response_model=MeOut, summary="当前用户信息")
def me(ctx: Ctx = Depends(get_any_ctx)):
    tenant = ctx.db.get(Tenant, ctx.tenant_id)
    return {
        "user": service.user_to_out(ctx.db, ctx.user),
        "tenant": tenant,
        "permissions": sorted(ctx.permissions),
    }


@auth_router.post("/change-password", response_model=Msg, summary="修改密码")
def change_password(body: ChangePasswordIn, ctx: Ctx = Depends(get_any_ctx)):
    service.change_password(ctx, body.old_password, body.new_password)
    return Msg(message="密码已修改，请重新登录")


# ------------------------------------------------------------------ 企业信息
@router.get("/tenant", response_model=TenantOut, summary="企业信息")
def get_tenant(ctx: Ctx = Depends(get_ctx)):
    return ctx.db.get(Tenant, ctx.tenant_id)


@router.put("/tenant", response_model=TenantOut, summary="修改企业信息")
def update_tenant(body: TenantUpdate, ctx: Ctx = Depends(perm("system:setting"))):
    tenant = ctx.db.get(Tenant, ctx.tenant_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(tenant, k, v.upper() if k == "base_currency" and v else v)
    audit(ctx, "update", "tenant", tenant.id, "修改企业信息", {"fields": list(data)})
    ctx.db.commit()
    clear_rate_cache(ctx.db)
    return tenant


# ------------------------------------------------------------------ 用户
@router.get("/users", response_model=Page[UserOut], summary="用户列表")
def list_users(
    keyword: str | None = None,
    is_active: bool | None = None,
    dept_id: int | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("system:user")),
):
    stmt = select(User).where(User.user_type == "staff").order_by(User.id)
    stmt = keyword_filter(stmt, keyword, [User.username, User.real_name, User.phone, User.email])
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    if dept_id:
        stmt = stmt.where(User.dept_id == dept_id)
    page = paginate(ctx.db, stmt, params)
    page["items"] = [service.user_to_out(ctx.db, u) for u in page["items"]]
    return page


@router.get("/users/options", response_model=list[Option], summary="用户下拉")
def user_options(ctx: Ctx = Depends(get_ctx)):
    users = ctx.db.execute(
        select(User).where(User.is_active.is_(True), User.user_type == "staff").order_by(User.id)
    ).scalars().all()
    return [Option(value=u.id, label=u.real_name or u.username) for u in users]


@router.get("/users/{user_id}", response_model=UserOut, summary="用户详情")
def get_user(user_id: int, ctx: Ctx = Depends(perm("system:user"))):
    return service.user_to_out(ctx.db, get_or_404(ctx.db, User, user_id, "用户"))


@router.post("/users", response_model=UserOut, summary="新增用户")
def create_user(body: UserCreate, ctx: Ctx = Depends(perm("system:user"))):
    user = service.create_user(ctx, body.model_dump())
    return service.user_to_out(ctx.db, user)


@router.put("/users/{user_id}", response_model=UserOut, summary="修改用户")
def update_user(user_id: int, body: UserUpdate, ctx: Ctx = Depends(perm("system:user"))):
    user = service.update_user(ctx, user_id, body.model_dump(exclude_unset=True))
    return service.user_to_out(ctx.db, user)


@router.post("/users/{user_id}/reset-password", response_model=Msg, summary="重置密码")
def reset_password(user_id: int, body: ResetPasswordIn, ctx: Ctx = Depends(perm("system:user"))):
    service.reset_password(ctx, user_id, body.password)
    return Msg(message="密码已重置")


@router.delete("/users/{user_id}", response_model=Msg, summary="删除用户")
def delete_user(user_id: int, ctx: Ctx = Depends(perm("system:user"))):
    service.delete_user(ctx, user_id)
    return Msg(message="已删除")


# ------------------------------------------------------------------ 角色与权限
@router.get("/permissions", summary="权限树")
def get_permissions(_: Ctx = Depends(get_ctx)):
    return permission_tree()


@router.get("/roles", response_model=list[RoleOut], summary="角色列表")
def list_roles(ctx: Ctx = Depends(perm("system:role"))):
    return ctx.db.execute(select(Role).order_by(Role.id)).scalars().all()


@router.get("/roles/options", response_model=list[Option], summary="角色下拉")
def role_options(ctx: Ctx = Depends(get_ctx)):
    return [Option(value=r.id, label=r.name) for r in ctx.db.execute(select(Role).order_by(Role.id)).scalars().all()]


@router.post("/roles", response_model=RoleOut, summary="新增角色")
def create_role(body: RoleIn, ctx: Ctx = Depends(perm("system:role"))):
    return service.create_role(ctx, body.model_dump())


@router.put("/roles/{role_id}", response_model=RoleOut, summary="修改角色")
def update_role(role_id: int, body: RoleUpdate, ctx: Ctx = Depends(perm("system:role"))):
    return service.update_role(ctx, role_id, body.model_dump(exclude_unset=True))


@router.delete("/roles/{role_id}", response_model=Msg, summary="删除角色")
def delete_role(role_id: int, ctx: Ctx = Depends(perm("system:role"))):
    service.delete_role(ctx, role_id)
    return Msg(message="已删除")


# ------------------------------------------------------------------ 部门
def _dept_before_delete(ctx: Ctx, dept: Department) -> None:
    if ctx.db.execute(select(User.id).where(User.dept_id == dept.id).limit(1)).first():
        raise Conflict("部门下存在用户，无法删除")
    if ctx.db.execute(select(Department.id).where(Department.parent_id == dept.id).limit(1)).first():
        raise Conflict("存在下级部门，无法删除")


router.include_router(
    build_crud_router(
        model=Department,
        create_schema=DepartmentIn,
        update_schema=DepartmentUpdate,
        out_schema=DepartmentOut,
        resource="department",
        label="部门",
        view_perm="system:dept",
        edit_perm="system:dept",
        search_fields=("name",),
        default_order=("sort", "id"),
        before_delete=_dept_before_delete,
    ),
    prefix="/departments",
)


# ------------------------------------------------------------------ 操作日志
@router.get("/audit-logs", response_model=Page[AuditLogOut], summary="操作日志")
def list_audit_logs(
    keyword: str | None = None,
    resource: str | None = None,
    user_id: int | None = None,
    params: PageParams = Depends(page_params),
    ctx: Ctx = Depends(perm("system:log")),
):
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    stmt = keyword_filter(stmt, keyword, [AuditLog.summary, AuditLog.username, AuditLog.resource_id])
    if resource:
        stmt = stmt.where(AuditLog.resource == resource)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    return paginate(ctx.db, stmt, params)


# ------------------------------------------------------------------ 系统参数
@router.get("/settings", response_model=list[SettingItem], summary="系统参数")
def get_settings(ctx: Ctx = Depends(get_ctx)):
    return service.list_settings(ctx.db)


@router.put("/settings", response_model=list[SettingItem], summary="修改系统参数")
def put_settings(body: SettingsUpdate, ctx: Ctx = Depends(perm("system:setting"))):
    service.update_settings(ctx, body.values)
    return service.list_settings(ctx.db)


# ------------------------------------------------------------------ 汇率
@router.get("/currencies", summary="币种列表")
def currencies(_: Ctx = Depends(get_ctx)):
    return [{"code": k, "name": v} for k, v in CURRENCIES.items()]


def _rate_before_save(ctx: Ctx, obj, data: dict) -> None:
    clear_rate_cache(ctx.db)


router.include_router(
    build_crud_router(
        model=ExchangeRate,
        create_schema=ExchangeRateIn,
        update_schema=ExchangeRateUpdate,
        out_schema=ExchangeRateOut,
        resource="exchange_rate",
        label="汇率",
        view_perm="finance:rate:view",
        edit_perm="finance:rate:edit",
        search_fields=("currency", "month"),
        filter_fields=("currency", "month"),
        default_order=("-month", "currency"),
        before_save=_rate_before_save,
    ),
    prefix="/exchange-rates",
)


# ------------------------------------------------------------------ 站内消息
@router.get("/notifications", response_model=Page[NotificationOut], summary="站内消息")
def list_notifications(
    unread: bool | None = None, params: PageParams = Depends(page_params), ctx: Ctx = Depends(get_ctx)
):
    stmt = (
        select(Notification)
        .where((Notification.user_id == ctx.user_id) | (Notification.user_id.is_(None)))
        .order_by(Notification.id.desc())
    )
    if unread:
        stmt = stmt.where(Notification.is_read.is_(False))
    return paginate(ctx.db, stmt, params)


@router.post("/notifications/read-all", response_model=Msg, summary="全部已读")
def read_all(request: Request, ctx: Ctx = Depends(get_ctx)):
    ctx.db.execute(
        update(Notification)
        .where((Notification.user_id == ctx.user_id) | (Notification.user_id.is_(None)))
        .values(is_read=True)
    )
    ctx.db.commit()
    return Msg()
