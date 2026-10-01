import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, App, Button, Card, Col, Drawer, Dropdown, Form, Input, InputNumber, Row, Select, Space, Statistic, Switch, Table, Tag, Typography } from 'antd'
import { DownOutlined, PlusOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import Perm from '@/components/Perm'
import StatusTag from '@/components/StatusTag'
import { CurrencySelect, LevelSelect, UserSelect } from '@/components/selects'
import { usePerm } from '@/store/auth'
import { DISTRIBUTOR_STATUS, dictOptions } from '@/utils/dicts'
import { fmtDateTime, fmtMoney } from '@/utils/format'

type D = Record<string, any>

interface Overview {
  distributors: number
  active: number
  pending_recharges: number
  to_audit: number
  balances: { currency: string; balance: number; credit: number; count: number }[]
  month_orders: { currency: string; orders: number; amount: number }[]
}

function OverviewCards() {
  const navigate = useNavigate()
  const { data } = useQuery({ queryKey: ['distributors', 'overview'], queryFn: () => api.get<Overview>('/distribution/overview') })
  return (
    <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
      <Col xs={12} md={4}><Card variant="borderless"><Statistic title="分销商（正常/全部）" value={data?.active ?? 0} suffix={`/ ${data?.distributors ?? 0}`} /></Card></Col>
      <Col xs={12} md={4}>
        <Card variant="borderless" hoverable onClick={() => navigate('/distribution/recharges')}>
          <Statistic title="待确认充值" value={data?.pending_recharges ?? 0} styles={{ content: { color: data?.pending_recharges ? '#fa8c16' : undefined } }} />
        </Card>
      </Col>
      <Col xs={12} md={4}>
        <Card variant="borderless" hoverable onClick={() => navigate('/distribution/orders')}>
          <Statistic title="待审核分销订单" value={data?.to_audit ?? 0} styles={{ content: { color: data?.to_audit ? '#fa8c16' : undefined } }} />
        </Card>
      </Col>
      <Col xs={24} md={6}>
        <Card variant="borderless">
          <div style={{ color: 'rgba(0,0,0,.45)', marginBottom: 8 }}>预存余额 / 授信</div>
          {(data?.balances ?? []).map((b) => (
            <div key={b.currency}>{fmtMoney(b.balance, b.currency)} <Typography.Text type="secondary">/ {fmtMoney(b.credit, b.currency)}（{b.count} 家）</Typography.Text></div>
          ))}
          {!data?.balances.length && '-'}
        </Card>
      </Col>
      <Col xs={24} md={6}>
        <Card variant="borderless">
          <div style={{ color: 'rgba(0,0,0,.45)', marginBottom: 8 }}>本月分销订单</div>
          {(data?.month_orders ?? []).map((m) => (
            <div key={m.currency}>{m.orders} 单 · {fmtMoney(m.amount, m.currency)}</div>
          ))}
          {!data?.month_orders.length && '-'}
        </Card>
      </Col>
    </Row>
  )
}

/** 分销商登录账号管理 */
function AccountsDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const run = useAction()
  const qc = useQueryClient()
  const [addOpen, setAddOpen] = useState(false)
  const [pwdUser, setPwdUser] = useState<D | null>(null)
  const [key, setKey] = useState<string | null>(null)
  const { data: d } = useQuery({
    queryKey: ['distributors', 'detail', id],
    queryFn: () => api.get<D>(`/distribution/distributors/${id}`),
    enabled: !!id,
  })
  const { data: users, isFetching } = useQuery({
    queryKey: ['distributor-users', id],
    queryFn: () => api.get<D[]>(`/distribution/distributors/${id}/users`),
    enabled: !!id,
  })
  const close = () => {
    setKey(null)
    onClose()
  }
  const reload = () => {
    qc.invalidateQueries({ queryKey: ['distributor-users'] })
    qc.invalidateQueries({ queryKey: ['distributors'] })
  }
  return (
    <Drawer open={!!id} onClose={close} size={720} title={`${d?.name ?? ''} · 门户账号与 API`} destroyOnHidden>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        title="分销商使用以下账号登录「分销商门户」（/portal/login）自助下单、充值、查看物流；无法访问 ERP 后台。"
      />
      <Space style={{ marginBottom: 12 }}>
        <Perm code="distribution:account">
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>开通登录账号</Button>
        </Perm>
      </Space>
      <Table<D>
        rowKey="id"
        size="small"
        loading={isFetching}
        pagination={false}
        dataSource={users ?? []}
        columns={[
          { title: '账号', dataIndex: 'username' },
          { title: '姓名', dataIndex: 'real_name' },
          { title: '状态', dataIndex: 'is_active', render: (v) => (v ? <Tag color="green">启用</Tag> : <Tag>禁用</Tag>) },
          { title: '最近登录', dataIndex: 'last_login_at', render: (v) => fmtDateTime(v) },
          {
            title: '操作', key: 'op',
            render: (_, u) => (
              <Perm code="distribution:account">
                <Space>
                  <a onClick={() => setPwdUser(u)}>重置密码</a>
                  <a onClick={() => run(() => api.put(`/distribution/distribution-users/${u.id}`, { is_active: !u.is_active }), { onDone: reload })}>
                    {u.is_active ? '禁用' : '启用'}
                  </a>
                </Space>
              </Perm>
            ),
          },
        ]}
      />
      <Typography.Title level={5} style={{ marginTop: 32 }}>API 对接</Typography.Title>
      <Space>
        {d?.has_api_key ? <Tag color="green">已启用 API Key</Tag> : <Tag>未启用</Tag>}
        <Perm code="distribution:account">
          <Button
            size="small"
            onClick={() =>
              run(() => api.post<{ api_key: string }>(`/distribution/distributors/${id}/api-key`), {
                confirm: d?.has_api_key ? '重新生成后旧 Key 立即失效，确认？' : '为该分销商生成 API Key？',
                success: '',
                onDone: (r) => {
                  reload()
                  setKey(r.api_key)
                },
              })
            }
          >
            {d?.has_api_key ? '重新生成' : '生成 API Key'}
          </Button>
          {d?.has_api_key && (
            <Button size="small" danger onClick={() => run(() => api.del(`/distribution/distributors/${id}/api-key`), { confirm: '停用后对接将立即失效，确认停用？', onDone: () => { setKey(null); reload() } })}>
              停用
            </Button>
          )}
        </Perm>
      </Space>
      {key && (
        <Alert
          style={{ marginTop: 12 }}
          type="warning"
          title="请立即复制并发送给分销商，该 Key 只显示一次"
          description={<Typography.Text copyable code style={{ wordBreak: 'break-all' }}>{key}</Typography.Text>}
        />
      )}
      <FormModal open={addOpen} title="开通门户登录账号" width={460} onCancel={() => setAddOpen(false)}
        onSubmit={async (v) => { await api.post(`/distribution/distributors/${id}/users`, v); reload() }}>
        <Form.Item name="username" label="登录账号" rules={[{ required: true, min: 3, pattern: /^[A-Za-z0-9_.@-]+$/, message: '3 位以上字母、数字或 _.@-' }]}><Input /></Form.Item>
        <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 6 }]}><Input.Password /></Form.Item>
        <Form.Item name="real_name" label="联系人姓名"><Input /></Form.Item>
      </FormModal>
      <FormModal open={!!pwdUser} title={`重置密码：${pwdUser?.username ?? ''}`} width={420} onCancel={() => setPwdUser(null)}
        onSubmit={async (v) => { await api.put(`/distribution/distribution-users/${pwdUser!.id}`, v); reload() }}>
        <Form.Item name="password" label="新密码" rules={[{ required: true, min: 6 }]}><Input.Password /></Form.Item>
      </FormModal>
    </Drawer>
  )
}

