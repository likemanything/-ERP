/** 业务字典：状态 → [中文, 颜色] */
export type Dict = Record<string, [string, string?]>

export const ORDER_STATUS: Dict = {
  pending: ['待处理', 'default'],
  to_audit: ['待审核', 'orange'],
  to_ship: ['待发货', 'blue'],
  shipped: ['已发货', 'green'],
  delivered: ['已签收', 'cyan'],
  cancelled: ['已取消', 'red'],
}

export const PO_STATUS: Dict = {
  draft: ['草稿', 'default'],
  pending_approval: ['待审批', 'orange'],
  rejected: ['已驳回', 'red'],
  approved: ['待下单', 'geekblue'],
  ordered: ['待到货', 'blue'],
  partial: ['部分到货', 'purple'],
  received: ['已到货', 'green'],
  closed: ['已完结', 'cyan'],
  cancelled: ['已作废', 'default'],
}

export const PAYMENT_STATUS: Dict = {
  unpaid: ['未付款', 'default'],
  partial: ['部分付款', 'orange'],
  paid: ['已付清', 'green'],
}

export const PAYMENT_REQ_STATUS: Dict = {
  pending: ['待审批', 'orange'],
  approved: ['待付款', 'blue'],
  paid: ['已付款', 'green'],
  rejected: ['已驳回', 'red'],
  cancelled: ['已取消', 'default'],
}

export const PLAN_STATUS: Dict = {
  pending: ['待处理', 'orange'],
  converted: ['已生成单据', 'green'],
  cancelled: ['已作废', 'default'],
}

export const DOC_STATUS: Dict = {
  draft: ['草稿', 'default'],
  pending: ['待审核', 'orange'],
  in_transit: ['在途', 'blue'],
  completed: ['已完成', 'green'],
  cancelled: ['已作废', 'default'],
}

export const DOC_TYPE: Dict = {
  in: ['其他入库', 'green'],
  out: ['其他出库', 'orange'],
  transfer: ['调拨', 'blue'],
  stocktake: ['盘点', 'purple'],
}

export const SHIPMENT_STATUS: Dict = {
  draft: ['待发货', 'default'],
  shipped: ['在途', 'blue'],
  receiving: ['签收中', 'purple'],
  closed: ['已完成', 'green'],
  cancelled: ['已取消', 'default'],
}

export const RETURN_STATUS: Dict = {
  pending: ['待处理', 'orange'],
  completed: ['已完成', 'green'],
  cancelled: ['已取消', 'default'],
}

export const RETURN_TYPE: Dict = {
  return_refund: ['退货退款', 'blue'],
  refund_only: ['仅退款', 'orange'],
}

export const SHOP_STATUS: Dict = {
  active: ['正常', 'green'],
  disabled: ['停用', 'default'],
  auth_expired: ['授权失效', 'red'],
}

export const PRODUCT_STATUS: Dict = {
  new: ['新品', 'cyan'],
  on_sale: ['在售', 'green'],
  clearance: ['清仓', 'orange'],
  discontinued: ['停售', 'default'],
}

export const PRODUCT_TYPE: Dict = {
  normal: ['普通产品', 'default'],
  bundle: ['组合产品', 'purple'],
  auxiliary: ['辅料包材', 'gold'],
}

export const WAREHOUSE_TYPE: Dict = {
  local: ['本地仓', 'blue'],
  overseas: ['海外仓', 'purple'],
  fba: ['FBA仓', 'orange'],
  third_party: ['第三方仓', 'cyan'],
}

export const LEDGER_TYPE: Dict = {
  purchase_in: ['采购入库', 'green'],
  purchase_return: ['采购退货', 'orange'],
  sale_out: ['销售出库', 'blue'],
  return_in: ['退货入库', 'cyan'],
  transfer_out: ['调拨出库', 'orange'],
  transfer_in: ['调拨入库', 'green'],
  fba_out: ['头程出库', 'orange'],
  fba_in: ['头程签收', 'green'],
  other_in: ['其他入库', 'green'],
  other_out: ['其他出库', 'orange'],
  stocktake_gain: ['盘盈', 'green'],
  stocktake_loss: ['盘亏', 'red'],
  lock: ['锁定', 'purple'],
  unlock: ['释放锁定', 'default'],
  defective_in: ['次品入库', 'magenta'],
  defective_out: ['次品出库', 'magenta'],
  initial: ['期初', 'gold'],
}

