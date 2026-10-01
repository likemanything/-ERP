# 云帆ERP（CloudSail ERP）

面向跨境电商中小卖家的一体化 ERP，对标领星 ERP 的核心业务链路：

**多平台店铺 → 产品/配对 → 采购 → 仓储 → FBA 头程 → 智能补货 → 订单 → 财务利润 → 广告分析**

可私有化部署（一条 `docker compose up`），也可作为多企业 SaaS 运行（行级多租户隔离）。

---

## 功能一览

| 模块 | 能力 |
| --- | --- |
| 店铺授权 | Amazon（SP-API + 广告 API）、Walmart、TikTok Shop、Shopify 原生对接；eBay/Temu/SHEIN/速卖通/线下渠道支持 Excel 导入；**演示模式**无需真实授权即可体验全流程；定时自动同步 + 手动同步 + 同步记录 |
| 产品 | 本地 SKU、SPU/变体属性、组合产品（套装自动拆分子件出入库）、辅料、箱规、报关信息、多供应商报价、Excel 导入导出 |
| Listing | MSKU ↔ SKU 配对（支持 1 MSKU = N 件多件装）、自动配对、Excel 批量配对、配对后回溯历史订单并重算成本 |
| 订单 | 多平台统一订单、FBA/自发货、状态页签；自发货流程：审核（分配仓库+锁库存）→ 批量发货（回传运单号）→ 签收；挂起/反审核/取消；平台直发订单自动补扣库存；Excel 导入；每单预估利润 |
| 退货退款 | 仅退款 / 退货退款，良品按原成本回库并冲减销售成本，次品单独记账 |
| 采购 | 采购计划（手工/补货建议）→ 按供应商合并生成采购单 → 审批（可关闭）→ 下单 → 分批到货质检（良品/次品）→ 结单；采购退货；请款单审批与付款；应付账款汇总；外币采购按下单汇率折算 |
| 仓储 | 多仓（本地/海外/FBA/三方）、库位、实时库存（实物/锁定/可用/次品/在途）、安全库存预警；其他出入库、调拨（在途→签收，运费分摊）、盘点（账面快照+差异过账）；库存流水；批次与库龄 |
| 成本核算 | **FIFO 批次成本层**，成本拆分为「采购成本」与「物流/头程成本」，从采购入库一路传递到调拨、头程、FBA 销售与退货 |
| FBA / 头程 | 发货计划 → 货件 → 发货出库 → 分批签收入 FBA 仓；装箱信息、计费重；头程费用（运费/关税/其他）**按计费重/体积/数量/货值分摊**；账单后补自动重新分摊并修正剩余批次成本；FBA 库存快照 |
| 智能补货 | 7/14/30 天加权日均 × 增长系数；**FBA 发货建议**（可售天数、断货日、建议发货量/发货日）与**采购建议**（含本地、FBA、采购在途、计划中，按起订量取整）；Listing 级个性化参数；一键生成发货计划 / 采购计划 |
| 物流 | 物流商、渠道（首重续重/按重量/按体积/按件、材积除数、最低收费、附加费）、多渠道运费比价 |
| 财务 | **利润报表**（按 MSKU / SKU / 店铺 / 天 / 月）、多币种按月度汇率折算本位币；结算明细导入并用实际佣金/FBA 费替换预估；费用单（店铺/公司公共）；库存估值（含头程在途）；汇率管理 |
| 广告 | 广告日报导入/同步，按活动/MSKU/店铺统计 曝光、点击、CTR、CPC、CVR、ACoS、ROAS，每日趋势；广告费自动计入利润 |
| 报表 | 首页看板（KPI、30 天趋势、店铺占比、热销 TOP10、待办）、销售统计（天/月/店铺/MSKU/SKU/国家）、库龄分析、库存周转/滞销 |
| 分销 | 给分销商开通门户账号（中英双语）：商品目录与等级价 / 专属价、可售库存；**一件代发 / 批发**下单实时报价（货款 + 运费 + 操作费）并从**预存款 + 授信额度**扣款；充值申请审核、余额调整、对账单；取消 / 退货自动退款；API Key 对接分销商自有系统 |
| 仓储作业 | 拣货波次（按库位汇总的拣货单 + 按单分拣）、装箱单、**扫码验货发货**（SKU / 条码 / FNSKU / MSKU 逐件校验）、运单号 Excel 导入并回传平台；FNSKU / SKU / 商品条码标签（热敏与 A4 标签纸）、FBA 箱唛 |
| 加工单 | 组装（子件 → 成品）与拆分，按 FIFO 结转子件成本 + 加工费，自动带出上次配方 |
| 审批 | 采购单 / 请款单 / 分销充值的**多级审批流**：按金额门槛匹配，每级指定人员或角色、或签 / 会签；审批中心与待审批提醒 |
| 系统 | 多企业（租户）注册开通、用户、角色（按钮级权限树）、**店铺级数据权限**、部门、操作日志、系统参数、站内消息 |

