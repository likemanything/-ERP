import { useState } from 'react'
import { Button, Col, DatePicker, Form, Input, InputNumber, Row, Select, Space } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { api, type Option } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import Perm from '@/components/Perm'
import { CurrencySelect, ShopSelect } from '@/components/selects'
import { fmtDate, fmtMoney } from '@/utils/format'

type R = Record<string, any>

export default function Expenses() {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<R | null>(null)
  const reload = useReload('expenses')
  const run = useAction()
  const { data: cats } = useQuery({ queryKey: ['expense-categories'], queryFn: () => api.get<Option[]>('/finance/expense-categories') })
  const catLabel = (v: string) => cats?.find((c) => c.value === v)?.label ?? v
  return (
    <>
      <DataTable<R>
        queryKey="expenses"
        url="/finance/expenses"
        filters={[
          { name: 'keyword', placeholder: '单号 / 描述 / MSKU' },
          { name: 'category', type: 'select', label: '类别', options: (cats ?? []).map((c) => ({ value: c.value as string, label: c.label })) },
          { name: 'shop_id', type: 'custom', render: () => <ShopSelect /> },
          { name: 'date', type: 'dateRange', label: '费用日期' },
        ]}
        toolbar={() => <Perm code="finance:expense:edit"><Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true) }}>新增费用</Button></Perm>}
        columns={[
          { title: '单号', dataIndex: 'expense_no' },
          { title: '日期', dataIndex: 'expense_date', render: fmtDate },
          { title: '类别', dataIndex: 'category', render: catLabel },
          { title: '归属', key: 'owner', render: (_, r) => r.shop_name ?? '公司公共费用' },
          { title: 'MSKU', dataIndex: 'msku', render: (v) => v ?? '-' },
          { title: '金额', dataIndex: 'amount', align: 'right', render: (v, r) => <b>{fmtMoney(v, r.currency)}</b> },
          { title: '描述', dataIndex: 'description', render: (v) => v ?? '-' },
          { title: '操作', key: 'op', render: (_, r) => (
            <Perm code="finance:expense:edit"><Space>
              <a onClick={() => { setEditing(r); setOpen(true) }}>编辑</a>
              <a style={{ color: '#cf1322' }} onClick={() => run(() => api.del(`/finance/expenses/${r.id}`), { confirm: '删除费用？', onDone: reload })}>删除</a>
            </Space></Perm>
          ) },
        ]}
      />
      <FormModal open={open} title={editing ? '编辑费用' : '新增费用'} width={600} onCancel={() => setOpen(false)}
        initialValues={editing ? { ...editing, expense_date: dayjs(editing.expense_date) } : { category: 'other', currency: 'CNY', expense_date: dayjs() }}
        onSubmit={async (v) => {
          const body = { ...v, expense_date: dayjs(v.expense_date).format('YYYY-MM-DD') }
          if (editing) await api.put(`/finance/expenses/${editing.id}`, body)
          else await api.post('/finance/expenses', body)
          reload()
        }}>
        <Row gutter={12}>
          <Col span={12}><Form.Item name="category" label="类别" rules={[{ required: true }]}><Select options={cats} /></Form.Item></Col>
          <Col span={12}><Form.Item name="expense_date" label="费用日期" rules={[{ required: true }]}><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={12}><Form.Item name="amount" label="金额" rules={[{ required: true }]}><InputNumber min={0.01} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={12}><Form.Item name="currency" label="币种"><CurrencySelect /></Form.Item></Col>
          <Col span={12}><Form.Item name="shop_id" label="归属店铺（为空=公司公共）"><ShopSelect /></Form.Item></Col>
          <Col span={12}><Form.Item name="msku" label="归属 MSKU（可选）"><Input /></Form.Item></Col>
          <Col span={24}><Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item></Col>
        </Row>
      </FormModal>
    </>
  )
}
