import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface RoleBrief {
  id: number
  code: string
  name: string
}

export interface CurrentUser {
  id: number
  username: string
  real_name: string
  email?: string | null
  phone?: string | null
  is_superuser: boolean
  all_shops: boolean
  roles: RoleBrief[]
  shop_ids: number[]
}

export interface Tenant {
  id: number
  code: string
  name: string
  base_currency: string
  timezone: string
}

interface AuthState {
  accessToken: string | null
  refreshToken: string | null
  user: CurrentUser | null
  tenant: Tenant | null
  permissions: string[]
  setTokens: (access: string, refresh: string) => void
  setProfile: (user: CurrentUser, tenant: Tenant, permissions: string[]) => void
  logout: () => void
  can: (perm: string) => boolean
}

export const useAuth = create<AuthState>()(
  persist(
    (set, get) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      tenant: null,
      permissions: [],
      setTokens: (access, refresh) => set({ accessToken: access, refreshToken: refresh }),
      setProfile: (user, tenant, permissions) => set({ user, tenant, permissions }),
      logout: () => set({ accessToken: null, refreshToken: null, user: null, tenant: null, permissions: [] }),
      can: (perm) => {
        const { user, permissions } = get()
        return !!user?.is_superuser || permissions.includes(perm)
      },
    }),
    {
      name: 'cloudsail-erp-auth',
      partialize: (s) => ({ accessToken: s.accessToken, refreshToken: s.refreshToken }),
    },
  ),
)

/** 组件内使用：返回判断权限的函数（会随权限变化重新渲染） */
export function usePerm() {
  const permissions = useAuth((s) => s.permissions)
  const isAdmin = useAuth((s) => !!s.user?.is_superuser)
  return (perm?: string | string[]) => {
    if (!perm) return true
    const list = Array.isArray(perm) ? perm : [perm]
    return isAdmin || list.some((p) => permissions.includes(p))
  }
}

export function useBaseCurrency(): string {
  return useAuth((s) => s.tenant?.base_currency ?? 'CNY')
}
