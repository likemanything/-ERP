import { useRef, useState } from 'react'
import { Alert, App, Button, Card, Col, Descriptions, Empty, Input, InputNumber, Row, Space, Switch, Table, Tag, Typography, type InputRef } from 'antd'
import { CheckCircleFilled, ScanOutlined } from '@ant-design/icons'
import { api, errorMessage } from '@/api/client'
import ProductCell from '@/components/ProductCell'
import StatusTag from '@/components/StatusTag'
import { ORDER_STATUS } from '@/utils/dicts'
import { useBaseCurrency } from '@/store/auth'
import { fmtMoney } from '@/utils/format'

interface Line {
  product_id: number
  sku: string
  name: string
  image_url?: string | null
  qty: number
  codes: string[]
}

interface ScanOrder {
  id: number
  order_no: string
  platform_order_id: string
  shop_name?: string | null
  status: string
  is_on_hold: boolean
  hold_reason?: string | null
  ship_name?: string | null
  ship_country?: string | null
  ship_address1?: string | null
  logistics_channel_name?: string | null
  carrier?: string | null
  tracking_no?: string | null
  est_freight: number
  buyer_note?: string | null
  wave_no?: string | null
  lines: Line[]
}

/** 简单提示音：成功高音、失败低音（扫码枪作业无需看屏幕） */
function beep(ok: boolean) {
  try {
    const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    const ctx = new AC()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.frequency.value = ok ? 1200 : 300
    gain.gain.value = 0.08
    osc.connect(gain).connect(ctx.destination)
    osc.start()
    osc.stop(ctx.currentTime + (ok ? 0.12 : 0.35))
    osc.onended = () => void ctx.close()
  } catch {
    /* 浏览器不支持音频时忽略 */
  }
}

