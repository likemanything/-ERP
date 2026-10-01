import { useState } from 'react'
import { App, Button, Col, Form, Input, InputNumber, Modal, Row, Space, Table, Tabs } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, errorMessage } from '@/api/client'
import DataTable from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import LinesEditor, { type Line } from '@/components/LinesEditor'
import Perm from '@/components/Perm'
import { ChannelSelect, CurrencySelect, ShopSelect, WarehouseSelect } from '@/components/selects'
import { useBaseCurrency, usePerm } from '@/store/auth'
import OrderDetail from './OrderDetail'
import { orderColumns } from './Orders'

type Order = Record<string, any>

interface BatchResult {
  success: number[]
  failed: { order_id: number; message: string }[]
}

function useBatchResult() {
  const { modal, message } = App.useApp()
  return (r: BatchResult, action: string) => {
    if (!r.failed.length) {
      message.success(`${action}成功 ${r.success.length} 单`)
      return
    }
    modal.warning({
      title: `${action}：成功 ${r.success.length} 单，失败 ${r.failed.length} 单`,
      width: 560,
      content: (
        <div style={{ maxHeight: 300, overflow: 'auto' }}>
          {r.failed.map((f) => <div key={f.order_id}>订单 #{f.order_id}：{f.message}</div>)}
        </div>
      ),
    })
  }
}

function ShipModal({ orders, onClose, onDone }: { orders: Order[]; onClose: () => void; onDone: () => void }) {
  const [rows, setRows] = useState<Record<number, { tracking_no?: string; carrier?: string; actual_freight?: number }>>({})
  const [loading, setLoading] = useState(false)
  const show = useBatchResult()
  const { message } = App.useApp()
  const cur = useBaseCurrency()
  const set = (id: number, patch: object) => setRows((s) => ({ ...s, [id]: { ...s[id], ...patch } }))
  const submit = async () => {
    setLoading(true)
    try {
      const r = await api.post<BatchResult>('/orders/ship', { orders: orders.map((o) => ({ order_id: o.id, ...rows[o.id] })) })
      show(r, '发货')
      onDone()
      onClose()
    } catch (e) {
      message.error(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }
  return (
    <Modal open={orders.length > 0} title={`批量发货（${orders.length} 单）`} width={860} onCancel={onClose} onOk={submit} confirmLoading={loading} okText="确认发货" destroyOnHidden>
      <Table
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={orders}
        columns={[
          { title: '订单号', dataIndex: 'platform_order_id' },
          { title: '收件人', dataIndex: 'ship_name' },
          { title: '承运商', render: (_, o) => <Input placeholder="USPS / UPS" defaultValue={o.carrier} onChange={(e) => set(o.id, { carrier: e.target.value })} /> },
          { title: '运单号', render: (_, o) => <Input onChange={(e) => set(o.id, { tracking_no: e.target.value })} /> },
          {
            title: `实际运费(${cur})`,
            render: (_, o) => <InputNumber min={0} placeholder={String(o.est_freight ?? '')} onChange={(v) => set(o.id, { actual_freight: v ?? undefined })} />,
          },
        ]}
      />
    </Modal>
  )
}

export default function FbmOrders() {
  const [tab, setTab] = useState('to_audit')
  const [detail, setDetail] = useState<number | null>(null)
  const [auditing, setAuditing] = useState<number[]>([])
  const [shipping, setShipping] = useState<Order[]>([])
  const [creating, setCreating] = useState(false)
  const cur = useBaseCurrency()
  const can = usePerm()
  const run = useAction()
  const show = useBatchResult()
  const qc = useQueryClient()
  const reload = () => qc.invalidateQueries({ queryKey: ['fbm-orders'] })
  const { data: counts } = useQuery({
    queryKey: ['fbm-orders', 'counts'],
    queryFn: () => api.get<Record<string, number>>('/orders/status-counts', { fulfillment: 'FBM' }),
  })
  const label = (k: string, t: string) => `${t}${counts?.[k] ? ` (${counts[k]})` : ''}`
  const batch = async (url: string, body: object, action: string, clear: () => void) => {
    const r = await run(() => api.post<BatchResult>(url, body), { success: '' })
    if (r) {
      show(r, action)
      clear()
      reload()
    }
  }

  return (
    <>
      <DataTable<Order>
        queryKey="fbm-orders"
        url="/orders"
        rowSelection
        extraParams={{ fulfillment: 'FBM', status: tab === 'on_hold' ? 'pending,to_audit,to_ship' : tab, on_hold: tab === 'on_hold' ? true : undefined }}
        header={
          <Tabs
            activeKey={tab}
            onChange={setTab}
            items={[
              { key: 'to_audit', label: label('to_audit', '待审核') },
              { key: 'to_ship', label: label('to_ship', '待发货') },
              { key: 'on_hold', label: label('on_hold', '已挂起') },
              { key: 'pending', label: label('pending', '待付款') },
              { key: 'shipped', label: '已发货' },
              { key: 'cancelled', label: '已取消' },
            ]}
          />
        }
        filters={[
          { name: 'keyword', placeholder: '订单号 / MSKU / 买家', width: 240 },
          { name: 'shop_id', type: 'custom', render: () => <ShopSelect /> },
          { name: 'country', placeholder: '国家代码', width: 100 },
        ]}
        toolbar={({ selectedRowKeys, selectedRows, clearSelection }) => {
          const ids = selectedRowKeys as number[]
          const none = ids.length === 0
          return (
            <Space wrap>
              <Perm code="order:edit">
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>手工订单</Button>
              </Perm>
              {tab === 'to_audit' && (
                <Perm code="order:audit">
                  <Button type="primary" ghost disabled={none} onClick={() => setAuditing(ids)}>审核（锁库存）</Button>
                </Perm>
              )}
              {tab === 'to_ship' && (
                <>
                  <Perm code="order:ship">
                    <Button type="primary" ghost disabled={none} onClick={() => setShipping(selectedRows)}>发货</Button>
                  </Perm>
                  <Perm code="order:audit">
                    <Button disabled={none} onClick={() => batch('/orders/revert-audit', { order_ids: ids }, '反审核', clearSelection)}>反审核</Button>
                  </Perm>
                </>
              )}
              {['to_audit', 'to_ship', 'pending'].includes(tab) && (
                <Perm code="order:edit">
                  <Button disabled={none} onClick={() => batch('/orders/hold', { order_ids: ids, hold: true, reason: '手动挂起' }, '挂起', clearSelection)}>挂起</Button>
                </Perm>
              )}
              {tab === 'on_hold' && (
                <Perm code="order:edit">
                  <Button disabled={none} onClick={() => batch('/orders/hold', { order_ids: ids, hold: false }, '取消挂起', clearSelection)}>取消挂起</Button>
                </Perm>
              )}
              {['to_audit', 'to_ship', 'pending', 'on_hold'].includes(tab) && (
                <Perm code="order:cancel">
                  <Button danger disabled={none} onClick={() => run(() => api.post<BatchResult>('/orders/cancel', { order_ids: ids, reason: '手动取消' }), {
                    confirm: `确定取消选中的 ${ids.length} 个订单？已锁定的库存将释放。`, danger: true, success: '',
                    onDone: (r) => { show(r, '取消'); clearSelection(); reload() },
                  })}>取消订单</Button>
                </Perm>
              )}
            </Space>
          )
        }}
        columns={[
          ...orderColumns(cur, can('product:cost:view'), setDetail),
          { title: '发货仓', dataIndex: 'warehouse_name', render: (v: string) => v ?? '-' },
        ]}
      />
      <OrderDetail orderId={detail} onClose={() => setDetail(null)} />
      <FormModal
        open={auditing.length > 0}
        title={`审核 ${auditing.length} 个订单`}
        width={480}
        okText="审核并锁定库存"
        onCancel={() => setAuditing([])}
        onSubmit={async (v) => {
          const r = await api.post<BatchResult>('/orders/audit', { order_ids: auditing, ...v })
          show(r, '审核')
          reload()
        }}
      >
        <Form.Item name="warehouse_id" label="发货仓（为空使用默认发货仓）"><WarehouseSelect excludeFba /></Form.Item>
        <Form.Item name="logistics_channel_id" label="物流渠道（用于预估运费）"><ChannelSelect usage="last_mile" /></Form.Item>
      </FormModal>
      <ShipModal orders={shipping} onClose={() => setShipping([])} onDone={reload} />
      <FormModal
        open={creating}
        title="手工创建订单"
        width={900}
        onCancel={() => setCreating(false)}
        initialValues={{ items: [] }}
        onSubmit={async (v) => {
          const items = (v.items as Line[]).filter((l) => l.product_id).map((l) => ({
            product_id: l.product_id, quantity: l.quantity || 1, unit_price: l.unit_price || 0,
          }))
          await api.post('/orders', { ...v, items })
          reload()
        }}
      >
        <Row gutter={12}>
          <Col span={8}><Form.Item name="shop_id" label="店铺" rules={[{ required: true }]}><ShopSelect /></Form.Item></Col>
          <Col span={8}><Form.Item name="platform_order_id" label="订单号（为空自动生成）"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="currency" label="币种（默认店铺币种）"><CurrencySelect /></Form.Item></Col>
          <Col span={8}><Form.Item name="ship_name" label="收件人"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="ship_phone" label="电话"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="ship_country" label="国家代码"><Input placeholder="US" /></Form.Item></Col>
          <Col span={8}><Form.Item name="ship_state" label="州/省"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="ship_city" label="城市"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="ship_postcode" label="邮编"><Input /></Form.Item></Col>
          <Col span={24}><Form.Item name="ship_address1" label="地址"><Input /></Form.Item></Col>
        </Row>
        <Form.Item name="items" label="商品明细" rules={[{ validator: (_, v: Line[]) => (v?.some((l) => l.product_id) ? Promise.resolve() : Promise.reject(new Error('请添加商品'))) }]}>
          <LinesEditor
            addText="添加商品"
            columns={[
              { key: 'product_id', title: '商品（本地 SKU）', type: 'product', required: true },
              { key: 'quantity', title: '数量', type: 'number', width: 100, min: 1 },
              { key: 'unit_price', title: '单价', type: 'money', width: 140 },
            ]}
          />
        </Form.Item>
        <Form.Item name="remark" label="备注"><Input /></Form.Item>
      </FormModal>
    </>
  )
}
