"""Walmart Marketplace API 连接器（美国站）。

授权：卖家在 Walmart Seller Center → Settings → API Key Management 生成 Client ID / Client Secret，
连接器使用 OAuth client_credentials 换取 15 分钟有效的 access token。

支持：订单（含 WFS 订单）、商品 Listing、WFS 库存、自发货订单回传运单号。
加拿大站使用数字签名认证，暂不支持。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

from app.integrations.base import FBA_INVENTORY, LISTINGS, ORDERS, ConnectorError, PlatformConnector
from app.integrations.dto import FbaInventoryDTO, ListingDTO, OrderDTO, OrderItemDTO

BASE_URL = "https://marketplace.walmartapis.com"
SVC_NAME = "Walmart Marketplace"
#: Walmart 认可的承运商名称，其他承运商使用 otherCarrier
KNOWN_CARRIERS = {
    "UPS", "USPS", "FedEx", "DHL", "OnTrac", "LaserShip", "Pitney Bowes", "Amazon Logistics", "Spee Dee", "Estes",
    "Saia", "Yellow", "Old Dominion", "XPO Logistics", "Purolator", "Canada Post", "4PX", "Yanwen", "China Post", "YunExpress",
}


def _ms(value) -> datetime | None:
    if value in (None, ""):
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def _amount(obj: dict | None) -> Decimal:
    return Decimal(str((obj or {}).get("amount") or 0))


class WalmartConnector(PlatformConnector):
    platform = "walmart"
    capabilities = frozenset({ORDERS, LISTINGS, FBA_INVENTORY})
    credential_fields = [
        ("client_id", "Client ID", False),
        ("client_secret", "Client Secret", True),
    ]
    page_size = 200

    def __init__(self, shop, credentials, client=None):
        super().__init__(shop, credentials, client)
        if getattr(shop, "marketplace_code", None) == "WALMART_CA":
            raise ConnectorError("沃尔玛加拿大站使用数字签名认证，暂不支持 API 对接，请使用 Excel 导入")
        self.base = (self.credentials.get("endpoint") or BASE_URL).rstrip("/")
        self._token: str | None = None
        self._token_expire = 0.0

    # ------------------------------------------------------------ 认证
    def _common_headers(self) -> dict:
        return {"WM_SVC.NAME": SVC_NAME, "WM_QOS.CORRELATION_ID": str(uuid.uuid4()), "Accept": "application/json"}

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expire - 60:
            return self._token
        cid, secret = self.credentials.get("client_id"), self.credentials.get("client_secret")
        if not cid or not secret:
            raise ConnectorError("缺少 Walmart Client ID / Client Secret", auth=True)
        resp = self.request(
            "POST", f"{self.base}/v3/token", auth=(cid, secret),
            headers={**self._common_headers(), "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials"},
        )
        data = resp.json()
        if "access_token" not in data:
            raise ConnectorError(f"获取 Walmart access token 失败: {data}", auth=True)
        self._token = data["access_token"]
        self._token_expire = time.time() + int(data.get("expires_in", 900))
        return self._token

    def api(self, method: str, path: str, **kwargs) -> dict:
        headers = {**self._common_headers(), "WM_SEC.ACCESS_TOKEN": self._access_token(), **kwargs.pop("headers", {})}
        return self.request(method, f"{self.base}{path}", headers=headers, **kwargs).json()

    def test_connection(self) -> dict:
        data = self.api("GET", "/v3/items", params={"limit": 1})
        return {"ok": True, "items": data.get("totalItems")}

    # ------------------------------------------------------------ 订单
    def fetch_orders(self, updated_after: datetime) -> Iterator[OrderDTO]:
        params: dict | None = {
            "lastModifiedStartDate": updated_after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": self.page_size, "productInfo": "true",
        }
        path = "/v3/orders"
        while True:
            data = self.api("GET", path, params=params)
            lst = data.get("list") or {}
            for o in ((lst.get("elements") or {}).get("order")) or []:
                yield self.map_order(o)
            cursor = (lst.get("meta") or {}).get("nextCursor")
            if not cursor:
                break
            # nextCursor 为完整查询串（以 ? 开头）
            path, params = f"/v3/orders{cursor if cursor.startswith('?') else '?' + cursor}", None

    def map_order(self, o: dict) -> OrderDTO:
        ship = o.get("shippingInfo") or {}
        addr = ship.get("postalAddress") or {}
        statuses: list[str] = []
        tracking = carrier = None
        shipped_at = None
        currency = None
        items = []
        # 每个订单行一条明细（platform_item_id = lineNumber），回传运单号时按行确认
        for ln in ((o.get("orderLines") or {}).get("orderLine")) or []:
            item = ln.get("item") or {}
            qty = int(Decimal(str((ln.get("orderLineQuantity") or {}).get("amount") or 1)))
            amounts = {"item": Decimal(0), "ship": Decimal(0), "tax": Decimal(0), "discount": Decimal(0)}
            for ch in ((ln.get("charges") or {}).get("charge")) or []:
                amt = _amount(ch.get("chargeAmount"))
                currency = currency or (ch.get("chargeAmount") or {}).get("currency")
                kind = (ch.get("chargeType") or "").upper()
                if kind == "PRODUCT":
                    amounts["item"] += amt
                elif kind == "SHIPPING":
                    amounts["ship"] += amt
                elif amt < 0 or "DISCOUNT" in kind:
                    amounts["discount"] += abs(amt)
                amounts["tax"] += _amount((ch.get("tax") or {}).get("taxAmount"))
            for st in ((ln.get("orderLineStatuses") or {}).get("orderLineStatus")) or []:
                statuses.append(st.get("status") or "")
                ti = st.get("trackingInfo") or {}
                if ti.get("trackingNumber"):
                    tracking = ti["trackingNumber"]
                    cn = ti.get("carrierName") or {}
                    carrier = cn.get("carrier") or cn.get("otherCarrier")
                    shipped_at = _ms(ti.get("shipDateTime")) or shipped_at
            items.append(OrderItemDTO(
                msku=item.get("sku") or str(ln.get("lineNumber")), quantity=qty, item_amount=amounts["item"],
                shipping_amount=amounts["ship"], tax_amount=amounts["tax"], discount_amount=amounts["discount"],
                title=item.get("productName"), platform_item_id=str(ln.get("lineNumber")),
            ))
        uniq = set(statuses) or {"Created"}
        if uniq <= {"Cancelled"}:
            status = "cancelled"
        elif uniq <= {"Delivered", "Cancelled"}:
            status = "delivered"
        elif uniq <= {"Shipped", "Delivered", "Cancelled"}:
            status = "shipped"
        else:
            status = "unshipped"
        node = ((o.get("shipNode") or {}).get("type")) or ""
        return OrderDTO(
            platform_order_id=str(o.get("purchaseOrderId")),
            fulfillment="FBA" if node == "WFSFulfilled" else "FBM",
            platform_status=",".join(sorted(uniq)),
            status=status,
            purchase_at=_ms(o.get("orderDate")) or datetime.now(UTC),
            paid_at=_ms(o.get("orderDate")),
            latest_ship_at=_ms(ship.get("estimatedShipDate")),
            shipped_at=shipped_at,
            currency=currency or getattr(self.shop, "currency", None) or "USD",
            buyer_name=addr.get("name"),
            buyer_email=o.get("customerEmailId"),
            ship_name=addr.get("name"),
            ship_phone=ship.get("phone"),
            ship_country={"USA": "US", "CAN": "CA"}.get(addr.get("country"), addr.get("country")),
            ship_state=addr.get("state"),
            ship_city=addr.get("city"),
            ship_address1=addr.get("address1"),
            ship_address2=addr.get("address2"),
            ship_postcode=addr.get("postalCode"),
            carrier=carrier,
            tracking_no=tracking,
            items=items,
        )

    def confirm_shipment(self, order) -> None:
        carrier = (order.carrier or "").strip()
        carrier_name = {"carrier": carrier} if carrier in KNOWN_CARRIERS else {"otherCarrier": carrier or "Other"}
        ship_ms = int((order.shipped_at or datetime.now(UTC)).timestamp() * 1000)
        lines = [{
            "lineNumber": item.platform_item_id,
            "orderLineStatuses": {"orderLineStatus": [{
                "status": "Shipped",
                "statusQuantity": {"unitOfMeasurement": "EACH", "amount": str(item.quantity)},
                "trackingInfo": {"shipDateTime": ship_ms, "carrierName": carrier_name, "methodCode": "Standard",
                                 "trackingNumber": order.tracking_no},
            }]},
        } for item in order.items if item.platform_item_id]
        if not lines:
            raise ConnectorError("订单缺少 Walmart 订单行号，无法回传")
        self.api("POST", f"/v3/orders/{order.platform_order_id}/shipping",
                 headers={"Content-Type": "application/json"}, json={"orderShipment": {"orderLines": {"orderLine": lines}}})

    # ------------------------------------------------------------ 商品 / WFS 库存
    def fetch_listings(self) -> Iterator[ListingDTO]:
        cursor = "*"
        while cursor:
            data = self.api("GET", "/v3/items", params={"limit": self.page_size, "nextCursor": cursor})
            for it in data.get("ItemResponse") or []:
                price = it.get("price") or {}
                yield ListingDTO(
                    msku=it.get("sku"),
                    asin=it.get("wpid") or it.get("itemId"),
                    parent_asin=it.get("variantGroupId"),
                    title=it.get("productName"),
                    price=_amount(price),
                    currency=price.get("currency") or getattr(self.shop, "currency", None),
                    status="active" if it.get("publishedStatus") == "PUBLISHED" and it.get("lifecycleStatus", "ACTIVE") == "ACTIVE" else "inactive",
                    fulfillment="FBM",
                )
            cursor = data.get("nextCursor")

    def fetch_fba_inventory(self) -> Iterator[FbaInventoryDTO]:
        """WFS（Walmart Fulfillment Services）库存，对应系统中的平台仓库存。"""
        offset = 0
        limit = 300
        while True:
            data = self.api("GET", "/v3/fulfillment/inventory", params={"limit": limit, "offset": offset})
            rows = ((data.get("payload") or {}).get("inventory")) or []
            for row in rows:
                avail = on_hand = 0
                for node in row.get("shipNodes") or []:
                    avail += int(node.get("availToSellQty") or 0)
                    on_hand += int(node.get("onHandQty") or 0)
                yield FbaInventoryDTO(msku=row.get("sku"), fulfillable=avail, reserved=max(on_hand - avail, 0))
            total = int(((data.get("headers") or {}).get("totalCount")) or 0)
            offset += limit
            if not rows or offset >= total:
                break
