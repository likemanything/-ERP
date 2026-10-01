import { useMemo, useState } from 'react'
import { Card, Input, Select, Space, Table, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import type { EChartsOption } from 'echarts'
import { api } from '@/api/client'
import EChart from '@/components/EChart'
import { WarehouseSelect } from '@/components/selects'
import { useBaseCurrency, usePerm } from '@/store/auth'
import { WAREHOUSE_TYPE, dictOptions } from '@/utils/dicts'
import { fmtMoney } from '@/utils/format'

type R = Record<string, any>

export default function Aging() {
  const cur = useBaseCurrency()
  const can = usePerm()
  const [warehouseId, setWarehouseId] = useState<number>()
  const [warehouseType, setWarehouseType] = useState<string>()
  const [keyword, setKeyword] = useState('')
  const { data, isFetching } = useQuery({
    queryKey: ['aging', warehouseId, warehouseType, keyword],
    queryFn: () => api.get<{ items: R[]; summary: R[]; buckets: string[] }>('/reports/inventory-aging', {
      warehouse_id: warehouseId, warehouse_type: warehouseType, keyword: keyword || undefined,
    }),
  })
  const chart = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 30, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: data?.buckets ?? [] },
    yAxis: { type: 'value', name: '件数' },
    series: [{
      type: 'bar', data: (data?.summary ?? []).map((s, i) => ({ value: s.qty, itemStyle: { color: ['#52c41a', '#95de64', '#fadb14', '#fa8c16', '#f5222d', '#a8071a'][i] } })),
      label: { show: true, position: 'top' },
    }],
  }), [data])
  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <Card variant="borderless" title="库龄分布">
        <Space wrap style={{ marginBottom: 12 }}>
          <WarehouseSelect value={warehouseId} onChange={setWarehouseId} />
          <Select allowClear placeholder="仓库类型" options={dictOptions(WAREHOUSE_TYPE)} value={warehouseType} onChange={setWarehouseType} style={{ width: 140 }} />
          <Input.Search allowClear placeholder="SKU / 品名" onSearch={setKeyword} style={{ width: 200 }} />
        </Space>
        <EChart option={chart} height={260} />
        {can('product:cost:view') && (
          <Space wrap size={24}>
            {(data?.summary ?? []).map((s) => <span key={s.bucket}>{s.bucket}：<b>{fmtMoney(s.value, cur)}</b></span>)}
          </Space>
        )}
      </Card>
      <Card variant="borderless">
        <Table<R> size="small" loading={isFetching} rowKey="product_id" dataSource={data?.items ?? []} pagination={{ pageSize: 50 }} scroll={{ x: 'max-content' }}
          columns={[
            { title: 'SKU', dataIndex: 'sku' }, { title: '品名', dataIndex: 'product_name', ellipsis: true },
            { title: '结存', dataIndex: 'qty', align: 'right' },
            ...(data?.buckets ?? []).map((b, i) => ({ title: b, key: b, align: 'right' as const, render: (_: unknown, r: R) => r.buckets[i] || '-' })),
            { title: '平均库龄', dataIndex: 'avg_age', align: 'right', render: (v: number) => <Tag color={v > 180 ? 'red' : v > 90 ? 'orange' : 'green'}>{v} 天</Tag> },
            { title: '最大库龄', dataIndex: 'max_age', align: 'right', render: (v: number) => `${v} 天` },
            ...(can('product:cost:view') ? [{ title: '库存金额', dataIndex: 'value', align: 'right' as const, render: (v: number) => fmtMoney(v, cur) }] : []),
          ]} />
      </Card>
    </Space>
  )
}
