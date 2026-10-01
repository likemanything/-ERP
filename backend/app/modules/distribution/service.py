"""分销业务。

资金：分销商账户 = 余额 + 授信额度。下单时按「货款 + 运费 + 代发操作费」实时扣款，
取消订单 / 退货退款自动退回；充值申请经财务确认后入账。所有变动写资金流水。

订单：分销订单写入 sales_orders（分销商专属虚拟店铺），完全复用
审核锁库存 → 发货 FIFO 出库核算成本 → 退货 → 利润报表 的既有链路。
"""

import hashlib
import hmac
import secrets
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.common.audit import audit
from app.common.crud import get_or_404
from app.common.currency import get_rate
from app.common.enums import OrderStatus, ProductType
from app.common.numbering import next_doc_no
from app.core.deps import Ctx
from app.core.errors import BizError, Conflict, Forbidden
from app.core.security import hash_password
from app.core.types import q2, utcnow
from app.modules.distribution.models import (
    DistributionLevelPrice,
    DistributionProduct,
    Distributor,
    DistributorLevel,
    DistributorTransaction,
    RechargeRequest,
)
from app.modules.logistics.models import LogisticsChannel
from app.modules.logistics.service import calc_freight
from app.modules.order.models import SalesOrder, SalesOrderItem
from app.modules.product.models import BundleItem, Product
from app.modules.shop.models import Shop
from app.modules.system.models import Tenant, User
from app.modules.system.service import get_setting
from app.modules.warehouse.models import InventoryBalance, Warehouse

API_KEY_PREFIX = "dk_"


# ================================================================ 基础工具
def convert(db, amount: Decimal, from_cur: str, to_cur: str) -> Decimal:
    if not amount or from_cur == to_cur:
        return Decimal(amount or 0)
    return Decimal(amount) * get_rate(db, from_cur) / get_rate(db, to_cur)


def distribution_warehouse_ids(db) -> list[int]:
    ids = [int(x) for x in (get_setting(db, "distribution.warehouse_ids") or [])]
    stmt = select(Warehouse.id).where(
        Warehouse.status == "active", Warehouse.warehouse_type.in_(["local", "overseas", "third_party"])
    )
    if ids:
        stmt = stmt.where(Warehouse.id.in_(ids))
    return list(db.execute(stmt.order_by(Warehouse.is_default.desc(), Warehouse.id)).scalars().all())


def _components(db, product_ids: list[int]) -> dict[int, list[tuple[int, int]]]:
    """产品 → [(库存SKU, 单位用量)]，组合产品展开为子件。"""
    products = {p.id: p for p in db.execute(select(Product).where(Product.id.in_(product_ids))).scalars().all()}
    bundle_ids = [pid for pid, p in products.items() if p.product_type == ProductType.BUNDLE]
    items: dict[int, list[tuple[int, int]]] = defaultdict(list)
    if bundle_ids:
        for b in db.execute(select(BundleItem).where(BundleItem.bundle_id.in_(bundle_ids))).scalars().all():
            items[b.bundle_id].append((b.component_id, b.quantity))
    return {pid: (items[pid] if pid in bundle_ids else [(pid, 1)]) for pid in products}


def stock_by_warehouse(db, product_ids: list[int], warehouse_ids: list[int]) -> dict[tuple[int, int], int]:
    if not product_ids or not warehouse_ids:
        return {}
    rows = db.execute(
        select(InventoryBalance.warehouse_id, InventoryBalance.product_id, InventoryBalance.qty_on_hand - InventoryBalance.qty_locked)
        .where(InventoryBalance.product_id.in_(product_ids), InventoryBalance.warehouse_id.in_(warehouse_ids))
    ).all()
    return {(w, p): int(q or 0) for w, p, q in rows}


