# 07 · 踩坑记录

都是本仓库开发中真实遇到过的问题。修掉一个新坑，就在对应分类追加一条：**现象 → 原因 → 正确做法**。

## 数据库 / SQLAlchemy

**PostgreSQL 报 `FOR UPDATE cannot be applied to the nullable side of an outer join`**
原因：模型有 `lazy="joined"` 关系（如 `Distributor.level`），`with_for_update()` 会锁到外连接的表。
做法：一律 `with_for_update(of=Model)`；`get_or_404(..., for_update=True)` 已内置。

**PostgreSQL 报 `could not identify an equality operator for type json`**
原因：对含 JSON 列的实体做 `SELECT DISTINCT`（或 `.distinct()` + join）。
做法：先查 ID 子查询，再 `Model.id.in_(subquery)`。

**`TypeError: unsupported operand type(s) for +: 'decimal.Decimal' and 'NoneType'`**
原因：`mapped_column(default=0)` 是 INSERT 时才生效的 Python 侧默认值，新建对象在 flush 前参与计算时字段仍是 `None`。
做法：构造时显式赋值所有参与计算的数值字段（参考 `distribution/service.py::place_order` 创建订单明细）。

**关系属性是旧数据**
原因：`SessionLocal(expire_on_commit=False)`，提交后对象不会自动刷新；新建的关联对象不会自动出现在已加载的关系里。
做法：需要最新数据时 `db.get(Model, id)` / `db.refresh(obj)`，或手动设置关系属性。

**JSON 列修改不保存**
原因：原地修改 dict（`order.charge_detail["x"] = 1`）不会被识别为变更。
做法：整体赋新值：`order.charge_detail = {**(order.charge_detail or {}), "x": 1}`。

**SQLite 上迁移失败（给已有表加外键 / 改列）**
原因：SQLite 不支持 `ALTER TABLE ADD CONSTRAINT`。
做法：`with op.batch_alter_table("表") as batch_op:`（env.py 已对 SQLite 开启 `render_as_batch`，但 autogenerate 生成的 `op.add_column/create_foreign_key` 需手动改写）。

**`alembic check` 报有差异 / autogenerate 生成一堆无关改动**
原因：在不是停在 head 的库、或用 `create_all` 建的开发库上 autogenerate。
做法：在干净测试库 `upgrade head` 后再生成（见 04-workflow §4）。

**只在 SQLite 测试通过**
SQLite 不支持行锁语义、对 JSON / DISTINCT / 外键检查更宽松；CI 会在 PostgreSQL 上失败。提交前两库都跑。

## FastAPI / 业务

**`GET /orders/scan` 返回 422（"scan" 不是整数）**
原因：`/orders/{order_id}` 先注册，静态路径被它匹配。
做法：静态路径定义在 `/{id}` 之前，或使用独立前缀（`/fulfillment/scan`）。

**分销商账号调后台接口 403 / 员工账号访问门户 403**
这是设计：`get_ctx` 拒绝 `user_type=distributor`，门户只接受分销商。两类都要用的接口（`/auth/me`）用 `get_any_ctx`。

**审批人点「通过」提示缺少权限**
原因：接口仍用 `perm("purchase:order:approve")`，而流程里的审批人不一定有这个权限。
做法：审批接口依赖 `get_ctx`，在 service 里：`approval.act()` 返回 `None` 时才 `ctx.require(...)`。

**嵌套事务里提前 `commit`**
被其他 service 调用的函数（`post_txn`、`approval.act`、`after_ship`、库存引擎）不要提交，否则外层的 savepoint / 回滚失效。

**`audit_order(force=True)` 直接改了 `qty_locked`**
平台已发货补扣库存时为允许负库存直接调整余额，是已知例外，不要在其他地方模仿；新代码一律走 `InventoryService`。

**演示账号「已存在」**
用户名全局唯一（跨企业）；`seed-demo` 重复执行会跳过，需要干净数据就重建库（见 00-onboarding）。

## 前端 / Ant Design 6

**`Form.List` 的默认值打开就是空的（只在开发环境）**
原因：React StrictMode 会挂载 → 卸载 → 再挂载；`Form preserve={false}` 时列表字段卸载后被置为 `undefined`（普通字段会回落到初始值，列表字段不会）。
做法：`FormModal` 传 `preserve`，并在每次打开时换 `key` 让表单重新创建（参考 `pages/system/ApprovalFlows.tsx`）。

**表单校验失败时控制台出现 `Uncaught (in promise) Object`**
已在 `FormModal` 内部捕获 `validateFields` 的异常；自己写 `Modal + Form` 时也要 `try/catch`。

**`List` 组件告警 deprecated**：antd 6.6 起废弃，改为自定义渲染。

**Input 输入时丢焦点**：动态增删 `suffix` / `prefix` 会重建 DOM，始终传一个元素（`<span />`）。

**`Table rowKey={(r, i) => i}` 告警**：给数据补一个稳定 key 字段。

**其他 v6 改名**：见 [03-conventions §2.2](03-conventions.md#22-ant-design-v6-写法)。

**PDF 新窗口被浏览器拦截**
原因：`await` 请求之后再 `window.open` 失去了用户手势。
做法：用 `api/client.ts::openPdf`（先同步打开空窗口，再写入 blob URL）。

**下载 / PDF 接口报错时提示 `[object Blob]`**
原因：`responseType: 'blob'` 时错误体也是 Blob。`download` / `openPdf` 已内置解析，自己写要用同样方式。

**react-query 列表不刷新**：`useReload(queryKey)` 的 key 必须与 `DataTable queryKey` 一致；下拉缓存 key 以 `'options'` 开头，保存主数据后 `invalidateQueries({ queryKey: ['options'] })`。

## PDF / 打印

**PDF 中文显示为空白或方块**：内置 CID 字体不嵌入，依赖阅读器字体。生产设置 `ERP_PDF_FONT_PATH`（Docker 已内置文泉驿）。
**条码超出标签**：`_barcode` 会按宽度自动缩小条宽，过长内容抛 `BizError`；不要把很长的文本当条码。
**部分符号缺字**：□ √ 安全，☐ ✓ 在某些字体里没有。

## 测试与工具环境（AI 代理常见）

- 全量测试或浏览器脚本超过工具的单条命令超时：放后台运行，结束后读输出文件。
- `pkill -f <pattern>` 可能匹配到执行它的 shell 自身导致命令异常退出：用保存的 PID（`kill $(cat api.pid)`）停止进程。
- `uvicorn` 不带 `--reload` 时改完后端要重启，否则浏览器测的是旧代码。
- 浏览器测试数据要幂等（名称带时间戳）；复用同一库重复跑会遇到唯一约束（409）。
- Docker Hub 可能限流，构建镜像失败时可以先用本地方式验证生产模式（`ERP_FRONTEND_DIST` 指向 `frontend/dist`）。
- 沙箱里浏览器路径不同：Playwright 用 `executablePath` 指定本机 Chromium，不要 `playwright install`。
