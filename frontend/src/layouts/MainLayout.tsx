import { Suspense, useMemo, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { App, Avatar, Badge, Breadcrumb, Button, Dropdown, Form, Input, Layout, List, Menu, Popover, Spin, Tag, Typography } from 'antd'
import { BellOutlined, LockOutlined, LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined, UserOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Page } from '@/api/client'
import { useAuth, usePerm } from '@/store/auth'
import { MENU } from '@/router/routes'
import { FormModal } from '@/components/common'
import { fmtDateTime } from '@/utils/format'

const { Header, Sider, Content } = Layout

interface Notice {
  id: number
  title: string
  content?: string
  link?: string
  is_read: boolean
  created_at: string
  category: string
}

function Notifications() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['notifications'],
    queryFn: () => api.get<Page<Notice>>('/system/notifications', { unread: true, page_size: 10 }),
    refetchInterval: 60_000,
  })
  const items = data?.items ?? []
  const content = (
    <div style={{ width: 340 }}>
      <List
        size="small"
        dataSource={items}
        locale={{ emptyText: '暂无未读消息' }}
        renderItem={(n) => (
          <List.Item style={{ cursor: n.link ? 'pointer' : undefined }} onClick={() => n.link && navigate(n.link.split('?')[0])}>
            <List.Item.Meta
              title={<span style={{ fontSize: 13 }}>{n.title}</span>}
              description={
                <span style={{ fontSize: 12 }}>
                  {n.content} · {fmtDateTime(n.created_at)}
                </span>
              }
            />
          </List.Item>
        )}
      />
      {items.length > 0 && (
        <Button
          type="link"
          block
          onClick={async () => {
            await api.post('/system/notifications/read-all')
            qc.invalidateQueries({ queryKey: ['notifications'] })
          }}
        >
          全部标为已读
        </Button>
      )}
    </div>
  )
  return (
    <Popover content={content} title="消息通知" trigger="click" placement="bottomRight">
      <Badge count={data?.total ?? 0} size="small">
        <BellOutlined style={{ fontSize: 18, cursor: 'pointer' }} />
      </Badge>
    </Popover>
  )
}

export default function MainLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const [pwdOpen, setPwdOpen] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const can = usePerm()
  const { user, tenant, logout } = useAuth()
  const { message } = App.useApp()

  const menuItems = useMemo(
    () =>
      MENU.map((g) => {
        const children = g.children.filter((r) => !r.hideInMenu && can(r.perm))
        if (!children.length) return null
        if (g.key === 'home') return { key: children[0].path, icon: g.icon, label: children[0].label }
        return { key: g.key, icon: g.icon, label: g.label, children: children.map((r) => ({ key: r.path, label: r.label })) }
      }).filter(Boolean) as NonNullable<React.ComponentProps<typeof Menu>['items']>,
    [can],
  )

  const current = useMemo(() => {
    let best = ''
    MENU.forEach((g) => g.children.forEach((r) => {
      if ((location.pathname === r.path || location.pathname.startsWith(r.path + '/')) && r.path.length > best.length) best = r.path
    }))
    return best
  }, [location.pathname])
  const group = MENU.find((g) => g.children.some((r) => r.path === current))
  const routeLabel = group?.children.find((r) => r.path === current)?.label
  const [openKeys, setOpenKeys] = useState<string[]>(group ? [group.key] : [])

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} trigger={null} width={216} theme="dark" style={{ overflow: 'auto', height: '100vh', position: 'sticky', top: 0 }}>
        <div style={{ height: 56, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, color: '#fff' }}>
          <img src="/logo.svg" width={28} height={28} alt="logo" />
          {!collapsed && <span style={{ fontSize: 17, fontWeight: 700, letterSpacing: 1 }}>云帆ERP</span>}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          items={menuItems}
          selectedKeys={[current]}
          openKeys={collapsed ? undefined : openKeys}
          onOpenChange={(keys) => setOpenKeys(keys as string[])}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', boxShadow: '0 1px 4px rgba(0,21,41,.08)', position: 'sticky', top: 0, zIndex: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Button type="text" icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={() => setCollapsed(!collapsed)} />
            <Breadcrumb items={[{ title: group?.label ?? '首页' }, ...(routeLabel && group?.key !== 'home' ? [{ title: routeLabel }] : [])]} />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
            <Tag color="blue">{tenant?.name}</Tag>
            <Typography.Text type="secondary">本位币 {tenant?.base_currency}</Typography.Text>
            <Notifications />
            <Dropdown
              menu={{
                items: [
                  { key: 'pwd', icon: <LockOutlined />, label: '修改密码', onClick: () => setPwdOpen(true) },
                  { type: 'divider' },
                  { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: () => { logout(); navigate('/login') } },
                ],
              }}
            >
              <span style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}>
                <Avatar size="small" icon={<UserOutlined />} style={{ background: '#1677ff' }} />
                {user?.real_name || user?.username}
              </span>
            </Dropdown>
          </div>
        </Header>
        <Content style={{ margin: 16 }}>
          <Suspense fallback={<div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>}>
            <Outlet />
          </Suspense>
        </Content>
      </Layout>
      <FormModal<{ old_password: string; new_password: string; confirm: string }>
        open={pwdOpen}
        title="修改密码"
        width={420}
        onCancel={() => setPwdOpen(false)}
        onSubmit={async (v) => {
          await api.post('/auth/change-password', { old_password: v.old_password, new_password: v.new_password })
          message.success('密码已修改，请重新登录')
          logout()
          navigate('/login')
        }}
      >
        <Form.Item name="old_password" label="原密码" rules={[{ required: true }]}>
          <Input.Password />
        </Form.Item>
        <Form.Item name="new_password" label="新密码" rules={[{ required: true, min: 6 }]}>
          <Input.Password />
        </Form.Item>
        <Form.Item
          name="confirm"
          label="确认新密码"
          dependencies={['new_password']}
          rules={[
            { required: true },
            ({ getFieldValue }) => ({
              validator: (_, v) => (v === getFieldValue('new_password') ? Promise.resolve() : Promise.reject(new Error('两次输入不一致'))),
            }),
          ]}
        >
          <Input.Password />
        </Form.Item>
      </FormModal>
    </Layout>
  )
}
