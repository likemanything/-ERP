import { useState } from 'react'
import { Alert, Button, Checkbox, Col, Form, Input, InputNumber, Popover, Row, Select, Space, Switch, Tag, Tooltip } from 'antd'
import { ApiOutlined, PlusOutlined, SyncOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import Perm from '@/components/Perm'
import StatusTag from '@/components/StatusTag'
import { UserSelect } from '@/components/selects'
import { useMarketplaces } from '@/hooks/useOptions'
import { PLATFORM, SHOP_STATUS, SYNC_JOB_TYPE, dictOptions } from '@/utils/dicts'
import { fmtDateTime } from '@/utils/format'

type Shop = Record<string, any>

const CAPABILITY_LABEL: Record<string, string> = {
  orders: '订单', listings: 'Listing', fba_inventory: '平台仓库存', finances: '结算明细', ads: '广告数据',
}

interface PlatformCap {
  platform: string
  capabilities: string[]
  credential_fields: { key: string; label: string; secret: boolean }[]
}

function ShopForm({ editing }: { editing: Shop | null }) {
  const form = Form.useFormInstance()
  const platform = Form.useWatch('platform', form) ?? editing?.platform
  const demo = Form.useWatch('demo', form)
  const { data: mps } = useMarketplaces(platform)
  const { data: caps } = useQuery({ queryKey: ['platform-caps'], queryFn: () => api.get<PlatformCap[]>('/integrations/platforms') })
  const cap = caps?.find((c) => c.platform === platform)
  return (
    <>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select options={dictOptions(PLATFORM)} disabled={!!editing} onChange={() => form.setFieldValue('marketplace_code', undefined)} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="marketplace_code" label="站点">
            <Select allowClear options={(mps ?? []).map((m) => ({ value: m.code, label: `${m.name}（${m.currency}）` }))} showSearch={{ optionFilterProp: 'label' }} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="name" label="店铺名称" rules={[{ required: true }]}>
            <Input placeholder="如：Amazon-US-品牌A" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="seller_id" label="卖家 ID / Merchant Token">
            <Input />
          </Form.Item>
        </Col>
        {platform === 'shopify' && (
          <Col span={24}>
            <Form.Item name="store_domain" label="店铺域名" rules={[{ required: true }]}>
              <Input placeholder="your-store.myshopify.com" />
            </Form.Item>
          </Col>
        )}
        <Col span={12}>
          <Form.Item name="manager_id" label="负责人">
            <UserSelect />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="status" label="状态">
            <Select options={dictOptions(SHOP_STATUS)} />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item label="API 授权">
        <Form.Item name="demo" valuePropName="checked" noStyle>
          <Checkbox>演示模式（无需真实授权，自动生成模拟数据）</Checkbox>
        </Form.Item>
      </Form.Item>
      {!demo && cap && (
        <>
          <div style={{ margin: '-8px 0 12px', color: '#888', fontSize: 12 }}>
            支持同步：{Object.keys(CAPABILITY_LABEL).filter((c) => cap.capabilities.includes(c)).map((c) => CAPABILITY_LABEL[c]).join('、')}
            {cap.capabilities.includes('ads') && cap.platform === 'amazon' && '（广告数据需填写广告 Refresh Token）'}
          </div>
          {editing?.has_credentials && (
            <Alert type="info" showIcon style={{ marginBottom: 12 }} title={`已保存授权字段：${editing.credential_keys.join(', ')}。留空表示不修改。`} />
          )}
          <Row gutter={16}>
            {cap.credential_fields.map((f) => (
              <Col span={12} key={f.key}>
                <Form.Item name={['credentials', f.key]} label={f.label}>
                  {f.secret ? <Input.Password autoComplete="new-password" /> : <Input />}
                </Form.Item>
              </Col>
            ))}
          </Row>
        </>
      )}
      {!demo && platform && !cap && (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }} title="该平台暂未接入 API，可通过 Excel 导入订单、Listing 与库存数据。" />
      )}
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="sync_enabled" label="自动同步" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="sync_interval_minutes" label="同步间隔（分钟）">
            <InputNumber min={10} max={1440} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="remark" label="备注">
        <Input.TextArea rows={2} />
      </Form.Item>
    </>
  )
}

function SyncButton({ shop, onDone }: { shop: Shop; onDone: () => void }) {
  const run = useAction()
  const [types, setTypes] = useState<string[]>([])
  const content = (
    <Space orientation="vertical">
      <Checkbox.Group options={dictOptions(SYNC_JOB_TYPE)} value={types} onChange={(v) => setTypes(v as string[])} />
      <span style={{ fontSize: 12, color: '#888' }}>不勾选表示同步全部类型</span>
      <Button
        type="primary"
        size="small"
        onClick={() =>
          run(() => api.post(`/shops/${shop.id}/sync`, { job_types: types.length ? types : null, background: true }), {
            success: '已提交后台同步，可在「同步记录」查看进度',
            onDone,
          })
        }
      >
        开始同步
      </Button>
    </Space>
  )
  return (
    <Popover content={content} title={`同步 ${shop.name}`} trigger="click">
      <Button size="small" icon={<SyncOutlined />}>同步</Button>
    </Popover>
  )
}

