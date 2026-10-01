# 交接：Walmart / TikTok Shop / Amazon Advertising 连接器（任务 T15）

- 日期：2026-10-01
- 交接人：Claude Code 会话（分支 `claude/wizardly-meitner-h2vsdz`）
- 状态：**已暂停**（负责人要求先完成 AI 入职与协同文档）
- 任务卡：[08-roadmap · T15](../ai/08-roadmap.md#t15-平台连接器walmart--tiktok-shop--amazon-advertising)

## 1. 目标

为 Walmart（美国站）、TikTok Shop、Amazon Advertising API 实现原生连接器，输出标准 DTO，复用现有同步、订单、成本、广告分析逻辑。

## 2. 当前状态

**全部未提交**（在交接人的工作区）。如果你接手时工作区里没有这些文件，说明容器已回收，需要按下面的设计重新实现。

| 文件 | 状态 | 内容 |
| --- | --- | --- |
| `backend/app/integrations/walmart.py` | 新增，230 行 | OAuth client_credentials（`POST /v3/token`，Basic auth，`WM_SVC.NAME`、`WM_QOS.CORRELATION_ID` 头）；订单 `GET /v3/orders`（`lastModifiedStartDate`，`nextCursor` 分页，每个订单行一条明细、`platform_item_id=lineNumber`，`shipNode.type == WFSFulfilled` → `FBA`）；商品 `GET /v3/items`（`nextCursor`）；WFS 库存 `GET /v3/fulfillment/inventory`（offset 分页）；回传 `POST /v3/orders/{po}/shipping`（已知承运商用 `carrier`，否则 `otherCarrier`）；加拿大站直接报错不支持 |
| `backend/app/integrations/tiktok.py` | 新增，256 行 | 202309 API；签名 `sign(path, params, body, secret)`（排除 sign/access_token、按键排序拼接 key+value、前置 path、追加 body、secret 首尾包裹、HMAC-SHA256 hex）；`x-tts-access-token` 头；错误码 105002/36004004 自动刷新 token（`auth.tiktok-shops.com/api/v2/token/refresh`）并写回 `shop.credentials_enc`；`shop_cipher` 为空时调 `/authorization/202309/shops` 自动获取；订单 `POST /order/202309/orders/search`（每件一条 line_item，按 seller_sku 合并）；商品 `POST /product/202309/products/search`；回传 `POST /fulfillment/202309/orders/{id}/packages`（需凭证 `shipping_provider_id`） |
| `backend/app/integrations/amazon_ads.py` | 新增，147 行 | `AmazonAdsClient`：LWA（广告 refresh token，client 默认复用 SP-API）；`/v2/profiles` 按站点自动匹配 profile；报告 v3 `POST /reporting/reports`（SPONSORED_PRODUCTS / spAdvertisedProduct / DAILY / GZIP_JSON），轮询 `GET /reporting/reports/{id}`，下载预签名 URL 并解压；按 31 天切片；映射为 `AdMetricDTO`（sales7d / purchases7d / unitsSoldClicks7d） |
| `backend/app/integrations/amazon.py` | 修改 | `capabilities` 加 `ADS`；`credential_fields` 加 `ads_refresh_token / ads_client_id / ads_client_secret / ads_profile_id`；`__init__` 创建 `self.ads = AmazonAdsClient(self, mp)`；`supports(ADS)` 仅在配置了广告 refresh token 时为真；`fetch_ad_metrics` 委托 |
| `backend/app/integrations/registry.py` | 修改 | 注册 `walmart`、`tiktok` |

## 3. 已验证 / 未验证

已验证：
- `uv run ruff check app` 通过
- `platform_capabilities()` 输出：amazon[ads, fba_inventory, finances, listings, orders]、walmart[fba_inventory, listings, orders]、tiktok[listings, orders]
- 修改前的全量测试（54 个）在 SQLite / PostgreSQL 通过（本改动之后**没有重跑全量**）

未验证：
- **三个连接器都还没有任何测试**
- 没有在页面上走过授权表单（凭证字段由 `/integrations/platforms` 动态渲染，理论上无需改前端）

## 4. 下一步（按顺序）

1. 重跑全量测试，确认 `amazon.py` 改动没有破坏 `tests/test_integrations.py`。
2. 新建 `backend/tests/test_connectors.py`，全部用 `httpx.MockTransport`：
   - Walmart：token 请求带 Basic auth 与 `WM_SVC.NAME`；token 只换取一次；订单两页（`nextCursor`）；多行订单 / WFS 订单 → `FBA` / 全取消 → `cancelled` / 已发货带运单；`confirm_shipment` 请求体（lineNumber、数量、承运商 `carrier` vs `otherCarrier`）；商品 cursor 分页；WFS 库存 offset 分页；`WALMART_CA` 抛错。
   - TikTok：`sign()` 用固定输入断言摘要（独立用 hmac 计算期望值）；请求包含 app_key / timestamp / shop_cipher / sign 与 `x-tts-access-token`；`shop_cipher` 自动获取并写回凭证；105002 → 刷新 token → 重试成功、`shop.credentials_enc` 可解密出新 token；line_items 合并数量与金额；状态映射；`confirm_shipment` 缺 `shipping_provider_id` 报错。
   - Amazon Ads：没有 `ads_refresh_token` 时 `supports(ADS)` 为 False；profile 自动匹配；创建报告 → 轮询（PENDING → COMPLETED）→ gzip 下载 → DTO；`poll_interval` 设为 0；超过 31 天拆成两次报告。
3. **平台仓虚拟仓**：`shop/router.py::ensure_fba_warehouse` 目前只给亚马逊建 FBA 仓；Walmart WFS / TikTok FBT 订单映射为 `FBA` 后，`order/service.py::settle_fba_cost` 找不到平台仓会退化为按参考成本结转。需决定：扩展 `ensure_fba_warehouse` 到 walmart/tiktok（推荐），并让 `fetch_fba_inventory`（WFS）写入该仓。
4. 用 `/shops/{id}/test-connection` 与授权表单在浏览器检查凭证字段展示（中文标签、密文字段）。
5. 更新 README「对接平台」表、`docs/ai/02-architecture.md §7`、08-roadmap 状态；提交（建议拆两个提交：Walmart+TikTok、Amazon Ads）。

## 5. 风险与待决问题

- 接口细节基于公开文档实现，未用真实账号联调；上线前需要用沙箱 / 测试店铺验证（尤其 TikTok 签名与 Walmart 订单行状态）。
- TikTok 回传运单号需要平台的物流商 ID，目前只支持在凭证里配置一个默认值；如需按订单渠道映射，需要新增「渠道 ↔ TikTok 物流商」映射（待负责人决定）。
- Amazon Ads 只拉取 Sponsored Products；Sponsored Brands / Display 是否需要，待负责人决定。
- Walmart 结算（Recon 报告）未实现，财务利润中的 Walmart 费用仍为预估。