export default function Distributors() {
  const navigate = useNavigate()
  const can = usePerm()
  const qc = useQueryClient()
  const run = useAction()
  const reload = useReload('distributors')
  const [editing, setEditing] = useState<D | null>(null)
  const [open, setOpen] = useState(false)
  const [accounts, setAccounts] = useState<number | null>(null)
  const [fund, setFund] = useState<{ d: D; mode: 'recharge' | 'adjust' } | null>(null)
  const { message } = App.useApp()
  const done = () => { reload(); qc.invalidateQueries({ queryKey: ['options'] }) }

  return (
    <>
      <OverviewCards />
      <DataTable<D>
        queryKey="distributors"
        url="/distribution/distributors"
        filters={[
          { name: 'keyword', placeholder: '编码 / 名称 / 联系人 / 电话' },
          { name: 'status', type: 'select', label: '状态', options: dictOptions(DISTRIBUTOR_STATUS) },
          { name: 'level_id', label: '等级', type: 'custom', render: () => <LevelSelect style={{ width: 140 }} /> },
        ]}
        toolbar={() => (
          <Perm code="distribution:edit">
            <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true) }}>新增分销商</Button>
          </Perm>
        )}
        columns={[
          { title: '编码', dataIndex: 'code' },
          {
            title: '分销商', dataIndex: 'name',
            render: (v, r) => (
              <div>
                <div style={{ fontWeight: 600 }}>{v}</div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>{[r.contact, r.phone, r.country].filter(Boolean).join(' · ')}</Typography.Text>
              </div>
            ),
          },
          { title: '等级', dataIndex: 'level_name', render: (v) => (v ? <Tag color="purple">{v}</Tag> : '-') },
          {
            title: '业务', key: 'biz',
            render: (_, r) => (
              <Space size={4}>
                {r.allow_dropship && <Tag color="blue">代发</Tag>}
                {r.allow_wholesale && <Tag color="purple">批发</Tag>}
              </Space>
            ),
          },
          { title: '余额', dataIndex: 'balance', align: 'right', render: (v, r) => <span style={{ color: v < 0 ? '#cf1322' : undefined }}>{fmtMoney(v, r.currency)}</span> },
          { title: '授信额度', dataIndex: 'credit_limit', align: 'right', render: (v, r) => fmtMoney(v, r.currency) },
          { title: '可用额度', dataIndex: 'available_funds', align: 'right', render: (v, r) => <Typography.Text strong style={{ color: v > 0 ? '#389e0d' : '#cf1322' }}>{fmtMoney(v, r.currency)}</Typography.Text> },
          { title: '门户账号', dataIndex: 'user_count', align: 'center', render: (v, r) => <a onClick={() => setAccounts(r.id)}>{v} 个{r.has_api_key ? ' · API' : ''}</a> },
          { title: '状态', dataIndex: 'status', render: (v) => <StatusTag dict={DISTRIBUTOR_STATUS} value={v} /> },
          {
            title: '操作', key: 'op', fixed: 'right',
            render: (_, r) => (
              <Space>
                <Perm code="distribution:edit"><a onClick={() => { setEditing(r); setOpen(true) }}>编辑</a></Perm>
                <a onClick={() => setAccounts(r.id)}>账号</a>
                <Dropdown
                  menu={{
                    items: [
                      { key: 'recharge', label: '后台充值', disabled: !can('distribution:finance'), onClick: () => setFund({ d: r, mode: 'recharge' }) },
                      { key: 'adjust', label: '调整余额', disabled: !can('distribution:finance'), onClick: () => setFund({ d: r, mode: 'adjust' }) },
                      { type: 'divider' },
                      { key: 'txns', label: '资金流水', onClick: () => navigate(`/distribution/funds?distributor_id=${r.id}`) },
                      { key: 'orders', label: '分销订单', onClick: () => navigate(`/distribution/orders?distributor_id=${r.id}`) },
                      { type: 'divider' },
                      {
                        key: 'status', label: r.status === 'active' ? '停用' : '启用', danger: r.status === 'active', disabled: !can('distribution:edit'),
                        onClick: () => run(() => api.put(`/distribution/distributors/${r.id}`, { status: r.status === 'active' ? 'disabled' : 'active' }), {
                          confirm: r.status === 'active' ? `停用「${r.name}」后其门户账号与 API 将无法使用，确认？` : undefined,
                          onDone: done,
                        }),
                      },
                    ],
                  }}
                >
                  <a>更多 <DownOutlined /></a>
                </Dropdown>
              </Space>
            ),
          },
        ]}
      />
      <FormModal
        open={open}
        title={editing ? `编辑分销商：${editing.name}` : '新增分销商'}
        width={780}
        onCancel={() => setOpen(false)}
        initialValues={editing ?? { currency: 'USD', credit_limit: 0, status: 'active', allow_dropship: true, allow_wholesale: true }}
        onSubmit={async (v) => {
          if (editing) {
            const { username: _u, password: _p, code: _c, ...rest } = v as D
            if (!can('distribution:finance')) delete rest.credit_limit
            await api.put(`/distribution/distributors/${editing.id}`, rest)
          } else {
            await api.post('/distribution/distributors', v)
          }
          done()
        }}
      >
        <Row gutter={16}>
          <Col span={8}><Form.Item name="code" label="编码（为空自动生成）"><Input disabled={!!editing} /></Form.Item></Col>
          <Col span={16}><Form.Item name="name" label="分销商名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="contact" label="联系人"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="phone" label="电话"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="email" label="邮箱"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="country" label="国家/地区"><Input placeholder="如 US、CN" /></Form.Item></Col>
          <Col span={16}><Form.Item name="address" label="地址（批发默认收货地址）"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="level_id" label="分销等级"><LevelSelect /></Form.Item></Col>
          <Col span={8}><Form.Item name="currency" label="结算币种" extra={editing ? '产生资金流水后不可修改' : '分销价、余额均按此币种结算'}><CurrencySelect /></Form.Item></Col>
          <Col span={8}>
            <Form.Item name="credit_limit" label="授信额度" extra="允许欠款的最大额度">
              <InputNumber min={0} precision={2} style={{ width: '100%' }} disabled={!can('distribution:finance')} />
            </Form.Item>
          </Col>
          <Col span={8}><Form.Item name="allow_dropship" label="开通一件代发" valuePropName="checked"><Switch /></Form.Item></Col>
          <Col span={8}><Form.Item name="allow_wholesale" label="开通批发采购" valuePropName="checked"><Switch /></Form.Item></Col>
          <Col span={8}><Form.Item name="sales_rep_id" label="客户经理"><UserSelect /></Form.Item></Col>
          <Col span={8}><Form.Item name="status" label="状态"><Select options={dictOptions(DISTRIBUTOR_STATUS)} /></Form.Item></Col>
          <Col span={16}><Form.Item name="remark" label="备注"><Input /></Form.Item></Col>
          {!editing && can('distribution:account') && (
            <>
              <Col span={24}><Typography.Text type="secondary">同时开通门户登录账号（可选，也可稍后在「账号」中开通）</Typography.Text></Col>
              <Col span={12}><Form.Item name="username" label="登录账号" rules={[{ min: 3, pattern: /^[A-Za-z0-9_.@-]+$/, message: '3 位以上字母、数字或 _.@-' }]}><Input autoComplete="off" /></Form.Item></Col>
              <Col span={12}>
                <Form.Item name="password" label="初始密码" dependencies={['username']}
                  rules={[({ getFieldValue }) => ({ validator: (_, v) => (!getFieldValue('username') || (v && v.length >= 6) ? Promise.resolve() : Promise.reject(new Error('请设置至少 6 位密码'))) })]}>
                  <Input.Password autoComplete="new-password" />
                </Form.Item>
              </Col>
            </>
          )}
        </Row>
      </FormModal>
      <FormModal
        open={!!fund}
        title={fund ? `${fund.mode === 'recharge' ? '后台充值' : '调整余额'}：${fund.d.name}（${fund.d.currency}）` : ''}
        width={480}
        onCancel={() => setFund(null)}
        okText="确认"
        onSubmit={async (v) => {
          await api.post(`/distribution/distributors/${fund!.d.id}/${fund!.mode}`, v)
          message.success(fund!.mode === 'recharge' ? '已充值入账' : '余额已调整')
          done()
        }}
      >
        {fund?.mode === 'recharge' ? (
          <>
            <Alert type="info" title="线下已收到分销商货款时使用，提交后立即入账。" style={{ marginBottom: 16 }} />
            <Form.Item name="amount" label="充值金额" rules={[{ required: true }]}><InputNumber min={0.01} precision={2} style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="payment_method" label="收款方式" initialValue="bank">
              <Select options={[{ value: 'bank', label: '银行转账' }, { value: 'alipay', label: '支付宝' }, { value: 'wechat', label: '微信' }, { value: 'paypal', label: 'PayPal' }, { value: 'other', label: '其他' }]} />
            </Form.Item>
            <Form.Item name="transaction_no" label="收款流水号"><Input /></Form.Item>
            <Form.Item name="remark" label="备注"><Input /></Form.Item>
          </>
        ) : (
          <>
            <Alert type="warning" title="正数增加余额（如返点、赔付），负数扣减余额（如补收费用）。" style={{ marginBottom: 16 }} />
            <Form.Item name="amount" label="调整金额" rules={[{ required: true }]}><InputNumber precision={2} style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="remark" label="调整原因" rules={[{ required: true }]}><Input /></Form.Item>
          </>
        )}
      </FormModal>
      <AccountsDrawer id={accounts} onClose={() => setAccounts(null)} />
    </>
  )
}
