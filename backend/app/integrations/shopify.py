"""Shopify Admin REST API 连接器（独立站）。

所需凭证：access_token（自定义应用 Admin API access token）；店铺需填写 store_domain（xxx.myshopify.com）。
"""

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

from app.integrations.base import LISTINGS, ORDERS, ConnectorError, PlatformConnector
from app.integrations.dto import ListingDTO, OrderDTO, OrderItemDTO

API_VERSION = "2024-10"
_LINK_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class ShopifyConnector(PlatformConnector):
    platform = "shopify"
    capabilities = frozenset({ORDERS, LISTINGS})
    credential_fields = [("access_token", "Admin API Access Token", True)]

    def __init__(self, shop, credentials, client=None):
        super().__init__(shop, credentials, client)
        domain = (shop.store_domain or self.credentials.get("store_domain") or "").strip().rstrip("/")
        if not domain:
            raise ConnectorError("Shopify 店铺未填写店铺域名（xxx.myshopify.com）")
        domain = domain.replace("https://", "").replace("http://", "")
        self.base = f"https://{domain}/admin/api/{API_VERSION}"

    def _headers(self) -> dict:
        token = self.credentials.get("access_token")
        if not token:
            raise ConnectorError("缺少 access_token", auth=True)
        return {"X-Shopify-Access-Token": token, "Accept": "application/json"}

    def _paged(self, path: str, key: str, params: dict) -> Iterator[dict]:
        url: str | None = self.base + path
        query: dict | None = params
        while url:
            resp = self.request("GET", url, headers=self._headers(), params=query)
            yield from resp.json().get(key, [])
            m = _LINK_NEXT.search(resp.headers.get("Link", ""))
            url, query = (m.group(1), None) if m else (None, None)

    def test_connection(self) -> dict:
        data = self.request("GET", self.base + "/shop.json", headers=self._headers()).json()
        shop = data.get("shop", {})
        return {"ok": True, "name": shop.get("name"), "currency": shop.get("currency")}

    def fetch_orders(self, updated_after: datetime) -> Iterator[OrderDTO]:
        params = {"status": "any", "limit": 250, "updated_at_min": updated_after.astimezone(UTC).isoformat()}
        for o in self._paged("/orders.json", "orders", params):
            yield self.map_order(o)

    def map_order(self, o: dict) -> OrderDTO:
        if o.get("cancelled_at"):
            status = "cancelled"
        elif o.get("fulfillment_status") == "fulfilled":
            status = "shipped"
        elif o.get("financial_status") in ("pending", "authorized"):
            status = "pending"
        else:
            status = "unshipped"
        addr = o.get("shipping_address") or {}
        ship_total = sum(Decimal(str(s.get("price") or 0)) for s in o.get("shipping_lines") or [])
        items = []
        lines = o.get("line_items") or []
        for idx, li in enumerate(lines):
            qty = int(li.get("quantity") or 0)
            items.append(
                OrderItemDTO(
                    msku=li.get("sku") or str(li.get("variant_id") or li.get("id")),
                    title=li.get("title"),
                    platform_item_id=str(li.get("id")),
                    quantity=qty,
                    item_amount=Decimal(str(li.get("price") or 0)) * qty,
                    discount_amount=Decimal(str(li.get("total_discount") or 0)),
                    tax_amount=sum(Decimal(str(t.get("price") or 0)) for t in li.get("tax_lines") or []),
                    shipping_amount=ship_total if idx == 0 else Decimal(0),
                    commission_fee=Decimal(0),
                    fulfillment_fee=Decimal(0),
                )
            )
        tracking = None
        carrier = None
        for f in o.get("fulfillments") or []:
            tracking = f.get("tracking_number") or tracking
            carrier = f.get("tracking_company") or carrier
        customer = o.get("customer") or {}
        return OrderDTO(
            platform_order_id=str(o.get("name") or o.get("id")),
            fulfillment="FBM",
            platform_status=o.get("fulfillment_status") or o.get("financial_status"),
            status=status,
            purchase_at=_dt(o.get("created_at")),
            paid_at=_dt(o.get("processed_at")),
            currency=o.get("currency") or self.shop.currency,
            buyer_name=" ".join(x for x in (customer.get("first_name"), customer.get("last_name")) if x) or None,
            buyer_email=o.get("email"),
            ship_name=addr.get("name"),
            ship_phone=addr.get("phone"),
            ship_country=addr.get("country_code"),
            ship_state=addr.get("province_code") or addr.get("province"),
            ship_city=addr.get("city"),
            ship_address1=addr.get("address1"),
            ship_address2=addr.get("address2"),
            ship_postcode=addr.get("zip"),
            buyer_note=o.get("note"),
            carrier=carrier,
            tracking_no=tracking,
            items=items,
        )

    def fetch_listings(self) -> Iterator[ListingDTO]:
        for p in self._paged("/products.json", "products", {"limit": 250}):
            image = (p.get("image") or {}).get("src")
            for v in p.get("variants") or []:
                sku = v.get("sku") or str(v.get("id"))
                title = p.get("title") if v.get("title") in (None, "Default Title") else f"{p.get('title')} - {v.get('title')}"
                yield ListingDTO(
                    msku=sku,
                    asin=str(v.get("id")),
                    parent_asin=str(p.get("id")),
                    title=title,
                    image_url=image,
                    price=Decimal(str(v.get("price") or 0)),
                    currency=self.shop.currency,
                    status="active" if p.get("status") == "active" else "inactive",
                    fulfillment="FBM",
                    quantity=v.get("inventory_quantity"),
                )
