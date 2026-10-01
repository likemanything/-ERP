from tests.test_orders import _xlsx


def _orders(api, factory, n=3):
    wh = factory.default_warehouse()
    shop = factory.shop(name="US店")
    a = factory.product(sku="PICK-A", barcode="0012345678905")
    b = factory.product(sku="PICK-B")
    la = factory.listing(shop["id"], a["id"], msku="M-A", fnsku="X00PICKA01", fulfillment="FBM")
    factory.listing(shop["id"], b["id"], msku="M-B", fulfillment="FBM")
    factory.stock_in(wh["id"], a["id"], 50, unit_cost=10)
    factory.stock_in(wh["id"], b["id"], 50, unit_cost=5)
    bal = factory.inventory(wh["id"], a["id"])
    api.put(f"/inventory/{bal['id']}", {"bin_code": "A-01-02"})
    ids = []
    for i in range(n):
        o = api.post("/orders", {"shop_id": shop["id"], "ship_name": f"Buyer {i}", "ship_country": "US",
                                 "ship_address1": "1 Main St", "items": [{"msku": "M-A", "quantity": 2, "unit_price": 20},
                                                                         {"msku": "M-B", "quantity": 1, "unit_price": 9}]})
        ids.append(o["id"])
    api.post("/orders/audit", {"order_ids": ids, "warehouse_id": wh["id"]})
    return wh, shop, a, b, la, ids


def test_pick_wave_flow(api, factory):
    wh, shop, a, b, la, ids = _orders(api, factory)
    res = api.post("/fulfillment/waves", {"order_ids": ids})
    assert len(res["waves"]) == 1
    wave = res["waves"][0]
    assert wave["order_count"] == 3 and wave["sku_count"] == 2 and wave["unit_count"] == 9
    # 已在进行中的波次内，不能重复生成
    api.post("/fulfillment/waves", {"order_ids": ids}, expect=422)

    detail = api.get(f"/fulfillment/waves/{wave['id']}")
    assert [ln["sku"] for ln in detail["lines"]] == ["PICK-A", "PICK-B"]  # 有库位的排前面
    assert detail["lines"][0]["bin_code"] == "A-01-02" and detail["lines"][0]["qty"] == 6
    assert len(detail["lines"][0]["orders"]) == 3

    pdf = api.get(f"/fulfillment/waves/{wave['id']}/pick-list.pdf")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    slips = api.get(f"/fulfillment/waves/{wave['id']}/packing-slips.pdf?size=100x150")
    assert slips.content.startswith(b"%PDF")
    assert api.get("/fulfillment/waves")["items"][0]["print_count"] == 1

    # 移出一单 → 统计更新；拣货完成
    w = api.post(f"/fulfillment/waves/{wave['id']}/remove-orders", {"order_ids": [ids[2]]})
    assert w["order_count"] == 2 and w["unit_count"] == 6
    w = api.post(f"/fulfillment/waves/{wave['id']}/picked", {})
    assert w["status"] == "picked"
    api.post(f"/fulfillment/waves/{wave['id']}/complete", expect=422)  # 还有未发货订单

    # 扫码验货：系统单号 / 平台单号均可；条码包含 SKU、商品条码、FNSKU、MSKU
    order = api.get(f"/orders/{ids[0]}")
    scan = api.get(f"/fulfillment/scan?code={order['order_no']}")
    line_a = next(x for x in scan["lines"] if x["sku"] == "PICK-A")
    assert set(line_a["codes"]) >= {"PICK-A", "0012345678905", "X00PICKA01", "M-A"} and line_a["qty"] == 2
    assert scan["wave_no"] == wave["wave_no"]
    shipped = api.post("/fulfillment/scan-ship", {"order_id": ids[0], "tracking_no": "TRK-1", "carrier": "USPS"})
    assert shipped["status"] == "shipped" and shipped["tracking_no"] == "TRK-1"
    api.post("/fulfillment/scan-ship", {"order_id": ids[0]}, expect=422)  # 不能重复发货

    # 批量导入运单号：最后一单发货后波次自动完成
    second = api.get(f"/orders/{ids[1]}")
    file = _xlsx(["订单号（系统单号或平台单号）", "物流商", "运单号", "实际运费（本位币）", "是否发货(Y/N)"],
                 [[second["platform_order_id"], "UPS", "1ZTRK2", 12.5, "Y"], ["NOT-EXIST", "UPS", "X", None, None],
                  [order["order_no"], "USPS", "TRK-1B", None, None]])
    r = api.post("/fulfillment/tracking-import", files={"file": ("t.xlsx", file)}, data={"ship": "true"})
    assert r["created"] == 1 and r["updated"] == 1 and r["skipped"] == 1, r
    assert api.get(f"/orders/{ids[1]}")["tracking_no"] == "1ZTRK2"
    assert api.get(f"/orders/{ids[0]}")["tracking_no"] == "TRK-1B"
    assert api.get(f"/fulfillment/waves/{wave['id']}")["status"] == "completed"

    # 被移出的订单可以进入新波次，取消波次后订单退回
    w2 = api.post("/fulfillment/waves", {"warehouse_id": wh["id"]})["waves"][0]
    assert w2["order_count"] == 1
    api.post(f"/fulfillment/waves/{w2['id']}/cancel")
    assert api.post("/fulfillment/waves", {"order_ids": [ids[2]]})["waves"][0]["order_count"] == 1


