import { useState } from 'react'
import { Button, DatePicker, Form, Input, InputNumber, Space } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import Perm from '@/components/Perm'
import { CurrencySelect } from '@/components/selects'
import { useBaseCurrency } from '@/store/auth'
import { fmtDateTime } from '@/utils/format'

type R = Record<string, any>

export default function Rates() {
  const base = useBaseCurrency()
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<R | null>(null)
  const reload = useReload('rates')
  const run = useAction()
  return (
    <>
      <DataTable<R>
        queryKey="rates"
        url="/system/exchange-rates"
        title={`月度汇率（1 外币 = ? ${base}）`}
        pageSize={50}
        filters={[{ name: 'currency', placeholder: '币种，如 USD', width: 140 }, { name: 'month', placeholder: '月份 YYYY-MM', width: 140 }]}
        toolbar={() => <Perm code="finance:rate:edit"><Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true) }}>新增汇率</Button></Perm>}
        columns={[
          { title: '月份', dataIndex: 'month' },
          { title: '币种', dataIndex: 'currency' },
          { title: `汇率（→${base}）`, dataIndex: 'rate', render: (v) => <b>{v}</b> },
          { title: '备注', dataIndex: 'remark', render: (v) => v ?? '-' },
          { title: '更新时间', dataIndex: 'updated_at', render: fmtDateTime },
          { title: '操作', key: 'op', render: (_, r) => (
            <Perm code="finance:rate:edit"><Space>
              <a onClick={() => { setEditing(r); setOpen(true) }}>编辑</a>
              <a onClick={() => run(() => api.del(`/system/exchange-rates/${r.id}`), { confirm: '删除该汇率？', onDone: reload })}>删除</a>
            </Space></Perm>
          ) },
        ]}
      />
      <FormModal open={open} title={editing ? `编辑汇率 ${editing.currency} ${editing.month}` : '新增汇率'} width={440} onCancel={() => setOpen(false)}
        initialValues={editing ?? { month: dayjs() }}
        onSubmit={async (v) => {
          if (editing) await api.put(`/system/exchange-rates/${editing.id}`, { rate: v.rate, remark: v.remark })
          else await api.post('/system/exchange-rates', { ...v, month: dayjs(v.month).format('YYYY-MM') })
          reload()
        }}>
        {!editing && (
          <>
            <Form.Item name="currency" label="币种" rules={[{ required: true }]}><CurrencySelect /></Form.Item>
            <Form.Item name="month" label="月份" rules={[{ required: true }]}><DatePicker picker="month" style={{ width: '100%' }} /></Form.Item>
          </>
        )}
        <Form.Item name="rate" label={`汇率（1 外币 = ? ${base}）`} rules={[{ required: true }]}><InputNumber min={0} precision={6} style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="remark" label="备注"><Input /></Form.Item>
      </FormModal>
    </>
  )
}
