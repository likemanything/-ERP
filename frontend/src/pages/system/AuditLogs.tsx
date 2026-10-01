import { Tag } from 'antd'
import DataTable from '@/components/DataTable'
import { UserSelect } from '@/components/selects'
import { fmtDateTime } from '@/utils/format'

type R = Record<string, any>

const ACTIONS: Record<string, string> = {
  create: '新增', update: '修改', delete: '删除', approve: '审批', reject: '驳回', submit: '提交', cancel: '作废/取消',
  receive: '收货', ship: '发货', pay: '付款', import: '导入', sync: '同步', pair: '配对', close: '完结', order: '下单',
  complete: '完成', change_password: '改密', reset_password: '重置密码',
}

export default function AuditLogs() {
  return (
    <DataTable<R>
      queryKey="audit-logs"
      url="/system/audit-logs"
      title="操作日志"
      pageSize={50}
      filters={[{ name: 'keyword', placeholder: '内容 / 用户 / 对象ID' }, { name: 'resource', placeholder: '对象类型，如 purchase_order', width: 220 }, { name: 'user_id', type: 'custom', render: () => <UserSelect /> }]}
      columns={[
        { title: '时间', dataIndex: 'created_at', render: fmtDateTime, width: 160 },
        { title: '用户', dataIndex: 'username', render: (v) => v ?? '系统' },
        { title: '动作', dataIndex: 'action', render: (v) => <Tag>{ACTIONS[v] ?? v}</Tag> },
        { title: '对象', dataIndex: 'resource' },
        { title: '对象ID', dataIndex: 'resource_id', render: (v) => v ?? '-' },
        { title: '内容', dataIndex: 'summary' },
        { title: 'IP', dataIndex: 'ip', render: (v) => v ?? '-' },
      ]}
    />
  )
}
