import { useState } from 'react'
import { Alert, App, Button, Col, Divider, Form, Input, InputNumber, Row, Select, Space, Switch, Tag, Typography } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import Perm from '@/components/Perm'
import ProductCell from '@/components/ProductCell'
import StatusTag from '@/components/StatusTag'
import { CurrencySelect, ProductSelect } from '@/components/selects'
import { STOCK_DISPLAY, dictOptions } from '@/utils/dicts'
import { fmtMoney } from '@/utils/format'
import { useBaseCurrency } from '@/store/auth'

type C = Record<string, any>

interface Level {
  id: number
  code: string
  name: string
  discount_rate: number
}

export default function DistributionCatalog() {
  const reload = useReload('dist-catalog')
  const baseCur = useBaseCurrency()
  const run = useAction()
  const { message } = App.useApp()
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<C | null>(null)
  const { data: levels } = useQuery({
    queryKey: ['dist-levels'],
    queryFn: () => api.get<{ items: Level[] }>('/distribution/levels', { page_size: 200 }),
  })
  const levelList = levels?.items ?? []
  const levelName = (id: number) => levelList.find((l) => l.id === id)?.name ?? id

  const setActive = (ids: number[], active: boolean) =>
    run(() => api.post('/distribution/catalog', { items: ids.map((product_id) => ({ product_id, is_active: active })) }), { onDone: reload })

  return (
    <>
      <DataTable<C>
        queryKey="dist-catalog"
        url="/distribution/catalog"
        rowSelection
        filters={[
          { name: 'keyword', placeholder: 'SKU / 品名 / 分销标题' },
          { name: 'is_active', type: 'select', label: '状态', options: [{ label: '上架中', value: true }, { label: '已下架', value: false }] },
        ]}
        toolbar={(ctx) => (
          <Perm code="distribution:edit">
            <Space>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setAdding(true)}>添加分销商品</Button>
              <Button disabled={!ctx.selectedRows.length} onClick={() => setActive(ctx.selectedRows.map((r) => r.product_id), true).then(ctx.clearSelection)}>批量上架</Button>
              <Button disabled={!ctx.selectedRows.length} onClick={() => setActive(ctx.selectedRows.map((r) => r.product_id), false).then(ctx.clearSelection)}>批量下架</Button>
            </Space>
          </Perm>
        )}
        columns={[
          { title: '商品', key: 'p', render: (_, r) => <ProductCell image={r.image_url} title={r.sku} sub={r.title || r.product_name} /> },
          { title: '分销基础价', dataIndex: 'base_price', align: 'right', render: (v, r) => <Typography.Text strong>{fmtMoney(v, r.currency)}</Typography.Text> },
          {
            title: '等级价', key: 'lp',
            render: (_, r) =>
              r.level_prices.length ? (
                <Space size={4} wrap>
                  {r.level_prices.map((x: { level_id: number; price: number }) => (
                    <Tag key={x.level_id} color="purple">{levelName(x.level_id)} {fmtMoney(x.price, r.currency)}</Tag>
                  ))}
                </Space>
              ) : (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>按等级折扣</Typography.Text>
              ),
          },
          { title: '采购成本', dataIndex: 'purchase_cost', align: 'right', render: (v) => (v === null || v === undefined ? '-' : fmtMoney(v, baseCur)) },
          { title: '批发起订量', dataIndex: 'min_qty', align: 'center' },
          { title: '分销可售', dataIndex: 'available', align: 'right', render: (v) => <span style={{ color: v > 0 ? undefined : '#cf1322' }}>{v}</span> },
          { title: '库存展示', dataIndex: 'stock_display', render: (v, r) => <span>{STOCK_DISPLAY[v]?.[0] ?? v}{v === 'capped' ? `（≤${r.stock_cap}）` : ''}</span> },
          { title: '状态', dataIndex: 'is_active', render: (v) => <StatusTag dict={{ true: ['上架中', 'green'], false: ['已下架', 'default'] }} value={String(v)} /> },
          {
            title: '操作', key: 'op', fixed: 'right',
            render: (_, r) => (
              <Perm code="distribution:edit">
                <Space>
                  <a onClick={() => setEditing(r)}>编辑</a>
                  <a style={{ color: '#cf1322' }} onClick={() => run(() => api.del(`/distribution/catalog/${r.id}`), { confirm: `将 ${r.sku} 移出分销目录？`, onDone: reload })}>移出</a>
                </Space>
              </Perm>
            ),
          },
        ]}
      />
      <FormModal<{ product_ids: number[]; base_price?: number; currency?: string; min_qty?: number }>
        open={adding}
        title="添加分销商品"
        width={620}
        onCancel={() => setAdding(false)}
        initialValues={{ min_qty: 1 }}
        onSubmit={async (v) => {
          await api.post('/distribution/catalog', {
            items: v.product_ids.map((product_id) => ({ product_id, base_price: v.base_price, currency: v.currency, min_qty: v.min_qty, is_active: true })),
          })
          message.success(`已添加 ${v.product_ids.length} 个商品`)
          reload()
        }}
      >
        <Alert type="info" title="分销价优先级：等级专属价 ＞ 基础价 × 等级折扣。添加后可逐个设置等级价。" style={{ marginBottom: 16 }} />
        <Form.Item name="product_ids" label="选择产品" rules={[{ required: true }]}>
          <ProductSelect mode="multiple" />
        </Form.Item>
        <Row gutter={16}>
          <Col span={8}><Form.Item name="base_price" label="基础价（统一）"><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={8}><Form.Item name="currency" label="定价币种" extra="默认本位币"><CurrencySelect /></Form.Item></Col>
          <Col span={8}><Form.Item name="min_qty" label="批发起订量"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col>
        </Row>
      </FormModal>
      <FormModal
        open={!!editing}
        title={`编辑分销商品：${editing?.sku ?? ''}`}
        width={760}
        onCancel={() => setEditing(null)}
        initialValues={
          editing
            ? {
                ...editing,
                levels: Object.fromEntries((editing.level_prices as { level_id: number; price: number }[]).map((x) => [String(x.level_id), x.price])),
              }
            : undefined
        }
        onSubmit={async (v: C) => {
          const { levels: lp, ...rest } = v
          await api.post('/distribution/catalog', {
            items: [{
              product_id: editing!.product_id, base_price: rest.base_price, currency: rest.currency, min_qty: rest.min_qty,
              is_active: rest.is_active, stock_display: rest.stock_display, stock_cap: rest.stock_cap, title: rest.title ?? '',
              description: rest.description ?? '', sort: rest.sort,
            }],
          })
          const prices = Object.entries((lp ?? {}) as Record<string, number | null>)
            .filter(([, p]) => p !== null && p !== undefined)
            .map(([level_id, price]) => ({ level_id: Number(level_id), price }))
          await api.put(`/distribution/catalog/${editing!.product_id}/level-prices`, { prices })
          message.success('已保存')
          reload()
        }}
      >
        <Row gutter={16}>
          <Col span={8}><Form.Item name="base_price" label="分销基础价" rules={[{ required: true }]}><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={8}><Form.Item name="currency" label="定价币种"><CurrencySelect /></Form.Item></Col>
          <Col span={8}><Form.Item name="min_qty" label="批发起订量"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={8}><Form.Item name="stock_display" label="门户库存展示"><Select options={dictOptions(STOCK_DISPLAY)} /></Form.Item></Col>
          <Col span={8}><Form.Item name="stock_cap" label="展示上限" extra="“显示上限”时生效"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={4}><Form.Item name="sort" label="排序"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={4}><Form.Item name="is_active" label="上架" valuePropName="checked"><Switch /></Form.Item></Col>
          <Col span={24}><Form.Item name="title" label="分销标题" extra="为空使用产品名称"><Input /></Form.Item></Col>
          <Col span={24}><Form.Item name="description" label="分销说明（卖点、包装等）"><Input.TextArea rows={3} /></Form.Item></Col>
        </Row>
        <Divider titlePlacement="start" plain>等级专属价（留空则按 基础价 × 等级折扣）</Divider>
        <Row gutter={16}>
          {levelList.map((l) => (
            <Col span={8} key={l.id}>
              <Form.Item name={['levels', String(l.id)]} label={`${l.name}（折扣 ${Number(l.discount_rate).toFixed(2)}）`}>
                <InputNumber min={0} precision={2} style={{ width: '100%' }} placeholder={editing ? (Number(editing.base_price) * Number(l.discount_rate)).toFixed(2) : undefined} />
              </Form.Item>
            </Col>
          ))}
          {!levelList.length && <Col span={24}><Typography.Text type="secondary">尚未设置分销等级，可在「分销设置」中添加。</Typography.Text></Col>}
        </Row>
      </FormModal>
    </>
  )
}
