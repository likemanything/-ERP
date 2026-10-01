## 关联任务

T<编号>：<标题>（任务看板：`docs/ai/08-roadmap.md`）

## 做了什么

- 

## 为什么 / 业务口径

<!-- 业务规则或口径有变化时说明，并确认已更新 docs/ai/01-domain.md -->

## 验证

- [ ] `uv run ruff check app tests`
- [ ] 全量测试：SQLite ✅ / PostgreSQL ✅
- [ ] 迁移（如有）：两库 `upgrade → check → downgrade -1 → upgrade`
- [ ] 前端：`npm run typecheck && npm run build`
- [ ] 浏览器验证（如有页面改动）：截图 / 说明

## 影响面

- 数据库迁移：无 / 有（说明对现有数据的影响）
- 接口变更：无 / 新增 / 破坏性（说明）
- 权限 / 菜单 / 系统参数：无 / 有（说明）
- 冲突热点文件：<!-- 列出改动的热点文件，见 docs/ai/05-collaboration.md §5 -->

## 文档

- [ ] 已更新相关文档（01-domain / 02-architecture / 06-recipes / 07-pitfalls / 08-roadmap）
- [ ] 未完成部分已写交接记录（`docs/handoff/`）
