"""演示连接器：为任意平台生成确定性的模拟数据（店铺授权凭证填写 mode=demo 时启用）。

用于试用、培训与自动化测试：无需真实平台账号即可体验 订单同步 → 成本核算 → 补货 → 利润 的完整链路。
同一店铺、同一天生成的数据完全一致，重复同步是幂等的。
"""

import random
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.integrations.base import ADS, FBA_INVENTORY, FINANCES, LISTINGS, ORDERS, PlatformConnector
from app.integrations.dto import (
    AdMetricDTO,
    FbaInventoryDTO,
    ListingDTO,
    OrderDTO,
    OrderItemDTO,
    TransactionDTO,
)

CATALOG = [
    ("LAMP-01", "LED Desk Lamp with USB Charging Port", "29.99", "FBA", 6.0),
    ("MAT-02", "Non Slip Yoga Mat 6mm", "24.99", "FBA", 4.5),
    ("BOTTLE-03", "Insulated Water Bottle 32oz", "19.99", "FBA", 9.0),
    ("CABLE-04", "USB-C Cable 6ft 2-Pack", "12.99", "FBA", 12.0),
    ("STAND-05", "Adjustable Laptop Stand Aluminum", "35.99", "FBA", 3.0),
    ("BAG-06", "Waterproof Travel Backpack", "45.99", "FBM", 1.5),
    ("CASE-07", "Shockproof Phone Case", "15.99", "FBA", 7.0),
    ("TOWEL-08", "Microfiber Cleaning Towels 12pk", "16.99", "FBM", 2.0),
]
NAMES = ["James Smith", "Mary Johnson", "Robert Brown", "Linda Davis", "Michael Wilson", "Sarah Miller", "David Moore"]
STATES = [("CA", "Los Angeles", "90001"), ("NY", "New York", "10001"), ("TX", "Houston", "77001"), ("WA", "Seattle", "98101")]
MAX_DAYS = 60


