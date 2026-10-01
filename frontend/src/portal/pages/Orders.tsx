import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Alert, App, Button, Card, DatePicker, Descriptions, Drawer, Input, Modal, Space, Table, Tabs, Tag, Typography, Upload } from 'antd'
import { ImportOutlined, InboxOutlined, PlusOutlined } from '@ant-design/icons'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import type { Dayjs } from 'dayjs'
import { api, cleanParams, download, errorMessage, type Page } from '@/api/client'
import { fmtDateTime, fmtMoney } from '@/utils/format'
import { STATUS_COLOR, type PortalOrder } from '../api'
import { tStatus, useT, type T } from '../i18n'

const TABS = ['', 'to_audit', 'to_ship', 'shipped,delivered', 'cancelled']

function ChargeTable({ o, t }: { o: PortalOrder; t: T }) {
  const c = o.charge_detail ?? {}
  const rows: [string, number][] = [
    [t('goods'), Number(c.goods ?? 0)],
    [t('freight'), Number(c.freight ?? 0)],
    [t('handling'), Number(c.handling ?? 0)],
  ]
  if (Number(c.adjust ?? 0)) rows.push([t('adjust'), Number(c.adjust)])
  rows.push([t('total'), Number(c.total ?? 0)])
  if (Number(c.refunded ?? 0)) rows.push([t('refunded'), -Number(c.refunded)])
  return (
    <Descriptions size="small" column={1} bordered>
      {rows.map(([k, v]) => (
        <Descriptions.Item key={k} label={k}>
          <span style={{ fontWeight: k === t('total') ? 600 : undefined }}>{fmtMoney(v, o.currency)}</span>
        </Descriptions.Item>
      ))}
    </Descriptions>
  )
}

