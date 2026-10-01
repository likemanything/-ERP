# 04 · 开发工作流与验收

## 1. 标准流程

```
认领任务(08-roadmap) → 建分支 → 读相关代码/测试/交接记录 → 写测试 → 实现 → 迁移(如有) → 自检(§6 完成定义)
→ 浏览器验证(改了页面) → 提交并推送 → 更新看板 → 发起 PR / 通知负责人
```

小步快跑：每完成一个可独立验证的子功能就提交一次（后端功能 + 测试 → 前端页面 → 演示数据），不要攒一个巨大的提交。

## 2. 运行与调试

```bash
# 后端
cd backend
uv run uvicorn app.main:app --reload --port 8000     # 改代码自动重载；无 --reload 时改完要重启
uv run python -m app.worker                           # 需要定时同步时

# 前端
cd frontend && npm run dev                            # http://localhost:5173
```

- 接口文档：<http://localhost:8000/api/docs>（所有 `summary` 为中文）。
- 用 curl 调接口：

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"demo","password":"demo123456"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s localhost:8000/api/v1/orders?page_size=1 -H "Authorization: Bearer $TOKEN"
```

## 3. 测试

```bash
cd backend
uv run pytest -p no:logging                                   # 全量（SQLite）
uv run pytest -p no:logging tests/test_orders.py -k fbm       # 单文件 / 单用例
TEST_DATABASE_URL=postgresql+psycopg://erp:erp@localhost/erp_test uv run pytest -p no:logging   # PostgreSQL
uv run ruff check app tests --fix
```

- 全量测试约 1～2 分钟；AI 工具单条命令有超时限制时，**放到后台运行**再读结果文件。
- 只在 SQLite 通过不算通过：行锁、JSON、DISTINCT、约束行为在 PostgreSQL 上不同（见 07-pitfalls）。

## 4. 数据库迁移

改了任何模型（新表、新列、索引、外键）都要生成迁移，且迁移与模型改动在同一个提交。

```bash
cd backend
# 1) 准备一个「停在当前 head」的干净 PostgreSQL 库（不要用开发库）
export ERP_DATABASE_URL=postgresql+psycopg://erp:erp@localhost/erp_test
psql postgresql://erp:erp@localhost/erp_test -c "drop schema public cascade; create schema public;"
uv run alembic upgrade head
# 2) 生成
uv run alembic revision --autogenerate -m "short description"
# 3) 审查生成的文件：
#    - 修改已有表（加列 / 外键 / 改类型）→ 改写为 with op.batch_alter_table("表名") as batch_op: ...（SQLite 必需）
#    - NOT NULL 新列给已有数据：加 server_default
#    - downgrade 与 upgrade 对称
# 4) 两库验证
for URL in postgresql+psycopg://erp:erp@localhost/erp_test sqlite:////tmp/mig.db; do
  rm -f /tmp/mig.db; export ERP_DATABASE_URL=$URL
  uv run alembic upgrade head && uv run alembic check && uv run alembic downgrade -1 && uv run alembic upgrade head
done
```

- `alembic heads` 必须只有一个；多人并行时的处理见 [05-collaboration §4](05-collaboration.md#4-数据库迁移协同)。
- 开发库如果是 `create_all` 建的（没有 alembic_version），重建演示数据即可，不要对它跑 autogenerate。

## 5. 浏览器验证（改了页面必须做）

用 Playwright（`playwright-core` + 本机 Chromium）跑一遍主流程，检查：功能可用、控制台无 error / warning、没有意外的 4xx/5xx。

```js
// verify.mjs —— 在任意目录 npm i playwright-core 后运行：node verify.mjs
import { chromium } from 'playwright-core'
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
const problems = []
page.on('console', (m) => ['error', 'warning'].includes(m.type()) && problems.push(m.text()))
page.on('pageerror', (e) => problems.push(e.message))
page.on('response', (r) => r.url().includes('/api/') && r.status() >= 400 && problems.push(`${r.status()} ${r.url()}`))

await page.goto('http://localhost:5173/login')
await page.fill('input[placeholder="用户名"]', 'demo')
await page.fill('input[placeholder="密码"]', 'demo123456')
await page.click('button[type="submit"]')
await page.waitForURL((u) => !u.pathname.startsWith('/login'))

await page.goto('http://localhost:5173/warehouse/waves')
await page.locator('.ant-table-row').first().waitFor()
await page.screenshot({ path: 'waves.png' })
// …点击、填写表单、断言成功提示：await page.getByText('已保存').waitFor()

console.log(problems.length ? problems.join('\n') : 'no problems')
await browser.close()
```

经验：
- 定位用可见文本 / 角色（`getByRole('button', { name: /保\s*存/ })`，antd 两字按钮中间有空格）。
- 下拉：点 `.ant-select` 容器而不是隐藏的 input；选项在 `.ant-select-dropdown:visible .ant-select-item-option`。
- 打开新窗口的 PDF：`Promise.all([context.waitForEvent('page'), click()])`，断言新页面 URL 为 `blob:`。
- 测试数据要幂等（名称带时间戳），否则第二次运行会 409；必要时先重建演示数据。
- 截图后**真的看一眼**：布局、空数据、金额格式、中文是否正常。

## 6. 完成定义

提交 / 交付前逐项确认：

- [ ] 功能符合任务卡的验收标准；业务口径与 [01-domain](01-domain.md) 一致（若改变口径，同步更新该文档）
- [ ] 后端：`ruff check` 通过；新增 / 修改的逻辑有测试；**SQLite 与 PostgreSQL 全量测试通过**
- [ ] 模型变更：迁移已生成、已审查、两库 `upgrade → check → downgrade -1 → upgrade` 通过
- [ ] 前端：`npm run typecheck && npm run build` 通过；浏览器跑过主流程，控制台无报错
- [ ] 权限：新接口有权限依赖；新权限码已登记；按店铺的数据有过滤
- [ ] 演示数据：新功能需要演示时更新 `app/cli.py::seed_demo`，并实际执行一次 `seed-demo`
- [ ] 文档：新增前缀 / 参数 / 权限 / 坑 / 架构变化已写入对应文档；[08-roadmap](08-roadmap.md) 状态已更新
- [ ] 未完成的部分写了交接记录（`docs/handoff/`）

## 7. CI（`.github/workflows/ci.yml`）

| Job | 步骤 |
| --- | --- |
| backend | `uv sync --frozen` → ruff → pytest(SQLite) → pytest(PostgreSQL 16) → 空库 `alembic upgrade head` + `alembic check` |
| frontend | `npm ci` → `npm run typecheck` → `npm run build` |
| docker | 构建生产镜像 |

触发：推送到 `main` / `master` / `claude/**`，以及所有 PR。依赖变更（`uv add` / `npm install`）要提交 lock 文件。

## 8. 部署

```bash
cp .env.example .env    # 设置 ERP_SECRET_KEY（必填）、ERP_ENCRYPTION_KEY（建议）、DB_PASSWORD
docker compose up -d --build     # db + web（启动时自动迁移）+ worker
```

升级：拉取新代码后 `docker compose up -d --build`，入口脚本会执行 `alembic upgrade head`。
