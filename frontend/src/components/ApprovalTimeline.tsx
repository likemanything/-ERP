import { Card, Space, Steps, Tag, Timeline, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import StatusTag from '@/components/StatusTag'
import { APPROVAL_STATUS } from '@/utils/dicts'
import { fmtDateTime } from '@/utils/format'

export interface ApprovalStep {
  name: string
  approver_type: 'user' | 'role'
  mode: 'any' | 'all'
  approver_names: string[]
  state: 'done' | 'current' | 'rejected' | 'waiting'
}

export interface ApprovalRecord {
  id: number
  step_index: number
  step_name: string
  user_name?: string | null
  action: 'approve' | 'reject'
  comment?: string | null
  created_at: string
}

export interface ApprovalInstance {
  id: number
  doc_type: string
  doc_label: string
  doc_id: number
  doc_no?: string | null
  flow_name: string
  current_step: number
  status: string
  amount: number
  currency?: string | null
  amount_base: number
  summary?: string | null
  link?: string | null
  submitter_name?: string | null
  created_at: string
  finished_at?: string | null
  steps: ApprovalStep[]
  records: ApprovalRecord[]
  can_act: boolean
}

const STEP_STATUS = { done: 'finish', current: 'process', rejected: 'error', waiting: 'wait' } as const

/** 审批进度：节点 + 审批意见 */
export function ApprovalProgress({ inst }: { inst: ApprovalInstance }) {
  return (
    <Space orientation="vertical" style={{ width: '100%' }}>
      <Steps
        size="small"
        items={inst.steps.map((s) => ({
          title: s.name,
          status: STEP_STATUS[s.state],
          content: (
            <span style={{ fontSize: 12 }}>
              {s.approver_names.join('、') || '-'}
              {s.approver_names.length > 1 && <Tag style={{ marginLeft: 4 }}>{s.mode === 'all' ? '会签' : '或签'}</Tag>}
            </span>
          ),
        }))}
      />
      {inst.records.length > 0 && (
        <Timeline
          style={{ marginTop: 12 }}
          items={inst.records.map((r) => ({
            color: r.action === 'approve' ? 'green' : 'red',
            content: (
              <span>
                <b>{r.user_name}</b>（{r.step_name}）{r.action === 'approve' ? '通过' : '驳回'}
                {r.comment && <Typography.Text type="secondary">：{r.comment}</Typography.Text>}
                <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>{fmtDateTime(r.created_at)}</Typography.Text>
              </span>
            ),
          }))}
        />
      )}
    </Space>
  )
}

/** 单据详情中的审批记录（无审批流程时不显示） */
export default function ApprovalTimeline({ docType, docId }: { docType: string; docId?: number | null }) {
  const { data } = useQuery({
    queryKey: ['approval-doc', docType, docId],
    queryFn: () => api.get<ApprovalInstance[]>(`/approval/documents/${docType}/${docId}`),
    enabled: !!docId,
  })
  const inst = data?.[0]
  if (!inst) return null
  return (
    <Card size="small" style={{ marginTop: 16 }} title={<Space>审批流程：{inst.flow_name}<StatusTag dict={APPROVAL_STATUS} value={inst.status} /></Space>}
      extra={data && data.length > 1 && <Typography.Text type="secondary">共提交 {data.length} 次，显示最近一次</Typography.Text>}>
      <ApprovalProgress inst={inst} />
    </Card>
  )
}
