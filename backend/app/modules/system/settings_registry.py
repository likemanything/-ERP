"""企业级系统参数定义（键、默认值、说明）。"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SettingDef:
    key: str
    default: Any
    label: str
    description: str = ""


SETTING_DEFS: tuple[SettingDef, ...] = (
    SettingDef("purchase.require_approval", True, "采购单需要审批", "关闭后提交即自动审批通过"),
    SettingDef("payment.require_approval", True, "请款单需要审批", "关闭后提交即进入待付款"),
    SettingDef("inventory.allow_negative", False, "允许负库存出库", "本地仓出库时是否允许库存为负"),
    SettingDef("order.auto_audit", False, "自发货订单自动审核", "同步到的自发货订单自动分配仓库并锁定库存"),
    SettingDef("order.default_warehouse_id", None, "自发货默认发货仓", "自动审核时使用的仓库 ID"),
    SettingDef("fba.default_allocation", "weight", "头程费用默认分摊方式", "weight/volume/quantity/value"),
    SettingDef("inventory.low_stock_days", 15, "库存预警天数", "可售天数低于该值时首页预警"),
    SettingDef("finance.fee_estimate_commission_rate", 0.15, "预估佣金比例", "平台未结算前用于预估佣金"),
)

SETTING_MAP: dict[str, SettingDef] = {d.key: d for d in SETTING_DEFS}
