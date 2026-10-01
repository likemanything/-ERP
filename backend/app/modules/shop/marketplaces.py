"""平台站点参考数据（静态）。"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Marketplace:
    code: str
    platform: str
    country: str
    name: str
    currency: str
    region: str
    timezone: str
    platform_id: str | None = None  # 例如 Amazon MarketplaceId
    domain: str | None = None


_AMZ = [
    ("US", "美国站", "USD", "NA", "America/Los_Angeles", "ATVPDKIKX0DER", "amazon.com"),
    ("CA", "加拿大站", "CAD", "NA", "America/Los_Angeles", "A2EUQ1WTGCTBG2", "amazon.ca"),
    ("MX", "墨西哥站", "MXN", "NA", "America/Los_Angeles", "A1AM78C64UM0Y8", "amazon.com.mx"),
    ("BR", "巴西站", "BRL", "NA", "America/Sao_Paulo", "A2Q3Y263D00KWC", "amazon.com.br"),
    ("UK", "英国站", "GBP", "EU", "Europe/London", "A1F83G8C2ARO7P", "amazon.co.uk"),
    ("DE", "德国站", "EUR", "EU", "Europe/Paris", "A1PA6795UKMFR9", "amazon.de"),
    ("FR", "法国站", "EUR", "EU", "Europe/Paris", "A13V1IB3VIYZZH", "amazon.fr"),
    ("IT", "意大利站", "EUR", "EU", "Europe/Paris", "APJ6JRA9NG5V4", "amazon.it"),
    ("ES", "西班牙站", "EUR", "EU", "Europe/Paris", "A1RKKUPIHCS9HS", "amazon.es"),
    ("NL", "荷兰站", "EUR", "EU", "Europe/Paris", "A1805IZSGTT6HS", "amazon.nl"),
    ("SE", "瑞典站", "SEK", "EU", "Europe/Paris", "A2NODRKZP88ZB9", "amazon.se"),
    ("PL", "波兰站", "PLN", "EU", "Europe/Paris", "A1C3SOZRARQ6R3", "amazon.pl"),
    ("BE", "比利时站", "EUR", "EU", "Europe/Paris", "AMEN7PMS3EDWL", "amazon.com.be"),
    ("TR", "土耳其站", "TRY", "EU", "Europe/Istanbul", "A33AVAJ2PDY3EV", "amazon.com.tr"),
    ("AE", "阿联酋站", "AED", "EU", "Asia/Dubai", "A2VIGQ35RCS4UG", "amazon.ae"),
    ("SA", "沙特站", "SAR", "EU", "Asia/Riyadh", "A17E79C6D8DWNP", "amazon.sa"),
    ("IN", "印度站", "INR", "EU", "Asia/Kolkata", "A21TJRUUN4KGV", "amazon.in"),
    ("JP", "日本站", "JPY", "FE", "Asia/Tokyo", "A1VC38T7YXB528", "amazon.co.jp"),
    ("AU", "澳洲站", "AUD", "FE", "Australia/Sydney", "A39IBJ37TRP1C6", "amazon.com.au"),
    ("SG", "新加坡站", "SGD", "FE", "Asia/Singapore", "A19VAU5U5O7RUS", "amazon.sg"),
]

MARKETPLACES: dict[str, Marketplace] = {}
for c, n, cur, reg, tz, mid, dom in _AMZ:
    MARKETPLACES[f"AMAZON_{c}"] = Marketplace(f"AMAZON_{c}", "amazon", c, f"亚马逊{n}", cur, reg, tz, mid, dom)

for code, platform, country, name, cur, region, tz in [
    ("WALMART_US", "walmart", "US", "沃尔玛美国", "USD", "NA", "America/Los_Angeles"),
    ("WALMART_CA", "walmart", "CA", "沃尔玛加拿大", "CAD", "NA", "America/Los_Angeles"),
    ("EBAY_US", "ebay", "US", "eBay 美国", "USD", "NA", "America/Los_Angeles"),
    ("EBAY_UK", "ebay", "UK", "eBay 英国", "GBP", "EU", "Europe/London"),
    ("EBAY_DE", "ebay", "DE", "eBay 德国", "EUR", "EU", "Europe/Paris"),
    ("TIKTOK_US", "tiktok", "US", "TikTok Shop 美国", "USD", "NA", "America/Los_Angeles"),
    ("TIKTOK_UK", "tiktok", "UK", "TikTok Shop 英国", "GBP", "EU", "Europe/London"),
    ("TEMU_US", "temu", "US", "Temu 美国", "USD", "NA", "America/Los_Angeles"),
    ("SHEIN_US", "shein", "US", "SHEIN 美国", "USD", "NA", "America/Los_Angeles"),
    ("ALIEXPRESS_GLOBAL", "aliexpress", "GLOBAL", "速卖通", "USD", "GLOBAL", "Asia/Shanghai"),
    ("SHOPIFY_GLOBAL", "shopify", "GLOBAL", "Shopify 独立站", "USD", "GLOBAL", "UTC"),
    ("MANUAL_GLOBAL", "manual", "GLOBAL", "线下/其他渠道", "CNY", "GLOBAL", "Asia/Shanghai"),
]:
    MARKETPLACES[code] = Marketplace(code, platform, country, name, cur, region, tz)


def get_marketplace(code: str | None) -> Marketplace | None:
    return MARKETPLACES.get(code or "")


def marketplace_by_platform_id(platform_id: str) -> Marketplace | None:
    for m in MARKETPLACES.values():
        if m.platform_id == platform_id:
            return m
    return None


def list_marketplaces(platform: str | None = None) -> list[dict]:
    return [asdict(m) for m in MARKETPLACES.values() if platform is None or m.platform == platform]


# 常用币种（汇率维护用）
CURRENCIES: dict[str, str] = {
    "CNY": "人民币", "USD": "美元", "EUR": "欧元", "GBP": "英镑", "JPY": "日元", "CAD": "加元",
    "MXN": "墨西哥比索", "AUD": "澳元", "BRL": "巴西雷亚尔", "SEK": "瑞典克朗", "PLN": "波兰兹罗提",
    "TRY": "土耳其里拉", "AED": "阿联酋迪拉姆", "SAR": "沙特里亚尔", "INR": "印度卢比", "SGD": "新加坡元",
    "HKD": "港币",
}

# 新企业默认汇率（兑人民币，参考值，用户需按月维护）
DEFAULT_RATES_TO_CNY: dict[str, str] = {
    "USD": "7.10", "EUR": "7.80", "GBP": "9.10", "JPY": "0.048", "CAD": "5.20", "MXN": "0.39",
    "AUD": "4.70", "BRL": "1.30", "SEK": "0.68", "PLN": "1.80", "TRY": "0.21", "AED": "1.93",
    "SAR": "1.89", "INR": "0.085", "SGD": "5.30", "HKD": "0.91",
}
