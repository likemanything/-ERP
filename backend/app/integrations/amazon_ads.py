"""Amazon Advertising API（广告数据）。

与 SP-API 共用 LWA 认证，但需要单独的广告授权：refresh_token 需包含 advertising::campaign_management 权限；
广告应用可以与 SP-API 应用相同（填写 ads_client_id / ads_client_secret 时优先使用）。

数据：Sponsored Products 推广商品日报（reporting v3，spAdvertisedProduct），按日期 × 广告活动 × 广告组 × SKU，
写入广告分析模块，参与 ACoS / TACoS 与利润计算。
"""

from __future__ import annotations

import gzip
import json
import time
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal

from app.integrations.base import ConnectorError, PlatformConnector
from app.integrations.dto import AdMetricDTO

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
ADS_ENDPOINTS = {
    "NA": "https://advertising-api.amazon.com",
    "EU": "https://advertising-api-eu.amazon.com",
    "FE": "https://advertising-api-fe.amazon.com",
}
SP_COLUMNS = [
    "date", "campaignId", "campaignName", "adGroupName", "advertisedSku", "advertisedAsin", "impressions", "clicks",
    "cost", "sales7d", "purchases7d", "unitsSoldClicks7d", "campaignBudgetCurrencyCode",
]
MAX_RANGE_DAYS = 31


class AmazonAdsClient:
    """挂在 AmazonConnector 上使用，复用其 HTTP 客户端与重试逻辑。"""

    poll_interval = 10.0
    poll_timeout = 900.0

    def __init__(self, conn: PlatformConnector, marketplace):
        self.conn = conn
        self.marketplace = marketplace
        creds = conn.credentials
        self.client_id = creds.get("ads_client_id") or creds.get("client_id")
        self.client_secret = creds.get("ads_client_secret") or creds.get("client_secret")
        self.refresh_token = creds.get("ads_refresh_token")
        self.profile_id = str(creds.get("ads_profile_id") or "") or None
        self.endpoint = creds.get("ads_endpoint") or ADS_ENDPOINTS.get(marketplace.region, ADS_ENDPOINTS["NA"])
        self._token: str | None = None
        self._token_expire = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.refresh_token and self.client_id and self.client_secret)

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expire - 60:
            return self._token
        if not self.configured:
            raise ConnectorError("未配置广告授权（ads_refresh_token）", auth=True)
        data = self.conn.request("POST", LWA_TOKEN_URL, data={
            "grant_type": "refresh_token", "refresh_token": self.refresh_token,
            "client_id": self.client_id, "client_secret": self.client_secret,
        }).json()
        if "access_token" not in data:
            raise ConnectorError(f"获取广告 access_token 失败: {data}", auth=True)
        self._token = data["access_token"]
        self._token_expire = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def _headers(self, scope: bool = True, **extra) -> dict:
        h = {"Amazon-Advertising-API-ClientId": self.client_id, "Authorization": f"Bearer {self._access_token()}"}
        if scope:
            h["Amazon-Advertising-API-Scope"] = self.resolve_profile()
        h.update(extra)
        return h

    def profiles(self) -> list[dict]:
        return self.conn.request("GET", f"{self.endpoint}/v2/profiles", headers=self._headers(scope=False)).json()

    def resolve_profile(self) -> str:
        """未指定 profile 时按站点自动匹配卖家账户的广告 profile。"""
        if self.profile_id:
            return self.profile_id
        for p in self.profiles():
            info = p.get("accountInfo") or {}
            if info.get("marketplaceStringId") == self.marketplace.platform_id or p.get("countryCode") == self.marketplace.country:
                self.profile_id = str(p["profileId"])
                return self.profile_id
        raise ConnectorError(f"广告账户中没有 {self.marketplace.name} 站点的 profile")

    def _report(self, start: date, end: date) -> list[dict]:
        body = {
            "name": f"ERP SP {start}~{end}",
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "configuration": {
                "adProduct": "SPONSORED_PRODUCTS", "groupBy": ["advertiser"], "columns": SP_COLUMNS,
                "reportTypeId": "spAdvertisedProduct", "timeUnit": "DAILY", "format": "GZIP_JSON",
            },
        }
        created = self.conn.request(
            "POST", f"{self.endpoint}/reporting/reports", json=body,
            headers=self._headers(**{"Content-Type": "application/vnd.createasyncreportrequest.v3+json"}),
        ).json()
        report_id = created.get("reportId")
        if not report_id:
            raise ConnectorError(f"创建广告报告失败: {created}")
        waited = 0.0
        while True:
            info = self.conn.request("GET", f"{self.endpoint}/reporting/reports/{report_id}", headers=self._headers()).json()
            status = info.get("status")
            if status == "COMPLETED" and info.get("url"):
                raw = self.conn.request("GET", info["url"]).content  # 预签名下载地址，无需认证头
                if raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                return json.loads(raw or b"[]")
            if status == "FAILURE":
                raise ConnectorError(f"广告报告生成失败: {info.get('failureReason')}")
            if waited >= self.poll_timeout:
                raise ConnectorError("广告报告生成超时，请稍后重试", retryable=True)
            time.sleep(self.poll_interval)
            waited += self.poll_interval

    def fetch_metrics(self, start: date, end: date) -> Iterator[AdMetricDTO]:
        cur = start
        while cur <= end:
            chunk_end = min(end, cur + timedelta(days=MAX_RANGE_DAYS - 1))
            for r in self._report(cur, chunk_end):
                yield AdMetricDTO(
                    metric_date=date.fromisoformat(str(r.get("date"))[:10]),
                    campaign_id=str(r.get("campaignId")),
                    campaign_name=r.get("campaignName"),
                    ad_group=r.get("adGroupName") or "",
                    ad_type="SP",
                    msku=r.get("advertisedSku") or "",
                    asin=r.get("advertisedAsin"),
                    impressions=int(r.get("impressions") or 0),
                    clicks=int(r.get("clicks") or 0),
                    spend=Decimal(str(r.get("cost") or 0)),
                    sales=Decimal(str(r.get("sales7d") or 0)),
                    orders=int(r.get("purchases7d") or 0),
                    units=int(r.get("unitsSoldClicks7d") or 0),
                    currency=r.get("campaignBudgetCurrencyCode") or self.marketplace.currency,
                )
            cur = chunk_end + timedelta(days=1)
