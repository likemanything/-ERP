# 08 · 路线图与任务看板

> 认领 / 暂停 / 完成任务时**只改自己那一行**并单独提交（`docs: claim T19` 之类）。规则见 [05-collaboration §2](05-collaboration.md#2-任务生命周期)。
> 状态：`待认领` · `进行中` · `已暂停`（必须有交接）· `阻塞` · `待评审` · `已完成`。优先级 P0（紧急）～ P3（有空再做）。

## 1. 产品方向

公司场景：**跨境电商卖家（亚马逊为主，多平台）+ 给分销商开账号供货**。路线图优先级据此排序：
1. 让日常运营闭环更省人（多平台订单自动进来、自动出单发货、利润准确）；
2. 分销业务做深（分销商自助、对账、通知）；
3. 再补客服、监控等外围能力。

## 2. 已完成里程碑

| 里程碑 | 内容 | 提交 |
| --- | --- | --- |
| R1 主链路 | 多租户/权限、主数据、库存引擎(FIFO)、采购、订单(FBA/FBM)、FBA 头程与补货、财务利润、广告、报表、Amazon SP-API / Shopify / 演示连接器、前端全模块、迁移、Docker、CI | `9b5cb98` … `c65b55a` |
| R2-1 分销后端 | 分销商、等级价、预存款 + 授信、充值审核、门户 API（Token / API Key）、下单扣款、取消 / 退货自动退款 | `554ef98` |
| R2-2 分销前端 | 中英双语分销商门户（目录、购物车报价、订单、资金、API）、后台分销管理 6 个页面 | `4ae212a` |
| R2-3 仓储作业 | 拣货波次、扫码验货发货、运单号导入、FNSKU / SKU / 条码标签、箱唛、拣货单、装箱单 | `d8db993` |
| R2-4 审批与加工 | 多级审批流（采购单 / 请款单 / 分销充值）、审批中心、加工单（组装 / 拆分） | `d2254f8` |
| R2-5 协作文档 | `CLAUDE.md`、`AGENTS.md`、`docs/ai/*`、ADR、交接模板、PR 模板 | `8de7082` |
| R2-6 平台连接器 | Walmart（订单 / 商品 / WFS 库存 / 回传）、TikTok Shop（签名、token 自动刷新、订单 / 商品 / 回传）、Amazon 广告 API（SP 日报）；Walmart / TikTok 店铺自动建 WFS / FBT 平台仓 | T15 |

## 3. 任务看板

| ID | 标题 | 优先级 | 状态 | 负责人 | 分支 | 更新 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T15 | 平台连接器：Walmart / TikTok Shop / Amazon Ads | P1 | 已完成 | claude（会话 016P7Q） | `claude/wizardly-meitner-h2vsdz` | 2026-10-01 | 后续见 T30；[交接记录](../handoff/2026-10-01-platform-connectors.md) |
| T18a | 分销增强：分销商专属价格、门户子账号与角色权限 | P1 | 待认领 | | | 2026-10-01 | 设计草案见 T18 任务卡，尚无代码 |
| T18b | 分销增强：发货通知（站内消息 + 签名 Webhook） | P1 | 待认领 | | | | 邮件通知需负责人确认 SMTP 服务 |
| T18c | 分销增强：月结对账单在线确认、门户导出运单号 | P1 | 待认领 | | | | |
| T19 | 物流商面单对接（取号 + 打印面单） | P1 | 待认领 | | | | 依赖 T19a 选型 |
| T20 | Amazon Send-to-Amazon 货件创建与官方箱唛 | P2 | 待认领 | | | | |
| T21 | 平台结算对账（Amazon Settlement V2 / Walmart Recon） | P2 | 待认领 | | | | |
| T22 | 审批扩展：更多单据类型与条件分支 | P2 | 待认领 | | | | |
| T23 | 移动端 / PDA 扫码作业（上架、拣货确认、盘点） | P2 | 待认领 | | | | |
| T24 | 异步任务与导出中心 | P2 | 待认领 | | | | |
| T25 | 性能与可观测性 | P2 | 待认领 | | | | |
| T26 | 后台界面多语言（英文） | P3 | 待认领 | | | | |
| T27 | 客服中心（买家消息 / Review / Feedback） | P3 | 待认领 | | | | |
| T28 | Listing 价格与跟卖监控 | P3 | 待认领 | | | | |
| T29 | Temu / SHEIN / eBay 连接器 | P3 | 待认领 | | | | 参考 T15 的实现方式 |
| T30 | 连接器增强：真实账号联调、TikTok 物流商映射、Amazon SB/SD 广告 | P2 | 待认领 | | | | T15 遗留 |

## 4. 任务卡

### T15 平台连接器：Walmart / TikTok Shop / Amazon Advertising

> **已完成**（2026-10-01）。遗留事项转入 T30。

- **背景**：目前只有 Amazon SP-API、Shopify 原生对接；Walmart / TikTok 订单靠 Excel 导入，广告靠导入或演示数据。
- **范围**：Walmart（订单、商品、WFS 库存、回传运单）、TikTok Shop（订单、商品、回传运单、token 自动刷新）、Amazon Ads（SP 推广商品日报）。
- **验收**：mock 测试覆盖认证、分页、映射、回传、错误；`platform_capabilities` 正确；授权表单展示新凭证字段；WFS / FBT 订单成本从平台仓结转；README 更新。
- **涉及**：`app/integrations/*`、`shop/router.py`、`tests/test_connectors.py`。
- **结果**：`tests/test_connectors.py` 9 个用例（含 WFS 订单端到端成本结转）；授权表单展示新凭证字段与同步能力。

### T18 分销增强

- **背景**：分销是公司核心业务之一，当前已支持开户、下单、充值、对账单。
- **范围**：① 分销商子账号与门户内权限（下单 / 财务 / 只读）；② 按分销商的专属价格（优先级高于等级价）；③ 订单发货后通知分销商（站内消息 + 邮件 / Webhook，Webhook 地址在门户 API 页配置，带签名）；④ 月结对账单生成、分销商在线确认；⑤ 门户导出发货运单号 Excel。
- **验收**：每项有测试；门户中英文案齐全；不泄露成本；演示数据覆盖。
- **涉及**：`distribution/*`、`src/portal/*`、`pages/distribution/*`；需要迁移（单个）。
- **规模**：L，已拆为 T18a（价格 + 子账号）、T18b（通知 + Webhook）、T18c（月结确认 + 导出）。
- **T18a 设计草案**（2026-10-01 讨论确定，尚未实现）：
  - 新表 `distributor_prices`（distributor_id、product_id、price〔分销商币种〕、remark，唯一键 tenant+distributor+product）；
    价格优先级改为 **专属价 > 等级价 > 基础价 × 折扣**：`service.unit_price` 增加 `special_prices` 参数，`_resolve_lines` 与门户 `_catalog_rows` 传入；门户目录返回价格来源，显示「专属价」标签。
  - 后台接口：`GET/PUT /distribution/distributors/{id}/prices`、`DELETE …/prices/{product_id}`、Excel 导入（sku、price、remark）；只允许已上架分销的商品。
  - `users.portal_role`（admin / order / finance / viewer，空 = admin，需 batch 迁移）；门户动作权限：下单 / 取消 / 导入 = admin、order；充值 = admin、finance；查看流水 / 充值记录 / 对账单 = admin、finance、viewer；子账号与 API Key = admin（API Key 视为 admin，但不能管理账号）。
  - 门户新增「账号管理」页（主账号增删子账号、改角色、禁用、重置密码；不能停用自己、至少保留一个启用的主账号）；`/portal/me` 返回 role，前端按角色隐藏菜单与按钮；后台账号抽屉可设置角色。

### T19 物流商面单对接

- **背景**：扫码发货目前需要手工扫入运单号；领星可直接对接物流商取号打印面单。
- **范围**：T19a 选型（与负责人确认首批物流商，如 4PX / 云途 / 燕文 / 物流商自定义 API）；T19b 物流商连接器框架（类似平台连接器：下单取号、获取面单 PDF、取消、轨迹）；T19c 审核或扫码时自动取号，扫码验货页一键打印面单。
- **验收**：mock 测试；取号失败有明确提示且可重试；面单 PDF 可打印（100×150）；运单号自动写入订单并回传平台。
- **涉及**：`logistics/*`、`fulfillment/*`、`pages/warehouse/ScanShip.tsx`、新迁移（渠道 API 配置）。

### T20 Amazon Send-to-Amazon

- **范围**：基于 Fulfillment Inbound API v2024-03-20，从 FBA 货件生成入库计划、确认放置选项、获取官方箱唛 / 托盘标签，回写 `platform_shipment_id`、`destination_fc`。
- **验收**：mock 测试覆盖完整工作流（异步 operation 轮询）；前端货件页增加「同步到亚马逊」与「下载官方箱唛」。

### T21 平台结算对账

- **范围**：Amazon Settlement V2 报告解析入 `PlatformTransaction`（与 Finances API 去重）；Walmart Recon 报告；对账页显示「结算金额 vs 系统订单金额」差异。
- **验收**：样例报告测试；利润报表费用以实际结算为准。

### T22 审批扩展

- **范围**：接入加工单、调拨单、费用单；流程条件（按供应商、部门、店铺）；审批转交 / 加签；撤回。
- **验收**：每种单据类型测试（参考 `test_assembly_approval.py`）；配置页支持条件。

### T23 移动端 / PDA

- **范围**：响应式的仓库作业页面（扫码上架、波次拣货确认、盘点录入），适配常见安卓 PDA 扫码枪（键盘模式）。
- **验收**：在 390px 宽度下可用；扫码流程有声音反馈；浏览器测试截图。

### T24 异步任务与导出中心

- **范围**：大数据量导出、批量操作改为后台任务（复用 worker），任务中心页查看进度与下载结果。
- **验收**：10 万行订单导出不阻塞请求；任务失败可见原因。

### T25 性能与可观测性

- **范围**：订单 / 库存等核心列表 N+1 排查、索引审查、慢查询日志、结构化日志、错误上报（可选 Sentry）、10 万订单级别压测脚本。
- **验收**：核心列表 P95 < 500ms（10 万订单数据量）；压测报告写入 `docs/`。

### T30 连接器增强（T15 遗留）

- **范围**：① 用 Walmart / TikTok / Amazon Ads 沙箱或测试店铺联调，修正与真实返回不一致的映射；② TikTok「物流渠道 ↔ 平台物流商 ID」映射（替代凭证里的单一默认值）；③ Amazon Sponsored Brands / Sponsored Display 报告；④ TikTok FBT 库存同步。
- **验收**：联调记录写入交接 / ADR；映射可在页面配置；新增报告类型有 mock 测试。
- **依赖**：需要负责人提供测试账号；② 需要确认按渠道还是按店铺配置。

### T26 ～ T29

见看板标题，开工前由认领人补充任务卡（背景 / 范围 / 验收 / 涉及模块）。

## 5. 新任务卡模板

复制 [`templates/task-card.md`](templates/task-card.md) 的内容追加到 §4，并在 §3 看板表尾加一行。
