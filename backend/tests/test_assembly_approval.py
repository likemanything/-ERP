import pytest

from tests.conftest import Api


def _login(client, username, password) -> Api:
    return Api(client, Api(client).post("/auth/login", {"username": username, "password": password})["access_token"])


# ================================================================ 加工单
def test_assembly_and_disassembly_cost(api, factory):
    wh = factory.default_warehouse()
    a = factory.product(sku="CMP-A", purchase_cost=5)
    b = factory.product(sku="CMP-B", purchase_cost=2)
    kit = factory.product(sku="KIT-1", purchase_cost=0)
    factory.stock_in(wh["id"], a["id"], 10, unit_cost=5)
    factory.stock_in(wh["id"], b["id"], 20, unit_cost=2)

    body = {"order_type": "assemble", "warehouse_id": wh["id"], "product_id": kit["id"], "qty": 4, "processing_fee": 8,
            "lines": [{"product_id": a["id"], "qty_per_unit": 1}, {"product_id": b["id"], "qty_per_unit": 2}]}
    o = api.post("/assembly-orders", body)
    assert o["status"] == "draft" and [ln["qty"] for ln in o["lines"]] == [4, 8]
    assert o["lines"][0]["available"] == 10
    o = api.post(f"/assembly-orders/{o['id']}/complete")
    # 子件 4×5 + 8×2 = 36，加工费 8 → 成品单位成本 11
    assert o["status"] == "completed" and o["total_cost"] == 44 and o["unit_cost"] == 11
    assert o["lines"][1]["unit_cost"] == 2 and o["lines"][1]["amount"] == 16
    assert factory.inventory(wh["id"], kit["id"])["qty_on_hand"] == 4
    assert factory.inventory(wh["id"], a["id"])["qty_on_hand"] == 6
    assert factory.inventory(wh["id"], b["id"])["qty_on_hand"] == 12
    batch = api.get(f"/inventory/batches?product_id={kit['id']}")["items"][0]
    assert batch["unit_purchase_cost"] == 11
    api.post(f"/assembly-orders/{o['id']}/complete", expect=422)  # 不能重复执行
    assert api.get(f"/assembly-orders/recipe?product_id={kit['id']}") == [
        {"product_id": a["id"], "qty_per_unit": 1}, {"product_id": b["id"], "qty_per_unit": 2}]

    # 拆分 2 套：成本 22 按参考成本（A 5×2=10，B 2×4=8）分摊
    d = api.post("/assembly-orders", {**body, "order_type": "disassemble", "qty": 2, "processing_fee": 0})
    d = api.post(f"/assembly-orders/{d['id']}/complete")
    assert d["total_cost"] == 22
    assert abs(d["lines"][0]["amount"] - 22 * 10 / 18) < 0.01 and abs(sum(x["amount"] for x in d["lines"]) - 22) < 0.01
    assert factory.inventory(wh["id"], kit["id"])["qty_on_hand"] == 2
    assert factory.inventory(wh["id"], a["id"])["qty_on_hand"] == 8

    # 子件库存不足不能完成；组合产品不能作为成品
    big = api.post("/assembly-orders", {**body, "qty": 100})
    r = api.post(f"/assembly-orders/{big['id']}/complete", expect=422)
    assert "不足" in r["message"]
    bundle = factory.product(sku="BND-1", product_type="bundle", bundle_items=[{"component_id": a["id"], "quantity": 1}])
    api.post("/assembly-orders", {**body, "product_id": bundle["id"]}, expect=422)
    api.post("/assembly-orders", {**body, "lines": [{"product_id": kit["id"], "qty_per_unit": 1}]}, expect=422)
    api.post(f"/assembly-orders/{big['id']}/cancel")
    assert api.get("/assembly-orders?status=completed")["total"] == 2


# ================================================================ 多级审批
@pytest.fixture
def approvers(api, client):
    role = api.post("/system/roles", {"code": "cfo", "name": "财务总监", "permissions": ["dashboard:view"]})
    u1 = api.post("/system/users", {"username": "mgr1", "password": "mgr12345", "real_name": "采购经理", "role_ids": []})
    u2 = api.post("/system/users", {"username": "cfo1", "password": "cfo12345", "real_name": "财务总监", "role_ids": [role["id"]]})
    return role, u1, u2, _login(client, "mgr1", "mgr12345"), _login(client, "cfo1", "cfo12345")


