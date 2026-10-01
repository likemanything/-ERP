"""权限点注册表。

权限编码格式 ``模块:资源:动作``，角色保存权限编码列表；
企业管理员（is_superuser）拥有全部权限。前端依据权限编码控制菜单与按钮。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Perm:
    code: str
    name: str


@dataclass(frozen=True)
class PermGroup:
    key: str
    name: str
    perms: tuple[Perm, ...]


def _g(key: str, name: str, *items: tuple[str, str]) -> PermGroup:
    return PermGroup(key, name, tuple(Perm(c, n) for c, n in items))


PERMISSION_GROUPS: tuple[PermGroup, ...] = (
    _g("dashboard", "首页", ("dashboard:view", "查看首页看板")),
    _g(
        "shop",
        "店铺授权",
        ("shop:view", "查看店铺"),
        ("shop:edit", "新增/编辑店铺"),
        ("shop:sync", "手动同步店铺数据"),
    ),
    _g(
        "product",
        "产品管理",
        ("product:view", "查看产品"),
        ("product:edit", "新增/编辑产品"),
        ("product:delete", "删除产品"),
        ("product:cost:view", "查看采购成本"),
    ),
    _g(
        "listing",
        "Listing 管理",
        ("listing:view", "查看 Listing"),
        ("listing:edit", "编辑 Listing / SKU 配对"),
    ),
    _g(
        "order",
        "订单管理",
        ("order:view", "查看订单"),
        ("order:edit", "新增/编辑订单"),
        ("order:audit", "审核订单"),
        ("order:ship", "订单发货"),
        ("order:cancel", "取消订单"),
        ("return:view", "查看退货"),
        ("return:edit", "处理退货"),
    ),
    _g(
        "supplier",
        "供应商",
        ("supplier:view", "查看供应商"),
        ("supplier:edit", "新增/编辑供应商"),
    ),
    _g(
        "purchase",
        "采购管理",
        ("purchase:plan:view", "查看采购计划"),
        ("purchase:plan:edit", "编辑采购计划"),
        ("purchase:order:view", "查看采购单"),
        ("purchase:order:edit", "新增/编辑采购单"),
        ("purchase:order:approve", "审批采购单"),
        ("purchase:receive", "采购到货/质检入库"),
        ("purchase:return", "采购退货"),
        ("purchase:payment:view", "查看请款/付款"),
        ("purchase:payment:edit", "发起请款"),
        ("purchase:payment:approve", "审批/确认付款"),
    ),
    _g(
        "warehouse",
        "仓库管理",
        ("warehouse:view", "查看仓库"),
        ("warehouse:edit", "新增/编辑仓库与库位"),
        ("inventory:view", "查看库存"),
        ("inventory:doc:view", "查看出入库单"),
        ("inventory:doc:edit", "新增/编辑出入库单"),
        ("inventory:doc:approve", "审核出入库单（过账）"),
        ("inventory:assembly", "加工单（组装 / 拆分）"),
        ("inventory:ledger:view", "查看库存流水"),
    ),
    _g(
        "fba",
        "FBA 管理",
        ("fba:plan:view", "查看发货计划"),
        ("fba:plan:edit", "编辑发货计划"),
        ("fba:shipment:view", "查看 FBA 货件"),
        ("fba:shipment:edit", "编辑 FBA 货件/发货"),
        ("fba:inventory:view", "查看 FBA 库存"),
    ),
    _g(
        "replenish",
        "补货建议",
        ("replenish:view", "查看补货建议"),
        ("replenish:edit", "设置补货参数/生成计划"),
    ),
    _g(
        "logistics",
        "物流管理",
        ("logistics:view", "查看物流商/渠道"),
        ("logistics:edit", "编辑物流商/渠道"),
    ),
    _g(
        "finance",
        "财务管理",
        ("finance:profit:view", "查看利润报表"),
        ("finance:transaction:view", "查看平台交易/结算"),
        ("finance:transaction:edit", "导入平台交易"),
        ("finance:expense:view", "查看费用"),
        ("finance:expense:edit", "编辑费用"),
        ("finance:rate:view", "查看汇率"),
        ("finance:rate:edit", "编辑汇率"),
        ("finance:valuation:view", "查看库存估值"),
    ),
    _g(
        "distribution",
        "分销管理",
        ("distribution:view", "查看分销商/分销商品/分销订单"),
        ("distribution:edit", "维护分销商、等级、分销商品与价格"),
        ("distribution:account", "开通/管理分销商登录账号"),
        ("distribution:finance", "分销资金：充值审核、余额调整、对账"),
        ("distribution:setting", "分销参数设置"),
    ),
    _g(
        "ads",
        "广告管理",
        ("ads:view", "查看广告数据"),
        ("ads:edit", "导入/编辑广告数据"),
    ),
    _g("report", "数据报表", ("report:view", "查看数据报表")),
    _g(
        "system",
        "系统设置",
        ("system:user", "用户管理"),
        ("system:role", "角色权限"),
        ("system:dept", "部门管理"),
        ("system:log", "操作日志"),
        ("system:setting", "系统参数"),
        ("system:approval", "审批流程配置"),
    ),
)

ALL_PERMISSION_CODES: frozenset[str] = frozenset(p.code for g in PERMISSION_GROUPS for p in g.perms)


def permission_tree() -> list[dict]:
    return [
        {"key": g.key, "name": g.name, "children": [{"code": p.code, "name": p.name} for p in g.perms]}
        for g in PERMISSION_GROUPS
    ]


# 预置角色模板，创建企业时自动生成
PRESET_ROLES: dict[str, tuple[str, list[str]]] = {
    "operator": (
        "运营",
        [
            "dashboard:view", "shop:view", "product:view", "listing:view", "listing:edit", "order:view",
            "return:view", "fba:plan:view", "fba:plan:edit", "fba:shipment:view", "fba:inventory:view",
            "replenish:view", "replenish:edit", "inventory:view", "finance:profit:view", "ads:view", "ads:edit",
            "report:view", "purchase:plan:view", "purchase:plan:edit",
        ],
    ),
    "purchaser": (
        "采购",
        [
            "dashboard:view", "product:view", "product:cost:view", "supplier:view", "supplier:edit",
            "purchase:plan:view", "purchase:plan:edit", "purchase:order:view", "purchase:order:edit",
            "purchase:receive", "purchase:return", "purchase:payment:view", "purchase:payment:edit",
            "inventory:view", "replenish:view",
        ],
    ),
    "warehouse": (
        "仓管",
        [
            "dashboard:view", "product:view", "warehouse:view", "inventory:view", "inventory:doc:view",
            "inventory:doc:edit", "inventory:assembly", "inventory:ledger:view", "purchase:order:view", "purchase:receive",
            "order:view", "order:ship", "fba:shipment:view", "fba:shipment:edit", "logistics:view",
        ],
    ),
    "finance": (
        "财务",
        [
            "dashboard:view", "finance:profit:view", "finance:transaction:view", "finance:transaction:edit",
            "finance:expense:view", "finance:expense:edit", "finance:rate:view", "finance:rate:edit",
            "finance:valuation:view", "purchase:payment:view", "purchase:payment:approve", "product:cost:view",
            "report:view", "ads:view", "distribution:view", "distribution:finance",
        ],
    ),
    "distribution": (
        "分销专员",
        [
            "dashboard:view", "product:view", "inventory:view", "order:view", "order:audit", "order:cancel",
            "logistics:view", "distribution:view", "distribution:edit", "distribution:account",
        ],
    ),
}
