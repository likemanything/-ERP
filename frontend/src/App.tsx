import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { App as AntApp, ConfigProvider, Result, Spin } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useAuth, usePerm, type CurrentUser, type Tenant } from '@/store/auth'
import MainLayout from '@/layouts/MainLayout'
import Login from '@/pages/Login'
import { ALL_ROUTES } from '@/router/routes'

dayjs.locale('zh-cn')

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = useAuth((s) => s.accessToken)
  const user = useAuth((s) => s.user)
  const setProfile = useAuth((s) => s.setProfile)
  const logout = useAuth((s) => s.logout)
  const location = useLocation()
  const [loading, setLoading] = useState(!!token && !user)

  useEffect(() => {
    if (!token || user) return
    setLoading(true)
    api
      .get<{ user: CurrentUser; tenant: Tenant; permissions: string[] }>('/auth/me')
      .then((me) => setProfile(me.user, me.tenant, me.permissions))
      .catch(() => logout())
      .finally(() => setLoading(false))
  }, [token, user, setProfile, logout])

  if (!token) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (loading || !user) return <div style={{ textAlign: 'center', padding: 120 }}><Spin size="large" /></div>
  return <>{children}</>
}

function Guard({ perm, children }: { perm?: string | string[]; children: React.ReactNode }) {
  const can = usePerm()
  if (!can(perm)) return <Result status="403" title="无权限" subTitle="您没有访问该页面的权限，请联系管理员分配。" />
  return <>{children}</>
}

function HomeRedirect() {
  const can = usePerm()
  const first = ALL_ROUTES.find((r) => can(r.perm))
  return <Navigate to={first?.path ?? '/dashboard'} replace />
}

export default function AppRoot() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: { colorPrimary: '#1677ff', borderRadius: 6 },
        components: { Table: { headerBg: '#fafafa' } },
      }}
    >
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route
                path="/"
                element={
                  <RequireAuth>
                    <MainLayout />
                  </RequireAuth>
                }
              >
                <Route index element={<HomeRedirect />} />
                {ALL_ROUTES.map((r) => (
                  <Route
                    key={r.path}
                    path={r.path.slice(1)}
                    element={
                      <Guard perm={r.perm}>
                        <r.element />
                      </Guard>
                    }
                  />
                ))}
                <Route path="*" element={<Result status="404" title="页面不存在" />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  )
}
