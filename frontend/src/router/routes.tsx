import { lazy, type ComponentType, type LazyExoticComponent, type ReactNode } from 'react'
import {
  AccountBookOutlined,
  AppstoreOutlined,
  BarChartOutlined,
  CarOutlined,
  DashboardOutlined,
  InboxOutlined,
  RocketOutlined,
  SettingOutlined,
  ShopOutlined,
  ShoppingCartOutlined,
  ShoppingOutlined,
  SoundOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'

type Page = LazyExoticComponent<ComponentType>

export interface RouteItem {
  path: string
  label: string
  perm?: string | string[]
  element: Page
  hideInMenu?: boolean
}

export interface MenuGroup {
  key: string
  label: string
  icon: ReactNode
  children: RouteItem[]
}

const p = (loader: () => Promise<{ default: ComponentType }>) => lazy(loader)

export const MENU: MenuGroup[] = [
  {
    key: 'home', label: '首页', icon: <DashboardOutlined />,
    children: [{ path: '/dashboard', label: '数据看板', perm: 'dashboard:view', element: p(() => import('@/pages/Dashboard')) }],
  },
  {
    key: 'sales', label: '销售', icon: <ShoppingCartOutlined />,
    children: [
      { path: '/orders', label: '订单管理', perm: 'order:view', element: p(() => import('@/pages/order/Orders')) },
      { path: '/orders/fbm', label: '自发货处理', perm: 'order:view', element: p(() => import('@/pages/order/FbmOrders')) },
      { path: '/returns', label: '退货退款', perm: 'return:view', element: p(() => import('@/pages/order/Returns')) },
      { path: '/listings', label: 'Listing 管理', perm: 'listing:view', element: p(() => import('@/pages/product/Listings')) },
    ],
  },
  {
    key: 'product', label: '产品', icon: <AppstoreOutlined />,
    children: [
      { path: '/products', label: '产品管理', perm: 'product:view', element: p(() => import('@/pages/product/Products')) },
      { path: '/product-categories', label: '分类与品牌', perm: 'product:view', element: p(() => import('@/pages/product/Categories')) },
    ],
  },
  {
    key: 'purchase', label: '采购', icon: <ShoppingOutlined />,
    children: [
      { path: '/purchase/plans', label: '采购计划', perm: 'purchase:plan:view', element: p(() => import('@/pages/purchase/Plans')) },
      { path: '/purchase/orders', label: '采购单', perm: 'purchase:order:view', element: p(() => import('@/pages/purchase/PurchaseOrders')) },
      { path: '/purchase/receipts', label: '采购入库单', perm: 'purchase:order:view', element: p(() => import('@/pages/purchase/Receipts')) },
      { path: '/purchase/returns', label: '采购退货', perm: 'purchase:order:view', element: p(() => import('@/pages/purchase/PurchaseReturns')) },
      { path: '/purchase/payments', label: '请款付款', perm: 'purchase:payment:view', element: p(() => import('@/pages/purchase/Payments')) },
      { path: '/purchase/payables', label: '应付账款', perm: 'purchase:payment:view', element: p(() => import('@/pages/purchase/Payables')) },
      { path: '/suppliers', label: '供应商', perm: 'supplier:view', element: p(() => import('@/pages/purchase/Suppliers')) },
    ],
  },
  {
    key: 'warehouse', label: '仓库', icon: <InboxOutlined />,
    children: [
      { path: '/inventory', label: '库存查询', perm: 'inventory:view', element: p(() => import('@/pages/warehouse/Inventory')) },
      { path: '/stock-documents', label: '出入库单', perm: 'inventory:doc:view', element: p(() => import('@/pages/warehouse/StockDocuments')) },
      { path: '/inventory/ledger', label: '库存流水', perm: 'inventory:ledger:view', element: p(() => import('@/pages/warehouse/Ledger')) },
      { path: '/inventory/batches', label: '批次与库龄', perm: 'inventory:view', element: p(() => import('@/pages/warehouse/Batches')) },
      { path: '/warehouses', label: '仓库设置', perm: 'warehouse:view', element: p(() => import('@/pages/warehouse/Warehouses')) },
    ],
  },
  {
    key: 'fba', label: 'FBA', icon: <RocketOutlined />,
    children: [
      { path: '/fba/plans', label: '发货计划', perm: 'fba:plan:view', element: p(() => import('@/pages/fba/ShipmentPlans')) },
      { path: '/fba/shipments', label: '头程货件', perm: 'fba:shipment:view', element: p(() => import('@/pages/fba/Shipments')) },
      { path: '/fba/inventory', label: 'FBA 库存', perm: 'fba:inventory:view', element: p(() => import('@/pages/fba/FbaInventory')) },
    ],
  },
  {
    key: 'replenish', label: '补货', icon: <ThunderboltOutlined />,
    children: [
      { path: '/replenish/ship', label: 'FBA 发货建议', perm: 'replenish:view', element: p(() => import('@/pages/replenish/ShipSuggest')) },
      { path: '/replenish/purchase', label: '采购建议', perm: 'replenish:view', element: p(() => import('@/pages/replenish/PurchaseSuggest')) },
    ],
  },
  {
    key: 'logistics', label: '物流', icon: <CarOutlined />,
    children: [{ path: '/logistics', label: '物流商与渠道', perm: 'logistics:view', element: p(() => import('@/pages/logistics/Logistics')) }],
  },
  {
    key: 'finance', label: '财务', icon: <AccountBookOutlined />,
    children: [
      { path: '/finance/profit', label: '利润报表', perm: 'finance:profit:view', element: p(() => import('@/pages/finance/Profit')) },
      { path: '/finance/transactions', label: '结算明细', perm: 'finance:transaction:view', element: p(() => import('@/pages/finance/Transactions')) },
      { path: '/finance/expenses', label: '费用管理', perm: 'finance:expense:view', element: p(() => import('@/pages/finance/Expenses')) },
      { path: '/finance/valuation', label: '库存估值', perm: 'finance:valuation:view', element: p(() => import('@/pages/finance/Valuation')) },
      { path: '/finance/rates', label: '汇率管理', perm: 'finance:rate:view', element: p(() => import('@/pages/finance/Rates')) },
    ],
  },
  {
    key: 'ads', label: '广告', icon: <SoundOutlined />,
    children: [{ path: '/ads', label: '广告分析', perm: 'ads:view', element: p(() => import('@/pages/ads/Ads')) }],
  },
  {
    key: 'report', label: '报表', icon: <BarChartOutlined />,
    children: [
      { path: '/reports/sales', label: '销售统计', perm: 'report:view', element: p(() => import('@/pages/report/SalesReport')) },
      { path: '/reports/aging', label: '库龄分析', perm: 'inventory:view', element: p(() => import('@/pages/report/Aging')) },
      { path: '/reports/turnover', label: '库存周转', perm: 'inventory:view', element: p(() => import('@/pages/report/Turnover')) },
    ],
  },
  {
    key: 'shop', label: '店铺', icon: <ShopOutlined />,
    children: [
      { path: '/shops', label: '店铺授权', perm: 'shop:view', element: p(() => import('@/pages/shop/Shops')) },
      { path: '/sync-jobs', label: '同步记录', perm: 'shop:view', element: p(() => import('@/pages/shop/SyncJobs')) },
    ],
  },
  {
    key: 'system', label: '系统', icon: <SettingOutlined />,
    children: [
      { path: '/system/users', label: '用户管理', perm: 'system:user', element: p(() => import('@/pages/system/Users')) },
      { path: '/system/roles', label: '角色权限', perm: 'system:role', element: p(() => import('@/pages/system/Roles')) },
      { path: '/system/departments', label: '部门管理', perm: 'system:dept', element: p(() => import('@/pages/system/Departments')) },
      { path: '/system/logs', label: '操作日志', perm: 'system:log', element: p(() => import('@/pages/system/AuditLogs')) },
      { path: '/system/settings', label: '系统参数', perm: 'system:setting', element: p(() => import('@/pages/system/Settings')) },
    ],
  },
]

export const ALL_ROUTES: RouteItem[] = MENU.flatMap((g) => g.children)
