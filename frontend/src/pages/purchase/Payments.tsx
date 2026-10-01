import { useState } from 'react'
import { Button, Form, Input, InputNumber, Select, Space, Table, Tabs } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { api, type Page } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import Perm from '@/components/Perm'
import StatusTag from '@/components/StatusTag'
import { SupplierSelect } from '@/components/selects'
import { PAYMENT_REQ_STATUS, PAY_TYPE, PO_STATUS, dictOptions } from '@/utils/dicts'
import { fmtDateTime, fmtMoney } from '@/utils/format'

type R = Record<string, any>

function CreateRequest({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [form] = Form.useForm()
  const supplierId = Form.useWatch('supplier_id', form)
  const { data } = useQuery({
    queryKey: ['po-for-payment', supplierId],
    queryFn: () => api.get<Page<R>>('/purchase-orders', { supplier_id: supplierId, status: 'approved,ordered,partial,received,closed', page_size: 200 }),
    enabled: !!supplierId,
  })
  const pos: R[] = (data?.items ?? []).map((p) => ({ ...p, outstanding: +(p.total_amount - p.returned_amount - p.requested_amount).toFixed(2) })).filter((p) => p.outstanding > 0)
  const [amounts, setAmounts] = useState<Record<number, number>>({})
  const total = Object.values(amounts).reduce((s, v) => s + (v || 0), 0)
  return (
    <FormModal open={open} form={form} title="发起请款" width={900} onCancel={() => { setAmounts({}); onClose() }} initialValues={{ pay_type: 'balance' }}
      onSubmit={async (v) => {
        const lines = Object.entries(amounts).filter(([, a]) => a > 0).map(([id, a]) => ({ purchase_order_id: Number(id), amount: a }))
        if (!lines.length) throw new Error('请填写请款金额')
        await api.post('/payment-requests', { ...v, lines })
        setAmounts({})
        onDone()
      }}>
      <Space wrap>
        <Form.Item name="supplier_id" label="供应商" rules={[{ required: true }]}><SupplierSelect style={{ width: 260 }} onChange={() => setAmounts({})} /></Form.Item>
        <Form.Item name="pay_type" label="款项类型"><Select options={dictOptions(PAY_TYPE)} style={{ width: 140 }} /></Form.Item>
        <Form.Item name="payment_method" label="付款方式"><Input placeholder="银行转账 / 支付宝 / 1688" style={{ width: 200 }} /></Form.Item>
      </Space>
      <Table<R> size="small" rowKey="id" pagination={false} dataSource={pos} locale={{ emptyText: supplierId ? '该供应商没有可请款的采购单' : '请先选择供应商' }}
        columns={[
          { title: '采购单号', dataIndex: 'po_no' },
          { title: '状态', dataIndex: 'status', render: (v) => <StatusTag dict={PO_STATUS} value={v} /> },
          { title: '总额', dataIndex: 'total_amount', render: (v, r) => fmtMoney(v, r.currency) },
          { title: '已付', dataIndex: 'paid_amount', render: (v, r) => fmtMoney(v, r.currency) },
          { title: '可请款', dataIndex: 'outstanding', render: (v, r) => fmtMoney(v, r.currency) },
          { title: '本次请款', render: (_, r) => (
            <Space.Compact>
              <InputNumber min={0} max={r.outstanding} value={amounts[r.id]} onChange={(v) => setAmounts((s) => ({ ...s, [r.id]: v ?? 0 }))} />
              <Button onClick={() => setAmounts((s) => ({ ...s, [r.id]: r.outstanding }))}>全部</Button>
            </Space.Compact>
          ) },
        ]} />
      <div style={{ textAlign: 'right', margin: '12px 0', fontSize: 16 }}>合计：<b>{fmtMoney(total, pos[0]?.currency)}</b></div>
      <Form.Item name="payee_account" label="收款账户"><Input /></Form.Item>
      <Form.Item name="remark" label="备注"><Input /></Form.Item>
    </FormModal>
  )
}

export default function Payments() {
  const [tab, setTab] = useState('pending')
  const [open, setOpen] = useState(false)
  const [rejecting, setRejecting] = useState<R | null>(null)
  const [paying, setPaying] = useState<R | null>(null)
  const reload = useReload('payment-requests')
  const run = useAction()
  return (
    <>
      <DataTable<R>
        queryKey="payment-requests"
        url="/payment-requests"
        extraParams={{ status: tab === 'all' ? undefined : tab }}
        header={<Tabs activeKey={tab} onChange={setTab} items={[
          ...Object.entries(PAYMENT_REQ_STATUS).map(([k, [l]]) => ({ key: k, label: l })), { key: 'all', label: '全部' },
        ]} />}
        filters={[{ name: 'keyword', placeholder: '请款单号 / 交易号' }, { name: 'supplier_id', type: 'custom', render: () => <SupplierSelect /> }]}
        toolbar={() => <Perm code="purchase:payment:edit"><Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>发起请款</Button></Perm>}
        expandable={{ expandedRowRender: (r) => (
          <Table<R> size="small" rowKey="id" pagination={false} dataSource={r.lines} columns={[
            { title: '采购单号', dataIndex: 'po_no' }, { title: '请款金额', dataIndex: 'amount', render: (v) => fmtMoney(v, r.currency) },
          ]} />
        ) }}
        columns={[
          { title: '请款单号', dataIndex: 'request_no' },
          { title: '供应商', dataIndex: 'supplier_name' },
          { title: '金额', dataIndex: 'amount', align: 'right', render: (v, r) => <b>{fmtMoney(v, r.currency)}</b> },
          { title: '类型', dataIndex: 'pay_type', render: (v) => PAY_TYPE[v]?.[0] ?? v },
          { title: '状态', dataIndex: 'status', render: (v) => <StatusTag dict={PAYMENT_REQ_STATUS} value={v} /> },
          { title: '付款方式', dataIndex: 'payment_method', render: (v) => v ?? '-' },
          { title: '交易号', dataIndex: 'transaction_no', render: (v) => v ?? '-' },
          { title: '付款时间', dataIndex: 'paid_at', render: fmtDateTime },
          { title: '申请时间', dataIndex: 'created_at', render: fmtDateTime },
          { title: '备注', dataIndex: 'remark', render: (v, r) => r.reject_reason ? <span style={{ color: '#cf1322' }}>驳回：{r.reject_reason}</span> : v ?? '-' },
          {
            title: '操作', key: 'op', fixed: 'right',
            render: (_, r) => (
              <Space>
                {r.status === 'pending' && (
                  <Perm code="purchase:payment:approve">
                    <a onClick={() => run(() => api.post(`/payment-requests/${r.id}/approve`), { onDone: reload })}>通过</a>
                    <a style={{ color: '#cf1322' }} onClick={() => setRejecting(r)}>驳回</a>
                  </Perm>
                )}
                {r.status === 'approved' && <Perm code="purchase:payment:approve"><a onClick={() => setPaying(r)}>确认付款</a></Perm>}
                {['pending', 'approved'].includes(r.status) && (
                  <Perm code="purchase:payment:edit">
                    <a onClick={() => run(() => api.post(`/payment-requests/${r.id}/cancel`), { confirm: '取消该请款单？', onDone: reload })}>取消</a>
                  </Perm>
                )}
              </Space>
            ),
          },
        ]}
      />
      <CreateRequest open={open} onClose={() => setOpen(false)} onDone={reload} />
      <FormModal open={!!rejecting} title="驳回请款" width={420} onCancel={() => setRejecting(null)}
        onSubmit={async (v) => { await api.post(`/payment-requests/${rejecting!.id}/reject`, v); reload() }}>
        <Form.Item name="reason" label="驳回原因" rules={[{ required: true }]}><Input.TextArea rows={3} /></Form.Item>
      </FormModal>
      <FormModal open={!!paying} title={`确认付款 ${paying ? fmtMoney(paying.amount, paying.currency) : ''}`} width={420} onCancel={() => setPaying(null)}
        initialValues={{ payment_method: paying?.payment_method }}
        onSubmit={async (v) => { await api.post(`/payment-requests/${paying!.id}/pay`, v); reload() }}>
        <Form.Item name="payment_method" label="付款方式"><Input /></Form.Item>
        <Form.Item name="transaction_no" label="交易流水号"><Input /></Form.Item>
      </FormModal>
    </>
  )
}
