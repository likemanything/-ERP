# 03 · 编码规范

原则：**像周围代码一样写**。新代码的命名、注释密度、错误处理风格以同模块已有代码为准；本文件记录跨模块统一的部分。

## 1. 后端

### 1.1 模块结构

```
app/modules/<域>/
├── models.py    ORM 模型（继承 TenantModel）
├── schemas.py   Pydantic 输入 / 输出（Schema、ORMOut）
├── service.py   业务逻辑（函数式，第一个参数 ctx: Ctx）
└── router.py    薄路由：参数校验 → 调 service → 组装输出
```

新模块：在 `app/models.py` 导入 models，在 `app/main.py` 注册 router。复杂模块可以拆文件（如 `distribution/portal.py`、`fulfillment/printing.py`、`warehouse/inventory.py`）。

### 1.2 模型

```python
class PickWave(TenantModel):
    """拣货波次：……（类 docstring 用中文说明业务含义）"""

    __tablename__ = "pick_waves"
    __label__ = "拣货波次"            # get_or_404 的报错名称

    wave_no: Mapped[str] = mapped_column(String(32), index=True)
    warehouse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("warehouses.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="picking", index=True, doc="picking/picked/completed/cancelled")
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    picked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
```

- 外键列 `BigInteger` + `index=True`；状态列 `String(16)` + `index=True`，取值写在 `doc` 或 `common/enums.py`。
- 金额 `MoneyColumn`（Numeric(18,4)）；尺寸重量用已有的 `Dim`/`Numeric(12,3)`；时间用 `UTCDateTime`（存 UTC）。
- 明细关系：`relationship(back_populates=..., cascade="all, delete-orphan", lazy="selectin", order_by=...)`。
- 唯一约束要带 `tenant_id`：`UniqueConstraint("tenant_id", "code")`。
- **Python 侧 `default=` 只在 INSERT 时生效**：在 flush 前就参与计算的数值字段要显式赋值。
- JSON 列整体替换才能被检测到变更：`order.charge_detail = {**old, "refunded": x}`，不要原地修改。

### 1.3 Schema

- 输入：`class XxxIn(Schema)`，用 `Field(min_length=..., ge=..., pattern=...)` 做校验；更新用 `XxxUpdate`（全部可选，`model_dump(exclude_unset=True)`）。
- 输出：`class XxxOut(ORMOut)`，金额字段用 `Money`（序列化为 float），敏感字段（成本、密钥）按权限置空或不输出。
- `Field(description="中文说明")`，会出现在 `/api/docs`。

### 1.4 Service

```python
def complete_wave(ctx: Ctx, wave_id: int) -> PickWave:
    db = ctx.db
    wave = get_or_404(db, PickWave, wave_id, "拣货波次", for_update=True)   # 需要并发保护时加行锁
    if wave.status not in ACTIVE:
        raise BizError("波次已完成或已取消")                                 # 中文、可直接展示给用户
    ...
    audit(ctx, "update", "pick_wave", wave.id, f"波次 {wave.wave_no} 完成")
    db.commit()
    return wave
```

