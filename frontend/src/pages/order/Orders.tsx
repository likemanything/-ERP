import { useState } from 'react'
import { Button, Space, Tabs, Tag, Tooltip } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { ImportModal } from '@/components/common'
import Perm from '@/components/Perm'
import ProductCell from '@/components/ProductCell'
import StatusTag from '@/components/StatusTag'
import { ShopSelect } from '@/components/selects'
import { useBaseCurrency, usePerm } from '@/store/auth'
import { FULFILLMENT, ORDER_STATUS, dictOptions } from '@/utils/dicts'
import { fmtDateTime, fmtMoney, profitColor } from '@/utils/format'
import OrderDetail from './OrderDetail'

type Order = Record<string, any>

export const orderColumns = (cur: string, canCost: boolean, onOpen: (id: number) => void) => [
  {
    title: '订单', key: 'order', fixed: 'left' as const,
    render: (_: unknown, r: Order) => (
      <div style={{ lineHeight: 1.6 }}>
        <a onClick={() => onOpen(r.id)}>{r.platform_order_id}</a>
        <div style={{ fontSize: 12, color: '#888' }}>{r.shop_name} · {fmtDateTime(r.purchase_at)}</div>
        <Space size={4} wrap>
          <StatusTag dict={FULFILLMENT} value={r.fulfillment} />
          {r.is_on_hold && <Tag color="red">挂起</Tag>}
          {r.has_unpaired && <Tag color="orange">未配对</Tag>}
          {(r.tags ?? []).map((t: string) => <Tag key={t} color="volcano">{t}</Tag>)}
        </Space>
      </div>
    ),
  },
  {
    title: '商品', key: 'items',
    render: (_: unknown, r: Order) => (
      <Space orientation="vertical" size={4}>
        {r.items.slice(0, 3).map((i: Order) => (
          <ProductCell key={i.id} image={i.image_url} title={`${i.msku} × ${i.quantity}`} sub={i.sku ? `SKU ${i.sku}` : '未配对'} size={32} />
        ))}
        {r.items.length > 3 && <span style={{ color: '#888' }}>… 共 {r.items.length} 个商品</span>}
      </Space>
    ),
  },
  { title: '状态', dataIndex: 'status', render: (v: string) => <StatusTag dict={ORDER_STATUS} value={v} /> },
  { title: '订单金额', dataIndex: 'total_amount', align: 'right' as const, render: (v: number, r: Order) => fmtMoney(v, r.currency) },
  ...(canCost
    ? [{
        title: <Tooltip title="销售额 - 平台费用 - 退款 - 采购与头程成本 - 运费（本位币）">预估利润</Tooltip>,
        dataIndex: 'est_profit', align: 'right' as const,
        render: (v: number) => <span style={{ color: profitColor(v) }}>{fmtMoney(v, cur)}</span>,
      }]
    : []),
  { title: '收件国家', dataIndex: 'ship_country', render: (v: string, r: Order) => `${v ?? '-'} ${r.ship_state ?? ''}` },
  { title: '运单号', dataIndex: 'tracking_no', render: (v: string, r: Order) => (v ? `${r.carrier ?? ''} ${v}` : '-') },
]

export default function Orders() {
  const [tab, setTab] = useState('all')
  const [detail, setDetail] = useState<number | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const cur = useBaseCurrency()
  const can = usePerm()
  const reload = useReload('orders')
  const { data: counts } = useQuery({ queryKey: ['orders', 'counts'], queryFn: () => api.get<Record<string, number>>('/orders/status-counts') })
  const tabs = [
    { key: 'all', label: '全部' },
    ...Object.entries(ORDER_STATUS).map(([k, [label]]) => ({ key: k, label: `${label}${counts?.[k] ? ` (${counts[k]})` : ''}` })),
  ]
  return (
    <>
      <DataTable<Order>
        queryKey="orders"
        url="/orders"
        exportUrl="/orders/export"
        extraParams={{ status: tab === 'all' ? undefined : tab }}
        header={<Tabs activeKey={tab} onChange={setTab} items={tabs} />}
        filters={[
          { name: 'keyword', placeholder: '订单号 / MSKU / SKU / 买家 / 运单号', width: 260 },
          { name: 'shop_id', type: 'custom', render: () => <ShopSelect /> },
          { name: 'fulfillment', type: 'select', label: '配送', options: dictOptions(FULFILLMENT) },
          { name: 'date', type: 'dateRange', label: '下单日期' },
          { name: 'unpaired', type: 'select', label: '配对', options: [{ label: '含未配对', value: true }] },
        ]}
        toolbar={() => (
          <Perm code="order:edit">
            <Button icon={<UploadOutlined />} onClick={() => setImportOpen(true)}>导入订单</Button>
          </Perm>
        )}
        columns={orderColumns(cur, can('product:cost:view'), setDetail)}
      />
      <OrderDetail orderId={detail} onClose={() => setDetail(null)} />
      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} title="导入订单（适用于未接入 API 的平台/线下渠道）"
        uploadUrl="/orders/import" templateUrl="/orders/import-template" onDone={reload} />
    </>
  )
}
