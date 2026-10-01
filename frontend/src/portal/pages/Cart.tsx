import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, App, Button, Card, Col, Descriptions, Divider, Empty, Form, Image, Input, InputNumber, Radio, Result, Row, Select, Space, Table, Typography } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, errorMessage } from '@/api/client'
import { fmtMoney, fmtNumber } from '@/utils/format'
import { usePortalMe, type PortalOrder } from '../api'
import { useCart, type CartItem } from '../cart'
import { useT } from '../i18n'

interface Quote {
  currency: string
  lines: { product_id: number; sku: string; name: string; qty: number; unit_price: number; amount: number; in_stock: boolean }[]
  weight_kg: number
  goods: number
  freight: number
  handling: number
  total: number
  channel_name?: string | null
  transit_days?: number | null
  available_funds: number
  sufficient: boolean
}

interface Channel {
  value: number
  label: string
  transit_days?: number | null
}

function useDebounced<T>(value: T, ms = 400): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const h = setTimeout(() => setV(value), ms)
    return () => clearTimeout(h)
  }, [value, ms])
  return v
}

export default function PortalCart() {
  const t = useT()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { message, modal } = App.useApp()
  const { items, setQty, remove, clear } = useCart()
  const { data: me } = usePortalMe()
  const d = me?.distributor
  const [orderType, setOrderType] = useState<'dropship' | 'wholesale'>('dropship')
  const [channelId, setChannelId] = useState<number | undefined>()
  const [form] = Form.useForm()
  const [placed, setPlaced] = useState<PortalOrder | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (d && !d.allow_dropship && d.allow_wholesale) setOrderType('wholesale')
  }, [d])

  const { data: channels } = useQuery({ queryKey: ['portal-channels'], queryFn: () => api.get<Channel[]>('/portal/channels') })
  const quoteBody = useDebounced(
    useMemo(
      () => ({ order_type: orderType, channel_id: channelId, items: items.map((i) => ({ product_id: i.product_id, qty: i.qty })) }),
      [orderType, channelId, items],
    ),
  )
  const canQuote = quoteBody.items.length > 0 && (quoteBody.order_type === 'wholesale' || !!quoteBody.channel_id)
  const { data: quote, error: quoteError, isFetching: quoting } = useQuery({
    queryKey: ['portal-quote', quoteBody],
    queryFn: () => api.post<Quote>('/portal/quote', quoteBody),
    enabled: canQuote,
    retry: false,
  })

  const submit = async () => {
    const values = await form.validateFields()
    modal.confirm({
      title: t('confirmSubmit'),
      content: quote && <Typography.Text strong style={{ fontSize: 18 }}>{fmtMoney(quote.total, quote.currency)}</Typography.Text>,
      okText: t('ok'),
      cancelText: t('cancelBtn'),
      onOk: async () => {
        setSubmitting(true)
        try {
          const { reference_no, remark, ...address } = values
          const order = await api.post<PortalOrder>('/portal/orders', {
            ...quoteBody,
            reference_no: reference_no || undefined,
            remark: remark || undefined,
            address,
          })
          setPlaced(order)
          clear()
          qc.invalidateQueries({ queryKey: ['portal-me'] })
          qc.invalidateQueries({ queryKey: ['portal-orders'] })
          qc.invalidateQueries({ queryKey: ['portal-dashboard'] })
        } catch (e) {
          message.error(errorMessage(e))
        } finally {
          setSubmitting(false)
        }
      },
    })
  }

  if (placed) {
    return (
      <Card variant="borderless">
        <Result
          status="success"
          title={t('orderPlaced')}
          subTitle={`${t('orderPlacedDesc')}: ${placed.reference_no} · ${t('total')} ${fmtMoney(Number(placed.charge_detail?.total ?? 0), placed.currency)}`}
          extra={[
            <Button type="primary" key="orders" onClick={() => navigate('/portal/orders')}>{t('viewOrders')}</Button>,
            <Button key="shop" onClick={() => { setPlaced(null); navigate('/portal/catalog') }}>{t('continueShopping')}</Button>,
          ]}
        />
      </Card>
    )
  }

  if (!items.length) {
    return (
      <Card variant="borderless">
        <Empty description={t('cartEmpty')}>
          <Button type="primary" onClick={() => navigate('/portal/catalog')}>{t('goShopping')}</Button>
        </Empty>
      </Card>
    )
  }

  const priceMap = new Map((quote?.lines ?? []).map((l) => [l.product_id, l]))
  const isDropship = orderType === 'dropship'

  return (
    <Row gutter={16}>
      <Col xs={24} lg={16}>
        <Card variant="borderless" title={`${t('cart')}（${items.length} ${t('items')}）`} extra={<a onClick={clear}>{t('clearCart')}</a>}>
          <Table<CartItem>
            rowKey="product_id"
            size="small"
            pagination={false}
            dataSource={items}
            columns={[
              {
                title: t('product'),
                key: 'p',
                render: (_, r) => (
                  <Space>
                    {r.image_url ? <Image src={r.image_url} width={40} height={40} style={{ objectFit: 'cover' }} /> : null}
                    <div>
                      <div style={{ fontWeight: 600 }}>{r.sku}</div>
                      <div style={{ fontSize: 12, color: '#666', maxWidth: 320 }}>{r.title}</div>
                    </div>
                  </Space>
                ),
              },
              { title: t('price'), key: 'price', align: 'right', render: (_, r) => fmtMoney(priceMap.get(r.product_id)?.unit_price ?? r.price, r.currency) },
              {
                title: t('qty'),
                key: 'qty',
                render: (_, r) => (
                  <Space orientation="vertical" size={0}>
                    <InputNumber min={1} value={r.qty} onChange={(v) => setQty(r.product_id, Number(v) || 1)} style={{ width: 90 }} />
                    {orderType === 'wholesale' && r.qty < r.min_qty && <Typography.Text type="danger" style={{ fontSize: 12 }}>{t('moq')} {r.min_qty}</Typography.Text>}
                    {priceMap.get(r.product_id)?.in_stock === false && <Typography.Text type="warning" style={{ fontSize: 12 }}>{t('outOfStock')}</Typography.Text>}
                  </Space>
                ),
              },
              { title: t('amount'), key: 'amt', align: 'right', render: (_, r) => fmtMoney(priceMap.get(r.product_id)?.amount ?? r.price * r.qty, r.currency) },
              { title: '', key: 'op', render: (_, r) => <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(r.product_id)} /> },
            ]}
          />
        </Card>
        <Card variant="borderless" style={{ marginTop: 16 }} title={t('orderType')}>
          <Radio.Group value={orderType} onChange={(e) => setOrderType(e.target.value)}>
            <Radio.Button value="dropship" disabled={d && !d.allow_dropship}>{t('dropship')}</Radio.Button>
            <Radio.Button value="wholesale" disabled={d && !d.allow_wholesale}>{t('wholesale')}</Radio.Button>
          </Radio.Group>
          <div style={{ color: '#888', margin: '8px 0 16px' }}>{isDropship ? t('dropshipHint') : t('wholesaleHint')}</div>
          <Form form={form} layout="vertical">
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <Form.Item label={t('channel')} required={isDropship} extra={!isDropship ? t('channelOptional') : undefined}>
                  <Select
                    allowClear
                    placeholder={t('channelPlaceholder')}
                    value={channelId}
                    onChange={setChannelId}
                    options={(channels ?? []).map((c) => ({ value: c.value, label: c.transit_days ? `${c.label}（${c.transit_days} ${t('days')}）` : c.label }))}
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item name="reference_no" label={t('referenceNo')} extra={t('referenceHint')}>
                  <Input maxLength={64} />
                </Form.Item>
              </Col>
            </Row>
            <Divider titlePlacement="start" plain>{t('shipTo')}{!isDropship && <Typography.Text type="secondary" style={{ fontSize: 12 }}>（{t('wholesaleAddrHint')}）</Typography.Text>}</Divider>
            <Row gutter={16}>
              <Col xs={24} md={8}><Form.Item name="name" label={t('recipient')} rules={[{ required: isDropship, message: t('required') }]}><Input /></Form.Item></Col>
              <Col xs={24} md={8}><Form.Item name="phone" label={t('phone')}><Input /></Form.Item></Col>
              <Col xs={24} md={8}><Form.Item name="country" label={t('country')} rules={[{ required: isDropship, message: t('required') }]}><Input placeholder="US" maxLength={8} /></Form.Item></Col>
              <Col xs={24} md={8}><Form.Item name="state" label={t('state')}><Input /></Form.Item></Col>
              <Col xs={24} md={8}><Form.Item name="city" label={t('city')}><Input /></Form.Item></Col>
              <Col xs={24} md={8}><Form.Item name="postcode" label={t('postcode')}><Input /></Form.Item></Col>
              <Col xs={24} md={12}><Form.Item name="address1" label={t('address1')} rules={[{ required: isDropship, message: t('required') }]}><Input /></Form.Item></Col>
              <Col xs={24} md={12}><Form.Item name="address2" label={t('address2')}><Input /></Form.Item></Col>
              <Col span={24}><Form.Item name="remark" label={t('remark')}><Input.TextArea rows={2} maxLength={500} /></Form.Item></Col>
            </Row>
          </Form>
        </Card>
      </Col>
      <Col xs={24} lg={8}>
        <Card variant="borderless" title={t('summary')} style={{ position: 'sticky', top: 80 }} loading={quoting && !quote}>
          {!canQuote ? (
            <Alert type="info" title={t('selectChannelFirst')} />
          ) : quoteError ? (
            <Alert type="error" title={errorMessage(quoteError)} />
          ) : quote ? (
            <>
              <Descriptions column={1} size="small">
                <Descriptions.Item label={t('goods')}>{fmtMoney(quote.goods, quote.currency)}</Descriptions.Item>
                <Descriptions.Item label={t('freight')}>
                  {fmtMoney(quote.freight, quote.currency)}
                  {quote.channel_name && <Typography.Text type="secondary" style={{ fontSize: 12 }}>　{quote.channel_name}</Typography.Text>}
                </Descriptions.Item>
                <Descriptions.Item label={t('handling')}>{fmtMoney(quote.handling, quote.currency)}</Descriptions.Item>
                <Descriptions.Item label={t('totalWeight')}>{fmtNumber(quote.weight_kg, 2)} kg</Descriptions.Item>
              </Descriptions>
              <Divider style={{ margin: '12px 0' }} />
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                <span>{t('total')}</span>
                <Typography.Text strong style={{ fontSize: 24, color: '#cf1322' }}>{fmtMoney(quote.total, quote.currency)}</Typography.Text>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: '#888', marginTop: 4 }}>
                <span>{t('afterOrder')}</span>
                <span>{fmtMoney(quote.available_funds - quote.total, quote.currency)}</span>
              </div>
              {!quote.sufficient && (
                <Alert style={{ marginTop: 12 }} type="error" title={t('insufficient')} action={<Button size="small" onClick={() => navigate('/portal/funds?recharge=1')}>{t('recharge')}</Button>} />
              )}
              {quote.lines.some((l) => !l.in_stock) && <Alert style={{ marginTop: 12 }} type="warning" title={t('someOutOfStock')} />}
              <Button type="primary" size="large" block style={{ marginTop: 16 }} disabled={!quote.sufficient} loading={submitting} onClick={submit}>
                {t('submitOrder')}
              </Button>
            </>
          ) : null}
        </Card>
      </Col>
    </Row>
  )
}
