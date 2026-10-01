import { useState } from 'react'
import { App, Button, Card, Input, InputNumber, Space, Switch, Table, Tag, Tooltip } from 'antd'
import { SettingOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { api, errorMessage } from '@/api/client'
import Perm from '@/components/Perm'
import ProductCell from '@/components/ProductCell'
import { useLabelMap, useSupplierOptions } from '@/hooks/useOptions'
import RuleModal from './RuleModal'

type R = Record<string, any>

export default function PurchaseSuggest() {
  const [keyword, setKeyword] = useState('')
  const [onlyNeed, setOnlyNeed] = useState(true)
  const [qty, setQty] = useState<Record<number, number>>({})
  const [selected, setSelected] = useState<React.Key[]>([])
  const [ruleOpen, setRuleOpen] = useState(false)
  const { message } = App.useApp()
  const { data: suppliers } = useSupplierOptions()
  const supplierMap = useLabelMap(suppliers)
  const { data, isFetching, refetch } = useQuery({
    queryKey: ['purchase-suggest', keyword, onlyNeed],
    queryFn: () => api.get<R[]>('/replenishment/products', { keyword: keyword || undefined, only_need: onlyNeed }),
  })
  const generate = async () => {
    const items = (data ?? []).filter((r) => selected.includes(r.product_id))
      .map((r) => ({ product_id: r.product_id, qty: qty[r.product_id] ?? r.suggest_purchase_qty, supplier_id: r.supplier_id }))
      .filter((i) => i.qty > 0)
    if (!items.length) return message.warning('所选产品建议采购量为 0')
    try {
      const r = await api.post('/replenishment/to-purchase-plans', { items })
      message.success(`${r.message}，可在「采购计划」中合并生成采购单`)
      setSelected([])
      refetch()
    } catch (e) {
      message.error(errorMessage(e))
    }
  }
  return (
    <Card variant="borderless">
      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search placeholder="SKU / 品名" allowClear onSearch={setKeyword} style={{ width: 240 }} />
        <span>只看需要采购 <Switch checked={onlyNeed} onChange={setOnlyNeed} /></span>
        <Perm code="replenish:edit"><Button icon={<SettingOutlined />} onClick={() => setRuleOpen(true)}>补货参数</Button></Perm>
        <Perm code="purchase:plan:edit">
          <Button type="primary" disabled={!selected.length} onClick={generate}>生成采购计划（{selected.length}）</Button>
        </Perm>
      </Space>
      <Table<R>
        rowKey="product_id"
        loading={isFetching}
        dataSource={data ?? []}
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 50, showTotal: (t) => `共 ${t} 个 SKU` }}
        rowSelection={{ selectedRowKeys: selected, onChange: setSelected }}
        columns={[
          { title: '产品', fixed: 'left', render: (_, r) => <ProductCell image={r.image_url} title={r.sku} sub={r.product_name} extra={supplierMap.get(r.supplier_id) ?? '未设置供应商'} /> },
          { title: '30天销量', dataIndex: 'sales_30d', align: 'right' },
          { title: '日均需求', dataIndex: 'daily_sales', align: 'right', render: (v) => <b>{v}</b> },
          { title: '本地可用', dataIndex: 'local_available', align: 'right' },
          { title: 'FBA 总库存', dataIndex: 'fba_total', align: 'right' },
          { title: '采购在途', dataIndex: 'purchase_in_transit', align: 'right' },
          { title: '计划中', dataIndex: 'planned_qty', align: 'right' },
          { title: '总供给', dataIndex: 'total_supply', align: 'right' },
          {
            title: <Tooltip title="总供给 ÷ 日均需求">可售天数</Tooltip>, dataIndex: 'supply_days', align: 'right',
            render: (v) => (v === null || v === undefined ? '-' : <Tag color={v < 45 ? 'red' : v < 75 ? 'orange' : 'green'}>{v}</Tag>),
          },
          { title: '交期', dataIndex: 'purchase_lead_days', align: 'right', render: (v) => `${v} 天` },
          { title: '最晚下单日', dataIndex: 'latest_order_date', render: (v) => v ?? '-' },
          { title: '起订量', dataIndex: 'moq', align: 'right' },
          {
            title: '建议采购量', dataIndex: 'suggest_purchase_qty', fixed: 'right', align: 'right',
            render: (v, r) => <InputNumber min={0} size="small" value={qty[r.product_id] ?? v} onChange={(x) => setQty((s) => ({ ...s, [r.product_id]: x ?? 0 }))} style={{ width: 100 }} />,
          },
        ]}
      />
      <RuleModal open={ruleOpen} onClose={() => setRuleOpen(false)} onDone={() => refetch()} />
    </Card>
  )
}
