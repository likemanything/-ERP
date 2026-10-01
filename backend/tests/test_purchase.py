def _setup(api, factory):
    wh = factory.default_warehouse()
    s = factory.supplier(currency="CNY")
    p1 = factory.product(purchase_cost=10)
    p2 = factory.product(purchase_cost=20)
    return wh, s, p1, p2


def test_full_purchase_flow_with_landed_cost(api, factory):
    wh, s, p1, p2 = _setup(api, factory)
    po = api.post("/purchase-orders", {
        "supplier_id": s["id"], "warehouse_id": wh["id"], "shipping_fee": 60, "other_fee": 0, "discount": 0,
        "lines": [{"product_id": p1["id"], "qty": 100, "unit_price": 10}, {"product_id": p2["id"], "qty": 50, "unit_price": 40}],
    })
    assert po["status"] == "draft" and po["goods_amount"] == 3000 and po["total_amount"] == 3060
    po = api.post(f"/purchase-orders/{po['id']}/submit")
    assert po["status"] == "pending_approval"
    api.post(f"/purchase-orders/{po['id']}/receive", {"lines": [{"order_line_id": po["lines"][0]["id"], "qty_good": 1}]}, expect=422)
    po = api.post(f"/purchase-orders/{po['id']}/reject", {"reason": "价格太高"})
    assert po["status"] == "rejected" and po["reject_reason"] == "价格太高"
    po = api.put(f"/purchase-orders/{po['id']}", {"remark": "已议价"})
    po = api.post(f"/purchase-orders/{po['id']}/submit")
    po = api.post(f"/purchase-orders/{po['id']}/approve")
    assert po["status"] == "approved"
    po = api.post(f"/purchase-orders/{po['id']}/ordered", {"supplier_order_no": "1688-123"})
    assert po["status"] == "ordered"
    l1, l2 = po["lines"]
    # 部分到货：p1 到 60 良品 + 2 次品
    rc = api.post(f"/purchase-orders/{po['id']}/receive", {"lines": [{"order_line_id": l1["id"], "qty_good": 60, "qty_defective": 2}]})
    # 运费 60 按金额分摊：p1 金额 1000/3000 → 20 元 / 100 件 = 0.2
    assert rc["lines"][0]["unit_purchase_cost"] == 10 and rc["lines"][0]["unit_freight_cost"] == 0.2
    po = api.get(f"/purchase-orders/{po['id']}")
    assert po["status"] == "partial" and po["lines"][0]["qty_pending"] == 38
    inv = factory.inventory(wh["id"], p1["id"])
    assert inv["qty_on_hand"] == 60 and inv["qty_defective"] == 2 and inv["stock_value"] == 612
    # 超收
    api.post(f"/purchase-orders/{po['id']}/receive", {"lines": [{"order_line_id": l1["id"], "qty_good": 39}]}, expect=422)
    api.post(f"/purchase-orders/{po['id']}/receive", {"lines": [
        {"order_line_id": l1["id"], "qty_good": 38}, {"order_line_id": l2["id"], "qty_good": 50}]})
    po = api.get(f"/purchase-orders/{po['id']}")
    assert po["status"] == "received"
    # p2 运费: 2000/3000*60 = 40 / 50 = 0.8
    assert factory.inventory(wh["id"], p2["id"])["stock_value"] == 2040
    receipts = api.get(f"/purchase-receipts?order_id={po['id']}")
    assert receipts["total"] == 2

    # 退回次品给供应商
    ret = api.post("/purchase-returns", {"order_id": po["id"], "stock_type": "defective",
                                          "lines": [{"order_line_id": l1["id"], "qty": 2}]})
    assert ret["refund_amount"] == 20
    assert factory.inventory(wh["id"], p1["id"])["qty_defective"] == 0
    po = api.get(f"/purchase-orders/{po['id']}")
    assert po["returned_amount"] == 20

    # 请款 → 审批 → 付款
    payable = 3060 - 20
    api.post("/payment-requests", {"supplier_id": s["id"], "lines": [{"purchase_order_id": po["id"], "amount": payable + 1}]}, expect=422)
    req = api.post("/payment-requests", {"supplier_id": s["id"], "pay_type": "full",
                                          "lines": [{"purchase_order_id": po["id"], "amount": 1000}]})
    assert req["status"] == "pending"
    req = api.post(f"/payment-requests/{req['id']}/approve")
    req = api.post(f"/payment-requests/{req['id']}/pay", {"transaction_no": "TX001"})
    assert req["status"] == "paid"
    po = api.get(f"/purchase-orders/{po['id']}")
    assert po["paid_amount"] == 1000 and po["payment_status"] == "partial"
    req2 = api.post("/payment-requests", {"supplier_id": s["id"], "lines": [{"purchase_order_id": po["id"], "amount": payable - 1000}]})
    api.post(f"/payment-requests/{req2['id']}/approve")
    api.post(f"/payment-requests/{req2['id']}/pay", {})
    po = api.get(f"/purchase-orders/{po['id']}")
    assert po["payment_status"] == "paid"
    rows = api.get("/payables")
    assert rows[0]["unpaid_amount"] == 0


