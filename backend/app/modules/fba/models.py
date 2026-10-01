from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, BigInteger, Boolean, Date, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import TenantModel
from app.core.types import MoneyColumn, UTCDateTime


class ShipmentPlan(TenantModel):
    """发货计划（运营提交，仓库据此创建货件）。"""

    __tablename__ = "shipment_plans"
    __table_args__ = (UniqueConstraint("tenant_id", "plan_no"),)

    plan_no: Mapped[str] = mapped_column(String(32))
    shop_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shops.id"), index=True)
    ship_from_warehouse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("warehouses.id"))
    to_warehouse_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("warehouses.id"), doc="目的仓：FBA 仓或海外仓")
    logistics_channel_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("logistics_channels.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    expected_ship_date: Mapped[date | None] = mapped_column(Date)
    shipment_id: Mapped[int | None] = mapped_column(BigInteger, doc="生成的货件")
    remark: Mapped[str | None] = mapped_column(String(500))

    lines: Mapped[list["ShipmentPlanLine"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", lazy="selectin"
    )


class ShipmentPlanLine(TenantModel):
    __tablename__ = "shipment_plan_lines"

    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipment_plans.id", ondelete="CASCADE"), index=True)
    listing_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("listings.id"))
    msku: Mapped[str | None] = mapped_column(String(128))
    fnsku: Mapped[str | None] = mapped_column(String(64))
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"))
    qty: Mapped[int] = mapped_column(Integer)

    plan: Mapped[ShipmentPlan] = relationship(back_populates="lines")


class FbaShipment(TenantModel):
    """头程货件（发往 FBA / 海外仓），含头程费用分摊。"""

    __tablename__ = "fba_shipments"
    __table_args__ = (UniqueConstraint("tenant_id", "shipment_no"),)

    shipment_no: Mapped[str] = mapped_column(String(32))
    platform_shipment_id: Mapped[str | None] = mapped_column(String(64), index=True, doc="FBA 货件号，如 FBA15XXXX")
    shop_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shops.id"), index=True)
    plan_id: Mapped[int | None] = mapped_column(BigInteger)
    ship_from_warehouse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("warehouses.id"))
    to_warehouse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("warehouses.id"))
    destination_fc: Mapped[str | None] = mapped_column(String(32), doc="目的仓库代码，如 ONT8")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    logistics_channel_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("logistics_channels.id"))
    tracking_no: Mapped[str | None] = mapped_column(String(128))
    ship_date: Mapped[date | None] = mapped_column(Date)
    eta: Mapped[date | None] = mapped_column(Date)
    shipped_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    box_count: Mapped[int] = mapped_column(Integer, default=0)
    total_weight_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0, doc="实重")
    total_volume_cbm: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)
    chargeable_weight_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    boxes: Mapped[list | None] = mapped_column(JSON, doc="装箱信息 [{box_no,weight_kg,length_cm,width_cm,height_cm,items:[{msku,qty}]}]")
    cost_currency: Mapped[str] = mapped_column(String(8), default="CNY")
    freight_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="头程运费")
    customs_duty: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="关税")
    other_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="其他费用（报关、清关、送仓等）")
    allocation_method: Mapped[str] = mapped_column(String(16), default="weight")
    cost_allocated: Mapped[bool] = mapped_column(Boolean, default=False, doc="头程费用是否已分摊")
    remark: Mapped[str | None] = mapped_column(String(500))

    lines: Mapped[list["FbaShipmentLine"]] = relationship(
        back_populates="shipment", cascade="all, delete-orphan", lazy="selectin", order_by="FbaShipmentLine.id"
    )


class FbaShipmentLine(TenantModel):
    __tablename__ = "fba_shipment_lines"

    shipment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fba_shipments.id", ondelete="CASCADE"), index=True)
    listing_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("listings.id"))
    msku: Mapped[str | None] = mapped_column(String(128))
    fnsku: Mapped[str | None] = mapped_column(String(64))
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"))
    qty_shipped: Mapped[int] = mapped_column(Integer)
    qty_received: Mapped[int] = mapped_column(Integer, default=0)
    unit_weight_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    unit_volume_cbm: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0)
    unit_purchase_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="出库时 FIFO 采购成本（本位币）")
    unit_freight_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="出库仓已有的物流成本 + 本次头程分摊")
    allocated_cost: Mapped[Decimal] = mapped_column(MoneyColumn, default=0, doc="本行分摊的头程费用合计（本位币）")

    shipment: Mapped[FbaShipment] = relationship(back_populates="lines")


class FbaInventory(TenantModel):
    """平台仓库存快照（来自 FBA 库存报告/API）。"""

    __tablename__ = "fba_inventory"
    __table_args__ = (UniqueConstraint("tenant_id", "shop_id", "msku"),)

    shop_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shops.id"), index=True)
    msku: Mapped[str] = mapped_column(String(128))
    fnsku: Mapped[str | None] = mapped_column(String(64))
    asin: Mapped[str | None] = mapped_column(String(64))
    listing_id: Mapped[int | None] = mapped_column(BigInteger)
    product_id: Mapped[int | None] = mapped_column(BigInteger)
    fulfillable: Mapped[int] = mapped_column(Integer, default=0, doc="可售")
    inbound_working: Mapped[int] = mapped_column(Integer, default=0, doc="计划入库")
    inbound_shipped: Mapped[int] = mapped_column(Integer, default=0, doc="在途")
    inbound_receiving: Mapped[int] = mapped_column(Integer, default=0, doc="入库中")
    reserved: Mapped[int] = mapped_column(Integer, default=0, doc="预留（调仓/待发）")
    unfulfillable: Mapped[int] = mapped_column(Integer, default=0, doc="不可售")
    snapshot_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    @property
    def inbound_total(self) -> int:
        return (self.inbound_working or 0) + (self.inbound_shipped or 0) + (self.inbound_receiving or 0)
