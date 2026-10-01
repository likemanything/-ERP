import { useState } from 'react'
import { App, Button, Col, Divider, Drawer, Form, Input, InputNumber, Row, Select, Space, Switch, Table, Tabs, Tag } from 'antd'
import { PlusOutlined, PrinterOutlined, UploadOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, errorMessage } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, ImportModal, useAction } from '@/components/common'
import LinesEditor, { newKey, type Line } from '@/components/LinesEditor'
import Perm from '@/components/Perm'
import PrintLabelsModal, { type LabelLine } from '@/components/PrintLabels'
import ProductCell from '@/components/ProductCell'
import StatusTag from '@/components/StatusTag'
import { BrandSelect, CategorySelect, CurrencySelect, SupplierSelect, UserSelect } from '@/components/selects'
import { useBaseCurrency, usePerm } from '@/store/auth'
import { PRODUCT_STATUS, PRODUCT_TYPE, dictOptions } from '@/utils/dicts'
import { fmtMoney } from '@/utils/format'

type Product = Record<string, any>

function SupplierQuotes({ productId }: { productId: number }) {
  const { data, refetch } = useQuery({
    queryKey: ['product-quotes', productId],
    queryFn: () => api.get<Product[]>(`/products/${productId}/suppliers`),
  })
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<Product | null>(null)
  const run = useAction()
  return (
    <>
      <Perm code="product:edit">
        <Button size="small" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true) }} style={{ marginBottom: 8 }}>
          添加报价
        </Button>
      </Perm>
      <Table
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={data ?? []}
        columns={[
          { title: '供应商', dataIndex: 'supplier_name', render: (v, r) => <Space>{v}{r.is_default && <Tag color="blue">默认</Tag>}</Space> },
          { title: '单价', dataIndex: 'price', render: (v, r) => fmtMoney(v, r.currency, 4) },
          { title: '起订量', dataIndex: 'moq' },
          { title: '交期(天)', dataIndex: 'lead_days' },
          { title: '采购链接', dataIndex: 'purchase_url', render: (v) => (v ? <a href={v} target="_blank" rel="noreferrer">打开</a> : '-') },
          {
            title: '操作', key: 'op',
            render: (_, r) => (
              <Perm code="product:edit">
                <Space>
                  <a onClick={() => { setEditing(r); setOpen(true) }}>编辑</a>
                  <a onClick={() => run(() => api.del(`/products/${productId}/suppliers/${r.id}`), { confirm: '删除该报价？', onDone: () => refetch() })}>删除</a>
                </Space>
              </Perm>
            ),
          },
        ]}
      />
      <FormModal
        open={open}
        title={editing ? '编辑报价' : '添加报价'}
        width={520}
        onCancel={() => setOpen(false)}
        initialValues={editing ?? { currency: 'CNY', moq: 1, lead_days: 15, is_default: !data?.length }}
        onSubmit={async (v) => {
          if (editing) await api.put(`/products/${productId}/suppliers/${editing.id}`, v)
          else await api.post(`/products/${productId}/suppliers`, v)
          refetch()
        }}
      >
        <Form.Item name="supplier_id" label="供应商" rules={[{ required: true }]}><SupplierSelect /></Form.Item>
        <Row gutter={12}>
          <Col span={12}><Form.Item name="price" label="含税单价" rules={[{ required: true }]}><InputNumber min={0} precision={4} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={12}><Form.Item name="currency" label="币种"><CurrencySelect /></Form.Item></Col>
          <Col span={12}><Form.Item name="moq" label="起订量"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={12}><Form.Item name="lead_days" label="交期（天）"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
        </Row>
        <Form.Item name="purchase_url" label="采购链接"><Input /></Form.Item>
        <Form.Item name="is_default" label="设为默认供应商" valuePropName="checked"><Switch /></Form.Item>
      </FormModal>
    </>
  )
}

