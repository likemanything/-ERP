"""命令行工具。

    python -m app.cli init-db                    # 执行数据库迁移
    python -m app.cli create-tenant --company 我的公司 --username admin --password ******
    python -m app.cli seed-demo                  # 创建演示企业（demo / demo123456）并生成完整演示数据
"""

import argparse
import logging
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.db import SessionLocal
from app.core.types import q2

log = logging.getLogger("erp.cli")


def init_db() -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    command.upgrade(cfg, "head")
    print("数据库迁移完成")


def create_tenant(company: str, username: str, password: str) -> None:
    from app.modules.system.service import bootstrap_tenant

    with SessionLocal() as db:
        tenant, admin = bootstrap_tenant(db, company_name=company, username=username, password=password)
        print(f"已创建企业 {tenant.name}（{tenant.code}），管理员 {admin.username}")


def _ean13(base12: str) -> str:
    """12 位数字补校验位生成 EAN-13。"""
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(base12))
    return base12 + str((10 - total % 10) % 10)


def seed_demo(username: str = "demo", password: str = "demo123456") -> None:
    """生成演示企业：主数据 + 采购入库 + 头程发货 + 平台订单/财务/广告同步。"""
    from app.core.deps import system_ctx
    from app.core.security import encrypt_json
    from app.integrations.demo import CATALOG, placeholder_image
    from app.modules.fba import service as fba
    from app.modules.finance.service import create_expense
    from app.modules.integration.service import sync_shop
    from app.modules.logistics.models import LogisticsChannel, LogisticsProvider
    from app.modules.product.models import Brand, Category, Listing, Product, ProductSupplier
    from app.modules.product.service import pair_listing
    from app.modules.purchase import service as purchase
    from app.modules.shop.models import Shop
    from app.modules.shop.router import ensure_fba_warehouse
    from app.modules.supplier.models import Supplier
    from app.modules.system.models import User
    from app.modules.system.service import bootstrap_tenant
    from app.modules.warehouse.models import Warehouse

    with SessionLocal() as db:
        exists = db.execute(select(User).where(User.username == username).execution_options(skip_tenant_filter=True)).scalar_one_or_none()
        if exists:
            print(f"用户 {username} 已存在，跳过（如需重建请先清空数据库）")
            return
        tenant, admin = bootstrap_tenant(db, company_name="云帆演示贸易有限公司", username=username, password=password,
                                         real_name="演示管理员")
        ctx = system_ctx(db, tenant.id)
        ctx.user = admin
        db.info["user_id"] = admin.id

        # 物流
        prov = LogisticsProvider(code="FWD01", name="顺丰国际货代", provider_type="forwarder", contact="王经理")
        db.add(prov)
        db.flush()
        air = LogisticsChannel(provider_id=prov.id, code="AIR-US", name="美国空派专线", usage="first_mile", transport_mode="air",
                               unit_price=Decimal("38"), volume_divisor=6000, transit_days=12)
        sea = LogisticsChannel(provider_id=prov.id, code="SEA-US", name="美森快船", usage="first_mile", transport_mode="fast_sea",
                               unit_price=Decimal("13"), volume_divisor=6000, transit_days=25)
        exp = LogisticsChannel(provider_id=prov.id, code="USPS", name="USPS 小包", usage="last_mile", transport_mode="express",
                               currency="USD", first_weight_kg=Decimal("0.5"), first_price=Decimal("4.5"),
                               extra_unit_kg=Decimal("0.5"), extra_price=Decimal("1.2"), volume_divisor=5000, transit_days=5)
        db.add_all([air, sea, exp])

        # 供应商、分类、品牌
        s1 = Supplier(code="SUP0001", name="深圳市光明电子有限公司", contact="李生", phone="13800000001", settlement_type="monthly",
                      payment_days=30, rating=4)
        s2 = Supplier(code="SUP0002", name="义乌市优品家居厂", contact="陈总", phone="13800000002", settlement_type="cash", rating=5)
        cat_el = Category(name="3C 电子")
        cat_home = Category(name="家居运动")
        brand = Brand(name="CloudSail")
        db.add_all([s1, s2, cat_el, cat_home, brand])
        db.flush()

        costs = {"LAMP-01": 42, "MAT-02": 31, "BOTTLE-03": 22, "CABLE-04": 9, "STAND-05": 58, "BAG-06": 76, "CASE-07": 11, "TOWEL-08": 18}
        specs = {"LAMP-01": (0.9, 40, 15, 10), "MAT-02": (1.2, 62, 12, 12), "BOTTLE-03": (0.45, 26, 9, 9),
                 "CABLE-04": (0.12, 15, 10, 3), "STAND-05": (1.1, 30, 25, 6), "BAG-06": (0.95, 45, 32, 15),
                 "CASE-07": (0.08, 18, 10, 2), "TOWEL-08": (0.6, 30, 20, 8)}
        products: dict[str, Product] = {}
        for code, title, _price, _ful, _vel in CATALOG:
            w, length, width, height = specs[code]
            electronic = code in ("LAMP-01", "CABLE-04", "STAND-05", "CASE-07")
            sup = s1 if electronic else s2
            p = Product(sku=code, name=title, name_en=title, category_id=(cat_el if electronic else cat_home).id, brand_id=brand.id,
                        purchase_cost=Decimal(costs[code]), default_supplier_id=sup.id, purchase_lead_days=12, moq=50,
                        weight_kg=Decimal(str(w)), length_cm=Decimal(length), width_cm=Decimal(width), height_cm=Decimal(height),
                        units_per_carton=40, declare_name_en=title[:40], declare_value_usd=Decimal("5"),
                        image_url=placeholder_image(code), barcode=_ean13(f"690123456{len(products) + 1:03d}"))
            db.add(p)
            db.flush()
            db.add(ProductSupplier(product_id=p.id, supplier_id=sup.id, price=Decimal(costs[code]), moq=50, lead_days=12, is_default=True))
            products[code] = p
        db.commit()

        # 店铺（演示模式）
        shop = Shop(name="Amazon-US 演示店", platform="amazon", marketplace_code="AMAZON_US", country="US", region="NA",
                    currency="USD", timezone="America/Los_Angeles", credentials_enc=encrypt_json({"mode": "demo"}),
                    sync_enabled=True, sync_interval_minutes=60)
        db.add(shop)
        db.flush()
        fba_wh = ensure_fba_warehouse(ctx, shop)
        db.commit()
        sync_shop(ctx, shop.id, ["listings"], trigger="manual")
        for lst in db.execute(select(Listing).where(Listing.shop_id == shop.id)).scalars().all():
            code = lst.msku.rsplit("-S", 1)[0]
            if code in products:
                pair_listing(ctx, lst, products[code].id)
        db.commit()

        # 采购：下单 → 审批 → 到货入库
        wh = db.execute(select(Warehouse).where(Warehouse.is_default.is_(True))).scalars().first()
        for sup, codes in ((s1, ["LAMP-01", "CABLE-04", "STAND-05", "CASE-07"]), (s2, ["MAT-02", "BOTTLE-03", "BAG-06", "TOWEL-08"])):
            po = purchase.create_order(ctx, {
                "supplier_id": sup.id, "warehouse_id": wh.id, "shipping_fee": Decimal("300"),
                "lines": [{"product_id": products[c].id, "qty": 600} for c in codes],
            })
            purchase.submit_order(ctx, po.id)
            purchase.approve_order(ctx, po.id)
            purchase.mark_ordered(ctx, po.id, {"supplier_order_no": f"1688-{po.id:06d}"})
            purchase.receive(ctx, po.id, {"lines": [{"order_line_id": ln.id, "qty_good": ln.qty, "qty_defective": 0} for ln in po.lines]})
        # 再下一张在途采购单
        po = purchase.create_order(ctx, {"supplier_id": s1.id, "warehouse_id": wh.id,
                                         "expected_date": date.today() + timedelta(days=10),
                                         "lines": [{"product_id": products["LAMP-01"].id, "qty": 300}]})
        purchase.submit_order(ctx, po.id)

        # 头程：空运发 FBA，含运费分摊
        fba_codes = [c for c, _t, _p, ful, _v in CATALOG if ful == "FBA"]
        listings = {x.product_id: x for x in db.execute(select(Listing).where(Listing.shop_id == shop.id)).scalars().all()}
        shipment = fba.create_shipment(ctx, {
            "shop_id": shop.id, "ship_from_warehouse_id": wh.id, "to_warehouse_id": fba_wh.id,
            "platform_shipment_id": "FBA18DEMO01", "destination_fc": "ONT8", "logistics_channel_id": air.id,
            "freight_cost": Decimal("6800"), "customs_duty": Decimal("900"), "cost_currency": "CNY", "allocation_method": "weight",
            "lines": [{"listing_id": listings[products[c].id].id, "qty": 300} for c in fba_codes],
        })
        fba.ship(ctx, shipment.id)
        fba.receive(ctx, shipment.id, None, close=True)
        shipment2 = fba.create_shipment(ctx, {
            "shop_id": shop.id, "ship_from_warehouse_id": wh.id, "to_warehouse_id": fba_wh.id,
            "platform_shipment_id": "FBA18DEMO02", "logistics_channel_id": sea.id, "freight_cost": Decimal("2600"),
            "lines": [{"listing_id": listings[products[c].id].id, "qty": 120} for c in fba_codes[:3]],
        })
        fba.ship(ctx, shipment2.id)

        # 同步订单、FBA 库存、交易、广告
        sync_shop(ctx, shop.id, ["orders", "fba_inventory", "finances", "ads"], trigger="manual")

        # 费用
        for i, (cat, amount, desc) in enumerate([("salary", "18000", "运营团队工资"), ("software", "980", "ERP/工具订阅"),
                                                  ("rent", "6500", "办公室租金")]):
            create_expense(ctx, {"category": cat, "shop_id": shop.id if cat == "software" else None,
                                 "expense_date": date.today() - timedelta(days=5 + i * 7), "amount": Decimal(amount),
                                 "currency": "CNY", "description": desc})
        db.commit()

        # 默认仓库位（拣货单按库位排序）
        from app.modules.warehouse.models import InventoryBalance

        for i, code in enumerate(products):
            bal = db.execute(select(InventoryBalance).where(InventoryBalance.warehouse_id == wh.id,
                                                            InventoryBalance.product_id == products[code].id)).scalar_one_or_none()
            if bal is not None:
                bal.bin_code = f"A-{i // 4 + 1:02d}-{i % 4 + 1:02d}"
        db.commit()

                # 分销：等级、分销商（含门户账号）、分销商品、充值与订单
        from app.modules.distribution import service as dist
        from app.modules.distribution.models import DistributorLevel
        from app.modules.system.service import update_settings

        lv_normal = DistributorLevel(code="STD", name="标准分销", discount_rate=Decimal("1"))
        lv_vip = DistributorLevel(code="VIP", name="VIP 分销", discount_rate=Decimal("0.92"))
        db.add_all([lv_normal, lv_vip])
        db.flush()
        update_settings(ctx, {"distribution.channel_ids": [exp.id], "distribution.handling_fee_per_order": 7.1,
                              "distribution.freight_markup_rate": 0.1})
        dist.upsert_catalog(ctx, [
            {"product_id": p.id, "base_price": q2(Decimal(costs[code]) / Decimal("7.1") * Decimal("1.6")), "currency": "USD",
             "min_qty": 20, "title": p.name}
            for code, p in products.items()
        ])
        dealer = dist.create_distributor(ctx, {
            "name": "Sunrise Trading LLC", "contact": "Mike Chen", "email": "mike@example.com", "country": "US",
            "address": "500 Commerce Blvd, Ontario, CA 91761", "currency": "USD", "level_id": lv_vip.id,
            "credit_limit": Decimal("500"), "username": "dealer", "password": "dealer123456",
        })
        dist.create_distributor(ctx, {"name": "深圳跨境优选", "contact": "王总", "currency": "CNY", "level_id": lv_normal.id})
        req = dist.create_recharge(db, dealer, {"amount": Decimal("2000"), "payment_method": "电汇", "transaction_no": "TT20260901"})
        dist.review_recharge(ctx, req.id, True)
        dealer = db.get(type(dealer), dealer.id)
        for i, (code, qty) in enumerate([("LAMP-01", 2), ("BOTTLE-03", 3), ("CASE-07", 5)]):
            dist.place_order(ctx, dealer, {
                "order_type": "dropship", "channel_id": exp.id, "reference_no": f"SUN-{1001 + i}",
                "items": [{"product_id": products[code].id, "qty": qty}],
                "address": {"name": ["Emily Davis", "Jason Lee", "Karen White"][i], "country": "US", "state": "CA",
                            "city": "San Jose", "address1": f"{100 + i} Market St", "postcode": "95113"},
            })
            db.commit()
        dist.create_recharge(db, dealer, {"amount": Decimal("1500"), "payment_method": "PayPal", "transaction_no": "PP-88231"})
        db.commit()
        print(f"演示数据已生成：登录账号 {username} / {password}；分销商门户账号 dealer / dealer123456")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="云帆ERP 管理命令")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="执行数据库迁移到最新版本")
    p = sub.add_parser("create-tenant", help="创建企业及管理员")
    p.add_argument("--company", required=True)
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)
    d = sub.add_parser("seed-demo", help="生成演示企业与数据")
    d.add_argument("--username", default="demo")
    d.add_argument("--password", default="demo123456")
    args = parser.parse_args(argv)
    if args.cmd == "init-db":
        init_db()
    elif args.cmd == "create-tenant":
        create_tenant(args.company, args.username, args.password)
    elif args.cmd == "seed-demo":
        seed_demo(args.username, args.password)


if __name__ == "__main__":
    main(sys.argv[1:])
