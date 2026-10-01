import { useState } from 'react'
import { Button, Col, Form, Input, Row, Select, Space, Switch, Tag } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import { DeptSelect, RoleSelect } from '@/components/selects'
import { useShopOptions } from '@/hooks/useOptions'
import { useAuth } from '@/store/auth'
import { fmtDateTime } from '@/utils/format'

type U = Record<string, any>

export default function Users() {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<U | null>(null)
  const [resetting, setResetting] = useState<U | null>(null)
  const reload = useReload('users')
  const run = useAction()
  const me = useAuth((s) => s.user)
  const { data: shops } = useShopOptions()
  return (
    <>
      <DataTable<U>
        queryKey="users"
        url="/system/users"
        filters={[{ name: 'keyword', placeholder: '用户名 / 姓名 / 手机' }, { name: 'is_active', type: 'select', label: '状态', options: [{ label: '启用', value: true }, { label: '禁用', value: false }] }]}
        toolbar={() => <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true) }}>新增用户</Button>}
        columns={[
          { title: '用户名', dataIndex: 'username', render: (v, r) => <Space>{v}{r.is_superuser && <Tag color="gold">管理员</Tag>}</Space> },
          { title: '姓名', dataIndex: 'real_name' },
          { title: '手机', dataIndex: 'phone', render: (v) => v ?? '-' },
          { title: '角色', dataIndex: 'roles', render: (roles: U[], r) => (r.is_superuser ? '全部权限' : roles.map((x) => <Tag key={x.id}>{x.name}</Tag>)) },
          { title: '店铺权限', key: 'shops', render: (_, r) => (r.is_superuser || r.all_shops ? '全部店铺' : `${r.shop_ids.length} 个店铺`) },
          { title: '状态', dataIndex: 'is_active', render: (v) => (v ? <Tag color="green">启用</Tag> : <Tag color="red">禁用</Tag>) },
          { title: '最近登录', dataIndex: 'last_login_at', render: fmtDateTime },
          {
            title: '操作', key: 'op',
            render: (_, r) => (
              <Space>
                <a onClick={() => { setEditing(r); setOpen(true) }}>编辑</a>
                <a onClick={() => setResetting(r)}>重置密码</a>
                {r.id !== me?.id && <a style={{ color: '#cf1322' }} onClick={() => run(() => api.del(`/system/users/${r.id}`), { confirm: `删除用户 ${r.username}？`, danger: true, onDone: reload })}>删除</a>}
              </Space>
            ),
          },
        ]}
      />
      <FormModal open={open} title={editing ? `编辑用户 ${editing.username}` : '新增用户'} width={640} onCancel={() => setOpen(false)}
        initialValues={editing ? { ...editing, role_ids: editing.roles.map((x: U) => x.id) } : { is_active: true, is_superuser: false, all_shops: true, role_ids: [], shop_ids: [] }}
        onSubmit={async (v) => { if (editing) await api.put(`/system/users/${editing.id}`, v); else await api.post('/system/users', v); reload() }}>
        <Row gutter={12}>
          {!editing && (
            <>
              <Col span={12}><Form.Item name="username" label="用户名" rules={[{ required: true, min: 3 }]}><Input /></Form.Item></Col>
              <Col span={12}><Form.Item name="password" label="初始密码" rules={[{ required: true, min: 6 }]}><Input.Password /></Form.Item></Col>
            </>
          )}
          <Col span={12}><Form.Item name="real_name" label="姓名"><Input /></Form.Item></Col>
          <Col span={12}><Form.Item name="phone" label="手机"><Input /></Form.Item></Col>
          <Col span={12}><Form.Item name="email" label="邮箱"><Input /></Form.Item></Col>
          <Col span={12}><Form.Item name="dept_id" label="部门"><DeptSelect /></Form.Item></Col>
          <Col span={24}><Form.Item name="role_ids" label="角色"><RoleSelect mode="multiple" /></Form.Item></Col>
          <Col span={8}><Form.Item name="is_active" label="启用" valuePropName="checked"><Switch /></Form.Item></Col>
          <Col span={8}><Form.Item name="is_superuser" label="企业管理员" valuePropName="checked"><Switch /></Form.Item></Col>
          <Col span={8}><Form.Item name="all_shops" label="可见全部店铺" valuePropName="checked"><Switch /></Form.Item></Col>
          <Form.Item noStyle shouldUpdate={(a, b) => a.all_shops !== b.all_shops}>
            {({ getFieldValue }) => !getFieldValue('all_shops') && (
              <Col span={24}><Form.Item name="shop_ids" label="可访问店铺（数据权限）"><Select mode="multiple" options={shops} /></Form.Item></Col>
            )}
          </Form.Item>
        </Row>
      </FormModal>
      <FormModal open={!!resetting} title={`重置 ${resetting?.username ?? ''} 的密码`} width={420} onCancel={() => setResetting(null)}
        onSubmit={async (v) => { await api.post(`/system/users/${resetting!.id}/reset-password`, v) }}>
        <Form.Item name="password" label="新密码" rules={[{ required: true, min: 6 }]}><Input.Password /></Form.Item>
      </FormModal>
    </>
  )
}
