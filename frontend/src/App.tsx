import { lazy, Suspense, useEffect, useState } from 'react'
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
import PortalLogin from '@/portal/PortalLogin'

const PortalLayout = lazy(() => import('@/portal/PortalLayout'))
const PortalHome = lazy(() => import('@/portal/pages/Home'))
const PortalCatalog = lazy(() => import('@/portal/pages/Catalog'))
const PortalCart = lazy(() => import('@/portal/pages/Cart'))
const PortalOrders = lazy(() => import('@/portal/pages/Orders'))
const PortalFunds = lazy(() => import('@/portal/pages/Funds'))
const PortalApi = lazy(() => import('@/portal/pages/ApiAccess'))

dayjs.locale('zh-cn')

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

/** 登录校验：员工后台与分销商门户互相隔离，账号类型不匹配时自动跳转 */
function RequireAuth({ children, portal = false }: { children: React.ReactNode; portal?: boolean }) {
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

  if (!token) return <Navigate to={portal ? '/portal/login' : '/login'} replace state={{ from: location.pathname }} />
  if (loading || !user) return <div style={{ textAlign: 'center', padding: 120 }}><Spin size="large" /></div>
  const isDistributor = user.user_type === 'distributor'
  if (isDistributor && !portal) return <Navigate to="/portal" replace />
  if (!isDistributor && portal) return <Navigate to="/" replace />
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
              <Route path="/portal/login" element={<PortalLogin />} />
              <Route
                path="/portal"
                element={
                  <RequireAuth portal>
                    <Suspense fallback={<div style={{ textAlign: 'center', padding: 120 }}><Spin size="large" /></div>}>
                      <PortalLayout />
                    </Suspense>
                  </RequireAuth>
                }
              >
                <Route index element={<PortalHome />} />
                <Route path="catalog" element={<PortalCatalog />} />
                <Route path="cart" element={<PortalCart />} />
                <Route path="orders" element={<PortalOrders />} />
                <Route path="funds" element={<PortalFunds />} />
                <Route path="api" element={<PortalApi />} />
                <Route path="*" element={<Navigate to="/portal" replace />} />
              </Route>
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
