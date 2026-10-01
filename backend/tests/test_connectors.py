"""Walmart / TikTok Shop / Amazon Advertising 连接器（全部使用 MockTransport，不访问真实接口）。"""

import base64
import gzip
import hashlib
import hmac
import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

from app.core.security import decrypt_json, encrypt_json
from app.integrations.amazon import AmazonConnector
from app.integrations.base import ADS, ConnectorError
from app.integrations.tiktok import TikTokConnector, sign
from app.integrations.walmart import WalmartConnector


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


# ================================================================ Walmart
def _wm_line(no, sku, qty, price, status, tracking=None, carrier=None):
    st = {"status": status, "statusQuantity": {"unitOfMeasurement": "EACH", "amount": str(qty)}}
    if tracking:
        st["trackingInfo"] = {"shipDateTime": _ms(datetime(2026, 9, 2, tzinfo=UTC)), "trackingNumber": tracking,
                              "carrierName": {"carrier": carrier}}
    return {
        "lineNumber": str(no), "item": {"productName": f"Item {sku}", "sku": sku},
        "orderLineQuantity": {"unitOfMeasurement": "EACH", "amount": str(qty)},
        "charges": {"charge": [
            {"chargeType": "PRODUCT", "chargeAmount": {"currency": "USD", "amount": price},
             "tax": {"taxName": "Tax", "taxAmount": {"currency": "USD", "amount": 1.5}}},
            {"chargeType": "SHIPPING", "chargeAmount": {"currency": "USD", "amount": 4.99}},
        ]},
        "orderLineStatuses": {"orderLineStatus": [st]},
    }


def _wm_order(po, lines, node="SellerFulfilled"):
    return {
        "purchaseOrderId": po, "customerOrderId": f"C{po}", "customerEmailId": "buyer@relay.walmart.com",
        "orderDate": _ms(datetime(2026, 9, 1, 8, tzinfo=UTC)),
        "shippingInfo": {"phone": "5550100", "estimatedShipDate": _ms(datetime(2026, 9, 3, tzinfo=UTC)),
                         "postalAddress": {"name": "Ann Lee", "address1": "1 Main St", "city": "Austin", "state": "TX",
                                           "postalCode": "73301", "country": "USA"}},
        "orderLines": {"orderLine": lines}, "shipNode": {"type": node},
    }


