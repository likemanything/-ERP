import { useState } from 'react'
import { Alert, App, Button, Col, DatePicker, Descriptions, Drawer, Form, Input, InputNumber, Radio, Row, Space, Table, Tabs, Typography } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import LinesEditor, { newKey, type Line } from '@/components/LinesEditor'
import Perm from '@/components/Perm'
import ProductCell from '@/components/ProductCell'
import StatusTag from '@/components/StatusTag'
import { ProductSelect, WarehouseSelect } from '@/components/selects'
import { useBaseCurrency, usePerm } from '@/store/auth'
import { ASSEMBLY_STATUS, ASSEMBLY_TYPE } from '@/utils/dicts'
import { fmtDate, fmtDateTime, fmtMoney } from '@/utils/format'

type A = Record<string, any>

function Detail({ order, onClose }: { order: A | null; onClose: () => void }) {
  const cur = useBaseCurrency()
  const can = usePerm()
  if (!order) return null
  const assemble = order.order_type === 'assemble'
  return (
    <Drawer open onClose={onClose} size={880} title={`${ASSEMBLY_TYPE[order.order_type]?.[0]}单 ${order.order_no}`}>
      <Descriptions size="small" bordered column={3}>
        <Descriptions.Item label="成品"><ProductCell image={order.image_url} title={order.sku} sub={order.product_name} size={32} /></Descriptions.Item>
        <Descriptions.Item label="数量">{order.qty}</Descriptions.Item>
        <Descriptions.Item label="状态"><StatusTag dict={ASSEMBLY_STATUS} value={order.status} /></Descriptions.Item>
        <Descriptions.Item label="仓库">{order.warehouse_name}</Descriptions.Item>
        <Descriptions.Item label="加工费">{fmtMoney(order.processing_fee, cur)}</Descriptions.Item>
        <Descriptions.Item label="计划日期">{fmtDate(order.plan_date)}</Descriptions.Item>
        {can('product:cost:view') && order.status === 'completed' && (
          <>
            <Descriptions.Item label={assemble ? '成品单位成本' : '成品出库单位成本'}><b>{fmtMoney(order.unit_cost, cur, 4)}</b></Descriptions.Item>
            <Descriptions.Item label="总成本">{fmtMoney(order.total_cost, cur)}</Descriptions.Item>
            <Descriptions.Item label="完成时间">{fmtDateTime(order.completed_at)}</Descriptions.Item>
          </>
        )}
        <Descriptions.Item label="备注" span={3}>{order.remark ?? '-'}</Descriptions.Item>
      </Descriptions>
      <Table<A>
        style={{ marginTop: 16 }}
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={order.lines}
        title={() => (assemble ? '耗用子件' : '拆出子件')}
        columns={[
          { title: '子件', key: 'p', render: (_, l) => <ProductCell image={l.image_url} title={l.sku} sub={l.name} size={32} /> },
          { title: '单件用量', dataIndex: 'qty_per_unit', align: 'right' },
          { title: '合计数量', dataIndex: 'qty', align: 'right' },
          ...(order.status === 'draft' ? [{
            title: '可用库存', dataIndex: 'available', align: 'right' as const,
            render: (v: number | null, l: A) => <span style={{ color: assemble && (v ?? 0) < l.qty ? '#cf1322' : undefined }}>{v ?? 0}</span>,
          }] : []),
          ...(can('product:cost:view') && order.status === 'completed' ? [
            { title: '单位成本', dataIndex: 'unit_cost', align: 'right' as const, render: (v: number) => fmtMoney(v, cur, 4) },
            { title: '成本金额', dataIndex: 'amount', align: 'right' as const, render: (v: number) => fmtMoney(v, cur) },
          ] : []),
        ]}
      />
    </Drawer>
  )
}