export const SYNC_STATUS: Dict = {
  running: ['同步中', 'processing'],
  success: ['成功', 'success'],
  failed: ['失败', 'error'],
}

export const SYNC_JOB_TYPE: Dict = {
  orders: ['订单'],
  listings: ['Listing'],
  fba_inventory: ['FBA库存'],
  finances: ['交易明细'],
  ads: ['广告数据'],
}

export const TRANSPORT_MODE: Dict = {
  express: ['快递'],
  air: ['空运'],
  sea: ['海运'],
  fast_sea: ['快船'],
  rail: ['铁路'],
  truck: ['卡航'],
}

export const ALLOCATION_METHOD: Dict = {
  weight: ['按计费重'],
  volume: ['按体积'],
  quantity: ['按数量'],
  value: ['按货值'],
}

export const SETTLEMENT_TYPE: Dict = {
  cash: ['现结'],
  prepaid: ['预付'],
  monthly: ['月结'],
  half_monthly: ['半月结'],
}

export const PAY_TYPE: Dict = {
  prepay: ['预付款'],
  balance: ['尾款'],
  full: ['全款'],
}

export const CHANNEL_USAGE: Dict = {
  first_mile: ['头程'],
  last_mile: ['尾程/自发货'],
  both: ['通用'],
}

export const BILLING_TYPE: Dict = {
  weight: ['按重量'],
  volume: ['按体积'],
  piece: ['按件'],
}

export const PROVIDER_TYPE: Dict = {
  express: ['快递公司'],
  forwarder: ['货代'],
  postal: ['邮政'],
  platform: ['平台物流'],
}

export const PLATFORM: Dict = {
  amazon: ['亚马逊', 'orange'],
  shopify: ['Shopify', 'green'],
  walmart: ['沃尔玛', 'blue'],
  ebay: ['eBay', 'geekblue'],
  tiktok: ['TikTok', 'magenta'],
  temu: ['Temu', 'volcano'],
  shein: ['SHEIN', 'default'],
  aliexpress: ['速卖通', 'red'],
  manual: ['线下', 'default'],
  distribution: ['分销', 'purple'],
}

export const FULFILLMENT: Dict = {
  FBA: ['FBA', 'orange'],
  FBM: ['自发货', 'blue'],
}

export const LISTING_STATUS: Dict = {
  active: ['在售', 'green'],
  inactive: ['不可售', 'default'],
  incomplete: ['信息不全', 'orange'],
  deleted: ['已删除', 'red'],
}

export function dictOptions(d: Dict) {
  return Object.entries(d).map(([value, [label]]) => ({ value, label }))
}

export function dictLabel(d: Dict, v?: string | null): string {
  if (!v) return '-'
  return d[v]?.[0] ?? v
}

export const DISTRIBUTION_TYPE: Dict = {
  dropship: ['一件代发', 'blue'],
  wholesale: ['批发', 'purple'],
}

export const DISTRIBUTOR_STATUS: Dict = {
  active: ['正常', 'green'],
  disabled: ['停用', 'default'],
}

export const TXN_TYPE: Dict = {
  recharge: ['充值', 'green'],
  order: ['订单扣款', 'blue'],
  refund: ['退款', 'cyan'],
  adjust: ['调整', 'orange'],
}

export const RECHARGE_STATUS: Dict = {
  pending: ['待确认', 'orange'],
  approved: ['已到账', 'green'],
  rejected: ['已驳回', 'red'],
}

export const STOCK_DISPLAY: Dict = {
  real: ['显示真实库存', 'blue'],
  capped: ['显示上限', 'purple'],
  status: ['仅显示有货/缺货', 'default'],
}