def test_multi_level_po_approval(api, factory, approvers):
    role, u1, u2, mgr, cfo = approvers
    wh = factory.default_warehouse()
    s = factory.supplier(currency="CNY")
    p = factory.product(purchase_cost=10)
    api.post("/approval/flows", {"doc_type": "purchase_order", "name": "大额采购", "min_amount": 1000, "steps": [
        {"name": "采购经理", "approver_type": "user", "approver_ids": [u1["id"]]},
        {"name": "财务总监", "approver_type": "role", "approver_ids": [role["id"]], "mode": "all"},
    ]})
    api.post("/approval/flows", {"doc_type": "purchase_order", "name": "x", "steps": [
        {"approver_type": "user", "approver_ids": [999999]}]}, expect=422)

    # 小额：不命中流程，按原有单级审批
    small = api.post("/purchase-orders", {"supplier_id": s["id"], "warehouse_id": wh["id"], "lines": [{"product_id": p["id"], "qty": 5, "unit_price": 10}]})
    small = api.post(f"/purchase-orders/{small['id']}/submit")
    assert small["status"] == "pending_approval"  # 默认开启采购审批
    mgr.post(f"/purchase-orders/{small['id']}/approve", expect=403)  # 无审批权限
    assert api.get(f"/approval/documents/purchase_order/{small['id']}") == []

    big = api.post("/purchase-orders", {"supplier_id": s["id"], "warehouse_id": wh["id"], "lines": [{"product_id": p["id"], "qty": 200, "unit_price": 10}]})
    big = api.post(f"/purchase-orders/{big['id']}/submit")
    assert big["status"] == "pending_approval"
    assert mgr.get("/approval/pending/count")["count"] == 1 and cfo.get("/approval/pending/count")["count"] == 0
    cfo.post(f"/purchase-orders/{big['id']}/approve", expect=403)  # 还没到第二级
    po = mgr.post(f"/purchase-orders/{big['id']}/approve", {"comment": "价格合理"})
    assert po["status"] == "pending_approval"
    mgr.post(f"/purchase-orders/{big['id']}/approve", expect=403)  # 第二级不是他
    pending = cfo.get("/approval/instances?scope=mine")["items"]
    assert len(pending) == 1 and pending[0]["current_step"] == 1 and pending[0]["can_act"] is True
    inst = cfo.post(f"/approval/instances/{pending[0]['id']}/act", {"approve": True, "comment": "同意"})
    assert inst["status"] == "approved" and [r["user_name"] for r in inst["records"]] == ["采购经理", "财务总监"]
    assert api.get(f"/purchase-orders/{big['id']}")["status"] == "approved"

    # 驳回：任一级驳回即结束，重新提交生成新的审批
    po2 = api.post("/purchase-orders", {"supplier_id": s["id"], "warehouse_id": wh["id"], "lines": [{"product_id": p["id"], "qty": 300, "unit_price": 10}]})
    api.post(f"/purchase-orders/{po2['id']}/submit")
    mgr.post(f"/purchase-orders/{po2['id']}/reject", {"reason": "数量过多"})
    assert api.get(f"/purchase-orders/{po2['id']}")["status"] == "rejected"
    api.put(f"/purchase-orders/{po2['id']}", {"remark": "改"})
    api.post(f"/purchase-orders/{po2['id']}/submit")
    hist = api.get(f"/approval/documents/purchase_order/{po2['id']}")
    assert [h["status"] for h in hist] == ["pending", "rejected"]
    # 管理员可代审批（跳过当前级）
    api.post(f"/purchase-orders/{po2['id']}/approve")
    api.post(f"/purchase-orders/{po2['id']}/approve")
    assert api.get(f"/purchase-orders/{po2['id']}")["status"] == "approved"
    assert "代审批" in api.get(f"/approval/documents/purchase_order/{po2['id']}")[0]["records"][0]["comment"]
    assert api.get("/approval/instances?scope=all")["total"] == 3


def test_payment_and_recharge_flows(api, factory, client, approvers):
    role, u1, u2, mgr, cfo = approvers
    # 请款：开启流程后即使系统参数关闭审批也需走流程
    api.put("/system/settings", {"values": {"payment.require_approval": False, "purchase.require_approval": False}})
    api.post("/approval/flows", {"doc_type": "payment_request", "name": "请款审批", "steps": [
        {"name": "财务", "approver_type": "user", "approver_ids": [u2["id"]]}]})
    wh = factory.default_warehouse()
    s = factory.supplier(currency="CNY")
    p = factory.product(purchase_cost=10)
    po = api.post("/purchase-orders", {"supplier_id": s["id"], "warehouse_id": wh["id"], "lines": [{"product_id": p["id"], "qty": 10, "unit_price": 10}]})
    po = api.post(f"/purchase-orders/{po['id']}/submit")
    assert po["status"] == "approved"
    req = api.post("/payment-requests", {"supplier_id": s["id"], "pay_type": "full", "lines": [{"purchase_order_id": po["id"], "amount": 100}]})
    assert req["status"] == "pending"
    req = cfo.post(f"/payment-requests/{req['id']}/approve")
    assert req["status"] == "approved"

    # 分销商充值：门户提交 → 流程审批 → 到账
    api.post("/approval/flows", {"doc_type": "recharge", "name": "充值确认", "steps": [
        {"name": "出纳", "approver_type": "user", "approver_ids": [u1["id"]]},
        {"name": "财务总监", "approver_type": "user", "approver_ids": [u2["id"]]}]})
    d = api.post("/distribution/distributors", {"name": "测试分销", "currency": "CNY", "username": "dist1", "password": "dist123"})
    portal = _login(client, "dist1", "dist123")
    rc = portal.post("/portal/recharges", {"amount": 500, "transaction_no": "T1"})
    assert mgr.get("/approval/pending/count")["count"] == 1
    r = mgr.post(f"/distribution/recharges/{rc['id']}/review", {"approve": True})
    assert r["status"] == "pending" and portal.get("/portal/me")["distributor"]["balance"] == 0
    r = cfo.post(f"/distribution/recharges/{rc['id']}/review", {"approve": True})
    assert r["status"] == "approved" and portal.get("/portal/me")["distributor"]["balance"] == 500
    assert api.get(f"/distribution/distributors/{d['id']}")["balance"] == 500
