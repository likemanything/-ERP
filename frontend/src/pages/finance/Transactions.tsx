import { useState } from 'react'
import { Alert, Button, Card, DatePicker, Form, Space, Table, Tag } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs, { type Dayjs } from 'dayjs'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { ImportModal } from '@/components/common'
import Perm from '@/components/Perm'
import { ShopSelect } from '@/components/selects'
import { fmtDateTime, fmtMoney } from '@/utils/format'

type R = Record<string, any>

const CATEGORY: Record<string, [string, string]> = {
  revenue: ['销售收入', 'green'], commission: ['佣金', 'orange'], fulfillment: ['FBA配送费', 'orange'],
  promotion: ['促销', 'purple'], other: ['其他', 'default'],
}

function Summary() {
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(29, 'day'), dayjs()])
  const { data, isFetching } = useQuery({
    queryKey: ['tx-summary', range[0].format(), range[1].format()],
    queryFn: () => api.get<R[]>('/finance/transactions/summary', { date_from: range[0].format('YYYY-MM-DD'), date_to: range[1].format('YYYY-MM-DD') }),
  })
  const m = (v: number, r: R) => fmtMoney(v, r.currency)
  return (
    <Card variant="borderless" title="结算汇总" extra={<DatePicker.RangePicker value={range} allowClear={false} onChange={(v) => v && setRange(v as [Dayjs, Dayjs])} />}>
      <Table<R> size="small" rowKey={(r) => `${r.shop_id}-${r.currency}`} loading={isFetching} pagination={false} dataSource={data ?? []} columns={[
        { title: '店铺', dataIndex: 'shop_name' }, { title: '币种', dataIndex: 'currency' },
        { title: '销售收入', dataIndex: 'revenue', align: 'right', render: m },
        { title: '佣金', dataIndex: 'commission', align: 'right', render: m },
        { title: 'FBA配送费', dataIndex: 'fulfillment', align: 'right', render: m },
        { title: '促销', dataIndex: 'promotion', align: 'right', render: m },
        { title: '退款', dataIndex: 'refund', align: 'right', render: m },
        { title: '其他费用', dataIndex: 'other', align: 'right', render: m },
        { title: '净结算', dataIndex: 'net', align: 'right', render: (v, r) => <b>{m(v, r)}</b> },
        { title: '已转账', dataIndex: 'transfer', align: 'right', render: m },
      ]} />
    </Card>
  )
}

export default function Transactions() {
  const [open, setOpen] = useState(false)
  const [shopId, setShopId] = useState<number>()
  const reload = useReload('transactions')
  return (
    <Space orientation="vertical" style={{ width: '100%' }} size={16}>
      <Summary />
      <DataTable<R>
        queryKey="transactions"
        url="/finance/transactions"
        title="交易明细"
        pageSize={50}
        filters={[
          { name: 'keyword', placeholder: '订单号 / MSKU / 结算ID / 费用类型' },
          { name: 'shop_id', type: 'custom', render: () => <ShopSelect /> },
          { name: 'event_type', type: 'select', label: '类型', options: ['order', 'refund', 'service_fee', 'adjustment', 'ads', 'transfer', 'other'].map((v) => ({ value: v, label: v })) },
          { name: 'date', type: 'dateRange', label: '日期' },
        ]}
        toolbar={() => (
          <Perm code="finance:transaction:edit">
            <Button icon={<UploadOutlined />} onClick={() => setOpen(true)}>导入结算报告</Button>
          </Perm>
        )}
        columns={[
          { title: '日期', dataIndex: 'posted_at', render: fmtDateTime },
          { title: '店铺', dataIndex: 'shop_name' },
          { title: '类型', dataIndex: 'event_type' },
          { title: '费用类型', dataIndex: 'amount_type', render: (v, r) => <Space>{v}<Tag color={CATEGORY[r.category]?.[1]}>{CATEGORY[r.category]?.[0]}</Tag></Space> },
          { title: '订单号', dataIndex: 'platform_order_id', render: (v) => v ?? '-' },
          { title: 'MSKU', dataIndex: 'msku', render: (v) => v ?? '-' },
          { title: '数量', dataIndex: 'quantity' },
          { title: '金额', dataIndex: 'amount', align: 'right', render: (v, r) => <span style={{ color: v < 0 ? '#cf1322' : '#389e0d' }}>{fmtMoney(v, r.currency)}</span> },
          { title: '结算ID', dataIndex: 'settlement_id', render: (v) => v ?? '-' },
        ]}
      />
      <ImportModal open={open} onClose={() => setOpen(false)} title="导入结算/交易明细" uploadUrl="/finance/transactions/import"
        templateUrl="/finance/transactions/import-template" fields={shopId ? { shop_id: shopId, apply_fees: true } : undefined}
        onDone={reload}
        extra={(
          <>
            <Form.Item label="店铺" required style={{ marginBottom: 0 }}><ShopSelect value={shopId} onChange={setShopId} /></Form.Item>
            {!shopId && <Alert type="warning" showIcon title="请先选择店铺再上传" />}
            <span style={{ color: '#888', fontSize: 12 }}>导入后会用实际佣金/FBA费替换订单上的预估费用，利润更精确。</span>
          </>
        )} />
    </Space>
  )
}
