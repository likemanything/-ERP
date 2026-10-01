# 架构决策记录（ADR）

记录「为什么这样设计」。改动涉及下列决策时先读对应 ADR；要推翻某个决策，新增一条 ADR 并把旧的标记为「已废弃」。
新 ADR 使用模板 [`../ai/templates/adr.md`](../ai/templates/adr.md)，编号顺延。

| 编号 | 决策 | 状态 |
| --- | --- | --- |
| [0001](0001-row-level-multi-tenancy.md) | 行级多租户：会话事件自动加租户条件 | 已采纳 |
| [0002](0002-fifo-cost-layers.md) | FIFO 批次成本层，采购成本与物流成本分开 | 已采纳 |
| [0003](0003-distribution-orders-reuse-sales-orders.md) | 分销订单复用销售订单（每个分销商一个虚拟店铺） | 已采纳 |
| [0004](0004-approval-engine-fallback.md) | 审批引擎：命中流程才启用，否则回退单级权限 | 已采纳 |
| [0005](0005-server-side-pdf.md) | 打印由后端生成 PDF（reportlab） | 已采纳 |
| [0006](0006-connector-dto.md) | 平台对接：连接器 + 标准 DTO | 已采纳 |
