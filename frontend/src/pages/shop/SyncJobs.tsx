import { Tooltip, Typography } from 'antd'
import DataTable from '@/components/DataTable'
import StatusTag from '@/components/StatusTag'
import { ShopSelect } from '@/components/selects'
import { SYNC_JOB_TYPE, SYNC_STATUS, dictOptions } from '@/utils/dicts'
import { fmtDateTime } from '@/utils/format'

type Job = Record<string, any>

export default function SyncJobs() {
  return (
    <DataTable<Job>
      queryKey="sync-jobs"
      url="/sync-jobs"
      title="平台数据同步记录"
      filters={[
        { name: 'shop_id', type: 'custom', render: () => <ShopSelect /> },
        { name: 'status', type: 'select', label: '状态', options: dictOptions(SYNC_STATUS) },
      ]}
      columns={[
        { title: '店铺', dataIndex: 'shop_name' },
        { title: '数据类型', dataIndex: 'job_type', render: (v) => <StatusTag dict={SYNC_JOB_TYPE} value={v} /> },
        { title: '触发', dataIndex: 'trigger', render: (v) => (v === 'manual' ? '手动' : '定时') },
        { title: '状态', dataIndex: 'status', render: (v) => <StatusTag dict={SYNC_STATUS} value={v} /> },
        {
          title: '结果', dataIndex: 'stats',
          render: (s) => (s ? `新增 ${s.created ?? 0} / 更新 ${s.updated ?? 0}${s.errors ? ` / 失败 ${s.errors}` : ''}` : '-'),
        },
        { title: '开始时间', dataIndex: 'started_at', render: fmtDateTime },
        {
          title: '耗时', key: 'cost',
          render: (_, r) => (r.finished_at && r.started_at ? `${Math.max(0, Math.round((+new Date(r.finished_at) - +new Date(r.started_at)) / 1000))} 秒` : '-'),
        },
        {
          title: '错误信息', dataIndex: 'error',
          render: (v, r) => {
            const samples: string[] = r.stats?.error_samples ?? []
            const text = v || samples.join('\n')
            return text ? (
              <Tooltip title={<pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{text}</pre>}>
                <Typography.Text type="danger" ellipsis style={{ maxWidth: 280 }}>{text}</Typography.Text>
              </Tooltip>
            ) : '-'
          },
        },
      ]}
    />
  )
}
