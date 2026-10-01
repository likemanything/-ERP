def test_fifo_costing(api, factory):
    wh = factory.default_warehouse()
    p = factory.product(purchase_cost=10)
    factory.stock_in(wh["id"], p["id"], 10, unit_cost=10)
    factory.stock_in(wh["id"], p["id"], 10, unit_cost=12)
    inv = factory.inventory(wh["id"], p["id"])
    assert inv["qty_on_hand"] == 20 and inv["stock_value"] == 220
    # 出库 15：10*10 + 5*12 = 160
    doc = api.post("/stock-documents", {"doc_type": "out", "warehouse_id": wh["id"], "lines": [{"product_id": p["id"], "qty": 15}]})
    doc = api.post(f"/stock-documents/{doc['id']}/approve")
    assert doc["status"] == "completed"
    assert abs(doc["lines"][0]["unit_cost"] - 160 / 15) < 0.001
    inv = factory.inventory(wh["id"], p["id"])
    assert inv["qty_on_hand"] == 5 and inv["stock_value"] == 60
    # 库存不足
    doc = api.post("/stock-documents", {"doc_type": "out", "warehouse_id": wh["id"], "lines": [{"product_id": p["id"], "qty": 6}]})
    api.post(f"/stock-documents/{doc['id']}/approve", expect=422)
    ledger = api.get(f"/inventory/ledger?product_id={p['id']}")
    assert ledger["total"] == 4  # 2 入 + 2 个批次出
    batches = api.get(f"/inventory/batches?product_id={p['id']}")["items"]
    assert len(batches) == 1 and batches[0]["qty_remaining"] == 5


def test_transfer_with_freight(api, factory):
    src = factory.default_warehouse()
    dst = factory.warehouse(name="美国海外仓", warehouse_type="overseas")
    p = factory.product()
    factory.stock_in(src["id"], p["id"], 100, unit_cost=10)
    doc = api.post("/stock-documents", {"doc_type": "transfer", "warehouse_id": src["id"], "to_warehouse_id": dst["id"],
                                         "freight_cost": 200, "lines": [{"product_id": p["id"], "qty": 40}]})
    doc = api.post(f"/stock-documents/{doc['id']}/approve")
    assert doc["status"] == "in_transit"
    assert factory.inventory(dst["id"], p["id"])["qty_in_transit"] == 40
    assert factory.inventory(src["id"], p["id"])["qty_on_hand"] == 60
    doc = api.post(f"/stock-documents/{doc['id']}/receive", {"lines": [{"line_id": doc["lines"][0]["id"], "qty_received": 40}]})
    assert doc["status"] == "completed"
    d = factory.inventory(dst["id"], p["id"])
    assert d["qty_on_hand"] == 40 and d["qty_in_transit"] == 0
    # 成本 = 10 采购 + 200/40=5 运费
    assert d["stock_value"] == 600
    batches = api.get(f"/inventory/batches?warehouse_id={dst['id']}")["items"]
    assert batches[0]["unit_purchase_cost"] == 10 and batches[0]["unit_freight_cost"] == 5


def test_stocktake(api, factory):
    wh = factory.default_warehouse()
    p1 = factory.product()
    p2 = factory.product()
    factory.stock_in(wh["id"], p1["id"], 10, unit_cost=10)
    factory.stock_in(wh["id"], p2["id"], 10, unit_cost=20)
    doc = api.post("/stock-documents", {"doc_type": "stocktake", "warehouse_id": wh["id"], "fill_all": True})
    assert {ln["system_qty"] for ln in doc["lines"]} == {10}
    lines = [{"product_id": p1["id"], "counted_qty": 12}, {"product_id": p2["id"], "counted_qty": 7}]
    doc = api.put(f"/stock-documents/{doc['id']}", {"lines": lines})
    doc = api.post(f"/stock-documents/{doc['id']}/approve")
    diffs = {ln["product_id"]: ln["qty"] for ln in doc["lines"]}
    assert diffs == {p1["id"]: 2, p2["id"]: -3}
    assert factory.inventory(wh["id"], p1["id"])["qty_on_hand"] == 12
    assert factory.inventory(wh["id"], p2["id"])["qty_on_hand"] == 7
    # 盘盈按结存均价入库
    assert factory.inventory(wh["id"], p1["id"])["stock_value"] == 120


def test_defective_stock_and_cancel(api, factory):
    wh = factory.default_warehouse()
    p = factory.product()
    doc = api.post("/stock-documents", {"doc_type": "in", "warehouse_id": wh["id"], "stock_type": "defective",
                                         "lines": [{"product_id": p["id"], "qty": 3}]})
    api.post(f"/stock-documents/{doc['id']}/approve")
    inv = factory.inventory(wh["id"], p["id"])
    assert inv["qty_defective"] == 3 and inv["qty_on_hand"] == 0
    doc = api.post("/stock-documents", {"doc_type": "in", "warehouse_id": wh["id"], "lines": [{"product_id": p["id"], "qty": 3}]})
    api.post(f"/stock-documents/{doc['id']}/cancel")
    api.post(f"/stock-documents/{doc['id']}/approve", expect=422)
    summary = api.get("/inventory/summary")["items"]
    assert summary[0]["defective"] == 3


def test_bundle_cannot_hold_stock(api, factory):
    wh = factory.default_warehouse()
    a = factory.product()
    kit = api.post("/products", {"sku": "KIT", "name": "kit", "product_type": "bundle",
                                 "bundle_items": [{"component_id": a["id"], "quantity": 2}]})
    api.post("/stock-documents", {"doc_type": "in", "warehouse_id": wh["id"], "lines": [{"product_id": kit["id"], "qty": 1}]}, expect=422)
