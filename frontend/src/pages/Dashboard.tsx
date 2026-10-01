import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Col, Row, Skeleton, Statistic, Table, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import type { EChartsOption } from 'echarts'
import { api } from '@/api/client'
import EChart from '@/components/EChart'
import ProductCell from '@/components/ProductCell'
import { useBaseCurrency, usePerm } from '@/store/auth'
import { currencySymbol, fmtMoney, fmtPercent } from '@/utils/format'

interface Period {
  sales: number
  orders: number
  units: number
}

interface Overview {
  kpi: Record<'today' | 'yesterday' | 'last_7d' | 'last_30d' | 'month', Period>
  trend: { date: string; sales: number; orders: number; units: number }[]
  by_shop: { shop_id: number; shop_name: string; sales: number; orders: number }[]
  top_products: { shop_name: string; msku: string; asin?: string; title?: string; image_url?: string; sales: number; units: number; orders: number }[]
  todo: Record<string, number>
  month_profit?: { sales: number; profit: number; margin: number | null; ad_spend: number }
}

const TODOS: { key: string; label: string; path: string; perm: string }[] = [
  { key: 'orders_to_audit', label: '待审核订单', path: '/orders/fbm', perm: 'order:view' },
  { key: 'orders_to_ship', label: '待发货订单', path: '/orders/fbm', perm: 'order:view' },
  { key: 'po_pending_approval', label: '采购单待审批', path: '/purchase/orders', perm: 'purchase:order:view' },
  { key: 'po_to_receive', label: '采购待到货', path: '/purchase/orders', perm: 'purchase:order:view' },
  { key: 'purchase_plans_pending', label: '待处理采购计划', path: '/purchase/plans', perm: 'purchase:plan:view' },
  { key: 'payments_pending', label: '请款待审批', path: '/purchase/payments', perm: 'purchase:payment:view' },
  { key: 'payments_to_pay', label: '待付款', path: '/purchase/payments', perm: 'purchase:payment:view' },
  { key: 'shipment_plans_pending', label: '待处理发货计划', path: '/fba/plans', perm: 'fba:plan:view' },
  { key: 'shipments_in_transit', label: '头程在途货件', path: '/fba/shipments', perm: 'fba:shipment:view' },
  { key: 'unpaired_listings', label: '未配对 Listing', path: '/listings', perm: 'listing:view' },
  { key: 'low_stock', label: '低于安全库存', path: '/inventory', perm: 'inventory:view' },
]

function change(cur: number, prev: number) {
  if (!prev) return null
  const pct = ((cur - prev) / prev) * 100
  return <span style={{ color: pct >= 0 ? '#389e0d' : '#cf1322', fontSize: 12 }}>{pct >= 0 ? '↑' : '↓'} {Math.abs(pct).toFixed(1)}%</span>
}