### 核心算法

**利润（本位币，已发货订单口径）**

```
毛利润 = 销售额(商品 + 买家运费 - 促销) - 退款
       - 平台佣金 - FBA 配送费 - 其他订单费用
       - 广告费
       - 采购成本 - 头程成本（FIFO 结转） + 退货回库成本
       - 自发货运费 - 平台其他费用（仓储费/月租等） - 费用单
```

**补货**

```
日均 = (近7天日均×w7 + 近14天日均×w14 + 近30天日均×w30) / (w7+w14+w30) × 增长系数
建议发货量 = 日均 × (头程时效 + 安全天数 + 备货天数) - (FBA 可售 + 预留 + 入库在途)
建议采购量 = Σ(日均需求) × (采购交期 + 质检 + 头程 + 安全 + 备货) - (本地可用 + FBA 总库存 + 采购在途 + 待处理计划)，按起订量向上取整
```

**头程分摊**：总费用 × 汇率 → 按（实重与体积重取大的）计费重 / 体积 / 数量 / 货值 占比分摊到每个 SKU，签收时与出库 FIFO 采购成本一起形成 FBA 仓批次成本。

---

## 快速开始

### 方式一：Docker Compose（推荐，生产可用）

```bash
cp .env.example .env
# 编辑 .env：至少设置 ERP_SECRET_KEY（python -c "import secrets;print(secrets.token_urlsafe(48))"）
# 首次体验可设置 ERP_SEED_DEMO=true 生成演示数据
docker compose up -d --build
```

打开 <http://localhost:8000>，演示账号 `demo / demo123456`，或在登录页「免费开通」注册新企业。
服务包含：`db`（PostgreSQL 16）、`web`（API + 前端，启动时自动迁移数据库）、`worker`（平台数据定时同步）。

### 方式二：本地开发

