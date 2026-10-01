import { useState } from 'react'
import { App, Button, Checkbox, Col, Descriptions, Drawer, Form, Input, InputNumber, Modal, Row, Select, Space, Table, Tabs } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { api, errorMessage } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import LinesEditor, { type Line } from '@/components/LinesEditor'
import Perm from '@/components/Perm'
import StatusTag from '@/components/StatusTag'
import { WarehouseSelect } from '@/components/selects'
import { usePerm } from '@/store/auth'
import { DOC_STATUS, DOC_TYPE, dictOptions } from '@/utils/dicts'
import { fmtDateTime, fmtMoney } from '@/utils/format'

type Doc = Record<string, any>

const BIZ_TYPES: Record<string, { value: string; label: string }[]> = {
  in: [{ value: 'initial', label: '期初入库' }, { value: 'sample', label: '样品入库' }, { value: 'gift', label: '赠品入库' }, { value: 'other', label: '其他' }],
  out: [{ value: 'scrap', label: '报损' }, { value: 'sample', label: '样品领用' }, { value: 'gift', label: '赠品出库' }, { value: 'other', label: '其他' }],
}

function CreateDoc({ docType, open, onClose, onDone }: { docType: string; open: boolean; onClose: () => void; onDone: () => void }) {
  const isStocktake = docType === 'stocktake'
  return (
    <FormModal open={open} width={920} title={`新建${DOC_TYPE[docType]?.[0] ?? ''}单`} onCancel={onClose}
      initialValues={{ stock_type: 'good', lines: [], fill_all: isStocktake, freight_cost: 0 }}
      onSubmit={async (v) => {
        const lines = ((v.lines ?? []) as Line[]).filter((l) => l.product_id).map((l) => ({
          product_id: l.product_id, qty: l.qty ?? 0, unit_cost: l.unit_cost ?? null, counted_qty: l.counted_qty ?? null,
        }))
        await api.post('/stock-documents', { ...v, doc_type: docType, lines })
        onDone()
      }}>
      <Row gutter={16}>
        <Col span={8}><Form.Item name="warehouse_id" label={docType === 'transfer' ? '调出仓' : '仓库'} rules={[{ required: true }]}><WarehouseSelect /></Form.Item></Col>
        {docType === 'transfer' && <Col span={8}><Form.Item name="to_warehouse_id" label="调入仓" rules={[{ required: true }]}><WarehouseSelect /></Form.Item></Col>}
        {BIZ_TYPES[docType] && <Col span={8}><Form.Item name="biz_type" label="业务类型"><Select options={BIZ_TYPES[docType]} allowClear /></Form.Item></Col>}
        {['in', 'out'].includes(docType) && (
          <Col span={8}><Form.Item name="stock_type" label="库存类型"><Select options={[{ value: 'good', label: '良品' }, { value: 'defective', label: '次品' }]} /></Form.Item></Col>
        )}
        {docType === 'transfer' && (
          <>
            <Col span={8}><Form.Item name="freight_cost" label="调拨运费（本位币，分摊入成本）"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="tracking_no" label="物流单号"><Input /></Form.Item></Col>
          </>
        )}
        {isStocktake && (
          <Col span={16}>
            <Form.Item name="fill_all" valuePropName="checked" label=" ">
              <Checkbox>自动带出仓库全部有库存的 SKU（实盘数默认等于账面数，创建后修改差异即可）</Checkbox>
            </Form.Item>
          </Col>
        )}
      </Row>
      <Form.Item name="lines" label={isStocktake ? '盘点明细（勾选自动带出时可留空）' : '明细'}>
        <LinesEditor columns={
          isStocktake
            ? [{ key: 'product_id', title: '产品', type: 'product', excludeBundle: true }, { key: 'counted_qty', title: '实盘数量', type: 'number', width: 140 }]
            : [
                { key: 'product_id', title: '产品', type: 'product', excludeBundle: true, required: true },
                { key: 'qty', title: '数量', type: 'number', width: 120, min: 1, required: true },
                ...(docType === 'in' ? [{ key: 'unit_cost', title: '入库单价（空=参考成本）', type: 'money' as const, width: 180 }] : []),
              ]
        } />
      </Form.Item>
      <Form.Item name="remark" label="备注"><Input /></Form.Item>
    </FormModal>
  )
}

