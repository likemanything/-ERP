import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { App, Button, Card, ConfigProvider, Form, Input, Segmented, Typography } from 'antd'
import enUS from 'antd/locale/en_US'
import zhCN from 'antd/locale/zh_CN'
import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { api, errorMessage } from '@/api/client'
import { useAuth, type CurrentUser, type Tenant } from '@/store/auth'
import { usePortalLang, useT } from './i18n'

export default function PortalLogin() {
  const t = useT()
  const lang = usePortalLang((s) => s.lang)
  const setLang = usePortalLang((s) => s.setLang)
  const navigate = useNavigate()
  const { message } = App.useApp()
  const { setTokens, setProfile } = useAuth()
  const [loading, setLoading] = useState(false)

  const onLogin = async (v: { username: string; password: string }) => {
    setLoading(true)
    try {
      const tk = await api.post<{ access_token: string; refresh_token: string }>('/auth/login', v)
      setTokens(tk.access_token, tk.refresh_token)
      const me = await api.get<{ user: CurrentUser; tenant: Tenant; permissions: string[] }>('/auth/me')
      setProfile(me.user, me.tenant, me.permissions)
      message.success(t('loginOk'))
      navigate(me.user.user_type === 'distributor' ? '/portal' : '/', { replace: true })
    } catch (e) {
      message.error(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <ConfigProvider locale={lang === 'zh' ? zhCN : enUS} theme={{ token: { colorPrimary: '#722ed1' } }}>
      <div className="login-bg" style={{ position: 'relative', background: 'linear-gradient(135deg, #391085 0%, #722ed1 55%, #1677ff 100%)' }}>
        <div style={{ position: 'absolute', top: 16, right: 24 }}>
          <Segmented value={lang} onChange={(v) => setLang(v as 'zh' | 'en')} options={[{ label: '中文', value: 'zh' }, { label: 'English', value: 'en' }]} />
        </div>
        <div style={{ display: 'flex', gap: 64, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'center', padding: 24 }}>
          <div style={{ color: '#fff', maxWidth: 420 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <img src="/logo.svg" width={48} height={48} alt="logo" />
              <span style={{ fontSize: 32, fontWeight: 700 }}>{t('portal')}</span>
            </div>
            <Typography.Paragraph style={{ color: 'rgba(255,255,255,.88)', fontSize: 16, marginTop: 20 }}>{t('loginDesc')}</Typography.Paragraph>
          </div>
          <Card style={{ width: 380 }} title={t('loginTitle')}>
            <Form onFinish={onLogin} size="large">
              <Form.Item name="username" rules={[{ required: true, message: t('required') }]}>
                <Input prefix={<UserOutlined />} placeholder={t('username')} autoComplete="username" />
              </Form.Item>
              <Form.Item name="password" rules={[{ required: true, message: t('required') }]}>
                <Input.Password prefix={<LockOutlined />} placeholder={t('password')} autoComplete="current-password" />
              </Form.Item>
              <Button type="primary" htmlType="submit" block loading={loading}>
                {t('login')}
              </Button>
            </Form>
            <div style={{ textAlign: 'center', marginTop: 16, fontSize: 12 }}>
              <Link to="/login">{t('staffLogin')}</Link>
            </div>
          </Card>
        </div>
      </div>
    </ConfigProvider>
  )
}
