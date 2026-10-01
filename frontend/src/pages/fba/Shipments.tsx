import { useState } from 'react'
import { App, Button, Col, DatePicker, Descriptions, Divider, Drawer, Form, Input, InputNumber, Modal, Row, Select, Space, Table, Tabs, Tag } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { api, errorMessage } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import LinesEditor, { type Line } from '@/components/LinesEditor'
import Perm from '@/components/Perm'
import ProductCell from '@/components/ProductCell'
import StatusTag from '@/components/StatusTag'
import { ChannelSelect, CurrencySelect, ShopSelect, WarehouseSelect } from '@/components/selects'
import { useBaseCurrency, usePerm } from '@/store/auth'
import { ALLOCATION_METHOD, SHIPMENT_STATUS, dictOptions } from '@/utils/dicts'
import { fmtDate, fmtDateTime, fmtMoney } from '@/utils/format'

type R = Record<string, any>

const dateStr = (v: unknown) => (v ? dayjs(v as string).format('YYYY-MM-DD') : null)

function CreateShipment({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [form] = Form.useForm()
  const shopId = Form.useWatch('shop_id', form)
  return (
    <FormModal open={open} form={form} title="新建头程货件" width={960} onCancel={onClose}
      initialValues={{ cost_currency: 'CNY', freight_cost: 0, customs_duty: 0, other_cost: 0, allocation_method: 'weight', lines: [] }}
      onSubmit={async (v) => {
        const lines = (v.lines as Line[]).filter((l) => l.listing_id && l.qty).map((l) => ({ listing_id: l.listing_id, qty: l.qty }))
        if (!lines.length) throw new Error('请添加明细')
        await api.post('/fba-shipments', { ...v, lines, ship_date: dateStr(v.ship_date), eta: dateStr(v.eta) })
        onDone()
      }}>
      <Row gutter={12}>
        <Col span={6}><Form.Item name="shop_id" label="店铺" rules={[{ required: true }]}><ShopSelect /></Form.Item></Col>
        <Col span={6}><Form.Item name="ship_from_warehouse_id" label="发货仓" rules={[{ required: true }]}><WarehouseSelect excludeFba /></Form.Item></Col>
        <Col span={6}><Form.Item name="to_warehouse_id" label="目的仓（空=FBA仓）"><WarehouseSelect /></Form.Item></Col>
        <Col span={6}><Form.Item name="platform_shipment_id" label="FBA 货件号"><Input placeholder="FBA15XXXXXX" /></Form.Item></Col>
        <Col span={6}><Form.Item name="destination_fc" label="目的仓库代码"><Input placeholder="ONT8" /></Form.Item></Col>
        <Col span={6}><Form.Item name="logistics_channel_id" label="头程渠道"><ChannelSelect usage="first_mile" /></Form.Item></Col>
        <Col span={6}><Form.Item name="tracking_no" label="物流单号"><Input /></Form.Item></Col>
        <Col span={6}><Form.Item name="eta" label="预计到达"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
      </Row>
      <Form.Item name="lines" label="发货明细（数量为 MSKU 件数，自动换算本地 SKU）">
        <LinesEditor columns={[
          { key: 'listing_id', title: 'MSKU', type: 'listing', required: true, shopId },
          { key: 'sku', title: '配对 SKU', type: 'readonly', width: 140, render: (l) => l._listing?.sku ?? '-' },
          { key: 'qty', title: '数量', type: 'number', width: 120, min: 1, required: true },
        ]} />
      </Form.Item>
      <Divider titlePlacement="start">头程费用（可发货后补录，自动重新分摊）</Divider>
      <Row gutter={12}>
        <Col span={5}><Form.Item name="cost_currency" label="费用币种"><CurrencySelect /></Form.Item></Col>
        <Col span={5}><Form.Item name="freight_cost" label="运费"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
        <Col span={5}><Form.Item name="customs_duty" label="关税"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
        <Col span={4}><Form.Item name="other_cost" label="其他"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
        <Col span={5}><Form.Item name="allocation_method" label="分摊方式"><Select options={dictOptions(ALLOCATION_METHOD)} /></Form.Item></Col>
      </Row>
    </FormModal>
  )
}

function ReceiveModal({ s, onClose, onDone }: { s: R | null; onClose: () => void; onDone: () => void }) {
  const [qty, setQty] = useState<Record<number, number>>({})
  const [loading, setLoading] = useState(false)
  const { message } = App.useApp()
  if (!s) return null
  const submit = async (close: boolean) => {
    setLoading(true)
    try {
      const lines = Object.entries(qty).filter(([, q]) => q > 0).map(([id, q]) => ({ line_id: Number(id), qty_received: q }))
      await api.post(`/fba-shipments/${s.id}/receive`, { lines: lines.length ? lines : null, close })
      message.success('签收完成')
      setQty({})
      onDone()
      onClose()
    } catch (e) {
      message.error(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }
  return (
    <Modal open title={`签收货件 ${s.platform_shipment_id ?? s.shipment_no}`} width={820} onCancel={onClose} destroyOnHidden
      footer={<Space><Button onClick={onClose}>取消</Button><Button loading={loading} onClick={() => submit(false)}>签收（未填写时全部签收）</Button>
        <Button type="primary" loading={loading} onClick={() => submit(true)}>签收并完结</Button></Space>}>
      <Table<R> size="small" rowKey="id" pagination={false} dataSource={s.lines} columns={[
        { title: 'MSKU', dataIndex: 'msku' }, { title: 'SKU', dataIndex: 'sku' },
        { title: '发货', dataIndex: 'qty_shipped' }, { title: '已签收', dataIndex: 'qty_received' },
        { title: '本次签收', render: (_, l) => <InputNumber min={0} max={l.qty_shipped - l.qty_received} placeholder={String(l.qty_shipped - l.qty_received)}
          onChange={(v) => setQty((q) => ({ ...q, [l.id]: v ?? 0 }))} /> },
      ]} />
    </Modal>
  )
}

function Detail({ s, onClose }: { s: R | null; onClose: () => void }) {
  const cur = useBaseCurrency()
  const can = usePerm()
  if (!s) return null
  return (
    <Drawer open onClose={onClose} size={1000} title={`货件 ${s.platform_shipment_id ?? s.shipment_no}`}>
      <Descriptions size="small" bordered column={3}>
        <Descriptions.Item label="系统单号">{s.shipment_no}</Descriptions.Item>
        <Descriptions.Item label="状态"><StatusTag dict={SHIPMENT_STATUS} value={s.status} /></Descriptions.Item>
        <Descriptions.Item label="店铺">{s.shop_name}</Descriptions.Item>
        <Descriptions.Item label="发货仓">{s.ship_from_warehouse_name}</Descriptions.Item>
        <Descriptions.Item label="目的仓">{s.to_warehouse_name} {s.destination_fc}</Descriptions.Item>
        <Descriptions.Item label="渠道">{s.logistics_channel_name ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="物流单号">{s.tracking_no ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="发货日期">{fmtDate(s.ship_date)}</Descriptions.Item>
        <Descriptions.Item label="预计到达">{fmtDate(s.eta)}</Descriptions.Item>
        <Descriptions.Item label="箱数">{s.box_count}</Descriptions.Item>
        <Descriptions.Item label="实重 / 体积">{s.total_weight_kg} kg / {s.total_volume_cbm} m³</Descriptions.Item>
        <Descriptions.Item label="计费重">{s.chargeable_weight_kg} kg</Descriptions.Item>
        <Descriptions.Item label="头程费用">
          {fmtMoney(s.freight_cost + s.customs_duty + s.other_cost, s.cost_currency)}（运费 {s.freight_cost} + 关税 {s.customs_duty} + 其他 {s.other_cost}）
        </Descriptions.Item>
        <Descriptions.Item label="分摊方式">{ALLOCATION_METHOD[s.allocation_method]?.[0]}</Descriptions.Item>
        <Descriptions.Item label="完成时间">{fmtDateTime(s.closed_at)}</Descriptions.Item>
      </Descriptions>
      <Table<R> style={{ marginTop: 16 }} size="small" rowKey="id" pagination={false} dataSource={s.lines} scroll={{ x: 'max-content' }} columns={[
        { title: '商品', render: (_, l) => <ProductCell image={l.image_url} title={l.msku ?? l.sku} sub={`${l.sku} · ${l.fnsku ?? ''}`} size={32} /> },
        { title: '发货', dataIndex: 'qty_shipped' },
        { title: '签收', dataIndex: 'qty_received', render: (v, l) => <span style={{ color: v < l.qty_shipped && s.status === 'closed' ? '#cf1322' : undefined }}>{v}</span> },
        { title: '单品重kg', dataIndex: 'unit_weight_kg' },
        ...(can('product:cost:view') ? [
          { title: '单位采购成本', dataIndex: 'unit_purchase_cost', render: (v: number) => fmtMoney(v, cur, 4) },
          { title: '分摊头程合计', dataIndex: 'allocated_cost', render: (v: number) => fmtMoney(v, cur) },
          { title: '单位头程', dataIndex: 'allocated_unit_cost', render: (v: number) => <Tag color="blue">{fmtMoney(v, cur, 4)}</Tag> },
          { title: '落地成本', key: 'landed', render: (_: unknown, l: R) => <b>{fmtMoney((l.unit_purchase_cost ?? 0) + (l.unit_freight_cost ?? 0) + (l.allocated_unit_cost ?? 0), cur, 4)}</b> },
        ] : []),
      ]} />
    </Drawer>
  )
}

export default function Shipments() {
  const [tab, setTab] = useState('all')
  const [creating, setCreating] = useState(false)
  const [detail, setDetail] = useState<R | null>(null)
  const [receiving, setReceiving] = useState<R | null>(null)
  const [costing, setCosting] = useState<R | null>(null)
  const [editing, setEditing] = useState<R | null>(null)
  const reload = useReload('fba-shipments')
  const run = useAction()
  const act = (s: R, action: string, confirm?: string) => run(() => api.post(`/fba-shipments/${s.id}/${action}`), { confirm, onDone: reload })
  return (
    <>
      <DataTable<R>
        queryKey="fba-shipments"
        url="/fba-shipments"
        extraParams={{ status: tab === 'all' ? undefined : tab }}
        header={<Tabs activeKey={tab} onChange={setTab} items={[{ key: 'all', label: '全部' }, ...Object.entries(SHIPMENT_STATUS).map(([k, [l]]) => ({ key: k, label: l }))]} />}
        filters={[{ name: 'keyword', placeholder: '货件号 / MSKU / 物流单号', width: 240 }, { name: 'shop_id', type: 'custom', render: () => <ShopSelect /> }]}
        toolbar={() => <Perm code="fba:shipment:edit"><Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>新建货件</Button></Perm>}
        columns={[
          { title: '货件', key: 's', render: (_, r) => <div><a onClick={() => setDetail(r)}>{r.platform_shipment_id ?? r.shipment_no}</a><div style={{ fontSize: 12, color: '#888' }}>{r.shipment_no}</div></div> },
          { title: '店铺', dataIndex: 'shop_name' },
          { title: '路线', key: 'route', render: (_, r) => `${r.ship_from_warehouse_name} → ${r.to_warehouse_name}${r.destination_fc ? ` (${r.destination_fc})` : ''}` },
          { title: '状态', dataIndex: 'status', render: (v) => <StatusTag dict={SHIPMENT_STATUS} value={v} /> },
          { title: '数量', key: 'qty', render: (_, r) => `${r.received_qty} / ${r.total_qty}` },
          { title: '计费重kg', dataIndex: 'chargeable_weight_kg', align: 'right' },
          { title: '头程费用', key: 'cost', align: 'right', render: (_, r) => fmtMoney(r.freight_cost + r.customs_duty + r.other_cost, r.cost_currency) },
          { title: '渠道', dataIndex: 'logistics_channel_name', render: (v) => v ?? '-' },
          { title: '发货日期', dataIndex: 'ship_date', render: fmtDate },
          { title: '预计到达', dataIndex: 'eta', render: fmtDate },
          {
            title: '操作', key: 'op', fixed: 'right',
            render: (_, r) => (
              <Perm code="fba:shipment:edit">
                <Space size={4} wrap>
                  {r.status === 'draft' && <a onClick={() => setEditing(r)}>编辑</a>}
                  {r.status === 'draft' && <a onClick={() => act(r, 'ship', '确认发货？将从发货仓扣减库存并转入在途。')}>发货</a>}
                  {['shipped', 'receiving'].includes(r.status) && <a onClick={() => setReceiving(r)}>签收</a>}
                  {r.status !== 'cancelled' && <a onClick={() => setCosting(r)}>费用</a>}
                  {['shipped', 'receiving'].includes(r.status) && <a onClick={() => act(r, 'close', '完结后未签收数量将视为丢失，确定？')}>完结</a>}
                  {r.status === 'draft' && <a style={{ color: '#cf1322' }} onClick={() => act(r, 'cancel', '取消货件？')}>取消</a>}
                </Space>
              </Perm>
            ),
          },
        ]}
      />
      <CreateShipment open={creating} onClose={() => setCreating(false)} onDone={reload} />
      <Detail s={detail} onClose={() => setDetail(null)} />
      <ReceiveModal s={receiving} onClose={() => setReceiving(null)} onDone={reload} />
      <FormModal open={!!costing} title="头程费用（修改后自动重新分摊，并修正目的仓剩余批次成本）" width={560} onCancel={() => setCosting(null)}
        initialValues={costing ?? {}}
        onSubmit={async (v) => { await api.post(`/fba-shipments/${costing!.id}/costs`, v); reload() }}>
        <Row gutter={12}>
          <Col span={12}><Form.Item name="cost_currency" label="币种"><CurrencySelect /></Form.Item></Col>
          <Col span={12}><Form.Item name="allocation_method" label="分摊方式"><Select options={dictOptions(ALLOCATION_METHOD)} /></Form.Item></Col>
          <Col span={8}><Form.Item name="freight_cost" label="运费"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={8}><Form.Item name="customs_duty" label="关税"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={8}><Form.Item name="other_cost" label="其他费用"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
        </Row>
      </FormModal>
      <FormModal open={!!editing} title="编辑货件" width={620} onCancel={() => setEditing(null)}
        initialValues={editing ? { ...editing, ship_date: editing.ship_date ? dayjs(editing.ship_date) : undefined, eta: editing.eta ? dayjs(editing.eta) : undefined } : {}}
        onSubmit={async (v) => { await api.put(`/fba-shipments/${editing!.id}`, { ...v, ship_date: dateStr(v.ship_date), eta: dateStr(v.eta) }); reload() }}>
        <Row gutter={12}>
          <Col span={12}><Form.Item name="platform_shipment_id" label="FBA 货件号"><Input /></Form.Item></Col>
          <Col span={12}><Form.Item name="destination_fc" label="目的仓库代码"><Input /></Form.Item></Col>
          <Col span={12}><Form.Item name="logistics_channel_id" label="头程渠道"><ChannelSelect usage="first_mile" /></Form.Item></Col>
          <Col span={12}><Form.Item name="tracking_no" label="物流单号"><Input /></Form.Item></Col>
          <Col span={12}><Form.Item name="ship_date" label="发货日期"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={12}><Form.Item name="eta" label="预计到达"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={24}><Form.Item name="remark" label="备注"><Input /></Form.Item></Col>
        </Row>
      </FormModal>
    </>
  )
}
