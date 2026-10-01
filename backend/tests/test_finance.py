from datetime import date, timedelta

from tests.test_orders import _xlsx

ORDER_HEADERS = ["店铺", "订单号", "下单时间", "MSKU", "数量", "单价", "币种", "配送方式", "状态"]


def _seed(api, factory):
    wh = factory.default_warehouse()
    shop = factory.shop(name="US店")
    p = factory.product(sku="P1", purchase_cost=10, weight_kg=1, length_cm=10, width_cm=10, height_cm=10)
    lst = factory.listing(shop["id"], p["id"], msku="M1")
    factory.stock_in(wh["id"], p["id"], 100, unit_cost=10)
    s = api.post("/fba-shipments", {"shop_id": shop["id"], "ship_from_warehouse_id": wh["id"], "freight_cost": 100,
                                     "lines": [{"listing_id": lst["id"], "qty": 50}]})
    api.post(f"/fba-shipments/{s['id']}/ship")
    api.post(f"/fba-shipments/{s['id']}/receive", {})
    day = date.today() - timedelta(days=1)
    rows = [["US店", "A-1", f"{day} 10:00:00", "M1", 2, 25, "USD", "FBA", "shipped"],
            ["US店", "A-2", f"{day} 11:00:00", "M1", 1, 25, "USD", "FBA", "shipped"],
            ["US店", "A-3", f"{day} 12:00:00", "M1", 5, 25, "USD", "FBA", "cancelled"]]
    api.post("/orders/import", files={"file": ("o.xlsx", _xlsx(ORDER_HEADERS, rows), "application/octet-stream")})
    return shop, p, lst, day


def test_profit_report(api, factory):
    shop, p, lst, day = _seed(api, factory)
    # 结算：A-1 实际佣金 7.5 + FBA 费 8
    tx_headers = ["交易ID", "日期", "交易类型", "费用类型", "订单号", "MSKU", "金额", "币种"]
    tx = [["t1", f"{day} 12:00:00", "order", "Principal", "A-1", "M1", 50, "USD"],
          ["t2", f"{day} 12:00:00", "order", "Commission", "A-1", "M1", -7.5, "USD"],
          ["t3", f"{day} 12:00:00", "order", "FBAPerUnitFulfillmentFee", "A-1", "M1", -8, "USD"],
          ["t4", f"{day} 12:00:00", "service_fee", "StorageFee", None, None, -10, "USD"]]
    res = api.post("/finance/transactions/import", data={"shop_id": shop["id"]},
                   files={"file": ("t.xlsx", _xlsx(tx_headers, tx), "application/octet-stream")})
    assert res["created"] == 4
    o1 = next(o for o in api.get("/orders")["items"] if o["platform_order_id"] == "A-1")
    assert o1["items"][0]["commission_fee"] == 7.5 and o1["items"][0]["fee_estimated"] is False
    # 广告
    ad_headers = ["日期", "广告活动ID", "广告活动", "MSKU", "曝光", "点击", "花费", "销售额", "订单", "销量", "币种"]
    api.post("/ads/import", data={"shop_id": shop["id"]},
             files={"file": ("a.xlsx", _xlsx(ad_headers, [[str(day), "C1", "SP-Auto", "M1", 1000, 50, 5, 25, 1, 1, "USD"]]),
                             "application/octet-stream")})
    # 费用
    api.post("/finance/expenses", {"category": "software", "shop_id": shop["id"], "expense_date": str(day), "amount": 71, "currency": "CNY"})

    rep = api.get(f"/finance/profit?date_from={day}&date_to={day}&group_by=msku")
    rows = {r["msku"]: r for r in rep["items"]}
    m1 = rows["M1"]
    assert m1["units"] == 3 and m1["orders"] == 2
    rate = 7.1
    assert abs(m1["sales"] - 75 * rate) < 0.01
    # 佣金：A-1 实际 7.5，A-2 预估 25*15%=3.75
    assert abs(m1["commission"] - (7.5 + 3.75) * rate) < 0.01
    assert abs(m1["fulfillment_fee"] - 8 * rate) < 0.01
    assert abs(m1["ad_spend"] - 5 * rate) < 0.01
    # 成本：采购 10 + 头程 100/50=2
    assert m1["cost_purchase"] == 30 and m1["cost_freight"] == 6
    tot = rep["totals"]
    assert abs(tot["platform_other_fee"] - 10 * rate) < 0.01
    assert tot["expenses"] == 71
    expected = (75 - 11.25 - 8 - 5 - 10) * rate - 36 - 71
    assert abs(tot["profit"] - expected) < 0.05
    assert rep["base_currency"] == "CNY"

    by_shop = api.get(f"/finance/profit?date_from={day}&date_to={day}&group_by=shop")["items"]
    assert len(by_shop) == 1 and abs(by_shop[0]["profit"] - expected) < 0.05
    by_day = api.get(f"/finance/profit?date_from={day - timedelta(days=2)}&date_to={day}&group_by=day")["items"]
    assert by_day[-1]["period"] == str(day)
    resp = api.get(f"/finance/profit/export?date_from={day}&date_to={day}")
    assert resp.status_code == 200

    summary = api.get(f"/finance/transactions/summary?date_from={day}&date_to={day}")
    assert summary[0]["commission"] == -7.5 and summary[0]["net"] == 50 - 7.5 - 8 - 10

    ads = api.get(f"/ads/summary?date_from={day}&date_to={day}&group_by=msku")
    assert ads["items"][0]["acos"] == 20.0 and ads["totals"]["ctr"] == 5.0
    camp = api.get("/ads/campaigns")["items"]
    assert camp[0]["name"] == "SP-Auto"

    val = api.get("/finance/inventory-valuation")
    fba_row = next(x for x in val["items"] if x["warehouse_type"] == "fba")
    assert fba_row["qty"] == 47 and fba_row["total_value"] == 47 * 12


def test_dashboard_and_reports(api, factory):
    shop, p, lst, day = _seed(api, factory)
    ov = api.get("/dashboard/overview")
    assert ov["kpi"]["last_7d"]["orders"] == 2 and ov["kpi"]["last_7d"]["units"] == 3
    assert len(ov["trend"]) == 30 and ov["top_products"][0]["msku"] == "M1"
    assert "month_profit" in ov and ov["todo"]["unpaired_listings"] == 0
    rep = api.get(f"/reports/sales?date_from={day}&date_to={day}&group_by=sku")
    assert rep["items"][0]["sku"] == "P1" and rep["totals"]["units"] == 3
    aging = api.get("/reports/inventory-aging")
    assert aging["summary"][0]["qty"] == 50 + 47
    turn = api.get("/reports/inventory-turnover")
    assert turn["items"][0]["sold_qty"] == 3
