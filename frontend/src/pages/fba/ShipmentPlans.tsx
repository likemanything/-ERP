import { useState } from 'react'
import { Button, Col, DatePicker, Form, Input, Row, Space, Table, Tabs } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import LinesEditor, { type Line } from '@/components/LinesEditor'
import Perm from '@/components/Perm'
import StatusTag from '@/components/StatusTag'
import { ChannelSelect, ShopSelect, WarehouseSelect } from '@/components/selects'
import { PLAN_STATUS } from '@/utils/dicts'
import { fmtDate, fmtDateTime } from '@/utils/format'

type R = Record<string, any>

function PlanForm({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [form] = Form.useForm()
  const shopId = Form.useWatch('shop_id', form)
  return (
    <FormModal open={open} form={form} title="新建发货计划" width={880} onCancel={onClose} initialValues={{ lines: [] }}
      onSubmit={async (v) => {
        const lines = (v.lines as Line[]).filter((l) => l.listing_id && l.qty).map((l) => ({ listing_id: l.listing_id, qty: l.qty }))
        if (!lines.length) throw new Error('请添加发货明细')
        await api.post('/shipment-plans', { ...v, lines, expected_ship_date: v.expected_ship_date ? dayjs(v.expected_ship_date).format('YYYY-MM-DD') : null })
        onDone()
      }}>
      <Row gutter={12}>
        <Col span={8}><Form.Item name="shop_id" label="店铺" rules={[{ required: true }]}><ShopSelect /></Form.Item></Col>
        <Col span={8}><Form.Item name="ship_from_warehouse_id" label="发货仓" rules={[{ required: true }]}><WarehouseSelect excludeFba /></Form.Item></Col>
        <Col span={8}><Form.Item name="to_warehouse_id" label="目的仓（空=店铺 FBA 仓）"><WarehouseSelect /></Form.Item></Col>
        <Col span={8}><Form.Item name="logistics_channel_id" label="头程渠道"><ChannelSelect usage="first_mile" /></Form.Item></Col>
        <Col span={8}><Form.Item name="expected_ship_date" label="预计发货"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
      </Row>
      <Form.Item name="lines" label="发货明细（数量为 MSKU 件数）">
        <LinesEditor columns={[
          { key: 'listing_id', title: 'MSKU', type: 'listing', required: true, shopId },
          { key: 'sku', title: '配对 SKU', type: 'readonly', width: 140, render: (l) => l._listing?.sku ?? '-' },
          { key: 'qty', title: '数量', type: 'number', width: 120, min: 1, required: true },
        ]} />
      </Form.Item>
      <Form.Item name="remark" label="备注"><Input /></Form.Item>
    </FormModal>
  )
}

export default function ShipmentPlans() {
  const [tab, setTab] = useState('pending')
  const [open, setOpen] = useState(false)
  const reload = useReload('shipment-plans')
  const run = useAction()
  const navigate = useNavigate()
  return (
    <>
      <DataTable<R>
        queryKey="shipment-plans"
        url="/shipment-plans"
        rowSelection
        extraParams={{ status: tab === 'all' ? undefined : tab }}
        header={<Tabs activeKey={tab} onChange={setTab} items={[
          { key: 'pending', label: '待处理' }, { key: 'converted', label: '已生成货件' }, { key: 'cancelled', label: '已作废' }, { key: 'all', label: '全部' },
        ]} />}
        filters={[{ name: 'keyword', placeholder: '计划号 / 备注' }, { name: 'shop_id', type: 'custom', render: () => <ShopSelect /> }]}
        toolbar={({ selectedRowKeys, clearSelection }) => (
          <Space>
            <Perm code="fba:plan:edit"><Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>新建发货计划</Button></Perm>
            {tab === 'pending' && (
              <Perm code="fba:plan:edit">
                <Button disabled={!selectedRowKeys.length} onClick={() => run(() => api.post('/shipment-plans/cancel', { ids: selectedRowKeys }), {
                  confirm: '作废选中的发货计划？', success: (r: any) => r.message, onDone: () => { clearSelection(); reload() },
                })}>作废</Button>
              </Perm>
            )}
          </Space>
        )}
        expandable={{ expandedRowRender: (r) => (
          <Table<R> size="small" rowKey="id" pagination={false} dataSource={r.lines} columns={[
            { title: 'MSKU', dataIndex: 'msku' }, { title: 'FNSKU', dataIndex: 'fnsku' }, { title: 'SKU', dataIndex: 'sku' },
            { title: '品名', dataIndex: 'product_name' }, { title: '发货数量', dataIndex: 'qty' },
            { title: '本地可用', dataIndex: 'stock_available', render: (v, l) => <span style={{ color: v < l.qty ? '#cf1322' : undefined }}>{v}</span> },
          ]} />
        ) }}
        columns={[
          { title: '计划号', dataIndex: 'plan_no' },
          { title: '店铺', dataIndex: 'shop_name' },
          { title: '发货仓', dataIndex: 'ship_from_warehouse_name' },
          { title: 'SKU 数', key: 'n', render: (_, r) => r.lines.length },
          { title: '总数量', dataIndex: 'total_qty', align: 'right' },
          { title: '状态', dataIndex: 'status', render: (v) => <StatusTag dict={PLAN_STATUS} value={v} /> },
          { title: '预计发货', dataIndex: 'expected_ship_date', render: fmtDate },
          { title: '备注', dataIndex: 'remark', render: (v) => v ?? '-' },
          { title: '创建时间', dataIndex: 'created_at', render: fmtDateTime },
          {
            title: '操作', key: 'op',
            render: (_, r) => r.status === 'pending' && (
              <Perm code="fba:shipment:edit">
                <a onClick={() => run(() => api.post(`/shipment-plans/${r.id}/to-shipment`), {
                  success: (s: any) => `已生成货件 ${s.shipment_no}`, onDone: () => { reload(); navigate('/fba/shipments') },
                })}>生成货件</a>
              </Perm>
            ),
          },
        ]}
      />
      <PlanForm open={open} onClose={() => setOpen(false)} onDone={reload} />
    </>
  )
}