function StocktakeEditor({ doc, onClose, onDone }: { doc: Doc | null; onClose: () => void; onDone: () => void }) {
  const [counts, setCounts] = useState<Record<number, number>>({})
  const [loading, setLoading] = useState(false)
  const { message } = App.useApp()
  if (!doc) return null
  const save = async (approve: boolean) => {
    setLoading(true)
    try {
      const lines = doc.lines.map((l: Doc) => ({ product_id: l.product_id, counted_qty: counts[l.id] ?? l.counted_qty }))
      await api.put(`/stock-documents/${doc.id}`, { lines })
      if (approve) await api.post(`/stock-documents/${doc.id}/approve`)
      message.success(approve ? '盘点已过账' : '已保存')
      setCounts({})
      onDone()
      onClose()
    } catch (e) {
      message.error(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }
  return (
    <Modal open title={`录入盘点结果 ${doc.doc_no}`} width={820} onCancel={onClose} destroyOnHidden
      footer={<Space><Button onClick={onClose}>关闭</Button><Button loading={loading} onClick={() => save(false)}>保存</Button>
        <Perm code="inventory:doc:approve"><Button type="primary" loading={loading} onClick={() => save(true)}>保存并过账</Button></Perm></Space>}>
      <Table<Doc> size="small" rowKey="id" pagination={{ pageSize: 50 }} dataSource={doc.lines} columns={[
        { title: 'SKU', dataIndex: 'sku' }, { title: '品名', dataIndex: 'product_name' },
        { title: '账面数量', dataIndex: 'system_qty' },
        { title: '实盘数量', render: (_, l) => <InputNumber min={0} defaultValue={l.counted_qty} onChange={(v) => setCounts((s) => ({ ...s, [l.id]: v ?? 0 }))} /> },
        { title: '差异', render: (_, l) => {
          const d = (counts[l.id] ?? l.counted_qty ?? 0) - (l.system_qty ?? 0)
          return <span style={{ color: d > 0 ? '#389e0d' : d < 0 ? '#cf1322' : undefined }}>{d > 0 ? `+${d}` : d}</span>
        } },
      ]} />
    </Modal>
  )
}

function DocDetail({ doc, onClose }: { doc: Doc | null; onClose: () => void }) {
  const can = usePerm()
  if (!doc) return null
  return (
    <Drawer open onClose={onClose} size={860} title={`${DOC_TYPE[doc.doc_type]?.[0]} ${doc.doc_no}`}>
      <Descriptions size="small" bordered column={2}>
        <Descriptions.Item label="状态"><StatusTag dict={DOC_STATUS} value={doc.status} /></Descriptions.Item>
        <Descriptions.Item label="库存类型">{doc.stock_type === 'good' ? '良品' : '次品'}</Descriptions.Item>
        <Descriptions.Item label={doc.doc_type === 'transfer' ? '调出仓' : '仓库'}>{doc.warehouse_name}</Descriptions.Item>
        {doc.to_warehouse_name && <Descriptions.Item label="调入仓">{doc.to_warehouse_name}</Descriptions.Item>}
        {doc.doc_type === 'transfer' && <Descriptions.Item label="调拨运费">{fmtMoney(doc.freight_cost)}</Descriptions.Item>}
        <Descriptions.Item label="创建时间">{fmtDateTime(doc.created_at)}</Descriptions.Item>
        <Descriptions.Item label="完成时间">{fmtDateTime(doc.completed_at)}</Descriptions.Item>
        <Descriptions.Item label="备注" span={2}>{doc.remark ?? '-'}</Descriptions.Item>
      </Descriptions>
      <Table<Doc> style={{ marginTop: 16 }} size="small" rowKey="id" pagination={false} dataSource={doc.lines} columns={[
        { title: 'SKU', dataIndex: 'sku' }, { title: '品名', dataIndex: 'product_name' },
        ...(doc.doc_type === 'stocktake'
          ? [{ title: '账面', dataIndex: 'system_qty' }, { title: '实盘', dataIndex: 'counted_qty' }, { title: '差异', dataIndex: 'qty' }]
          : [{ title: '数量', dataIndex: 'qty' }]),
        ...(doc.doc_type === 'transfer' ? [{ title: '实收', dataIndex: 'qty_received' }] : []),
        ...(can('product:cost:view') ? [{ title: '单位成本', dataIndex: 'unit_cost', render: (v: number) => fmtMoney(v, undefined, 4) }] : []),
      ]} />
    </Drawer>
  )
}

export default function StockDocuments() {
  const [tab, setTab] = useState('in')
  const [creating, setCreating] = useState(false)
  const [detail, setDetail] = useState<Doc | null>(null)
  const [counting, setCounting] = useState<Doc | null>(null)
  const reload = useReload('stock-documents')
  const run = useAction()
  const act = (d: Doc, action: string, confirm?: string) => run(() => api.post(`/stock-documents/${d.id}/${action}`, action === 'receive' ? {} : undefined), { confirm, onDone: reload })
  return (
    <>
      <DataTable<Doc>
        queryKey="stock-documents"
        url="/stock-documents"
        extraParams={{ doc_type: tab }}
        header={<Tabs activeKey={tab} onChange={setTab} items={Object.entries(DOC_TYPE).map(([k, [l]]) => ({ key: k, label: `${l}单` }))} />}
        filters={[
          { name: 'keyword', placeholder: '单号 / 备注 / 物流单号' },
          { name: 'warehouse_id', type: 'custom', render: () => <WarehouseSelect /> },
          { name: 'status', type: 'select', label: '状态', options: dictOptions(DOC_STATUS) },
        ]}
        toolbar={() => <Perm code="inventory:doc:edit"><Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>新建{DOC_TYPE[tab][0]}单</Button></Perm>}
        columns={[
          { title: '单号', dataIndex: 'doc_no', render: (v, r) => <a onClick={() => setDetail(r)}>{v}</a> },
          { title: '仓库', dataIndex: 'warehouse_name', render: (v, r) => (r.to_warehouse_name ? `${v} → ${r.to_warehouse_name}` : v) },
          { title: '业务类型', dataIndex: 'biz_type', render: (v) => [...(BIZ_TYPES.in ?? []), ...(BIZ_TYPES.out ?? [])].find((b) => b.value === v)?.label ?? v ?? '-' },
          { title: '库存类型', dataIndex: 'stock_type', render: (v) => (v === 'good' ? '良品' : '次品') },
          { title: 'SKU 数', key: 'n', render: (_, r) => r.lines.length },
          { title: tab === 'stocktake' ? '差异合计' : '数量', dataIndex: 'total_qty', align: 'right' },
          { title: '状态', dataIndex: 'status', render: (v) => <StatusTag dict={DOC_STATUS} value={v} /> },
          { title: '创建时间', dataIndex: 'created_at', render: fmtDateTime },
          {
            title: '操作', key: 'op',
            render: (_, r) => (
              <Space>
                {['draft', 'pending'].includes(r.status) && tab === 'stocktake' && <Perm code="inventory:doc:edit"><a onClick={() => setCounting(r)}>录入盘点</a></Perm>}
                {['draft', 'pending'].includes(r.status) && (
                  <Perm code="inventory:doc:approve">
                    <a onClick={() => act(r, 'approve', tab === 'transfer' ? '审核后将从调出仓出库，货物进入在途，确定？' : '审核后库存将立即变动，确定？')}>审核过账</a>
                  </Perm>
                )}
                {r.status === 'in_transit' && <Perm code="inventory:doc:approve"><a onClick={() => act(r, 'receive', '按调拨数量全部签收入库？')}>签收入库</a></Perm>}
                {['draft', 'pending'].includes(r.status) && <Perm code="inventory:doc:edit"><a onClick={() => act(r, 'cancel', '作废该单据？')}>作废</a></Perm>}
              </Space>
            ),
          },
        ]}
      />
      <CreateDoc docType={tab} open={creating} onClose={() => setCreating(false)} onDone={reload} />
      <DocDetail doc={detail} onClose={() => setDetail(null)} />
      <StocktakeEditor doc={counting} onClose={() => setCounting(null)} onDone={reload} />
    </>
  )
}
