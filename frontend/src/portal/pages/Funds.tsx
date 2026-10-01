import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Alert, App, Button, Card, Col, DatePicker, Form, Input, InputNumber, Row, Select, Space, Statistic, Table, Tabs, Tag } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs, { type Dayjs } from 'dayjs'
import { api, cleanParams, type Page } from '@/api/client'
import { FormModal } from '@/components/common'
import { fmtDateTime, fmtMoney } from '@/utils/format'
import { usePortalMe } from '../api'
import { tStatus, useT } from '../i18n'

interface Txn {
  id: number
  created_at: string
  txn_type: string
  amount: number
  balance_after: number
  currency: string
  ref_no?: string | null
  remark?: string | null
}

interface Recharge {
  id: number
  request_no: string
  created_at: string
  amount: number
  currency: string
  payment_method?: string | null
  transaction_no?: string | null
  status: string
  reviewed_at?: string | null
  reject_reason?: string | null
}

interface Statement {
  currency: string
  opening_balance: number
  closing_balance: number
  recharge: number
  order: number
  refund: number
  adjust: number
  order_count: number
  units: number
  transactions: Txn[]
}

const TXN_COLOR: Record<string, string> = { recharge: 'green', order: 'blue', refund: 'cyan', adjust: 'orange' }
const RECHARGE_COLOR: Record<string, string> = { pending: 'orange', approved: 'green', rejected: 'red' }

function usePaged<T>(key: string, url: string, extra: Record<string, unknown> = {}) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const params = cleanParams({ ...extra, page, page_size: pageSize })
  const q = useQuery({ queryKey: [key, params], queryFn: () => api.get<Page<T>>(url, params), placeholderData: keepPreviousData })
  return {
    ...q,
    pagination: {
      current: page,
      pageSize,
      total: q.data?.total ?? 0,
      showSizeChanger: true,
      onChange: (p: number, ps: number) => { setPage(p); setPageSize(ps) },
    },
  }
}

