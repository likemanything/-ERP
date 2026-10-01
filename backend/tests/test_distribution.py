from datetime import date

from tests.conftest import Api
from tests.test_orders import _xlsx


def _login(client, username, password) -> Api:
    tokens = Api(client).post("/auth/login", {"username": username, "password": password})
    return Api(client, tokens["access_token"])


def _setup(api, factory, client, credit=0):
    wh = factory.default_warehouse()
    a = factory.product(sku="DA", purchase_cost=30, weight_kg=1)
    b = factory.product(sku="DB", purchase_cost=50, weight_kg=2)
    factory.stock_in(wh["id"], a["id"], 100, unit_cost=30)
    factory.stock_in(wh["id"], b["id"], 5, unit_cost=50)
    prov = api.post("/logistics-providers", {"code": "UPS", "name": "UPS"})
    ch = api.post("/logistics-channels", {"provider_id": prov["id"], "code": "UPS-G", "name": "UPS Ground", "usage": "last_mile",
                                          "currency": "USD", "unit_price": 2, "volume_divisor": 6000})
    level = api.post("/distribution/levels", {"code": "VIP", "name": "VIP", "discount_rate": 0.9})
    d = api.post("/distribution/distributors", {"name": "美国分销商A", "currency": "USD", "level_id": level["id"],
                                                 "credit_limit": credit, "username": "dist_a", "password": "dist123"})
    api.post("/distribution/catalog", {"items": [
        {"product_id": a["id"], "base_price": 10, "currency": "USD", "min_qty": 10},
        {"product_id": b["id"], "base_price": 20, "currency": "USD", "stock_display": "status"},
    ]})
    api.put(f"/distribution/catalog/{b['id']}/level-prices", {"prices": [{"level_id": level["id"], "price": 15}]})
    api.put("/distribution/settings", {"handling_fee_per_order": 7.1, "handling_fee_per_item": 0, "freight_markup_rate": 0.1,
                                       "auto_audit": True, "allow_cancel_after_audit": True, "warehouse_ids": [], "channel_ids": []})
    portal = _login(client, "dist_a", "dist123")
    return wh, a, b, ch, level, d, portal


ADDR = {"name": "John", "country": "US", "state": "CA", "city": "LA", "address1": "1 Main St", "postcode": "90001"}


def test_distributor_isolated_from_backoffice(api, factory, client):
    _, _, _, _, _, d, portal = _setup(api, factory, client)
    me = portal.get("/auth/me")
    assert me["user"]["user_type"] == "distributor" and me["permissions"] == []
    for url in ["/products", "/products/options", "/shops/options", "/system/settings", "/system/users/options",
                "/orders", "/distribution/distributors", "/warehouses", "/dashboard/overview"]:
        portal.get(url, expect=403)
    # 员工账号不能访问门户
    api.get("/portal/me", expect=403)
    # 后台用户列表不包含分销商账号
    assert all(u["user_type"] == "staff" for u in api.get("/system/users")["items"])
    assert d["shop_id"] and d["code"].startswith("D")


def test_catalog_pricing_and_stock(api, factory, client):
    wh, a, b, ch, level, d, portal = _setup(api, factory, client)
    me = portal.get("/portal/me")
    assert me["distributor"]["currency"] == "USD" and me["distributor"]["level_name"] == "VIP"
    rows = {r["sku"]: r for r in portal.get("/portal/catalog")["items"]}
    assert rows["DA"]["price"] == 9.0 and rows["DA"]["stock"] == 100   # 10 × 0.9
    assert rows["DB"]["price"] == 15.0 and rows["DB"]["stock"] is None and rows["DB"]["in_stock"] is True  # 等级价，仅显示有货
    assert "purchase_cost" not in rows["DA"]
    # 下架后不可见
    api.post("/distribution/catalog", {"items": [{"product_id": b["id"], "is_active": False}]})
    assert [r["sku"] for r in portal.get("/portal/catalog")["items"]] == ["DA"]


