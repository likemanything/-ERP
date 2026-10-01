"""业务枚举。数据库中以字符串存储，便于迁移与跨数据库兼容。"""

from enum import StrEnum


class Platform(StrEnum):
    AMAZON = "amazon"
    SHOPIFY = "shopify"
    WALMART = "walmart"
    EBAY = "ebay"
    TIKTOK = "tiktok"
    TEMU = "temu"
    SHEIN = "shein"
    ALIEXPRESS = "aliexpress"
    MANUAL = "manual"  # 手工/线下店铺


class ShopStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    AUTH_EXPIRED = "auth_expired"


class ProductType(StrEnum):
    NORMAL = "normal"  # 普通产品
    BUNDLE = "bundle"  # 组合产品
    AUXILIARY = "auxiliary"  # 辅料/包材


class ProductStatus(StrEnum):
    NEW = "new"  # 新品
    ON_SALE = "on_sale"  # 在售
    CLEARANCE = "clearance"  # 清仓
    DISCONTINUED = "discontinued"  # 停售


class Fulfillment(StrEnum):
    FBA = "FBA"  # 平台仓发货
    FBM = "FBM"  # 自发货


class WarehouseType(StrEnum):
    LOCAL = "local"  # 本地仓
    OVERSEAS = "overseas"  # 海外仓
    FBA = "fba"  # FBA 虚拟仓
    THIRD_PARTY = "third_party"  # 第三方仓


class StockType(StrEnum):
    GOOD = "good"  # 良品
    DEFECTIVE = "defective"  # 次品


class LedgerType(StrEnum):
    PURCHASE_IN = "purchase_in"  # 采购入库
    PURCHASE_RETURN = "purchase_return"  # 采购退货出库
    SALE_OUT = "sale_out"  # 销售出库
    RETURN_IN = "return_in"  # 销售退货入库
    TRANSFER_OUT = "transfer_out"  # 调拨出库
    TRANSFER_IN = "transfer_in"  # 调拨入库
    FBA_OUT = "fba_out"  # FBA 发货出库
    FBA_IN = "fba_in"  # FBA 签收入库
    OTHER_IN = "other_in"  # 其他入库
    OTHER_OUT = "other_out"  # 其他出库
    STOCKTAKE_GAIN = "stocktake_gain"  # 盘盈
    STOCKTAKE_LOSS = "stocktake_loss"  # 盘亏
    LOCK = "lock"  # 锁定
    UNLOCK = "unlock"  # 释放锁定
    DEFECTIVE_IN = "defective_in"  # 次品入库
    DEFECTIVE_OUT = "defective_out"  # 次品出库
    ASSEMBLY_IN = "assembly_in"  # 组装入库
    ASSEMBLY_OUT = "assembly_out"  # 组装耗用
    INITIAL = "initial"  # 期初


class DocStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"  # 待审核
    IN_TRANSIT = "in_transit"  # 在途（调拨）
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class StockDocType(StrEnum):
    IN = "in"  # 其他入库
    OUT = "out"  # 其他出库
    TRANSFER = "transfer"  # 调拨
    STOCKTAKE = "stocktake"  # 盘点


class PurchaseStatus(StrEnum):
    DRAFT = "draft"  # 草稿
    PENDING_APPROVAL = "pending_approval"  # 待审批
    REJECTED = "rejected"  # 已驳回
    APPROVED = "approved"  # 待下单
    ORDERED = "ordered"  # 已下单（待到货）
    PARTIAL = "partial"  # 部分到货
    RECEIVED = "received"  # 全部到货
    CLOSED = "closed"  # 已完结（手动结单）
    CANCELLED = "cancelled"  # 已作废


class PaymentStatus(StrEnum):
    UNPAID = "unpaid"
    PARTIAL = "partial"
    PAID = "paid"


class PaymentRequestStatus(StrEnum):
    PENDING = "pending"  # 待审批
    APPROVED = "approved"  # 待付款
    PAID = "paid"  # 已付款
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class PlanStatus(StrEnum):
    PENDING = "pending"  # 待处理
    CONVERTED = "converted"  # 已生成单据
    CANCELLED = "cancelled"


class OrderStatus(StrEnum):
    PENDING = "pending"  # 待付款 / 平台处理中
    TO_AUDIT = "to_audit"  # 待审核
    TO_SHIP = "to_ship"  # 待发货（已审核、已锁库存）
    SHIPPED = "shipped"  # 已发货
    DELIVERED = "delivered"  # 已签收/完成
    CANCELLED = "cancelled"  # 已取消


class ReturnStatus(StrEnum):
    PENDING = "pending"  # 待处理
    COMPLETED = "completed"  # 已完成
    CANCELLED = "cancelled"


class ShipmentStatus(StrEnum):
    DRAFT = "draft"  # 待发货
    SHIPPED = "shipped"  # 已发货（在途）
    RECEIVING = "receiving"  # 签收中
    CLOSED = "closed"  # 已完成
    CANCELLED = "cancelled"


class AllocationMethod(StrEnum):
    WEIGHT = "weight"  # 按计费重
    VOLUME = "volume"  # 按体积
    QUANTITY = "quantity"  # 按数量
    VALUE = "value"  # 按货值


class TransportMode(StrEnum):
    EXPRESS = "express"  # 快递
    AIR = "air"  # 空运
    SEA = "sea"  # 海运
    FAST_SEA = "fast_sea"  # 快船
    RAIL = "rail"  # 铁路
    TRUCK = "truck"  # 卡航
