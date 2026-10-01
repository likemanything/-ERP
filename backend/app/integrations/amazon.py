"""Amazon Selling Partner API 连接器。

授权：开发者在 Seller Central 注册 SP-API 应用后，卖家授权得到 refresh_token。
所需凭证：client_id、client_secret（LWA 应用凭证）、refresh_token（卖家授权）。
自 2023-10 起 SP-API 不再要求 AWS SigV4 签名，仅需 LWA access token。

接口：
* Orders v0：getOrders / getOrderItems / confirmShipment
* Reports 2021-06-30：GET_MERCHANT_LISTINGS_ALL_DATA（Listing）
* FBA Inventory v1：getInventorySummaries
* Finances v0：listFinancialEvents
"""

import csv
import gzip
import io
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.integrations.amazon_ads import AmazonAdsClient
from app.integrations.base import (
    ADS,
    FBA_INVENTORY,
    FINANCES,
    LISTINGS,
    ORDERS,
    ConnectorError,
    PlatformConnector,
)
from app.integrations.dto import FbaInventoryDTO, ListingDTO, OrderDTO, OrderItemDTO, TransactionDTO
from app.modules.shop.marketplaces import get_marketplace

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
ENDPOINTS = {
    "NA": "https://sellingpartnerapi-na.amazon.com",
    "EU": "https://sellingpartnerapi-eu.amazon.com",
    "FE": "https://sellingpartnerapi-fe.amazon.com",
}

STATUS_MAP = {
    "Pending": "pending",
    "PendingAvailability": "pending",
    "Unshipped": "unshipped",
    "PartiallyShipped": "unshipped",
    "Shipped": "shipped",
    "InvoiceUnconfirmed": "shipped",
    "Canceled": "cancelled",
    "Unfulfillable": "cancelled",
}


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _money(obj: dict | None) -> Decimal:
    if not obj:
        return Decimal(0)
    amount = obj.get("Amount", obj.get("CurrencyAmount", 0))
    return Decimal(str(amount or 0))


