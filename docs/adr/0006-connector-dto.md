# ADR-0006：平台对接采用「连接器 + 标准 DTO」

- 状态：已采纳
- 日期：2026-10-01

## 背景

需要对接的平台很多（Amazon、Walmart、TikTok、Shopify、Temu…），各平台字段、分页、认证差异大，但 ERP 内部的订单 / Listing / 库存 / 结算 / 广告处理逻辑相同。

## 决策

- 每个平台实现一个 `PlatformConnector`，只负责调用平台 API 并输出 `dto.py` 中的标准 DTO；声明 `capabilities` 与 `credential_fields`。
- 同步服务 `sync_shop` 只依赖 DTO，负责幂等落库、游标、错误隔离、授权失效标记。
- 连接器统一使用基类的 `request()`（限流退避、授权错误识别），测试用 `httpx.MockTransport`。
- 演示模式（`DemoConnector`）生成确定性数据，用于体验与端到端测试。

## 影响

- 新平台的工作量集中在一个文件 + 测试；订单、成本、利润无需改动。
- DTO 是平台与 ERP 之间的契约，新增字段要考虑所有连接器；删除字段视为破坏性变更。
- 前端授权表单由 `credential_fields` 动态渲染，无需为新平台写页面。
