# 文档目录

| 目录 / 文件 | 内容 |
| --- | --- |
| [`ai/00-onboarding.md`](ai/00-onboarding.md) | 入职指南：环境、演示账号、阅读顺序、第一个任务 |
| [`ai/01-domain.md`](ai/01-domain.md) | 业务链路、状态机、分销规则、核心公式、单据编号、术语表 |
| [`ai/02-architecture.md`](ai/02-architecture.md) | 技术栈、目录、请求生命周期、多租户、模块地图、核心引擎、前端架构、配置 |
| [`ai/03-conventions.md`](ai/03-conventions.md) | 后端 / 前端 / 测试 / 提交规范 |
| [`ai/04-workflow.md`](ai/04-workflow.md) | 开发流程、测试、迁移、浏览器验证、完成定义、CI、部署 |
| [`ai/05-collaboration.md`](ai/05-collaboration.md) | 多人 / 多 AI 协同：任务生命周期、分支、迁移协同、冲突热点、评审、交接、沟通 |
| [`ai/06-recipes.md`](ai/06-recipes.md) | 配方：新增模块 / 权限 / 参数 / 导入导出 / 连接器 / 审批单据 / 打印 / 页面 / 迁移… |
| [`ai/07-pitfalls.md`](ai/07-pitfalls.md) | 踩坑记录 |
| [`ai/08-roadmap.md`](ai/08-roadmap.md) | 路线图、任务看板、任务卡 |
| [`ai/templates/`](ai/templates/) | 任务卡、交接记录、ADR 模板 |
| [`adr/`](adr/) | 架构决策记录 |
| [`handoff/`](handoff/) | 未完成工作的交接记录 |

AI 代理的入口是仓库根目录的 [`CLAUDE.md`](../CLAUDE.md) / [`AGENTS.md`](../AGENTS.md)。

**维护规则**：代码改动导致文档过时，在同一个 PR 里更新文档；文档之间不要复制大段内容，用链接互相引用。