class DemoConnector(PlatformConnector):
    platform = "demo"
    capabilities = frozenset({ORDERS, LISTINGS, FBA_INVENTORY, FINANCES, ADS})
    credential_fields = [("mode", "模式（填写 demo）", False)]

    def _currency(self) -> str:
        return self.shop.currency or "USD"

    def _msku(self, code: str) -> str:
        return f"{code}-S{self.shop.id}"

    def _rng(self, *parts) -> random.Random:
        return random.Random("|".join(str(p) for p in (self.shop.id, *parts)))

    def test_connection(self) -> dict:
        return {"ok": True, "mode": "demo"}

    def fetch_listings(self) -> Iterator[ListingDTO]:
        for idx, (code, title, price, ful, _) in enumerate(CATALOG):
            rng = self._rng("listing", code)
            yield ListingDTO(
                msku=self._msku(code),
                asin=f"B0DEMO{self.shop.id:02d}{idx:02d}",
                fnsku=f"X00DEMO{self.shop.id:02d}{idx:02d}" if ful == "FBA" else None,
                title=title,
                image_url=f"https://picsum.photos/seed/{code}/120/120",
                price=Decimal(price),
                currency=self._currency(),
                status="active",
                fulfillment=ful,
                open_date=date.today() - timedelta(days=rng.randint(90, 600)),
            )

    def _orders_for_day(self, day: date) -> list[OrderDTO]:
        rng = self._rng("orders", day.isoformat())
        today = datetime.now(UTC).date()
        orders = []
        weekday_boost = 1.2 if day.weekday() >= 5 else 1.0
        for idx, (code, title, price, ful, velocity) in enumerate(CATALOG):
            n = rng.choices([0, 1, 2, 3], weights=[1, 2, 2, 1])[0] if velocity < 3 else int(rng.gauss(velocity * weekday_boost / 3, 1))
            for k in range(max(0, n)):
                qty = rng.choices([1, 2, 3], weights=[85, 12, 3])[0]
                purchase_at = datetime(day.year, day.month, day.day, rng.randint(0, 23), rng.randint(0, 59), tzinfo=UTC)
                age = (today - day).days
                roll = rng.random()
                if roll < 0.03:
                    status = "cancelled"
                elif ful == "FBA":
                    status = "shipped" if age >= 1 else rng.choice(["pending", "unshipped", "shipped"])
                else:
                    status = "shipped" if age >= 3 else "unshipped"
                name = rng.choice(NAMES)
                state, city, zipc = rng.choice(STATES)
                unit = Decimal(price)
                discount = Decimal("2.00") * qty if rng.random() < 0.1 else Decimal(0)
                orders.append(OrderDTO(
                    platform_order_id=f"D{self.shop.id}-{day:%y%m%d}-{idx}{k:02d}",
                    fulfillment=ful,
                    platform_status=status,
                    status=status,
                    purchase_at=purchase_at,
                    shipped_at=purchase_at + timedelta(hours=20) if status == "shipped" else None,
                    currency=self._currency(),
                    buyer_name=name,
                    buyer_email=f"{name.split()[0].lower()}{rng.randint(10, 99)}@example.com",
                    ship_name=name,
                    ship_country=self.shop.country if self.shop.country not in (None, "GLOBAL") else "US",
                    ship_state=state,
                    ship_city=city,
                    ship_address1=f"{rng.randint(100, 9999)} Main St",
                    ship_postcode=zipc,
                    carrier="USPS" if status == "shipped" and ful == "FBM" else None,
                    tracking_no=f"9400{rng.randint(10**15, 10**16 - 1)}" if status == "shipped" and ful == "FBM" else None,
                    items=[OrderItemDTO(
                        msku=self._msku(code), asin=f"B0DEMO{self.shop.id:02d}{idx:02d}", title=title,
                        platform_item_id=f"{idx}{k:02d}", quantity=qty, item_amount=unit * qty, discount_amount=discount,
                        tax_amount=(unit * qty * Decimal("0.08")).quantize(Decimal("0.01")),
                    )],
                ))
        return orders

    def _days(self, since: datetime) -> list[date]:
        today = datetime.now(UTC).date()
        start = max(since.astimezone(UTC).date(), today - timedelta(days=MAX_DAYS))
        return [start + timedelta(days=i) for i in range((today - start).days + 1)]

    def fetch_orders(self, updated_after: datetime) -> Iterator[OrderDTO]:
        # 订单状态会随时间推进，因此回看 3 天，保证 待发货 → 已发货 的状态被更新
        for day in self._days(updated_after - timedelta(days=3)):
            yield from self._orders_for_day(day)

    def fetch_fba_inventory(self) -> Iterator[FbaInventoryDTO]:
        rng = self._rng("fba", date.today().isoformat())
        for idx, (code, _title, _price, ful, velocity) in enumerate(CATALOG):
            if ful != "FBA":
                continue
            yield FbaInventoryDTO(
                msku=self._msku(code), fnsku=f"X00DEMO{self.shop.id:02d}{idx:02d}", asin=f"B0DEMO{self.shop.id:02d}{idx:02d}",
                fulfillable=int(velocity * rng.randint(8, 50)), inbound_shipped=rng.choice([0, 0, 50, 100, 200]),
                inbound_receiving=rng.choice([0, 0, 20]), reserved=rng.randint(0, 15), unfulfillable=rng.randint(0, 3),
            )

    def fetch_transactions(self, posted_after: datetime) -> Iterator[TransactionDTO]:
        for day in self._days(posted_after):
            for o in self._orders_for_day(day):
                if o.status != "shipped":
                    continue
                for it in o.items:
                    posted = o.shipped_at or o.purchase_at
                    base = f"{o.platform_order_id}-{it.platform_item_id}"
                    commission = -(it.item_amount - it.discount_amount) * Decimal("0.15")
                    fba_fee = -Decimal("4.75") * it.quantity if o.fulfillment == "FBA" else Decimal(0)
                    for amount_type, amount in (("Principal", it.item_amount), ("Commission", commission),
                                                ("FBAPerUnitFulfillmentFee", fba_fee), ("Promotion", -it.discount_amount)):
                        if amount:
                            yield TransactionDTO(
                                external_id=f"{base}-{amount_type}", posted_at=posted, event_type="order",
                                amount_type=amount_type, amount=amount.quantize(Decimal("0.01")), currency=o.currency,
                                platform_order_id=o.platform_order_id, msku=it.msku, quantity=it.quantity,
                            )
            if day.day == 1:
                yield TransactionDTO(external_id=f"storage-{day}", posted_at=datetime(day.year, day.month, day.day, tzinfo=UTC),
                                     event_type="service_fee", amount_type="FBAStorageFee", amount=Decimal("-38.50"),
                                     currency=self._currency(), description="月度仓储费")

    def fetch_ad_metrics(self, start: date, end: date) -> Iterator[AdMetricDTO]:
        day = start
        while day <= end:
            for idx, (code, _title, price, _ful, velocity) in enumerate(CATALOG):
                rng = self._rng("ads", code, day.isoformat())
                impressions = int(velocity * rng.randint(120, 300))
                clicks = int(impressions * rng.uniform(0.003, 0.008))
                orders = sum(1 for _ in range(clicks) if rng.random() < 0.14)
                cpc = Decimal(str(round(rng.uniform(0.35, 0.95), 2)))
                yield AdMetricDTO(
                    metric_date=day, campaign_id=f"DEMO-{self.shop.id}-{idx}", campaign_name=f"SP-{code}-自动",
                    ad_group="自动投放", ad_type="SP", msku=self._msku(code), asin=f"B0DEMO{self.shop.id:02d}{idx:02d}",
                    impressions=impressions, clicks=clicks, spend=cpc * clicks, sales=Decimal(price) * orders,
                    orders=orders, units=orders, currency=self._currency(),
                )
            day += timedelta(days=1)

    def confirm_shipment(self, order) -> None:
        return None
