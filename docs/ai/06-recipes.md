# 06 · 开发配方（照着做）

每个配方列出**要改的所有位置**，漏改是最常见的返工原因。示例代码以仓库现有写法为准。

---

## 新增业务模块

以「质检单 `qc`」为例：

1. **模型** `backend/app/modules/qc/models.py`：继承 `TenantModel`，明细表 `relationship(... lazy="selectin", cascade="all, delete-orphan")`。
2. **注册模型**：`backend/app/models.py` 按字母序加 `from app.modules.qc import models as qc_models  # noqa: F401`。
3. **Schema** `schemas.py`：`QcIn / QcUpdate / QcOut(ORMOut)`，金额用 `Money`。
4. **Service** `service.py`：`create_xxx(ctx, data)`、状态流转函数；`next_doc_no(db, "QC")`（先查 [01-domain §6](01-domain.md#6-单据编号) 前缀表并登记）；写操作 `audit()` + `commit()`。
5. **Router** `router.py`：`APIRouter(prefix="/qc-orders", tags=["质检"])`，列表 `Page[QcOut]` + `paginate`，输出用批量 `qc_out(ctx, rows)`。
6. **注册路由**：`backend/app/main.py` 的 router 列表末尾追加。
7. **权限**：见下一节。
8. **迁移**：见「修改模型并生成迁移」。
9. **测试** `backend/tests/test_qc.py`：主流程 + 错误路径 + 权限。
10. **前端**：页面 `frontend/src/pages/warehouse/Qc.tsx`；字典 `utils/dicts.ts` 加 `QC_STATUS`；路由 `router/routes.tsx` 加菜单项（带 `perm`）。
11. **演示数据**（可选）：`app/cli.py::seed_demo` 末尾追加一段。
12. **文档**：01-domain（业务规则、状态机、前缀）、02-architecture（模块地图一行）、08-roadmap（状态）。

---

## 新增权限点

1. `backend/app/core/permissions.py` 对应分组追加 `("qc:view", "查看质检单")`。
2. 需要默认授予的预置角色：改 `PRESET_ROLES`（只影响**新建**企业；已有企业由管理员在「角色权限」中勾选）。
3. 接口使用 `Depends(perm("qc:view"))`；前端路由 `perm: 'qc:view'`、按钮 `<Perm code="qc:edit">`。
4. 测试：创建只有部分权限的角色与用户，断言 403（参考 `test_auth_tenancy.py`）。

---

## 新增系统参数

1. `backend/app/modules/system/settings_registry.py` 追加 `SettingDef("qc.require_photo", False, "质检需上传照片", "说明")`。
2. 读取：`get_setting(db, "qc.require_photo")`；写入：`update_settings(ctx, {"qc.require_photo": True})`。
3. 「系统参数」页面会自动显示（布尔 → 开关，数字 → 数字框）；如果参数属于某个模块的专属设置页（如分销），在 `pages/system/Settings.tsx` 的过滤里排除该前缀，并在模块页面提供编辑。

---

## 新增单据编号前缀

`next_doc_no(db, "QC")` 即可（按企业 + 前缀 + 日期自动建序列）。**前缀先在 01-domain 的表里登记**，避免与现有前缀重复。

---

## 新增 Excel 导入 / 导出

```python
QC_COLUMNS = [("order_no", "单号"), ("sku", "SKU"), ("qty", "数量")]

@router.get("/qc-orders/export", summary="导出质检单")
def export(ctx: Ctx = Depends(perm("qc:view"))):
    rows = [...]                                          # list[dict]，键与 COLUMNS 对应
    return export_xlsx("质检单.xlsx", QC_COLUMNS, rows)

@router.get("/qc-orders/import-template", summary="导入模板")
def template(_: Ctx = Depends(perm("qc:view"))):
    return template_response("质检单导入模板.xlsx", QC_COLUMNS, {"order_no": "QC001", "sku": "SKU-1", "qty": 1})

@router.post("/qc-orders/import", response_model=ImportResult, summary="导入质检单")
def import_(file: UploadFile = File(...), ctx: Ctx = Depends(perm("qc:edit"))):
    rows = read_upload(file, QC_COLUMNS)                  # 每行带 _row 行号
    result = ImportResult()
    for r in rows:
        sp = ctx.db.begin_nested()
        try:
            ...; sp.commit(); result.created += 1
        except BizError as exc:
            sp.rollback(); result.skipped += 1; result.errors.append(f"第 {r['_row']} 行：{exc.message}")
    ctx.db.commit()
    return result
```

前端：`DataTable exportUrl="/qc-orders/export"`；导入用 `<ImportModal uploadUrl="/qc-orders/import" templateUrl="/qc-orders/import-template" />`。

---

## 新增平台连接器

1. `backend/app/integrations/<platform>.py`：

```python
class XxxConnector(PlatformConnector):
    platform = "xxx"                                  # 与 Shop.platform 一致
    capabilities = frozenset({ORDERS, LISTINGS})      # 支持的同步类型
    credential_fields = [("app_key", "App Key", False), ("app_secret", "App Secret", True)]  # (键, 中文标签, 是否密文)

    def test_connection(self) -> dict: ...
    def fetch_orders(self, updated_after: datetime) -> Iterator[OrderDTO]: ...   # 分页用生成器
    def fetch_listings(self) -> Iterator[ListingDTO]: ...
    def confirm_shipment(self, order) -> None: ...    # 可选：自发货回传运单号
```

   - HTTP 一律用 `self.request(...)`（自带 429/5xx 退避、401/403 → `ConnectorError(auth=True)`）。
   - 平台单号 → `platform_order_id`；平台订单行 ID → `OrderItemDTO.platform_item_id`（回传运单号时要用）。
   - 状态映射到 `pending / unshipped / shipped / delivered / cancelled`；平台仓发货的订单 `fulfillment="FBA"`。
   - 金额 `Decimal`；时间带时区（UTC）。
   - 需要刷新 token 的平台：刷新后更新 `self.credentials` 并写回 `self.shop.credentials_enc = encrypt_json(...)`（同步服务会提交）。
2. `registry.py` 的 `CONNECTORS` 注册。
3. 站点：`app/modules/shop/marketplaces.py` 确认有该平台站点；平台仓发货的平台需要 FBA 类虚拟仓时扩展 `shop/router.py::ensure_fba_warehouse`。
4. 测试：`httpx.Client(transport=httpx.MockTransport(handler))` 注入，断言请求（头、签名、分页参数）与 DTO 映射；参考 `tests/test_connectors.py`。端到端同步：`monkeypatch.setattr("app.modules.integration.service.get_connector", ...)` 后调用 `POST /shops/{id}/sync`（`background: false`），见 `test_walmart_wfs_order_sync_end_to_end`。
5. 文档：README「对接平台」表、02-architecture §7、08-roadmap。

---

## 新增审批单据类型

以「调拨单 `transfer`」为例（引擎见 `approval/service.py`）：

1. `approval/service.py::DOC_TYPES` 加 `"transfer": "调拨单"`；`approval/schemas.py::FlowIn.doc_type` 的 `pattern` 加上 `transfer`。
2. 提交时启动：

```python
if get_setting(db, "transfer.require_approval") or approval.requires_approval(db, "transfer", amount, currency):
    doc.status = "pending"
    approval.start(ctx, "transfer", doc.id, doc_no=doc.doc_no, amount=amount, currency=currency,
                   summary="调拨 xxx", link="/stock-documents")
```

3. 审批 / 驳回函数：

```python
res = approval.act(ctx, "transfer", doc.id, True, comment)   # 驳回传 False 与原因
if res is None:
    ctx.require("inventory:doc:approve")                      # 没有流程 → 原单级权限
elif res == "pending":
    audit(...); ctx.db.commit(); return doc                   # 还有下一级
# res == "approved" / "rejected" → 执行单据自身的通过 / 驳回逻辑
```

4. 单据作废 / 撤回时 `approval.cancel_pending(db, "transfer", doc.id)`。
5. 审批 / 驳回接口依赖改为 `get_ctx`（让流程中的审批人即使没有原权限也能审批）。
6. `approval/router.py::act` 增加分派分支。
7. 前端：`pages/system/ApprovalFlows.tsx` 的 `DOC_LABEL`、`pages/approval/MyApprovals.tsx` 的 `DOC_TYPES`；单据详情加 `<ApprovalTimeline docType="transfer" docId={id} />`。
8. 测试：参考 `tests/test_assembly_approval.py`（多级、会签 / 或签、驳回后重提、管理员代审批）。

---

## 新增打印模板（PDF）

1. 模板函数放 `fulfillment/printing.py`（或模块自己的 `printing.py`）：
   - 条码标签：组装 `LabelItem(code, lines, copies)` → `labels_pdf(items, size_key, skip=)`。
   - 文档：`story = [_header(...), Spacer(...), grid(data, col_widths)]` → `doc_pdf(story, pagesize=A4, title=...)`；条码用 `BarcodeFlowable`；文本用 `p(text, size)`（自动转义）。
2. 路由返回 `pdf_response(content, "文件名.pdf")`；权限用查看权限。
3. 前端：`openPdf('/xxx.pdf', { params })` 或 `{ body }`（必须在点击事件里同步调用）。
4. 测试断言 `content.startswith(b"%PDF")`；用 `pdftoppm -png -r 70 file.pdf out` 生成图片人工检查版式与中文。
5. 字形注意：避免冷僻符号（☐✓ 在部分字体缺字），用 □ √；中文长文本用 `wrap_text` / `fit_text`。

---

## 新增前端页面与菜单

1. `frontend/src/pages/<域>/Xxx.tsx`，`export default function Xxx()`。
2. `router/routes.tsx` 对应分组 children 追加 `{ path: '/xxx', label: '中文菜单名', perm: 'xxx:view', element: p(() => import('@/pages/<域>/Xxx')) }`。
3. 需要隐藏在菜单外（详情页）：`hideInMenu: true`。
4. 字典与下拉：`utils/dicts.ts`、`hooks/useOptions.ts` + `components/selects.tsx`。
5. `npm run typecheck`，浏览器验证。

---

## 修改模型并生成迁移

1. 改 `models.py`（新列可空或给 `server_default`，避免已有数据失败）。
2. 按 [04-workflow §4](04-workflow.md#4-数据库迁移) 生成并审查迁移；修改已有表一律改成 `op.batch_alter_table`：

```python
def upgrade() -> None:
    with op.batch_alter_table("sales_orders") as batch_op:
        batch_op.add_column(sa.Column("wave_id", sa.BigInteger(), nullable=True))
        batch_op.create_index(batch_op.f("ix_sales_orders_wave_id"), ["wave_id"], unique=False)
        batch_op.create_foreign_key(batch_op.f("fk_sales_orders_wave_id_pick_waves"), "pick_waves", ["wave_id"], ["id"], ondelete="SET NULL")
```

3. 同步 schema 输出字段、前端展示、导入导出列（如适用）。
4. 两库验证迁移 + 全量测试。

---

## 新增库存变动类型

1. `common/enums.py::LedgerType` 追加（如 `QC_SCRAP = "qc_scrap"`）。
2. 业务代码通过 `InventoryService` 调用：`inv.outbound(wh, pid, qty, Ref("qc_order", id, no, "备注"), change_type=LedgerType.QC_SCRAP)`。
3. 前端 `utils/dicts.ts::LEDGER_TYPE` 加中文名与颜色，否则流水页显示英文。

---

## 新增分销商门户接口与页面

1. 接口写在 `distribution/portal.py`，依赖 `p: PortalCtx = Depends(get_portal_ctx)`；只查询 `p.distributor` 自己的数据；**不返回成本**。
2. 写操作调用 service 时传 `p.ctx`（操作人记为分销商）；需要 API Key 禁止的操作检查 `p.via_api_key`。
3. 页面放 `frontend/src/portal/pages/`，在 `App.tsx` 的 `/portal` 路由下注册，在 `PortalLayout` 菜单加入口。
4. 所有文案加到 `src/portal/i18n.ts` 的 DICT（中、英两列），页面用 `const t = useT()`。
5. 测试用分销商账号登录 + API Key 两种方式（参考 `tests/test_distribution.py`）。

---

## 新增演示数据

在 `app/cli.py::seed_demo` 末尾 `print` 之前追加独立段落（中文注释标题），通过 service 函数造数（保证与真实流程一致）；
新增登录账号要更新 [00-onboarding §3](00-onboarding.md#3-演示账号seed-demo-生成) 与 `print` 提示。执行一次 `seed-demo` 验证。

---

## 发送站内消息

```python
from app.modules.system.models import Notification
db.add(Notification(user_id=uid_or_None, category="approval", title="采购单 PO… 待您审批", content="摘要", link="/approvals"))
```

`user_id=None` 表示企业全员可见；前端右上角铃铛每分钟轮询。
