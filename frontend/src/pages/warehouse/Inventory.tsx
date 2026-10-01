import { useState } from 'react'
import { Form, Input, InputNumber, Tabs, Tooltip } from 'antd'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal } from '@/components/common'
import Perm from '@/components/Perm'
import ProductCell from '@/components/ProductCell'
import StatusTag from '@/components/StatusTag'
import { WarehouseSelect } from '@/components/selects'
import { useBaseCurrency, usePerm } from '@/store/auth'
import { WAREHOUSE_TYPE, dictOptions } from '@/utils/dicts'
import { fmtMoney } from '@/utils/format'

type R = Record<string, any>

function Detail() {
  const cur = useBaseCurrency()
  const can = usePerm()
  const [editing, setEditing] = useState<R | null>(null)
  const reload = useReload('inventory')
  return (
    <>
      <DataTable<R>
        queryKey="inventory"
        url="/inventory"
        exportUrl="/inventory/export"
        card={false}
        filters={[
          { name: 'keyword', placeholder: 'SKU / 品名' },
          { name: 'warehouse_id', type: 'custom', render: () => <WarehouseSelect /> },
          { name: 'warehouse_type', type: 'select', label: '仓库类型', options: dictOptions(WAREHOUSE_TYPE) },
          { name: 'low_stock_only', type: 'select', label: '预警', options: [{ label: '低于安全库存', value: true }] },
        ]}
        columns={[
          { title: '产品', key: 'p', fixed: 'left', render: (_, r) => <ProductCell image={r.image_url} title={r.sku} sub={r.product_name} size={36} /> },
          { title: '仓库', dataIndex: 'warehouse_name', render: (v, r) => <span>{v} <StatusTag dict={WAREHOUSE_TYPE} value={r.warehouse_type} /></span> },
          { title: '实物库存', dataIndex: 'qty_on_hand', align: 'right', render: (v) => <b style={{ color: v < 0 ? '#cf1322' : undefined }}>{v}</b> },
          { title: '锁定', dataIndex: 'qty_locked', align: 'right' },
          {
            title: '可用', dataIndex: 'qty_available', align: 'right',
            render: (v, r) => <span style={{ color: r.safety_stock && v < r.safety_stock ? '#cf1322' : '#389e0d', fontWeight: 600 }}>{v}</span>,
          },
          { title: '次品', dataIndex: 'qty_defective', align: 'right' },
          { title: <Tooltip title="调拨/头程在途，将入本仓">在途</Tooltip>, dataIndex: 'qty_in_transit', align: 'right' },
          { title: '安全库存', dataIndex: 'safety_stock', align: 'right' },
          { title: '库位', dataIndex: 'bin_code', render: (v) => v ?? '-' },
          ...(can('product:cost:view') ? [
            { title: '单位成本', dataIndex: 'unit_cost', align: 'right' as const, render: (v: number) => fmtMoney(v, cur) },
            { title: '库存金额', dataIndex: 'stock_value', align: 'right' as const, render: (v: number) => fmtMoney(v, cur) },
          ] : []),
          { title: '操作', key: 'op', render: (_, r) => <Perm code="warehouse:edit"><a onClick={() => setEditing(r)}>设置</a></Perm> },
        ]}
      />
      <FormModal open={!!editing} title={`库存设置 ${editing?.sku ?? ''} @ ${editing?.warehouse_name ?? ''}`} width={420}
        onCancel={() => setEditing(null)} initialValues={editing ?? {}}
        onSubmit={async (v) => { await api.put(`/inventory/${editing!.id}`, v); reload() }}>
        <Form.Item name="safety_stock" label="安全库存（可用量低于该值时预警）"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="bin_code" label="默认库位"><Input /></Form.Item>
      </FormModal>
    </>
  )
}

function Summary() {
  return (
    <DataTable<R>
      queryKey="inventory-summary"
      url="/inventory/summary"
      rowKey="product_id"
      card={false}
      filters={[{ name: 'keyword', placeholder: 'SKU / 品名' }]}
      columns={[
        { title: '产品', key: 'p', render: (_, r) => <ProductCell image={r.image_url} title={r.sku} sub={r.product_name} size={36} /> },
        { title: '本地仓实物', dataIndex: 'local_on_hand', align: 'right' },
        { title: '本地锁定', dataIndex: 'local_locked', align: 'right' },
        { title: '本地可用', dataIndex: 'local_available', align: 'right', render: (v) => <b>{v}</b> },
        { title: '在途', dataIndex: 'in_transit', align: 'right' },
        { title: 'FBA 仓（系统账）', dataIndex: 'fba_on_hand', align: 'right' },
        { title: '次品', dataIndex: 'defective', align: 'right' },
        { title: '合计', key: 'total', align: 'right', render: (_, r) => <b>{r.local_on_hand + r.in_transit + Math.max(0, r.fba_on_hand)}</b> },
      ]}
    />
  )
}

export default function Inventory() {
  return (
    <div style={{ background: '#fff', padding: '0 24px 24px', borderRadius: 8 }}>
      <Tabs items={[
        { key: 'detail', label: '库存明细（仓库 × SKU）', children: <Detail /> },
        { key: 'summary', label: '库存汇总（按 SKU）', children: <Summary /> },
      ]} />
    </div>
  )
}
