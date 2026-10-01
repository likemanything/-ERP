import { useState } from 'react'
import { App, Button, Card, Col, Form, Input, InputNumber, Row, Select, Space, Table, Tabs } from 'antd'
import { CalculatorOutlined, PlusOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { api, errorMessage } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import Perm from '@/components/Perm'
import { CurrencySelect, ProviderSelect } from '@/components/selects'
import { useBaseCurrency } from '@/store/auth'
import { BILLING_TYPE, CHANNEL_USAGE, PROVIDER_TYPE, TRANSPORT_MODE, dictLabel, dictOptions } from '@/utils/dicts'
import { fmtMoney } from '@/utils/format'

type R = Record<string, any>

function Providers() {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<R | null>(null)
  const reload = useReload('providers')
  const qc = useQueryClient()
  const run = useAction()
  const done = () => { reload(); qc.invalidateQueries({ queryKey: ['options'] }) }
  return (
    <>
      <DataTable<R> queryKey="providers" url="/logistics-providers" card={false}
        filters={[{ name: 'keyword', placeholder: '编码 / 名称' }]}
        toolbar={() => <Perm code="logistics:edit"><Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true) }}>新增物流商</Button></Perm>}
        columns={[
          { title: '编码', dataIndex: 'code' }, { title: '名称', dataIndex: 'name' },
          { title: '类型', dataIndex: 'provider_type', render: (v) => dictLabel(PROVIDER_TYPE, v) },
          { title: '联系人', dataIndex: 'contact', render: (v, r) => `${v ?? '-'} ${r.phone ?? ''}` },
          { title: '状态', dataIndex: 'status', render: (v) => (v === 'active' ? '启用' : '停用') },
          { title: '操作', key: 'op', render: (_, r) => (
            <Perm code="logistics:edit"><Space>
              <a onClick={() => { setEditing(r); setOpen(true) }}>编辑</a>
              <a onClick={() => run(() => api.del(`/logistics-providers/${r.id}`), { confirm: '删除物流商？', onDone: done })}>删除</a>
            </Space></Perm>
          ) },
        ]} />
      <FormModal open={open} title={editing ? '编辑物流商' : '新增物流商'} width={520} onCancel={() => setOpen(false)}
        initialValues={editing ?? { provider_type: 'forwarder', status: 'active' }}
        onSubmit={async (v) => { if (editing) await api.put(`/logistics-providers/${editing.id}`, v); else await api.post('/logistics-providers', v); done() }}>
        <Row gutter={12}>
          <Col span={12}><Form.Item name="code" label="编码" rules={[{ required: true }]}><Input /></Form.Item></Col>
          <Col span={12}><Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
          <Col span={12}><Form.Item name="provider_type" label="类型"><Select options={dictOptions(PROVIDER_TYPE)} /></Form.Item></Col>
          <Col span={12}><Form.Item name="status" label="状态"><Select options={[{ value: 'active', label: '启用' }, { value: 'disabled', label: '停用' }]} /></Form.Item></Col>
          <Col span={12}><Form.Item name="contact" label="联系人"><Input /></Form.Item></Col>
          <Col span={12}><Form.Item name="phone" label="电话"><Input /></Form.Item></Col>
          <Col span={24}><Form.Item name="website" label="官网/查询地址"><Input /></Form.Item></Col>
        </Row>
      </FormModal>
    </>
  )
}

