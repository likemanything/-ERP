import { App, Button, Card, Descriptions, Space, Table, Tag, Typography } from 'antd'
import { useQueryClient } from '@tanstack/react-query'
import { api, errorMessage } from '@/api/client'
import { usePortalMe } from '../api'
import { useT, type TKey } from '../i18n'

const ENDPOINTS: [string, string, TKey][] = [
  ['GET', '/catalog?page=1&page_size=100', 'ep_catalog'],
  ['GET', '/channels', 'ep_channels'],
  ['POST', '/quote', 'ep_quote'],
  ['POST', '/orders', 'ep_create'],
  ['GET', '/orders?keyword=&status=shipped', 'ep_orders'],
  ['GET', '/orders/{id}', 'ep_order'],
  ['POST', '/orders/{id}/cancel', 'ep_cancel'],
  ['GET', '/me', 'ep_me'],
  ['GET', '/transactions', 'ep_txn'],
]

const ORDER_EXAMPLE = `{
  "reference_no": "MY-ORDER-10001",
  "order_type": "dropship",
  "channel_id": 1,
  "items": [{ "sku": "SKU-001", "qty": 2 }],
  "address": {
    "name": "John Smith", "phone": "1-555-0100",
    "country": "US", "state": "CA", "city": "Los Angeles",
    "address1": "123 Main St", "postcode": "90001"
  }
}`

export default function PortalApi() {
  const t = useT()
  const qc = useQueryClient()
  const { message, modal } = App.useApp()
  const { data: me } = usePortalMe()
  const enabled = !!me?.distributor.has_api_key
  const base = `${window.location.origin}/api/v1/portal`

  const generate = () =>
    modal.confirm({
      title: enabled ? t('resetKey') : t('generateKey'),
      content: enabled ? t('confirmReset') : undefined,
      okText: t('ok'),
      cancelText: t('cancelBtn'),
      onOk: async () => {
        try {
          const r = await api.post<{ api_key: string }>('/portal/api-key')
          qc.invalidateQueries({ queryKey: ['portal-me'] })
          modal.success({
            title: t('generateKey'),
            width: 560,
            okText: t('ok'),
            content: (
              <div>
                <p>{t('keyOnce')}</p>
                <Typography.Paragraph copyable={{ text: r.api_key }} code style={{ wordBreak: 'break-all' }}>{r.api_key}</Typography.Paragraph>
              </div>
            ),
          })
        } catch (e) {
          message.error(errorMessage(e))
        }
      },
    })

  const revoke = () =>
    modal.confirm({
      title: t('revokeKey'),
      content: t('confirmRevoke'),
      okButtonProps: { danger: true },
      okText: t('ok'),
      cancelText: t('cancelBtn'),
      onOk: async () => {
        try {
          await api.del('/portal/api-key')
          qc.invalidateQueries({ queryKey: ['portal-me'] })
        } catch (e) {
          message.error(errorMessage(e))
        }
      },
    })

  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      <Card variant="borderless" title={t('apiTitle')}>
        <Typography.Paragraph type="secondary">{t('apiDesc')}</Typography.Paragraph>
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label={t('apiKeyStatus')}>
            <Space>
              {enabled ? <Tag color="green">{t('enabled')}</Tag> : <Tag>{t('notEnabled')}</Tag>}
              <Button type="primary" size="small" onClick={generate}>{enabled ? t('resetKey') : t('generateKey')}</Button>
              {enabled && <Button danger size="small" onClick={revoke}>{t('revokeKey')}</Button>}
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label={t('baseUrl')}><Typography.Text copyable code>{base}</Typography.Text></Descriptions.Item>
          <Descriptions.Item label={t('authHeader')}><Typography.Text code>X-Api-Key: dk_xxxxxxxx</Typography.Text></Descriptions.Item>
        </Descriptions>
      </Card>
      <Card variant="borderless" title={t('endpoints')}>
        <Table
          size="small"
          rowKey={(r) => r[0] + r[1]}
          pagination={false}
          dataSource={ENDPOINTS}
          columns={[
            { title: 'Method', key: 'm', width: 90, render: (_, r) => <Tag color={r[0] === 'GET' ? 'blue' : 'green'}>{r[0]}</Tag> },
            { title: 'Path', key: 'p', render: (_, r) => <Typography.Text code>{r[1]}</Typography.Text> },
            { title: '', key: 'd', render: (_, r) => t(r[2]) },
          ]}
        />
        <Typography.Title level={5} style={{ marginTop: 24 }}>{t('example')} · {t('ep_create')}</Typography.Title>
        <pre style={{ background: '#f6f8fa', padding: 16, borderRadius: 6, overflow: 'auto', fontSize: 12 }}>
{`curl -X POST '${base}/orders' \\
  -H 'X-Api-Key: dk_xxxxxxxx' \\
  -H 'Content-Type: application/json' \\
  -d '${ORDER_EXAMPLE}'`}
        </pre>
        <Typography.Paragraph type="secondary">{t('swaggerHint')}</Typography.Paragraph>
      </Card>
    </Space>
  )
}