export default function Shops() {
  const [editing, setEditing] = useState<Shop | null>(null)
  const [open, setOpen] = useState(false)
  const reload = useReload('shops')
  const qc = useQueryClient()
  const run = useAction()

  const save = async (v: Record<string, any>) => {
    const { demo, ...rest } = v
    let credentials: Record<string, string> | undefined
    if (demo) credentials = { mode: 'demo' }
    else if (rest.credentials) {
      credentials = Object.fromEntries(Object.entries(rest.credentials).filter(([, val]) => val)) as Record<string, string>
      if (editing?.credential_keys?.includes('mode')) credentials.mode = ''
      if (!Object.keys(credentials).length) credentials = undefined
    }
    const body = { ...rest, credentials }
    if (editing) await api.put(`/shops/${editing.id}`, body)
    else await api.post('/shops', body)
    reload()
    qc.invalidateQueries({ queryKey: ['options'] })
  }

  return (
    <>
      <DataTable<Shop>
        queryKey="shops"
        url="/shops"
        filters={[
          { name: 'keyword', placeholder: '店铺名称 / 卖家ID' },
          { name: 'platform', type: 'select', label: '平台', options: dictOptions(PLATFORM) },
          { name: 'status', type: 'select', label: '状态', options: dictOptions(SHOP_STATUS) },
        ]}
        toolbar={() => (
          <Perm code="shop:edit">
            <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true) }}>
              添加店铺
            </Button>
          </Perm>
        )}
        columns={[
          { title: '店铺', dataIndex: 'name', render: (v, r) => <Space><b>{v}</b>{r.credential_keys?.includes('mode') && <Tag color="purple">演示</Tag>}</Space> },
          { title: '平台', dataIndex: 'platform', render: (v) => <StatusTag dict={PLATFORM} value={v} /> },
          { title: '站点', dataIndex: 'marketplace_code', render: (v, r) => (v ? `${r.country ?? ''} ${v}` : '-') },
          { title: '币种', dataIndex: 'currency' },
          { title: '状态', dataIndex: 'status', render: (v) => <StatusTag dict={SHOP_STATUS} value={v} /> },
          { title: '授权', dataIndex: 'has_credentials', render: (v) => (v ? <Tag color="green">已授权</Tag> : <Tag>未授权</Tag>) },
          { title: '自动同步', dataIndex: 'sync_enabled', render: (v, r) => (v ? `每 ${r.sync_interval_minutes} 分钟` : '关闭') },
          {
            title: '最近同步', dataIndex: 'last_sync_at',
            render: (v, r) => (
              <Tooltip title={r.last_sync_message}>
                <span>{fmtDateTime(v)} {r.last_sync_status && <Tag color={r.last_sync_status === 'success' ? 'green' : 'red'}>{r.last_sync_status === 'success' ? '成功' : '失败'}</Tag>}</span>
              </Tooltip>
            ),
          },
          {
            title: '操作', key: 'op', fixed: 'right',
            render: (_, r) => (
              <Space>
                <Perm code="shop:sync"><SyncButton shop={r} onDone={reload} /></Perm>
                <Perm code="shop:edit">
                  <Button size="small" icon={<ApiOutlined />} onClick={() => run(() => api.post(`/shops/${r.id}/test-connection`), {
                    success: (res: any) => (res.ok ? '连接成功' : `连接失败：${res.message}`),
                  })}>测试</Button>
                  <Button size="small" onClick={() => { setEditing(r); setOpen(true) }}>编辑</Button>
                  <Button size="small" danger onClick={() => run(() => api.del(`/shops/${r.id}`), { confirm: `确定删除店铺「${r.name}」？`, danger: true, onDone: reload })}>删除</Button>
                </Perm>
              </Space>
            ),
          },
        ]}
      />
      <FormModal
        open={open}
        title={editing ? '编辑店铺' : '添加店铺'}
        width={720}
        onCancel={() => setOpen(false)}
        onSubmit={save}
        initialValues={
          editing
            ? { ...editing, demo: editing.credential_keys?.includes('mode'), credentials: {} }
            : { platform: 'amazon', status: 'active', sync_enabled: true, sync_interval_minutes: 60, demo: false }
        }
      >
        <ShopForm editing={editing} />
      </FormModal>
    </>
  )
}