def test_walmart_orders_items_inventory_and_shipping():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request):
        calls.append(request)
        path = request.url.path
        if path == "/v3/token":
            assert request.headers["WM_SVC.NAME"] == "Walmart Marketplace"
            assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"cid:secret").decode()
            assert parse_qs(request.content.decode()) == {"grant_type": ["client_credentials"]}
            return httpx.Response(200, json={"access_token": "wm-token", "token_type": "Bearer", "expires_in": 900})
        assert request.headers["WM_SEC.ACCESS_TOKEN"] == "wm-token"
        assert request.headers["WM_QOS.CORRELATION_ID"]
        if path == "/v3/orders" and request.method == "GET":
            if request.url.params.get("nextCursor") == "page2":
                return httpx.Response(200, json={"list": {"meta": {"totalCount": 3}, "elements": {"order": [
                    _wm_order("PO3", [_wm_line(1, "SKU-C", 1, 9, "Cancelled")]),
                ]}}})
            assert request.url.params["lastModifiedStartDate"].endswith("Z")
            return httpx.Response(200, json={"list": {"meta": {"totalCount": 3, "nextCursor": "?nextCursor=page2&limit=200"},
                                                      "elements": {"order": [
                _wm_order("PO1", [_wm_line(1, "SKU-A", 2, 20, "Acknowledged"), _wm_line(2, "SKU-B", 1, 15, "Created")]),
                _wm_order("PO2", [_wm_line(1, "SKU-A", 1, 10, "Shipped", "1Z999", "UPS")], node="WFSFulfilled"),
            ]}}})
        if path == "/v3/items":
            if request.url.params.get("nextCursor") == "*":
                return httpx.Response(200, json={"totalItems": 2, "nextCursor": "abc", "ItemResponse": [
                    {"sku": "SKU-A", "wpid": "W1", "productName": "Lamp", "price": {"currency": "USD", "amount": 19.99},
                     "publishedStatus": "PUBLISHED", "lifecycleStatus": "ACTIVE"}]})
            return httpx.Response(200, json={"totalItems": 2, "ItemResponse": [
                {"sku": "SKU-B", "wpid": "W2", "productName": "Mat", "price": {"currency": "USD", "amount": 9},
                 "publishedStatus": "UNPUBLISHED", "lifecycleStatus": "ACTIVE"}]})
        if path == "/v3/fulfillment/inventory":
            offset = int(request.url.params["offset"])
            rows = [{"sku": "SKU-A", "shipNodes": [{"availToSellQty": 40, "onHandQty": 45, "shipNodeType": "WFSFulfilled"}]}] \
                if offset == 0 else []
            return httpx.Response(200, json={"headers": {"totalCount": 1}, "payload": {"inventory": rows}})
        if path == "/v3/orders/PO1/shipping":
            return httpx.Response(200, json={"order": {"purchaseOrderId": "PO1"}})
        return httpx.Response(404, json={})

    shop = SimpleNamespace(id=1, marketplace_code="WALMART_US", currency="USD")
    conn = WalmartConnector(shop, {"client_id": "cid", "client_secret": "secret"}, _client(handler))
    orders = list(conn.fetch_orders(datetime.now(UTC) - timedelta(days=1)))
    assert [o.platform_order_id for o in orders] == ["PO1", "PO2", "PO3"]
    o1, o2, o3 = orders
    assert o1.status == "unshipped" and o1.fulfillment == "FBM" and o1.ship_country == "US" and o1.ship_state == "TX"
    assert [(i.msku, i.quantity, i.platform_item_id) for i in o1.items] == [("SKU-A", 2, "1"), ("SKU-B", 1, "2")]
    assert str(o1.items[0].item_amount) == "20" and str(o1.items[0].shipping_amount) == "4.99"
    assert str(o1.items[0].tax_amount) == "1.5" and o1.latest_ship_at.date() == date(2026, 9, 3)
    assert o2.fulfillment == "FBA" and o2.status == "shipped" and o2.tracking_no == "1Z999" and o2.carrier == "UPS"
    assert o3.status == "cancelled"
    # token 只换取一次
    assert sum(1 for c in calls if c.url.path == "/v3/token") == 1

    listings = list(conn.fetch_listings())
    assert [(x.msku, x.status, x.fulfillment) for x in listings] == [("SKU-A", "active", "FBM"), ("SKU-B", "inactive", "FBM")]
    inv = list(conn.fetch_fba_inventory())
    assert inv[0].msku == "SKU-A" and inv[0].fulfillable == 40 and inv[0].reserved == 5

    # 回传运单号：按订单行确认，非标准承运商使用 otherCarrier
    order = SimpleNamespace(platform_order_id="PO1", carrier="YunExpress Plus", tracking_no="YT123",
                            shipped_at=datetime(2026, 9, 2, tzinfo=UTC),
                            items=[SimpleNamespace(platform_item_id="1", quantity=2), SimpleNamespace(platform_item_id="2", quantity=1)])
    conn.confirm_shipment(order)
    body = json.loads(calls[-1].content)
    lines = body["orderShipment"]["orderLines"]["orderLine"]
    assert [ln["lineNumber"] for ln in lines] == ["1", "2"]
    status = lines[0]["orderLineStatuses"]["orderLineStatus"][0]
    assert status["statusQuantity"]["amount"] == "2" and status["trackingInfo"]["carrierName"] == {"otherCarrier": "YunExpress Plus"}
    order.carrier = "UPS"
    conn.confirm_shipment(order)
    status = json.loads(calls[-1].content)["orderShipment"]["orderLines"]["orderLine"][0]["orderLineStatuses"]["orderLineStatus"][0]
    assert status["trackingInfo"]["carrierName"] == {"carrier": "UPS"}


