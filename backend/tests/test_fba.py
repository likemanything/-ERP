import io

from openpyxl import Workbook


def _setup(api, factory):
    wh = factory.default_warehouse()
    shop = factory.shop(name="US店")
    fba_wh = api.get(f"/warehouses?warehouse_type=fba&shop_id={shop['id']}")["items"][0]
    a = factory.product(sku="A", purchase_cost=10, weight_kg=1, length_cm=10, width_cm=10, height_cm=10)
    b = factory.product(sku="B", purchase_cost=20, weight_kg=3, length_cm=10, width_cm=10, height_cm=10)
    la = factory.listing(shop["id"], a["id"], msku="MSKU-A", fnsku="X00A")
    lb = factory.listing(shop["id"], b["id"], msku="MSKU-B", fnsku="X00B")
    factory.stock_in(wh["id"], a["id"], 100, unit_cost=10)
    factory.stock_in(wh["id"], b["id"], 100, unit_cost=20)
    return wh, shop, fba_wh, a, b, la, lb


def test_shipment_flow_with_weight_allocation(api, factory):
    wh, shop, fba_wh, a, b, la, lb = _setup(api, factory)
    plan = api.post("/shipment-plans", {"shop_id": shop["id"], "ship_from_warehouse_id": wh["id"],
                                        "lines": [{"listing_id": la["id"], "qty": 10}, {"listing_id": lb["id"], "qty": 10}]})
    assert plan["total_qty"] == 20 and plan["lines"][0]["stock_available"] == 100
    s = api.post(f"/shipment-plans/{plan['id']}/to-shipment")
    assert s["status"] == "draft" and s["to_warehouse_id"] == fba_wh["id"]
    assert s["total_weight_kg"] == 40
    s = api.put(f"/fba-shipments/{s['id']}", {"platform_shipment_id": "FBA15ABC", "freight_cost": 400, "cost_currency": "CNY",
                                               "allocation_method": "weight"})
    s = api.post(f"/fba-shipments/{s['id']}/ship")
    assert s["status"] == "shipped"
    lines = {ln["msku"]: ln for ln in s["lines"]}
    # 按重量：A 10kg / B 30kg → 100 / 300
    assert lines["MSKU-A"]["allocated_cost"] == 100 and lines["MSKU-B"]["allocated_cost"] == 300
    assert lines["MSKU-A"]["allocated_unit_cost"] == 10
    assert factory.inventory(wh["id"], a["id"])["qty_on_hand"] == 90
    assert factory.inventory(fba_wh["id"], a["id"])["qty_in_transit"] == 10
    # 部分签收
    s = api.post(f"/fba-shipments/{s['id']}/receive", {"lines": [{"line_id": lines["MSKU-A"]["id"], "qty_received": 8}]})
    assert s["status"] == "receiving"
    inv_a = factory.inventory(fba_wh["id"], a["id"])
    assert inv_a["qty_on_hand"] == 8 and inv_a["qty_in_transit"] == 2
    assert inv_a["stock_value"] == 8 * (10 + 10)  # 采购 10 + 头程 10
    # 剩余全部签收并完结
    s = api.post(f"/fba-shipments/{s['id']}/receive", {"close": True})
    assert s["status"] == "closed"
    assert factory.inventory(fba_wh["id"], b["id"])["stock_value"] == 10 * (20 + 30)

    # 头程账单后补：运费改为 800 → 剩余批次成本更新
    s = api.post(f"/fba-shipments/{s['id']}/costs", {"freight_cost": 800})
    assert factory.inventory(fba_wh["id"], a["id"])["stock_value"] == 10 * (10 + 20)

    # FBA 订单消耗落地成本
    from tests.test_orders import _xlsx
    headers = ["店铺", "订单号", "下单时间", "MSKU", "数量", "单价", "币种", "配送方式", "状态"]
    rows = [["US店", "113-1", "2026-09-10 10:00:00", "MSKU-A", 3, 30, "USD", "FBA", "shipped"]]
    api.post("/orders/import", files={"file": ("o.xlsx", _xlsx(headers, rows), "application/octet-stream")})
    o = api.get("/orders")["items"][0]
    assert o["items"][0]["cost_purchase"] == 30 and o["items"][0]["cost_freight"] == 60
    assert factory.inventory(fba_wh["id"], a["id"])["qty_on_hand"] == 7


def test_shipment_cancel_and_validation(api, factory):
    wh, shop, fba_wh, a, b, la, lb = _setup(api, factory)
    s = api.post("/fba-shipments", {"shop_id": shop["id"], "ship_from_warehouse_id": wh["id"],
                                     "lines": [{"listing_id": la["id"], "qty": 1000}]})
    api.post(f"/fba-shipments/{s['id']}/ship", expect=422)  # 库存不足
    s = api.post(f"/fba-shipments/{s['id']}/cancel")
    assert s["status"] == "cancelled"
    api.post("/fba-shipments", {"shop_id": shop["id"], "ship_from_warehouse_id": fba_wh["id"],
                                "lines": [{"listing_id": la["id"], "qty": 1}]}, expect=422)


def test_quantity_allocation_with_boxes(api, factory):
    wh, shop, fba_wh, a, b, la, lb = _setup(api, factory)
    s = api.post("/fba-shipments", {
        "shop_id": shop["id"], "ship_from_warehouse_id": wh["id"], "allocation_method": "quantity",
        "freight_cost": 100, "cost_currency": "USD",
        "boxes": [{"box_no": "1", "weight_kg": 12.5, "length_cm": 50, "width_cm": 40, "height_cm": 30,
                   "items": [{"msku": "MSKU-A", "qty": 5}, {"msku": "MSKU-B", "qty": 5}]}],
        "lines": [{"listing_id": la["id"], "qty": 5}, {"listing_id": lb["id"], "qty": 5}],
    })
    assert s["box_count"] == 1 and s["total_weight_kg"] == 12.5 and s["total_volume_cbm"] == 0.06
    assert s["chargeable_weight_kg"] == 12.5
    s = api.post(f"/fba-shipments/{s['id']}/ship")
    # 100 USD * 7.1 = 710 按数量平分
    assert {ln["allocated_cost"] for ln in s["lines"]} == {355}


def test_fba_inventory_import(api, factory):
    wh, shop, fba_wh, a, b, la, lb = _setup(api, factory)
    wb = Workbook()
    ws = wb.active
    ws.append(["店铺", "MSKU", "FNSKU", "可售", "在途", "预留"])
    ws.append(["US店", "MSKU-A", "X00A", 120, 30, 5])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    res = api.post("/fba-inventory/import", files={"file": ("f.xlsx", buf, "application/octet-stream")})
    assert res["updated"] == 1
    rows = api.get("/fba-inventory")["items"]
    assert rows[0]["fulfillable"] == 120 and rows[0]["inbound_total"] == 30 and rows[0]["sku"] == "A"
