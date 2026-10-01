import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { App, Button, Card, Form, Input, Select, Tabs, Typography } from 'antd'
import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { api, errorMessage } from '@/api/client'
import { useAuth, type CurrentUser, type Tenant } from '@/store/auth'

interface TokenOut {
  access_token: string
  refresh_token: string
}

export default function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const { message } = App.useApp()
  const { setTokens, setProfile } = useAuth()
  const [loading, setLoading] = useState(false)

  const afterLogin = async (t: TokenOut) => {
    setTokens(t.access_token, t.refresh_token)
    const me = await api.get<{ user: CurrentUser; tenant: Tenant; permissions: string[] }>('/auth/me')
    setProfile(me.user, me.tenant, me.permissions)
    if (me.user.user_type === 'distributor') {
      navigate('/portal', { replace: true })
      return
    }
    const from = (location.state as { from?: string } | null)?.from
    navigate(from && from !== '/login' && !from.startsWith('/portal') ? from : '/', { replace: true })
  }

  const onLogin = async (v: { username: string; password: string }) => {
    setLoading(true)
    try {
      await afterLogin(await api.post<TokenOut>('/auth/login', v))
      message.success('登录成功')
    } catch (e) {
      message.error(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  const onRegister = async (v: Record<string, string>) => {
    setLoading(true)
    try {
      await afterLogin(await api.post<TokenOut>('/auth/register', v))
      message.success('企业开通成功')
    } catch (e) {
      message.error(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-bg">
      <div style={{ display: 'flex', gap: 64, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'center', padding: 24 }}>
        <div style={{ color: '#fff', maxWidth: 420 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <img src="/logo.svg" width={48} height={48} alt="logo" />
            <span style={{ fontSize: 34, fontWeight: 700 }}>云帆ERP</span>
          </div>
          <Typography.Paragraph style={{ color: 'rgba(255,255,255,.85)', fontSize: 16, marginTop: 20 }}>
            跨境电商一体化管理平台：多平台店铺、采购、仓储、FBA 头程、智能补货、订单、财务利润、广告分析，一站搞定。
          </Typography.Paragraph>
          <ul style={{ color: 'rgba(255,255,255,.8)', lineHeight: 2, paddingLeft: 18 }}>
            <li>FIFO 批次成本 + 头程分摊，利润精确到每个 MSKU</li>
            <li>按销量与在途库存自动计算发货、采购建议</li>
            <li>多币种、多店铺、多仓库，权限细到按钮与店铺</li>
          </ul>
        </div>
        <Card style={{ width: 400 }}>
          <Tabs
            centered
            items={[
              {
                key: 'login',
                label: '账号登录',
                children: (
                  <Form onFinish={onLogin} size="large" initialValues={{ username: '', password: '' }}>
                    <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
                      <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
                    </Form.Item>
                    <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
                      <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
                    </Form.Item>
                    <Button type="primary" htmlType="submit" block loading={loading}>
                      登录
                    </Button>
                    <Typography.Paragraph type="secondary" style={{ marginTop: 12, fontSize: 12, textAlign: 'center' }}>
                      演示账号：demo / demo123456（需先执行 seed-demo）
                      <br />
                      分销商请从 <Link to="/portal/login">分销商门户</Link> 登录（演示：dealer / dealer123456）
                    </Typography.Paragraph>
                  </Form>
                ),
              },
              {
                key: 'register',
                label: '免费开通',
                children: (
                  <Form onFinish={onRegister} layout="vertical" initialValues={{ base_currency: 'CNY' }}>
                    <Form.Item name="company_name" label="企业名称" rules={[{ required: true, min: 2 }]}>
                      <Input placeholder="如：深圳某某贸易有限公司" />
                    </Form.Item>
                    <Form.Item name="username" label="管理员账号" rules={[{ required: true, min: 3, pattern: /^[A-Za-z0-9_.@-]+$/, message: '3 位以上字母、数字或 _.@-' }]}>
                      <Input />
                    </Form.Item>
                    <Form.Item name="password" label="密码" rules={[{ required: true, min: 6 }]}>
                      <Input.Password />
                    </Form.Item>
                    <Form.Item name="real_name" label="姓名">
                      <Input />
                    </Form.Item>
                    <Form.Item name="base_currency" label="本位币">
                      <Select options={[{ value: 'CNY', label: 'CNY 人民币' }, { value: 'USD', label: 'USD 美元' }, { value: 'HKD', label: 'HKD 港币' }]} />
                    </Form.Item>
                    <Button type="primary" htmlType="submit" block loading={loading}>
                      开通企业账号
                    </Button>
                  </Form>
                ),
              },
            ]}
          />
        </Card>
      </div>
    </div>
  )
}