export default function ScanShip() {
  const { message } = App.useApp()
  const cur = useBaseCurrency()
  const orderRef = useRef<InputRef>(null)
  const itemRef = useRef<InputRef>(null)
  const trackingRef = useRef<InputRef>(null)
  const [code, setCode] = useState('')
  const [itemCode, setItemCode] = useState('')
  const [order, setOrder] = useState<ScanOrder | null>(null)
  const [scanned, setScanned] = useState<Record<number, number>>({})
  const [skipVerify, setSkipVerify] = useState(false)
  const [tracking, setTracking] = useState('')
  const [carrier, setCarrier] = useState('')
  const [freight, setFreight] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState<{ order_no: string; platform_order_id: string; tracking_no?: string | null; at: string }[]>([])
  const [error, setError] = useState<string | null>(null)

  const reset = () => {
    setOrder(null)
    setScanned({})
    setTracking('')
    setCarrier('')
    setFreight(null)
    setCode('')
    setTimeout(() => orderRef.current?.focus(), 50)
  }

  const lookup = async () => {
    if (!code.trim()) return
    setLoading(true)
    setError(null)
    try {
      const o = await api.get<ScanOrder>('/fulfillment/scan', { code: code.trim() })
      setOrder(o)
      setScanned({})
      setTracking(o.tracking_no ?? '')
      setCarrier(o.carrier ?? '')
      setFreight(null)
      const ok = o.status === 'to_ship' && !o.is_on_hold
      beep(ok)
      if (ok) setTimeout(() => (skipVerify ? trackingRef : itemRef).current?.focus(), 50)
    } catch (e) {
      beep(false)
      setError(errorMessage(e))
      setOrder(null)
    } finally {
      setLoading(false)
      setCode('')
    }
  }

  const verified = !!order && order.lines.every((l) => (scanned[l.product_id] ?? 0) >= l.qty)

  const scanItem = () => {
    const c = itemCode.trim().toUpperCase()
    setItemCode('')
    if (!order || !c) return
    const line = order.lines.find((l) => l.codes.some((x) => x.toUpperCase() === c))
    if (!line) {
      beep(false)
      message.error(`条码 ${c} 不属于该订单`)
      return
    }
    const n = scanned[line.product_id] ?? 0
    if (n >= line.qty) {
      beep(false)
      message.warning(`${line.sku} 已扫够 ${line.qty} 件，请检查是否多放`)
      return
    }
    beep(true)
    const next = { ...scanned, [line.product_id]: n + 1 }
    setScanned(next)
    if (order.lines.every((l) => (next[l.product_id] ?? 0) >= l.qty)) setTimeout(() => trackingRef.current?.focus(), 50)
  }

  const ship = async () => {
    if (!order) return
    if (!skipVerify && !verified) {
      beep(false)
      message.warning('商品尚未验货完成')
      return
    }
    setLoading(true)
    try {
      const o = await api.post<ScanOrder>('/fulfillment/scan-ship', {
        order_id: order.id, tracking_no: tracking || undefined, carrier: carrier || undefined, actual_freight: freight ?? undefined,
      })
      beep(true)
      message.success(`${o.platform_order_id} 已发货`)
      setHistory((h) => [{ order_no: o.order_no, platform_order_id: o.platform_order_id, tracking_no: o.tracking_no, at: new Date().toLocaleTimeString() }, ...h].slice(0, 30))
      reset()
    } catch (e) {
      beep(false)
      message.error(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  const blocked = order && (order.status !== 'to_ship' || order.is_on_hold)

  return (
    <Row gutter={16}>
      <Col xs={24} xl={17}>
        <Card variant="borderless" title={<Space><ScanOutlined />扫码验货发货</Space>}
          extra={<Space><span>跳过商品验货</span><Switch checked={skipVerify} onChange={setSkipVerify} /></Space>}>
          <Input
            ref={orderRef}
            autoFocus
            size="large"
            allowClear
            prefix={<ScanOutlined />}
            placeholder="扫描装箱单条码 / 系统单号 / 平台单号 / 运单号，回车查询"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            onPressEnter={lookup}
            disabled={loading}
          />
          {error && <Alert style={{ marginTop: 12 }} type="error" showIcon title={error} />}
          {!order && !error && <Empty style={{ marginTop: 48 }} description="请扫描订单" />}
          {order && (
            <Space orientation="vertical" size="middle" style={{ width: '100%', marginTop: 16 }}>
              {blocked && (
                <Alert type="error" showIcon title={order.is_on_hold ? `订单已挂起：${order.hold_reason ?? ''}` : `订单状态为「${ORDER_STATUS[order.status]?.[0] ?? order.status}」，不能发货`} />
              )}
              {order.buyer_note && <Alert type="warning" showIcon title={`买家留言：${order.buyer_note}`} />}
              <Descriptions size="small" bordered column={3}>
                <Descriptions.Item label="平台单号">{order.platform_order_id}</Descriptions.Item>
                <Descriptions.Item label="系统单号">{order.order_no}</Descriptions.Item>
                <Descriptions.Item label="状态"><StatusTag dict={ORDER_STATUS} value={order.status} /></Descriptions.Item>
                <Descriptions.Item label="店铺">{order.shop_name}</Descriptions.Item>
                <Descriptions.Item label="收件人">{order.ship_name} / {order.ship_country}</Descriptions.Item>
                <Descriptions.Item label="波次">{order.wave_no ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="物流渠道">{order.logistics_channel_name ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="预估运费">{fmtMoney(order.est_freight, cur)}</Descriptions.Item>
                <Descriptions.Item label="地址">{order.ship_address1 ?? '-'}</Descriptions.Item>
              </Descriptions>
              {!skipVerify && !blocked && (
                <Input
                  ref={itemRef}
                  size="large"
                  placeholder="逐件扫描商品条码（SKU / UPC / FNSKU / MSKU）"
                  value={itemCode}
                  onChange={(e) => setItemCode(e.target.value)}
                  onPressEnter={scanItem}
                  disabled={verified}
                  suffix={verified ? <Tag color="green" icon={<CheckCircleFilled />}>验货完成</Tag> : <span />}
                />
              )}
              <Table<Line>
                size="small"
                rowKey="product_id"
                pagination={false}
                dataSource={order.lines}
                columns={[
                  { title: '商品', key: 'p', render: (_, r) => <ProductCell image={r.image_url} title={r.sku} sub={r.name} size={48} /> },
                  { title: '可识别条码', dataIndex: 'codes', render: (v: string[]) => <Space size={4} wrap>{v.map((c) => <Tag key={c}>{c}</Tag>)}</Space> },
                  { title: '应发', dataIndex: 'qty', align: 'right', render: (v) => <Typography.Text strong style={{ fontSize: 18 }}>{v}</Typography.Text> },
                  {
                    title: '已扫', key: 'scanned', align: 'right',
                    render: (_, r) => {
                      const n = scanned[r.product_id] ?? 0
                      return <Typography.Text strong style={{ fontSize: 18, color: n >= r.qty ? '#389e0d' : n > 0 ? '#fa8c16' : undefined }}>{n}</Typography.Text>
                    },
                  },
                ]}
              />
              {!blocked && (
                <Row gutter={12} align="bottom">
                  <Col span={9}>
                    <div style={{ marginBottom: 4 }}>运单号</div>
                    <Input ref={trackingRef} size="large" value={tracking} onChange={(e) => setTracking(e.target.value)} onPressEnter={ship} placeholder="扫描面单运单号，回车发货" />
                  </Col>
                  <Col span={5}>
                    <div style={{ marginBottom: 4 }}>物流商</div>
                    <Input size="large" value={carrier} onChange={(e) => setCarrier(e.target.value)} placeholder="如 USPS" />
                  </Col>
                  <Col span={5}>
                    <div style={{ marginBottom: 4 }}>实际运费（{cur}）</div>
                    <InputNumber size="large" min={0} value={freight} onChange={(v) => setFreight(v)} placeholder="默认预估" style={{ width: '100%' }} />
                  </Col>
                  <Col span={5}>
                    <Button type="primary" size="large" block loading={loading} disabled={!skipVerify && !verified} onClick={ship}>确认发货</Button>
                  </Col>
                </Row>
              )}
            </Space>
          )}
        </Card>
      </Col>
      <Col xs={24} xl={7}>
        <Card variant="borderless" title={`本次已发货（${history.length}）`}>
          {!history.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无" />}
          {history.map((h) => (
            <div key={h.order_no} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
              <div>
                <div style={{ fontWeight: 500 }}>{h.platform_order_id}</div>
                <div style={{ color: '#888', fontSize: 12 }}>{h.order_no} · {h.tracking_no ?? '无运单号'}</div>
              </div>
              <span style={{ color: '#888', fontSize: 12 }}>{h.at}</span>
            </div>
          ))}
        </Card>
      </Col>
    </Row>
  )
}
