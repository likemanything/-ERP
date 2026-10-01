import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Alert, App, Button, Form, Input, InputNumber, Space, Tabs, Tooltip } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import Perm from '@/components/Perm'
import StatusTag from '@/components/StatusTag'
import { ChannelSelect, DistributorSelect, WarehouseSelect } from '@/components/selects'
import { useBaseCurrency, usePerm } from '@/store/auth'
import { DISTRIBUTION_TYPE, ORDER_STATUS } from '@/utils/dicts'
import { fmtMoney } from '@/utils/format'
import OrderDetail from '@/pages/order/OrderDetail'
import { orderColumns } from '@/pages/order/Orders'

type Order = Record<string, any>
type BatchResult = { success: number[]; failed: { order_id: number; message: string }[] }

export default function DistributionOrders() {
  const navigate = useNavigate()
  const [search] = useSearchParams()
  const initialDistributor = search.get('distributor_id') ? Number(search.get('distributor_id')) : undefined
  const [tab, setTab] = useState('all')
  const [detail, setDetail] = useState<number | null>(null)
  const [charge, setCharge] = useState<Order | null>(null)
  const [auditing, setAuditing] = useState<number[] | null>(null)
  const cur = useBaseCurrency()
  const can = usePerm()
  const run = useAction()
  const qc = useQueryClient()
  const { message } = App.useApp()
  const reload = useReload('dist-orders')
  const done = () => { reload(); qc.invalidateQueries({ queryKey: ['dist-orders-counts'] }) }
  const { data: counts } = useQuery({
    queryKey: ['dist-orders-counts'],
    queryFn: () => api.get<Record<string, number>>('/orders/status-counts', { distribution_only: true }),
  })
  const tabs = [
    { key: 'all', label: '全部' },
    ...Object.entries(ORDER_STATUS).filter(([k]) => k !== 'pending').map(([k, [label]]) => ({ key: k, label: `${label}${counts?.[k] ? ` (${counts[k]})` : ''}` })),
  ]
  const extraParams = useMemo(() => ({ distribution_only: true, status: tab === 'all' ? undefined : tab }), [tab])

  const base = orderColumns(cur, can('product:cost:view'), setDetail)
  const columns = [
    base[0],
    {
      title: '分销商', key: 'dist',
      render: (_: unknown, r: Order) => (
        <div>
          <a onClick={() => navigate(`/distribution/funds?distributor_id=${r.distributor_id}`)}>{r.distributor_name}</a>
          <div><StatusTag dict={DISTRIBUTION_TYPE} value={r.distribution_type} /></div>
        </div>
      ),
    },
    ...base.slice(1, 3),
    {
      title: <Tooltip title="货款 + 运费 + 操作费 + 调整（分销商币种）">扣款金额</Tooltip>, key: 'charge', align: 'right' as const,
      render: (_: unknown, r: Order) => {
        const c = r.charge_detail ?? {}
        return (
          <div>
            <div style={{ fontWeight: 600 }}>{fmtMoney(c.total ?? 0, r.currency)}</div>
            <div style={{ fontSize: 12, color: '#888' }}>货 {fmtMoney(c.goods ?? 0, r.currency)} · 运 {fmtMoney(c.freight ?? 0, r.currency)} · 操 {fmtMoney(c.handling ?? 0, r.currency)}</div>
            {!!Number(c.refunded ?? 0) && <div style={{ fontSize: 12, color: '#cf1322' }}>已退 {fmtMoney(c.refunded, r.currency)}</div>}
          </div>
        )
      },
    },
    ...base.slice(4),
    {
      title: '操作', key: 'op', fixed: 'right' as const,
      render: (_: unknown, r: Order) => (
        <Space>
          <a onClick={() => setDetail(r.id)}>详情</a>
          {r.status === 'to_audit' && <Perm code="order:audit"><a onClick={() => setAuditing([r.id])}>审核</a></Perm>}
          {r.status !== 'cancelled' && <Perm code="distribution:finance"><a onClick={() => setCharge(r)}>补扣/退款</a></Perm>}
          {['to_audit', 'to_ship', 'pending'].includes(r.status) && (
            <Perm code="order:cancel">
              <a style={{ color: '#cf1322' }} onClick={() => run(async () => {
                const res = await api.post<BatchResult>('/orders/cancel', { order_ids: [r.id], reason: '后台取消分销订单' })
                if (res.failed.length) throw new Error(res.failed[0].message)
                return res
              }, { confirm: '取消后订单金额将自动退回分销商余额，确认取消？', danger: true, success: '已取消并退款', onDone: done })}>取消</a>
            </Perm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <>
      <Alert type="info" showIcon style={{ marginBottom: 12 }}
        title="分销商在门户下单时已实时扣款；订单进入正常履约流程（审核锁库存 → 自发货处理 → 发货），取消或退货会自动退款到分销商余额。"
        action={<Button size="small" onClick={() => navigate('/orders/fbm')}>去自发货处理</Button>} />
      <DataTable<Order>
        queryKey="dist-orders"
        url="/orders"
        rowSelection
        extraParams={extraParams}
        header={<Tabs activeKey={tab} onChange={setTab} items={tabs} />}
        filters={[
          { name: 'keyword', placeholder: '订单号 / SKU / 收件人 / 运单号', width: 240 },
          { name: 'distributor_id', type: 'custom', initial: initialDistributor, render: () => <DistributorSelect style={{ width: 200 }} /> },
          { name: 'date', type: 'dateRange', label: '下单日期' },
        ]}
        toolbar={(ctx) => (
          <Perm code="order:audit">
            <Button disabled={!ctx.selectedRows.some((r) => r.status === 'to_audit')}
              onClick={() => setAuditing(ctx.selectedRows.filter((r) => r.status === 'to_audit').map((r) => r.id))}>
              批量审核
            </Button>
          </Perm>
        )}
        columns={columns}
      />
      <OrderDetail orderId={detail} onClose={() => setDetail(null)} />
      <FormModal<{ amount: number; remark: string }>
        open={!!charge}
        title={`分销订单费用调整：${charge?.platform_order_id ?? ''}`}
        width={480}
        okText="确认"
        onCancel={() => setCharge(null)}
        onSubmit={async (v) => {
          await api.post(`/distribution/orders/${charge!.id}/charge`, v)
          message.success('已调整，资金流水已记录')
          done()
        }}
      >
        <Alert type="warning" title={`正数为补扣（如实际运费超出），负数为部分退款（如缺货少发）。金额币种：${charge?.currency ?? ''}`} style={{ marginBottom: 16 }} />
        <Form.Item name="amount" label="金额" rules={[{ required: true }]}><InputNumber precision={2} style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="remark" label="原因（分销商可见）" rules={[{ required: true }]}><Input /></Form.Item>
      </FormModal>
      <FormModal<{ warehouse_id?: number; logistics_channel_id?: number }>
        open={!!auditing}
        title={`审核分销订单（${auditing?.length ?? 0} 单）`}
        width={480}
        okText="审核并锁定库存"
        onCancel={() => setAuditing(null)}
        onSubmit={async (v) => {
          const r = await api.post<BatchResult>('/orders/audit', { order_ids: auditing, ...v })
          if (r.failed.length) message.warning(`成功 ${r.success.length} 单，失败 ${r.failed.length} 单：${r.failed.map((f) => f.message).join('；')}`)
          else message.success(`已审核 ${r.success.length} 单`)
          done()
        }}
      >
        <Form.Item name="warehouse_id" label="发货仓库" extra="为空使用默认仓库"><WarehouseSelect excludeFba /></Form.Item>
        <Form.Item name="logistics_channel_id" label="物流渠道" extra="为空保留分销商所选渠道"><ChannelSelect /></Form.Item>
      </FormModal>
    </>
  )
}
