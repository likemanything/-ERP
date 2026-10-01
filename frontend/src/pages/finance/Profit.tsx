import { useMemo, useState } from 'react'
import { Button, Card, Col, DatePicker, Input, Row, Segmented, Space, Statistic, Table, Tooltip } from 'antd'
import { DownloadOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs, { type Dayjs } from 'dayjs'
import type { EChartsOption } from 'echarts'
import { api, download } from '@/api/client'
import EChart from '@/components/EChart'
import ProductCell from '@/components/ProductCell'
import { ShopSelect } from '@/components/selects'
import { useBaseCurrency } from '@/store/auth'
import { currencySymbol, fmtMoney, fmtPercent, profitColor } from '@/utils/format'

type R = Record<string, any>

const GROUPS = [
  { value: 'msku', label: 'MSKU' },
  { value: 'sku', label: 'SKU' },
  { value: 'shop', label: '店铺' },
  { value: 'day', label: '按天' },
  { value: 'month', label: '按月' },
]

export default function Profit() {
  const cur = useBaseCurrency()
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(29, 'day'), dayjs()])
  const [groupBy, setGroupBy] = useState('msku')
  const [shopId, setShopId] = useState<number>()
  const [keyword, setKeyword] = useState('')
  const params = { date_from: range[0].format('YYYY-MM-DD'), date_to: range[1].format('YYYY-MM-DD'), group_by: groupBy, shop_id: shopId }
  const { data, isFetching } = useQuery({
    queryKey: ['profit', params, keyword],
    queryFn: () => api.get<{ items: R[]; totals: R }>('/finance/profit', { ...params, keyword: keyword || undefined }),
  })
  const t = data?.totals
  const money = (v: number) => fmtMoney(v, cur)

  const chart = useMemo<EChartsOption | null>(() => {
    if (!data || !['day', 'month'].includes(groupBy)) return null
    return {
      tooltip: { trigger: 'axis' },
      legend: { top: 0, data: ['销售额', '毛利润', '毛利率'] },
      grid: { left: 70, right: 50, top: 40, bottom: 30 },
      xAxis: { type: 'category', data: data.items.map((r) => r.period) },
      yAxis: [{ type: 'value' }, { type: 'value', axisLabel: { formatter: '{value}%' }, splitLine: { show: false } }],
      series: [
        { name: '销售额', type: 'bar', data: data.items.map((r) => r.sales), itemStyle: { color: '#91caff' } },
        { name: '毛利润', type: 'bar', data: data.items.map((r) => r.profit), itemStyle: { color: '#52c41a' } },
        { name: '毛利率', type: 'line', yAxisIndex: 1, data: data.items.map((r) => r.margin), itemStyle: { color: '#fa8c16' } },
      ],
    }
  }, [data, groupBy])

  const keyCols: R[] = {
    msku: [{ title: 'Listing', key: 'k', fixed: 'left', render: (_: unknown, r: R) => <ProductCell image={r.image_url} title={r.msku ?? '店铺/公共费用'} sub={r.title} extra={`${r.shop_name ?? ''}${r.sku ? ` · ${r.sku}` : ''}`} size={32} /> }],
    sku: [{ title: 'SKU', key: 'k', fixed: 'left', render: (_: unknown, r: R) => <ProductCell image={r.image_url} title={r.sku ?? '未配对/公共'} sub={r.product_name} size={32} /> }],
    shop: [{ title: '店铺', dataIndex: 'shop_name', fixed: 'left' }],
    day: [{ title: '日期', dataIndex: 'period', fixed: 'left' }],
    month: [{ title: '月份', dataIndex: 'period', fixed: 'left' }],
  }[groupBy] as R[]

  const columns = [
    ...keyCols,
    { title: '销量', dataIndex: 'units', align: 'right' },
    { title: '订单', dataIndex: 'orders', align: 'right' },
    { title: '销售额', dataIndex: 'sales', align: 'right', render: money, sorter: (a: R, b: R) => a.sales - b.sales },
    { title: '退款', dataIndex: 'refunds', align: 'right', render: money },
    { title: '平台佣金', dataIndex: 'commission', align: 'right', render: money },
    { title: 'FBA配送费', dataIndex: 'fulfillment_fee', align: 'right', render: money },
    { title: '广告费', dataIndex: 'ad_spend', align: 'right', render: money },
    { title: '采购成本', dataIndex: 'cost_purchase', align: 'right', render: money },
    { title: '头程成本', dataIndex: 'cost_freight', align: 'right', render: money },
    { title: '自发货运费', dataIndex: 'logistics', align: 'right', render: money },
    { title: '平台其他费', dataIndex: 'platform_other_fee', align: 'right', render: money },
    { title: '其他费用', dataIndex: 'expenses', align: 'right', render: money },
    {
      title: '毛利润', dataIndex: 'profit', align: 'right', fixed: 'right', sorter: (a: R, b: R) => a.profit - b.profit,
      render: (v: number) => <b style={{ color: profitColor(v) }}>{money(v)}</b>,
    },
    { title: '毛利率', dataIndex: 'margin', align: 'right', fixed: 'right', render: (v: number) => <span style={{ color: profitColor(v) }}>{fmtPercent(v)}</span> },
    { title: 'ROI', dataIndex: 'roi', align: 'right', render: (v: number) => fmtPercent(v) },
    { title: 'ACoS', dataIndex: 'acos', align: 'right', render: (v: number) => fmtPercent(v) },
  ]

  return (
    <Space orientation="vertical" style={{ width: '100%' }} size={16}>
      <Card variant="borderless">
        <Space wrap>
          <DatePicker.RangePicker value={range} allowClear={false} onChange={(v) => v && setRange(v as [Dayjs, Dayjs])}
            presets={[
              { label: '近7天', value: [dayjs().subtract(6, 'day'), dayjs()] },
              { label: '近30天', value: [dayjs().subtract(29, 'day'), dayjs()] },
              { label: '本月', value: [dayjs().startOf('month'), dayjs()] },
              { label: '上月', value: [dayjs().subtract(1, 'month').startOf('month'), dayjs().subtract(1, 'month').endOf('month')] },
              { label: '今年', value: [dayjs().startOf('year'), dayjs()] },
            ]} />
          <ShopSelect value={shopId} onChange={setShopId} />
          <Segmented options={GROUPS} value={groupBy} onChange={(v) => setGroupBy(v as string)} />
          {['msku', 'sku'].includes(groupBy) && <Input.Search allowClear placeholder="MSKU / SKU / 品名" onSearch={setKeyword} style={{ width: 200 }} />}
          <Button icon={<DownloadOutlined />} onClick={() => download('/finance/profit/export', params)}>导出</Button>
          <Tooltip title="已发货订单口径：销售额 - 退款 - 平台费用 - 广告费 - FIFO 采购成本 - 头程成本 + 退货回库 - 自发货运费 - 平台其他费用 - 费用单。外币按月度汇率折算为本位币。">
            <QuestionCircleOutlined style={{ color: '#888' }} />
          </Tooltip>
        </Space>
        {t && (
          <Row gutter={16} style={{ marginTop: 16 }}>
            {[
              ['销售额', t.sales], ['毛利润', t.profit], ['广告费', t.ad_spend], ['平台费用', t.commission + t.fulfillment_fee + t.other_order_fee + t.platform_other_fee],
              ['商品成本', t.cogs], ['其他费用', t.expenses],
            ].map(([label, v]) => (
              <Col flex="1 1 150px" key={label as string}>
                <Statistic title={label as string} value={v as number} precision={2} prefix={currencySymbol(cur)}
                  styles={{ content: { color: label === '毛利润' ? profitColor(v as number) : undefined, fontSize: 20 } }} />
              </Col>
            ))}
            <Col flex="1 1 150px"><Statistic title="毛利率 / ROI" value={`${fmtPercent(t.margin)} / ${fmtPercent(t.roi)}`} styles={{ content: { fontSize: 20 } }} /></Col>
          </Row>
        )}
      </Card>
      {chart && <Card variant="borderless"><EChart option={chart} height={300} /></Card>}
      <Card variant="borderless">
        <Table<R>
          rowKey={(r) => JSON.stringify([r.shop_id, r.msku, r.product_id, r.period])}
          size="small"
          loading={isFetching}
          dataSource={data?.items ?? []}
          columns={columns as never}
          scroll={{ x: 'max-content' }}
          pagination={{ pageSize: 50, showSizeChanger: true }}
          summary={() => t && (
            <Table.Summary fixed>
              <Table.Summary.Row style={{ fontWeight: 600, background: '#fafafa' }}>
                <Table.Summary.Cell index={0}>合计</Table.Summary.Cell>
                <Table.Summary.Cell index={1} align="right">{t.units}</Table.Summary.Cell>
                <Table.Summary.Cell index={2} align="right">{t.orders}</Table.Summary.Cell>
                {['sales', 'refunds', 'commission', 'fulfillment_fee', 'ad_spend', 'cost_purchase', 'cost_freight', 'logistics', 'platform_other_fee', 'expenses', 'profit'].map((k, i) => (
                  <Table.Summary.Cell key={k} index={3 + i} align="right"><span style={{ color: k === 'profit' ? profitColor(t[k]) : undefined }}>{money(t[k])}</span></Table.Summary.Cell>
                ))}
                <Table.Summary.Cell index={14} align="right">{fmtPercent(t.margin)}</Table.Summary.Cell>
                <Table.Summary.Cell index={15} align="right">{fmtPercent(t.roi)}</Table.Summary.Cell>
                <Table.Summary.Cell index={16} align="right">{fmtPercent(t.acos)}</Table.Summary.Cell>
              </Table.Summary.Row>
            </Table.Summary>
          )}
        />
      </Card>
    </Space>
  )
}
