# 云帆ERP · AI 开发助手须知

> 本文件会被 Claude Code 自动加载，其他 AI 工具请读 `AGENTS.md`（内容指向同一套规范）。
> **首次进入本仓库**：按 [`docs/ai/00-onboarding.md`](docs/ai/00-onboarding.md) 的阅读顺序过一遍，再动手。

云帆ERP 是对标领星 ERP 的跨境电商 ERP（多平台店铺 → 产品/配对 → 采购 → 仓储 → FBA 头程 → 补货 → 订单 → 财务利润 → 广告），
另含**分销**（分销商门户 + 一件代发/批发 + 预存款）、**仓储作业**（波次拣货、扫码验货、标签打印）、**加工单**、**多级审批**。
后端 FastAPI + SQLAlchemy 2（PostgreSQL / SQLite），前端 React 19 + Ant Design 6。

## 文档地图

| 文档 | 什么时候读 |
| --- | --- |
| [docs/ai/00-onboarding.md](docs/ai/00-onboarding.md) | 第一次进入仓库：环境、演示账号、阅读顺序 |
| [docs/ai/01-domain.md](docs/ai/01-domain.md) | 业务链路、状态机、核心公式、术语表 |
| [docs/ai/02-architecture.md](docs/ai/02-architecture.md) | 架构、代码地图、核心引擎（多租户 / 库存 / 订单 / 审批 / 分销 / 打印） |
| [docs/ai/03-conventions.md](docs/ai/03-conventions.md) | 编码规范（后端 / 前端 / 测试 / 提交） |
| [docs/ai/04-workflow.md](docs/ai/04-workflow.md) | 开发流程、迁移、浏览器验证、CI、完成定义 |
| [docs/ai/05-collaboration.md](docs/ai/05-collaboration.md) | 多人 / 多 AI 协同：认领、冲突热点、迁移协同、交接、评审 |
| [docs/ai/06-recipes.md](docs/ai/06-recipes.md) | 配方：新增模块 / 权限 / 参数 / 连接器 / 审批单据 / 打印模板… |
| [docs/ai/07-pitfalls.md](docs/ai/07-pitfalls.md) | 已踩过的坑（改代码前先扫一眼） |
| [docs/ai/08-roadmap.md](docs/ai/08-roadmap.md) | 路线图与任务看板（**认领任务在这里登记**） |
| [docs/adr/](docs/adr/) · [docs/handoff/](docs/handoff/) | 架构决策记录 · 未完成工作的交接记录 |

## 命令

```bash
# 后端（backend/）
uv sync
uv run pytest -p no:logging                                    # SQLite
TEST_DATABASE_URL=postgresql+psycopg://erp:erp@localhost/erp_test uv run pytest -p no:logging   # PostgreSQL
uv run ruff check app tests --fix
uv run alembic revision --autogenerate -m "xxx"               # 改模型后生成迁移；alembic check 确认无漂移
uv run python -m app.cli seed-demo                             # 演示数据（账号见 00-onboarding）
uv run uvicorn app.main:app --reload                           # http://localhost:8000/api/docs

# 前端（frontend/）
npm run dev | npm run typecheck | npm run build                # dev: http://localhost:5173（/api 代理到 8000）
```

## 硬性约定（违反即返工）

1. **多租户**：业务表继承 `TenantModel`，**不要手写 `tenant_id` 过滤**（会话事件自动处理）；系统级跨租户查询用 `.execution_options(skip_tenant_filter=True)`。
2. **权限**：接口依赖 `ctx: Ctx = Depends(perm("权限码"))`，新权限码先加到 `app/core/permissions.py`；按店铺的数据调用 `ctx.require_shop()` 或按 `ctx.shop_ids` 过滤。`get_ctx` 只允许员工账号，分销商门户走 `distribution/portal.py` 的 `get_portal_ctx`。
3. **库存**：所有库存变动只能经过 `InventoryService`（`app/modules/warehouse/inventory.py`），禁止直接改 `InventoryBalance` / `InventoryBatch`。
4. **金额**：一律 `Decimal`；模型列 `MoneyColumn`，响应 schema 用 `Money`；成本为本位币，订单金额保留原币。
5. **错误与事务**：业务错误抛 `BizError`（422），不存在抛 `NotFound`；写操作调用 `audit()`，在 service 末尾 `ctx.db.commit()`；被其他事务复用的内部函数（如 `post_txn`、`approval.act`）**不提交**。
6. **行锁**：`with_for_update(of=Model)`，不要裸 `with_for_update()`（PostgreSQL 与 joined 预加载冲突）。
7. **迁移**：改模型必须生成 Alembic 迁移；修改已有表结构用 `op.batch_alter_table`（兼容 SQLite）；PostgreSQL 与 SQLite 都要跑 `upgrade → check → downgrade -1 → upgrade`。CI 会执行 `alembic check`。
8. **平台对接**：实现 `app/integrations/base.py::PlatformConnector`，只输出 `dto.py` 的标准 DTO，在 `registry.py` 注册；测试用 `httpx.MockTransport`，不连真实接口。
9. **前端**：页面在 `src/pages/`（门户在 `src/portal/`），路由与菜单在 `src/router/routes.tsx`（带权限码）；列表用 `DataTable`，弹窗表单用 `FormModal`，明细行用 `LinesEditor`，PDF 用 `openPdf`。Ant Design 为 **v6**：`orientation`、`destroyOnHidden`、`variant`、`mask={{ closable }}`、`showSearch={{...}}`、Drawer `size`、Alert `title`、Steps/Timeline `content`；`List` 已废弃。
10. **文案**：后台 UI、错误信息、注释、文档用简体中文；分销商门户中英双语（`src/portal/i18n.ts`）。

## 完成定义（每次提交前）

- [ ] `uv run ruff check app tests` 通过；相关测试 + 全量测试在 **SQLite 和 PostgreSQL** 上通过
- [ ] 改了模型 → 有迁移且两库验证通过；改了前端 → `npm run typecheck && npm run build` 通过
- [ ] 改了页面 → 浏览器实际走一遍主流程，控制台无报错（见 04-workflow 的 Playwright 脚本骨架）
- [ ] 新功能有测试；演示数据需要时同步更新 `app/cli.py`；`docs/ai/08-roadmap.md` 状态已更新
- [ ] 暂停 / 交接未完成工作 → 在 `docs/handoff/` 写交接记录

## 协同

- 开工前在 [08-roadmap.md](docs/ai/08-roadmap.md) 的任务看板登记「负责人 / 分支 / 状态」，一个代理同时只做一个任务。
- 冲突热点文件（`app/models.py`、`app/main.py`、`permissions.py`、`settings_registry.py`、`routes.tsx`、`dicts.ts`、`cli.py`、`alembic/versions/`）只做**追加式**最小改动，详见 05-collaboration。
- 涉及业务口径、删除数据、破坏性接口变更时先问人类负责人。
