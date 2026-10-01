# 00 · 入职指南（AI / 新同学第一天）

目标：30 分钟内跑起系统、知道去哪找代码、能按规范交付第一个改动。

## 1. 阅读顺序

| 顺序 | 文档 | 预计 | 读完应该知道 |
| --- | --- | --- | --- |
| 1 | [`CLAUDE.md`](../../CLAUDE.md) | 5 分钟 | 10 条硬性约定、完成定义 |
| 2 | [01-domain](01-domain.md) | 15 分钟 | 业务主链路、订单 / 库存 / 成本口径、术语 |
| 3 | [02-architecture](02-architecture.md) | 20 分钟 | 请求生命周期、多租户、模块地图、核心引擎 |
| 4 | [03-conventions](03-conventions.md) | 10 分钟 | 后端 / 前端 / 测试写法 |
| 5 | [04-workflow](04-workflow.md) | 10 分钟 | 迁移、两库测试、浏览器验证、CI |
| 6 | [05-collaboration](05-collaboration.md) | 10 分钟 | 认领任务、冲突热点、交接 |
| 7 | [07-pitfalls](07-pitfalls.md) | 5 分钟 | 已知坑 |
| 按需 | [06-recipes](06-recipes.md) | — | 照着做：新增模块 / 权限 / 连接器… |
| 开工前 | [08-roadmap](08-roadmap.md) + [`docs/handoff/`](../handoff/) | — | 有哪些任务、谁在做、未完成工作的现状 |

## 2. 环境（本地开发）

前置：Python 3.11+、[uv](https://github.com/astral-sh/uv)、Node 20.19+ / 22、（推荐）PostgreSQL 16。

```bash
# 后端
cd backend
uv sync
cp ../.env.example .env              # 可选；不配置时默认 SQLite ./erp.db
# 使用 PostgreSQL：echo 'ERP_DATABASE_URL=postgresql+psycopg://erp:erp@localhost/erp' >> .env
uv run python -m app.cli init-db      # 迁移到最新
uv run python -m app.cli seed-demo    # 演示企业 + 数据
uv run uvicorn app.main:app --reload  # API: http://localhost:8000/api/docs

# 前端（另一个终端）
cd frontend
npm install
npm run dev                           # http://localhost:5173 （/api 代理到 127.0.0.1:8000）
```

本地起一个 PostgreSQL（含测试库）：

```bash
docker run -d --name erp-pg -p 5432:5432 -e POSTGRES_USER=erp -e POSTGRES_PASSWORD=erp -e POSTGRES_DB=erp postgres:16
docker exec erp-pg psql -U erp -c "create database erp_test"
```

## 3. 演示账号（`seed-demo` 生成）

| 账号 | 密码 | 身份 | 入口 | 用来体验 |
| --- | --- | --- | --- | --- |
| `demo` | `demo123456` | 企业管理员（全部权限） | `/login` | 所有后台功能 |
| `caigou` | `caigou123` | 采购主管（采购角色） | `/login` | 大额采购单第 1 级审批 |
| `caiwu` | `caiwu123` | 财务经理（财务角色） | `/login` | 采购单第 2 级审批、分销充值确认 |
| `dealer` | `dealer123456` | 分销商 Sunrise Trading LLC | `/portal/login` | 分销商门户（中/英）、下单、充值、API Key |

演示数据包含：Amazon 美国演示店（演示模式自动生成订单 / Listing / FBA 库存 / 结算 / 广告）、8 个产品（带条码、库位）+ 1 个组装套装 SET-OFFICE、
采购单与入库、FBA 货件、分销商与 3 个代发订单、待审批采购单与充值申请、组装单（办公套装）。

重建演示数据（会清空当前库）：

```bash
cd backend
uv run python -c "import app.models; from app.core.db import Base, engine; Base.metadata.drop_all(engine); Base.metadata.create_all(engine)"
uv run python -m app.cli seed-demo
```

> `seed-demo` 中的账号名全局唯一（跨企业），同一个库重复执行会跳过。

## 4. 仓库速览

```
.
├── CLAUDE.md / AGENTS.md        AI 入口
├── docs/ai/                     本套文档     docs/adr/ 架构决策   docs/handoff/ 交接记录
├── backend/
│   ├── app/core/                配置、DB 与多租户、认证依赖(Ctx)、权限注册表、错误、类型(Money/UTCDateTime)
│   ├── app/common/              分页、通用 CRUD、单据编号、汇率、Excel、PDF、审计日志、枚举
│   ├── app/modules/<域>/        models / schemas / service / router（共 18 个域）
│   ├── app/integrations/        平台连接器（amazon / shopify / demo …）与标准 DTO
│   ├── app/cli.py               init-db / create-tenant / seed-demo
│   ├── app/worker.py            定时同步 worker
│   ├── alembic/versions/        迁移（线性链）
│   └── tests/                   pytest（api / factory / client 夹具）
├── frontend/src/
│   ├── router/routes.tsx        菜单 + 路由 + 权限码（唯一注册处）
│   ├── pages/<域>/              后台页面          portal/  分销商门户（独立布局、中英双语）
│   ├── components/              DataTable / FormModal / LinesEditor / selects / PrintLabels …
│   └── api/client.ts            axios（自动刷新 token）、download、openPdf
├── Dockerfile / docker-compose.yml / deploy/entrypoint.sh
└── .github/workflows/ci.yml     lint + 两库测试 + 迁移检查 + 前端构建 + 镜像构建
```

## 5. 第一个任务怎么做

1. 在 [08-roadmap](08-roadmap.md) 选一个「待认领」任务，在看板表格登记负责人、分支、状态 `进行中`。
2. 先读相关模块的 `models.py → service.py → router.py` 与对应前端页面，以及 `tests/` 里的同域测试。
3. 有未完成交接（`docs/handoff/`）的先读交接记录，从「下一步」开始。
4. 先写 / 改测试，再实现；小步提交（每个提交都能通过 lint 与测试）。
5. 按 [04-workflow](04-workflow.md#6-完成定义) 的完成定义自检；更新看板状态；需要暂停时写交接记录。

## 6. 遇到问题

- 先查 [07-pitfalls](07-pitfalls.md)，大部分环境 / 框架问题都记录过。
- 业务口径不确定（例如利润怎么算、状态怎么流转）：查 [01-domain](01-domain.md)，仍不确定就问人类负责人，**不要猜**。
- 修完一个新坑，把它补进 07-pitfalls。
