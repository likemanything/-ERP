import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="erp-test-")
os.environ.setdefault("ERP_DATABASE_URL", os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db"))
os.environ.setdefault("ERP_SECRET_KEY", "test-secret-key-for-unit-tests-only-0123456789")
os.environ["ERP_ENV"] = "test"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402, F401
from app.core.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


class Api:
    """测试用 HTTP 封装：自动带上 token，并断言状态码。"""

    def __init__(self, client: TestClient, token: str | None = None):
        self.client = client
        self.token = token

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _call(self, method, url, expect=200, **kwargs):
        resp = self.client.request(method, "/api/v1" + url, headers=self.headers, **kwargs)
        if expect is not None:
            assert resp.status_code == expect, f"{method} {url} -> {resp.status_code}: {resp.text}"
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp

    def get(self, url, expect=200, **kw):
        return self._call("GET", url, expect, **kw)

    def post(self, url, json=None, expect=200, **kw):
        return self._call("POST", url, expect, json=json, **kw)

    def put(self, url, json=None, expect=200, **kw):
        return self._call("PUT", url, expect, json=json, **kw)

    def delete(self, url, expect=200, **kw):
        return self._call("DELETE", url, expect, **kw)


@pytest.fixture(autouse=True)
def _db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def register(client: TestClient, company="测试公司", username="admin", password="admin123") -> Api:
    resp = client.post(
        "/api/v1/auth/register",
        json={"company_name": company, "username": username, "password": password, "real_name": "管理员"},
    )
    assert resp.status_code == 200, resp.text
    return Api(client, resp.json()["access_token"])


@pytest.fixture
def api(client) -> Api:
    return register(client)


@pytest.fixture
def factory(api):
    return Factory(api)


class Factory:
    """快速创建测试基础数据。"""

    def __init__(self, api: Api):
        self.api = api
        self._n = 0

    def _next(self):
        self._n += 1
        return self._n

    def warehouse(self, **kw):
        n = self._next()
        data = {"code": f"WH-T{n}", "name": f"测试仓{n}", "warehouse_type": "local"}
        data.update(kw)
        return self.api.post("/warehouses", data)

    def default_warehouse(self):
        items = self.api.get("/warehouses?warehouse_type=local")["items"]
        return next(w for w in items if w["is_default"])

    def product(self, **kw):
        n = self._next()
        data = {"sku": f"SKU-{n:03d}", "name": f"产品{n}", "purchase_cost": 10, "weight_kg": 0.5,
                "length_cm": 20, "width_cm": 10, "height_cm": 5}
        data.update(kw)
        return self.api.post("/products", data)

    def supplier(self, **kw):
        n = self._next()
        data = {"name": f"供应商{n}"}
        data.update(kw)
        return self.api.post("/suppliers", data)

    def shop(self, **kw):
        n = self._next()
        data = {"name": f"店铺{n}", "platform": "amazon", "marketplace_code": "AMAZON_US"}
        data.update(kw)
        return self.api.post("/shops", data)

    def listing(self, shop_id, product_id=None, **kw):
        n = self._next()
        data = {"shop_id": shop_id, "msku": f"MSKU-{n:03d}", "asin": f"B0TEST{n:04d}", "fnsku": f"X00TEST{n:03d}",
                "price": 29.99, "product_id": product_id}
        data.update(kw)
        return self.api.post("/listings", data)

    def stock_in(self, warehouse_id, product_id, qty, unit_cost=None):
        line = {"product_id": product_id, "qty": qty}
        if unit_cost is not None:
            line["unit_cost"] = unit_cost
        doc = self.api.post("/stock-documents", {"doc_type": "in", "warehouse_id": warehouse_id, "lines": [line]})
        return self.api.post(f"/stock-documents/{doc['id']}/approve")

    def inventory(self, warehouse_id, product_id):
        rows = self.api.get(f"/inventory?warehouse_id={warehouse_id}&in_stock_only=false&page_size=500")["items"]
        return next((r for r in rows if r["product_id"] == product_id), None)