function ProductDrawer({ open, product, onClose, onSaved }: { open: boolean; product: Product | null; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const { message } = App.useApp()
  const can = usePerm()
  const type = Form.useWatch('product_type', form)
  const save = async () => {
    const v = await form.validateFields()
    const body = {
      ...v,
      bundle_items: v.product_type === 'bundle'
        ? (v.bundle_items ?? []).filter((l: Line) => l.component_id).map((l: Line) => ({ component_id: l.component_id, quantity: l.quantity || 1 }))
        : [],
    }
    setSaving(true)
    try {
      if (product) await api.put(`/products/${product.id}`, body)
      else await api.post('/products', body)
      message.success('已保存')
      onSaved()
      onClose()
    } catch (e) {
      message.error(errorMessage(e))
    } finally {
      setSaving(false)
    }
  }
  const initial = product
    ? { ...product, bundle_items: (product.bundle_items ?? []).map((b: Product) => ({ ...b, _key: newKey() })) }
    : { product_type: 'normal', status: 'on_sale', unit: '个', purchase_lead_days: 15, moq: 1, bundle_items: [] }
  const num = (name: string, label: string, precision = 2, span = 6) => (
    <Col span={span}>
      <Form.Item name={name} label={label}>
        <InputNumber min={0} precision={precision} style={{ width: '100%' }} />
      </Form.Item>
    </Col>
  )
  return (
    <Drawer
      open={open}
      onClose={onClose}
      size={880}
      title={product ? `编辑产品 ${product.sku}` : '新增产品'}
      destroyOnHidden
      extra={<Button type="primary" loading={saving} onClick={save}>保存</Button>}
    >
      <Form form={form} layout="vertical" initialValues={initial} preserve={false}>
        <Tabs
          items={[
            {
              key: 'basic', label: '基础信息', forceRender: true,
              children: (
                <Row gutter={16}>
                  <Col span={8}><Form.Item name="sku" label="SKU" rules={[{ required: true }]}><Input /></Form.Item></Col>
                  <Col span={16}><Form.Item name="name" label="品名" rules={[{ required: true }]}><Input /></Form.Item></Col>
                  <Col span={8}><Form.Item name="spu" label="SPU（款号）"><Input /></Form.Item></Col>
                  <Col span={16}><Form.Item name="name_en" label="英文名"><Input /></Form.Item></Col>
                  <Col span={8}><Form.Item name="barcode" label="商品条码（UPC/EAN）" tooltip="用于扫码验货、打印商品条码标签"><Input /></Form.Item></Col>
                  <Col span={8}><Form.Item name="product_type" label="产品类型"><Select options={dictOptions(PRODUCT_TYPE)} /></Form.Item></Col>
                  <Col span={8}><Form.Item name="status" label="状态"><Select options={dictOptions(PRODUCT_STATUS)} /></Form.Item></Col>
                  <Col span={8}><Form.Item name="unit" label="单位"><Input /></Form.Item></Col>
                  <Col span={8}><Form.Item name="category_id" label="分类"><CategorySelect /></Form.Item></Col>
                  <Col span={8}><Form.Item name="brand_id" label="品牌"><BrandSelect /></Form.Item></Col>
                  <Col span={8}><Form.Item name="image_url" label="图片链接"><Input /></Form.Item></Col>
                  <Col span={8}><Form.Item name="developer_id" label="开发人员"><UserSelect /></Form.Item></Col>
                  <Col span={8}><Form.Item name="purchaser_id" label="采购员"><UserSelect /></Form.Item></Col>
                  {can('product:cost:view') && num('purchase_cost', '参考采购成本（本位币）', 4, 8)}
                  <Col span={8}><Form.Item name="default_supplier_id" label="默认供应商"><SupplierSelect /></Form.Item></Col>
                  <Col span={8}><Form.Item name="purchase_lead_days" label="采购交期（天）"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
                  <Col span={8}><Form.Item name="moq" label="最小起订量"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col>
                  <Col span={24}><Form.Item name="remark" label="备注"><Input.TextArea rows={2} /></Form.Item></Col>
                  {type === 'bundle' && (
                    <Col span={24}>
                      <Divider titlePlacement="start">组合明细（1 个组合品包含）</Divider>
                      <Form.Item name="bundle_items">
                        <LinesEditor
                          addText="添加子产品"
                          columns={[
                            { key: 'component_id', title: '子产品', type: 'product', required: true, excludeBundle: true },
                            { key: 'quantity', title: '数量', type: 'number', width: 120, min: 1 },
                          ]}
                        />
                      </Form.Item>
                    </Col>
                  )}
                </Row>
              ),
            },
            {
              key: 'spec', label: '规格与箱规', forceRender: true,
              children: (
                <Row gutter={16}>
                  {num('weight_kg', '单品重量 kg', 3)}
                  {num('length_cm', '长 cm', 1)}
                  {num('width_cm', '宽 cm', 1)}
                  {num('height_cm', '高 cm', 1)}
                  <Col span={6}><Form.Item name="units_per_carton" label="单箱数量"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
                  {num('carton_weight_kg', '箱重 kg', 2)}
                  {num('carton_length_cm', '箱长 cm', 1)}
                  {num('carton_width_cm', '箱宽 cm', 1)}
                  {num('carton_height_cm', '箱高 cm', 1)}
                </Row>
              ),
            },
            {
              key: 'customs', label: '报关信息', forceRender: true,
              children: (
                <Row gutter={16}>
                  <Col span={12}><Form.Item name="declare_name_cn" label="中文报关名"><Input /></Form.Item></Col>
                  <Col span={12}><Form.Item name="declare_name_en" label="英文报关名"><Input /></Form.Item></Col>
                  {num('declare_value_usd', '申报价值 USD', 2, 8)}
                  <Col span={8}><Form.Item name="hs_code" label="海关编码"><Input /></Form.Item></Col>
                  <Col span={8}><Form.Item name="material" label="材质"><Input /></Form.Item></Col>
                  <Col span={8}><Form.Item name="usage" label="用途"><Input /></Form.Item></Col>
                </Row>
              ),
            },
            ...(product ? [{ key: 'quotes', label: '供应商报价', children: <SupplierQuotes productId={product.id} /> }] : []),
          ]}
        />
      </Form>
    </Drawer>
  )
}

export default function Products() {
  const [drawer, setDrawer] = useState<{ open: boolean; product: Product | null }>({ open: false, product: null })
  const [importOpen, setImportOpen] = useState(false)
  const [labels, setLabels] = useState<LabelLine[] | null>(null)
  const reload = useReload('products')
  const qc = useQueryClient()
  const run = useAction()
  const cur = useBaseCurrency()
  const can = usePerm()
  const afterSave = () => {
    reload()
    qc.invalidateQueries({ queryKey: ['product-options'] })
  }
  return (
    <>
      <DataTable<Product>
        queryKey="products"
        url="/products"
        exportUrl="/products/export"
        filters={[
          { name: 'keyword', placeholder: 'SKU / 品名 / SPU' },
          { name: 'category_id', type: 'custom', render: () => <CategorySelect /> },
          { name: 'status', type: 'select', label: '状态', options: dictOptions(PRODUCT_STATUS) },
          { name: 'product_type', type: 'select', label: '类型', options: dictOptions(PRODUCT_TYPE) },
        ]}
        rowSelection
        toolbar={({ selectedRows }) => (
          <Space>
            <Perm code="product:edit">
              <Space>
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setDrawer({ open: true, product: null })}>新增产品</Button>
                <Button icon={<UploadOutlined />} onClick={() => setImportOpen(true)}>导入</Button>
              </Space>
            </Perm>
            <Button icon={<PrinterOutlined />} disabled={!selectedRows.length}
              onClick={() => setLabels(selectedRows.map((r) => ({ key: r.id, product_id: r.id, name: r.sku, code: r.barcode ?? undefined, title: r.name_en || r.name, qty: 1 })))}>
              打印标签
            </Button>
          </Space>
        )}
        columns={[
          { title: '产品', key: 'product', fixed: 'left', render: (_, r) => <ProductCell image={r.image_url} title={r.sku} sub={r.name} extra={r.spu ? `SPU ${r.spu}` : undefined} /> },
          { title: '类型', dataIndex: 'product_type', render: (v) => <StatusTag dict={PRODUCT_TYPE} value={v} /> },
          { title: '状态', dataIndex: 'status', render: (v) => <StatusTag dict={PRODUCT_STATUS} value={v} /> },
          { title: '分类', dataIndex: 'category_name', render: (v) => v ?? '-' },
          { title: '品牌', dataIndex: 'brand_name', render: (v) => v ?? '-' },
          ...(can('product:cost:view') ? [{ title: '采购成本', dataIndex: 'purchase_cost', align: 'right' as const, render: (v: number) => fmtMoney(v, cur, 2) }] : []),
          { title: '重量kg', dataIndex: 'weight_kg', align: 'right' },
          { title: '尺寸cm', key: 'size', render: (_, r) => `${r.length_cm}×${r.width_cm}×${r.height_cm}` },
          { title: '本地可用', dataIndex: 'stock_available', align: 'right', render: (v) => <b>{v ?? 0}</b> },
          {
            title: '组合明细', dataIndex: 'bundle_items',
            render: (items: Product[]) => (items?.length ? items.map((b) => `${b.component_sku}×${b.quantity}`).join(', ') : '-'),
          },
          {
            title: '操作', key: 'op', fixed: 'right',
            render: (_, r) => (
              <Space>
                <a onClick={() => setDrawer({ open: true, product: r })}>{can('product:edit') ? '编辑' : '查看'}</a>
                <Perm code="product:delete">
                  <a style={{ color: '#ff4d4f' }} onClick={() => run(() => api.del(`/products/${r.id}`), { confirm: `删除产品 ${r.sku}？`, danger: true, onDone: afterSave })}>删除</a>
                </Perm>
              </Space>
            ),
          },
        ]}
      />
      <ProductDrawer open={drawer.open} product={drawer.product} onClose={() => setDrawer({ open: false, product: null })} onSaved={afterSave} />
      <PrintLabelsModal open={!!labels} lines={labels ?? []} kinds={['sku', 'barcode']} onClose={() => setLabels(null)} />
      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} title="导入产品" uploadUrl="/products/import"
        templateUrl="/products/import-template" onDone={afterSave}
        extra={<span style={{ color: '#888', fontSize: 12 }}>按 SKU 新增或更新；分类、品牌不存在时自动创建。组合产品请在页面中新建。</span>} />
    </>
  )
}
