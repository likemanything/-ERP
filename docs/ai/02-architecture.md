# 02 · 架构与代码地图

## 1. 技术栈

| 层 | 选型 | 备注 |
| --- | --- | --- |
| 后端 | Python 3.11、FastAPI、SQLAlchemy 2（同步 ORM）、Alembic、Pydantic 2、pydantic-settings | 包管理 uv；lint ruff |
| 数据库 | PostgreSQL 16（生产 / CI）、SQLite（开发 / 测试） | 两库都必须通过测试与迁移 |
| 其他后端库 | PyJWT、bcrypt、cryptography(Fernet)、httpx、openpyxl、reportlab、tzdata | reportlab 生成 PDF（条码、中文） |
| 前端 | React 19、TypeScript 5.9、Vite 8、Ant Design 6、TanStack Query 5、zustand、axios、ECharts 6、dayjs | 路由 react-router 7 |
| 部署 | Docker 单镜像（API + 前端静态文件）+ worker；docker compose（db / web / worker） | `deploy/entrypoint.sh web|worker` |

## 2. 后端目录

```
backend/app/
├── main.py                 创建 FastAPI、注册所有 router（/api/v1 前缀）、托管前端静态文件、/api/health
├── models.py               导入全部模块的 models（Alembic / create_all 依赖它）
├── cli.py                  init-db / create-tenant / seed-demo
├── worker.py               定时同步：轮询到期店铺，FOR UPDATE SKIP LOCKED 认领，多实例安全
├── core/
│   ├── config.py           Settings（环境变量前缀 ERP_）
│   ├── db.py               引擎、SessionLocal(expire_on_commit=False)、TenantModel、多租户会话事件
│   ├── deps.py             Ctx、_load_ctx、get_ctx / get_any_ctx / perm()、system_ctx
│   ├── permissions.py      权限点注册表 PERMISSION_GROUPS、预置角色 PRESET_ROLES
│   ├── security.py         密码哈希、JWT、Fernet 加解密
│   ├── errors.py           BizError(422) / NotFound(404) / Conflict(409) / Forbidden(403) / Unauthorized(401)
│   └── types.py            MoneyColumn、Money、UTCDateTime、q2/q4、utcnow
├── common/
│   ├── crud.py             get_or_404、build_crud_router（简单主数据一键 CRUD）、ensure_unique / ensure_not_referenced
│   ├── pagination.py       page_params、paginate → {items,total,page,page_size}
│   ├── numbering.py        next_doc_no（行锁 + 重试，按企业/前缀/日期递增）
│   ├── currency.py         汇率 get_rate、to_base（按月度汇率）
│   ├── excel.py            export_xlsx、template_response、read_upload
│   ├── pdf.py              条码标签、箱唛、文档 PDF（reportlab）
│   ├── audit.py            audit(ctx, action, resource, id, summary)
│   └── enums.py            状态 / 类型枚举（StrEnum）
├── integrations/           平台连接器框架（见 §7）
└── modules/<域>/           models.py / schemas.py / service.py / router.py
```

## 3. 请求生命周期

```
HTTP ─▶ router 函数
        └─ Depends(perm("order:ship"))  →  _load_ctx：
             解析 JWT(sub, tid, ver) → 查 User（skip_tenant_filter）→ 校验 is_active / token_version / 企业有效
             → db.info["tenant_id"] = tid（此后所有 ORM 查询自动带租户条件）
             → 计算权限集合、店铺数据范围 → 返回 Ctx(db, user, tenant_id, permissions, shop_ids)
        └─ service 函数(ctx, ...)：业务校验（BizError）→ InventoryService / 其他服务 → audit() → ctx.db.commit()
        └─ 返回 response_model（Pydantic，Money 序列化为 float）
异常 ─▶ 全局处理器 → {"code": "...", "message": "中文提示", "details": ...}
```

依赖函数：

