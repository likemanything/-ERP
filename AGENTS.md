# AGENTS.md

本仓库面向所有 AI 编码代理（Claude Code、Codex、Cursor、Copilot、Gemini 等）与人类开发者使用同一套规范：

- **入口与硬性约定**：[`CLAUDE.md`](CLAUDE.md)（不止给 Claude 用，所有代理都必须遵守）
- **完整文档**：[`docs/ai/`](docs/ai/)，第一次进入请从 [`docs/ai/00-onboarding.md`](docs/ai/00-onboarding.md) 开始
- **任务看板**：[`docs/ai/08-roadmap.md`](docs/ai/08-roadmap.md)（开工前登记，完工后更新）
- **交接记录**：[`docs/handoff/`](docs/handoff/)（接手未完成工作前先读）

最少必须知道的命令：

```bash
cd backend && uv sync && uv run pytest -p no:logging && uv run ruff check app tests
cd frontend && npm ci && npm run typecheck && npm run build
```

> 维护约定：修改规范时只改 `CLAUDE.md` 与 `docs/ai/`，本文件只做索引，避免两处内容漂移。