def test_walmart_errors():
    with pytest.raises(ConnectorError, match="加拿大"):
        WalmartConnector(SimpleNamespace(marketplace_code="WALMART_CA"), {"client_id": "a", "client_secret": "b"})
    conn = WalmartConnector(SimpleNamespace(marketplace_code="WALMART_US", currency="USD"), {}, _client(lambda r: httpx.Response(500)))
    with pytest.raises(ConnectorError) as exc:
        conn.test_connection()
    assert exc.value.auth is True
    unauthorized = WalmartConnector(SimpleNamespace(marketplace_code="WALMART_US", currency="USD"),
                                    {"client_id": "a", "client_secret": "b"}, _client(lambda r: httpx.Response(401, json={})))
    with pytest.raises(ConnectorError) as exc:
        unauthorized.test_connection()
    assert exc.value.auth is True


# ================================================================ TikTok Shop
def test_tiktok_sign_algorithm():
    params = {"app_key": "k", "timestamp": "1700000000", "shop_cipher": "C1", "page_size": "50",
              "access_token": "ignored", "sign": "ignored"}
    body = '{"update_time_ge":1}'
    expected_base = "s3cret" + "/order/202309/orders/search" + "app_keykpage_size50shop_cipherC1timestamp1700000000" + body + "s3cret"
    expected = hmac.new(b"s3cret", expected_base.encode(), hashlib.sha256).hexdigest()
    assert sign("/order/202309/orders/search", params, body, "s3cret") == expected


def _tt_line(line_id, sku, price, discount="0"):
    return {"id": line_id, "sku_id": f"S{sku}", "seller_sku": sku, "product_name": "Bottle", "sku_name": "Blue",
            "sale_price": price, "original_price": price, "seller_discount": discount, "platform_discount": "0", "currency": "USD"}