| 依赖 | 允许 | 用途 |
| --- | --- | --- |
| `perm("code")` | 员工 + 拥有该权限（管理员全部通过） | 绝大多数接口 |
| `get_ctx` | 任意员工账号 | 不需要特定权限的接口（如审批人审批、待审批数量） |
| `get_any_ctx` | 员工或分销商 | `/auth/me`、修改密码 |
| `get_portal_ctx` | 分销商 Bearer Token 或 `X-Api-Key` | `/portal/*` |
| `system_ctx(db, tenant_id)` | 虚拟系统用户（全权限） | worker、CLI、种子数据 |

`Ctx` 常用：`ctx.db`、`ctx.user`、`ctx.user_id`、`ctx.tenant_id`、`ctx.can(code)`、`ctx.require(code)`、`ctx.shop_ids`（None = 全部店铺）、`ctx.require_shop(shop_id)`。

## 4. 多租户（行级隔离）

- 所有业务表继承 `TenantModel` = 自增主键 + `created_at/updated_at` + `tenant_id` + `created_by/updated_by`。
- `db.py` 的 `do_orm_execute` 事件：对 ORM 查询追加 `with_loader_criteria(TenantMixin, tenant_id == db.info["tenant_id"])`。
- `before_flush` 事件：新对象自动填充 `tenant_id`、`created_by`；修改其他企业的数据直接报错。
- 系统级查询（登录查用户、worker 扫描全部店铺）：`.execution_options(skip_tenant_filter=True)`。
- **用户名全局唯一**（跨企业），登录不需要企业编码。

## 5. 模块地图

| 模块 | 主要模型 | 核心逻辑 | 路由前缀（/api/v1） | 前端页面 | 测试 |
| --- | --- | --- | --- | --- | --- |
| system | Tenant、User、Role、UserRole、UserShop、Department、AuditLog、Sequence、SystemSetting、Notification | 注册开通企业、用户角色、参数 `get_setting/update_settings`、消息 | `/auth`、`/system/*` | `pages/system/*`、`Login` | test_auth_tenancy |
| shop | Shop | 店铺 CRUD、凭证加密、站点表 `marketplaces.py`、亚马逊 FBA 虚拟仓 | `/shops` | `pages/shop/*` | test_master_data |
| product | Product、BundleItem、ProductSupplier、Category、Brand、Listing | 产品 / 组合 / 配对 `pair_listing`、`expand_bundle`、导入导出 | `/products`、`/listings`、`/product-*` | `pages/product/*` | test_master_data |
| supplier | Supplier | CRUD | `/suppliers` | `purchase/Suppliers` | test_master_data |
| warehouse | Warehouse、WarehouseBin、InventoryBalance、InventoryBatch、InventoryLedger、StockDocument(+Line) | **InventoryService**、出入库 / 调拨 / 盘点单据 | `/warehouses`、`/warehouse-bins`、`/inventory*`、`/stock-documents` | `pages/warehouse/*` | test_inventory |
| purchase | PurchasePlan、PurchaseOrder(+Line)、PurchaseReceipt(+Line)、PurchaseReturn、PaymentRequest(+Line) | 计划转单、审批（接入审批引擎）、收货分摊、退货、请款付款、应付 | `/purchase-*`、`/payment-requests`、`/payables` | `pages/purchase/*` | test_purchase |
| logistics | LogisticsProvider、LogisticsChannel | `calc_freight` 运费规则、比价 | `/logistics-*`、`/logistics`（比价） | `logistics/Logistics` | test_master_data |
| order | SalesOrder、SalesOrderItem、ReturnOrder(+Line) | `upsert_order`、`_advance_status`、`audit_order`、`ship_order`、FBA/FBM 成本结转、退货、`estimate_profit` | `/orders*`、`/returns` | `pages/order/*` | test_orders |
| fba | ShipmentPlan(+Line)、FbaShipment(+Line)、FbaInventory | 货件出库 / 签收、头程分摊 | `/shipment-plans`、`/fba-shipments`、`/fba-inventory` | `pages/fba/*` | test_fba |
| replenishment | ReplenishmentRule | 日均销量、发货 / 采购建议 | `/replenishment/*` | `pages/replenish/*` | test_replenishment |
| finance | PlatformTransaction、Expense、ExchangeRate | 利润报表、结算导入与实际费用回填、估值 | `/finance/*` | `pages/finance/*` | test_finance |
| ads | AdCampaign、AdMetricDaily | 广告指标导入 / 同步 `upsert_metrics` | `/ads/*` | `ads/Ads` | test_finance |
| report | — | 看板、销售统计、库龄、周转 | `/dashboard`、`/reports/*` | `Dashboard`、`pages/report/*` | test_finance |
| integration | SyncJob、SyncCursor | `sync_shop`（按类型独立事务、游标）、`push_tracking` | `/shops/{id}/sync`、`/sync-jobs`、`/integrations`（平台能力） | `shop/SyncJobs` | test_integrations |
| distribution | DistributorLevel、Distributor、DistributionProduct、DistributionLevelPrice、DistributorTransaction、RechargeRequest | 报价、下单扣款 `place_order`、`post_txn`（行锁）、退款钩子、对账单；`portal.py` 门户 | `/distribution/*`、`/portal/*` | `pages/distribution/*`、`src/portal/*` | test_distribution |
| fulfillment | PickWave（+ `SalesOrder.wave_id`） | 波次、拣货汇总、扫码验货、运单导入、`printing.py` 打印模板 | `/fulfillment/*`、`/print/*` | `warehouse/Waves`、`ScanShip`、`components/PrintLabels` | test_fulfillment |
| assembly | AssemblyOrder、AssemblyLine | 组装 / 拆分成本结转 | `/assembly-orders` | `warehouse/Assembly` | test_assembly_approval |
| approval | ApprovalFlow、ApprovalInstance、ApprovalRecord | 多级审批引擎 `start / act / cancel_pending` | `/approval/*` | `approval/MyApprovals`、`system/ApprovalFlows`、`components/ApprovalTimeline` | test_assembly_approval |