后端（Python 3.11+，使用 [uv](https://github.com/astral-sh/uv)）：

```bash
cd backend
uv sync
# 默认使用 SQLite（./erp.db）；使用 PostgreSQL：export ERP_DATABASE_URL=postgresql+psycopg://user:pass@localhost/erp
uv run python -m app.cli init-db          # 数据库迁移
uv run python -m app.cli seed-demo        # 可选：生成演示企业 demo / demo123456
uv run uvicorn app.main:app --reload      # http://localhost:8000/api/docs
uv run python -m app.worker               # 可选：后台同步 worker
```

前端（Node 20.19+ / 22）：

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 ，/api 代理到 127.0.0.1:8000
```

### 测试

```bash
cd backend
uv run pytest                                                         # SQLite
TEST_DATABASE_URL=postgresql+psycopg://erp:erp@localhost/erp_test uv run pytest   # PostgreSQL
uv run ruff check app tests
cd ../frontend && npm run typecheck && npm run build
```

---

## 对接平台

在【店铺 → 店铺授权】添加店铺并填写凭证（Fernet 加密存储，接口与页面均不回显明文）：

| 平台 | 所需凭证 | 同步内容 |
| --- | --- | --- |
| Amazon | SP-API 应用的 `client_id`、`client_secret`，卖家授权的 `refresh_token`；选择站点 | 订单（Orders API）、Listing（GET_MERCHANT_LISTINGS_ALL_DATA 报告）、FBA 库存（FBA Inventory API）、结算明细（Finances API）；自发货订单发货后回传运单号 |
| Shopify | 自定义应用的 Admin API `access_token`，店铺域名 `xxx.myshopify.com` | 订单、商品变体（Listing） |
| Amazon 广告 | 在 Amazon 店铺授权中额外填写广告 `ads_refresh_token`（广告应用 client 可选，Profile 默认按站点自动匹配） | Sponsored Products 推广商品日报（Reporting v3），按日期 × 活动 × 广告组 × SKU 计入广告分析与利润 |
| Walmart（美国站） | Seller Center 生成的 `client_id`、`client_secret` | 订单（含 WFS 订单，从 WFS 虚拟仓结转成本）、商品、WFS 库存；自发货订单回传运单号 |
| TikTok Shop | Partner 应用 `app_key`、`app_secret`，卖家授权 `access_token` / `refresh_token`（过期自动刷新）；`shop_cipher` 可留空自动获取 | 订单、商品；填写默认物流商 ID 后可回传运单号 |
| 其他平台 / 线下 | — | 订单、FBA 库存、结算、广告数据均支持 Excel 模板导入 |
| 任意平台（演示） | 勾选「演示模式」 | 自动生成确定性的订单、Listing、FBA 库存、结算、广告数据 |

新增平台只需在 `backend/app/integrations/` 实现 `PlatformConnector`（输出标准 DTO）并在 `registry.py` 注册，订单落库、成本核算、利润等逻辑全部复用。

---

## 技术架构

```
frontend/  React 19 + TypeScript + Vite + Ant Design 6 + TanStack Query + ECharts
backend/   FastAPI + SQLAlchemy 2 + Alembic + Pydantic 2，PostgreSQL（开发可用 SQLite）
  app/core/          配置、数据库与多租户隔离、认证与权限依赖、错误处理
  app/common/        分页、通用 CRUD、单据编号、汇率、Excel、操作日志
  app/modules/<域>/   models / schemas / service / router
    system shop product supplier warehouse purchase logistics order fba replenishment
    finance ads report integration distribution fulfillment assembly approval
  app/integrations/  平台连接器（amazon + amazon_ads / walmart / tiktok / shopify / demo）与标准 DTO
frontend/src/portal/ 分销商门户（独立布局、中英双语）
  app/worker.py      定时同步 worker（PostgreSQL 下多实例安全）
  app/cli.py         init-db / create-tenant / seed-demo
```

关键设计：

- **多租户**：所有业务表带 `tenant_id`；会话级 `do_orm_execute` 事件自动为每条 ORM 查询追加租户条件，`before_flush` 阻止跨租户写入——业务代码无需手写租户过滤。
- **权限**：权限点注册表（`app/core/permissions.py`）→ 角色 → 用户；企业管理员全权限；用户可限定可见店铺（订单、Listing、FBA、补货、广告等按店铺过滤）。
- **库存引擎**（`app/modules/warehouse/inventory.py`）：所有库存变动的唯一入口，写流水、维护余额、FIFO 消耗批次并返回成本；PostgreSQL 下行锁保证并发安全；FBA 虚拟仓允许负数（以平台数据为准）。
- **金额**：数据库 `Numeric(18,4)`，计算全程 `Decimal`；订单金额保留原币，成本统一为本位币，报表按月度汇率折算。
- **幂等同步**：订单按（店铺，平台单号）、交易按外部 ID、广告按（日期，活动，广告组，MSKU）去重；单个订单失败不影响整批同步。

---

## 与领星 ERP 的对照与路线图

已覆盖领星中小卖家最常用的主链路（店铺授权、产品与配对、采购、仓库、FBA 发货与头程分摊、补货建议、订单、利润报表、广告分析、权限），
并补充了分销商门户、仓储作业（波次 / 扫码发货 / 标签打印）、加工单、多级审批。

下一步（详见 [任务看板](docs/ai/08-roadmap.md)）：分销增强、物流商面单对接、
Amazon Send-to-Amazon、平台结算对账、移动端扫码作业等。

## 参与开发（人类与 AI）

- AI 代理入口：[`CLAUDE.md`](CLAUDE.md)（Claude Code 自动加载）/ [`AGENTS.md`](AGENTS.md)（其他工具）
- 入职指南：[`docs/ai/00-onboarding.md`](docs/ai/00-onboarding.md) —— 环境、演示账号、阅读顺序
- 全部文档：[`docs/`](docs/README.md)（架构、规范、工作流、协同协议、配方、踩坑、路线图、ADR、交接记录）

## 许可证

尚未指定开源许可证，由仓库所有者决定。
