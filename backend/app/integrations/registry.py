"""连接器注册表。"""

from app.core.security import decrypt_json
from app.integrations.amazon import AmazonConnector
from app.integrations.base import ConnectorError, PlatformConnector
from app.integrations.demo import DemoConnector
from app.integrations.shopify import ShopifyConnector
from app.integrations.tiktok import TikTokConnector
from app.integrations.walmart import WalmartConnector

CONNECTORS: dict[str, type[PlatformConnector]] = {
    "amazon": AmazonConnector,
    "shopify": ShopifyConnector,
    "walmart": WalmartConnector,
    "tiktok": TikTokConnector,
}


def get_connector(shop, client=None) -> PlatformConnector:
    creds = decrypt_json(shop.credentials_enc)
    if creds.get("mode") == "demo":
        return DemoConnector(shop, creds, client)
    cls = CONNECTORS.get(shop.platform)
    if cls is None:
        raise ConnectorError(f"平台 {shop.platform} 暂未接入 API，可通过 Excel 导入订单/库存，或使用演示模式（mode=demo）")
    return cls(shop, creds, client)


def platform_capabilities() -> list[dict]:
    out = []
    for platform, cls in CONNECTORS.items():
        out.append({"platform": platform, "capabilities": sorted(cls.capabilities),
                    "credential_fields": [{"key": k, "label": label, "secret": s} for k, label, s in cls.credential_fields]})
    out.append({"platform": "demo", "capabilities": sorted(DemoConnector.capabilities),
                "credential_fields": [{"key": "mode", "label": "模式（填写 demo）", "secret": False}]})
    return out
