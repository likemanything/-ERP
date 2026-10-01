"""数据库引擎、ORM 基类、通用 Mixin 以及多租户自动隔离。

多租户隔离策略：
* 所有业务表继承 ``TenantMixin``，带 ``tenant_id`` 列。
* 每个请求的 Session 在认证后写入 ``session.info["tenant_id"]``。
* ``do_orm_execute`` 事件为所有 ORM 查询自动追加 ``tenant_id = :tid`` 条件，
  ``before_flush`` 事件为新对象自动填充 tenant_id 并阻止跨租户写入。
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Integer, MetaData, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    ORMExecuteState,
    Session,
    declared_attr,
    mapped_column,
    sessionmaker,
    with_loader_criteria,
)

from app.core.config import settings
from app.core.types import UTCDateTime, utcnow

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# SQLite 仅对 INTEGER PRIMARY KEY 自增，因此主键在 SQLite 下退化为 Integer
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IdMixin:
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class TenantMixin:
    @declared_attr
    def tenant_id(cls) -> Mapped[int]:  # noqa: N805
        return mapped_column(BigInteger, ForeignKey("tenants.id"), index=True, nullable=False)


class AuditMixin:
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class BaseModel(Base, IdMixin, TimestampMixin):
    __abstract__ = True


class TenantModel(Base, IdMixin, TimestampMixin, TenantMixin, AuditMixin):
    """绝大多数业务表的基类：自增主键 + 时间戳 + 租户 + 操作人。"""

    __abstract__ = True


def _make_engine(url: str) -> Engine:
    kwargs: dict = {"echo": settings.db_echo, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(pool_pre_ping=True, pool_size=10, max_overflow=20)
    eng = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _sqlite_pragma(dbapi_conn, _):  # pragma: no cover - 简单设置
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return eng


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class TenantViolation(RuntimeError):
    pass


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_filter(state: ORMExecuteState) -> None:
    if state.execution_options.get("skip_tenant_filter", False):
        return
    tid = state.session.info.get("tenant_id")
    if tid is None:
        return
    if (state.is_select and not state.is_column_load and not state.is_relationship_load) or state.is_update or state.is_delete:
        state.statement = state.statement.options(
            with_loader_criteria(TenantMixin, lambda cls: cls.tenant_id == tid, include_aliases=True)
        )


@event.listens_for(Session, "before_flush")
def _before_flush(session: Session, _ctx, _instances) -> None:
    tid = session.info.get("tenant_id")
    uid = session.info.get("user_id")
    for obj in session.new:
        if isinstance(obj, TenantMixin):
            if getattr(obj, "tenant_id", None) is None:
                if tid is None:
                    raise TenantViolation(f"创建 {type(obj).__name__} 时未设置租户")
                obj.tenant_id = tid
            elif tid is not None and obj.tenant_id != tid:
                raise TenantViolation("禁止跨租户写入数据")
        if isinstance(obj, AuditMixin) and getattr(obj, "created_by", None) is None:
            obj.created_by = uid
    for obj in session.dirty:
        if isinstance(obj, TenantMixin) and tid is not None and obj.tenant_id != tid:
            raise TenantViolation("禁止跨租户修改数据")
        if isinstance(obj, AuditMixin) and uid is not None and session.is_modified(obj, include_collections=False):
            obj.updated_by = uid
    for obj in session.deleted:
        if isinstance(obj, TenantMixin) and tid is not None and obj.tenant_id != tid:
            raise TenantViolation("禁止跨租户删除数据")


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def tenant_session(tenant_id: int | None, user_id: int | None = None) -> Iterator[Session]:
    """后台任务 / 脚本使用：创建绑定指定租户的会话。"""
    db = SessionLocal()
    db.info["tenant_id"] = tenant_id
    db.info["user_id"] = user_id
    try:
        yield db
    finally:
        db.close()
