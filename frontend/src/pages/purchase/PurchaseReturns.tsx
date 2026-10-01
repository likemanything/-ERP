import { useState } from 'react'
import { Button, Form, Input, InputNumber, Select, Table } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { api, type Page } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal } from '@/components/common'
import Perm from '@/components/Perm'
import { SupplierSelect } from '@/components/selects'
import { fmtDateTime, fmtMoney } from '@/utils/format'

type R = Record<string, any>

function CreateReturn({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [form] = Form.useForm()
  const [kw, setKw] = useState('')
  const orderId = Form.useWatch('order_id', form)
  const { data } = useQuery({
    queryKey: ['po-search-return', kw],
    queryFn: () => api.get<Page<R>>('/purchase-orders', { keyword: kw || undefined, status: 'partial,received,closed', page_size: 30 }),
  })
  const po = data?.items.find((p) => p.id === orderId)
  const [qty, setQty] = useState<Record<number, number>>({})
  return (
    <FormModal open={open} form={form} title="新建采购退货（审核后直接出库）" width={820} onCancel={() => { setQty({}); onClose() }}
      initialValues={{ stock_type: 'defective' }}
      onSubmit={async (v) => {
        const lines = Object.entries(qty).filter(([, q]) => q > 0).map(([id, q]) => ({ order_line_id: Number(id), qty: q }))
        if (!lines.length) throw new Error('请填写退货数量')
        await api.post('/purchase-returns', { ...v, lines })
        setQty({})
        onDone()
      }}>
      <Form.Item name="order_id" label="采购单" rules={[{ required: true }]}>
        <Select showSearch={{ filterOption: false, onSearch: setKw }} placeholder="输入采购单号搜索"
          options={(data?.items ?? []).map((p) => ({ value: p.id, label: `${p.po_no} - ${p.supplier_name}` }))} />
      </Form.Item>
      <Form.Item name="stock_type" label="退货库存类型">
        <Select options={[{ value: 'defective', label: '次品（质检不良）' }, { value: 'good', label: '良品' }]} />
      </Form.Item>
      {po && (
        <Table<R> size="small" rowKey="id" pagination={false} dataSource={po.lines} style={{ marginBottom: 16 }} columns={[
          { title: 'SKU', dataIndex: 'sku' }, { title: '已到货', dataIndex: 'qty_received' }, { title: '次品', dataIndex: 'qty_defective' },
          { title: '已退', dataIndex: 'qty_returned' }, { title: '单价', dataIndex: 'unit_price', render: (v) => fmtMoney(v, po.currency, 4) },
          { title: '退货数量', render: (_, l) => <InputNumber min={0} max={l.qty_received - l.qty_returned} onChange={(v) => setQty((s) => ({ ...s, [l.id]: v ?? 0 }))} /> },
        ]} />
      )}
      <Form.Item name="refund_amount" label="退款金额（为空按 数量×单价）"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
      <Form.Item name="reason" label="退货原因"><Input /></Form.Item>
    </FormModal>
  )
}

export default function PurchaseReturns() {
  const [open, setOpen] = useState(false)
  const reload = useReload('purchase-returns')
  return (
    <>
      <DataTable<R>
        queryKey="purchase-returns"
        url="/purchase-returns"
        filters={[{ name: 'keyword', placeholder: '退货单号 / 原因' }, { name: 'supplier_id', type: 'custom', render: () => <SupplierSelect /> }]}
        toolbar={() => <Perm code="purchase:return"><Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>新建退货</Button></Perm>}
        expandable={{ expandedRowRender: (r) => (
          <Table<R> size="small" rowKey="id" pagination={false} dataSource={r.lines} columns={[
            { title: 'SKU', dataIndex: 'sku' }, { title: '品名', dataIndex: 'product_name' }, { title: '数量', dataIndex: 'qty' },
            { title: '单价', dataIndex: 'unit_price', render: (v) => fmtMoney(v, undefined, 4) },
          ]} />
        ) }}
        columns={[
          { title: '退货单号', dataIndex: 'return_no' },
          { title: '采购单号', dataIndex: 'po_no' },
          { title: '供应商', dataIndex: 'supplier_name' },
          { title: '类型', dataIndex: 'stock_type', render: (v) => (v === 'good' ? '良品' : '次品') },
          { title: '件数', key: 'qty', render: (_, r) => r.lines.reduce((s: number, l: R) => s + l.qty, 0) },
          { title: '退款金额', dataIndex: 'refund_amount', align: 'right', render: (v) => fmtMoney(v) },
          { title: '原因', dataIndex: 'reason', render: (v) => v ?? '-' },
          { title: '时间', dataIndex: 'created_at', render: fmtDateTime },
        ]}
      />
      <CreateReturn open={open} onClose={() => setOpen(false)} onDone={reload} />
    </>
  )
}
