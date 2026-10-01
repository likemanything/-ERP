import { useState } from 'react'
import { App, Button, Col, DatePicker, Descriptions, Divider, Drawer, Form, Input, InputNumber, Modal, Row, Space, Table, Tabs, Tag } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { api, errorMessage, type Page } from '@/api/client'
import DataTable from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import LinesEditor, { newKey, type Line } from '@/components/LinesEditor'
import ApprovalTimeline from '@/components/ApprovalTimeline'
import Perm from '@/components/Perm'
import ProductCell from '@/components/ProductCell'
import StatusTag from '@/components/StatusTag'
import { CurrencySelect, SupplierSelect, UserSelect, WarehouseSelect } from '@/components/selects'
import { usePerm } from '@/store/auth'
import { PAYMENT_STATUS, PO_STATUS } from '@/utils/dicts'
import { fmtDate, fmtDateTime, fmtMoney } from '@/utils/format'

type PO = Record<string, any>

function POForm({ open, po, onClose, onSaved }: { open: boolean; po: PO | null; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const { message } = App.useApp()
  const lines: Line[] = Form.useWatch('lines', form) ?? []
  const fees = Form.useWatch(['shipping_fee'], form) ?? 0
  const other = Form.useWatch(['other_fee'], form) ?? 0
  const discount = Form.useWatch(['discount'], form) ?? 0
  const currency = Form.useWatch('currency', form)
  const goods = lines.reduce((s, l) => s + (l.qty || 0) * (l.unit_price || 0), 0)
  const save = async () => {
    const v = await form.validateFields()
    const body = {
      ...v,
      expected_date: v.expected_date ? dayjs(v.expected_date).format('YYYY-MM-DD') : null,
      lines: (v.lines as Line[]).filter((l) => l.product_id).map((l) => ({
        product_id: l.product_id, qty: l.qty, unit_price: l.unit_price ?? null, remark: l.remark,
      })),
    }
    setSaving(true)
    try {
      if (po) await api.put(`/purchase-orders/${po.id}`, body)
      else await api.post('/purchase-orders', body)
      message.success('已保存')
      onSaved()
      onClose()
    } catch (e) {
      message.error(errorMessage(e))
    } finally {
      setSaving(false)
    }
  }
  const initial = po
    ? { ...po, expected_date: po.expected_date ? dayjs(po.expected_date) : undefined, lines: po.lines.map((l: PO) => ({ ...l, _key: newKey() })) }
    : { shipping_fee: 0, other_fee: 0, discount: 0, lines: [{ _key: newKey() }] }
  return (
    <Drawer open={open} onClose={onClose} size={1000} title={po ? `编辑采购单 ${po.po_no}` : '新建采购单'} destroyOnHidden
      extra={<Button type="primary" loading={saving} onClick={save}>保存草稿</Button>}>
      <Form form={form} layout="vertical" initialValues={initial} preserve={false}>
        <Row gutter={16}>
          <Col span={8}><Form.Item name="supplier_id" label="供应商" rules={[{ required: true }]}><SupplierSelect /></Form.Item></Col>
          <Col span={8}><Form.Item name="warehouse_id" label="收货仓" rules={[{ required: true }]}><WarehouseSelect excludeFba /></Form.Item></Col>
          <Col span={8}><Form.Item name="currency" label="币种（默认供应商币种）"><CurrencySelect /></Form.Item></Col>
          <Col span={8}><Form.Item name="purchaser_id" label="采购员"><UserSelect /></Form.Item></Col>
          <Col span={8}><Form.Item name="expected_date" label="预计到货"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={8}><Form.Item name="supplier_order_no" label="供应商单号 / 1688 单号"><Input /></Form.Item></Col>
        </Row>
        <Form.Item name="lines" label="采购明细（单价为空时取供应商报价）" rules={[{ validator: (_, v: Line[]) => (v?.some((l) => l.product_id && l.qty) ? Promise.resolve() : Promise.reject(new Error('请添加明细'))) }]}>
          <LinesEditor columns={[
            { key: 'product_id', title: '产品', type: 'product', required: true, excludeBundle: true },
            { key: 'qty', title: '数量', type: 'number', width: 110, min: 1, required: true },
            { key: 'unit_price', title: '含税单价', type: 'money', width: 140 },
            { key: 'amount', title: '金额', type: 'readonly', width: 120, render: (l) => fmtMoney((l.qty || 0) * (l.unit_price || 0), currency) },
            { key: 'remark', title: '备注', type: 'text', width: 160 },
          ]} />
        </Form.Item>
        <Row gutter={16}>
          <Col span={6}><Form.Item name="shipping_fee" label="运费（分摊入成本）"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={6}><Form.Item name="other_fee" label="其他费用"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={6}><Form.Item name="discount" label="优惠"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={6}>
            <Form.Item label="单据总额">
              <b style={{ fontSize: 18 }}>{fmtMoney(goods + Number(fees) + Number(other) - Number(discount), currency)}</b>
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="remark" label="备注"><Input.TextArea rows={2} /></Form.Item>
      </Form>
    </Drawer>
  )
}

function ReceiveModal({ po, onClose, onDone }: { po: PO | null; onClose: () => void; onDone: () => void }) {
  const [qty, setQty] = useState<Record<number, { good?: number; bad?: number }>>({})
  const [tracking, setTracking] = useState('')
  const [loading, setLoading] = useState(false)
  const { message } = App.useApp()
  if (!po) return null
  const pending = po.lines.filter((l: PO) => l.qty_pending > 0)
  const submit = async () => {
    const lines = pending
      .map((l: PO) => ({ order_line_id: l.id, qty_good: qty[l.id]?.good ?? 0, qty_defective: qty[l.id]?.bad ?? 0 }))
      .filter((l: PO) => l.qty_good + l.qty_defective > 0)
    if (!lines.length) return message.warning('请填写到货数量')
    setLoading(true)
    try {
      const r = await api.post(`/purchase-orders/${po.id}/receive`, { lines, tracking_no: tracking || undefined })
      message.success(`已入库，入库单 ${r.receipt_no}`)
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
    <Modal open title={`到货质检入库 - ${po.po_no}`} width={860} onCancel={onClose} onOk={submit} confirmLoading={loading} okText="确认入库" destroyOnHidden>
      <Space style={{ marginBottom: 12 }}>
        <Button size="small" onClick={() => setQty(Object.fromEntries(pending.map((l: PO) => [l.id, { good: l.qty_pending, bad: 0 }])))}>全部按未到货数量填充</Button>
        <Input size="small" placeholder="物流单号（可选）" value={tracking} onChange={(e) => setTracking(e.target.value)} style={{ width: 220 }} />
      </Space>
      <Table<PO>
        size="small" rowKey="id" pagination={false} dataSource={pending}
        columns={[
          { title: '产品', render: (_, l) => <ProductCell image={l.image_url} title={l.sku} sub={l.product_name} size={32} /> },
          { title: '采购数', dataIndex: 'qty' },
          { title: '已到货', dataIndex: 'qty_received' },
          { title: '未到货', dataIndex: 'qty_pending' },
          { title: '良品数', render: (_, l) => <InputNumber min={0} max={l.qty_pending} value={qty[l.id]?.good} onChange={(v) => setQty((s) => ({ ...s, [l.id]: { ...s[l.id], good: v ?? 0 } }))} /> },
          { title: '次品数', render: (_, l) => <InputNumber min={0} max={l.qty_pending} value={qty[l.id]?.bad} onChange={(v) => setQty((s) => ({ ...s, [l.id]: { ...s[l.id], bad: v ?? 0 } }))} /> },
        ]}
      />
    </Modal>
  )
}

function PODetail({ po, onClose }: { po: PO | null; onClose: () => void }) {
  const { data: receipts } = useQuery({
    queryKey: ['po-receipts', po?.id],
    queryFn: () => api.get<Page<PO>>('/purchase-receipts', { order_id: po!.id, page_size: 100 }),
    enabled: !!po,
  })
  const can = usePerm()
  if (!po) return null
  return (
    <Drawer open onClose={onClose} size={1000} title={`采购单 ${po.po_no}`}>
      <Descriptions size="small" bordered column={3}>
        <Descriptions.Item label="供应商">{po.supplier_name}</Descriptions.Item>
        <Descriptions.Item label="收货仓">{po.warehouse_name}</Descriptions.Item>
        <Descriptions.Item label="状态"><Space><StatusTag dict={PO_STATUS} value={po.status} /><StatusTag dict={PAYMENT_STATUS} value={po.payment_status} /></Space></Descriptions.Item>
        <Descriptions.Item label="币种 / 汇率">{po.currency} / {po.exchange_rate}</Descriptions.Item>
        <Descriptions.Item label="货款">{fmtMoney(po.goods_amount, po.currency)}</Descriptions.Item>
        <Descriptions.Item label="运费+其他-优惠">{fmtMoney(po.shipping_fee + po.other_fee - po.discount, po.currency)}</Descriptions.Item>
        <Descriptions.Item label="单据总额"><b>{fmtMoney(po.total_amount, po.currency)}</b></Descriptions.Item>
        <Descriptions.Item label="已付款">{fmtMoney(po.paid_amount, po.currency)}</Descriptions.Item>
        <Descriptions.Item label="退货金额">{fmtMoney(po.returned_amount, po.currency)}</Descriptions.Item>
        <Descriptions.Item label="供应商单号">{po.supplier_order_no ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="预计到货">{fmtDate(po.expected_date)}</Descriptions.Item>
        <Descriptions.Item label="创建时间">{fmtDateTime(po.created_at)}</Descriptions.Item>
        {po.reject_reason && <Descriptions.Item label="驳回原因" span={3}><span style={{ color: '#cf1322' }}>{po.reject_reason}</span></Descriptions.Item>}
        <Descriptions.Item label="备注" span={3}>{po.remark ?? '-'}</Descriptions.Item>
      </Descriptions>
      <ApprovalTimeline docType="purchase_order" docId={po.id} />
      <Divider titlePlacement="start">采购明细</Divider>
      <Table<PO> size="small" rowKey="id" pagination={false} dataSource={po.lines} columns={[
        { title: '产品', render: (_, l) => <ProductCell image={l.image_url} title={l.sku} sub={l.product_name} size={32} /> },
        { title: '数量', dataIndex: 'qty' },
        { title: '单价', dataIndex: 'unit_price', render: (v) => fmtMoney(v, po.currency, 4) },
        { title: '金额', dataIndex: 'amount', render: (v) => fmtMoney(v, po.currency) },
        { title: '已到货', dataIndex: 'qty_received' },
        { title: '良品/次品', render: (_, l) => `${l.qty_good} / ${l.qty_defective}` },
        { title: '已退货', dataIndex: 'qty_returned' },
        { title: '未到货', dataIndex: 'qty_pending', render: (v) => (v > 0 ? <Tag color="orange">{v}</Tag> : 0) },
      ]} />
      <Divider titlePlacement="start">入库记录</Divider>
      <Table<PO> size="small" rowKey="id" pagination={false} dataSource={receipts?.items ?? []}
        expandable={{ expandedRowRender: (r) => (
          <Table<PO> size="small" rowKey="id" pagination={false} dataSource={r.lines} columns={[
            { title: 'SKU', dataIndex: 'sku' }, { title: '良品', dataIndex: 'qty_good' }, { title: '次品', dataIndex: 'qty_defective' },
            ...(can('product:cost:view') ? [
              { title: '单位采购成本', dataIndex: 'unit_purchase_cost', render: (v: number) => fmtMoney(v, undefined, 4) },
              { title: '单位运杂费', dataIndex: 'unit_freight_cost', render: (v: number) => fmtMoney(v, undefined, 4) },
            ] : []),
          ]} />
        ) }}
        columns={[
          { title: '入库单号', dataIndex: 'receipt_no' },
          { title: '入库时间', dataIndex: 'received_at', render: fmtDateTime },
          { title: '件数', render: (_, r) => r.lines.reduce((s: number, l: PO) => s + l.qty_good + l.qty_defective, 0) },
          { title: '物流单号', dataIndex: 'tracking_no', render: (v) => v ?? '-' },
        ]}
      />
    </Drawer>
  )
}

const TABS = ['all', 'draft', 'pending_approval', 'approved', 'ordered', 'partial', 'received', 'rejected', 'closed', 'cancelled']

export default function PurchaseOrders() {
  const [tab, setTab] = useState('all')
  const [form, setForm] = useState<{ open: boolean; po: PO | null }>({ open: false, po: null })
  const [detail, setDetail] = useState<PO | null>(null)
  const [receiving, setReceiving] = useState<PO | null>(null)
  const [rejecting, setRejecting] = useState<PO | null>(null)
  const [ordering, setOrdering] = useState<PO | null>(null)
  const qc = useQueryClient()
  const reload = () => qc.invalidateQueries({ queryKey: ['purchase-orders'] })
  const run = useAction()
  const { data: counts } = useQuery({ queryKey: ['purchase-orders', 'counts'], queryFn: () => api.get<Record<string, number>>('/purchase-orders/status-counts') })

  const act = (po: PO, action: string, label: string, confirm?: string) =>
    run(() => api.post(`/purchase-orders/${po.id}/${action}`), { success: `${label}成功`, confirm, onDone: reload })

  const actions = (po: PO) => {
    const s = po.status
    return (
      <Space wrap size={4}>
        <a onClick={() => setDetail(po)}>详情</a>
        {['draft', 'rejected'].includes(s) && (
          <Perm code="purchase:order:edit">
            <a onClick={() => setForm({ open: true, po })}>编辑</a>
            <a onClick={() => act(po, 'submit', '提交')}>提交</a>
          </Perm>
        )}
        {s === 'pending_approval' && (
          <Perm code="purchase:order:approve">
            <a onClick={() => act(po, 'approve', '审批')}>通过</a>
            <a style={{ color: '#cf1322' }} onClick={() => setRejecting(po)}>驳回</a>
          </Perm>
        )}
        {s === 'approved' && <Perm code="purchase:order:edit"><a onClick={() => setOrdering(po)}>确认下单</a></Perm>}
        {['approved', 'ordered', 'partial'].includes(s) && <Perm code="purchase:receive"><a onClick={() => setReceiving(po)}>到货入库</a></Perm>}
        {['ordered', 'partial'].includes(s) && po.received_qty > 0 && (
          <Perm code="purchase:order:edit"><a onClick={() => act(po, 'close', '结单', '结单后剩余未到货数量将不再收货，确定？')}>结单</a></Perm>
        )}
        {['draft', 'rejected', 'pending_approval', 'approved', 'ordered'].includes(s) && po.received_qty === 0 && (
          <Perm code="purchase:order:edit"><a style={{ color: '#cf1322' }} onClick={() => act(po, 'cancel', '作废', `作废采购单 ${po.po_no}？`)}>作废</a></Perm>
        )}
        {['draft', 'cancelled'].includes(s) && (
          <Perm code="purchase:order:edit">
            <a style={{ color: '#cf1322' }} onClick={() => run(() => api.del(`/purchase-orders/${po.id}`), { confirm: `删除采购单 ${po.po_no}？`, onDone: reload })}>删除</a>
          </Perm>
        )}
      </Space>
    )
  }

  return (
    <>
      <DataTable<PO>
        queryKey="purchase-orders"
        url="/purchase-orders"
        exportUrl="/purchase-orders/export"
        extraParams={{ status: tab === 'all' ? undefined : tab }}
        header={<Tabs activeKey={tab} onChange={setTab} items={TABS.map((k) => ({
          key: k, label: k === 'all' ? '全部' : `${PO_STATUS[k][0]}${counts?.[k] ? ` (${counts[k]})` : ''}`,
        }))} />}
        filters={[
          { name: 'keyword', placeholder: '采购单号 / SKU / 供应商单号', width: 240 },
          { name: 'supplier_id', type: 'custom', render: () => <SupplierSelect /> },
          { name: 'date', type: 'dateRange', label: '创建日期' },
        ]}
        toolbar={() => (
          <Perm code="purchase:order:edit">
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setForm({ open: true, po: null })}>新建采购单</Button>
          </Perm>
        )}
        columns={[
          { title: '采购单号', dataIndex: 'po_no', fixed: 'left', render: (v, r) => <a onClick={() => setDetail(r)}>{v}</a> },
          { title: '供应商', dataIndex: 'supplier_name' },
          { title: '状态', dataIndex: 'status', render: (v) => <StatusTag dict={PO_STATUS} value={v} /> },
          {
            title: '产品', key: 'lines',
            render: (_, r) => (
              <span>{r.lines.slice(0, 2).map((l: PO) => `${l.sku}×${l.qty}`).join('，')}{r.lines.length > 2 ? ` 等${r.lines.length}项` : ''}</span>
            ),
          },
          { title: '到货进度', key: 'progress', render: (_, r) => `${r.received_qty} / ${r.total_qty}` },
          { title: '总额', dataIndex: 'total_amount', align: 'right', render: (v, r) => fmtMoney(v, r.currency) },
          { title: '付款', dataIndex: 'payment_status', render: (v, r) => <Space orientation="vertical" size={0}><StatusTag dict={PAYMENT_STATUS} value={v} /><span style={{ fontSize: 12, color: '#888' }}>{fmtMoney(r.paid_amount, r.currency)}</span></Space> },
          { title: '收货仓', dataIndex: 'warehouse_name' },
          { title: '预计到货', dataIndex: 'expected_date', render: fmtDate },
          { title: '创建时间', dataIndex: 'created_at', render: fmtDateTime },
          { title: '操作', key: 'op', fixed: 'right', width: 220, render: (_, r) => actions(r) },
        ]}
      />
      <POForm open={form.open} po={form.po} onClose={() => setForm({ open: false, po: null })} onSaved={reload} />
      <PODetail po={detail} onClose={() => setDetail(null)} />
      <ReceiveModal po={receiving} onClose={() => setReceiving(null)} onDone={reload} />
      <FormModal open={!!rejecting} title={`驳回 ${rejecting?.po_no ?? ''}`} width={460} onCancel={() => setRejecting(null)}
        onSubmit={async (v) => { await api.post(`/purchase-orders/${rejecting!.id}/reject`, v); reload() }}>
        <Form.Item name="reason" label="驳回原因" rules={[{ required: true }]}><Input.TextArea rows={3} /></Form.Item>
      </FormModal>
      <FormModal open={!!ordering} title={`确认下单 ${ordering?.po_no ?? ''}`} width={460} onCancel={() => setOrdering(null)}
        initialValues={{ supplier_order_no: ordering?.supplier_order_no }}
        onSubmit={async (v) => {
          await api.post(`/purchase-orders/${ordering!.id}/ordered`, {
            ...v, expected_date: v.expected_date ? dayjs(v.expected_date).format('YYYY-MM-DD') : undefined,
          })
          reload()
        }}>
        <Form.Item name="supplier_order_no" label="供应商单号 / 1688 订单号"><Input /></Form.Item>
        <Form.Item name="expected_date" label="预计到货日期"><DatePicker style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="tracking_no" label="物流单号"><Input /></Form.Item>
      </FormModal>
    </>
  )
}
