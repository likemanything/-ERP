import { useNavigate } from 'react-router-dom'
import { Alert, Button, Card, Col, Row, Space, Statistic, Table, Tag } from 'antd'
import { AppstoreOutlined, ImportOutlined, WalletOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { fmtDateTime, fmtMoney } from '@/utils/format'
import { STATUS_COLOR, type PortalDistributor, type PortalOrder } from '../api'
import { tStatus, useT } from '../i18n'

interface Dashboard {
  distributor: PortalDistributor
  status_counts: Record<string, number>
  month_spend: number
  recent_orders: PortalOrder[]
  pending_recharges: number
}

export default function PortalHome() {
  const t = useT()
  const navigate = useNavigate()
  const { data } = useQuery({ queryKey: ['portal-dashboard'], queryFn: () => api.get<Dashboard>('/portal/dashboard') })
  const d = data?.distributor
  const cur = d?.currency
  const counts = data?.status_counts ?? {}
  const low = d && d.available_funds < Math.max(100, d.credit_limit * 0.1)
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      {low && <Alert type="warning" showIcon title={t('lowFunds')} action={<Button size="small" onClick={() => navigate('/portal/funds?recharge=1')}>{t('recharge')}</Button>} />}
      {!!data?.pending_recharges && <Alert type="info" showIcon title={`${data.pending_recharges} ${t('pendingRecharge')}`} />}
      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}><Card variant="borderless"><Statistic title={t('availableFunds')} value={d?.available_funds ?? 0} precision={2} prefix={cur} styles={{ content: { color: '#389e0d' } }} /></Card></Col>
        <Col xs={12} md={6}><Card variant="borderless"><Statistic title={t('balance')} value={d?.balance ?? 0} precision={2} prefix={cur} /></Card></Col>
        <Col xs={12} md={6}><Card variant="borderless"><Statistic title={t('creditLimit')} value={d?.credit_limit ?? 0} precision={2} prefix={cur} /></Card></Col>
        <Col xs={12} md={6}><Card variant="borderless"><Statistic title={t('monthSpend')} value={data?.month_spend ?? 0} precision={2} prefix={cur} /></Card></Col>
      </Row>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={16}>
          <Card variant="borderless" title={t('recentOrders')} extra={<a onClick={() => navigate('/portal/orders')}>{t('viewAll')}</a>}>
            <Table<PortalOrder>
              size="small"
              rowKey="id"
              pagination={false}
              dataSource={data?.recent_orders ?? []}
              columns={[
                { title: t('referenceNo'), dataIndex: 'reference_no' },
                { title: t('createdAt'), dataIndex: 'created_at', render: (v) => fmtDateTime(v) },
                { title: t('recipient'), dataIndex: 'ship_name' },
                { title: t('amount'), key: 'amt', align: 'right', render: (_, r) => fmtMoney(Number(r.charge_detail?.total ?? 0), r.currency) },
                { title: t('status'), dataIndex: 'status', render: (v) => <Tag color={STATUS_COLOR[v]}>{tStatus(t, 'status', v)}</Tag> },
                { title: t('tracking'), dataIndex: 'tracking_no', render: (v) => v ?? '-' },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card variant="borderless" title={t('orders')}>
            <Row gutter={[8, 16]}>
              {(['to_audit', 'to_ship', 'shipped', 'cancelled'] as const).map((s) => (
                <Col span={12} key={s}>
                  <a onClick={() => navigate(`/portal/orders?status=${s}`)}>
                    <Statistic title={tStatus(t, 'status', s)} value={counts[s] ?? 0} />
                  </a>
                </Col>
              ))}
            </Row>
          </Card>
          <Card variant="borderless" title={t('quickActions')} style={{ marginTop: 16 }}>
            <Space wrap>
              <Button type="primary" icon={<AppstoreOutlined />} onClick={() => navigate('/portal/catalog')}>{t('browseCatalog')}</Button>
              <Button icon={<ImportOutlined />} onClick={() => navigate('/portal/orders?import=1')}>{t('importOrders')}</Button>
              <Button icon={<WalletOutlined />} onClick={() => navigate('/portal/funds?recharge=1')}>{t('recharge')}</Button>
            </Space>
            {d?.level_name && <div style={{ marginTop: 16, color: '#888' }}>{t('level')}：<Tag color="purple">{d.level_name}</Tag></div>}
          </Card>
        </Col>
      </Row>
    </Space>
  )
}
