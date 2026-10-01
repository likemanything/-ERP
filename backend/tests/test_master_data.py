def test_product_crud_and_bundle(api, factory):
    a = factory.product(sku="A-1", purchase_cost=10)
    b = factory.product(sku="B-1", purchase_cost=5)
    api.post("/products", {"sku": "A-1", "name": "dup"}, expect=409)
    bundle = api.post(
        "/products",
        {"sku": "KIT-1", "name": "套装", "product_type": "bundle",
         "bundle_items": [{"component_id": a["id"], "quantity": 2}, {"component_id": b["id"], "quantity": 1}]},
    )
    assert bundle["purchase_cost"] == 25  # 2*10 + 5
    assert {i["component_sku"] for i in bundle["bundle_items"]} == {"A-1", "B-1"}
    # 组合品不能嵌套
    api.post("/products", {"sku": "KIT-2", "name": "x", "product_type": "bundle",
                           "bundle_items": [{"component_id": bundle["id"], "quantity": 1}]}, expect=422)
    # 被组合品引用的子产品不能删除
    api.delete(f"/products/{a['id']}", expect=409)
    upd = api.put(f"/products/{a['id']}", {"name": "改名", "status": "clearance"})
    assert upd["name"] == "改名" and upd["status"] == "clearance"
    api.put(f"/products/{a['id']}", {"status": "nonsense"}, expect=422)
    res = api.get("/products?keyword=KIT")
    assert res["total"] == 1
    opts = api.get("/products/options?keyword=B-1")
    assert opts[0]["sku"] == "B-1"


def test_product_supplier_quotes(api, factory):
    p = factory.product()
    s = factory.supplier()
    q = api.post(f"/products/{p['id']}/suppliers", {"supplier_id": s["id"], "price": 8.8, "moq": 100, "lead_days": 20, "is_default": True})
    assert q["supplier_name"] == s["name"]
    prod = api.get(f"/products/{p['id']}")
    assert prod["default_supplier_id"] == s["id"] and prod["moq"] == 100 and prod["purchase_lead_days"] == 20
    api.post(f"/products/{p['id']}/suppliers", {"supplier_id": s["id"], "price": 1}, expect=422)
    # 供应商被报价引用时不可删除
    api.delete(f"/suppliers/{s['id']}", expect=409)


def test_supplier_auto_code(api):
    s1 = api.post("/suppliers", {"name": "义乌工厂"})
    s2 = api.post("/suppliers", {"name": "深圳工厂"})
    assert s1["code"].startswith("SUP") and s1["code"] != s2["code"]
    assert api.get("/suppliers?keyword=义乌")["total"] == 1


def test_listing_pairing(api, factory):
    shop = factory.shop()
    p = factory.product(sku="PAIR-SKU")
    lst = factory.listing(shop["id"], msku="PAIR-SKU")
    assert lst["product_id"] is None
    lst2 = factory.listing(shop["id"], msku="OTHER")
    api.post(f"/listings/auto-pair?shop_id={shop['id']}")
    rows = {x["msku"]: x for x in api.get(f"/listings?shop_id={shop['id']}")["items"]}
    assert rows["PAIR-SKU"]["sku"] == "PAIR-SKU"
    assert rows["OTHER"]["product_id"] is None
    paired = api.post(f"/listings/{lst2['id']}/pair", {"product_id": p["id"], "pair_quantity": 2})
    assert paired["sku"] == "PAIR-SKU" and paired["pair_quantity"] == 2
    assert api.get("/listings?paired=false")["total"] == 0
    api.post("/listings", {"shop_id": shop["id"], "msku": "OTHER"}, expect=422)


def test_logistics_quote(api):
    prov = api.post("/logistics-providers", {"code": "DHL", "name": "DHL"})
    api.post("/logistics-channels", {"provider_id": prov["id"], "code": "AIR1", "name": "空派", "unit_price": 40,
                                     "volume_divisor": 6000, "transport_mode": "air"})
    api.post("/logistics-channels", {"provider_id": prov["id"], "code": "EXP1", "name": "快递", "billing_type": "weight",
                                     "first_weight_kg": 0.5, "first_price": 100, "extra_unit_kg": 0.5, "extra_price": 30,
                                     "volume_divisor": 5000})
    quotes = api.post("/logistics/quote", {"weight_kg": 10, "length_cm": 50, "width_cm": 40, "height_cm": 30})
    by = {q["channel_name"]: q for q in quotes}
    # 体积重 50*40*30/6000 = 10 → 计费重 10 → 400
    assert by["空派"]["chargeable_weight_kg"] == 10 and by["空派"]["freight"] == 400
    # 体积重 /5000 = 12 → 首重 0.5 + 续重 23 * 30 = 790
    assert by["快递"]["chargeable_weight_kg"] == 12 and by["快递"]["freight"] == 790
    assert quotes[0]["channel_name"] == "空派"  # 按价格排序
