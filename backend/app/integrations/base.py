"""平台连接器抽象。

每个平台实现一个 Connector，负责把平台 API 数据转换为标准 DTO（见 dto.py），
ERP 的同步服务只依赖 DTO，与具体平台解耦。新增平台只需实现本接口并在 registry 中注册。
"""

import logging
import time
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, ClassVar

import httpx

from app.integrations.dto import AdMetricDTO, FbaInventoryDTO, ListingDTO, OrderDTO, TransactionDTO

log = logging.getLogger("erp.integrations")

ORDERS = "orders"
LISTINGS = "listings"
FBA_INVENTORY = "fba_inventory"
FINANCES = "finances"
ADS = "ads"
ALL_JOB_TYPES = (LISTINGS, ORDERS, FBA_INVENTORY, FINANCES, ADS)


class ConnectorError(Exception):
    """平台接口调用失败。auth=True 表示授权失效，需要重新授权。"""

    def __init__(self, message: str, *, auth: bool = False, retryable: bool = False):
        super().__init__(message)
        self.auth = auth
        self.retryable = retryable


class PlatformConnector:
    platform: ClassVar[str] = ""
    capabilities: ClassVar[frozenset[str]] = frozenset()
    #: 凭证字段说明，用于前端渲染授权表单 [(key, label, secret)]
    credential_fields: ClassVar[list[tuple[str, str, bool]]] = []

    def __init__(self, shop: Any, credentials: dict, client: httpx.Client | None = None):
        self.shop = shop
        self.credentials = credentials or {}
        self._client = client

    # ------------------------------------------------------------ HTTP
    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))
        return self._client

    def request(self, method: str, url: str, *, retries: int = 5, **kwargs) -> httpx.Response:
        """带限流重试的 HTTP 请求（429 / 5xx 指数退避）。"""
        delay = 1.0
        for attempt in range(retries):
            try:
                resp = self.client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                if attempt == retries - 1:
                    raise ConnectorError(f"网络错误: {exc}", retryable=True) from exc
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == retries - 1:
                    raise ConnectorError(f"平台接口繁忙（HTTP {resp.status_code}）", retryable=True)
                retry_after = resp.headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else delay)
                delay = min(delay * 2, 60)
                continue
            if resp.status_code in (401, 403):
                raise ConnectorError(f"授权失败（HTTP {resp.status_code}）: {resp.text[:300]}", auth=True)
            if resp.status_code >= 400:
                raise ConnectorError(f"平台接口错误（HTTP {resp.status_code}）: {resp.text[:300]}")
            return resp
        raise ConnectorError("请求失败")  # pragma: no cover

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    # ------------------------------------------------------------ 能力
    def supports(self, job_type: str) -> bool:
        return job_type in self.capabilities

    def test_connection(self) -> dict:
        raise NotImplementedError

    def fetch_orders(self, updated_after: datetime) -> Iterator[OrderDTO]:
        raise NotImplementedError

    def fetch_listings(self) -> Iterator[ListingDTO]:
        raise NotImplementedError

    def fetch_fba_inventory(self) -> Iterator[FbaInventoryDTO]:
        raise NotImplementedError

    def fetch_transactions(self, posted_after: datetime) -> Iterator[TransactionDTO]:
        raise NotImplementedError

    def fetch_ad_metrics(self, start: date, end: date) -> Iterator[AdMetricDTO]:
        raise NotImplementedError

    def confirm_shipment(self, order: Any) -> None:
        """自发货订单回传物流单号（可选实现）。"""
        raise NotImplementedError
