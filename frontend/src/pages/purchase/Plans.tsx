import { useState } from 'react'
import { Button, DatePicker, Form, Input, InputNumber, Space, Tabs } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import Perm from '@/components/Perm'
import ProductCell from '@/components/ProductCell'
import StatusTag from '@/components/StatusTag'
import { ProductSelect, SupplierSelect, UserSelect, WarehouseSelect } from '@/components/selects'
import { PLAN_STATUS } from '@/utils/dicts'
import { fmtDate, fmtDateTime } from '@/utils/format'

type Plan = Record<string, any>

export default function Plans() {
  const [tab, setTab] = useState('pending')
  const [creating, setCreating] = useState(false)
  const [converting, setConverting] = useState<number[] | null>(null)
  const reload = useReload('purchase-plans')
  const run = useAction()
  return (
    <>
      <DataTable<Plan>
        queryKey="purchase-plans"
        url="/purchase-plans"
        rowSelection
        extraParams={{ status: tab === 'all' ? undefined : tab }}
        header={<Tabs activeKey={tab} onChange={setTab} items={[
          { key: 'pending', label: '待处理' }, { key: 'converted', label: '已生成采购单' }, { key: 'cancelled', label: '已作废' }, { key: 'all', label: '全部' },
        ]} />}
        filters={[
          { name: 'keyword', placeholder: '计划号 / SKU / 品名' },
          { name: 'supplier_id', type: 'custom', render: () => <SupplierSelect /> },
          { name: 'source', type: 'select', label: '来源', options: [{ label: '手工', value: 'manual' }, { label: '补货建议', value: 'replenishment' }] },
        ]}
        toolbar={({ selectedRowKeys, clearSelection }) => (
          <Space>
            <Perm code="purchase:plan:edit">
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>新建计划</Button>
            </Perm>
            {tab === 'pending' && (
              <>
                <Perm code="purchase:order:edit">
                  <Button type="primary" ghost disabled={!selectedRowKeys.length} onClick={() => setConverting(selectedRowKeys as number[])}>
                    生成采购单（按供应商合并）
                  </Button>
                </Perm>
                <Perm code="purchase:plan:edit">
                  <Button disabled={!selectedRowKeys.length} onClick={() => run(() => api.post('/purchase-plans/cancel', { ids: selectedRowKeys }), {
                    confirm: `作废选中的 ${selectedRowKeys.length} 条计划？`, success: (r: any) => r.message, onDone: () => { clearSelection(); reload() },
                  })}>作废</Button>
                </Perm>
              </>
            )}
          </Space>
        )}
        columns={[
          { title: '计划号', dataIndex: 'plan_no' },
          { title: '产品', key: 'p', render: (_, r) => <ProductCell image={r.image_url} title={r.sku} sub={r.product_name} size={32} /> },
          { title: '计划数量', dataIndex: 'qty', align: 'right' },
          { title: '供应商', dataIndex: 'supplier_name', render: (v) => v ?? <span style={{ color: '#fa8c16' }}>未指定</span> },
          { title: '收货仓', dataIndex: 'warehouse_name', render: (v) => v ?? '默认仓' },
          { title: '期望到货', dataIndex: 'expected_date', render: fmtDate },
          { title: '来源', dataIndex: 'source', render: (v) => (v === 'replenishment' ? '补货建议' : '手工') },
          { title: '状态', dataIndex: 'status', render: (v) => <StatusTag dict={PLAN_STATUS} value={v} /> },
          { title: '采购单', dataIndex: 'po_no', render: (v) => v ?? '-' },
          { title: '备注', dataIndex: 'remark', render: (v) => v ?? '-' },
          { title: '创建时间', dataIndex: 'created_at', render: fmtDateTime },
        ]}
      />
      <FormModal open={creating} title="新建采购计划" width={560} onCancel={() => setCreating(false)}
        onSubmit={async (v) => {
          await api.post('/purchase-plans', { ...v, expected_date: v.expected_date ? dayjs(v.expected_date).format('YYYY-MM-DD') : undefined })
          reload()
        }}>
        <Form.Item name="product_id" label="产品" rules={[{ required: true }]}><ProductSelect excludeBundle /></Form.Item>
        <Form.Item name="qty" label="数量" rules={[{ required: true }]}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="supplier_id" label="供应商（为空取产品默认供应商）"><SupplierSelect /></Form.Item>
        <Form.Item name="warehouse_id" label="收货仓"><WarehouseSelect excludeFba /></Form.Item>
        <Form.Item name="expected_date" label="期望到货"><DatePicker style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="purchaser_id" label="采购员"><UserSelect /></Form.Item>
        <Form.Item name="remark" label="备注"><Input /></Form.Item>
      </FormModal>
      <FormModal open={!!converting} title="生成采购单" width={460} okText="生成" onCancel={() => setConverting(null)}
        onSubmit={async (v) => {
          await api.post('/purchase-plans/to-orders', { plan_ids: converting, warehouse_id: v.warehouse_id })
          reload()
        }}>
        <p>选中的 {converting?.length} 条计划将按「供应商 + 收货仓」合并生成采购单（草稿），单价自动取供应商报价。</p>
        <Form.Item name="warehouse_id" label="统一收货仓（可选）"><WarehouseSelect excludeFba /></Form.Item>
      </FormModal>
    </>
  )
}