def test_tiktok_orders_refresh_token_and_shipping():
    calls: list[httpx.Request] = []
    state = {"expired": True}

    def handler(request: httpx.Request):
        calls.append(request)
        url = request.url
        if url.host == "auth.tiktok-shops.com":
            assert url.params["grant_type"] == "refresh_token" and url.params["refresh_token"] == "rt-1"
            state["expired"] = False
            return httpx.Response(200, json={"code": 0, "message": "success", "data": {
                "access_token": "at-2", "access_token_expire_in": 4102444800, "refresh_token": "rt-2"}})
        # 所有业务请求都要带签名与 access token
        params = dict(url.params)
        body = request.content.decode()
        assert params["sign"] == sign(url.path, params, body, "secret")
        assert params["app_key"] == "app" and "timestamp" in params
        if url.path == "/authorization/202309/shops":
            assert "shop_cipher" not in params
            return httpx.Response(200, json={"code": 0, "data": {"shops": [
                {"name": "UK shop", "region": "GB", "cipher": "C-UK"}, {"name": "US shop", "region": "US", "cipher": "C-US"}]}})
        assert params["shop_cipher"] == "C-US"
        if state["expired"]:
            return httpx.Response(200, json={"code": 105002, "message": "Expired credentials"})
        assert request.headers["x-tts-access-token"] == "at-2"
        if url.path == "/order/202309/orders/search":
            assert json.loads(body)["update_time_ge"] > 0
            if params.get("page_token") == "p2":
                return httpx.Response(200, json={"code": 0, "data": {"orders": [
                    {"id": "577002", "status": "CANCELLED", "create_time": 1756720000, "payment": {"currency": "USD"},
                     "line_items": [_tt_line("L9", "SKU-B", "5")]}]}})
            return httpx.Response(200, json={"code": 0, "data": {"next_page_token": "p2", "orders": [{
                "id": "577001", "status": "AWAITING_SHIPMENT", "create_time": 1756710000, "paid_time": 1756710100,
                "fulfillment_type": "FULFILLMENT_BY_SELLER", "buyer_email": "b@x.com", "buyer_message": "gift wrap",
                "payment": {"currency": "USD", "shipping_fee": "3.99", "tax": "1.20"},
                "recipient_address": {"name": "Tom", "phone_number": "+1 555", "address_line1": "9 Elm", "postal_code": "10001",
                                      "region_code": "US", "district_info": [
                                          {"address_level_name": "State", "address_name": "NY"},
                                          {"address_level_name": "City", "address_name": "New York"}]},
                "line_items": [_tt_line("L1", "SKU-A", "12.50", "1.00"), _tt_line("L2", "SKU-A", "12.50"), _tt_line("L3", "SKU-B", "8")],
            }]}})
        if url.path == "/order/202309/orders":
            assert params["ids"] == "577001"
            return httpx.Response(200, json={"code": 0, "data": {"orders": [{"id": "577001", "line_items": [{"id": "L1"}, {"id": "L2"}]}]}})
        if url.path == "/fulfillment/202309/orders/577001/packages":
            return httpx.Response(200, json={"code": 0, "data": {"package_id": "PK1"}})
        if url.path == "/product/202309/products/search":
            return httpx.Response(200, json={"code": 0, "data": {"products": [{"id": "P1", "title": "Bottle", "status": "ACTIVATE", "skus": [
                {"id": "S1", "seller_sku": "SKU-A", "price": {"currency": "USD", "sale_price": "12.50"},
                 "inventory": [{"quantity": 7, "warehouse_id": "W1"}, {"quantity": 3, "warehouse_id": "W2"}]}]}]}})
        return httpx.Response(404, json={})

    creds = {"app_key": "app", "app_secret": "secret", "access_token": "at-1", "refresh_token": "rt-1",
             "shipping_provider_id": "6617675021119438597"}
    shop = SimpleNamespace(id=1, country="US", currency="USD", credentials_enc=encrypt_json(creds))
    conn = TikTokConnector(shop, dict(creds), _client(handler))

    orders = list(conn.fetch_orders(datetime.now(UTC) - timedelta(days=1)))
    assert [o.platform_order_id for o in orders] == ["577001", "577002"]
    o = orders[0]
    assert o.status == "unshipped" and o.fulfillment == "FBM" and o.ship_state == "NY" and o.ship_city == "New York"
    assert o.buyer_note == "gift wrap" and o.currency == "USD"
    a, b = o.items
    assert (a.msku, a.quantity, str(a.item_amount), str(a.discount_amount)) == ("SKU-A", 2, "25.00", "1.00")
    assert str(a.shipping_amount) == "3.99" and str(b.shipping_amount) == "0" and b.quantity == 1
    assert orders[1].status == "cancelled"
    # 过期 token 自动刷新，shop_cipher 自动获取，均写回店铺凭证
    saved = decrypt_json(shop.credentials_enc)
    assert saved["access_token"] == "at-2" and saved["refresh_token"] == "rt-2" and saved["shop_cipher"] == "C-US"
    assert sum(1 for c in calls if c.url.host == "auth.tiktok-shops.com") == 1

    listings = list(conn.fetch_listings())
    assert listings[0].msku == "SKU-A" and listings[0].quantity == 10 and listings[0].status == "active"

    conn.confirm_shipment(SimpleNamespace(platform_order_id="577001", tracking_no="TRK-9"))
    body = json.loads(calls[-1].content)
    assert body == {"order_line_item_ids": ["L1", "L2"], "tracking_number": "TRK-9", "shipping_provider_id": "6617675021119438597"}


def test_tiktok_errors():
    with pytest.raises(ConnectorError) as exc:
        TikTokConnector(SimpleNamespace(), {"app_key": "a"})
    assert exc.value.auth is True

    def handler(request):
        return httpx.Response(200, json={"code": 36009004, "message": "Invalid param"})

    conn = TikTokConnector(SimpleNamespace(country="US"), {"app_key": "a", "app_secret": "s", "access_token": "t", "shop_cipher": "C"},
                           _client(handler))
    with pytest.raises(ConnectorError, match="36009004") as exc:
        list(conn.fetch_listings())
    assert exc.value.auth is False
    with pytest.raises(ConnectorError, match="shipping_provider_id"):
        conn.confirm_shipment(SimpleNamespace(platform_order_id="1", tracking_no="x"))