## 6. 核心引擎

### 6.1 库存引擎 `warehouse/inventory.py::InventoryService`

所有库存变动的唯一入口：维护 `InventoryBalance`（实物 / 锁定 / 次品 / 在途）、写 `InventoryLedger` 流水、按 FIFO 维护 `InventoryBatch`。

| 方法 | 作用 |
| --- | --- |
| `inbound(wh, product, qty, ref, change_type, unit_purchase_cost, unit_freight_cost, …)` | 良品入库形成批次；成本为空时取产品参考成本；负库存时先冲抵负数部分 |
| `inbound_layers(...)` | 按来源成本层入库（调拨 / FBA 签收 / 退货保持原成本） |
| `outbound(wh, product, qty, ref, change_type, from_locked, allow_negative)` | FIFO 出库，返回 `OutboundResult(purchase_cost, freight_cost, layers)` |
| `lock / unlock` | 锁定 / 释放（订单审核 / 取消） |
| `inbound_defective / outbound_defective` | 次品 |
| `add_in_transit`、`adjust_to`、`average_cost` | 在途、盘点调整、平均成本 |

`Ref(ref_type, ref_id, ref_no, remark, biz_date)` 描述关联单据；`LedgerType` 枚举描述变动类型。PostgreSQL 下余额 / 批次用 `FOR UPDATE OF` 行锁。

### 6.2 订单管线 `order/service.py`

