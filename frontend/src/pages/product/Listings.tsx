import { useState } from 'react'
import { Button, Checkbox, Col, Form, Input, InputNumber, Row, Select, Space, Tag } from 'antd'
import { LinkOutlined, PlusOutlined, ThunderboltOutlined, UploadOutlined } from '@ant-design/icons'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, ImportModal, useAction } from '@/components/common'
import Perm from '@/components/Perm'
import ProductCell from '@/components/ProductCell'
import StatusTag from '@/components/StatusTag'
import { ProductSelect, ShopSelect, UserSelect } from '@/components/selects'
import { FULFILLMENT, LISTING_STATUS, dictOptions } from '@/utils/dicts'
import { fmtMoney } from '@/utils/format'

type Listing = Record<string, any>

export default function Listings() {
  const [pairing, setPairing] = useState<Listing | null>(null)
  const [creating, setCreating] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const reload = useReload('listings')
  const run = useAction()

  return (
    <>
      <DataTable<Listing>
        queryKey="listings"
        url="/listings"
        exportUrl="/listings/export"
        filters={[
          { name: 'keyword', placeholder: 'MSKU / ASIN / FNSKU / 标题' },
          { name: 'shop_id', type: 'custom', render: () => <ShopSelect /> },
          { name: 'fulfillment', type: 'select', label: '配送', options: dictOptions(FULFILLMENT) },
          { name: 'status', type: 'select', label: '状态', options: dictOptions(LISTING_STATUS) },
          { name: 'paired', type: 'select', label: '配对', options: [{ label: '已配对', value: true }, { label: '未配对', value: false }] },
        ]}
        toolbar={() => (
          <Perm code="listing:edit">
            <Space>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>手工添加</Button>
              <Button icon={<ThunderboltOutlined />} onClick={() => run(() => api.post('/listings/auto-pair'), { success: (r: any) => r.message, onDone: reload })}>
                自动配对
              </Button>
              <Button icon={<UploadOutlined />} onClick={() => setImportOpen(true)}>批量配对</Button>
              <Button onClick={() => run(() => api.post('/orders/resettle-cost'), { success: (r: any) => r.message })}>重算订单成本</Button>
            </Space>
          </Perm>
        )}
        columns={[
          {
            title: 'Listing', key: 'listing', fixed: 'left',
            render: (_, r) => <ProductCell image={r.image_url} title={r.msku} sub={r.title} extra={`${r.asin ?? '-'} · ${r.fnsku ?? '-'}`} />,
          },
          { title: '店铺', dataIndex: 'shop_name' },
          { title: '配送', dataIndex: 'fulfillment', render: (v) => <StatusTag dict={FULFILLMENT} value={v} /> },
          { title: '状态', dataIndex: 'status', render: (v) => <StatusTag dict={LISTING_STATUS} value={v} /> },
          { title: '售价', dataIndex: 'price', align: 'right', render: (v, r) => fmtMoney(v, r.currency) },
          {
            title: '配对 SKU', dataIndex: 'sku',
            render: (v, r) => (v ? (
              <Space orientation="vertical" size={0}>
                <span><Tag color="green">{v}</Tag>{r.pair_quantity > 1 && <Tag>×{r.pair_quantity}</Tag>}</span>
                <span style={{ fontSize: 12, color: '#888' }}>{r.product_name}</span>
              </Space>
            ) : <Tag color="orange">未配对</Tag>),
          },
          { title: '开售日期', dataIndex: 'open_date', render: (v) => v ?? '-' },
          {
            title: '操作', key: 'op', fixed: 'right',
            render: (_, r) => (
              <Perm code="listing:edit">
                <Space>
                  <a onClick={() => setPairing(r)}><LinkOutlined /> 配对</a>
                  <a style={{ color: '#ff4d4f' }} onClick={() => run(() => api.del(`/listings/${r.id}`), { confirm: `删除 ${r.msku}？`, onDone: reload })}>删除</a>
                </Space>
              </Perm>
            ),
          },
        ]}
      />
      <FormModal
        open={!!pairing}
        title={`配对 ${pairing?.msku ?? ''}`}
        width={520}
        onCancel={() => setPairing(null)}
        initialValues={{ product_id: pairing?.product_id, pair_quantity: pairing?.pair_quantity ?? 1, apply_to_history: true }}
        onSubmit={async (v) => {
          await api.post(`/listings/${pairing!.id}/pair`, v)
          reload()
        }}
      >
        <Form.Item name="product_id" label="本地 SKU（为空表示解除配对）"><ProductSelect /></Form.Item>
        <Form.Item name="pair_quantity" label="配对数量（1 个 MSKU = N 个 SKU，多件装填写件数）"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="apply_to_history" valuePropName="checked"><Checkbox>同步更新历史订单的 SKU</Checkbox></Form.Item>
      </FormModal>
      <FormModal
        open={creating}
        title="手工添加 Listing"
        onCancel={() => setCreating(false)}
        initialValues={{ fulfillment: 'FBA', status: 'active', pair_quantity: 1 }}
        onSubmit={async (v) => {
          await api.post('/listings', v)
          reload()
        }}
      >
        <Row gutter={12}>
          <Col span={12}><Form.Item name="shop_id" label="店铺" rules={[{ required: true }]}><ShopSelect /></Form.Item></Col>
          <Col span={12}><Form.Item name="msku" label="MSKU" rules={[{ required: true }]}><Input /></Form.Item></Col>
          <Col span={12}><Form.Item name="asin" label="ASIN / 平台商品ID"><Input /></Form.Item></Col>
          <Col span={12}><Form.Item name="fnsku" label="FNSKU"><Input /></Form.Item></Col>
          <Col span={24}><Form.Item name="title" label="标题"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="price" label="售价"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={8}><Form.Item name="fulfillment" label="配送方式"><Select options={dictOptions(FULFILLMENT)} /></Form.Item></Col>
          <Col span={8}><Form.Item name="status" label="状态"><Select options={dictOptions(LISTING_STATUS)} /></Form.Item></Col>
          <Col span={16}><Form.Item name="product_id" label="配对 SKU"><ProductSelect /></Form.Item></Col>
          <Col span={8}><Form.Item name="pair_quantity" label="配对数量"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={12}><Form.Item name="principal_id" label="负责人"><UserSelect /></Form.Item></Col>
        </Row>
      </FormModal>
      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} title="批量配对（店铺 + MSKU → SKU）"
        uploadUrl="/listings/import-pair" templateUrl="/listings/pair-template" onDone={reload} />
    </>
  )
}
