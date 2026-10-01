import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx

from app.integrations.amazon import AmazonConnector
from app.integrations.shopify import ShopifyConnector


def test_demo_shop_sync_end_to_end(api, factory):
    shop = factory.shop(name="演示店", credentials={"mode": "demo"})
    assert shop["has_credentials"] and shop["credential_keys"] == ["mode"]
    assert api.post(f"/shops/{shop['id']}/test-connection")["ok"] is True
    res = api.post(f"/shops/{shop['id']}/sync", {"background": False})
    status = {j["job_type"]: j for j in res["jobs"]}
    assert all(j["status"] == "success" for j in res["jobs"]), res
    assert status["listings"]["stats"]["created"] == 8
    n_orders = api.get(f"/orders?shop_id={shop['id']}")["total"]
    assert n_orders > 50
    assert api.get("/fba-inventory")["total"] == 6
    assert api.get("/finance/transactions")["total"] > 0
    assert api.get("/ads/campaigns")["total"] == 8
    # 重复同步幂等
    res2 = api.post(f"/shops/{shop['id']}/sync", {"background": False, "job_types": ["orders", "listings"]})
    assert all(j["status"] == "success" for j in res2["jobs"])
    assert api.get(f"/orders?shop_id={shop['id']}")["total"] == n_orders
    jobs = api.get("/sync-jobs")
    assert jobs["total"] == 7
    # 配对后重新核算 FBA 成本
    p = factory.product(sku="LAMP", purchase_cost=30)
    lst = api.get("/listings?keyword=LAMP-01")["items"][0]
    api.post(f"/listings/{lst['id']}/pair", {"product_id": p["id"]})
    api.post("/orders/resettle-cost")
    o = next(o for o in api.get(f"/orders?keyword={lst['msku']}&status=shipped&fulfillment=FBA")["items"])
    assert o["items"][0]["cost_purchase"] == 30 * o["items"][0]["quantity"]
    shops = api.get("/shops")["items"]
    assert shops[0]["last_sync_status"] == "success"


def test_unsupported_platform_sync(api, factory):
    shop = factory.shop(name="Temu店", platform="temu", marketplace_code="TEMU_US")
    res = api.post(f"/shops/{shop['id']}/test-connection")
    assert res["ok"] is False and "暂未接入" in res["message"]


def _amz_shop():
    return SimpleNamespace(id=1, marketplace_code="AMAZON_US", currency="USD", country="US")