# ================================================================ Amazon Advertising
def _amz_shop():
    return SimpleNamespace(id=1, marketplace_code="AMAZON_US", currency="USD", country="US")


def test_amazon_ads_requires_ads_credentials():
    conn = AmazonConnector(_amz_shop(), {"client_id": "a", "client_secret": "b", "refresh_token": "c"},
                           _client(lambda r: httpx.Response(500)))
    assert conn.supports(ADS) is False and conn.supports("orders") is True
    conn = AmazonConnector(_amz_shop(), {"client_id": "a", "client_secret": "b", "refresh_token": "c", "ads_refresh_token": "ads"},
                           _client(lambda r: httpx.Response(500)))
    assert conn.supports(ADS) is True


def test_amazon_ads_report_flow():
    calls: list[httpx.Request] = []
    polls = {"n": 0}
    rows = [
        {"date": "2026-09-01", "campaignId": 111, "campaignName": "Auto - Lamp", "adGroupName": "AG1", "advertisedSku": "LAMP-01",
         "advertisedAsin": "B0LAMP", "impressions": 1000, "clicks": 25, "cost": 12.34, "sales7d": 89.9, "purchases7d": 3,
         "unitsSoldClicks7d": 4, "campaignBudgetCurrencyCode": "USD"},
    ]

    def handler(request: httpx.Request):
        calls.append(request)
        url = str(request.url)
        if url.startswith("https://api.amazon.com/auth/o2/token"):
            form = parse_qs(request.content.decode())
            assert form["refresh_token"] == ["ads-rt"] and form["client_id"] == ["ads-app"]
            return httpx.Response(200, json={"access_token": "ads-at", "expires_in": 3600})
        if request.url.host == "reports.example.com":
            assert "Authorization" not in request.headers  # 预签名地址不带认证头
            return httpx.Response(200, content=gzip.compress(json.dumps(rows).encode()))
        assert request.headers["Amazon-Advertising-API-ClientId"] == "ads-app"
        assert request.headers["Authorization"] == "Bearer ads-at"
        if request.url.path == "/v2/profiles":
            assert "Amazon-Advertising-API-Scope" not in request.headers
            return httpx.Response(200, json=[
                {"profileId": 1, "countryCode": "CA", "accountInfo": {"marketplaceStringId": "A2EUQ1WTGCTBG2"}},
                {"profileId": 2, "countryCode": "US", "accountInfo": {"marketplaceStringId": "ATVPDKIKX0DER"}},
            ])
        assert request.headers["Amazon-Advertising-API-Scope"] == "2"
        if request.url.path == "/reporting/reports" and request.method == "POST":
            assert request.headers["Content-Type"] == "application/vnd.createasyncreportrequest.v3+json"
            body = json.loads(request.content)
            assert body["configuration"]["reportTypeId"] == "spAdvertisedProduct"
            assert body["configuration"]["timeUnit"] == "DAILY"
            return httpx.Response(200, json={"reportId": f"r-{body['startDate']}", "status": "PENDING"})
        if request.url.path.startswith("/reporting/reports/"):
            polls["n"] += 1
            if polls["n"] % 2 == 1:
                return httpx.Response(200, json={"status": "PENDING"})
            return httpx.Response(200, json={"status": "COMPLETED", "url": "https://reports.example.com/r.json.gz"})
        return httpx.Response(404, json={})

    creds = {"client_id": "sp", "client_secret": "sp-secret", "refresh_token": "sp-rt",
             "ads_refresh_token": "ads-rt", "ads_client_id": "ads-app", "ads_client_secret": "ads-secret"}
    conn = AmazonConnector(_amz_shop(), creds, _client(handler))
    conn.ads.poll_interval = 0
    metrics = list(conn.fetch_ad_metrics(date(2026, 9, 1), date(2026, 9, 1)))
    assert len(metrics) == 1
    m = metrics[0]
    assert (m.metric_date, m.campaign_id, m.msku, m.asin, m.ad_type) == (date(2026, 9, 1), "111", "LAMP-01", "B0LAMP", "SP")
    assert (m.impressions, m.clicks, m.orders, m.units) == (1000, 25, 3, 4)
    assert str(m.spend) == "12.34" and str(m.sales) == "89.9" and m.currency == "USD"

    # 超过 31 天拆成两份报告
    calls.clear()
    list(conn.fetch_ad_metrics(date(2026, 7, 1), date(2026, 8, 15)))
    created = [json.loads(c.content) for c in calls if c.url.path == "/reporting/reports" and c.method == "POST"]
    assert [(b["startDate"], b["endDate"]) for b in created] == [("2026-07-01", "2026-07-31"), ("2026-08-01", "2026-08-15")]