export default function Assembly() {
  const { message } = App.useApp()
  const [tab, setTab] = useState('draft')
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<A | null>(null)
  const [detail, setDetail] = useState<A | null>(null)
  const [form] = Form.useForm()
  const run = useAction()
  const reload = useReload('assembly')
  const orderType = Form.useWatch('order_type', form) as string | undefined

  const loadRecipe = async (productId?: number) => {
    if (!productId || (form.getFieldValue('lines') as Line[] | undefined)?.some((l) => l.product_id)) return
    const recipe = await api.get<{ product_id: number; qty_per_unit: number }[]>('/assembly-orders/recipe', { product_id: productId })
    if (recipe.length) {
      form.setFieldValue('lines', recipe.map((r) => ({ _key: newKey(), ...r })))
      message.info('已带出该成品上次的加工配方')
    }
  }

  return (
    <>
      <DataTable<A>
        queryKey="assembly"
        url="/assembly-orders"
        extraParams={{ status: tab === 'all' ? undefined : tab }}
        header={<Tabs activeKey={tab} onChange={setTab} items={[
          { key: 'draft', label: '待加工' }, { key: 'completed', label: '已完成' }, { key: 'cancelled', label: '已作废' }, { key: 'all', label: '全部' },
        ]} />}
        filters={[
          { name: 'keyword', placeholder: '单号 / 成品 SKU' },
          { name: 'order_type', type: 'select', label: '类型', options: Object.entries(ASSEMBLY_TYPE).map(([value, [label]]) => ({ value, label })) },
          { name: 'warehouse_id', type: 'custom', render: () => <WarehouseSelect excludeFba /> },
        ]}
        toolbar={() => (
          <Perm code="inventory:assembly">
            <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true) }}>新建加工单</Button>
          </Perm>
        )}
        columns={[
          { title: '单号', dataIndex: 'order_no', render: (v, r) => <a onClick={() => setDetail(r)}>{v}</a> },
          { title: '类型', dataIndex: 'order_type', render: (v) => <StatusTag dict={ASSEMBLY_TYPE} value={v} /> },
          { title: '成品', key: 'p', render: (_, r) => <ProductCell image={r.image_url} title={r.sku} sub={r.product_name} size={32} /> },
          { title: '数量', dataIndex: 'qty', align: 'right' },
          { title: '子件', key: 'lines', render: (_, r) => <span style={{ fontSize: 12 }}>{r.lines.map((l: A) => `${l.sku}×${l.qty_per_unit}`).join('，')}</span> },
          { title: '仓库', dataIndex: 'warehouse_name' },
          { title: '状态', dataIndex: 'status', render: (v) => <StatusTag dict={ASSEMBLY_STATUS} value={v} /> },
          { title: '单位成本', dataIndex: 'unit_cost', align: 'right', render: (v, r) => (r.status === 'completed' && v !== null ? fmtMoney(v, undefined, 4) : '-') },
          { title: '创建时间', dataIndex: 'created_at', render: (v) => fmtDateTime(v) },
          {
            title: '操作', key: 'op', fixed: 'right',
            render: (_, r) => (
              <Space>
                <a onClick={() => setDetail(r)}>详情</a>
                {r.status === 'draft' && (
                  <Perm code="inventory:assembly">
                    <Space>
                      <a onClick={() => { setEditing(r); setOpen(true) }}>编辑</a>
                      <a onClick={() => run(() => api.post(`/assembly-orders/${r.id}/complete`), {
                        confirm: r.order_type === 'assemble' ? `确认完成组装？将扣减子件库存并入库成品 ${r.qty} 件。` : `确认完成拆分？将扣减成品 ${r.qty} 件并入库子件。`,
                        success: '加工完成，库存与成本已结转', onDone: reload,
                      })}>完成加工</a>
                      <a style={{ color: '#cf1322' }} onClick={() => run(() => api.post(`/assembly-orders/${r.id}/cancel`), { confirm: '作废该加工单？', onDone: reload })}>作废</a>
                    </Space>
                  </Perm>
                )}
              </Space>
            ),
          },
        ]}
      />
      <FormModal
        open={open}
        form={form}
        title={editing ? `编辑加工单 ${editing.order_no}` : '新建加工单'}
        width={860}
        onCancel={() => setOpen(false)}
        initialValues={editing ? {
          ...editing, plan_date: editing.plan_date ? dayjs(editing.plan_date) : undefined,
          lines: editing.lines.map((l: A) => ({ _key: newKey(), product_id: l.product_id, qty_per_unit: l.qty_per_unit })),
        } : { order_type: 'assemble', qty: 1, processing_fee: 0, lines: [] }}
        onSubmit={async (v) => {
          const lines = (v.lines as Line[]).filter((l) => l.product_id).map((l) => ({ product_id: l.product_id, qty_per_unit: l.qty_per_unit || 1 }))
          const body = { ...v, lines, plan_date: v.plan_date ? dayjs(v.plan_date).format('YYYY-MM-DD') : null }
          if (editing) await api.put(`/assembly-orders/${editing.id}`, body)
          else await api.post('/assembly-orders', body)
          reload()
        }}
      >
        <Alert type="info" showIcon style={{ marginBottom: 16 }}
          title={orderType === 'disassemble'
            ? '拆分：按 FIFO 扣减成品，成品成本 + 加工费按子件参考采购成本比例分摊到子件入库。'
            : '组装：按 FIFO 扣减子件（含头程等物流成本），成品入库成本 = (子件成本 + 加工费) ÷ 成品数量。'} />
        <Row gutter={16}>
          <Col span={8}>
            <Form.Item name="order_type" label="加工类型">
              <Radio.Group optionType="button" options={[{ value: 'assemble', label: '组装' }, { value: 'disassemble', label: '拆分' }]} />
            </Form.Item>
          </Col>
          <Col span={8}><Form.Item name="warehouse_id" label="仓库" rules={[{ required: true }]}><WarehouseSelect excludeFba /></Form.Item></Col>
          <Col span={8}><Form.Item name="plan_date" label="计划日期"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={12}><Form.Item name="product_id" label="成品" rules={[{ required: true }]}><ProductSelect excludeBundle onChange={(v) => void loadRecipe(v as number)} /></Form.Item></Col>
          <Col span={6}><Form.Item name="qty" label="成品数量" rules={[{ required: true }]}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={6}><Form.Item name="processing_fee" label="加工费合计（本位币）"><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item></Col>
        </Row>
        <Form.Item name="lines" label={<Space>子件配方 <Typography.Text type="secondary" style={{ fontSize: 12 }}>（每件成品的用量）</Typography.Text></Space>}
          rules={[{ validator: (_, v: Line[]) => (v?.some((l) => l.product_id) ? Promise.resolve() : Promise.reject(new Error('请添加子件'))) }]}>
          <LinesEditor
            addText="添加子件"
            columns={[
              { key: 'product_id', title: '子件', type: 'product', required: true, excludeBundle: true },
              { key: 'qty_per_unit', title: '单件用量', type: 'number', width: 140, min: 1 },
            ]}
          />
        </Form.Item>
        <Form.Item name="remark" label="备注"><Input /></Form.Item>
      </FormModal>
      <Detail order={detail} onClose={() => setDetail(null)} />
    </>
  )
}