export default function PortalFunds() {
  const t = useT()
  const qc = useQueryClient()
  const { message } = App.useApp()
  const { data: me } = usePortalMe()
  const d = me?.distributor
  const [search, setSearch] = useSearchParams()
  const [txnType, setTxnType] = useState<string>()
  const [tab, setTab] = useState(search.get('recharge') ? 'recharges' : 'txns')
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().startOf('month'), dayjs()])
  const txns = usePaged<Txn>('portal-txns', '/portal/transactions', { txn_type: txnType })
  const recharges = usePaged<Recharge>('portal-recharges', '/portal/recharges')
  const { data: st, isFetching: stLoading } = useQuery({
    queryKey: ['portal-statement', range[0].format('YYYY-MM-DD'), range[1].format('YYYY-MM-DD')],
    queryFn: () => api.get<Statement>('/portal/statement', { date_from: range[0].format('YYYY-MM-DD'), date_to: range[1].format('YYYY-MM-DD') }),
    enabled: tab === 'statement',
  })
  const rechargeOpen = search.get('recharge') === '1'
  const cur = d?.currency

  const txnColumns = [
    { title: t('time'), dataIndex: 'created_at', render: (v: string) => fmtDateTime(v) },
    { title: t('txnType'), dataIndex: 'txn_type', render: (v: string) => <Tag color={TXN_COLOR[v]}>{tStatus(t, 'txn', v)}</Tag> },
    { title: t('refNo'), dataIndex: 'ref_no', render: (v?: string) => v ?? '-' },
    {
      title: t('amount'), dataIndex: 'amount', align: 'right' as const,
      render: (v: number, r: Txn) => <span style={{ color: v >= 0 ? '#389e0d' : '#cf1322' }}>{v > 0 ? '+' : ''}{fmtMoney(v, r.currency)}</span>,
    },
    { title: t('balanceAfter'), dataIndex: 'balance_after', align: 'right' as const, render: (v: number, r: Txn) => fmtMoney(v, r.currency) },
    { title: t('remark'), dataIndex: 'remark', render: (v?: string) => v ?? '-' },
  ]

  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}><Card variant="borderless"><Statistic title={t('availableFunds')} value={d?.available_funds ?? 0} precision={2} prefix={cur} styles={{ content: { color: '#389e0d' } }} /></Card></Col>
        <Col xs={12} md={8}><Card variant="borderless"><Statistic title={t('balance')} value={d?.balance ?? 0} precision={2} prefix={cur} /></Card></Col>
        <Col xs={12} md={8}><Card variant="borderless"><Statistic title={t('creditLimit')} value={d?.credit_limit ?? 0} precision={2} prefix={cur} /></Card></Col>
      </Row>
      <Card variant="borderless">
        <Tabs
          activeKey={tab}
          onChange={setTab}
          tabBarExtraContent={<Button type="primary" icon={<PlusOutlined />} onClick={() => setSearch({ recharge: '1' })}>{t('newRecharge')}</Button>}
          items={[
            {
              key: 'txns',
              label: t('transactions'),
              children: (
                <>
                  <Select allowClear placeholder={t('txnType')} style={{ width: 160, marginBottom: 12 }} value={txnType} onChange={setTxnType}
                    options={['recharge', 'order', 'refund', 'adjust'].map((v) => ({ value: v, label: tStatus(t, 'txn', v) }))} />
                  <Table<Txn> rowKey="id" size="small" loading={txns.isFetching} dataSource={txns.data?.items ?? []} columns={txnColumns}
                    pagination={{ ...txns.pagination, showTotal: (n) => t('total_n', { n }) }} scroll={{ x: 'max-content' }} />
                </>
              ),
            },
            {
              key: 'recharges',
              label: t('rechargeRecords'),
              children: (
                <Table<Recharge>
                  rowKey="id"
                  size="small"
                  loading={recharges.isFetching}
                  dataSource={recharges.data?.items ?? []}
                  pagination={{ ...recharges.pagination, showTotal: (n) => t('total_n', { n }) }}
                  scroll={{ x: 'max-content' }}
                  columns={[
                    { title: t('requestNo'), dataIndex: 'request_no' },
                    { title: t('time'), dataIndex: 'created_at', render: (v) => fmtDateTime(v) },
                    { title: t('rechargeAmount'), dataIndex: 'amount', align: 'right', render: (v, r) => fmtMoney(v, r.currency) },
                    { title: t('paymentMethod'), dataIndex: 'payment_method', render: (v) => (v ? t(v as 'bank') : '-') },
                    { title: t('transactionNo'), dataIndex: 'transaction_no', render: (v) => v ?? '-' },
                    { title: t('status'), dataIndex: 'status', render: (v) => <Tag color={RECHARGE_COLOR[v]}>{tStatus(t, 'recharge', v)}</Tag> },
                    { title: t('rejectReason'), dataIndex: 'reject_reason', render: (v) => v ?? '-' },
                  ]}
                />
              ),
            },
            {
              key: 'statement',
              label: t('statement'),
              children: (
                <Space orientation="vertical" style={{ width: '100%' }}>
                  <Space>
                    <span>{t('period')}</span>
                    <DatePicker.RangePicker allowClear={false} value={range} onChange={(v) => v?.[0] && v[1] && setRange([v[0], v[1]])} />
                  </Space>
                  {st && (
                    <Row gutter={[16, 16]}>
                      {([
                        ['opening', st.opening_balance],
                        ['rechargeTotal', st.recharge],
                        ['orderTotal', st.order],
                        ['refundTotal', st.refund],
                        ['adjustTotal', st.adjust],
                        ['closing', st.closing_balance],
                      ] as const).map(([k, v]) => (
                        <Col xs={12} md={4} key={k}><Statistic title={t(k)} value={v} precision={2} prefix={st.currency} /></Col>
                      ))}
                      <Col xs={12} md={4}><Statistic title={t('orderCount')} value={st.order_count} /></Col>
                      <Col xs={12} md={4}><Statistic title={t('units')} value={st.units} /></Col>
                    </Row>
                  )}
                  <Table<Txn> rowKey="id" size="small" loading={stLoading} dataSource={st?.transactions ?? []} columns={txnColumns} pagination={{ pageSize: 50 }} scroll={{ x: 'max-content' }} />
                </Space>
              ),
            },
          ]}
        />
      </Card>
      <FormModal<{ amount: number; payment_method?: string; transaction_no?: string; proof_url?: string; remark?: string }>
        open={rechargeOpen}
        title={t('newRecharge')}
        width={520}
        okText={t('submit')}
        initialValues={{ payment_method: 'bank' }}
        onCancel={() => setSearch({})}
        onSubmit={async (v) => {
          await api.post('/portal/recharges', v)
          message.success(t('rechargeSubmitted'))
          setTab('recharges')
          qc.invalidateQueries({ queryKey: ['portal-recharges'] })
          qc.invalidateQueries({ queryKey: ['portal-dashboard'] })
        }}
      >
        <Alert type="info" title={t('rechargeHint')} style={{ marginBottom: 16 }} />
        <Form.Item name="amount" label={`${t('rechargeAmount')}（${cur ?? ''}）`} rules={[{ required: true, message: t('required') }]}>
          <InputNumber min={0.01} precision={2} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="payment_method" label={t('paymentMethod')}>
          <Select options={(['bank', 'alipay', 'wechat', 'paypal', 'other'] as const).map((v) => ({ value: v, label: t(v) }))} />
        </Form.Item>
        <Form.Item name="transaction_no" label={t('transactionNo')} rules={[{ required: true, message: t('required') }]}>
          <Input />
        </Form.Item>
        <Form.Item name="proof_url" label={t('proofUrl')}>
          <Input placeholder="https://" />
        </Form.Item>
        <Form.Item name="remark" label={t('remark')}>
          <Input.TextArea rows={2} />
        </Form.Item>
      </FormModal>
    </Space>
  )
}