function Channels() {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<R | null>(null)
  const reload = useReload('channels')
  const qc = useQueryClient()
  const run = useAction()
  const done = () => { reload(); qc.invalidateQueries({ queryKey: ['options'] }) }
  const pricing = (r: R) => {
    if (r.billing_type === 'piece') return `${fmtMoney(r.unit_price, r.currency)}/件`
    if (r.billing_type === 'volume') return `${fmtMoney(r.unit_price, r.currency)}/m³`
    if (r.first_weight_kg && r.extra_unit_kg) return `首重 ${r.first_weight_kg}kg ${fmtMoney(r.first_price, r.currency)}，续重每 ${r.extra_unit_kg}kg ${fmtMoney(r.extra_price, r.currency)}`
    return `${fmtMoney(r.unit_price, r.currency)}/kg`
  }
  return (
    <>
      <DataTable<R> queryKey="channels" url="/logistics-channels" card={false}
        filters={[
          { name: 'keyword', placeholder: '编码 / 名称' },
          { name: 'usage', type: 'select', label: '用途', options: dictOptions(CHANNEL_USAGE) },
          { name: 'transport_mode', type: 'select', label: '方式', options: dictOptions(TRANSPORT_MODE) },
        ]}
        toolbar={() => <Perm code="logistics:edit"><Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true) }}>新增渠道</Button></Perm>}
        columns={[
          { title: '编码', dataIndex: 'code' }, { title: '渠道名称', dataIndex: 'name' },
          { title: '用途', dataIndex: 'usage', render: (v) => dictLabel(CHANNEL_USAGE, v) },
          { title: '运输方式', dataIndex: 'transport_mode', render: (v) => dictLabel(TRANSPORT_MODE, v) },
          { title: '计费规则', key: 'p', render: (_, r) => pricing(r) },
          { title: '材积除数', dataIndex: 'volume_divisor' },
          { title: '时效(天)', dataIndex: 'transit_days' },
          { title: '操作', key: 'op', render: (_, r) => (
            <Perm code="logistics:edit"><Space>
              <a onClick={() => { setEditing(r); setOpen(true) }}>编辑</a>
              <a onClick={() => run(() => api.del(`/logistics-channels/${r.id}`), { confirm: '删除渠道？', onDone: done })}>删除</a>
            </Space></Perm>
          ) },
        ]} />
      <FormModal open={open} title={editing ? '编辑渠道' : '新增渠道'} width={760} onCancel={() => setOpen(false)}
        initialValues={editing ?? { usage: 'first_mile', transport_mode: 'air', billing_type: 'weight', currency: 'CNY', volume_divisor: 6000, transit_days: 10, status: 'active' }}
        onSubmit={async (v) => { if (editing) await api.put(`/logistics-channels/${editing.id}`, v); else await api.post('/logistics-channels', v); done() }}>
        <Row gutter={12}>
          <Col span={8}><Form.Item name="provider_id" label="物流商" rules={[{ required: true }]}><ProviderSelect /></Form.Item></Col>
          <Col span={8}><Form.Item name="code" label="渠道编码" rules={[{ required: true }]}><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="name" label="渠道名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="usage" label="用途"><Select options={dictOptions(CHANNEL_USAGE)} /></Form.Item></Col>
          <Col span={8}><Form.Item name="transport_mode" label="运输方式"><Select options={dictOptions(TRANSPORT_MODE)} /></Form.Item></Col>
          <Col span={8}><Form.Item name="billing_type" label="计费方式"><Select options={dictOptions(BILLING_TYPE)} /></Form.Item></Col>
          <Col span={6}><Form.Item name="currency" label="币种"><CurrencySelect /></Form.Item></Col>
          <Col span={6}><Form.Item name="unit_price" label="单价（/kg、/m³、/件）"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={6}><Form.Item name="volume_divisor" label="材积除数"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={6}><Form.Item name="transit_days" label="时效（天）"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={6}><Form.Item name="first_weight_kg" label="首重 kg"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={6}><Form.Item name="first_price" label="首重价"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={6}><Form.Item name="extra_unit_kg" label="续重单位 kg"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={6}><Form.Item name="extra_price" label="续重价"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={8}><Form.Item name="min_charge" label="最低收费"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={8}><Form.Item name="surcharge" label="每票附加费"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
        </Row>
      </FormModal>
    </>
  )
}

function Quote() {
  const [rows, setRows] = useState<R[]>([])
  const [loading, setLoading] = useState(false)
  const { message } = App.useApp()
  const cur = useBaseCurrency()
  const onFinish = async (v: R) => {
    setLoading(true)
    try {
      setRows(await api.post('/logistics/quote', v))
    } catch (e) {
      message.error(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }
  return (
    <Row gutter={16}>
      <Col xs={24} lg={8}>
        <Card size="small" title="货物信息">
          <Form layout="vertical" onFinish={onFinish} initialValues={{ weight_kg: 10, length_cm: 50, width_cm: 40, height_cm: 30, pieces: 1 }}>
            <Form.Item name="weight_kg" label="实重 kg" rules={[{ required: true }]}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
            <Space.Compact block>
              <Form.Item name="length_cm" label="长 cm"><InputNumber min={0} /></Form.Item>
              <Form.Item name="width_cm" label="宽 cm"><InputNumber min={0} /></Form.Item>
              <Form.Item name="height_cm" label="高 cm"><InputNumber min={0} /></Form.Item>
            </Space.Compact>
            <Form.Item name="volume_cbm" label="或直接填写总体积 m³（多箱）"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="pieces" label="件数"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
            <Button type="primary" htmlType="submit" block icon={<CalculatorOutlined />} loading={loading}>多渠道比价</Button>
          </Form>
        </Card>
      </Col>
      <Col xs={24} lg={16}>
        <Table<R> rowKey="channel_id" dataSource={rows} pagination={false} columns={[
          { title: '渠道', dataIndex: 'channel_name', render: (v, r) => `${v}（${r.provider_name ?? '-'}）` },
          { title: '方式', dataIndex: 'transport_mode', render: (v) => dictLabel(TRANSPORT_MODE, v) },
          { title: '计费重 kg', dataIndex: 'chargeable_weight_kg' },
          { title: '运费', dataIndex: 'freight', render: (v, r) => fmtMoney(v, r.currency) },
          { title: `折合${cur}`, dataIndex: 'freight_base', render: (v, _r, i) => <b style={{ color: i === 0 ? '#389e0d' : undefined }}>{fmtMoney(v, cur)}</b> },
          { title: '时效', dataIndex: 'transit_days', render: (v) => `${v} 天` },
        ]} />
      </Col>
    </Row>
  )
}

export default function Logistics() {
  return (
    <div style={{ background: '#fff', padding: '0 24px 24px', borderRadius: 8 }}>
      <Tabs items={[
        { key: 'channels', label: '物流渠道', children: <Channels /> },
        { key: 'providers', label: '物流商', children: <Providers /> },
        { key: 'quote', label: '运费试算', children: <Quote /> },
      ]} />
    </div>
  )
}