function ImportOrders({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const t = useT()
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<{ created: number; skipped: number; errors: string[] } | null>(null)
  const close = () => { setResult(null); onClose() }
  return (
    <Modal open={open} title={t('importTitle')} onCancel={close} footer={<Button onClick={close}>{t('close')}</Button>} width={640} destroyOnHidden>
      <Space orientation="vertical" style={{ width: '100%' }}>
        <Alert type="info" title={t('importHint')} />
        <Typography.Link onClick={() => download('/portal/orders/import-template').catch((e) => message.error(errorMessage(e)))}>{t('downloadTemplate')}</Typography.Link>
        <Upload.Dragger
          accept=".xlsx"
          showUploadList={false}
          disabled={loading}
          customRequest={async ({ file }) => {
            setLoading(true)
            try {
              const r = await api.upload<{ created: number; skipped: number; errors: string[] }>('/portal/orders/import', file as File)
              setResult(r)
              onDone()
            } catch (e) {
              message.error(errorMessage(e))
            } finally {
              setLoading(false)
            }
          }}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p>{loading ? t('importing') : t('uploadHint')}</p>
        </Upload.Dragger>
        {result && (
          <Alert
            type={result.errors.length ? 'warning' : 'success'}
            title={t('importResult', { ok: result.created, fail: result.skipped })}
            description={result.errors.length > 0 && <div style={{ maxHeight: 220, overflow: 'auto' }}>{result.errors.map((e, i) => <div key={i}>{e}</div>)}</div>}
          />
        )}
      </Space>
    </Modal>
  )
}

export default function PortalOrders() {
  const t = useT()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { message, modal } = App.useApp()
  const [search, setSearch] = useSearchParams()
  const [status, setStatus] = useState(search.get('status') ?? '')
  const [keyword, setKeyword] = useState<string>()
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [detail, setDetail] = useState<PortalOrder | null>(null)
  const importOpen = search.get('import') === '1'

  const params = cleanParams({
    status,
    keyword,
    date_from: range?.[0]?.format('YYYY-MM-DD'),
    date_to: range?.[1]?.format('YYYY-MM-DD'),
    page,
    page_size: pageSize,
  })
  const { data, isFetching } = useQuery({
    queryKey: ['portal-orders', params],
    queryFn: () => api.get<Page<PortalOrder>>('/portal/orders', params),
    placeholderData: keepPreviousData,
  })
  const reload = () => {
    qc.invalidateQueries({ queryKey: ['portal-orders'] })
    qc.invalidateQueries({ queryKey: ['portal-me'] })
    qc.invalidateQueries({ queryKey: ['portal-dashboard'] })
  }

  const cancel = (o: PortalOrder) =>
    modal.confirm({
      title: `${t('cancel')} ${o.reference_no}`,
      content: t('confirmCancel'),
      okButtonProps: { danger: true },
      okText: t('ok'),
      cancelText: t('cancelBtn'),
      onOk: async () => {
        try {
          const r = await api.post<PortalOrder>(`/portal/orders/${o.id}/cancel`)
          message.success(t('cancelled'))
          if (detail?.id === o.id) setDetail(r)
          reload()
        } catch (e) {
          message.error(errorMessage(e))
        }
      },
    })

  return (
    <Card variant="borderless">
      <Tabs
        activeKey={status}
        onChange={(k) => { setStatus(k); setPage(1) }}
        items={TABS.map((s) => ({ key: s, label: s ? tStatus(t, 'status', s.split(',')[0]) : t('all') }))}
      />
      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <Space wrap>
          <Input.Search allowClear placeholder={`${t('referenceNo')} / ${t('recipient')} / ${t('tracking')}`} style={{ width: 300 }}
            onSearch={(v) => { setKeyword(v || undefined); setPage(1) }} enterButton={t('search')} />
          <DatePicker.RangePicker value={range} onChange={(v) => { setRange(v); setPage(1) }} />
        </Space>
        <Space>
          <Button icon={<ImportOutlined />} onClick={() => setSearch({ import: '1' })}>{t('importOrders')}</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/portal/catalog')}>{t('newOrder')}</Button>
        </Space>
      </div>
      <Table<PortalOrder>
        rowKey="id"
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
            title: t('referenceNo'),
            dataIndex: 'reference_no',
            render: (v, r) => (
              <div>
                <a onClick={() => setDetail(r)}>{v}</a>
                <div style={{ fontSize: 12, color: '#999' }}>{r.order_no}</div>
              </div>
            ),
          },
          { title: t('orderType'), dataIndex: 'distribution_type', render: (v) => <Tag color={v === 'wholesale' ? 'purple' : 'blue'}>{v === 'wholesale' ? t('wholesale') : t('dropship')}</Tag> },
          { title: t('createdAt'), dataIndex: 'created_at', render: (v) => fmtDateTime(v) },
          {
            title: t('lines'),
            key: 'items',
            render: (_, r) => (
              <div style={{ fontSize: 12 }}>
                {r.items.slice(0, 3).map((i, idx) => <div key={idx}>{i.sku} × {i.quantity}</div>)}
                {r.items.length > 3 && <div style={{ color: '#999' }}>…</div>}
              </div>
            ),
          },
          { title: t('recipient'), key: 'to', render: (_, r) => <div>{r.ship_name}<div style={{ fontSize: 12, color: '#999' }}>{[r.ship_country, r.ship_city].filter(Boolean).join(' / ')}</div></div> },
          { title: t('amount'), key: 'amt', align: 'right', render: (_, r) => fmtMoney(Number(r.charge_detail?.total ?? 0), r.currency) },
          {
            title: t('status'),
            dataIndex: 'status',
            render: (v, r) => (
              <div>
                <Tag color={STATUS_COLOR[v]}>{tStatus(t, 'status', v)}</Tag>
                {r.note && <div style={{ fontSize: 12, color: '#999', maxWidth: 160 }}>{r.note}</div>}
              </div>
            ),
          },
          {
            title: t('tracking'),
            key: 'track',
            render: (_, r) => (r.tracking_no ? <div><Typography.Text copyable>{r.tracking_no}</Typography.Text><div style={{ fontSize: 12, color: '#999' }}>{r.carrier ?? r.channel_name}</div></div> : r.channel_name ?? '-'),
          },
          {
            title: t('actions'),
            key: 'op',
            fixed: 'right',
            render: (_, r) => (
              <Space>
                <a onClick={() => setDetail(r)}>{t('detail')}</a>
                {r.can_cancel && <a style={{ color: '#cf1322' }} onClick={() => cancel(r)}>{t('cancel')}</a>}
              </Space>
            ),
          },
        ]}
      />
      <Drawer open={!!detail} onClose={() => setDetail(null)} size={720} title={detail?.reference_no} destroyOnHidden
        extra={detail?.can_cancel && <Button danger onClick={() => cancel(detail)}>{t('cancel')}</Button>}>
        {detail && (
          <Space orientation="vertical" size="large" style={{ width: '100%' }}>
            <Descriptions size="small" bordered column={2}>
              <Descriptions.Item label={t('orderNo')}>{detail.order_no}</Descriptions.Item>
              <Descriptions.Item label={t('status')}><Tag color={STATUS_COLOR[detail.status]}>{tStatus(t, 'status', detail.status)}</Tag></Descriptions.Item>
              <Descriptions.Item label={t('orderType')}>{detail.distribution_type === 'wholesale' ? t('wholesale') : t('dropship')}</Descriptions.Item>
              <Descriptions.Item label={t('createdAt')}>{fmtDateTime(detail.created_at)}</Descriptions.Item>
              <Descriptions.Item label={t('channel')}>{detail.channel_name ?? '-'}</Descriptions.Item>
              <Descriptions.Item label={t('shippedAt')}>{fmtDateTime(detail.shipped_at)}</Descriptions.Item>
              <Descriptions.Item label={t('tracking')} span={2}>{detail.tracking_no ? <Typography.Text copyable>{detail.tracking_no}</Typography.Text> : '-'} {detail.carrier}</Descriptions.Item>
              <Descriptions.Item label={t('shipTo')} span={2}>
                {detail.ship_name} {detail.ship_phone}
                <br />
                {[detail.ship_address1, detail.ship_address2, detail.ship_city, detail.ship_state, detail.ship_postcode, detail.ship_country].filter(Boolean).join(', ')}
              </Descriptions.Item>
              {detail.note && <Descriptions.Item label={t('note')} span={2}>{detail.note}</Descriptions.Item>}
            </Descriptions>
            <Table
              size="small"
              rowKey="key"
              pagination={false}
              title={() => t('lines')}
              dataSource={detail.items.map((it, i) => ({ ...it, key: i }))}
              columns={[
                { title: 'SKU', dataIndex: 'sku' },
                { title: t('product'), dataIndex: 'title' },
                { title: t('qty'), dataIndex: 'quantity', align: 'right' },
                { title: t('price'), dataIndex: 'unit_price', align: 'right', render: (v) => fmtMoney(v, detail.currency) },
                { title: t('amount'), dataIndex: 'item_amount', align: 'right', render: (v) => fmtMoney(v, detail.currency) },
              ]}
            />
            <div>
              <Typography.Title level={5}>{t('charges')}</Typography.Title>
              <ChargeTable o={detail} t={t} />
            </div>
          </Space>
        )}
      </Drawer>
      <ImportOrders open={importOpen} onClose={() => setSearch({})} onDone={reload} />
    </Card>
  )
}
