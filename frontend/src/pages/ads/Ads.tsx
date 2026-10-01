import { useMemo, useState } from 'react'
import { Button, Card, Col, DatePicker, Input, Row, Segmented, Space, Statistic, Table, Tag } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs, { type Dayjs } from 'dayjs'
import type { EChartsOption } from 'echarts'
import { api } from '@/api/client'
import EChart from '@/components/EChart'
import { ImportModal } from '@/components/common'
import Perm from '@/components/Perm'
import { ShopSelect } from '@/components/selects'
import { useBaseCurrency } from '@/store/auth'
import { currencySymbol, fmtMoney, fmtPercent } from '@/utils/format'

type R = Record<string, any>

const acosTag = (v: number | null) => (v === null || v === undefined ? '-' : <Tag color={v > 40 ? 'red' : v > 25 ? 'orange' : 'green'}>{fmtPercent(v)}</Tag>)

export default function Ads() {
  const cur = useBaseCurrency()
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(29, 'day'), dayjs()])
  const [groupBy, setGroupBy] = useState('campaign')
  const [shopId, setShopId] = useState<number>()
  const [keyword, setKeyword] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const [importShop, setImportShop] = useState<number>()
  const qc = useQueryClient()
  const base = { date_from: range[0].format('YYYY-MM-DD'), date_to: range[1].format('YYYY-MM-DD'), shop_id: shopId }
  const { data, isFetching } = useQuery({
    queryKey: ['ads-summary', base, groupBy, keyword],
    queryFn: () => api.get<{ items: R[]; totals: R }>('/ads/summary', { ...base, group_by: groupBy, keyword: keyword || undefined }),
  })
  const { data: daily } = useQuery({
    queryKey: ['ads-summary', base, 'day'],
    queryFn: () => api.get<{ items: R[]; totals: R }>('/ads/summary', { ...base, group_by: 'day' }),
  })
  const t = data?.totals
  const chart = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: 'axis' },
    legend: { top: 0, data: ['花费', '广告销售额', 'ACoS'] },
    grid: { left: 60, right: 50, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: (daily?.items ?? []).map((r) => r.date.slice(5)) },
    yAxis: [{ type: 'value' }, { type: 'value', axisLabel: { formatter: '{value}%' }, splitLine: { show: false } }],
    series: [
      { name: '花费', type: 'bar', data: (daily?.items ?? []).map((r) => r.spend), itemStyle: { color: '#ff7875' } },
      { name: '广告销售额', type: 'bar', data: (daily?.items ?? []).map((r) => r.sales), itemStyle: { color: '#69b1ff' } },
      { name: 'ACoS', type: 'line', yAxisIndex: 1, data: (daily?.items ?? []).map((r) => r.acos), itemStyle: { color: '#fa8c16' } },
    ],
  }), [daily])
  const keyCols: R[] = {
    campaign: [{ title: '广告活动', dataIndex: 'campaign_name', render: (v: string, r: R) => <div>{v}<div style={{ fontSize: 12, color: '#888' }}>{r.shop_name} · {r.ad_type}</div></div> }],
    msku: [{ title: 'MSKU', dataIndex: 'msku', render: (v: string, r: R) => <div>{v || '-'}<div style={{ fontSize: 12, color: '#888' }}>{r.shop_name} · {r.asin ?? ''}</div></div> }],
    shop: [{ title: '店铺', dataIndex: 'shop_name' }],
  }[groupBy] as R[]
  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <Card variant="borderless">
        <Space wrap>
          <DatePicker.RangePicker value={range} allowClear={false} onChange={(v) => v && setRange(v as [Dayjs, Dayjs])} />
          <ShopSelect value={shopId} onChange={setShopId} />
          <Segmented value={groupBy} onChange={(v) => setGroupBy(v as string)} options={[{ value: 'campaign', label: '广告活动' }, { value: 'msku', label: 'MSKU' }, { value: 'shop', label: '店铺' }]} />
          <Input.Search allowClear placeholder="活动 / MSKU / ASIN" onSearch={setKeyword} style={{ width: 200 }} />
          <Perm code="ads:edit"><Button icon={<UploadOutlined />} onClick={() => setImportOpen(true)}>导入广告报表</Button></Perm>
        </Space>
        {t && (
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col xs={12} md={4}><Statistic title="花费" value={t.spend} precision={2} prefix={currencySymbol(cur)} /></Col>
            <Col xs={12} md={4}><Statistic title="广告销售额" value={t.sales} precision={2} prefix={currencySymbol(cur)} /></Col>
            <Col xs={12} md={4}><Statistic title="ACoS" value={t.acos ?? 0} precision={2} suffix="%" /></Col>
            <Col xs={12} md={4}><Statistic title="ROAS" value={t.roas ?? 0} precision={2} /></Col>
            <Col xs={12} md={4}><Statistic title="点击 / CTR" value={`${t.clicks} / ${fmtPercent(t.ctr)}`} /></Col>
            <Col xs={12} md={4}><Statistic title="订单 / CVR" value={`${t.orders} / ${fmtPercent(t.cvr)}`} /></Col>
          </Row>
        )}
      </Card>
      <Card variant="borderless" title="每日趋势"><EChart option={chart} height={280} /></Card>
      <Card variant="borderless">
        <Table<R> size="small" loading={isFetching} dataSource={data?.items ?? []} rowKey={(r) => JSON.stringify([r.shop_id, r.campaign_id, r.msku])}
          scroll={{ x: 'max-content' }} pagination={{ pageSize: 50 }}
          columns={[
            ...keyCols,
            { title: '曝光', dataIndex: 'impressions', align: 'right' },
            { title: '点击', dataIndex: 'clicks', align: 'right' },
            { title: 'CTR', dataIndex: 'ctr', align: 'right', render: (v: number) => fmtPercent(v) },
            { title: 'CPC', dataIndex: 'cpc', align: 'right', render: (v: number) => fmtMoney(v, cur) },
            { title: '花费', dataIndex: 'spend', align: 'right', render: (v: number) => fmtMoney(v, cur), sorter: (a: R, b: R) => a.spend - b.spend },
            { title: '销售额', dataIndex: 'sales', align: 'right', render: (v: number) => fmtMoney(v, cur) },
            { title: '订单', dataIndex: 'orders', align: 'right' },
            { title: 'CVR', dataIndex: 'cvr', align: 'right', render: (v: number) => fmtPercent(v) },
            { title: 'ACoS', dataIndex: 'acos', align: 'right', render: acosTag, sorter: (a: R, b: R) => (a.acos ?? 999) - (b.acos ?? 999) },
            { title: 'ROAS', dataIndex: 'roas', align: 'right' },
          ] as never}
        />
      </Card>
      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} title="导入广告日报（Sponsored Products 报表）" uploadUrl="/ads/import"
        templateUrl="/ads/import-template" fields={importShop ? { shop_id: importShop } : undefined}
        onDone={() => qc.invalidateQueries({ queryKey: ['ads-summary'] })}
        extra={<ShopSelect value={importShop} onChange={setImportShop} placeholder="选择店铺（必选）" />} />
    </Space>
  )
}
