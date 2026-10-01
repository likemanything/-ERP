import { Card, Table, Tooltip } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { fmtMoney } from '@/utils/format'

type R = Record<string, any>

export default function Payables() {
  const { data, isFetching } = useQuery({ queryKey: ['payables'], queryFn: () => api.get<R[]>('/payables') })
  return (
    <Card title="应付账款（按供应商 × 币种）" variant="borderless">
      <Table<R>
        rowKey={(r) => `${r.supplier_id}-${r.currency}`}
        loading={isFetching}
        dataSource={data ?? []}
        pagination={false}
        columns={[
          { title: '供应商', dataIndex: 'supplier_name' },
          { title: '币种', dataIndex: 'currency' },
          { title: '采购单数', dataIndex: 'order_count', align: 'right' },
          { title: '采购总额', dataIndex: 'total_amount', align: 'right', render: (v, r) => fmtMoney(v, r.currency) },
          { title: '已到货金额', dataIndex: 'received_value', align: 'right', render: (v, r) => fmtMoney(v, r.currency) },
          { title: '退货金额', dataIndex: 'returned_amount', align: 'right', render: (v, r) => fmtMoney(v, r.currency) },
          { title: '已付款', dataIndex: 'paid_amount', align: 'right', render: (v, r) => fmtMoney(v, r.currency) },
          { title: '请款中', dataIndex: 'requested_amount', align: 'right', render: (v, r) => fmtMoney(v, r.currency) },
          { title: '未付总额', dataIndex: 'unpaid_amount', align: 'right', render: (v, r) => <b style={{ color: v > 0 ? '#cf1322' : undefined }}>{fmtMoney(v, r.currency)}</b> },
          {
            title: <Tooltip title="已到货金额 - 退货 - 已付款">当前应付</Tooltip>,
            dataIndex: 'payable_now', align: 'right', render: (v, r) => fmtMoney(v, r.currency),
          },
        ]}
      />
    </Card>
  )
}