```
平台同步 / Excel 导入 / 手工 / 分销下单
  └─ upsert_order：按 (店铺, 平台单号) 幂等；明细按 platform_item_id 或 msku 合并；自动配对 MSKU→SKU；预估佣金
      └─ _advance_status：FBA 发货 → settle_fba_cost（FBA 仓 FIFO）；FBM 自动审核（可选）；平台直发补扣库存
audit_order：分配仓库 / 渠道，展开组合与多件装 → stock_plan，锁库存，预估运费 → to_ship
ship_order：按 stock_plan 从锁定库存 FIFO 出库，成本写入明细 → shipped；after_ship 钩子（波次自动完成）
_do_cancel：释放锁定；分销订单调用 distribution.refund_order
complete_return：良品按原成本回库；分销订单调用 credit_return
```

### 6.3 平台同步 `integration/service.py::sync_shop`

按 `ALL_JOB_TYPES = (listings, orders, fba_inventory, finances, ads)` 逐类执行，每类独立事务与 `SyncJob` 记录；
游标 `SyncCursor` 记录上次成功时间；单个订单失败只记录错误样例不影响整批；`ConnectorError(auth=True)` 把店铺标记为 `auth_expired`。
`worker.py` 每 `ERP_WORKER_POLL_SECONDS` 扫描到期店铺，用 `FOR UPDATE SKIP LOCKED` 认领，可多实例部署。

### 6.4 审批引擎 `approval/service.py`

