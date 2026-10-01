import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { App, Button, Card, Col, DatePicker, Empty, Row, Space, Statistic, Table, Tabs } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs, { type Dayjs } from 'dayjs'
import { api, download, errorMessage } from '@/api/client'
import DataTable from '@/components/DataTable'
import StatusTag from '@/components/StatusTag'
import { DistributorSelect } from '@/components/selects'
import { TXN_TYPE, dictOptions } from '@/utils/dicts'
import { fmtDateTime, fmtMoney } from '@/utils/format'

type T = Record<string, any>

const txnColumns = (withName: boolean) => [
  { title: '时间', dataIndex: 'created_at', render: (v: string) => fmtDateTime(v) },
  ...(withName ? [{ title: '分销商', dataIndex: 'distributor_name' }] : []),
  { title: '类型', dataIndex: 'txn_type', render: (v: string) => <StatusTag dict={TXN_TYPE} value={v} /> },
  { title: '关联单号', dataIndex: 'ref_no', render: (v?: string) => v ?? '-' },
  {
    title: '金额', dataIndex: 'amount', align: 'right' as const,
    render: (v: number, r: T) => <span style={{ color: v >= 0 ? '#389e0d' : '#cf1322' }}>{v > 0 ? '+' : ''}{fmtMoney(v, r.currency)}</span>,
  },
  { title: '变动后余额', dataIndex: 'balance_after', align: 'right' as const, render: (v: number, r: T) => fmtMoney(v, r.currency) },
  { title: '备注', dataIndex: 'remark', render: (v?: string) => v ?? '-' },
]

function StatementPanel({ initialDistributor }: { initialDistributor?: number }) {
  const { message } = App.useApp()
  const [distributorId, setDistributorId] = useState<number | undefined>(initialDistributor)
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().startOf('month'), dayjs()])
  const params = { distributor_id: distributorId, date_from: range[0].format('YYYY-MM-DD'), date_to: range[1].format('YYYY-MM-DD') }
  const { data: st, isFetching } = useQuery({
    queryKey: ['dist-statement', params],
    queryFn: () => api.get<T>('/distribution/statement', params),
    enabled: !!distributorId,
  })
  return (
    <Space orientation="vertical" style={{ width: '100%' }} size="middle">
      <Space wrap>
        <DistributorSelect value={distributorId} onChange={setDistributorId} style={{ width: 240 }} />
        <DatePicker.RangePicker allowClear={false} value={range} onChange={(v) => v?.[0] && v[1] && setRange([v[0], v[1]])} />
        <Button icon={<DownloadOutlined />} disabled={!distributorId}
          onClick={() => download('/distribution/statement/export', params).catch((e) => message.error(errorMessage(e)))}>
          导出对账单
        </Button>
      </Space>
      {!distributorId ? (
        <Empty description="请选择分销商" />
      ) : (
        st && (
          <>
            <Row gutter={[16, 16]}>
              {([
                ['期初余额', st.opening_balance], ['充值', st.recharge], ['订单扣款', st.order], ['退款', st.refund], ['调整', st.adjust], ['期末余额', st.closing_balance],
              ] as [string, number][]).map(([k, v]) => (
                <Col xs={12} md={4} key={k}><Card size="small"><Statistic title={k} value={v} precision={2} prefix={st.currency} /></Card></Col>
              ))}
              <Col xs={12} md={4}><Card size="small"><Statistic title="订单数" value={st.order_count} /></Card></Col>
              <Col xs={12} md={4}><Card size="small"><Statistic title="出货件数" value={st.units} /></Card></Col>
            </Row>
            <Table<T> rowKey="id" size="small" loading={isFetching} dataSource={st.transactions} columns={txnColumns(false)} pagination={{ pageSize: 50 }} />
          </>
        )
      )}
    </Space>
  )
}

export default function DistributionFunds() {
  const [search] = useSearchParams()
  const initialDistributor = search.get('distributor_id') ? Number(search.get('distributor_id')) : undefined
  const [tab, setTab] = useState('txns')
  return (
    <Card variant="borderless">
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'txns',
            label: '资金流水',
            children: (
              <DataTable<T>
                card={false}
                queryKey="dist-txns"
                url="/distribution/transactions"
                filters={[
                  { name: 'distributor_id', type: 'custom', initial: initialDistributor, render: () => <DistributorSelect style={{ width: 220 }} /> },
                  { name: 'txn_type', type: 'select', label: '类型', options: dictOptions(TXN_TYPE) },
                  { name: 'keyword', placeholder: '单号 / 备注' },
                ]}
                columns={txnColumns(true)}
              />
            ),
          },
          { key: 'statement', label: '对账单', children: <StatementPanel initialDistributor={initialDistributor} /> },
        ]}
      />
    </Card>
  )
}
