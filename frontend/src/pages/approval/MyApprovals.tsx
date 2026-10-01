import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { App, Button, Drawer, Input, Space, Tabs, Typography } from 'antd'
import { useQueryClient } from '@tanstack/react-query'
import { api, errorMessage } from '@/api/client'
import DataTable from '@/components/DataTable'
import { ApprovalProgress, type ApprovalInstance } from '@/components/ApprovalTimeline'
import StatusTag from '@/components/StatusTag'
import { usePerm } from '@/store/auth'
import { APPROVAL_STATUS } from '@/utils/dicts'
import { fmtDateTime, fmtMoney } from '@/utils/format'

const DOC_TYPES = [
  { value: 'purchase_order', label: '采购单' },
  { value: 'payment_request', label: '请款单' },
  { value: 'recharge', label: '分销商充值' },
]

function ActDrawer({ inst, onClose }: { inst: ApprovalInstance | null; onClose: () => void }) {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [comment, setComment] = useState('')
  const [loading, setLoading] = useState(false)
  const act = async (approve: boolean) => {
    if (!approve && !comment.trim()) {
      message.warning('请填写驳回原因')
      return
    }
    setLoading(true)
    try {
      const r = await api.post<ApprovalInstance>(`/approval/instances/${inst!.id}/act`, { approve, comment: comment || undefined })
      message.success(approve ? (r.status === 'approved' ? '审批通过，流程结束' : '已通过，流转下一级') : '已驳回')
      qc.invalidateQueries({ queryKey: ['approvals'] })
      qc.invalidateQueries({ queryKey: ['approval-count'] })
      setComment('')
      onClose()
    } catch (e) {
      message.error(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }
  return (
    <Drawer open={!!inst} onClose={onClose} size={760} title={inst ? `${inst.doc_label} ${inst.doc_no ?? ''}` : ''} destroyOnHidden
      extra={inst?.link && <Button onClick={() => navigate(inst.link!.split('?')[0])}>查看单据</Button>}
      footer={inst?.can_act && (
        <Space orientation="vertical" style={{ width: '100%' }}>
          <Input.TextArea rows={2} placeholder="审批意见（驳回时必填）" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={255} />
          <Space style={{ justifyContent: 'flex-end', width: '100%' }}>
            <Button danger loading={loading} onClick={() => act(false)}>驳回</Button>
            <Button type="primary" loading={loading} onClick={() => act(true)}>通过</Button>
          </Space>
        </Space>
      )}>
      {inst && (
        <Space orientation="vertical" size="large" style={{ width: '100%' }}>
          <div>
            <Typography.Title level={5} style={{ marginTop: 0 }}>{inst.summary}</Typography.Title>
            <Space wrap>
              <StatusTag dict={APPROVAL_STATUS} value={inst.status} />
              <span>金额 <b>{fmtMoney(inst.amount, inst.currency)}</b></span>
              <Typography.Text type="secondary">提交人 {inst.submitter_name ?? '-'} · {fmtDateTime(inst.created_at)}</Typography.Text>
              <Typography.Text type="secondary">流程：{inst.flow_name}</Typography.Text>
            </Space>
          </div>
          <ApprovalProgress inst={inst} />
        </Space>
      )}
    </Drawer>
  )
}

export default function MyApprovals() {
  const can = usePerm()
  const [scope, setScope] = useState('mine')
  const [current, setCurrent] = useState<ApprovalInstance | null>(null)
  const tabs = [
    { key: 'mine', label: '待我审批' },
    { key: 'done', label: '我已审批' },
    { key: 'submitted', label: '我提交的' },
    ...(can('system:approval') ? [{ key: 'all', label: '全部审批' }] : []),
  ]
  return (
    <>
      <DataTable<ApprovalInstance>
        queryKey="approvals"
        url="/approval/instances"
        extraParams={{ scope }}
        header={<Tabs activeKey={scope} onChange={setScope} items={tabs} />}
        filters={[
          { name: 'doc_type', type: 'select', label: '单据类型', options: DOC_TYPES },
          { name: 'status', type: 'select', label: '状态', options: Object.entries(APPROVAL_STATUS).map(([value, [label]]) => ({ value, label })) },
        ]}
        columns={[
          { title: '单据', key: 'doc', render: (_, r) => <div><a onClick={() => setCurrent(r)}>{r.doc_label} {r.doc_no}</a><div style={{ fontSize: 12, color: '#888' }}>{r.summary}</div></div> },
          { title: '金额', key: 'amount', align: 'right', render: (_, r) => fmtMoney(r.amount, r.currency) },
          { title: '当前节点', key: 'step', render: (_, r) => (r.status === 'pending' ? `${r.current_step + 1}/${r.steps.length} ${r.steps[r.current_step]?.name ?? ''}` : '-') },
          { title: '状态', dataIndex: 'status', render: (v) => <StatusTag dict={APPROVAL_STATUS} value={v} /> },
          { title: '提交人', dataIndex: 'submitter_name', render: (v) => v ?? '-' },
          { title: '提交时间', dataIndex: 'created_at', render: (v) => fmtDateTime(v) },
          { title: '操作', key: 'op', render: (_, r) => <a onClick={() => setCurrent(r)}>{r.can_act ? '审批' : '查看'}</a> },
        ]}
      />
      <ActDrawer inst={current} onClose={() => setCurrent(null)} />
    </>
  )
}
