from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import TenantModel
from app.core.types import MoneyColumn, UTCDateTime, utcnow


class Warehouse(TenantModel):
    __tablename__ = "warehouses"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    warehouse_type: Mapped[str] = mapped_column(String(16), default="local", index=True)
    country: Mapped[str | None] = mapped_column(String(16))
    address: Mapped[str | None] = mapped_column(String(255))
    contact: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(32))
    shop_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("shops.id"), doc="FBA 虚拟仓所属店铺")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="active")
    remark: Mapped[str | None] = mapped_column(String(500))


class WarehouseBin(TenantModel):
    """库位。"""

    __tablename__ = "warehouse_bins"
    __table_args__ = (UniqueConstraint("warehouse_id", "code"),)

    warehouse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("warehouses.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    zone: Mapped[str | None] = mapped_column(String(32))
    bin_type: Mapped[str] = mapped_column(String(16), default="storage", doc="storage/pick/defective/receiving")
    status: Mapped[str] = mapped_column(String(16), default="active")
    remark: Mapped[str | None] = mapped_column(String(255))


class InventoryBalance(TenantModel):
    """仓库 + SKU 维度的实时库存。可用量 = qty_on_hand - qty_locked。"""

    __tablename__ = "inventory_balances"
    __table_args__ = (UniqueConstraint("warehouse_id", "product_id"),)

    warehouse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("warehouses.id"), index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), index=True)
    qty_on_hand: Mapped[int] = mapped_column(Integer, default=0, doc="良品实物库存")
    qty_locked: Mapped[int] = mapped_column(Integer, default=0, doc="已锁定（待出库）")
    qty_defective: Mapped[int] = mapped_column(Integer, default=0, doc="次品库存")
    qty_in_transit: Mapped[int] = mapped_column(Integer, default=0, doc="调拨在途（将入本仓）")
    bin_code: Mapped[str | None] = mapped_column(String(32), doc="默认库位")
    safety_stock: Mapped[int] = mapped_column(Integer, default=0, doc="安全库存，低于则预警")

    @property
    def qty_available(self) -> int:
        return (self.qty_on_hand or 0) - (self.qty_locked or 0)


class InventoryBatch(TenantModel):
    """批次 / 成本层（先进先出计价）。单位成本均为本位币。"""

    __tablename__ = "inventory_batches"
    __table_args__ = (Index("ix_inventory_batches_fifo", "warehouse_id", "product_id", "qty_remaining"),)

    warehouse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("warehouses.id"), index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), index=True)
    batch_no: Mapped[str] = mapped_column(String(64), index=True)
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[int | None] = mapped_column(BigInteger)
    source_no: Mapped[str | None] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    qty_in: Mapped[int] = mapped_column(Integer)
    qty_remaining: Mapped[int] = mapped_column(Integer)
    unit_purchase_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="单位采购成本")
    unit_freight_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="单位头程/物流成本")
    supplier_id: Mapped[int | None] = mapped_column(BigInteger)
    purchase_order_id: Mapped[int | None] = mapped_column(BigInteger)

    @property
    def unit_cost(self) -> Decimal:
        return (self.unit_purchase_cost or Decimal(0)) + (self.unit_freight_cost or Decimal(0))


class InventoryLedger(TenantModel):
    """库存流水。"""

    __tablename__ = "inventory_ledger"
    __table_args__ = (Index("ix_inventory_ledger_wh_product", "warehouse_id", "product_id"),)

    warehouse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("warehouses.id"))
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"))
    batch_id: Mapped[int | None] = mapped_column(BigInteger)
    change_type: Mapped[str] = mapped_column(String(32), index=True)
    stock_type: Mapped[str] = mapped_column(String(16), default="good", doc="good/defective/locked")
    qty_change: Mapped[int] = mapped_column(Integer)
    qty_after: Mapped[int] = mapped_column(Integer, doc="变动后该库存类型数量")
    unit_purchase_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    unit_freight_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    amount: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="变动金额（本位币）")
    ref_type: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[int | None] = mapped_column(BigInteger)
    ref_no: Mapped[str | None] = mapped_column(String(64), index=True)
    biz_date: Mapped[date] = mapped_column(Date, default=lambda: utcnow().date(), index=True)
    remark: Mapped[str | None] = mapped_column(String(255))


class StockDocument(TenantModel):
    """库存单据：其他入库 / 其他出库 / 调拨 / 盘点。"""

    __tablename__ = "stock_documents"
    __table_args__ = (UniqueConstraint("tenant_id", "doc_no"),)

    doc_no: Mapped[str] = mapped_column(String(32))
    doc_type: Mapped[str] = mapped_column(String(16), index=True)
    biz_type: Mapped[str | None] = mapped_column(String(32), doc="业务类型：样品/报损/赠品/期初等")
    warehouse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("warehouses.id"), index=True)
    to_warehouse_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("warehouses.id"))
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    stock_type: Mapped[str] = mapped_column(String(16), default="good")
    logistics_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    tracking_no: Mapped[str | None] = mapped_column(String(64))
    freight_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="调拨运费（本位币），按数量分摊入目的仓成本")
    shipped_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    approved_by: Mapped[int | None] = mapped_column(BigInteger)
    remark: Mapped[str | None] = mapped_column(String(500))

    lines: Mapped[list["StockDocumentLine"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", lazy="selectin", order_by="StockDocumentLine.id"
    )


class StockDocumentLine(TenantModel):
    __tablename__ = "stock_document_lines"

    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stock_documents.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"))
    qty: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="入库单价（本位币）；调拨为出库成本")
    unit_freight_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0)
    qty_received: Mapped[int] = mapped_column(Integer, default=0, doc="调拨实收")
    system_qty: Mapped[int | None] = mapped_column(Integer, doc="盘点：账面数量")
    counted_qty: Mapped[int | None] = mapped_column(Integer, doc="盘点：实盘数量")
    remark: Mapped[str | None] = mapped_column(String(255))

    document: Mapped[StockDocument] = relationship(back_populates="lines")
