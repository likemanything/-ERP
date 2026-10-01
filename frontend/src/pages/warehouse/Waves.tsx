import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { App, Button, Descriptions, Drawer, Progress, Space, Table, Tabs, Tag, Typography } from 'antd'
import { PrinterOutlined, ScanOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, errorMessage, openPdf } from '@/api/client'
import DataTable from '@/components/DataTable'
import { useAction } from '@/components/common'
import Perm from '@/components/Perm'
import ProductCell from '@/components/ProductCell'
import StatusTag from '@/components/StatusTag'
import { WarehouseSelect } from '@/components/selects'
import { ORDER_STATUS, WAVE_STATUS } from '@/utils/dicts'
import { fmtDateTime } from '@/utils/format'

type W = Record<string, any>

function WaveDetail({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const run = useAction()
  const [selected, setSelected] = useState<React.Key[]>([])
  const { data: w, isFetching } = useQuery({ queryKey: ['waves', 'detail', id], queryFn: () => api.get<W>(`/fulfillment/waves/${id}`), enabled: !!id })
  const reload = () => qc.invalidateQueries({ queryKey: ['waves'] })
  const active = w && ['picking', 'picked'].includes(w.status)
  return (
    <Drawer open={!!id} onClose={onClose} size={1000} title={w ? `拣货波次 ${w.wave_no}` : '拣货波次'} destroyOnHidden
      extra={w && (
        <Space>
          <Button icon={<PrinterOutlined />} onClick={() => openPdf(`/fulfillment/waves/${w.id}/pick-list.pdf`).then(reload).catch((e) => message.error(errorMessage(e)))}>拣货单</Button>
          <Button icon={<PrinterOutlined />} onClick={() => openPdf(`/fulfillment/waves/${w.id}/packing-slips.pdf`).catch((e) => message.error(errorMessage(e)))}>装箱单</Button>
          {active && <Button type="primary" icon={<ScanOutlined />} onClick={() => navigate('/warehouse/scan-ship')}>扫码验货发货</Button>}
        </Space>
      )}>
      {w && (
        <Space orientation="vertical" size="large" style={{ width: '100%' }}>
          <Descriptions size="small" bordered column={3}>
            <Descriptions.Item label="仓库">{w.warehouse_name}</Descriptions.Item>
            <Descriptions.Item label="状态"><StatusTag dict={WAVE_STATUS} value={w.status} /></Descriptions.Item>
            <Descriptions.Item label="发货进度"><Progress percent={w.order_count ? Math.round((w.shipped_count / w.order_count) * 100) : 0} size="small" format={() => `${w.shipped_count}/${w.order_count}`} /></Descriptions.Item>
            <Descriptions.Item label="SKU / 件数">{w.sku_count} / {w.unit_count}</Descriptions.Item>
            <Descriptions.Item label="拣货员">{w.picker_name ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="打印次数">{w.print_count}</Descriptions.Item>
          </Descriptions>
          <Tabs
            items={[
              {
                key: 'lines',
                label: `拣货汇总（${w.lines.length}）`,
                children: (
                  <Table<W>
                    size="small"
                    rowKey="product_id"
                    loading={isFetching}
                    pagination={false}
                    dataSource={w.lines}
                    columns={[
                      { title: '库位', dataIndex: 'bin_code', render: (v) => (v ? <Tag color="blue">{v}</Tag> : <Typography.Text type="secondary">未设置</Typography.Text>) },
                      { title: '商品', key: 'p', render: (_, r) => <ProductCell image={r.image_url} title={r.sku} sub={r.name} /> },
                      { title: '数量', dataIndex: 'qty', align: 'right', render: (v) => <Typography.Text strong style={{ fontSize: 16 }}>{v}</Typography.Text> },
                      { title: '订单分布', dataIndex: 'orders', render: (v: W[]) => <span style={{ fontSize: 12 }}>{v.map((x) => `${x.platform_order_id}×${x.qty}`).join('，')}</span> },
                    ]}
                  />
                ),
              },
              {
                key: 'orders',
                label: `订单（${w.orders.length}）`,
                children: (
                  <>
                    {active && (
                      <Perm code="order:ship">
                        <Button style={{ marginBottom: 12 }} disabled={!selected.length}
                          onClick={() => run(() => api.post(`/fulfillment/waves/${w.id}/remove-orders`, { order_ids: selected }), {
                            confirm: `将 ${selected.length} 个订单移出波次（如缺货、地址异常）？订单保持待发货状态。`,
                            onDone: () => { setSelected([]); reload() },
                          })}>
                          移出波次
                        </Button>
                      </Perm>
                    )}
                    <Table<W>
                      size="small"
                      rowKey="id"
                      pagination={false}
                      dataSource={w.orders}
                      rowSelection={active ? { selectedRowKeys: selected, onChange: setSelected, getCheckboxProps: (r) => ({ disabled: r.status !== 'to_ship' }) } : undefined}
                      columns={[
                        { title: '系统单号', dataIndex: 'order_no' },
                        { title: '平台单号', dataIndex: 'platform_order_id' },
                        { title: '店铺', dataIndex: 'shop_name' },
                        { title: '收件人', key: 'to', render: (_, r) => `${r.ship_name ?? '-'} / ${r.ship_country ?? '-'}` },
                        { title: '件数', dataIndex: 'units', align: 'right' },
                        { title: '状态', dataIndex: 'status', render: (v) => <StatusTag dict={ORDER_STATUS} value={v} /> },
                        { title: '运单号', dataIndex: 'tracking_no', render: (v) => v ?? '-' },
                      ]}
                    />
                  </>
                ),
              },
            ]}
          />
        </Space>
      )}
    </Drawer>
  )
}

export default function Waves() {
  const [tab, setTab] = useState('picking,picked')
  const [detail, setDetail] = useState<number | null>(null)
  const { message } = App.useApp()
  const run = useAction()
  const qc = useQueryClient()
  const reload = () => qc.invalidateQueries({ queryKey: ['waves'] })
  return (
    <>
      <DataTable<W>
        queryKey="waves"
        url="/fulfillment/waves"
        extraParams={{ status: tab === 'all' ? undefined : tab }}
        header={<Tabs activeKey={tab} onChange={setTab} items={[
          { key: 'picking,picked', label: '进行中' }, { key: 'completed', label: '已完成' }, { key: 'cancelled', label: '已取消' }, { key: 'all', label: '全部' },
        ]} />}
        filters={[
          { name: 'keyword', placeholder: '波次号 / 订单号' },
          { name: 'warehouse_id', type: 'custom', render: () => <WarehouseSelect excludeFba /> },
        ]}
        toolbar={() => <Typography.Text type="secondary">在「自发货处理 → 待发货」中勾选订单或按仓库生成波次</Typography.Text>}
        columns={[
          { title: '波次号', dataIndex: 'wave_no', render: (v, r) => <a onClick={() => setDetail(r.id)}>{v}</a> },
          { title: '仓库', dataIndex: 'warehouse_name' },
          { title: '状态', dataIndex: 'status', render: (v) => <StatusTag dict={WAVE_STATUS} value={v} /> },
          {
            title: '发货进度', key: 'progress', width: 180,
            render: (_, r) => <Progress size="small" percent={r.order_count ? Math.round((r.shipped_count / r.order_count) * 100) : 0} format={() => `${r.shipped_count}/${r.order_count}`} />,
          },
          { title: 'SKU / 件数', key: 'units', render: (_, r) => `${r.sku_count} / ${r.unit_count}` },
          { title: '拣货员', dataIndex: 'picker_name', render: (v) => v ?? '-' },
          { title: '打印', dataIndex: 'print_count', render: (v) => (v ? `${v} 次` : <Tag color="orange">未打印</Tag>) },
          { title: '创建时间', dataIndex: 'created_at', render: (v) => fmtDateTime(v) },
          {
            title: '操作', key: 'op', fixed: 'right',
            render: (_, r) => (
              <Space>
                <a onClick={() => openPdf(`/fulfillment/waves/${r.id}/pick-list.pdf`).then(reload).catch((e) => message.error(errorMessage(e)))}>拣货单</a>
                <a onClick={() => openPdf(`/fulfillment/waves/${r.id}/packing-slips.pdf`).catch((e) => message.error(errorMessage(e)))}>装箱单</a>
                <a onClick={() => setDetail(r.id)}>详情</a>
                <Perm code="order:ship">
                  <Space>
                    {r.status === 'picking' && <a onClick={() => run(() => api.post(`/fulfillment/waves/${r.id}/picked`, {}), { success: '已标记拣货完成', onDone: reload })}>拣货完成</a>}
                    {['picking', 'picked'].includes(r.status) && (
                      <>
                        <a onClick={() => run(() => api.post(`/fulfillment/waves/${r.id}/complete`), { onDone: reload })}>完成</a>
                        <a style={{ color: '#cf1322' }} onClick={() => run(() => api.post(`/fulfillment/waves/${r.id}/cancel`), { confirm: '取消波次后，未发货订单退回待发货、可重新生成波次。确认？', onDone: reload })}>取消</a>
                      </>
                    )}
                  </Space>
                </Perm>
              </Space>
            ),
          },
        ]}
      />
      <WaveDetail id={detail} onClose={() => setDetail(null)} />
    </>
  )
}