def available_qty(db, product_ids: list[int]) -> dict[int, int]:
    """分销仓合计可售数量（组合产品按子件最小可组数计算）。"""
    if not product_ids:
        return {}
    comps = _components(db, product_ids)
    all_comp = list({c for lst in comps.values() for c, _ in lst})
    whs = distribution_warehouse_ids(db)
    per_wh = stock_by_warehouse(db, all_comp, whs)
    total: dict[int, int] = defaultdict(int)
    for (_, pid), q in per_wh.items():
        total[pid] += max(0, q)
    result = {}
    for pid, lst in comps.items():
        result[pid] = min((total.get(c, 0) // qty for c, qty in lst), default=0) if lst else 0
    return result


def pick_warehouse(db, needs: dict[int, int]) -> int | None:
    """选择能整单满足的分销仓（默认仓优先）。needs: 库存SKU → 数量。"""
    whs = distribution_warehouse_ids(db)
    stock = stock_by_warehouse(db, list(needs), whs)
    for wid in whs:
        if all(stock.get((wid, pid), 0) >= q for pid, q in needs.items()):
            return wid
    return None


# ================================================================ 定价
def level_price_map(db, product_ids: list[int], level_id: int | None) -> dict[int, Decimal]:
    if not level_id or not product_ids:
        return {}
    rows = db.execute(
        select(DistributionLevelPrice.product_id, DistributionLevelPrice.price)
        .where(DistributionLevelPrice.level_id == level_id, DistributionLevelPrice.product_id.in_(product_ids))
    ).all()
    return {pid: Decimal(price) for pid, price in rows}


def unit_price(db, distributor: Distributor, dp: DistributionProduct, level_prices: dict[int, Decimal]) -> Decimal:
    """分销商的含税单价（分销商结算币种）：等级价 > 基础价 × 等级折扣。"""
    if dp.product_id in level_prices:
        price = level_prices[dp.product_id]
    else:
        rate = Decimal(distributor.level.discount_rate) if distributor.level else Decimal(1)
        price = Decimal(dp.base_price) * rate
    return q2(convert(db, price, dp.currency, distributor.currency))


# ================================================================ 资金账户
def post_txn(
    db, distributor_id: int, amount: Decimal, txn_type: str, *, ref_type: str | None = None, ref_id: int | None = None,
    ref_no: str | None = None, remark: str | None = None, check_funds: bool = False,
) -> DistributorTransaction:
    """记一笔资金流水（行锁防止并发超扣）。"""
    d = db.execute(select(Distributor).where(Distributor.id == distributor_id).with_for_update(of=Distributor)).scalar_one()
    amount = q2(amount)
    if check_funds and amount < 0 and Decimal(d.balance) + Decimal(d.credit_limit) + amount < 0:
        raise BizError(
            f"账户可用资金不足：余额 {q2(d.balance)} + 授信 {q2(d.credit_limit)} {d.currency}，本次需扣 {-amount} {d.currency}",
            code="insufficient_funds",
        )
    d.balance = q2(Decimal(d.balance) + amount)
    txn = DistributorTransaction(
        distributor_id=d.id, txn_type=txn_type, amount=amount, balance_after=d.balance, currency=d.currency,
        ref_type=ref_type, ref_id=ref_id, ref_no=ref_no, remark=remark,
    )
    db.add(txn)
    db.flush()
    return txn


# ================================================================ 分销商管理
def _tenant_tz(db) -> str:
    tid = db.info.get("tenant_id")
    t = db.get(Tenant, tid) if tid else None
    return t.timezone if t else "Asia/Shanghai"


def ensure_shop(ctx: Ctx, d: Distributor) -> Shop:
    shop = ctx.db.get(Shop, d.shop_id) if d.shop_id else None
    if shop is None:
        shop = Shop(
            name=f"分销-{d.code}-{d.name}"[:128], platform="distribution", marketplace_code="DISTRIBUTION_GLOBAL",
            country="GLOBAL", region="GLOBAL", currency=d.currency, timezone=_tenant_tz(ctx.db), status="active",
            sync_enabled=False, remark="分销商专属虚拟店铺（系统自动创建）",
        )
        ctx.db.add(shop)
        ctx.db.flush()
        d.shop_id = shop.id
    else:
        shop.name = f"分销-{d.code}-{d.name}"[:128]
        shop.currency = d.currency
        shop.status = "active" if d.status == "active" else "disabled"
    return shop


def _next_code(db) -> str:
    n = db.execute(select(func.count()).select_from(Distributor)).scalar_one()
    while True:
        n += 1
        code = f"D{n:04d}"
        if not db.execute(select(Distributor.id).where(Distributor.code == code)).first():
            return code


def create_distributor(ctx: Ctx, data: dict) -> Distributor:
    db = ctx.db
    username, password = data.pop("username", None), data.pop("password", None)
    data["code"] = (data.get("code") or _next_code(db)).strip()
    if db.execute(select(Distributor.id).where(Distributor.code == data["code"])).first():
        raise Conflict(f"分销商编码 {data['code']} 已存在")
    data["currency"] = (data.get("currency") or "CNY").upper()
    if data.get("level_id"):
        get_or_404(db, DistributorLevel, data["level_id"], "分销等级")
    d = Distributor(**data, balance=Decimal(0))
    db.add(d)
    db.flush()
    ensure_shop(ctx, d)
    if username:
        create_portal_user(ctx, d, username, password or "", d.contact or d.name)
    audit(ctx, "create", "distributor", d.id, f"新增分销商 {d.code} {d.name}")
    db.commit()
    return d


def update_distributor(ctx: Ctx, distributor_id: int, data: dict) -> Distributor:
    db = ctx.db
    d = get_or_404(db, Distributor, distributor_id, "分销商", for_update=True)
    if "currency" in data and data["currency"] and data["currency"].upper() != d.currency:
        has_txn = db.execute(select(DistributorTransaction.id).where(DistributorTransaction.distributor_id == d.id).limit(1)).first()
        if has_txn:
            raise BizError("已有资金流水的分销商不能修改结算币种")
        data["currency"] = data["currency"].upper()
    if data.get("level_id"):
        get_or_404(db, DistributorLevel, data["level_id"], "分销等级")
    for k, v in data.items():
        setattr(d, k, v)
    ensure_shop(ctx, d)
    if d.status != "active":
        # 停用分销商时同时使其账号 token 失效
        for u in db.execute(select(User).where(User.distributor_id == d.id)).scalars().all():
            u.token_version += 1
    audit(ctx, "update", "distributor", d.id, f"修改分销商 {d.code}", {"fields": list(data)})
    db.commit()
    db.refresh(d)
    return d


def create_portal_user(ctx: Ctx, d: Distributor, username: str, password: str, real_name: str = "") -> User:
    db = ctx.db
    if len(username) < 3 or len(password) < 6:
        raise BizError("登录账号至少 3 位，密码至少 6 位")
    exists = db.execute(select(User.id).where(User.username == username).execution_options(skip_tenant_filter=True)).first()
    if exists:
        raise Conflict(f"用户名 {username} 已被占用")
    user = User(
        username=username, password_hash=hash_password(password), real_name=real_name or d.name,
        user_type="distributor", distributor_id=d.id, is_superuser=False, all_shops=False, email=d.email, phone=d.phone,
    )
    db.add(user)
    db.flush()
    audit(ctx, "create", "distributor_user", user.id, f"为分销商 {d.code} 开通账号 {username}")
    return user


def generate_api_key(db, d: Distributor) -> str:
    key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    d.api_key_prefix = key[:10]
    d.api_key_hash = hashlib.sha256(key.encode()).hexdigest()
    return key


def find_by_api_key(db, key: str) -> Distributor | None:
    if not key or not key.startswith(API_KEY_PREFIX):
        return None
    candidates = db.execute(
        select(Distributor).where(Distributor.api_key_prefix == key[:10]).execution_options(skip_tenant_filter=True)
    ).scalars().all()
    digest = hashlib.sha256(key.encode()).hexdigest()
    for d in candidates:
        if d.api_key_hash and hmac.compare_digest(d.api_key_hash, digest):
            return d
    return None


# ================================================================ 充值
def create_recharge(db, d: Distributor, data: dict) -> RechargeRequest:
    if Decimal(data["amount"]) <= 0:
        raise BizError("充值金额必须大于 0")
    req = RechargeRequest(request_no=next_doc_no(db, "CZ"), distributor_id=d.id, currency=d.currency, status="pending", **data)
    db.add(req)
    db.flush()
    return req


def review_recharge(ctx: Ctx, req_id: int, approve: bool, reason: str | None = None) -> RechargeRequest:
    db = ctx.db
    req = get_or_404(db, RechargeRequest, req_id, "充值申请", for_update=True)
    if req.status != "pending":
        raise BizError("充值申请已处理")
    req.status = "approved" if approve else "rejected"
    req.reviewed_by = ctx.user_id
    req.reviewed_at = utcnow()
    if approve:
        post_txn(db, req.distributor_id, Decimal(req.amount), "recharge", ref_type="recharge", ref_id=req.id,
                 ref_no=req.request_no, remark=f"充值到账 {req.payment_method or ''} {req.transaction_no or ''}".strip())
    else:
        req.reject_reason = reason
    audit(ctx, "approve" if approve else "reject", "distributor_recharge", req.id,
          f"{'确认' if approve else '驳回'}充值 {req.request_no} {req.amount} {req.currency}")
    db.commit()
    return req


def adjust_balance(ctx: Ctx, distributor_id: int, amount: Decimal, remark: str) -> DistributorTransaction:
    d = get_or_404(ctx.db, Distributor, distributor_id, "分销商")
    txn = post_txn(ctx.db, d.id, amount, "adjust", ref_type="manual", remark=remark)
    audit(ctx, "adjust", "distributor", d.id, f"调整分销商 {d.code} 余额 {amount} {d.currency}：{remark}")
    ctx.db.commit()
    return txn


# ================================================================ 商品目录
def upsert_catalog(ctx: Ctx, items: list[dict]) -> int:
    db = ctx.db
    ids = [i["product_id"] for i in items]
    products = {p.id: p for p in db.execute(select(Product).where(Product.id.in_(ids))).scalars().all()}
    existing = {x.product_id: x for x in db.execute(select(DistributionProduct).where(DistributionProduct.product_id.in_(ids))).scalars().all()}
    n = 0
    for it in items:
        p = products.get(it["product_id"])
        if p is None:
            raise BizError(f"产品不存在（ID={it['product_id']}）")
        if p.product_type == ProductType.AUXILIARY:
            raise BizError(f"辅料 {p.sku} 不能上架分销")
        dp = existing.get(p.id)
        if dp is None:
            dp = DistributionProduct(product_id=p.id)
            db.add(dp)
            existing[p.id] = dp
        for k, v in it.items():
            if k != "product_id" and v is not None:
                setattr(dp, k, v.upper() if k == "currency" else v)
        if dp.base_price is None:
            dp.base_price = Decimal(0)
        n += 1
    audit(ctx, "update", "distribution_product", None, f"维护分销商品 {n} 个")
    db.commit()
    return n


def set_level_prices(ctx: Ctx, product_id: int, prices: list[dict]) -> None:
    db = ctx.db
    get_or_404(db, Product, product_id, "产品")
    current = {x.level_id: x for x in db.execute(select(DistributionLevelPrice).where(DistributionLevelPrice.product_id == product_id)).scalars().all()}
    keep = set()
    for p in prices:
        get_or_404(db, DistributorLevel, p["level_id"], "分销等级")
        keep.add(p["level_id"])
        row = current.get(p["level_id"])
        if row is None:
            db.add(DistributionLevelPrice(product_id=product_id, level_id=p["level_id"], price=p["price"]))
        else:
            row.price = p["price"]
    for level_id, row in current.items():
        if level_id not in keep:
            db.delete(row)
    audit(ctx, "update", "distribution_product", product_id, "设置等级价")
    db.commit()


# ================================================================ 报价与下单
@dataclass
class QuoteLine:
    product: Product
    dp: DistributionProduct
    qty: int
    unit_price: Decimal

    @property
    def amount(self) -> Decimal:
        return q2(self.unit_price * self.qty)


def allowed_channels(db) -> list[LogisticsChannel]:
    ids = [int(x) for x in (get_setting(db, "distribution.channel_ids") or [])]
    stmt = select(LogisticsChannel).where(LogisticsChannel.status == "active")
    if ids:
        stmt = stmt.where(LogisticsChannel.id.in_(ids))
    else:
        stmt = stmt.where(LogisticsChannel.usage.in_(["last_mile", "both"]))
    return list(db.execute(stmt.order_by(LogisticsChannel.id)).scalars().all())


def _resolve_lines(db, d: Distributor, items: list[dict], order_type: str) -> list[QuoteLine]:
    if not items:
        raise BizError("请添加商品")
    skus = [str(i.get("sku")).strip() for i in items if i.get("sku") and not i.get("product_id")]
    by_sku = {p.sku: p for p in db.execute(select(Product).where(Product.sku.in_(skus))).scalars().all()} if skus else {}
    pids = [i["product_id"] for i in items if i.get("product_id")]
    by_id = {p.id: p for p in db.execute(select(Product).where(Product.id.in_(pids))).scalars().all()} if pids else {}
    resolved: dict[int, int] = defaultdict(int)
    for i in items:
        p = by_id.get(i["product_id"]) if i.get("product_id") else by_sku.get(str(i.get("sku") or "").strip())
        if p is None:
            raise BizError(f"商品不存在：{i.get('sku') or i.get('product_id')}")
        qty = int(i.get("qty") or i.get("quantity") or 0)
        if qty <= 0:
            raise BizError(f"{p.sku} 数量必须大于 0")
        resolved[p.id] += qty
    dps = {x.product_id: x for x in db.execute(
        select(DistributionProduct).where(DistributionProduct.product_id.in_(list(resolved)), DistributionProduct.is_active.is_(True))
    ).scalars().all()}
    products = {p.id: p for p in db.execute(select(Product).where(Product.id.in_(list(resolved)))).scalars().all()}
    lp = level_price_map(db, list(resolved), d.level_id)
    lines = []
    for pid, qty in resolved.items():
        dp = dps.get(pid)
        if dp is None:
            raise BizError(f"{products[pid].sku} 未上架分销")
        if order_type == "wholesale" and qty < (dp.min_qty or 1):
            raise BizError(f"{products[pid].sku} 批发起订量为 {dp.min_qty}")
        lines.append(QuoteLine(products[pid], dp, qty, unit_price(db, d, dp, lp)))
    return lines


def _weight(db, lines: list[QuoteLine]) -> Decimal:
    comps = _components(db, [ln.product.id for ln in lines])
    comp_ids = list({c for lst in comps.values() for c, _ in lst})
    weights = dict(db.execute(select(Product.id, Product.weight_kg).where(Product.id.in_(comp_ids))).all())
    total = Decimal(0)
    for ln in lines:
        for c, q in comps[ln.product.id]:
            total += Decimal(weights.get(c) or 0) * q * ln.qty
    return total


def quote(db, d: Distributor, items: list[dict], channel_id: int | None, order_type: str) -> dict[str, Any]:
    if order_type not in ("dropship", "wholesale"):
        raise BizError("订单类型无效")
    if order_type == "dropship" and not d.allow_dropship:
        raise Forbidden("您的账户未开通一件代发")
    if order_type == "wholesale" and not d.allow_wholesale:
        raise Forbidden("您的账户未开通批发采购")
    lines = _resolve_lines(db, d, items, order_type)
    goods = sum((ln.amount for ln in lines), Decimal(0))
    weight = _weight(db, lines)
    freight = Decimal(0)
    channel = None
    if channel_id:
        channel = next((c for c in allowed_channels(db) if c.id == channel_id), None)
        if channel is None:
            raise BizError("该物流渠道不可用")
        _, fee = calc_freight(channel, weight_kg=weight)
        markup = Decimal(str(get_setting(db, "distribution.freight_markup_rate") or 0))
        freight = q2(convert(db, fee, channel.currency, d.currency) * (1 + markup))
    elif order_type == "dropship":
        raise BizError("一件代发订单请选择物流渠道")
    handling = Decimal(0)
    if order_type == "dropship":
        from app.common.currency import base_currency

        base = base_currency(db)
        per_order = Decimal(str(get_setting(db, "distribution.handling_fee_per_order") or 0))
        per_item = Decimal(str(get_setting(db, "distribution.handling_fee_per_item") or 0))
        units = sum(ln.qty for ln in lines)
        handling = q2(convert(db, per_order + per_item * units, base, d.currency))
    total = q2(goods + freight + handling)
    avail = available_qty(db, [ln.product.id for ln in lines])
    return {
        "currency": d.currency,
        "lines": [{"product_id": ln.product.id, "sku": ln.product.sku, "name": ln.dp.title or ln.product.name,
                   "qty": ln.qty, "unit_price": ln.unit_price, "amount": ln.amount,
                   "in_stock": avail.get(ln.product.id, 0) >= ln.qty} for ln in lines],
        "weight_kg": q2(weight),
        "goods": q2(goods),
        "freight": freight,
        "handling": handling,
        "total": total,
        "channel_id": channel.id if channel else None,
        "channel_name": channel.name if channel else None,
        "transit_days": channel.transit_days if channel else None,
        "available_funds": q2(d.available_funds),
        "sufficient": d.available_funds >= total,
        "_lines": lines,
    }


def place_order(ctx: Ctx, d: Distributor, data: dict) -> SalesOrder:
    """分销商下单：报价 → 扣款 → 写入订单 →（可选）自动审核锁库存。"""
    from app.modules.order.service import _recalc_totals, audit_order, local_date_of, stock_components

    db = ctx.db
    if d.status != "active":
        raise Forbidden("分销商账户已停用")
    order_type = data.get("order_type") or "dropship"
    q = quote(db, d, data["items"], data.get("channel_id"), order_type)
    shop = ensure_shop(ctx, d)
    ref = (data.get("reference_no") or "").strip() or f"DS{utcnow():%y%m%d}{secrets.token_hex(3).upper()}"
    if db.execute(select(SalesOrder.id).where(SalesOrder.shop_id == shop.id, SalesOrder.platform_order_id == ref)).first():
        raise Conflict(f"订单号 {ref} 已存在，请勿重复提交")
    addr = data.get("address") or {}
    if order_type == "dropship" and not (addr.get("name") and addr.get("address1") and addr.get("country")):
        raise BizError("一件代发订单需填写收件人、国家和地址")
    now = utcnow()
    order = SalesOrder(
        order_no=next_doc_no(db, "SO"), shop_id=shop.id, platform="distribution", platform_order_id=ref,
        fulfillment="FBM", status=OrderStatus.TO_AUDIT, platform_status="submitted", purchase_at=now, paid_at=now,
        local_date=local_date_of(now, shop.timezone), currency=d.currency, buyer_name=d.name, buyer_email=d.email,
        ship_name=addr.get("name") or d.contact or d.name, ship_phone=addr.get("phone") or d.phone,
        ship_country=(addr.get("country") or d.country or "").upper() or None, ship_state=addr.get("state"),
        ship_city=addr.get("city"), ship_address1=addr.get("address1") or (d.address if order_type == "wholesale" else None),
        ship_address2=addr.get("address2"), ship_postcode=addr.get("postcode"), buyer_note=data.get("remark"),
        distributor_id=d.id, distribution_type=order_type, logistics_channel_id=q["channel_id"],
        charge_detail={"goods": float(q["goods"]), "freight": float(q["freight"]), "handling": float(q["handling"]),
                       "adjust": 0.0, "total": float(q["total"]), "currency": d.currency, "refunded": 0.0},
    )
    for idx, ln in enumerate(q["_lines"]):
        order.items.append(SalesOrderItem(
            shop_id=shop.id, msku=ln.product.sku, product_id=ln.product.id, sku=ln.product.sku,
            title=ln.dp.title or ln.product.name, quantity=ln.qty, unit_price=ln.unit_price, item_amount=ln.amount,
            shipping_amount=(q["freight"] + q["handling"]) if idx == 0 else Decimal(0),
            tax_amount=Decimal(0), discount_amount=Decimal(0), commission_fee=Decimal(0), fulfillment_fee=Decimal(0),
            other_fee=Decimal(0), fee_estimated=False, quantity_shipped=0, refund_qty=0, refund_amount=Decimal(0),
            cost_purchase=Decimal(0), cost_freight=Decimal(0), cost_settled=False,
        ))
    _recalc_totals(order)
    db.add(order)
    db.flush()
    post_txn(db, d.id, -q["total"], "order", ref_type="sales_order", ref_id=order.id, ref_no=ref,
             remark=f"{'一件代发' if order_type == 'dropship' else '批发'}订单扣款", check_funds=True)
    audit(ctx, "create", "sales_order", order.id, f"分销商 {d.code} 下单 {ref}，扣款 {q['total']} {d.currency}")
    if get_setting(db, "distribution.auto_audit"):
        try:
            with db.begin_nested():
                needs: dict[int, int] = defaultdict(int)
                for p in stock_components(db, order):
                    needs[p["product_id"]] += p["qty"]
                wid = pick_warehouse(db, needs)
                if wid is None:
                    raise BizError("分销仓库存不足，等待人工审核")
                audit_order(ctx, order, wid, q["channel_id"])
        except BizError as exc:
            order.tags = sorted(set(order.tags or []) | {"待人工审核"})
            order.remark = f"自动审核未通过：{exc.message}"[:500]
    return order


def _refundable(detail: dict) -> Decimal:
    refunded = detail.get("refunded")
    refunded = Decimal(0) if isinstance(refunded, bool) or refunded is None else Decimal(str(refunded))
    return max(Decimal(str(detail.get("total") or 0)) - refunded, Decimal(0))


def refund_order(db, order: SalesOrder, remark: str) -> None:
    """订单取消：退回尚未退还的扣款（幂等）。charge_detail.refunded 为累计退款金额。"""
    detail = dict(order.charge_detail or {})
    if not order.distributor_id or detail.get("cancel_refunded"):
        return
    amount = q2(_refundable(detail))
    if amount:
        post_txn(db, order.distributor_id, amount, "refund", ref_type="sales_order", ref_id=order.id,
                 ref_no=order.platform_order_id, remark=remark)
    detail["refunded"] = float(Decimal(str(detail.get("total") or 0)))
    detail["cancel_refunded"] = True
    order.charge_detail = detail


def credit_return(db, order: SalesOrder, ret) -> None:
    """退货退款完成：按退款金额退回分销商账户（不超过订单尚未退还的扣款）。"""
    if not order.distributor_id:
        return
    detail = dict(order.charge_detail or {})
    amount = q2(min(Decimal(ret.refund_amount or 0), _refundable(detail)))
    if amount <= 0:
        return
    post_txn(db, order.distributor_id, amount, "refund", ref_type="return_order",
             ref_id=ret.id, ref_no=ret.return_no, remark=f"退货退款（订单 {order.platform_order_id}）")
    detail["refunded"] = float(Decimal(str(detail.get("total") or 0)) - _refundable(detail) + amount)
    order.charge_detail = detail


def charge_adjust(ctx: Ctx, order_id: int, amount: Decimal, remark: str) -> SalesOrder:
    """订单补扣（正数，如运费差额）或部分退款（负数），同步计入订单收入。"""
    db = ctx.db
    order = get_or_404(db, SalesOrder, order_id, "订单", for_update=True)
    if not order.distributor_id:
        raise BizError("非分销订单")
    if order.status == OrderStatus.CANCELLED:
        raise BizError("已取消订单不能调整费用")
    amount = q2(amount)
    if not amount:
        raise BizError("金额不能为 0")
    post_txn(db, order.distributor_id, -amount, "order" if amount > 0 else "refund", ref_type="sales_order",
             ref_id=order.id, ref_no=order.platform_order_id, remark=remark, check_funds=amount > 0)
    detail = dict(order.charge_detail or {})
    detail["adjust"] = float(Decimal(str(detail.get("adjust") or 0)) + amount)
    detail["total"] = float(Decimal(str(detail.get("total") or 0)) + amount)
    order.charge_detail = detail
    if order.items:
        order.items[0].shipping_amount = q2(Decimal(order.items[0].shipping_amount or 0) + amount)
        from app.modules.order.service import _recalc_totals

        _recalc_totals(order)
    audit(ctx, "adjust", "sales_order", order.id, f"分销订单 {order.platform_order_id} 费用调整 {amount}：{remark}")
    db.commit()
    return order


def cancel_by_distributor(ctx: Ctx, d: Distributor, order_id: int) -> SalesOrder:
    from app.modules.order.service import cancel

    db = ctx.db
    order = db.execute(
        select(SalesOrder).where(SalesOrder.id == order_id, SalesOrder.distributor_id == d.id).with_for_update(of=SalesOrder)
    ).scalar_one_or_none()
    if order is None:
        raise BizError("订单不存在")
    if order.status == OrderStatus.TO_SHIP and not get_setting(db, "distribution.allow_cancel_after_audit"):
        raise BizError("订单已审核配货，请联系客服取消")
    if order.status not in (OrderStatus.TO_AUDIT, OrderStatus.TO_SHIP, OrderStatus.PENDING):
        raise BizError("订单已发货或已取消，无法取消")
    cancel(ctx, order, "分销商取消")
    audit(ctx, "cancel", "sales_order", order.id, f"分销商 {d.code} 取消订单 {order.platform_order_id}")
    db.commit()
    return order


# ================================================================ 对账
def statement(db, distributor_id: int, date_from: date, date_to: date) -> dict:
    from datetime import datetime, time

    d = get_or_404(db, Distributor, distributor_id, "分销商")
    start = datetime.combine(date_from, time.min)
    end = datetime.combine(date_to, time.max)
    T = DistributorTransaction
    before = db.execute(
        select(T.balance_after).where(T.distributor_id == d.id, T.created_at < start).order_by(T.id.desc()).limit(1)
    ).scalar_one_or_none()
    txns = db.execute(
        select(T).where(T.distributor_id == d.id, T.created_at >= start, T.created_at <= end).order_by(T.id)
    ).scalars().all()
    sums: dict[str, Decimal] = defaultdict(Decimal)
    for t in txns:
        sums[t.txn_type] += Decimal(t.amount)
    opening = Decimal(before or 0)
    closing = Decimal(txns[-1].balance_after) if txns else opening
    active = (SalesOrder.distributor_id == d.id, SalesOrder.status != OrderStatus.CANCELLED,
              SalesOrder.local_date >= date_from, SalesOrder.local_date <= date_to)
    units = db.execute(
        select(func.coalesce(func.sum(SalesOrderItem.quantity), 0))
        .select_from(SalesOrder).join(SalesOrderItem, SalesOrderItem.order_id == SalesOrder.id).where(*active)
    ).scalar_one()
    order_count = db.execute(select(func.count()).select_from(SalesOrder).where(*active)).scalar_one()
    return {
        "distributor_id": d.id, "distributor_name": d.name, "currency": d.currency,
        "date_from": date_from, "date_to": date_to,
        "opening_balance": q2(opening), "closing_balance": q2(closing),
        "recharge": q2(sums["recharge"]), "order": q2(sums["order"]), "refund": q2(sums["refund"]), "adjust": q2(sums["adjust"]),
        "order_count": int(order_count), "units": int(units or 0),
        "transactions": txns,
    }
