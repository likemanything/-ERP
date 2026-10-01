"""请求上下文与权限依赖。

用法::

    @router.get("/products")
    def list_products(ctx: Ctx = Depends(perm("product:view"))): ...
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWTError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import Forbidden, Unauthorized
from app.core.permissions import ALL_PERMISSION_CODES
from app.core.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login/form", auto_error=False)


@dataclass
class Ctx:
    db: Session
    user: "User"  # noqa: F821
    tenant_id: int
    permissions: frozenset[str]
    shop_ids: frozenset[int] | None  # None 表示全部店铺
    ip: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def user_id(self) -> int:
        return self.user.id

    @property
    def is_admin(self) -> bool:
        return bool(self.user.is_superuser)

    def can(self, code: str) -> bool:
        return self.is_admin or code in self.permissions

    def require(self, *codes: str) -> None:
        missing = [c for c in codes if not self.can(c)]
        if missing:
            raise Forbidden(f"缺少权限: {', '.join(missing)}")

    def can_access_shop(self, shop_id: int | None) -> bool:
        return self.shop_ids is None or shop_id is None or shop_id in self.shop_ids

    def require_shop(self, shop_id: int | None) -> None:
        if not self.can_access_shop(shop_id):
            raise Forbidden("无权访问该店铺数据")


def _load_ctx(request: Request, db: Session, token: str | None) -> Ctx:
    from app.modules.system.models import User, UserShop

    if not token:
        raise Unauthorized("未登录或登录已过期")
    try:
        payload = decode_token(token)
    except PyJWTError as exc:
        raise Unauthorized("登录凭证无效或已过期") from exc
    if payload.get("type") != "access":
        raise Unauthorized("登录凭证类型错误")
    user = db.execute(
        select(User).where(User.id == int(payload["sub"])).execution_options(skip_tenant_filter=True)
    ).scalar_one_or_none()
    if user is None or not user.is_active or user.token_version != payload.get("ver", 0):
        raise Unauthorized("用户不存在、已禁用或凭证已失效")
    if user.tenant_id != payload.get("tid"):
        raise Unauthorized("登录凭证无效")

    db.info["tenant_id"] = user.tenant_id
    db.info["user_id"] = user.id

    from app.modules.system.models import Tenant

    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None or not tenant.is_active:
        raise Unauthorized("企业账号已停用")

    if getattr(user, "user_type", "staff") != "staff":
        perms = frozenset()  # 分销商账号不具备任何后台权限
    elif user.is_superuser:
        perms = ALL_PERMISSION_CODES
    else:
        codes: set[str] = set()
        for role in user.roles:
            codes.update(role.permissions or [])
        perms = frozenset(codes & ALL_PERMISSION_CODES)

    shop_ids = None
    if getattr(user, "user_type", "staff") != "staff":
        shop_ids = frozenset()
    elif not user.is_superuser and not user.all_shops:
        shop_ids = frozenset(db.execute(select(UserShop.shop_id).where(UserShop.user_id == user.id)).scalars().all())

    ip = request.client.host if request.client else None
    return Ctx(db=db, user=user, tenant_id=user.tenant_id, permissions=perms, shop_ids=shop_ids, ip=ip)


def get_any_ctx(request: Request, db: Session = Depends(get_db), token: str | None = Depends(oauth2_scheme)) -> Ctx:
    """任意已登录账号（员工或分销商），仅用于 /auth/me、修改密码等通用接口。"""
    return _load_ctx(request, db, token)


def get_ctx(request: Request, db: Session = Depends(get_db), token: str | None = Depends(oauth2_scheme)) -> Ctx:
    """管理后台接口：仅允许员工账号，分销商账号一律拒绝。"""
    ctx = _load_ctx(request, db, token)
    if getattr(ctx.user, "user_type", "staff") != "staff":
        raise Forbidden("分销商账号无权访问管理后台，请使用分销商门户")
    return ctx


def perm(*codes: str) -> Callable[..., Ctx]:
    """生成要求指定权限（全部满足）的依赖。"""

    def _dep(ctx: Ctx = Depends(get_ctx)) -> Ctx:
        ctx.require(*codes)
        return ctx

    return _dep


def any_perm(*codes: str) -> Callable[..., Ctx]:
    """生成要求任意一个权限的依赖。"""

    def _dep(ctx: Ctx = Depends(get_ctx)) -> Ctx:
        if not any(ctx.can(c) for c in codes):
            raise Forbidden(f"缺少权限: {' / '.join(codes)}")
        return ctx

    return _dep


class _SystemUser:
    """后台任务使用的虚拟用户（拥有全部权限）。"""

    id = None
    username = "system"
    real_name = "系统"
    is_superuser = True
    all_shops = True
    token_version = 0
    user_type = "staff"


def system_ctx(db: Session, tenant_id: int) -> Ctx:
    db.info["tenant_id"] = tenant_id
    db.info["user_id"] = None
    return Ctx(db=db, user=_SystemUser(), tenant_id=tenant_id, permissions=ALL_PERMISSION_CODES, shop_ids=None)
