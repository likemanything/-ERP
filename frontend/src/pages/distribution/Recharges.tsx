import { useState } from 'react'
import { App, Form, Input, Space, Tabs, Typography } from 'antd'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import Perm from '@/components/Perm'
import StatusTag from '@/components/StatusTag'
import { DistributorSelect } from '@/components/selects'
import { RECHARGE_STATUS } from '@/utils/dicts'
import { fmtDateTime, fmtMoney } from '@/utils/format'

type R = Record<string, any>

const METHOD: Record<string, string> = { bank: '银行转账', alipay: '支付宝', wechat: '微信', paypal: 'PayPal', other: '其他' }

export default function Recharges() {
  const [tab, setTab] = useState('pending')
  const [rejecting, setRejecting] = useState<R | null>(null)
  const reload = useReload('dist-recharges')
  const qc = useQueryClient()
  const run = useAction()
  const { message } = App.useApp()
  const done = () => {
    reload()
    qc.invalidateQueries({ queryKey: ['distributors'] })
    qc.invalidateQueries({ queryKey: ['notifications'] })
  }
  return (
    <>
      <DataTable<R>
        queryKey="dist-recharges"
        url="/distribution/recharges"
        extraParams={{ status: tab === 'all' ? undefined : tab }}
        header={
          <Tabs activeKey={tab} onChange={setTab}
            items={[{ key: 'pending', label: '待确认' }, { key: 'approved', label: '已到账' }, { key: 'rejected', label: '已驳回' }, { key: 'all', label: '全部' }]} />
        }
        filters={[{ name: 'distributor_id', type: 'custom', render: () => <DistributorSelect style={{ width: 220 }} /> }]}
        columns={[
          { title: '申请单号', dataIndex: 'request_no' },
          { title: '分销商', dataIndex: 'distributor_name' },
          { title: '充值金额', dataIndex: 'amount', align: 'right', render: (v, r) => <Typography.Text strong>{fmtMoney(v, r.currency)}</Typography.Text> },
          { title: '付款方式', dataIndex: 'payment_method', render: (v) => METHOD[v] ?? v ?? '-' },
          { title: '付款流水号', dataIndex: 'transaction_no', render: (v) => (v ? <Typography.Text copyable>{v}</Typography.Text> : '-') },
          { title: '凭证', dataIndex: 'proof_url', render: (v) => (v ? <a href={v} target="_blank" rel="noreferrer">查看</a> : '-') },
          { title: '备注', dataIndex: 'remark', render: (v) => v ?? '-' },
          { title: '提交时间', dataIndex: 'created_at', render: (v) => fmtDateTime(v) },
          { title: '状态', dataIndex: 'status', render: (v, r) => <Space orientation="vertical" size={0}><StatusTag dict={RECHARGE_STATUS} value={v} />{r.reject_reason && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{r.reject_reason}</Typography.Text>}</Space> },
          { title: '处理时间', dataIndex: 'reviewed_at', render: (v) => fmtDateTime(v) },
          {
            title: '操作', key: 'op', fixed: 'right',
            render: (_, r) =>
              r.status === 'pending' && (
                <Perm code="distribution:finance">
                  <Space>
                    <a onClick={() => run(() => api.post(`/distribution/recharges/${r.id}/review`, { approve: true }), {
                      confirm: <span>确认已收到 <b>{r.distributor_name}</b> 的 <b>{fmtMoney(r.amount, r.currency)}</b>？确认后立即入账。</span>,
                      success: '已确认到账', onDone: done,
                    })}>确认到账</a>
                    <a style={{ color: '#cf1322' }} onClick={() => setRejecting(r)}>驳回</a>
                  </Space>
                </Perm>
              ),
          },
        ]}
      />
      <FormModal<{ reason: string }>
        open={!!rejecting}
        title={`驳回充值申请：${rejecting?.request_no ?? ''}`}
        width={460}
        okText="驳回"
        onCancel={() => setRejecting(null)}
        onSubmit={async (v) => {
          await api.post(`/distribution/recharges/${rejecting!.id}/review`, { approve: false, reason: v.reason })
          message.success('已驳回')
          done()
        }}
      >
        <Form.Item name="reason" label="驳回原因（分销商可见）" rules={[{ required: true }]}><Input.TextArea rows={3} /></Form.Item>
      </FormModal>
    </>
  )
}