def test_plans_to_orders_and_cancel(api, factory):
    wh, s, p1, p2 = _setup(api, factory)
    s2 = factory.supplier()
    api.post(f"/products/{p1['id']}/suppliers", {"supplier_id": s["id"], "price": 9.5, "is_default": True})
    plan1 = api.post("/purchase-plans", {"product_id": p1["id"], "qty": 100})
    assert plan1["supplier_id"] == s["id"]
    plan2 = api.post("/purchase-plans", {"product_id": p1["id"], "qty": 50})
    plan3 = api.post("/purchase-plans", {"product_id": p2["id"], "qty": 20, "supplier_id": s2["id"]})
    orders = api.post("/purchase-plans/to-orders", {"plan_ids": [plan1["id"], plan2["id"], plan3["id"]]})
    assert len(orders) == 2
    o1 = next(o for o in orders if o["supplier_id"] == s["id"])
    assert o1["lines"][0]["qty"] == 150 and o1["lines"][0]["unit_price"] == 9.5
    o2 = next(o for o in orders if o["supplier_id"] == s2["id"])
    assert o2["lines"][0]["unit_price"] == 20  # 无报价取参考成本
    plans = api.get("/purchase-plans?status=converted")
    assert plans["total"] == 3 and plans["items"][0]["po_no"]
    # 作废采购单后计划退回待处理
    api.post(f"/purchase-orders/{o2['id']}/cancel")
    assert api.get("/purchase-plans?status=pending")["total"] == 1
    api.post("/purchase-plans/to-orders", {"plan_ids": [plan1["id"]]}, expect=422)


def test_no_approval_setting(api, factory):
    wh, s, p1, _ = _setup(api, factory)
    api.put("/system/settings", {"values": {"purchase.require_approval": False, "payment.require_approval": False}})
    po = api.post("/purchase-orders", {"supplier_id": s["id"], "warehouse_id": wh["id"], "lines": [{"product_id": p1["id"], "qty": 5}]})
    po = api.post(f"/purchase-orders/{po['id']}/submit")
    assert po["status"] == "approved"
    req = api.post("/payment-requests", {"supplier_id": s["id"], "lines": [{"purchase_order_id": po["id"], "amount": 10}]})
    assert req["status"] == "approved"
    api.post(f"/purchase-orders/{po['id']}/cancel", expect=422)  # 有请款记录
    api.post(f"/payment-requests/{req['id']}/cancel")
    po = api.post(f"/purchase-orders/{po['id']}/cancel")
    assert po["status"] == "cancelled"
    api.delete(f"/purchase-orders/{po['id']}", expect=422)  # 有请款历史
    po2 = api.post("/purchase-orders", {"supplier_id": s["id"], "warehouse_id": wh["id"], "lines": [{"product_id": p1["id"], "qty": 1}]})
    api.delete(f"/purchase-orders/{po2['id']}")


def test_foreign_currency_po(api, factory):
    wh = factory.default_warehouse()
    s = factory.supplier(currency="USD")
    p = factory.product(purchase_cost=71)
    po = api.post("/purchase-orders", {"supplier_id": s["id"], "warehouse_id": wh["id"],
                                        "lines": [{"product_id": p["id"], "qty": 10, "unit_price": 10}]})
    assert po["currency"] == "USD" and po["exchange_rate"] == 7.1
    po = api.post(f"/purchase-orders/{po['id']}/submit")
    po = api.post(f"/purchase-orders/{po['id']}/approve")
    api.post(f"/purchase-orders/{po['id']}/receive", {"lines": [{"order_line_id": po["lines"][0]["id"], "qty_good": 10}]})
    assert factory.inventory(wh["id"], p["id"])["stock_value"] == 710