def test_order_lifecycle_with_funds(api, factory, client):
    wh, a, b, ch, level, d, portal = _setup(api, factory, client)
    q = portal.post("/portal/quote", {"order_type": "dropship", "channel_id": ch["id"], "items": [{"sku": "DA", "qty": 2}]})
    # 货款 18；运费 2kg × 2 USD × 1.1 = 4.4；操作费 7.1 CNY = 1 USD
    assert q["goods"] == 18 and q["freight"] == 4.4 and q["handling"] == 1 and q["total"] == 23.4
    assert q["sufficient"] is False
    order_body = {"order_type": "dropship", "channel_id": ch["id"], "reference_no": "AMZ-001", "address": ADDR,
                  "items": [{"sku": "DA", "qty": 2}]}
    r = client.post("/api/v1/portal/orders", json=order_body, headers=portal.headers)
    assert r.status_code == 422 and r.json()["code"] == "insufficient_funds"

    # 充值申请 → 财务确认
    req = portal.post("/portal/recharges", {"amount": 100, "payment_method": "PayPal", "transaction_no": "PP123"})
    assert req["status"] == "pending"
    api.post(f"/distribution/recharges/{req['id']}/review", {"approve": True})
    assert portal.get("/portal/me")["distributor"]["balance"] == 100

    o = portal.post("/portal/orders", order_body)
    assert o["status"] == "to_ship" and o["charge_detail"]["total"] == 23.4  # 自动审核锁库存
    assert portal.get("/portal/me")["distributor"]["balance"] == 76.6
    assert factory.inventory(wh["id"], a["id"])["qty_locked"] == 2
    portal.post("/portal/orders", order_body, expect=409)  # 防重复提交

    # 取消 → 释放库存并退款
    o = portal.post(f"/portal/orders/{o['id']}/cancel")
    assert o["status"] == "cancelled" and o["charge_detail"]["refunded"] == 23.4
    assert portal.get("/portal/me")["distributor"]["balance"] == 100
    assert factory.inventory(wh["id"], a["id"])["qty_locked"] == 0

    # 再下单 → 后台发货 → 门户可见运单号
    o2 = portal.post("/portal/orders", {**order_body, "reference_no": "AMZ-002"})
    api.post(f"/orders/{o2['id']}/ship", {"tracking_no": "1ZDIST", "carrier": "UPS", "actual_freight": 20})
    o2 = portal.get(f"/portal/orders/{o2['id']}")
    assert o2["status"] == "shipped" and o2["tracking_no"] == "1ZDIST" and o2["can_cancel"] is False
    portal.post(f"/portal/orders/{o2['id']}/cancel", expect=422)

    # 运费差额补扣
    api.post(f"/distribution/orders/{o2['id']}/charge", {"amount": 2, "remark": "超重补运费"})
    assert portal.get("/portal/me")["distributor"]["balance"] == round(100 - 23.4 - 2, 2)
    staff_view = api.get(f"/orders/{o2['id']}")
    assert staff_view["distributor_name"] == "美国分销商A" and staff_view["distribution_type"] == "dropship"
    assert staff_view["items"][0]["cost_purchase"] == 60  # FIFO 成本
    assert staff_view["shipping_amount"] == 4.4 + 1 + 2

    # 退货退款 → 退回余额
    ret = api.post("/returns", {"order_id": o2["id"], "lines": [{"order_item_id": staff_view["items"][0]["id"], "qty": 1,
                                                              "refund_amount": 9, "qty_good": 1}]})
    api.post(f"/returns/{ret['id']}/complete", {"warehouse_id": wh["id"]})
    bal = portal.get("/portal/me")["distributor"]["balance"]
    assert bal == round(100 - 23.4 - 2 + 9, 2)
    assert portal.get(f"/portal/orders/{o2['id']}")["charge_detail"]["refunded"] == 9

    # 退款不超过订单剩余扣款
    ret2 = api.post("/returns", {"order_id": o2["id"], "lines": [{"order_item_id": staff_view["items"][0]["id"], "qty": 1,
                                                               "refund_amount": 100, "qty_good": 1}]})
    api.post(f"/returns/{ret2['id']}/complete", {"warehouse_id": wh["id"]})
    bal = portal.get("/portal/me")["distributor"]["balance"]
    assert bal == round(100 - 23.4 - 2 + 9 + (25.4 - 9), 2)
    assert portal.get(f"/portal/orders/{o2['id']}")["charge_detail"]["refunded"] == 25.4

    # 流水与对账单
    txns = portal.get("/portal/transactions")["items"]
    assert [t["txn_type"] for t in txns][:4] == ["refund", "refund", "order", "order"]
    st = portal.get(f"/portal/statement?date_from={date.today()}&date_to={date.today()}")
    assert st["opening_balance"] == 0 and st["closing_balance"] == bal and st["recharge"] == 100

    # 利润报表包含分销渠道
    prof = api.get(f"/finance/profit?date_from={date.today()}&date_to={date.today()}&group_by=shop")
    assert any(r["shop_name"].startswith("分销-") for r in prof["items"])


