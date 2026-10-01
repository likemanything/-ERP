import secrets
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.common.audit import audit
from app.common.crud import ensure_unique, get_or_404
from app.core.config import settings
from app.core.deps import Ctx
from app.core.errors import BizError, Conflict, Forbidden, Unauthorized
from app.core.permissions import ALL_PERMISSION_CODES, PRESET_ROLES
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.core.types import utcnow
from app.modules.system.models import (
    ExchangeRate,
    Role,
    SystemSetting,
    Tenant,
    User,
    UserRole,
    UserShop,
)
from app.modules.system.settings_registry import SETTING_MAP


# ---------------------------------------------------------------- 认证
def login(db: Session, username: str, password: str) -> dict:
    user = db.execute(
        select(User).where(User.username == username).execution_options(skip_tenant_filter=True)
    ).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        raise Unauthorized("用户名或密码错误")
    if not user.is_active:
        raise Unauthorized("账号已被禁用")
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None or not tenant.is_active:
        raise Unauthorized("企业账号已停用")
    db.info["tenant_id"] = user.tenant_id
    db.info["user_id"] = user.id
    user.last_login_at = utcnow()
    db.commit()
    return issue_tokens(user)


def issue_tokens(user: User) -> dict:
    return {
        "access_token": create_token(user.id, user.tenant_id, "access", user.token_version),
        "refresh_token": create_token(user.id, user.tenant_id, "refresh", user.token_version),
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
    }


def refresh(db: Session, refresh_token: str) -> dict:
    try:
        payload = decode_token(refresh_token)
    except Exception as exc:  # noqa: BLE001
        raise Unauthorized("刷新凭证无效或已过期") from exc
    if payload.get("type") != "refresh":
        raise Unauthorized("刷新凭证类型错误")
    user = db.execute(
        select(User).where(User.id == int(payload["sub"])).execution_options(skip_tenant_filter=True)
    ).scalar_one_or_none()
    if user is None or not user.is_active or user.token_version != payload.get("ver", 0):
        raise Unauthorized("用户不存在或凭证已失效")
    return issue_tokens(user)


def change_password(ctx: Ctx, old_password: str, new_password: str) -> None:
    if not verify_password(old_password, ctx.user.password_hash):
        raise BizError("原密码不正确")
    ctx.user.password_hash = hash_password(new_password)
    ctx.user.token_version += 1
    audit(ctx, "change_password", "user", ctx.user.id, "修改密码")
    ctx.db.commit()


# ---------------------------------------------------------------- 企业开通
def bootstrap_tenant(
    db: Session,
    *,
    company_name: str,
    username: str,
    password: str,
    real_name: str = "",
    phone: str | None = None,
    base_currency: str = "CNY",
) -> tuple[Tenant, User]:
    """创建企业并初始化：预置角色、管理员、默认仓库、汇率、补货默认规则。"""
    from app.modules.replenishment.models import ReplenishmentRule
    from app.modules.shop.marketplaces import DEFAULT_RATES_TO_CNY
    from app.modules.warehouse.models import Warehouse

    exists = db.execute(
        select(User.id).where(User.username == username).execution_options(skip_tenant_filter=True)
    ).first()
    if exists:
        raise Conflict(f"用户名 {username} 已被占用")

    tenant = Tenant(
        code="T" + secrets.token_hex(4).upper(),
        name=company_name,
        base_currency=base_currency.upper(),
        timezone=settings.default_timezone,
        contact_name=real_name or username,
        contact_phone=phone,
    )
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id

    for code, (name, perms) in PRESET_ROLES.items():
        db.add(Role(code=code, name=name, permissions=perms, is_system=True, description=f"预置角色：{name}"))

    admin = User(
        username=username,
        password_hash=hash_password(password),
        real_name=real_name or "管理员",
        phone=phone,
        is_superuser=True,
        all_shops=True,
    )
    db.add(admin)
    db.flush()
    db.info["user_id"] = admin.id

    db.add(Warehouse(code="WH001", name="默认仓库", warehouse_type="local", country="CN", is_default=True))
    if tenant.base_currency == "CNY":
        month = date.today().strftime("%Y-%m")
        for cur, rate in DEFAULT_RATES_TO_CNY.items():
            db.add(ExchangeRate(currency=cur, month=month, rate=Decimal(rate), remark="系统默认参考汇率"))
    db.add(ReplenishmentRule(listing_id=None))
    db.commit()
    return tenant, admin


# ---------------------------------------------------------------- 用户
def user_to_out(db: Session, user: User) -> dict:
    shop_ids = db.execute(select(UserShop.shop_id).where(UserShop.user_id == user.id)).scalars().all()
    return {
        "id": user.id,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "username": user.username,
        "real_name": user.real_name,
        "email": user.email,
        "phone": user.phone,
        "dept_id": user.dept_id,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "all_shops": user.all_shops,
        "last_login_at": user.last_login_at,
        "roles": [{"id": r.id, "code": r.code, "name": r.name} for r in user.roles],
        "shop_ids": list(shop_ids),
    }


def _set_user_roles(db: Session, user: User, role_ids: list[int]) -> None:
    valid = set(db.execute(select(Role.id).where(Role.id.in_(role_ids))).scalars().all()) if role_ids else set()
    if set(role_ids) - valid:
        raise BizError("包含无效的角色")
    db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    for rid in valid:
        db.add(UserRole(user_id=user.id, role_id=rid))


