import { useState } from 'react'
import { Card, Input, Segmented, Space, Table, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'

type R = Record<string, any>

export default function Turnover() {
  const [days, setDays] = useState(30)
  const [keyword, setKeyword] = useState('')
  const { data, isFetching } = useQuery({
    queryKey: ['turnover', days, keyword],
    queryFn: () => api.get<{ items: R[] }>('/reports/inventory-turnover', { days, keyword: keyword || undefined }),
  })
  return (
    <Card variant="borderless" title="库存周转分析">
      <Space style={{ marginBottom: 12 }}>
        <Segmented value={days} onChange={(v) => setDays(v as number)} options={[{ value: 7, label: '近7天' }, { value: 30, label: '近30天' }, { value: 90, label: '近90天' }]} />
        <Input.Search allowClear placeholder="SKU / 品名" onSearch={setKeyword} style={{ width: 200 }} />
      </Space>
      <Table<R> size="small" loading={isFetching} rowKey="product_id" dataSource={data?.items ?? []} pagination={{ pageSize: 50 }} columns={[
        { title: 'SKU', dataIndex: 'sku' },
        { title: '品名', dataIndex: 'product_name', ellipsis: true },
        { title: '当前库存（全仓）', dataIndex: 'stock_qty', align: 'right' },
        { title: '期间销售出库', dataIndex: 'sold_qty', align: 'right' },
        { title: '期间总出库', dataIndex: 'moved_qty', align: 'right' },
        { title: '日均销量', dataIndex: 'daily_sales', align: 'right' },
        {
          title: '库存可售天数', dataIndex: 'days_of_inventory', align: 'right',
          render: (v, r) => (r.slow_moving ? <Tag color="red">滞销</Tag> : v === null ? '-' : <Tag color={v > 120 ? 'orange' : 'green'}>{v} 天</Tag>),
        },
        { title: '周转率', dataIndex: 'turnover_rate', align: 'right', render: (v) => v ?? '-' },
      ]} />
    </Card>
  )
}