def test_amazon_ads_report_failure():
    def handler(request):
        if str(request.url).startswith("https://api.amazon.com/auth/o2/token"):
            return httpx.Response(200, json={"access_token": "x", "expires_in": 3600})
        if request.url.path == "/reporting/reports":
            return httpx.Response(200, json={"reportId": "r1"})
        if request.url.path == "/reporting/reports/r1":
            return httpx.Response(200, json={"status": "FAILURE", "failureReason": "bad columns"})
        return httpx.Response(404, json={})

    conn = AmazonConnector(_amz_shop(), {"client_id": "a", "client_secret": "b", "refresh_token": "c",
                                         "ads_refresh_token": "d", "ads_profile_id": "99"}, _client(handler))
    conn.ads.poll_interval = 0
    with pytest.raises(ConnectorError, match="bad columns"):
        list(conn.fetch_ad_metrics(date(2026, 9, 1), date(2026, 9, 2)))


# ================================================================ 端到端：Walmart WFS 订单从 WFS 仓结转成本
def test_walmart_wfs_order_sync_end_to_end(api, factory, monkeypatch):
    from app.core.security import decrypt_json as _decrypt

    shop = factory.shop(name="Walmart店", platform="walmart", marketplace_code="WALMART_US",
                        credentials={"client_id": "cid", "client_secret": "secret"})
    wfs = next(w for w in api.get("/warehouses?warehouse_type=fba")["items"] if w["shop_id"] == shop["id"])
    assert wfs["name"].startswith("WFS仓")
    p = factory.product(sku="WM-LAMP", purchase_cost=10)
    factory.listing(shop["id"], p["id"], msku="SKU-A", fulfillment="FBA")
    factory.stock_in(wfs["id"], p["id"], 5, unit_cost=12)

    def handler(request: httpx.Request):
        if request.url.path == "/v3/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 900})
        if request.url.path == "/v3/orders":
            return httpx.Response(200, json={"list": {"meta": {}, "elements": {"order": [
                _wm_order("WFS-1", [_wm_line(1, "SKU-A", 2, 40, "Shipped", "TBA1", "FedEx")], node="WFSFulfilled"),
                _wm_order("SF-1", [_wm_line(1, "SKU-A", 1, 20, "Created")]),
            ]}}})
        return httpx.Response(404, json={})

    monkeypatch.setattr("app.modules.integration.service.get_connector",
                        lambda s, client=None: WalmartConnector(s, _decrypt(s.credentials_enc), _client(handler)))
    res = api.post(f"/shops/{shop['id']}/sync", {"job_types": ["orders"], "background": False})
    assert res["jobs"][0]["status"] == "success" and res["jobs"][0]["stats"]["created"] == 2
    orders = {o["platform_order_id"]: o for o in api.get(f"/orders?shop_id={shop['id']}")["items"]}
    wfs_order, own = orders["WFS-1"], orders["SF-1"]
    assert wfs_order["fulfillment"] == "FBA" and wfs_order["status"] == "shipped"
    assert wfs_order["items"][0]["cost_purchase"] == 24 and wfs_order["items"][0]["cost_settled"] is True
    assert own["fulfillment"] == "FBM" and own["status"] == "to_audit"
    assert factory.inventory(wfs["id"], p["id"])["qty_on_hand"] == 3
