import { useState } from 'react'
import { App, Button, Card, Image, Input, InputNumber, Select, Space, Switch, Table, Tag, Typography } from 'antd'
import { DownloadOutlined, ShoppingCartOutlined } from '@ant-design/icons'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api, cleanParams, download, errorMessage, type Option, type Page } from '@/api/client'
import { fmtMoney, fmtNumber } from '@/utils/format'
import { useCart } from '../cart'
import { useT } from '../i18n'

interface Item {
  product_id: number
  sku: string
  title: string
  name_en?: string | null
  image_url?: string | null
  category_name?: string | null
  weight_kg: number
  length_cm: number
  width_cm: number
  height_cm: number
  units_per_carton: number
  price: number
  currency: string
  min_qty: number
  stock: number | null
  in_stock: boolean
  description?: string | null
}

export default function PortalCatalog() {
  const t = useT()
  const { message } = App.useApp()
  const add = useCart((s) => s.add)
  const [kw, setKw] = useState('')
  const [filters, setFilters] = useState<{ keyword?: string; category_id?: number; in_stock_only?: boolean }>({})
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [qty, setQty] = useState<Record<number, number>>({})
  const params = cleanParams({ ...filters, page, page_size: pageSize })
  const { data, isFetching } = useQuery({
    queryKey: ['portal-catalog', params],
    queryFn: () => api.get<Page<Item>>('/portal/catalog', params),
    placeholderData: keepPreviousData,
  })
  const { data: cats } = useQuery({ queryKey: ['portal-cats'], queryFn: () => api.get<Option[]>('/portal/categories') })

  const addItem = (r: Item) => {
    const n = qty[r.product_id] ?? 1
    add({ product_id: r.product_id, sku: r.sku, title: r.title, image_url: r.image_url, price: r.price, currency: r.currency, min_qty: r.min_qty, qty: n })
    message.success(`${t('added')}：${r.sku} × ${n}`)
  }

  return (
    <Card variant="borderless">
      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <Space wrap>
          <Input.Search
            allowClear
            placeholder={t('keyword')}
            value={kw}
            onChange={(e) => setKw(e.target.value)}
            onSearch={(v) => { setFilters((f) => ({ ...f, keyword: v || undefined })); setPage(1) }}
            style={{ width: 260 }}
            enterButton={t('search')}
          />
          <Select
            allowClear
            placeholder={t('allCategories')}
            options={cats}
            style={{ width: 180 }}
            onChange={(v) => { setFilters((f) => ({ ...f, category_id: v })); setPage(1) }}
          />
          <Space>
            <Switch size="small" onChange={(v) => { setFilters((f) => ({ ...f, in_stock_only: v || undefined })); setPage(1) }} />
            <span>{t('inStockOnly')}</span>
          </Space>
        </Space>
        <Button icon={<DownloadOutlined />} onClick={() => download('/portal/catalog/export').catch((e) => message.error(errorMessage(e)))}>
          {t('exportCatalog')}
        </Button>
      </div>
      <Table<Item>
        rowKey="product_id"
        loading={isFetching}
        dataSource={data?.items ?? []}
        scroll={{ x: 'max-content' }}
        pagination={{
          current: page,
          pageSize,
          total: data?.total ?? 0,
          showSizeChanger: true,
          showTotal: (n) => t('total_n', { n }),
          onChange: (p, ps) => { setPage(p); setPageSize(ps) },
        }}
        columns={[
          {
            title: t('product'),
            key: 'product',
            render: (_, r) => (
              <Space align="start">
                {r.image_url ? (
                  <Image src={r.image_url} width={56} height={56} style={{ objectFit: 'cover', borderRadius: 4 }} />
                ) : (
                  <div style={{ width: 56, height: 56, background: '#f5f5f5', borderRadius: 4 }} />
                )}
                <div style={{ maxWidth: 360 }}>
                  <Typography.Text strong copyable={{ text: r.sku }}>{r.sku}</Typography.Text>
                  <div>{r.title}</div>
                  {r.name_en && r.name_en !== r.title && <div style={{ color: '#888', fontSize: 12 }}>{r.name_en}</div>}
                  {r.category_name && <Tag style={{ marginTop: 4 }}>{r.category_name}</Tag>}
                </div>
              </Space>
            ),
          },
          {
            title: t('price'),
            dataIndex: 'price',
            align: 'right',
            render: (v, r) => <Typography.Text strong style={{ fontSize: 15, color: '#cf1322' }}>{fmtMoney(v, r.currency)}</Typography.Text>,
          },
          {
            title: t('stock'),
            key: 'stock',
            align: 'center',
            render: (_, r) =>
              r.stock !== null ? (
                <Tag color={r.stock > 0 ? 'green' : 'red'}>{r.stock}</Tag>
              ) : (
                <Tag color={r.in_stock ? 'green' : 'red'}>{r.in_stock ? t('inStock') : t('outOfStock')}</Tag>
              ),
          },
          { title: t('moq'), dataIndex: 'min_qty', align: 'center' },
          {
            title: t('specs'),
            key: 'specs',
            render: (_, r) => (
              <div style={{ fontSize: 12, color: '#666' }}>
                <div>{t('weight')}: {fmtNumber(r.weight_kg, 3)} kg</div>
                <div>{fmtNumber(r.length_cm, 1)} × {fmtNumber(r.width_cm, 1)} × {fmtNumber(r.height_cm, 1)} cm</div>
                {r.units_per_carton > 0 && <div>{t('perCarton')}: {r.units_per_carton}</div>}
              </div>
            ),
          },
          {
            title: t('qty'),
            key: 'qty',
            fixed: 'right',
            render: (_, r) => (
              <Space.Compact>
                <InputNumber min={1} value={qty[r.product_id] ?? 1} onChange={(v) => setQty((q) => ({ ...q, [r.product_id]: Number(v) || 1 }))} style={{ width: 80 }} />
                <Button type="primary" icon={<ShoppingCartOutlined />} onClick={() => addItem(r)}>
                  {t('addToCart')}
                </Button>
              </Space.Compact>
            ),
          },
        ]}
      />
    </Card>
  )
}
