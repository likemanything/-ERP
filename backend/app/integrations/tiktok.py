"""TikTok Shop Partner API（202309 版本）连接器。

授权：在 TikTok Shop Partner Center 创建应用得到 app_key / app_secret，卖家授权后得到
access_token / refresh_token；shop_cipher 为可选（为空时自动通过授权店铺接口获取）。

签名（HMAC-SHA256）：除 sign / access_token 外的查询参数按键排序后拼接为 key+value，
前置 API 路径、追加请求体，再用 app_secret 首尾包裹，以 app_secret 为密钥计算十六进制摘要。

支持：订单、商品 Listing、自发货订单回传运单号（需在授权信息中填写 shipping_provider_id）。
access_token 过期时自动用 refresh_token 刷新，并写回店铺授权信息。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections import OrderedDict
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

from app.integrations.base import LISTINGS, ORDERS, ConnectorError, PlatformConnector
from app.integrations.dto import ListingDTO, OrderDTO, OrderItemDTO

API_BASE = "https://open-api.tiktokglobalshop.com"
AUTH_BASE = "https://auth.tiktok-shops.com"
#: 授权失效相关错误码
AUTH_ERRORS = {105000, 105001, 105002, 105003, 105005, 36004004}
EXPIRED_TOKEN = {105002, 36004004}

STATUS_MAP = {
    "UNPAID": "pending",
    "ON_HOLD": "pending",
    "AWAITING_SHIPMENT": "unshipped",
    "PARTIALLY_SHIPPING": "unshipped",
    "AWAITING_COLLECTION": "shipped",
    "IN_TRANSIT": "shipped",
    "DELIVERED": "delivered",
    "COMPLETED": "delivered",
    "CANCELLED": "cancelled",
}


def sign(path: str, params: dict, body: str, app_secret: str) -> str:
    """TikTok Shop API 请求签名。"""
    keys = sorted(k for k in params if k not in ("sign", "access_token"))
    base = path + "".join(f"{k}{params[k]}" for k in keys) + (body or "")
    wrapped = f"{app_secret}{base}{app_secret}"
    return hmac.new(app_secret.encode(), wrapped.encode(), hashlib.sha256).hexdigest()


def _ts(value) -> datetime | None:
    if value in (None, "", 0):
        return None
    return datetime.fromtimestamp(int(value), tz=UTC)


def _dec(value) -> Decimal:
    return Decimal(str(value or 0))


class TikTokConnector(PlatformConnector):
    platform = "tiktok"
    capabilities = frozenset({ORDERS, LISTINGS})
    credential_fields = [
        ("app_key", "App Key", False),
        ("app_secret", "App Secret", True),
        ("access_token", "Access Token", True),
        ("refresh_token", "Refresh Token", True),
        ("shop_cipher", "Shop Cipher（可选，留空自动获取）", False),
        ("shipping_provider_id", "默认物流商 ID（回传运单号用，可选）", False),
    ]
    page_size = 50

    def __init__(self, shop, credentials, client=None):
        super().__init__(shop, credentials, client)
        for key in ("app_key", "app_secret", "access_token"):
            if not self.credentials.get(key):
                raise ConnectorError(f"缺少 TikTok Shop 授权字段 {key}", auth=True)
        self.base = (self.credentials.get("endpoint") or API_BASE).rstrip("/")
        self._refreshed = False

    # ------------------------------------------------------------ 认证 / 签名
    def _persist_credentials(self) -> None:
        """刷新后的 token 写回店铺（由同步服务统一提交事务）。"""
        if hasattr(self.shop, "credentials_enc"):
            from app.core.security import encrypt_json

            self.shop.credentials_enc = encrypt_json(self.credentials)

    def refresh_access_token(self) -> None:
        rt = self.credentials.get("refresh_token")
        if not rt:
            raise ConnectorError("TikTok Shop access_token 已过期且未配置 refresh_token，请重新授权", auth=True)
        resp = self.request("GET", f"{AUTH_BASE}/api/v2/token/refresh", params={
            "app_key": self.credentials["app_key"], "app_secret": self.credentials["app_secret"],
            "refresh_token": rt, "grant_type": "refresh_token",
        })
        payload = resp.json()
        data = payload.get("data") or {}
        if payload.get("code") not in (0, None) or not data.get("access_token"):
            raise ConnectorError(f"刷新 TikTok Shop token 失败: {payload.get('message')}", auth=True)
        self.credentials.update(access_token=data["access_token"], refresh_token=data.get("refresh_token") or rt,
                                access_token_expire_at=data.get("access_token_expire_in"))
        self._persist_credentials()

    def call(self, method: str, path: str, *, params: dict | None = None, body: dict | None = None,
             shop_scoped: bool = True) -> dict:
        expire_at = self.credentials.get("access_token_expire_at")
        if expire_at and int(expire_at) < time.time() + 60 and not self._refreshed:
            self._refreshed = True
            self.refresh_access_token()
        query: dict = OrderedDict(params or {})
        query["app_key"] = self.credentials["app_key"]
        query["timestamp"] = str(int(time.time()))
        if shop_scoped:
            query["shop_cipher"] = self.shop_cipher()
        raw = json.dumps(body, separators=(",", ":")) if body is not None else ""
        query["sign"] = sign(path, query, raw, self.credentials["app_secret"])
        headers = {"x-tts-access-token": self.credentials["access_token"], "content-type": "application/json"}
        resp = self.request(method, self.base + path, params=query, headers=headers, content=raw or None)
        payload = resp.json()
        code = payload.get("code", 0)
        if code == 0:
            return payload.get("data") or {}
        if code in EXPIRED_TOKEN and not self._refreshed:
            self._refreshed = True
            self.refresh_access_token()
            return self.call(method, path, params=params, body=body, shop_scoped=shop_scoped)
        raise ConnectorError(f"TikTok Shop 接口错误 {code}: {payload.get('message')}", auth=code in AUTH_ERRORS)

    def shop_cipher(self) -> str:
        cipher = self.credentials.get("shop_cipher")
        if cipher:
            return cipher
        shops = self.call("GET", "/authorization/202309/shops", shop_scoped=False).get("shops") or []
        if not shops:
            raise ConnectorError("该授权下没有可用的 TikTok 店铺", auth=True)
        region = (getattr(self.shop, "country", None) or "").upper()
        chosen = next((s for s in shops if (s.get("region") or "").upper() == region), shops[0])
        self.credentials["shop_cipher"] = chosen["cipher"]
        self._persist_credentials()
        return chosen["cipher"]

    def test_connection(self) -> dict:
        shops = self.call("GET", "/authorization/202309/shops", shop_scoped=False).get("shops") or []
        return {"ok": True, "shops": [s.get("name") for s in shops]}

    # ------------------------------------------------------------ 订单
    def fetch_orders(self, updated_after: datetime) -> Iterator[OrderDTO]:
        token = None
        while True:
            params = {"page_size": self.page_size, "sort_field": "update_time", "sort_order": "ASC"}
            if token:
                params["page_token"] = token
            data = self.call("POST", "/order/202309/orders/search", params=params,
                             body={"update_time_ge": int(updated_after.timestamp())})
            for o in data.get("orders") or []:
                yield self.map_order(o)
            token = data.get("next_page_token")
            if not token:
                break

    def map_order(self, o: dict) -> OrderDTO:
        pay = o.get("payment") or {}
        addr = o.get("recipient_address") or {}
        districts = {d.get("address_level_name", "").lower(): d.get("address_name") for d in addr.get("district_info") or []}
        currency = pay.get("currency") or getattr(self.shop, "currency", None) or "USD"
        # 202309 版本每件商品一条 line_item，按 SKU 合并
        lines: OrderedDict[str, dict] = OrderedDict()
        tracking = carrier = None
        for li in o.get("line_items") or []:
            sku = li.get("seller_sku") or li.get("sku_id") or str(li.get("id"))
            ln = lines.setdefault(sku, {"qty": 0, "amount": Decimal(0), "discount": Decimal(0), "title": None, "ids": []})
            ln["qty"] += 1
            ln["amount"] += _dec(li.get("original_price") or li.get("sale_price"))
            ln["discount"] += _dec(li.get("seller_discount")) + _dec(li.get("platform_discount"))
            ln["title"] = " ".join(x for x in (li.get("product_name"), li.get("sku_name")) if x) or None
            ln["ids"].append(str(li.get("id")))
            tracking = li.get("tracking_number") or tracking
            carrier = li.get("shipping_provider_name") or carrier
        shipping = _dec(pay.get("shipping_fee"))
        tax = _dec(pay.get("tax")) + _dec(pay.get("product_tax")) + _dec(pay.get("shipping_fee_tax"))
        items = [
            OrderItemDTO(msku=sku, quantity=ln["qty"], item_amount=ln["amount"], discount_amount=ln["discount"],
                         shipping_amount=shipping if idx == 0 else Decimal(0), tax_amount=tax if idx == 0 else Decimal(0),
                         title=ln["title"], platform_item_id=sku[:64])
            for idx, (sku, ln) in enumerate(lines.items())
        ]
        return OrderDTO(
            platform_order_id=str(o.get("id")),
            fulfillment="FBA" if o.get("fulfillment_type") == "FULFILLMENT_BY_TIKTOK" else "FBM",
            platform_status=o.get("status"),
            status=STATUS_MAP.get(o.get("status") or "", "unshipped"),
            purchase_at=_ts(o.get("create_time")) or datetime.now(UTC),
            paid_at=_ts(o.get("paid_time")),
            latest_ship_at=_ts(o.get("shipping_due_time")),
            shipped_at=_ts(o.get("rts_time")),
            currency=currency,
            buyer_name=addr.get("name"),
            buyer_email=o.get("buyer_email"),
            ship_name=addr.get("name"),
            ship_phone=addr.get("phone_number"),
            ship_country=addr.get("region_code"),
            ship_state=districts.get("state") or districts.get("province") or districts.get("county"),
            ship_city=districts.get("city"),
            ship_address1=addr.get("address_line1") or addr.get("full_address"),
            ship_address2=addr.get("address_line2"),
            ship_postcode=addr.get("postal_code"),
            buyer_note=o.get("buyer_message"),
            carrier=carrier or o.get("shipping_provider"),
            tracking_no=tracking or o.get("tracking_number"),
            items=items,
        )

    def confirm_shipment(self, order) -> None:
        provider = self.credentials.get("shipping_provider_id")
        if not provider:
            raise ConnectorError("未配置 TikTok 物流商 ID（shipping_provider_id），无法回传运单号")
        detail = self.call("GET", "/order/202309/orders", params={"ids": order.platform_order_id}).get("orders") or []
        if not detail:
            raise ConnectorError(f"TikTok 订单不存在：{order.platform_order_id}")
        line_ids = [str(li["id"]) for li in detail[0].get("line_items") or [] if li.get("id")]
        self.call("POST", f"/fulfillment/202309/orders/{order.platform_order_id}/packages", body={
            "order_line_item_ids": line_ids, "tracking_number": order.tracking_no, "shipping_provider_id": provider,
        })

    # ------------------------------------------------------------ 商品
    def fetch_listings(self) -> Iterator[ListingDTO]:
        token = None
        while True:
            params = {"page_size": 100}
            if token:
                params["page_token"] = token
            data = self.call("POST", "/product/202309/products/search", params=params, body={})
            for p in data.get("products") or []:
                active = p.get("status") in ("ACTIVATE", "LIVE", None)
                for s in p.get("skus") or []:
                    price = s.get("price") or {}
                    qty = sum(int(i.get("quantity") or 0) for i in s.get("inventory") or [])
                    yield ListingDTO(
                        msku=s.get("seller_sku") or str(s.get("id")),
                        asin=str(s.get("id")),
                        parent_asin=str(p.get("id")),
                        title=p.get("title"),
                        price=_dec(price.get("sale_price") or price.get("tax_exclusive_price")),
                        currency=price.get("currency") or getattr(self.shop, "currency", None),
                        status="active" if active else "inactive",
                        fulfillment="FBM",
                        quantity=qty,
                    )
            token = data.get("next_page_token")
            if not token:
                break