def test_labels_and_carton(api, factory):
    wh, shop, a, b, la, ids = _orders(api, factory, n=1)
    sizes = api.get("/print/label-sizes")
    assert any(s["value"] == "a4_30" and s["per_page"] == 30 for s in sizes)
    pdf = api.post("/print/labels.pdf", {"kind": "fnsku", "size": "a4_30", "skip": 3, "extra": "Made in China",
                                         "items": [{"listing_id": la["id"], "qty": 40}]})
    assert pdf.content.startswith(b"%PDF")
    pdf = api.post("/print/labels.pdf", {"kind": "barcode", "size": "60x30", "items": [{"product_id": a["id"], "qty": 2}]})
    assert pdf.content.startswith(b"%PDF")
    # 未维护商品条码 / 规格不存在
    r = api.post("/print/labels.pdf", {"kind": "barcode", "items": [{"product_id": b["id"], "qty": 1}]}, expect=422)
    assert "条码" in r["message"]
    api.post("/print/labels.pdf", {"kind": "sku", "size": "9x9", "items": [{"product_id": b["id"], "qty": 1}]}, expect=422)

    fba = next(w for w in api.get("/warehouses?warehouse_type=fba")["items"] if w["shop_id"] == shop["id"])
    shipment = api.post("/fba-shipments", {
        "shop_id": shop["id"], "ship_from_warehouse_id": wh["id"], "to_warehouse_id": fba["id"],
        "platform_shipment_id": "FBA15TEST01", "destination_fc": "ONT8",
        "boxes": [{"box_no": "1", "weight_kg": 10, "length_cm": 50, "width_cm": 40, "height_cm": 30,
                   "items": [{"msku": "M-A", "qty": 5}]},
                  {"box_no": "B2", "weight_kg": 9, "items": [{"msku": "M-A", "qty": 5}]}],
        "lines": [{"listing_id": la["id"], "qty": 10}],
    })
    r = api.get(f"/print/fba-shipments/{shipment['id']}/carton-labels.pdf")
    assert r.content.startswith(b"%PDF")
    r = api.get(f"/print/fba-shipments/{shipment['id']}/fnsku-labels.pdf?size=50x25")
    assert r.content.startswith(b"%PDF")
    r = api.post("/fulfillment/packing-slips.pdf", {"order_ids": ids})
    assert r.content.startswith(b"%PDF")