class AmazonConnector(PlatformConnector):
    platform = "amazon"
    capabilities = frozenset({ORDERS, LISTINGS, FBA_INVENTORY, FINANCES, ADS})
    credential_fields = [
        ("client_id", "LWA Client ID", False),
        ("client_secret", "LWA Client Secret", True),
        ("refresh_token", "Refresh Token（卖家授权）", True),
        ("ads_refresh_token", "广告 Refresh Token（可选，开通广告数据同步）", True),
        ("ads_client_id", "广告应用 Client ID（可选，默认同上）", False),
        ("ads_client_secret", "广告应用 Client Secret（可选）", True),
        ("ads_profile_id", "广告 Profile ID（可选，默认按站点自动匹配）", False),
    ]
    #: getOrderItems 速率约 0.5 次/秒，两次调用间隔（秒）
    item_call_interval = 2.0
    report_poll_interval = 15.0
    report_poll_timeout = 900.0

    def __init__(self, shop, credentials, client=None):
        super().__init__(shop, credentials, client)
        mp = get_marketplace(shop.marketplace_code)
        if mp is None or mp.platform != "amazon":
            raise ConnectorError("亚马逊店铺未设置站点")
        self.marketplace = mp
        self.endpoint = self.credentials.get("endpoint") or ENDPOINTS.get(mp.region, ENDPOINTS["NA"])
        self._token: str | None = None
        self._token_expire = 0.0
        self.ads = AmazonAdsClient(self, mp)

    def supports(self, job_type: str) -> bool:
        if job_type == ADS:
            return self.ads.configured
        return super().supports(job_type)

    def fetch_ad_metrics(self, start, end):
        return self.ads.fetch_metrics(start, end)

    # ------------------------------------------------------------ 认证
    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expire - 60:
            return self._token
        for key in ("client_id", "client_secret", "refresh_token"):
            if not self.credentials.get(key):
                raise ConnectorError(f"缺少授权参数 {key}", auth=True)
        resp = self.request(
            "POST",
            LWA_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.credentials["refresh_token"],
                "client_id": self.credentials["client_id"],
                "client_secret": self.credentials["client_secret"],
            },
        )
        data = resp.json()
        if "access_token" not in data:
            raise ConnectorError(f"获取 access_token 失败: {data}", auth=True)
        self._token = data["access_token"]
        self._token_expire = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def api(self, method: str, path: str, **kwargs) -> dict:
        headers = kwargs.pop("headers", {})
        headers.update({"x-amz-access-token": self._access_token(), "accept": "application/json"})
        resp = self.request(method, self.endpoint + path, headers=headers, **kwargs)
        return resp.json() if resp.content else {}

    def test_connection(self) -> dict:
        data = self.api("GET", "/sellers/v1/marketplaceParticipations")
        mps = [p.get("marketplace", {}).get("id") for p in data.get("payload", [])]
        return {"ok": True, "marketplaces": mps, "authorized_for_site": self.marketplace.platform_id in mps}

    # ------------------------------------------------------------ 订单
    def fetch_orders(self, updated_after: datetime) -> Iterator[OrderDTO]:
        params = {
            "MarketplaceIds": self.marketplace.platform_id,
            "LastUpdatedAfter": _iso(updated_after),
            "MaxResultsPerPage": 100,
        }
        next_token = None
        while True:
            q = {"MarketplaceIds": self.marketplace.platform_id, "NextToken": next_token} if next_token else params
            payload = self.api("GET", "/orders/v0/orders", params=q).get("payload", {})
            for o in payload.get("Orders", []):
                yield self._map_order(o, self._order_items(o["AmazonOrderId"]))
            next_token = payload.get("NextToken")
            if not next_token:
                break

    def _order_items(self, order_id: str) -> list[dict]:
        items: list[dict] = []
        next_token = None
        while True:
            params = {"NextToken": next_token} if next_token else None
            payload = self.api("GET", f"/orders/v0/orders/{order_id}/orderItems", params=params).get("payload", {})
            items.extend(payload.get("OrderItems", []))
            next_token = payload.get("NextToken")
            if self.item_call_interval:
                time.sleep(self.item_call_interval)
            if not next_token:
                return items

    def _map_order(self, o: dict, items: list[dict]) -> OrderDTO:
        addr = o.get("ShippingAddress") or {}
        buyer = o.get("BuyerInfo") or {}
        currency = (o.get("OrderTotal") or {}).get("CurrencyCode") or self.marketplace.currency
        status = STATUS_MAP.get(o.get("OrderStatus", ""), "unshipped")
        return OrderDTO(
            platform_order_id=o["AmazonOrderId"],
            fulfillment="FBA" if o.get("FulfillmentChannel") == "AFN" else "FBM",
            platform_status=o.get("OrderStatus"),
            status=status,
            purchase_at=_dt(o.get("PurchaseDate")),
            latest_ship_at=_dt(o.get("LatestShipDate")),
            shipped_at=_dt(o.get("LastUpdateDate")) if status == "shipped" else None,
            currency=currency,
            buyer_name=buyer.get("BuyerName"),
            buyer_email=buyer.get("BuyerEmail"),
            ship_name=addr.get("Name"),
            ship_phone=addr.get("Phone"),
            ship_country=addr.get("CountryCode"),
            ship_state=addr.get("StateOrRegion"),
            ship_city=addr.get("City"),
            ship_address1=addr.get("AddressLine1"),
            ship_address2=addr.get("AddressLine2"),
            ship_postcode=addr.get("PostalCode"),
            items=[
                OrderItemDTO(
                    msku=it.get("SellerSKU") or it.get("ASIN"),
                    asin=it.get("ASIN"),
                    title=it.get("Title"),
                    platform_item_id=it.get("OrderItemId"),
                    quantity=int(it.get("QuantityOrdered") or 0),
                    item_amount=_money(it.get("ItemPrice")),
                    shipping_amount=_money(it.get("ShippingPrice")),
                    tax_amount=_money(it.get("ItemTax")),
                    discount_amount=_money(it.get("PromotionDiscount")),
                )
                for it in items
                if int(it.get("QuantityOrdered") or 0) > 0 or status == "cancelled"
            ],
        )

    def confirm_shipment(self, order) -> None:
        items = [{"orderItemId": i.platform_item_id, "quantity": i.quantity} for i in order.items if i.platform_item_id]
        body = {
            "marketplaceId": self.marketplace.platform_id,
            "packageDetail": {
                "packageReferenceId": "1",
                "carrierCode": order.carrier or "Other",
                "trackingNumber": order.tracking_no,
                "shipDate": _iso(order.shipped_at or datetime.now(UTC)),
                "orderItems": items,
            },
        }
        self.api("POST", f"/orders/v0/orders/{order.platform_order_id}/shipmentConfirmation", json=body)

    # ------------------------------------------------------------ 报告
    def _run_report(self, report_type: str) -> list[dict]:
        created = self.api("POST", "/reports/2021-06-30/reports",
                           json={"reportType": report_type, "marketplaceIds": [self.marketplace.platform_id]})
        report_id = created["reportId"]
        deadline = time.time() + self.report_poll_timeout
        while True:
            rep = self.api("GET", f"/reports/2021-06-30/reports/{report_id}")
            status = rep.get("processingStatus")
            if status == "DONE":
                break
            if status in ("CANCELLED", "FATAL"):
                raise ConnectorError(f"报告 {report_type} 生成失败: {status}")
            if time.time() > deadline:
                raise ConnectorError(f"报告 {report_type} 生成超时", retryable=True)
            time.sleep(self.report_poll_interval)
        doc = self.api("GET", f"/reports/2021-06-30/documents/{rep['reportDocumentId']}")
        raw = self.request("GET", doc["url"]).content
        if doc.get("compressionAlgorithm") == "GZIP":
            raw = gzip.decompress(raw)
        text = raw.decode("utf-8", errors="replace") if self.marketplace.country != "JP" else raw.decode("cp932", errors="replace")
        return list(csv.DictReader(io.StringIO(text), delimiter="\t"))

    def fetch_listings(self) -> Iterator[ListingDTO]:
        for row in self._run_report("GET_MERCHANT_LISTINGS_ALL_DATA"):
            sku = row.get("seller-sku")
            if not sku:
                continue
            channel = (row.get("fulfillment-channel") or "").upper()
            status = (row.get("status") or "Active").lower()
            open_date = None
            if row.get("open-date"):
                try:
                    open_date = datetime.strptime(row["open-date"][:10], "%Y-%m-%d").date()
                except ValueError:
                    open_date = None
            yield ListingDTO(
                msku=sku,
                asin=row.get("asin1") or None,
                title=row.get("item-name") or None,
                price=Decimal(row.get("price") or 0),
                currency=self.marketplace.currency,
                status="active" if status == "active" else ("inactive" if status == "inactive" else status),
                fulfillment="FBM" if channel in ("DEFAULT", "MFN", "") else "FBA",
                open_date=open_date,
                image_url=row.get("image-url") or None,
                quantity=int(row["quantity"]) if (row.get("quantity") or "").isdigit() else None,
            )

    # ------------------------------------------------------------ FBA 库存
    def fetch_fba_inventory(self) -> Iterator[FbaInventoryDTO]:
        mid = self.marketplace.platform_id
        next_token = None
        while True:
            params = {"details": "true", "granularityType": "Marketplace", "granularityId": mid, "marketplaceIds": mid}
            if next_token:
                params["nextToken"] = next_token
            data = self.api("GET", "/fba/inventory/v1/summaries", params=params)
            for s in data.get("payload", {}).get("inventorySummaries", []):
                d = s.get("inventoryDetails") or {}
                yield FbaInventoryDTO(
                    msku=s.get("sellerSku"),
                    fnsku=s.get("fnSku"),
                    asin=s.get("asin"),
                    fulfillable=int(d.get("fulfillableQuantity") or 0),
                    inbound_working=int(d.get("inboundWorkingQuantity") or 0),
                    inbound_shipped=int(d.get("inboundShippedQuantity") or 0),
                    inbound_receiving=int(d.get("inboundReceivingQuantity") or 0),
                    reserved=int((d.get("reservedQuantity") or {}).get("totalReservedQuantity") or 0),
                    unfulfillable=int((d.get("unfulfillableQuantity") or {}).get("totalUnfulfillableQuantity") or 0),
                )
            next_token = (data.get("pagination") or {}).get("nextToken")
            if not next_token:
                break

    # ------------------------------------------------------------ 财务
    def fetch_transactions(self, posted_after: datetime) -> Iterator[TransactionDTO]:
        # PostedBefore 必须早于当前时间至少 2 分钟
        posted_before = datetime.now(UTC) - timedelta(minutes=3)
        params = {"PostedAfter": _iso(posted_after), "PostedBefore": _iso(posted_before), "MaxResultsPerPage": 100}
        next_token = None
        while True:
            q = {"NextToken": next_token} if next_token else params
            payload = self.api("GET", "/finances/v0/financialEvents", params=q).get("payload", {})
            yield from self.map_financial_events(payload.get("FinancialEvents") or {})
            next_token = payload.get("NextToken")
            if not next_token:
                break

    def map_financial_events(self, events: dict) -> Iterator[TransactionDTO]:
        cur_default = self.marketplace.currency

        def tx(ext, posted, event_type, amount_type, money, order_id=None, sku=None, qty=0, desc=None):
            if not money:
                return None
            amount = _money(money)
            if amount == 0:
                return None
            return TransactionDTO(
                external_id=ext[:128], posted_at=_dt(posted) or datetime.now(UTC), event_type=event_type,
                amount_type=amount_type, amount=amount, currency=money.get("CurrencyCode") or cur_default,
                platform_order_id=order_id, msku=sku, quantity=qty, description=desc,
            )

        for kind, event_type in (("ShipmentEventList", "order"), ("RefundEventList", "refund")):
            for ev in events.get(kind) or []:
                oid, posted = ev.get("AmazonOrderId"), ev.get("PostedDate")
                item_key = "ShipmentItemList" if kind == "ShipmentEventList" else "ShipmentItemAdjustmentList"
                for item in ev.get(item_key) or []:
                    sku = item.get("SellerSKU")
                    qty = int(item.get("QuantityShipped") or 0)
                    iid = item.get("OrderItemId") or item.get("OrderAdjustmentItemId") or sku
                    charges = item.get("ItemChargeList") or item.get("ItemChargeAdjustmentList") or []
                    fees = item.get("ItemFeeList") or item.get("ItemFeeAdjustmentList") or []
                    promos = item.get("PromotionList") or item.get("PromotionAdjustmentList") or []
                    for c in charges:
                        t = tx(f"{event_type}-{oid}-{iid}-{c.get('ChargeType')}-{posted}", posted, event_type,
                               c.get("ChargeType"), c.get("ChargeAmount"), oid, sku, qty)
                        if t:
                            yield t
                    for f in fees:
                        t = tx(f"{event_type}-{oid}-{iid}-{f.get('FeeType')}-{posted}", posted, event_type,
                               f.get("FeeType"), f.get("FeeAmount"), oid, sku, qty)
                        if t:
                            yield t
                    for p in promos:
                        t = tx(f"{event_type}-{oid}-{iid}-promo-{p.get('PromotionId')}-{posted}", posted, event_type,
                               "Promotion", p.get("PromotionAmount"), oid, sku, qty)
                        if t:
                            yield t
        for idx, ev in enumerate(events.get("ServiceFeeEventList") or []):
            for f in ev.get("FeeList") or []:
                t = tx(f"svc-{ev.get('AmazonOrderId') or ''}-{ev.get('SellerSKU') or ''}-{f.get('FeeType')}-{idx}-{ev.get('FeeReason')}",
                       ev.get("PostedDate") or datetime.now(UTC).isoformat(), "service_fee", f.get("FeeType"),
                       f.get("FeeAmount"), ev.get("AmazonOrderId"), ev.get("SellerSKU"), desc=ev.get("FeeDescription"))
                if t:
                    yield t
        for ev in events.get("AdjustmentEventList") or []:
            for idx, item in enumerate(ev.get("AdjustmentItemList") or [{}]):
                money = item.get("TotalAmount") or ev.get("AdjustmentAmount")
                t = tx(f"adj-{ev.get('AdjustmentType')}-{ev.get('PostedDate')}-{item.get('SellerSKU')}-{idx}",
                       ev.get("PostedDate"), "adjustment", ev.get("AdjustmentType") or "Adjustment", money,
                       sku=item.get("SellerSKU"), qty=int(item.get("Quantity") or 0))
                if t:
                    yield t
        for ev in events.get("ProductAdsPaymentEventList") or []:
            t = tx(f"ads-{ev.get('invoiceId')}-{ev.get('postedDate')}", ev.get("postedDate"), "ads",
                   ev.get("transactionType") or "ProductAdsPayment", ev.get("transactionValue"))
            if t:
                yield t
