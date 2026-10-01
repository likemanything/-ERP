import { Descriptions, Drawer, Space, Table, Tag, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import StatusTag from '@/components/StatusTag'
import ProductCell from '@/components/ProductCell'
import { useBaseCurrency } from '@/store/auth'
import { FULFILLMENT, ORDER_STATUS, PLATFORM } from '@/utils/dicts'
import { fmtDate, fmtDateTime, fmtMoney, profitColor } from '@/utils/format'

type Order = Record<string, any>

export default function OrderDetail({ orderId, onClose }: { orderId: number | null; onClose: () => void }) {
  const cur = useBaseCurrency()
  const { data: o } = useQuery({
    queryKey: ['order', orderId],
    queryFn: () => api.get<Order>(`/orders/${orderId}`),
    enabled: !!orderId,
  })
  return (
    <Drawer open={!!orderId} onClose={onClose} size={980} title={o ? `订单 ${o.platform_order_id}` : '订单详情'} destroyOnHidden>
      {o && (
        <Space orientation="vertical" style={{ width: '100%' }} size="large">
          <Descriptions size="small" bordered column={3}>
            <Descriptions.Item label="系统单号">{o.order_no}</Descriptions.Item>
            <Descriptions.Item label="店铺"><Space><StatusTag dict={PLATFORM} value={o.platform} />{o.shop_name}</Space></Descriptions.Item>
            <Descriptions.Item label="状态">
              <Space>
                <StatusTag dict={ORDER_STATUS} value={o.status} />
                <StatusTag dict={FULFILLMENT} value={o.fulfillment} />
                {o.is_on_hold && <Tag color="red">挂起</Tag>}
                {(o.tags ?? []).map((t: string) => <Tag key={t} color="volcano">{t}</Tag>)}
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="下单时间">{fmtDateTime(o.purchase_at)}</Descriptions.Item>
            <Descriptions.Item label="站点日期">{fmtDate(o.local_date)}</Descriptions.Item>
            <Descriptions.Item label="平台状态">{o.platform_status ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="买家">{o.buyer_name ?? '-'} {o.buyer_email && <Typography.Text type="secondary">({o.buyer_email})</Typography.Text>}</Descriptions.Item>
            <Descriptions.Item label="收件人">{o.ship_name ?? '-'} {o.ship_phone ?? ''}</Descriptions.Item>
            <Descriptions.Item label="国家/地区">{[o.ship_country, o.ship_state, o.ship_city].filter(Boolean).join(' / ') || '-'}</Descriptions.Item>
            <Descriptions.Item label="收货地址" span={3}>
              {[o.ship_address1, o.ship_address2, o.ship_postcode].filter(Boolean).join(', ') || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="发货仓">{o.warehouse_name ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="物流">{o.logistics_channel_name ?? o.carrier ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="运单号">{o.tracking_no ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="发货时间">{fmtDateTime(o.shipped_at)}</Descriptions.Item>
            <Descriptions.Item label="预估运费">{fmtMoney(o.est_freight, cur)}</Descriptions.Item>
            <Descriptions.Item label="实际运费">{fmtMoney(o.actual_freight, cur)}</Descriptions.Item>
            <Descriptions.Item label="订单金额">{fmtMoney(o.total_amount, o.currency)}</Descriptions.Item>
            <Descriptions.Item label="预估利润">
              <span style={{ color: profitColor(o.est_profit), fontWeight: 600 }}>{fmtMoney(o.est_profit, cur)}</span>
            </Descriptions.Item>
            <Descriptions.Item label="备注">{o.remark ?? '-'}</Descriptions.Item>
            {o.buyer_note && <Descriptions.Item label="买家留言" span={3}>{o.buyer_note}</Descriptions.Item>}
            {o.cancel_reason && <Descriptions.Item label="取消原因" span={3}>{o.cancel_reason}</Descriptions.Item>}
          </Descriptions>
          <Table<Record<string, any>>
            size="small"
            rowKey="id"
            pagination={false}
            dataSource={o.items}
            scroll={{ x: 'max-content' }}
            columns={[
              { title: '商品', render: (_, i) => <ProductCell image={i.image_url} title={i.msku} sub={i.title} extra={i.sku ? `SKU ${i.sku}` : '未配对'} /> },
              { title: '数量', dataIndex: 'quantity', align: 'right' },
              { title: '商品金额', dataIndex: 'item_amount', align: 'right', render: (v) => fmtMoney(v, o.currency) },
              { title: '运费', dataIndex: 'shipping_amount', align: 'right', render: (v) => fmtMoney(v, o.currency) },
              { title: '折扣', dataIndex: 'discount_amount', align: 'right', render: (v) => fmtMoney(v, o.currency) },
              {
                title: '佣金', dataIndex: 'commission_fee', align: 'right',
                render: (v, i) => <span>{fmtMoney(v, o.currency)}{i.fee_estimated && <Tag style={{ marginLeft: 4 }}>预估</Tag>}</span>,
              },
              { title: 'FBA费', dataIndex: 'fulfillment_fee', align: 'right', render: (v) => fmtMoney(v, o.currency) },
              { title: '退款', dataIndex: 'refund_amount', align: 'right', render: (v, i) => (v ? `${fmtMoney(v, o.currency)} (${i.refund_qty}件)` : '-') },
              { title: '采购成本', dataIndex: 'cost_purchase', align: 'right', render: (v, i) => (i.cost_settled ? fmtMoney(v, cur) : <Tag>未核算</Tag>) },
              { title: '头程成本', dataIndex: 'cost_freight', align: 'right', render: (v, i) => (i.cost_settled ? fmtMoney(v, cur) : '-') },
            ]}
          />
        </Space>
      )}
    </Drawer>
  )
}
