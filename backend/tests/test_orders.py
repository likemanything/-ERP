import io

from openpyxl import Workbook


def _xlsx(headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _setup(api, factory, stock=10, cost=10):
    wh = factory.default_warehouse()
    shop = factory.shop(name="US店")
    p = factory.product(sku="SKU-A", purchase_cost=cost, weight_kg=0.5)
    lst = factory.listing(shop["id"], p["id"], msku="MSKU-A", fulfillment="FBM")
    if stock:
        factory.stock_in(wh["id"], p["id"], stock, unit_cost=cost)
    return wh, shop, p, lst


def test_fbm_order_flow(api, factory):
    wh, shop, p, lst = _setup(api, factory)
    order = api.post("/orders", {"shop_id": shop["id"], "items": [{"msku": "MSKU-A", "quantity": 3, "unit_price": 20}],
                                 "ship_name": "John", "ship_country": "US"})
    assert order["status"] == "to_audit" and order["total_amount"] == 60
    assert order["items"][0]["sku"] == "SKU-A"
    assert order["items"][0]["commission_fee"] == 9  # 预估 15%
    res = api.post("/orders/audit", {"order_ids": [order["id"]], "warehouse_id": wh["id"]})
    assert res["success"] == [order["id"]]
    inv = factory.inventory(wh["id"], p["id"])
    assert inv["qty_locked"] == 3 and inv["qty_available"] == 7
    order = api.post(f"/orders/{order['id']}/ship", {"tracking_no": "1Z999", "carrier": "UPS", "actual_freight": 30})
    assert order["status"] == "shipped" and order["tracking_no"] == "1Z999"
    item = order["items"][0]
    assert item["cost_purchase"] == 30 and item["cost_settled"] is True
    inv = factory.inventory(wh["id"], p["id"])
    assert inv["qty_on_hand"] == 7 and inv["qty_locked"] == 0
    # 预估利润 = (60 - 9) * 7.1 - 30 成本 - 30 运费
    assert abs(order["est_profit"] - (51 * 7.1 - 60)) < 0.01
    counts = api.get("/orders/status-counts")
    assert counts["shipped"] == 1


def test_audit_failures_and_cancel(api, factory):
    wh, shop, p, lst = _setup(api, factory, stock=2)
    o1 = api.post("/orders", {"shop_id": shop["id"], "items": [{"msku": "MSKU-A", "quantity": 5, "unit_price": 10}]})
    o2 = api.post("/orders", {"shop_id": shop["id"], "items": [{"msku": "UNPAIRED", "quantity": 1, "unit_price": 10}]})
    o3 = api.post("/orders", {"shop_id": shop["id"], "items": [{"msku": "MSKU-A", "quantity": 2, "unit_price": 10}]})
    assert o2["has_unpaired"] is True
    res = api.post("/orders/audit", {"order_ids": [o1["id"], o2["id"], o3["id"]], "warehouse_id": wh["id"]})
    assert res["success"] == [o3["id"]]
    msgs = {f["order_id"]: f["message"] for f in res["failed"]}
    assert "库存不足" in msgs[o1["id"]] and "未配对" in msgs[o2["id"]]
    assert factory.inventory(wh["id"], p["id"])["qty_locked"] == 2
    api.post("/orders/cancel", {"order_ids": [o3["id"]], "reason": "买家取消"})
    assert factory.inventory(wh["id"], p["id"])["qty_locked"] == 0
    # 反审核
    api.post("/orders/hold", {"order_ids": [o1["id"]], "hold": True, "reason": "地址待确认"})
    res = api.post("/orders/audit", {"order_ids": [o1["id"]]})
    assert "挂起" in res["failed"][0]["message"]


def test_bundle_order(api, factory):
    wh = factory.default_warehouse()
    shop = factory.shop()
    a = factory.product(sku="A", purchase_cost=5)
    b = factory.product(sku="B", purchase_cost=3)
    kit = api.post("/products", {"sku": "KIT", "name": "套装", "product_type": "bundle",
                                 "bundle_items": [{"component_id": a["id"], "quantity": 2}, {"component_id": b["id"], "quantity": 1}]})
    factory.listing(shop["id"], kit["id"], msku="KIT-MSKU", fulfillment="FBM")
    factory.stock_in(wh["id"], a["id"], 10, unit_cost=5)
    factory.stock_in(wh["id"], b["id"], 10, unit_cost=3)
    o = api.post("/orders", {"shop_id": shop["id"], "items": [{"msku": "KIT-MSKU", "quantity": 2, "unit_price": 30}]})
    api.post("/orders/audit", {"order_ids": [o["id"]], "warehouse_id": wh["id"]})
    o = api.post(f"/orders/{o['id']}/ship", {})
    assert o["items"][0]["cost_purchase"] == 2 * (2 * 5 + 3)
    assert factory.inventory(wh["id"], a["id"])["qty_on_hand"] == 6
    assert factory.inventory(wh["id"], b["id"])["qty_on_hand"] == 8


def test_import_fba_orders_and_cost(api, factory):
    shop = factory.shop(name="FBA店")
    p = factory.product(sku="FBA-SKU", purchase_cost=12)
    factory.listing(shop["id"], p["id"], msku="FBA-MSKU", fulfillment="FBA")
    headers = ["店铺", "订单号", "下单时间", "MSKU", "数量", "单价", "币种", "配送方式", "状态"]
    rows = [
        ["FBA店", "111-1", "2026-09-01 10:00:00", "FBA-MSKU", 2, 25, "USD", "FBA", "shipped"],
        ["FBA店", "111-2", "2026-09-01 11:00:00", "FBA-MSKU", 1, 25, "USD", "FBA", "pending"],
        ["FBA店", "111-2", "2026-09-01 11:00:00", "OTHER", 1, 5, "USD", "FBA", "pending"],
        ["不存在的店", "111-3", "2026-09-01 11:00:00", "X", 1, 5, "USD", "FBA", "shipped"],
    ]
    res = api.post("/orders/import", files={"file": ("o.xlsx", _xlsx(headers, rows), "application/octet-stream")})
    assert res["created"] == 2 and res["skipped"] == 1
    orders = {o["platform_order_id"]: o for o in api.get("/orders")["items"]}
    o1 = orders["111-1"]
    assert o1["status"] == "shipped" and o1["fulfillment"] == "FBA"
    assert o1["items"][0]["cost_purchase"] == 24  # FBA 仓无批次 → 参考成本
    assert orders["111-2"]["status"] == "pending" and len(orders["111-2"]["items"]) == 2
    # 再次导入同一订单为更新（幂等）
    res = api.post("/orders/import", files={"file": ("o.xlsx", _xlsx(headers, rows[:1]), "application/octet-stream")})
    assert res["updated"] == 1
    assert api.get("/orders")["total"] == 2
    # FBA 虚拟仓出现负库存（以平台为准）
    fba_wh = api.get("/warehouses?warehouse_type=fba")["items"][0]
    assert factory.inventory(fba_wh["id"], p["id"])["qty_on_hand"] == -2


def test_return_restock(api, factory):
    wh, shop, p, lst = _setup(api, factory, stock=10, cost=10)
    o = api.post("/orders", {"shop_id": shop["id"], "items": [{"msku": "MSKU-A", "quantity": 2, "unit_price": 20}]})
    api.post("/orders/audit", {"order_ids": [o["id"]], "warehouse_id": wh["id"]})
    o = api.post(f"/orders/{o['id']}/ship", {})
    ret = api.post("/returns", {"order_id": o["id"], "reason": "不喜欢", "lines": [
        {"order_item_id": o["items"][0]["id"], "qty": 2, "refund_amount": 40, "qty_good": 1, "qty_defective": 1}]})
    assert ret["status"] == "pending" and ret["refund_amount"] == 40
    ret = api.post(f"/returns/{ret['id']}/complete", {"warehouse_id": wh["id"]})
    assert ret["status"] == "completed" and ret["restock_cost"] == 10
    inv = factory.inventory(wh["id"], p["id"])
    assert inv["qty_on_hand"] == 9 and inv["qty_defective"] == 1
    o = api.get(f"/orders/{o['id']}")
    assert o["items"][0]["refund_qty"] == 2 and o["items"][0]["refund_amount"] == 40
    api.post("/returns", {"order_id": o["id"], "lines": [{"order_item_id": o["items"][0]["id"], "qty": 1}]}, expect=422)


def test_auto_audit(api, factory):
    wh, shop, p, lst = _setup(api, factory, stock=5)
    api.put("/system/settings", {"values": {"order.auto_audit": True}})
    o = api.post("/orders", {"shop_id": shop["id"], "items": [{"msku": "MSKU-A", "quantity": 2, "unit_price": 10}]})
    assert o["status"] == "to_ship" and o["warehouse_id"] == wh["id"]
    o2 = api.post("/orders", {"shop_id": shop["id"], "items": [{"msku": "MSKU-A", "quantity": 9, "unit_price": 10}]})
    assert o2["status"] == "to_audit" and "自动审核失败" in o2["tags"]


def test_platform_shipped_unpaired_fbm_order_settles_after_pairing(api, factory):
    wh = factory.default_warehouse()
    shop = factory.shop(name="FBM店")
    p = factory.product(sku="LATE", purchase_cost=8)
    factory.stock_in(wh["id"], p["id"], 10, unit_cost=8)
    headers = ["店铺", "订单号", "下单时间", "MSKU", "数量", "单价", "币种", "配送方式", "状态"]
    rows = [["FBM店", "F-1", "2026-09-01 10:00:00", "NEW-MSKU", 2, 15, "USD", "FBM", "shipped"]]
    res = api.post("/orders/import", files={"file": ("o.xlsx", _xlsx(headers, rows), "application/octet-stream")})
    assert res["created"] == 1, res
    o = api.get("/orders")["items"][0]
    assert o["status"] == "shipped" and "平台发货-待核算成本" in o["tags"]
    assert o["items"][0]["cost_settled"] is False
    lst = factory.listing(shop["id"], p["id"], msku="NEW-MSKU", fulfillment="FBM")
    assert lst["sku"] == "LATE"
    api.post("/orders/resettle-cost")
    o = api.get(f"/orders/{o['id']}")
    assert o["items"][0]["cost_settled"] is True and o["items"][0]["cost_purchase"] == 16
    assert not o["tags"]
    assert factory.inventory(wh["id"], p["id"])["qty_on_hand"] == 8


def test_sku_snapshot_after_pairing_in_same_session(api, factory):
    """回归：同一会话内先配对再写订单，订单行 SKU 快照不能为空。"""
    from app.core.db import SessionLocal
    from app.core.deps import system_ctx
    from app.integrations.dto import OrderDTO, OrderItemDTO
    from app.modules.order.service import upsert_order
    from app.modules.product.models import Listing
    from app.modules.product.service import pair_listing
    from app.modules.shop.models import Shop

    shop = factory.shop(name="会话店")
    p = factory.product(sku="SNAP-SKU")
    lst = factory.listing(shop["id"], None, msku="SNAP-M", fulfillment="FBM")
    with SessionLocal() as db:
        tenant_id = db.execute(__import__("sqlalchemy").text("select tenant_id from shops where id=:i"), {"i": shop["id"]}).scalar()
        ctx = system_ctx(db, tenant_id)
        listing = db.get(Listing, lst["id"])
        assert listing.product is None  # 关系已加载为 None
        pair_listing(ctx, listing, p["id"])
        db.commit()
        order, _ = upsert_order(ctx, db.get(Shop, shop["id"]), OrderDTO(
            platform_order_id="SNAP-1", purchase_at="2026-09-01T00:00:00Z",
            items=[OrderItemDTO(msku="SNAP-M", quantity=1, item_amount=10)]))
        db.commit()
        assert order.items[0].product_id == p["id"] and order.items[0].sku == "SNAP-SKU"
