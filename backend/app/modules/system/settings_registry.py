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
    # ---- 分销
    SettingDef("distribution.warehouse_ids", [], "分销发货仓", "分销商品可售库存与发货的仓库 ID 列表，为空表示全部本地/海外仓"),
    SettingDef("distribution.channel_ids", [], "分销可选物流渠道", "分销商下单可选的物流渠道 ID 列表，为空表示全部尾程渠道"),
    SettingDef("distribution.handling_fee_per_order", 0, "代发操作费（每单，本位币）", "一件代发订单按单收取"),
    SettingDef("distribution.handling_fee_per_item", 0, "代发操作费（每件，本位币）", "一件代发订单按件收取"),
    SettingDef("distribution.freight_markup_rate", 0, "运费加价比例", "如 0.1 表示在渠道运费基础上加收 10%"),
    SettingDef("distribution.auto_audit", True, "分销订单自动审核", "分销商下单后自动分配仓库并锁定库存"),
    SettingDef("distribution.allow_cancel_after_audit", True, "允许分销商取消已审核订单", "未发货前分销商可自行取消并退款"),
)

SETTING_MAP: dict[str, SettingDef] = {d.key: d for d in SETTING_DEFS}