- 写操作：校验 → 变更 → `audit()` → `commit()`。
- **被其他事务调用的内部函数不提交**（例如 `post_txn`、`approval.act`、`after_ship`、`InventoryService` 的方法），由最外层 service 提交。
- 批量操作逐条隔离：`with db.begin_nested():`（savepoint），单条失败收集错误继续，最后统一 `commit`（参考 `order/service.py::batch`、导入接口）。
- 行锁：`select(Model)...with_for_update(of=Model)`，或 `get_or_404(..., for_update=True)`。
- 读设置：`get_setting(db, "purchase.require_approval")`；新参数先在 `system/settings_registry.py` 定义。
- 单据编号：`next_doc_no(db, "前缀")`，前缀登记在 [01-domain §6](01-domain.md#6-单据编号)。
- 站内消息：`db.add(Notification(user_id=可选, category="approval", title=..., content=..., link="/前端路由"))`。
- 金额计算：`Decimal` + `q2()`（2 位）/ `q4()`（4 位）；外币折算 `to_base(db, amount, currency, date)`。
- 时间：`utcnow()`；订单按店铺时区算 `local_date`（`order/service.py::local_date_of`）。

### 1.5 Router

```python
router = APIRouter(prefix="/fulfillment", tags=["仓储作业与打印"])

@router.get("/waves", response_model=Page[WaveOut], summary="拣货波次列表")
def list_waves(status: str | None = None, params: PageParams = Depends(page_params),
               ctx: Ctx = Depends(perm("order:view"))):
    page = paginate(ctx.db, select(PickWave).order_by(PickWave.id.desc()), params)
    page["items"] = wave_out(ctx, page["items"])      # 批量补充名称，避免 N+1
    return page
```

- `summary=` 写中文；列表返回 `Page[...]`；下拉接口 `/xxx/options` 返回 `list[Option]`。
- **静态路径与 `/{id}` 冲突**：`GET /orders/scan` 会被 `GET /orders/{order_id}` 抢先匹配。新接口要么放在 `/{id}` 之前定义，要么换前缀（如 `/fulfillment/scan`）。
- 输出组装用 `xxx_out(ctx, rows)` 批量查关联名称（一次 `IN` 查询），不要在循环里逐条 `db.get`。
- 简单主数据直接用 `build_crud_router(...)`（见 `distribution/router.py` 的等级）。
- Excel：`COLUMNS = [(key, 中文表头)]` → `export_xlsx` / `template_response` / `read_upload`，导入返回 `ImportResult(created, updated, skipped, errors)`。
- PDF：返回 `pdf_response(content, "文件名.pdf")`（inline）。

### 1.6 权限与数据范围

- 权限码格式 `域:动作` 或 `域:子域:动作`（`purchase:order:approve`），在 `core/permissions.py` 对应分组追加；需要时加入 `PRESET_ROLES`（只影响新建企业）。
- 按店铺的数据：查询时 `if ctx.shop_ids is not None: stmt = stmt.where(X.shop_id.in_(ctx.shop_ids))`，单条访问 `ctx.require_shop(shop_id)`。
- 成本类字段：输出前 `ctx.can("product:cost:view")`，无权限置 `None`。

### 1.7 安全

- 店铺凭证 `encrypt_json` 存 `credentials_enc`，接口永不回显；API Key 只存前缀 + sha256 哈希，明文只返回一次。
- 分销商门户不得返回成本、供应商、内部库存明细。
- 不要把任何真实凭证、客户数据写进代码、测试或文档。

## 2. 前端

### 2.1 页面骨架

```tsx
export default function Suppliers() {
  const [editing, setEditing] = useState<S | null>(null)
  const [open, setOpen] = useState(false)
  const reload = useReload('suppliers')          // 与 DataTable 的 queryKey 一致
  const run = useAction()                         // 带确认与成功/失败提示的写操作
  return (
    <>
      <DataTable<S> queryKey="suppliers" url="/suppliers" filters={[...]} toolbar={() => <Perm code="supplier:edit">…</Perm>} columns={[...]} />
      <FormModal open={open} title="…" onCancel={() => setOpen(false)} initialValues={editing ?? {...}}
        onSubmit={async (v) => { await api.post('/suppliers', v); reload() }}>
        <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
      </FormModal>
    </>
  )
}
```

- 新页面：`src/pages/<域>/Xxx.tsx`（默认导出）→ 在 `router/routes.tsx` 的对应分组加 `{ path, label, perm, element: p(() => import(...)) }`。
- 列表：`DataTable`（筛选、分页、导出、工具栏、选择）；写操作：`useAction()(fn, { confirm, success, onDone })`；表单弹窗：`FormModal`（含 `Form.List` 时传 `preserve` + 每次打开换 `key`，见 07-pitfalls）。
- 明细行：`LinesEditor`（产品 / Listing / 数字 / 金额列）。
- 下拉：优先用 `components/selects.tsx` 里的 `XxxSelect`；新增远程下拉在 `hooks/useOptions.ts` 加 hook（queryKey 以 `'options'` 开头，保存后 `invalidateQueries({queryKey:['options']})`）。
- 状态展示：`StatusTag dict={XXX_STATUS}`，字典加在 `utils/dicts.ts`；金额 / 日期用 `utils/format.ts`。
- 按钮级权限：`<Perm code="xxx:edit">`，`usePerm()` 做逻辑判断。
- 文件：导出 `download(url, params)`；PDF `openPdf(url, { body | params })`（必须在点击事件中同步调用）；上传 `api.upload` / `ImportModal`。
- react-query：列表 key = DataTable 的 `queryKey`；详情 key `[queryKey, 'detail', id]`，这样 `useReload(queryKey)` 会一并刷新。

### 2.2 Ant Design v6 写法

| 不要 | 要 |
| --- | --- |
| `Space direction` | `Space orientation` |
| `Modal/Drawer destroyOnClose` | `destroyOnHidden` |
| `Drawer width` | `Drawer size={760}` |
| `Card bordered={false}` | `Card variant="borderless"` |
| `Modal maskClosable` | `mask={{ closable: false }}` |
| `Select showSearch optionFilterProp` | `showSearch={{ optionFilterProp: 'label' }}` |
| `Alert message` | `Alert title` |
| `Statistic valueStyle` | `Statistic styles={{ content: {...} }}` |
| `Steps/Timeline description / children` | `content` |
| `Divider orientation="left"` | `Divider titlePlacement="start"` |
| `List` | 自定义渲染（`List` 在 6.6 已废弃） |
| `Table rowKey={(r, i) => i}` | 给数据加稳定 key |
| 动态增删 `Input` 的 `suffix/prefix` | 始终传一个元素（如 `<span />`），否则会丢焦点 |

### 2.3 分销商门户

- 页面放 `src/portal/pages/`，布局 `PortalLayout`，文案全部走 `useT()`（`src/portal/i18n.ts` 的 DICT 同时提供中 / 英）。
- 门户接口只调用 `/portal/*`；`antd` 语言随门户语言切换（`ConfigProvider locale`）。

## 3. 测试

- 位置 `backend/tests/test_<域>.py`；夹具：`api`（已注册企业的管理员 Api）、`factory`（快速造数）、`client`（TestClient，用于登录其他账号）。
- `Api.get/post/put/delete(url, json, expect=200)` 自动断言状态码；`expect=422/403/409` 测错误路径。
- 每个业务功能至少覆盖：主流程、关键金额 / 数量断言、权限或隔离、一个错误路径。
- 外部接口一律 `httpx.MockTransport`；PDF 只断言 `content.startswith(b"%PDF")` 与 content-type，版式用 `pdftoppm` 人工看。
- 两库都要过：默认 SQLite；`TEST_DATABASE_URL=postgresql+psycopg://erp:erp@localhost/erp_test`。
- 测试数据不要依赖执行顺序；需要多账号时用 `/system/users` 创建并 `Api(client, token)` 登录（参考 `test_assembly_approval.py`）。

## 4. 提交与分支

- 分支：`<代理或人名>/<主题>`，例如 `claude/xxx`、`codex/walmart-connector`、`alice/fix-profit-report`。
- 提交信息：英文祈使句标题（≤ 72 字符），推荐 `feat(scope): …` / `fix(scope): …` / `docs: …` / `refactor: …` / `test: …`；
  正文用要点说明「做了什么、为什么」；AI 提交末尾附工具要求的署名行（如 `Co-Authored-By: …`）。
- 一个提交只做一件事，且每个提交都能通过 lint 与测试；迁移与对应模型改动放在同一个提交。
- 文档、注释、UI 文案用简体中文；代码标识符用英文。
