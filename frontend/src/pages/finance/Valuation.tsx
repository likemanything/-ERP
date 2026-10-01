import { Card, Col, Row, Statistic, Table } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import StatusTag from '@/components/StatusTag'
import { useBaseCurrency } from '@/store/auth'
import { WAREHOUSE_TYPE } from '@/utils/dicts'
import { currencySymbol, fmtMoney } from '@/utils/format'

type R = Record<string, any>

export default function Valuation() {
  const cur = useBaseCurrency()
  const { data, isFetching } = useQuery({ queryKey: ['valuation'], queryFn: () => api.get<{ items: R[]; totals: R }>('/finance/inventory-valuation') })
  const t = data?.totals
  const sym = currencySymbol(cur)
  return (
    <Card variant="borderless" title="库存估值（按 FIFO 批次结存）">
      {t && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={4}><Statistic title="在库数量" value={t.qty} /></Col>
          <Col span={5}><Statistic title="在库总值" value={t.total_value} precision={2} prefix={sym} /></Col>
          <Col span={5}><Statistic title="其中采购成本" value={t.purchase_value} precision={2} prefix={sym} /></Col>
          <Col span={5}><Statistic title="其中物流/头程" value={t.freight_value} precision={2} prefix={sym} /></Col>
          <Col span={5}><Statistic title={`头程在途（${t.in_transit_qty} 件）`} value={t.in_transit_value} precision={2} prefix={sym} /></Col>
        </Row>
      )}
      <Table<R> rowKey="warehouse_id" loading={isFetching} dataSource={data?.items ?? []} pagination={false} columns={[
        { title: '仓库', dataIndex: 'warehouse_name' },
        { title: '类型', dataIndex: 'warehouse_type', render: (v) => <StatusTag dict={WAREHOUSE_TYPE} value={v} /> },
        { title: '数量', dataIndex: 'qty', align: 'right' },
        { title: '采购成本', dataIndex: 'purchase_value', align: 'right', render: (v) => fmtMoney(v, cur) },
        { title: '物流/头程成本', dataIndex: 'freight_value', align: 'right', render: (v) => fmtMoney(v, cur) },
        { title: '合计', dataIndex: 'total_value', align: 'right', render: (v) => <b>{fmtMoney(v, cur)}</b> },
        { title: '占比', key: 'pct', align: 'right', render: (_, r) => (t?.total_value ? `${((r.total_value / t.total_value) * 100).toFixed(1)}%` : '-') },
      ]} />
    </Card>
  )
}
