# 开发指南（给后续开发者 / AI 助手）

## 命令

```bash
# 后端（backend/）
uv sync
uv run pytest -p no:logging                 # SQLite；PostgreSQL：TEST_DATABASE_URL=postgresql+psycopg://erp:erp@localhost/erp_test
uv run ruff check app tests --fix
uv run alembic revision --autogenerate -m "xxx"   # 改模型后生成迁移；用 alembic check 确认无漂移
uv run python -m app.cli seed-demo           # 演示数据 demo / demo123456
uv run uvicorn app.main:app --reload

# 前端（frontend/）
npm run dev | npm run typecheck | npm run build
```

## 约定

- 每个业务域在 `backend/app/modules/<域>/` 下分 `models.py / schemas.py / service.py / router.py`；新模型需在 `app/models.py` 导入。
- 业务表继承 `TenantModel`，**不要手写 tenant_id 过滤**（会话事件自动处理）；跨租户的系统级查询使用 `.execution_options(skip_tenant_filter=True)`。
- 接口依赖 `ctx: Ctx = Depends(perm("权限码"))`；新权限码先加到 `app/core/permissions.py`。按店铺的数据需调用 `ctx.require_shop()` 或按 `ctx.shop_ids` 过滤。
- 库存变动只能通过 `InventoryService`（`app/modules/warehouse/inventory.py`），不要直接改 `InventoryBalance`。
- 金额用 `Decimal`，模型列用 `MoneyColumn`，响应 schema 用 `Money` 类型。
- 业务错误抛 `BizError`（422），不存在抛 `NotFound`；写操作调用 `audit()` 记录日志并在 service 末尾 `ctx.db.commit()`。
- 平台对接：实现 `app/integrations/base.py::PlatformConnector`，只输出 `dto.py` 中的标准 DTO，在 `registry.py` 注册。
- 前端页面在 `src/pages/`，路由与菜单在 `src/router/routes.tsx`（带权限码）；列表优先使用 `components/DataTable`，表单弹窗用 `FormModal`，明细行用 `LinesEditor`。Ant Design 为 v6：用 `orientation`（非 direction）、`destroyOnHidden`、`variant`、`mask={{ closable }}`、`showSearch={{ ... }}`。
- UI 文案为简体中文。
