import { useMemo, useState } from 'react'
import { App, Button, Card, Form, Input, InputNumber, Modal, Space, Switch, Table, Tag, Tooltip } from 'antd'
import { DownloadOutlined, SettingOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { api, download, errorMessage } from '@/api/client'
import Perm from '@/components/Perm'
import ProductCell from '@/components/ProductCell'
import { ShopSelect, WarehouseSelect } from '@/components/selects'
import RuleModal from './RuleModal'

type R = Record<string, any>

const daysTag = (v: number | null) => (v === null || v === undefined ? '-' : <Tag color={v < 15 ? 'red' : v < 30 ? 'orange' : 'green'}>{v}</Tag>)

export default function ShipSuggest() {
  const [shopId, setShopId] = useState<number>()
  const [keyword, setKeyword] = useState('')
  const [onlyNeed, setOnlyNeed] = useState(true)
  const [qty, setQty] = useState<Record<number, number>>({})
  const [selected, setSelected] = useState<React.Key[]>([])
  const [rule, setRule] = useState<{ open: boolean; listingId?: number; title?: string }>({ open: false })
  const [genOpen, setGenOpen] = useState(false)
  const [warehouseId, setWarehouseId] = useState<number>()
  const { message } = App.useApp()
  const { data, isFetching, refetch } = useQuery({
    queryKey: ['ship-suggest', shopId, keyword, onlyNeed],
    queryFn: () => api.get<R[]>('/replenishment/listings', { shop_id: shopId, keyword: keyword || undefined, only_need: onlyNeed }),
  })
  const rows = useMemo(() => data ?? [], [data])
  const generate = async () => {
    if (!warehouseId) return message.warning('请选择发货仓')
    const items = rows.filter((r) => selected.includes(r.listing_id)).map((r) => ({ listing_id: r.listing_id, qty: qty[r.listing_id] ?? r.suggest_ship_qty })).filter((i) => i.qty > 0)
    if (!items.length) return message.warning('所选 Listing 建议数量为 0')
    try {
      const r = await api.post('/replenishment/to-shipment-plans', { items, ship_from_warehouse_id: warehouseId })
      message.success(r.message)
      setGenOpen(false)
      setSelected([])
    } catch (e) {
      message.error(errorMessage(e))
    }
  }
  return (
    <Card variant="borderless">
      <Space wrap style={{ marginBottom: 12 }}>
        <ShopSelect value={shopId} onChange={setShopId} />
        <Input.Search placeholder="MSKU / ASIN / 标题" allowClear onSearch={setKeyword} style={{ width: 240 }} />
        <span>只看需要补货 <Switch checked={onlyNeed} onChange={setOnlyNeed} /></span>
        <Perm code="replenish:edit">
          <Button icon={<SettingOutlined />} onClick={() => setRule({ open: true })}>默认补货参数</Button>
        </Perm>
        <Perm code={['fba:plan:edit']}>
          <Button type="primary" disabled={!selected.length} onClick={() => setGenOpen(true)}>生成发货计划（{selected.length}）</Button>
        </Perm>
        <Button icon={<DownloadOutlined />} onClick={() => download('/replenishment/listings/export', { shop_id: shopId, only_need: onlyNeed })}>导出</Button>
      </Space>
      <Table<R>
        rowKey="listing_id"
        size="middle"
        loading={isFetching}
        dataSource={rows}
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 50, showTotal: (t) => `共 ${t} 个 Listing` }}
        rowSelection={{ selectedRowKeys: selected, onChange: setSelected }}
        columns={[
          { title: 'Listing', fixed: 'left', render: (_, r) => <ProductCell image={r.image_url} title={r.msku} sub={r.title} extra={`${r.shop_name} · ${r.sku ?? '未配对'}`} /> },
          { title: '7/14/30天销量', render: (_, r) => `${r.sales_7d} / ${r.sales_14d} / ${r.sales_30d}` },
          { title: '加权日均', dataIndex: 'daily_sales', align: 'right', render: (v) => <b>{v}</b> },
          { title: 'FBA可售', dataIndex: 'fba_available', align: 'right' },
          { title: 'FBA在途', dataIndex: 'fba_inbound', align: 'right' },
          { title: '本地可用', dataIndex: 'local_available', align: 'right' },
          { title: <Tooltip title="FBA 可售 ÷ 日均">可售天数</Tooltip>, dataIndex: 'available_days', align: 'right', render: daysTag },
          { title: <Tooltip title="(可售 + 在途) ÷ 日均">总可售天数</Tooltip>, dataIndex: 'total_days', align: 'right', render: daysTag },
          { title: '预计断货', dataIndex: 'out_of_stock_date', render: (v) => v ?? '-' },
          { title: '建议发货日', dataIndex: 'suggest_ship_date', render: (v) => v ?? '-' },
          {
            title: '建议发货量', dataIndex: 'suggest_ship_qty', align: 'right', fixed: 'right',
            render: (v, r) => <InputNumber min={0} size="small" value={qty[r.listing_id] ?? v} onChange={(x) => setQty((s) => ({ ...s, [r.listing_id]: x ?? 0 }))} style={{ width: 90 }} />,
          },
          {
            title: '参数', fixed: 'right',
            render: (_, r) => (
              <Perm code="replenish:edit">
                <a onClick={() => setRule({ open: true, listingId: r.listing_id, title: `补货参数 - ${r.msku}` })}>
                  {r.has_custom_rule ? <Tag color="purple">个性化</Tag> : '设置'}
                </a>
              </Perm>
            ),
          },
        ]}
      />
      <RuleModal open={rule.open} listingId={rule.listingId} title={rule.title} onClose={() => setRule({ open: false })} onDone={() => refetch()} />
      <Modal open={genOpen} title="生成发货计划" onCancel={() => setGenOpen(false)} onOk={generate} okText="生成">
        <p>将为选中的 {selected.length} 个 Listing 按店铺生成发货计划（可在「发货计划」中调整后生成货件）。</p>
        <Form layout="vertical"><Form.Item label="发货仓" required><WarehouseSelect excludeFba value={warehouseId} onChange={setWarehouseId} /></Form.Item></Form>
      </Modal>
    </Card>
  )
}