def test_amazon_connector_mapping():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        url = str(request.url)
        if url.startswith("https://api.amazon.com/auth/o2/token"):
            return httpx.Response(200, json={"access_token": "Atza|x", "expires_in": 3600})
        assert request.headers["x-amz-access-token"] == "Atza|x"
        if "/orderItems" in url:
            return httpx.Response(200, json={"payload": {"OrderItems": [
                {"ASIN": "B01", "SellerSKU": "SKU1", "OrderItemId": "OI1", "Title": "Lamp", "QuantityOrdered": 2,
                 "ItemPrice": {"CurrencyCode": "USD", "Amount": "59.98"}, "PromotionDiscount": {"Amount": "5.00"}}]}})
        if "/orders/v0/orders" in url:
            if "NextToken" in url:
                return httpx.Response(200, json={"payload": {"Orders": []}})
            return httpx.Response(200, json={"payload": {"NextToken": "abc", "Orders": [
                {"AmazonOrderId": "113-1", "PurchaseDate": "2026-09-01T10:00:00Z", "OrderStatus": "Shipped",
                 "FulfillmentChannel": "AFN", "OrderTotal": {"CurrencyCode": "USD", "Amount": "54.98"},
                 "ShippingAddress": {"City": "LA", "CountryCode": "US", "StateOrRegion": "CA"}}]}})
        if "/fba/inventory/v1/summaries" in url:
            return httpx.Response(200, json={"payload": {"inventorySummaries": [
                {"sellerSku": "SKU1", "fnSku": "X001", "asin": "B01", "inventoryDetails": {
                    "fulfillableQuantity": 100, "inboundShippedQuantity": 20, "reservedQuantity": {"totalReservedQuantity": 3},
                    "unfulfillableQuantity": {"totalUnfulfillableQuantity": 1}}}]}, "pagination": {}})
        return httpx.Response(404, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    conn = AmazonConnector(_amz_shop(), {"client_id": "a", "client_secret": "b", "refresh_token": "c"}, client)
    conn.item_call_interval = 0
    orders = list(conn.fetch_orders(datetime.now(UTC) - timedelta(days=1)))
    assert len(orders) == 1
    o = orders[0]
    assert o.fulfillment == "FBA" and o.status == "shipped" and o.ship_state == "CA"
    assert o.items[0].msku == "SKU1" and o.items[0].quantity == 2 and str(o.items[0].discount_amount) == "5.00"
    inv = list(conn.fetch_fba_inventory())
    assert inv[0].fulfillable == 100 and inv[0].reserved == 3 and inv[0].inbound_shipped == 20
    # token 只换取一次
    assert sum(1 for c in calls if "auth/o2/token" in str(c.url)) == 1


def test_amazon_financial_events_mapping():
    conn = AmazonConnector(_amz_shop(), {"client_id": "a", "client_secret": "b", "refresh_token": "c"},
                           httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    events = {
        "ShipmentEventList": [{"AmazonOrderId": "113-1", "PostedDate": "2026-09-02T00:00:00Z", "ShipmentItemList": [{
            "SellerSKU": "SKU1", "OrderItemId": "OI1", "QuantityShipped": 2,
            "ItemChargeList": [{"ChargeType": "Principal", "ChargeAmount": {"CurrencyCode": "USD", "CurrencyAmount": 59.98}}],
            "ItemFeeList": [{"FeeType": "Commission", "FeeAmount": {"CurrencyCode": "USD", "CurrencyAmount": -9.0}},
                            {"FeeType": "FBAPerUnitFulfillmentFee", "FeeAmount": {"CurrencyCode": "USD", "CurrencyAmount": -9.5}}],
        }]}],
        "ServiceFeeEventList": [{"FeeList": [{"FeeType": "Subscription", "FeeAmount": {"CurrencyCode": "USD", "CurrencyAmount": -39.99}}]}],
    }
    txs = list(conn.map_financial_events(events))
    by = {t.amount_type: t for t in txs}
    assert str(by["Principal"].amount) == "59.98" and by["Commission"].platform_order_id == "113-1"
    assert by["Subscription"].event_type == "service_fee"
    assert len({t.external_id for t in txs}) == len(txs)


def test_shopify_connector_pagination_and_mapping():
    pages = {
        "1": {"orders": [{"id": 1, "name": "#1001", "created_at": "2026-09-01T10:00:00-04:00", "currency": "USD",
                          "financial_status": "paid", "fulfillment_status": None, "email": "a@b.com",
                          "line_items": [{"id": 11, "sku": "SKU1", "quantity": 2, "price": "10.00", "total_discount": "1.00"}],
                          "shipping_lines": [{"price": "5.00"}], "shipping_address": {"name": "A", "country_code": "US"}}]},
        "2": {"orders": [{"id": 2, "name": "#1002", "created_at": "2026-09-01T11:00:00Z", "currency": "USD",
                          "cancelled_at": "2026-09-01T12:00:00Z", "line_items": [{"id": 21, "sku": "SKU2", "quantity": 1, "price": "8"}]}]},
    }

    def handler(request: httpx.Request):
        assert request.headers["X-Shopify-Access-Token"] == "shpat"
        page = request.url.params.get("page_info") or "1"
        headers = {}
        if page == "1":
            headers["Link"] = '<https://demo.myshopify.com/admin/api/2024-10/orders.json?page_info=2>; rel="next"'
        return httpx.Response(200, content=json.dumps(pages[page]), headers=headers)

    shop = SimpleNamespace(id=1, store_domain="demo.myshopify.com", currency="USD")
    conn = ShopifyConnector(shop, {"access_token": "shpat"}, httpx.Client(transport=httpx.MockTransport(handler)))
    orders = list(conn.fetch_orders(datetime.now(UTC)))
    assert [o.platform_order_id for o in orders] == ["#1001", "#1002"]
    assert orders[0].status == "unshipped" and str(orders[0].items[0].shipping_amount) == "5.00"
    assert orders[1].status == "cancelled"