- `start(ctx, doc_type, doc_id, …)`：按单据类型 + 金额（本位币）匹配启用流程（门槛最高者），快照步骤生成实例并通知第一级；未匹配返回 `None`。
- `act(ctx, doc_type, doc_id, approve, comment)`：返回 `None`（无实例 → 调用方走原单级权限逻辑）/ `"pending"` / `"approved"` / `"rejected"`；**不提交事务**。
- 接入方式见 [06-recipes](06-recipes.md#新增审批单据类型)。已接入：采购单、请款单、分销充值。

### 6.5 分销 `distribution/`

- `service.py`：价格计算 `unit_price`、库存 `available_qty`（分销仓）、`quote`、`place_order`、`post_txn`（锁分销商行、校验可用额度、写流水）、`refund_order`、`credit_return`、`charge_adjust`、`statement`。
- `portal.py`：门户接口；`_PortalUser` 作为操作人写日志；永不返回成本字段。
- 分销商用户 `User.user_type = "distributor"`、`User.distributor_id`；后台 `get_ctx` 会拒绝这类账号。

### 6.6 打印 `common/pdf.py` + `fulfillment/printing.py`

- `labels_pdf`：热敏（60×30 等）与 A4 标签纸（21/24/30/40/44 格，支持跳过已用格）；Code128 条码。
- `carton_labels_pdf`：100×100 / 100×150 箱唛；`doc_pdf + grid + BarcodeFlowable`：拣货单、装箱单。
- 字体：默认内置 CID 字体（不嵌入）；生产设置 `ERP_PDF_FONT_PATH` 嵌入 TTF/TTC（Docker 镜像已内置文泉驿正黑）。
- 前端用 `openPdf()`（先同步打开窗口防拦截，再写入 blob URL）。

## 7. 平台连接器 `app/integrations/`

```
base.py      PlatformConnector：capabilities、credential_fields、request()（429/5xx 指数退避、401/403 → auth 错误）
             fetch_orders / fetch_listings / fetch_fba_inventory / fetch_transactions / fetch_ad_metrics / confirm_shipment
dto.py       OrderDTO / OrderItemDTO / ListingDTO / FbaInventoryDTO / TransactionDTO / AdMetricDTO（平台无关）
registry.py  CONNECTORS = {platform: Connector}；get_connector(shop)（mode=demo → DemoConnector）；platform_capabilities()
amazon.py    SP-API（LWA，无需 SigV4）    shopify.py  Admin REST    demo.py  确定性演示数据
```

状态见 [08-roadmap](08-roadmap.md)：Walmart / TikTok Shop / Amazon Ads 连接器开发中（交接记录在 `docs/handoff/`）。

## 8. 前端架构

```
src/
├── main.tsx / App.tsx      StrictMode；路由：/login、/portal/login、/portal/*（RequireAuth portal）、/*（RequireAuth + MainLayout + Guard(perm)）
├── router/routes.tsx       MENU（分组 → 页面 {path,label,perm,element(lazy)}），菜单与路由都由它生成
├── layouts/MainLayout.tsx  侧边菜单（按权限过滤）、面包屑、待审批角标、消息、修改密码
├── store/auth.ts           zustand(persist token)：user(user_type)、tenant、permissions；usePerm()、useBaseCurrency()
├── api/client.ts           axios 实例（Bearer、401 自动 refresh）、api.get/post/put/del/upload、download、openPdf、errorMessage
├── components/             DataTable（筛选+分页+工具栏+导出）、FormModal、ImportModal、useAction、LinesEditor、
│                           selects（Shop/Warehouse/Product/Listing/User/Role/Distributor/Level…Select）、StatusTag、Perm、
│                           ProductCell、EChart、PrintLabels、ApprovalTimeline
├── hooks/useOptions.ts     下拉选项（react-query 缓存 5 分钟，key 以 'options' 开头）
├── utils/dicts.ts          状态字典 {value: [中文, 颜色]} + dictOptions / dictLabel
├── utils/format.ts         fmtMoney / fmtNumber / fmtDate / fmtDateTime / profitColor
├── pages/<域>/             后台页面
└── portal/                 分销商门户：PortalLayout、PortalLogin、i18n(useT 中英)、cart(zustand)、pages/*
```

- 员工账号访问 `/portal` 会被重定向到 `/`，分销商访问后台会被重定向到 `/portal`。
- 页面权限只是体验层，**后端必须独立校验权限**。

## 9. 数据库迁移链

`alembic/versions/` 线性链（head 必须唯一）：

1. `8175d4cdce16` initial schema
2. `2d48dcc5cdef` distribution
3. `45da6463832a` fulfillment waves and product barcode
4. `39bd6ae67159` approval flows and assembly orders

`env.py` 对 SQLite 启用 `render_as_batch`；手写或修改已有表时用 `op.batch_alter_table`。

## 10. 配置（环境变量，前缀 `ERP_`）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ERP_DATABASE_URL` | `sqlite:///./erp.db` | PostgreSQL：`postgresql+psycopg://user:pass@host/db` |
| `ERP_SECRET_KEY` | 开发默认值 | JWT 签名；生产必须设置 |
| `ERP_ENCRYPTION_KEY` | 空（由 SECRET_KEY 派生） | Fernet 密钥，加密店铺凭证；更换会导致已存凭证无法解密 |
| `ERP_ACCESS_TOKEN_EXPIRE_MINUTES` / `ERP_REFRESH_TOKEN_EXPIRE_DAYS` | 720 / 14 | Token 有效期 |
| `ERP_CORS_ORIGINS` | localhost:5173 | JSON 数组 |
| `ERP_ALLOW_REGISTRATION` | true | 是否允许公开注册企业 |
| `ERP_DEFAULT_BASE_CURRENCY` / `ERP_DEFAULT_TIMEZONE` | CNY / Asia/Shanghai | 新企业默认 |
| `ERP_WORKER_POLL_SECONDS` | 30 | worker 轮询间隔 |
| `ERP_FRONTEND_DIST` | 空 | 生产由后端托管前端构建产物 |
| `ERP_PDF_FONT_PATH` | 空 | PDF 嵌入字体 |
| `ERP_SEED_DEMO`（容器） | false | 容器启动时生成演示数据 |
| `TEST_DATABASE_URL`（测试） | 临时 SQLite | 指向 PostgreSQL 测试库即在 PG 上跑测试 |

企业级业务参数（审批开关、负库存、自动审核、分销费率等）存在 `SystemSetting`，定义在 `system/settings_registry.py`，用 `get_setting(db, key)` 读取。
