import { Suspense, useEffect, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { App, Avatar, Badge, ConfigProvider, Dropdown, Form, Input, Layout, Menu, Segmented, Spin, Typography } from 'antd'
import enUS from 'antd/locale/en_US'
import zhCN from 'antd/locale/zh_CN'
import dayjs from 'dayjs'
import {
  ApiOutlined,
  AppstoreOutlined,
  HomeOutlined,
  LockOutlined,
  LogoutOutlined,
  ProfileOutlined,
  ShoppingCartOutlined,
  UserOutlined,
  WalletOutlined,
} from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { FormModal } from '@/components/common'
import { useAuth } from '@/store/auth'
import { fmtMoney } from '@/utils/format'
import { usePortalMe } from './api'
import { useCart } from './cart'
import { usePortalLang, useT } from './i18n'

const { Header, Content, Footer } = Layout

export default function PortalLayout() {
  const t = useT()
  const lang = usePortalLang((s) => s.lang)
  const setLang = usePortalLang((s) => s.setLang)
  const navigate = useNavigate()
  const location = useLocation()
  const logout = useAuth((s) => s.logout)
  const qc = useQueryClient()
  const { data: me } = usePortalMe()
  const cartCount = useCart((s) => s.items.length)
  const bindCart = useCart((s) => s.bind)
  const [pwdOpen, setPwdOpen] = useState(false)
  const { message } = App.useApp()

  useEffect(() => {
    dayjs.locale(lang === 'zh' ? 'zh-cn' : 'en')
    return () => void dayjs.locale('zh-cn')
  }, [lang])
  useEffect(() => {
    if (me) bindCart(me.distributor.id)
  }, [me, bindCart])

  const signOut = () => {
    logout()
    qc.clear()
    navigate('/portal/login')
  }

  const items = [
    { key: '/portal', icon: <HomeOutlined />, label: t('home') },
    { key: '/portal/catalog', icon: <AppstoreOutlined />, label: t('catalog') },
    {
      key: '/portal/cart',
      icon: <ShoppingCartOutlined />,
      label: (
        <Badge count={cartCount} size="small" offset={[8, -2]}>
          <span style={{ color: 'inherit' }}>{t('cart')}</span>
        </Badge>
      ),
    },
    { key: '/portal/orders', icon: <ProfileOutlined />, label: t('orders') },
    { key: '/portal/funds', icon: <WalletOutlined />, label: t('funds') },
    { key: '/portal/api', icon: <ApiOutlined />, label: t('api') },
  ]
  const selected = [...items].reverse().find((i) => location.pathname === i.key || location.pathname.startsWith(i.key + '/'))?.key ?? '/portal'
  const d = me?.distributor

  return (
    <ConfigProvider locale={lang === 'zh' ? zhCN : enUS}>
      <Layout style={{ minHeight: '100vh' }}>
        <Header style={{ background: '#fff', padding: '0 24px', display: 'flex', alignItems: 'center', gap: 24, boxShadow: '0 1px 4px rgba(0,21,41,.08)', position: 'sticky', top: 0, zIndex: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', flexShrink: 0 }} onClick={() => navigate('/portal')}>
            <img src="/logo.svg" width={28} height={28} alt="logo" />
            <div style={{ lineHeight: 1.2 }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>{me?.company_name ?? '…'}</div>
              <div style={{ fontSize: 12, color: '#888' }}>{t('portal')}</div>
            </div>
          </div>
          <Menu mode="horizontal" items={items} selectedKeys={[selected]} onClick={({ key }) => navigate(key)} style={{ flex: 1, minWidth: 0, borderBottom: 'none' }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexShrink: 0 }}>
            {d && (
              <span style={{ cursor: 'pointer' }} onClick={() => navigate('/portal/funds')}>
                <Typography.Text type="secondary">{t('availableFunds')} </Typography.Text>
                <Typography.Text strong style={{ color: d.available_funds > 0 ? '#389e0d' : '#cf1322' }}>
                  {fmtMoney(d.available_funds, d.currency)}
                </Typography.Text>
              </span>
            )}
            <Segmented size="small" value={lang} onChange={(v) => setLang(v as 'zh' | 'en')} options={[{ label: '中文', value: 'zh' }, { label: 'EN', value: 'en' }]} />
            <Dropdown
              menu={{
                items: [
                  { key: 'pwd', icon: <LockOutlined />, label: t('changePassword'), onClick: () => setPwdOpen(true) },
                  { type: 'divider' },
                  { key: 'logout', icon: <LogoutOutlined />, label: t('logout'), onClick: signOut },
                ],
              }}
            >
              <span style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}>
                <Avatar size="small" icon={<UserOutlined />} style={{ background: '#722ed1' }} />
                <span>{d?.name ?? me?.username}</span>
              </span>
            </Dropdown>
          </div>
        </Header>
        <Content style={{ padding: 24, maxWidth: 1360, width: '100%', margin: '0 auto' }}>
          <Suspense fallback={<div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>}>
            <Outlet />
          </Suspense>
        </Content>
        <Footer style={{ textAlign: 'center', color: '#999', fontSize: 12 }}>
          {me?.company_name} · {t('portal')} {d && `· ${d.code}`}
        </Footer>
        <FormModal<{ old_password: string; new_password: string; confirm: string }>
          open={pwdOpen}
          title={t('changePassword')}
          width={420}
          okText={t('save')}
          onCancel={() => setPwdOpen(false)}
          onSubmit={async (v) => {
            await api.post('/auth/change-password', { old_password: v.old_password, new_password: v.new_password })
            message.success(t('passwordChanged'))
            signOut()
          }}
        >
          <Form.Item name="old_password" label={t('oldPassword')} rules={[{ required: true, message: t('required') }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="new_password" label={t('newPassword')} rules={[{ required: true, min: 6 }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item
            name="confirm"
            label={t('confirmPassword')}
            dependencies={['new_password']}
            rules={[
              { required: true, message: t('required') },
              ({ getFieldValue }) => ({
                validator: (_, v) => (v === getFieldValue('new_password') ? Promise.resolve() : Promise.reject(new Error(t('passwordMismatch')))),
              }),
            ]}
          >
            <Input.Password />
          </Form.Item>
        </FormModal>
      </Layout>
    </ConfigProvider>
  )
}