def _set_user_shops(db: Session, user: User, shop_ids: list[int]) -> None:
    from app.modules.shop.models import Shop

    valid = set(db.execute(select(Shop.id).where(Shop.id.in_(shop_ids))).scalars().all()) if shop_ids else set()
    if set(shop_ids) - valid:
        raise BizError("包含无效的店铺")
    db.execute(delete(UserShop).where(UserShop.user_id == user.id))
    for sid in valid:
        db.add(UserShop(user_id=user.id, shop_id=sid))


def create_user(ctx: Ctx, data: dict) -> User:
    db = ctx.db
    exists = db.execute(
        select(User.id).where(User.username == data["username"]).execution_options(skip_tenant_filter=True)
    ).first()
    if exists:
        raise Conflict(f"用户名 {data['username']} 已被占用")
    if data.get("is_superuser") and not ctx.is_admin:
        raise Forbidden("仅管理员可创建管理员账号")
    role_ids = data.pop("role_ids", [])
    shop_ids = data.pop("shop_ids", [])
    password = data.pop("password")
    user = User(**data, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    _set_user_roles(db, user, role_ids)
    _set_user_shops(db, user, shop_ids)
    audit(ctx, "create", "user", user.id, f"新增用户 {user.username}")
    db.commit()
    db.refresh(user)
    return user


def update_user(ctx: Ctx, user_id: int, data: dict) -> User:
    db = ctx.db
    user = get_or_404(db, User, user_id, "用户")
    if "is_superuser" in data and data["is_superuser"] != user.is_superuser and not ctx.is_admin:
        raise Forbidden("仅管理员可调整管理员身份")
    if user.id == ctx.user.id and data.get("is_active") is False:
        raise BizError("不能禁用当前登录账号")
    if user.id == ctx.user.id and data.get("is_superuser") is False:
        raise BizError("不能取消自己的管理员身份")
    role_ids = data.pop("role_ids", None)
    shop_ids = data.pop("shop_ids", None)
    deactivated = data.get("is_active") is False and user.is_active
    for k, v in data.items():
        setattr(user, k, v)
    if deactivated:
        user.token_version += 1
    if role_ids is not None:
        _set_user_roles(db, user, role_ids)
    if shop_ids is not None:
        _set_user_shops(db, user, shop_ids)
    audit(ctx, "update", "user", user.id, f"修改用户 {user.username}", {"fields": list(data.keys())})
    db.commit()
    db.expire(user)
    db.refresh(user)
    return user


def reset_password(ctx: Ctx, user_id: int, password: str) -> None:
    user = get_or_404(ctx.db, User, user_id, "用户")
    user.password_hash = hash_password(password)
    user.token_version += 1
    audit(ctx, "reset_password", "user", user.id, f"重置用户 {user.username} 密码")
    ctx.db.commit()


def delete_user(ctx: Ctx, user_id: int) -> None:
    user = get_or_404(ctx.db, User, user_id, "用户")
    if user.id == ctx.user.id:
        raise BizError("不能删除当前登录账号")
    ctx.db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    ctx.db.execute(delete(UserShop).where(UserShop.user_id == user.id))
    ctx.db.delete(user)
    audit(ctx, "delete", "user", user_id, f"删除用户 {user.username}")
    ctx.db.commit()


# ---------------------------------------------------------------- 角色
def validate_permissions(perms: list[str]) -> list[str]:
    invalid = [p for p in perms if p not in ALL_PERMISSION_CODES]
    if invalid:
        raise BizError(f"无效的权限编码: {', '.join(invalid)}")
    return sorted(set(perms))


def create_role(ctx: Ctx, data: dict) -> Role:
    ensure_unique(ctx.db, Role, "code", data["code"], label="角色编码")
    data["permissions"] = validate_permissions(data.get("permissions", []))
    role = Role(**data)
    ctx.db.add(role)
    ctx.db.flush()
    audit(ctx, "create", "role", role.id, f"新增角色 {role.name}")
    ctx.db.commit()
    return role


def update_role(ctx: Ctx, role_id: int, data: dict) -> Role:
    role = get_or_404(ctx.db, Role, role_id, "角色")
    if "permissions" in data and data["permissions"] is not None:
        data["permissions"] = validate_permissions(data["permissions"])
    for k, v in data.items():
        if v is not None:
            setattr(role, k, v)
    audit(ctx, "update", "role", role.id, f"修改角色 {role.name}")
    ctx.db.commit()
    return role


def delete_role(ctx: Ctx, role_id: int) -> None:
    role = get_or_404(ctx.db, Role, role_id, "角色")
    in_use = ctx.db.execute(select(UserRole.id).where(UserRole.role_id == role.id).limit(1)).first()
    if in_use:
        raise Conflict("角色已分配给用户，请先解除")
    ctx.db.delete(role)
    audit(ctx, "delete", "role", role_id, f"删除角色 {role.name}")
    ctx.db.commit()


# ---------------------------------------------------------------- 系统参数
def get_setting(db: Session, key: str) -> Any:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    if row is not None:
        return row.value
    d = SETTING_MAP.get(key)
    return d.default if d else None


def list_settings(db: Session) -> list[dict]:
    rows = {r.key: r.value for r in db.execute(select(SystemSetting)).scalars().all()}
    return [
        {"key": d.key, "value": rows.get(d.key, d.default), "label": d.label, "description": d.description}
        for d in SETTING_MAP.values()
    ]


def update_settings(ctx: Ctx, values: dict[str, Any]) -> None:
    for key, value in values.items():
        if key not in SETTING_MAP:
            raise BizError(f"未知参数: {key}")
        row = ctx.db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
        if row is None:
            ctx.db.add(SystemSetting(key=key, value=value))
        else:
            row.value = value
    audit(ctx, "update", "settings", None, "修改系统参数", {"keys": list(values.keys())})
    ctx.db.commit()
