# ADR-0001：行级多租户，会话事件自动加租户条件

- 状态：已采纳
- 日期：2026-10-01

## 背景

系统既要支持私有化部署（单企业），也要支持 SaaS（多企业共用一个库）。中小卖家数量多、数据量中等，每企业一个库运维成本高。
最大的风险是开发者忘记写 `tenant_id` 条件导致数据串租户。

## 决策

- 所有业务表继承 `TenantModel`（带 `tenant_id`）。
- `Session` 的 `do_orm_execute` 事件对所有 ORM 查询自动追加 `with_loader_criteria(TenantMixin, tenant_id == 当前租户)`；
  `before_flush` 事件为新对象填充 `tenant_id` 并拒绝写入其他租户的数据。
- 当前租户在认证依赖中写入 `db.info["tenant_id"]`；系统级查询显式 `.execution_options(skip_tenant_filter=True)`。
- 用户名全局唯一，登录不需要输入企业编码。

## 备选方案

- 每企业一个 schema / 数据库：隔离更强，但迁移、连接池、跨企业运维复杂。
- 手写过滤：容易遗漏，评审成本高。

## 影响

- 业务代码不写租户条件，降低出错概率；但**原生 SQL / Core 语句不会被自动过滤**，必须使用 ORM 或自行加条件。
- 唯一约束需要包含 `tenant_id`。
- 后台任务需要用 `system_ctx(db, tenant_id)` 设置租户。
