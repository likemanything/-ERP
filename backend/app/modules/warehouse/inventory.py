"""库存引擎：所有库存变动的唯一入口。

* 每次变动写库存流水 InventoryLedger，并更新 InventoryBalance。
* 良品入库生成批次（成本层），出库按先进先出（FIFO）消耗批次，返回实际成本。
* 成本拆分为「采购成本」与「物流/头程成本」，利润报表可分别展示。
* PostgreSQL 下对余额行加 SELECT ... FOR UPDATE，保证并发安全。
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.enums import LedgerType, ProductType
from app.core.errors import BizError
from app.core.types import q4, utcnow
from app.modules.product.models import Product
from app.modules.warehouse.models import InventoryBalance, InventoryBatch, InventoryLedger, Warehouse


@dataclass
class CostLayer:
    batch_id: int | None
    qty: int
    unit_purchase_cost: Decimal
    unit_freight_cost: Decimal


@dataclass
class OutboundResult:
    qty: int = 0
    purchase_cost: Decimal = Decimal(0)
    freight_cost: Decimal = Decimal(0)
    layers: list[CostLayer] = field(default_factory=list)

    @property
    def total_cost(self) -> Decimal:
        return self.purchase_cost + self.freight_cost

    @property
    def unit_purchase_cost(self) -> Decimal:
        return q4(self.purchase_cost / self.qty) if self.qty else Decimal(0)

    @property
    def unit_freight_cost(self) -> Decimal:
        return q4(self.freight_cost / self.qty) if self.qty else Decimal(0)

    def merge(self, other: "OutboundResult") -> None:
        self.qty += other.qty
        self.purchase_cost += other.purchase_cost
        self.freight_cost += other.freight_cost
        self.layers.extend(other.layers)


@dataclass
class Ref:
    """库存变动关联的业务单据。"""

    ref_type: str
    ref_id: int | None = None
    ref_no: str | None = None
    remark: str | None = None
    biz_date: date | None = None


class InventoryService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------ 基础
    def balance(self, warehouse_id: int, product_id: int, *, lock: bool = True) -> InventoryBalance:
        stmt = select(InventoryBalance).where(
            InventoryBalance.warehouse_id == warehouse_id, InventoryBalance.product_id == product_id
        )
        if lock:
            stmt = stmt.with_for_update(of=InventoryBalance)
        bal = self.db.execute(stmt).scalar_one_or_none()
        if bal is None:
            try:
                with self.db.begin_nested():
                    bal = InventoryBalance(
                        warehouse_id=warehouse_id, product_id=product_id, qty_on_hand=0, qty_locked=0,
                        qty_defective=0, qty_in_transit=0,
                    )
                    self.db.add(bal)
                    self.db.flush()
            except IntegrityError:
                bal = self.db.execute(stmt).scalar_one()
        return bal

    def _check_product(self, product_id: int) -> Product:
        product = self.db.get(Product, product_id)
        if product is None:
            raise BizError(f"产品不存在（ID={product_id}）")
        if product.product_type == ProductType.BUNDLE:
            raise BizError(f"组合产品 {product.sku} 不直接管理库存，请操作其子产品")
        return product

    def _warehouse(self, warehouse_id: int) -> Warehouse:
        wh = self.db.get(Warehouse, warehouse_id)
        if wh is None:
            raise BizError(f"仓库不存在（ID={warehouse_id}）")
        return wh

    def _ledger(
        self,
        bal: InventoryBalance,
        change_type: str,
        qty_change: int,
        qty_after: int,
        ref: Ref,
        *,
        stock_type: str = "good",
        batch_id: int | None = None,
        unit_purchase_cost: Decimal = Decimal(0),
        unit_freight_cost: Decimal = Decimal(0),
    ) -> InventoryLedger:
        entry = InventoryLedger(
            warehouse_id=bal.warehouse_id,
            product_id=bal.product_id,
            batch_id=batch_id,
            change_type=change_type,
            stock_type=stock_type,
            qty_change=qty_change,
            qty_after=qty_after,
            unit_purchase_cost=unit_purchase_cost,
            unit_freight_cost=unit_freight_cost,
            amount=(unit_purchase_cost + unit_freight_cost) * qty_change,
            ref_type=ref.ref_type,
            ref_id=ref.ref_id,
            ref_no=ref.ref_no,
            biz_date=ref.biz_date or utcnow().date(),
            remark=ref.remark,
        )
        self.db.add(entry)
        return entry

    def _allow_negative(self, warehouse: Warehouse) -> bool:
        if warehouse.warehouse_type == "fba":
            return True  # FBA 虚拟仓以平台数据为准，允许负数
        from app.modules.system.service import get_setting

        return bool(get_setting(self.db, "inventory.allow_negative"))

    # ------------------------------------------------------------ 入库
    def inbound(
        self,
        warehouse_id: int,
        product_id: int,
        qty: int,
        ref: Ref,
        *,
        change_type: str,
        unit_purchase_cost: Decimal | None = None,
        unit_freight_cost: Decimal = Decimal(0),
        batch_no: str | None = None,
        supplier_id: int | None = None,
        purchase_order_id: int | None = None,
        received_at: datetime | None = None,
    ) -> InventoryBatch:
        """良品入库：生成成本批次。unit_purchase_cost 为空时取产品参考成本。"""
        if qty <= 0:
            raise BizError("入库数量必须大于 0")
        product = self._check_product(product_id)
        self._warehouse(warehouse_id)
        if unit_purchase_cost is None:
            unit_purchase_cost = Decimal(product.purchase_cost or 0)
        unit_purchase_cost = q4(unit_purchase_cost)
        unit_freight_cost = q4(unit_freight_cost or 0)
        bal = self.balance(warehouse_id, product_id)
        before = bal.qty_on_hand
        bal.qty_on_hand += qty
        # 负库存时，新入库数量先冲抵负数部分（该部分已按参考成本出库），剩余才形成可消耗批次
        absorbed = min(qty, max(0, -before))
        batch = InventoryBatch(
            warehouse_id=warehouse_id,
            product_id=product_id,
            batch_no=batch_no or ref.ref_no or f"B{utcnow():%y%m%d%H%M%S}",
            source_type=ref.ref_type,
            source_id=ref.ref_id,
            source_no=ref.ref_no,
            received_at=received_at or utcnow(),
            qty_in=qty,
            qty_remaining=qty - absorbed,
            unit_purchase_cost=unit_purchase_cost,
            unit_freight_cost=unit_freight_cost,
            supplier_id=supplier_id,
            purchase_order_id=purchase_order_id,
        )
        self.db.add(batch)
        self.db.flush()
        self._ledger(
            bal, change_type, qty, bal.qty_on_hand, ref, batch_id=batch.id,
            unit_purchase_cost=unit_purchase_cost, unit_freight_cost=unit_freight_cost,
        )
        return batch

    def inbound_layers(
        self, warehouse_id: int, product_id: int, layers: list[CostLayer], ref: Ref, *, change_type: str,
        extra_unit_freight: Decimal = Decimal(0),
    ) -> list[InventoryBatch]:
        """按来源成本层入库（调拨/FBA 签收时保留原始成本，叠加运费）。"""
        batches = []
        for layer in layers:
            if layer.qty <= 0:
                continue
            batches.append(
                self.inbound(
                    warehouse_id, product_id, layer.qty, ref, change_type=change_type,
                    unit_purchase_cost=layer.unit_purchase_cost,
                    unit_freight_cost=layer.unit_freight_cost + extra_unit_freight,
                )
            )
        return batches

    def inbound_defective(self, warehouse_id: int, product_id: int, qty: int, ref: Ref, *, change_type: str = LedgerType.DEFECTIVE_IN) -> None:
        if qty <= 0:
            return
        self._check_product(product_id)
        bal = self.balance(warehouse_id, product_id)
        bal.qty_defective += qty
        self._ledger(bal, change_type, qty, bal.qty_defective, ref, stock_type="defective")

    # ------------------------------------------------------------ 出库
    def outbound(
        self,
        warehouse_id: int,
        product_id: int,
        qty: int,
        ref: Ref,
        *,
        change_type: str,
        from_locked: bool = False,
        allow_negative: bool | None = None,
    ) -> OutboundResult:
        """良品出库，按 FIFO 消耗批次并返回成本。from_locked=True 表示消耗已锁定库存。"""
        if qty <= 0:
            raise BizError("出库数量必须大于 0")
        product = self._check_product(product_id)
        wh = self._warehouse(warehouse_id)
        if allow_negative is None:
            allow_negative = self._allow_negative(wh)
        bal = self.balance(warehouse_id, product_id)
        if from_locked:
            if bal.qty_locked < qty and not allow_negative:
                raise BizError(f"{product.sku} 在【{wh.name}】锁定库存不足（锁定 {bal.qty_locked}，需 {qty}）")
            bal.qty_locked = max(0, bal.qty_locked - qty)
        elif bal.qty_available < qty and not allow_negative:
            raise BizError(f"{product.sku} 在【{wh.name}】可用库存不足（可用 {bal.qty_available}，需 {qty}）")
        if bal.qty_on_hand < qty and not allow_negative:
            raise BizError(f"{product.sku} 在【{wh.name}】库存不足（实物 {bal.qty_on_hand}，需 {qty}）")

        result = OutboundResult()
        remaining = qty
        batches = self.db.execute(
            select(InventoryBatch)
            .where(
                InventoryBatch.warehouse_id == warehouse_id,
                InventoryBatch.product_id == product_id,
                InventoryBatch.qty_remaining > 0,
            )
            .order_by(InventoryBatch.received_at, InventoryBatch.id)
            .with_for_update(of=InventoryBatch)
        ).scalars().all()
        on_hand = bal.qty_on_hand
        for batch in batches:
            if remaining <= 0:
                break
            take = min(batch.qty_remaining, remaining)
            batch.qty_remaining -= take
            remaining -= take
            on_hand -= take
            layer = CostLayer(batch.id, take, batch.unit_purchase_cost, batch.unit_freight_cost)
            result.layers.append(layer)
            result.qty += take
            result.purchase_cost += batch.unit_purchase_cost * take
            result.freight_cost += batch.unit_freight_cost * take
            self._ledger(
                bal, change_type, -take, on_hand, ref, batch_id=batch.id,
                unit_purchase_cost=batch.unit_purchase_cost, unit_freight_cost=batch.unit_freight_cost,
            )
        if remaining > 0:
            # 批次不足（负库存或历史数据缺失）：按产品参考成本计价
            unit = q4(Decimal(product.purchase_cost or 0))
            on_hand -= remaining
            result.layers.append(CostLayer(None, remaining, unit, Decimal(0)))
            result.qty += remaining
            result.purchase_cost += unit * remaining
            self._ledger(bal, change_type, -remaining, on_hand, ref, unit_purchase_cost=unit)
        bal.qty_on_hand = on_hand
        return result

    def outbound_defective(self, warehouse_id: int, product_id: int, qty: int, ref: Ref, *, change_type: str = LedgerType.DEFECTIVE_OUT) -> None:
        product = self._check_product(product_id)
        bal = self.balance(warehouse_id, product_id)
        if bal.qty_defective < qty:
            raise BizError(f"{product.sku} 次品库存不足（次品 {bal.qty_defective}，需 {qty}）")
        bal.qty_defective -= qty
        self._ledger(bal, change_type, -qty, bal.qty_defective, ref, stock_type="defective")

    # ------------------------------------------------------------ 锁定
    def lock(self, warehouse_id: int, product_id: int, qty: int, ref: Ref) -> None:
        if qty <= 0:
            return
        product = self._check_product(product_id)
        wh = self._warehouse(warehouse_id)
        bal = self.balance(warehouse_id, product_id)
        if bal.qty_available < qty and not self._allow_negative(wh):
            raise BizError(f"{product.sku} 在【{wh.name}】可用库存不足（可用 {bal.qty_available}，需锁定 {qty}）")
        bal.qty_locked += qty
        self._ledger(bal, LedgerType.LOCK, qty, bal.qty_locked, ref, stock_type="locked")

    def unlock(self, warehouse_id: int, product_id: int, qty: int, ref: Ref) -> None:
        if qty <= 0:
            return
        bal = self.balance(warehouse_id, product_id)
        release = min(qty, bal.qty_locked)
        bal.qty_locked -= release
        self._ledger(bal, LedgerType.UNLOCK, -release, bal.qty_locked, ref, stock_type="locked")

    # ------------------------------------------------------------ 在途
    def add_in_transit(self, warehouse_id: int, product_id: int, qty: int) -> None:
        bal = self.balance(warehouse_id, product_id)
        bal.qty_in_transit = max(0, bal.qty_in_transit + qty)

    # ------------------------------------------------------------ 成本查询
    def average_cost(self, warehouse_id: int | None, product_id: int) -> tuple[Decimal, Decimal]:
        """当前结存的加权平均 (采购单价, 物流单价)，无结存时取产品参考成本。"""
        stmt = select(InventoryBatch).where(InventoryBatch.product_id == product_id, InventoryBatch.qty_remaining > 0)
        if warehouse_id:
            stmt = stmt.where(InventoryBatch.warehouse_id == warehouse_id)
        batches = self.db.execute(stmt).scalars().all()
        total = sum(b.qty_remaining for b in batches)
        if total:
            pc = sum(b.unit_purchase_cost * b.qty_remaining for b in batches) / total
            fc = sum(b.unit_freight_cost * b.qty_remaining for b in batches) / total
            return q4(pc), q4(fc)
        product = self.db.get(Product, product_id)
        return q4(Decimal(product.purchase_cost or 0) if product else Decimal(0)), Decimal(0)

    def adjust_to(self, warehouse_id: int, product_id: int, target_qty: int, ref: Ref) -> int:
        """盘点：将良品实物数量调整为 target_qty，返回差异。"""
        bal = self.balance(warehouse_id, product_id)
        diff = target_qty - bal.qty_on_hand
        if diff > 0:
            pc, fc = self.average_cost(warehouse_id, product_id)
            self.inbound(warehouse_id, product_id, diff, ref, change_type=LedgerType.STOCKTAKE_GAIN,
                         unit_purchase_cost=pc, unit_freight_cost=fc)
        elif diff < 0:
            if target_qty < bal.qty_locked:
                raise BizError(f"盘点数量 {target_qty} 小于已锁定数量 {bal.qty_locked}，请先处理待发货单据")
            self.outbound(warehouse_id, product_id, -diff, ref, change_type=LedgerType.STOCKTAKE_LOSS, allow_negative=False)
        return diff