def test_wholesale_min_qty_and_stock_shortage(api, factory, client):
    wh, a, b, ch, level, d, portal = _setup(api, factory, client)
    api.post(f"/distribution/distributors/{d['id']}/recharge", {"amount": 1000})
    portal.post("/portal/quote", {"order_type": "wholesale", "items": [{"sku": "DA", "qty": 5}]}, expect=422)  # 起订量 10
    # B 库存只有 5：下单成功但待人工审核
    o = portal.post("/portal/orders", {"order_type": "wholesale", "items": [{"sku": "DB", "qty": 8}], "address": ADDR})
    assert o["status"] == "to_audit" and o["note"] == "等待仓库人工审核"
    assert o["charge_detail"]["handling"] == 0  # 批发不收代发操作费


def test_credit_limit_and_disable(api, factory, client):
    wh, a, b, ch, level, d, portal = _setup(api, factory, client, credit=50)
    o = portal.post("/portal/orders", {"order_type": "dropship", "channel_id": ch["id"], "address": ADDR,
                                        "items": [{"sku": "DA", "qty": 2}]})
    assert o["status"] == "to_ship"
    assert portal.get("/portal/me")["distributor"]["balance"] == -23.4  # 使用授信
    api.put(f"/distribution/distributors/{d['id']}", {"status": "disabled"})
    portal.get("/portal/me", expect=401)  # 停用后 token 失效


def test_api_key_and_isolation(api, factory, client):
    wh, a, b, ch, level, d, portal = _setup(api, factory, client)
    api.post(f"/distribution/distributors/{d['id']}/recharge", {"amount": 500})
    key = portal.post("/portal/api-key")["api_key"]
    assert key.startswith("dk_")
    r = client.get("/api/v1/portal/catalog", headers={"X-Api-Key": key})
    assert r.status_code == 200 and r.json()["total"] == 2
    assert client.get("/api/v1/portal/catalog", headers={"X-Api-Key": "dk_wrong"}).status_code == 401
    r = client.post("/api/v1/portal/orders", headers={"X-Api-Key": key}, json={
        "order_type": "dropship", "channel_id": ch["id"], "address": ADDR, "items": [{"sku": "DA", "qty": 1}]})
    assert r.status_code == 200
    oid = r.json()["id"]
    # 另一个分销商看不到
    d2 = api.post("/distribution/distributors", {"name": "分销商B", "currency": "USD", "username": "dist_b", "password": "dist123"})
    portal_b = _login(client, "dist_b", "dist123")
    portal_b.get(f"/portal/orders/{oid}", expect=422)
    assert portal_b.get("/portal/orders")["total"] == 0
    assert d2["user_count"] == 1
    # 后台分销订单视图
    rows = api.get("/orders?distribution_only=true")["items"]
    assert len(rows) == 1 and rows[0]["distributor_name"] == "美国分销商A"


def test_portal_excel_import(api, factory, client):
    wh, a, b, ch, level, d, portal = _setup(api, factory, client)
    api.post(f"/distribution/distributors/{d['id']}/recharge", {"amount": 500})
    headers = ["订单号", "类型", "SKU", "数量", "物流渠道", "收件人", "国家", "地址1"]
    rows = [["X1", "一件代发", "DA", 1, "UPS Ground", "Tom", "US", "1 A St"],
            ["X1", "一件代发", "DB", 1, "UPS Ground", "Tom", "US", "1 A St"],
            ["X2", "dropship", "NOPE", 1, "UPS Ground", "Ann", "US", "2 B St"]]
    res = portal.post("/portal/orders/import", files={"file": ("o.xlsx", _xlsx(headers, rows), "application/octet-stream")})
    assert res["created"] == 1 and res["skipped"] == 1 and "NOPE" in res["errors"][0]
    o = portal.get("/portal/orders")["items"][0]
    assert o["reference_no"] == "X1" and len(o["items"]) == 2
