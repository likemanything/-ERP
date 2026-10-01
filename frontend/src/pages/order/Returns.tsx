import { useState } from 'react'
import { Button, Col, Form, Input, InputNumber, Row, Select, Space, Table } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { api, type Page } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import Perm from '@/components/Perm'
import StatusTag from '@/components/StatusTag'
import { ShopSelect, WarehouseSelect } from '@/components/selects'
import { useBaseCurrency, usePerm } from '@/store/auth'
import { RETURN_STATUS, RETURN_TYPE, dictOptions } from '@/utils/dicts'
import { fmtDate, fmtMoney } from '@/utils/format'

type Ret = Record<string, any>

function CreateReturn({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [form] = Form.useForm()
  const [keyword, setKeyword] = useState('')
  const orderId = Form.useWatch('order_id', form)
  const { data: found } = useQuery({
    queryKey: ['return-order-search', keyword],
    queryFn: () => api.get<Page<Ret>>('/orders', { keyword, page_size: 20, status: 'shipped,delivered' }),
    enabled: keyword.length >= 3,
  })
  const order = found?.items.find((o) => o.id === orderId)
  const [lines, setLines] = useState<Record<number, { qty?: number; refund_amount?: number; qty_good?: number; qty_defective?: number }>>({})
  const set = (id: number, patch: object) => setLines((s) => ({ ...s, [id]: { ...s[id], ...patch } }))
  return (
    <FormModal
      open={open}
      form={form}
      title="新建退货 / 退款"
      width={920}
      onCancel={() => { setLines({}); onClose() }}
      initialValues={{ return_type: 'return_refund' }}
      onSubmit={async (v) => {
        if (!order) throw new Error('请选择订单')
        const ls = order.items
          .filter((i: Ret) => lines[i.id]?.qty)
          .map((i: Ret) => ({ order_item_id: i.id, qty: lines[i.id].qty, refund_amount: lines[i.id].refund_amount ?? 0,
            qty_good: lines[i.id].qty_good ?? 0, qty_defective: lines[i.id].qty_defective ?? 0 }))
        if (!ls.length) throw new Error('请填写退货数量')
        await api.post('/returns', { ...v, lines: ls })
        setLines({})
        onDone()
      }}
    >
      <Row gutter={12}>
        <Col span={12}>
          <Form.Item name="order_id" label="原订单（输入订单号搜索）" rules={[{ required: true }]}>
            <Select
              showSearch={{ filterOption: false, onSearch: setKeyword }}
              placeholder="至少输入 3 位订单号"
              options={(found?.items ?? []).map((o) => ({ value: o.id, label: `${o.platform_order_id}（${o.shop_name}）` }))}
            />
          </Form.Item>
        </Col>
        <Col span={6}><Form.Item name="return_type" label="类型"><Select options={dictOptions(RETURN_TYPE)} /></Form.Item></Col>
        <Col span={6}><Form.Item name="warehouse_id" label="退货入库仓"><WarehouseSelect /></Form.Item></Col>
        <Col span={12}><Form.Item name="reason" label="退货原因"><Input /></Form.Item></Col>
        <Col span={12}><Form.Item name="platform_return_id" label="平台退货单号"><Input /></Form.Item></Col>
      </Row>
      {order && (
        <Table<Record<string, any>>
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={order.items}
          columns={[
            { title: 'MSKU', dataIndex: 'msku' },
            { title: 'SKU', dataIndex: 'sku' },
            { title: '购买数', dataIndex: 'quantity' },
            { title: '已退', dataIndex: 'refund_qty' },
            { title: '退货数', render: (_, i) => <InputNumber min={0} max={i.quantity - i.refund_qty} onChange={(v) => set(i.id, { qty: v ?? 0 })} /> },
            { title: `退款(${order.currency})`, render: (_, i) => <InputNumber min={0} onChange={(v) => set(i.id, { refund_amount: v ?? 0 })} /> },
            { title: '良品入库', render: (_, i) => <InputNumber min={0} onChange={(v) => set(i.id, { qty_good: v ?? 0 })} /> },
            { title: '次品入库', render: (_, i) => <InputNumber min={0} onChange={(v) => set(i.id, { qty_defective: v ?? 0 })} /> },
          ]}
        />
      )}
    </FormModal>
  )
}

export default function Returns() {
  const [creating, setCreating] = useState(false)
  const [completing, setCompleting] = useState<Ret | null>(null)
  const reload = useReload('returns')
  const run = useAction()
  const cur = useBaseCurrency()
  const can = usePerm()
  return (
    <>
      <DataTable<Ret>
        queryKey="returns"
        url="/returns"
        filters={[
          { name: 'keyword', placeholder: '退货单号 / 订单号' },
          { name: 'shop_id', type: 'custom', render: () => <ShopSelect /> },
          { name: 'status', type: 'select', label: '状态', options: dictOptions(RETURN_STATUS) },
          { name: 'date', type: 'dateRange', label: '退货日期' },
        ]}
        toolbar={() => (
          <Perm code="return:edit">
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>新建退货</Button>
          </Perm>
        )}
        expandable={{
          expandedRowRender: (r) => (
            <Table size="small" rowKey="id" pagination={false} dataSource={r.lines} columns={[
              { title: 'MSKU', dataIndex: 'msku' }, { title: 'SKU', dataIndex: 'sku' }, { title: '退货数', dataIndex: 'qty' },
              { title: '退款', dataIndex: 'refund_amount', render: (v) => fmtMoney(v, r.currency) },
              { title: '良品入库', dataIndex: 'qty_good' }, { title: '次品入库', dataIndex: 'qty_defective' },
            ]} />
          ),
        }}
        columns={[
          { title: '退货单号', dataIndex: 'return_no' },
          { title: '订单号', dataIndex: 'platform_order_id', render: (v) => v ?? '-' },
          { title: '店铺', dataIndex: 'shop_name' },
          { title: '类型', dataIndex: 'return_type', render: (v) => <StatusTag dict={RETURN_TYPE} value={v} /> },
          { title: '状态', dataIndex: 'status', render: (v) => <StatusTag dict={RETURN_STATUS} value={v} /> },
          { title: '退款金额', dataIndex: 'refund_amount', align: 'right', render: (v, r) => fmtMoney(v, r.currency) },
          ...(can('product:cost:view') ? [{ title: '回库成本', dataIndex: 'restock_cost', align: 'right' as const, render: (v: number) => fmtMoney(v, cur) }] : []),
          { title: '原因', dataIndex: 'reason', render: (v) => v ?? '-' },
          { title: '退货日期', dataIndex: 'return_date', render: fmtDate },
          {
            title: '操作', key: 'op',
            render: (_, r) => r.status === 'pending' && (
              <Perm code="return:edit">
                <Space>
                  <a onClick={() => setCompleting(r)}>完成入库</a>
                  <a onClick={() => run(() => api.post(`/returns/${r.id}/cancel`), { confirm: '取消该退货单？', onDone: reload })}>取消</a>
                </Space>
              </Perm>
            ),
          },
        ]}
      />
      <CreateReturn open={creating} onClose={() => setCreating(false)} onDone={reload} />
      <FormModal
        open={!!completing}
        title={`完成退货 ${completing?.return_no ?? ''}`}
        width={460}
        onCancel={() => setCompleting(null)}
        initialValues={{ warehouse_id: completing?.warehouse_id }}
        onSubmit={async (v) => {
          await api.post(`/returns/${completing!.id}/complete`, v)
          reload()
        }}
      >
        <p style={{ color: '#888' }}>良品按原订单成本回库并冲减销售成本，次品计入次品库存；退款金额计入利润报表。</p>
        <Form.Item name="warehouse_id" label="入库仓库"><WarehouseSelect /></Form.Item>
      </FormModal>
    </>
  )
}
