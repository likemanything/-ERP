from datetime import date, timedelta

from tests.test_orders import _xlsx


def test_replenishment_suggestions(api, factory):
    wh = factory.default_warehouse()
    shop = factory.shop(name="US店")
    s = factory.supplier()
    p = factory.product(sku="HOT", purchase_cost=10, purchase_lead_days=10, moq=50, default_supplier_id=s["id"])
    lst = factory.listing(shop["id"], p["id"], msku="HOT-M")
    factory.stock_in(wh["id"], p["id"], 40)
    # 过去 30 天每天卖 2 件（FBA 已发货）
    today = date.today()
    rows = []
    for d in range(1, 31):
        day = today - timedelta(days=d)
        rows.append(["US店", f"O-{d}", f"{day.isoformat()} 12:00:00", "HOT-M", 2, 20, "USD", "FBA", "shipped"])
    api.post("/orders/import", files={"file": ("o.xlsx", _xlsx(
        ["店铺", "订单号", "下单时间", "MSKU", "数量", "单价", "币种", "配送方式", "状态"], rows), "application/octet-stream")})
    wb_rows = [["US店", "HOT-M", 50, 20, 0]]
    api.post("/fba-inventory/import", files={"file": ("f.xlsx", _xlsx(["店铺", "MSKU", "可售", "在途", "预留"], wb_rows),
                                                      "application/octet-stream")})
    sug = api.get("/replenishment/listings")
    row = sug[0]
    assert row["sales_30d"] == 60 and abs(row["daily_sales"] - 2) < 0.2
    assert row["fba_available"] == 50 and row["fba_inbound"] == 20
    # 需求 2 * (30+15+30)=150 - 70 = 80
    assert row["suggest_ship_qty"] == 80
    assert row["available_days"] == 25.0 and row["local_available"] == 40

    # 个性化参数：头程改为 10 天
    api.put(f"/replenishment/rules/{lst['id']}", {"transit_days": 10})
    row = api.get("/replenishment/listings")[0]
    assert row["suggest_ship_qty"] == 2 * (10 + 15 + 30) - 70 and row["has_custom_rule"]

    psug = api.get("/replenishment/products?only_need=true")
    prow = psug[0]
    # 需求 = 2 * (10 采购 + 2 质检 + 30 头程 + 15 安全 + 30 备货) = 174；供给 = 40 本地 + 70 FBA = 110
    assert prow["total_supply"] == 110 and prow["suggest_purchase_qty"] == 64

    api.post("/replenishment/to-purchase-plans", {"items": [{"product_id": p["id"], "qty": prow["suggest_purchase_qty"]}]})
    plans = api.get("/purchase-plans")["items"]
    assert plans[0]["source"] == "replenishment" and plans[0]["supplier_id"] == s["id"]
    # 已有计划计入供给，建议量下降
    prow = api.get("/replenishment/products")[0]
    assert prow["planned_qty"] == 64 and prow["suggest_purchase_qty"] == 0

    api.post("/replenishment/to-shipment-plans", {"items": [{"listing_id": lst["id"], "qty": 30}], "ship_from_warehouse_id": wh["id"]})
    assert api.get("/shipment-plans")["items"][0]["total_qty"] == 30
