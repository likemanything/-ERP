from tests.conftest import Api, register


def test_register_login_me(client):
    api = register(client)
    me = api.get("/auth/me")
    assert me["user"]["username"] == "admin"
    assert me["user"]["is_superuser"] is True
    assert "purchase:order:approve" in me["permissions"]
    assert me["tenant"]["base_currency"] == "CNY"

    tokens = Api(client).post("/auth/login", {"username": "admin", "password": "admin123"})
    assert tokens["access_token"]
    Api(client).post("/auth/login", {"username": "admin", "password": "wrong"}, expect=401)

    refreshed = Api(client).post("/auth/refresh", {"refresh_token": tokens["refresh_token"]})
    assert Api(client, refreshed["access_token"]).get("/auth/me")["user"]["username"] == "admin"


def test_unauthenticated_and_bad_token(client):
    Api(client).get("/products", expect=401)
    Api(client, "garbage").get("/products", expect=401)


def test_duplicate_username_rejected(client):
    register(client)
    resp = client.post("/api/v1/auth/register", json={"company_name": "另一家", "username": "admin", "password": "x123456"})
    assert resp.status_code == 409


def test_tenant_isolation(client):
    a = register(client, "A公司", "alice", "alice123")
    b = register(client, "B公司", "bob", "bob12345")
    pa = a.post("/products", {"sku": "SAME-SKU", "name": "A的产品"})
    # 不同企业可使用相同 SKU
    pb = b.post("/products", {"sku": "SAME-SKU", "name": "B的产品"})
    assert pa["id"] != pb["id"]
    assert [p["name"] for p in a.get("/products")["items"]] == ["A的产品"]
    assert [p["name"] for p in b.get("/products")["items"]] == ["B的产品"]
    # 无法读取/修改/删除其他企业数据
    b.get(f"/products/{pa['id']}", expect=404)
    b.put(f"/products/{pa['id']}", {"name": "hack"}, expect=404)
    b.delete(f"/products/{pa['id']}", expect=404)
    # 计数类查询（分页 total）同样隔离
    assert a.get("/products")["total"] == 1
    # 仓库：各自只有默认仓
    assert a.get("/warehouses")["total"] == 1
    assert b.get("/warehouses")["total"] == 1


def test_rbac_and_user_management(client):
    admin = register(client)
    roles = {r["code"]: r for r in admin.get("/system/roles")}
    assert {"operator", "purchaser", "warehouse", "finance"} <= roles.keys()
    user = admin.post(
        "/system/users",
        {"username": "buyer1", "password": "buyer123", "real_name": "采购小王", "role_ids": [roles["purchaser"]["id"]]},
    )
    assert user["roles"][0]["code"] == "purchaser"
    buyer = Api(client, Api(client).post("/auth/login", {"username": "buyer1", "password": "buyer123"})["access_token"])
    me = buyer.get("/auth/me")
    assert "purchase:order:edit" in me["permissions"]
    assert "system:user" not in me["permissions"]
    buyer.get("/suppliers")
    buyer.get("/system/users", expect=403)
    buyer.post("/shops", {"name": "x", "platform": "amazon"}, expect=403)

    # 禁用后旧 token 失效
    admin.put(f"/system/users/{user['id']}", {"is_active": False})
    buyer.get("/suppliers", expect=401)

    # 自定义角色
    role = admin.post("/system/roles", {"code": "viewer", "name": "只读", "permissions": ["product:view"]})
    admin.post("/system/roles", {"code": "bad", "name": "坏", "permissions": ["no:such"]}, expect=422)
    admin.put(f"/system/roles/{role['id']}", {"permissions": ["product:view", "inventory:view"]})
    logs = admin.get("/system/audit-logs")
    assert logs["total"] >= 3


def test_shop_data_scope(client, ):
    admin = register(client)
    s1 = admin.post("/shops", {"name": "US店", "platform": "amazon", "marketplace_code": "AMAZON_US"})
    s2 = admin.post("/shops", {"name": "UK店", "platform": "amazon", "marketplace_code": "AMAZON_UK"})
    assert s1["currency"] == "USD" and s2["currency"] == "GBP"
    op_role = next(r for r in admin.get("/system/roles") if r["code"] == "operator")
    admin.post("/system/users", {"username": "op1", "password": "op12345", "role_ids": [op_role["id"]],
                                 "all_shops": False, "shop_ids": [s1["id"]]})
    op = Api(client, Api(client).post("/auth/login", {"username": "op1", "password": "op12345"})["access_token"])
    shops = op.get("/shops")["items"]
    assert [s["name"] for s in shops] == ["US店"]
    op.get(f"/shops/{s2['id']}", expect=403)
    # 亚马逊店铺自动创建 FBA 虚拟仓
    fba = admin.get("/warehouses?warehouse_type=fba")["items"]
    assert len(fba) == 2


def test_change_password_invalidates_token(client):
    api = register(client)
    api.post("/auth/change-password", {"old_password": "admin123", "new_password": "newpass1"})
    api.get("/auth/me", expect=401)
    Api(client).post("/auth/login", {"username": "admin", "password": "newpass1"})


def test_settings_and_rates(api):
    items = {s["key"]: s for s in api.get("/system/settings")}
    assert items["purchase.require_approval"]["value"] is True
    api.put("/system/settings", {"values": {"purchase.require_approval": False}})
    items = {s["key"]: s for s in api.get("/system/settings")}
    assert items["purchase.require_approval"]["value"] is False
    api.put("/system/settings", {"values": {"nope": 1}}, expect=422)
    rates = api.get("/system/exchange-rates?currency=USD")["items"]
    assert rates and rates[0]["rate"] > 0
    api.post("/system/exchange-rates", {"currency": "usd", "month": "2026-01", "rate": 7.2})
    api.post("/system/exchange-rates", {"currency": "USD", "month": "2026-01", "rate": 7.3}, expect=409)
