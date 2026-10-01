import { useMemo, useState } from 'react'
import { Button, Card, DatePicker, Segmented, Space, Statistic, Table } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs, { type Dayjs } from 'dayjs'
import type { EChartsOption } from 'echarts'
import { api, download } from '@/api/client'
import EChart from '@/components/EChart'
import { ShopSelect } from '@/components/selects'
import { useBaseCurrency } from '@/store/auth'
import { currencySymbol, fmtMoney } from '@/utils/format'

type R = Record<string, any>

export default function SalesReport() {
  const cur = useBaseCurrency()
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(29, 'day'), dayjs()])
  const [groupBy, setGroupBy] = useState('day')
  const [shopId, setShopId] = useState<number>()
  const params = { date_from: range[0].format('YYYY-MM-DD'), date_to: range[1].format('YYYY-MM-DD'), group_by: groupBy, shop_id: shopId }
  const { data, isFetching } = useQuery({ queryKey: ['sales-report', params], queryFn: () => api.get<{ items: R[]; totals: R }>('/reports/sales', params) })
  const items = data?.items ?? []
  const chart = useMemo<EChartsOption>(() => {
    if (['day', 'month'].includes(groupBy)) {
      return {
        tooltip: { trigger: 'axis' }, legend: { top: 0, data: ['销售额', '销量'] }, grid: { left: 70, right: 50, top: 40, bottom: 30 },
        xAxis: { type: 'category', data: items.map((r) => r.period) },
        yAxis: [{ type: 'value' }, { type: 'value', splitLine: { show: false } }],
        series: [
          { name: '销售额', type: 'line', smooth: true, areaStyle: { opacity: 0.15 }, data: items.map((r) => r.sales) },
          { name: '销量', type: 'bar', yAxisIndex: 1, data: items.map((r) => r.units), itemStyle: { color: '#95de64' } },
        ],
      }
    }
    const top = items.slice(0, 15)
    const name = (r: R) => r.msku ?? r.sku ?? r.shop_name ?? r.country
    return {
      tooltip: { trigger: 'axis' }, grid: { left: 140, right: 30, top: 20, bottom: 30 },
      xAxis: { type: 'value' }, yAxis: { type: 'category', inverse: true, data: top.map(name) },
      series: [{ type: 'bar', data: top.map((r) => r.sales), itemStyle: { color: '#1677ff' } }],
    }
  }, [items, groupBy])
  const keyCol = ({
    day: { title: '日期', dataIndex: 'period' }, month: { title: '月份', dataIndex: 'period' }, shop: { title: '店铺', dataIndex: 'shop_name' },
    msku: { title: 'MSKU', dataIndex: 'msku', render: (v: string, r: R) => <div>{v}<div style={{ fontSize: 12, color: '#888' }}>{r.shop_name}</div></div> },
    sku: { title: 'SKU', dataIndex: 'sku', render: (v: string, r: R) => <div>{v}<div style={{ fontSize: 12, color: '#888' }}>{r.product_name}</div></div> },
    country: { title: '国家', dataIndex: 'country' },
  } as Record<string, R>)[groupBy]
  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <Card variant="borderless">
        <Space wrap>
          <DatePicker.RangePicker value={range} allowClear={false} onChange={(v) => v && setRange(v as [Dayjs, Dayjs])} />
          <ShopSelect value={shopId} onChange={setShopId} />
          <Segmented value={groupBy} onChange={(v) => setGroupBy(v as string)} options={[
            { value: 'day', label: '按天' }, { value: 'month', label: '按月' }, { value: 'shop', label: '店铺' },
            { value: 'msku', label: 'MSKU' }, { value: 'sku', label: 'SKU' }, { value: 'country', label: '国家' },
          ]} />
          <Button icon={<DownloadOutlined />} onClick={() => download('/reports/sales/export', params)}>导出</Button>
        </Space>
        {data && (
          <Space size={48} style={{ marginTop: 16 }}>
            <Statistic title="销售额" value={data.totals.sales} precision={2} prefix={currencySymbol(cur)} />
            <Statistic title="订单数" value={data.totals.orders} />
            <Statistic title="销量" value={data.totals.units} />
            <Statistic title="客单价" value={data.totals.orders ? data.totals.sales / data.totals.orders : 0} precision={2} prefix={currencySymbol(cur)} />
          </Space>
        )}
      </Card>
      <Card variant="borderless"><EChart option={chart} height={320} /></Card>
      <Card variant="borderless">
        <Table<R> size="small" loading={isFetching} dataSource={items} rowKey={(r) => JSON.stringify(r)} pagination={{ pageSize: 50 }} columns={[
          keyCol,
          { title: '销量', dataIndex: 'units', align: 'right', sorter: (a: R, b: R) => a.units - b.units },
          { title: '订单数', dataIndex: 'orders', align: 'right' },
          { title: '销售额', dataIndex: 'sales', align: 'right', render: (v: number) => fmtMoney(v, cur), sorter: (a: R, b: R) => a.sales - b.sales },
          { title: '均价', dataIndex: 'avg_price', align: 'right', render: (v: number) => fmtMoney(v, cur) },
          { title: '占比', key: 'pct', align: 'right', render: (_: unknown, r: R) => (data?.totals.sales ? `${((r.sales / data.totals.sales) * 100).toFixed(1)}%` : '-') },
        ] as never} />
      </Card>
    </Space>
  )
}