export default function Dashboard() {
  const navigate = useNavigate()
  const can = usePerm()
  const cur = useBaseCurrency()
  const { data, isLoading } = useQuery({ queryKey: ['dashboard'], queryFn: () => api.get<Overview>('/dashboard/overview'), refetchInterval: 5 * 60_000 })

  const trendOption = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: 'axis' },
    legend: { top: 0, data: ['销售额', '订单数'] },
    grid: { left: 60, right: 50, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: (data?.trend ?? []).map((t) => t.date.slice(5)) },
    yAxis: [
      { type: 'value', name: `销售额(${cur})` },
      { type: 'value', name: '订单', splitLine: { show: false } },
    ],
    series: [
      { name: '销售额', type: 'bar', data: (data?.trend ?? []).map((t) => t.sales), itemStyle: { color: '#1677ff' }, barMaxWidth: 18 },
      { name: '订单数', type: 'line', yAxisIndex: 1, smooth: true, data: (data?.trend ?? []).map((t) => t.orders), itemStyle: { color: '#fa8c16' } },
    ],
  }), [data, cur])

  const shopOption = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: 'item', formatter: '{b}<br/>{c} ({d}%)' },
    legend: { bottom: 0, type: 'scroll' },
    series: [{
      type: 'pie', radius: ['45%', '70%'], center: ['50%', '45%'],
      data: (data?.by_shop ?? []).map((s) => ({ name: s.shop_name, value: s.sales })),
      label: { formatter: '{b}\n{d}%' },
    }],
  }), [data])

  if (isLoading || !data) return <Card><Skeleton active paragraph={{ rows: 12 }} /></Card>
  const k = data.kpi
  const sym = currencySymbol(cur)

  return (
    <div>
      <Row gutter={[16, 16]}>
        {([['今日', k.today, k.yesterday], ['昨日', k.yesterday, null], ['近7天', k.last_7d, null], ['近30天', k.last_30d, null], ['本月', k.month, null]] as const).map(([label, p, prev]) => (
          <Col xs={12} md={8} lg={label === '本月' ? 4 : 5} key={label}>
            <Card className="kpi-card" size="small">
              <Statistic title={`${label}销售额`} value={p.sales} precision={2} prefix={sym} />
              <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>
                订单 {p.orders} · 销量 {p.units} {prev && change(p.sales, prev.sales)}
              </div>
            </Card>
          </Col>
        ))}
      </Row>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={16}>
          <Card title="近 30 天销售趋势" size="small">
            <EChart option={trendOption} height={320} />
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="待办事项" size="small" styles={{ body: { padding: 12 } }}>
            <Row gutter={[8, 8]}>
              {TODOS.filter((t) => can(t.perm)).map((t) => (
                <Col span={12} key={t.key}>
                  <div
                    onClick={() => navigate(t.path)}
                    style={{ cursor: 'pointer', padding: '10px 12px', background: '#fafafa', borderRadius: 6, display: 'flex', justifyContent: 'space-between' }}
                  >
                    <span style={{ fontSize: 13 }}>{t.label}</span>
                    <Typography.Text strong style={{ color: data.todo[t.key] ? '#1677ff' : '#bbb' }}>
                      {data.todo[t.key] ?? 0}
                    </Typography.Text>
                  </div>
                </Col>
              ))}
            </Row>
            {data.month_profit && (
              <Card size="small" style={{ marginTop: 12, background: '#f6ffed', borderColor: '#b7eb8f' }}>
                <Row>
                  <Col span={12}>
                    <Statistic title="本月毛利润" value={data.month_profit.profit} precision={2} prefix={sym}
                      styles={{ content: { color: data.month_profit.profit >= 0 ? '#389e0d' : '#cf1322', fontSize: 20 } }} />
                  </Col>
                  <Col span={12}>
                    <Statistic title="毛利率" value={data.month_profit.margin ?? 0} precision={2} suffix="%" styles={{ content: { fontSize: 20 } }} />
                  </Col>
                </Row>
                <div style={{ fontSize: 12, color: '#888' }}>本月广告花费 {fmtMoney(data.month_profit.ad_spend, cur)}</div>
              </Card>
            )}
          </Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={8}>
          <Card title="店铺销售占比（近30天）" size="small">
            <EChart option={shopOption} height={300} />
          </Card>
        </Col>
        <Col xs={24} lg={16}>
          <Card title="热销 Listing TOP10（近30天）" size="small">
            <Table
              size="small"
              rowKey={(r) => `${r.shop_name}-${r.msku}`}
              pagination={false}
              dataSource={data.top_products}
              columns={[
                { title: '商品', render: (_, r) => <ProductCell image={r.image_url} title={r.msku} sub={r.title} extra={r.shop_name} size={36} /> },
                { title: '销量', dataIndex: 'units', align: 'right' },
                { title: '订单', dataIndex: 'orders', align: 'right' },
                { title: '销售额', dataIndex: 'sales', align: 'right', render: (v) => fmtMoney(v, cur) },
                { title: '占比', align: 'right', render: (_, r) => fmtPercent(k.last_30d.sales ? (r.sales / k.last_30d.sales) * 100 : 0, 1) },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
