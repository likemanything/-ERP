import axios, { AxiosError, type AxiosRequestConfig } from 'axios'
import { useAuth } from '@/store/auth'

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface ApiErrorBody {
  code: string
  message: string
  details?: unknown
}

export interface Option {
  value: number | string
  label: string
}

export const http = axios.create({ baseURL: '/api/v1', timeout: 120000 })

http.interceptors.request.use((config) => {
  const token = useAuth.getState().accessToken
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

let refreshing: Promise<string | null> | null = null

async function refreshToken(): Promise<string | null> {
  const { refreshToken: rt, setTokens, logout } = useAuth.getState()
  if (!rt) return null
  try {
    const { data } = await axios.post('/api/v1/auth/refresh', { refresh_token: rt })
    setTokens(data.access_token, data.refresh_token)
    return data.access_token as string
  } catch {
    logout()
    return null
  }
}

http.interceptors.response.use(
  (resp) => resp,
  async (error: AxiosError<ApiErrorBody>) => {
    const original = error.config as (AxiosRequestConfig & { _retry?: boolean }) | undefined
    if (error.response?.status === 401 && original && !original._retry && !original.url?.includes('/auth/')) {
      original._retry = true
      refreshing = refreshing ?? refreshToken().finally(() => (refreshing = null))
      const token = await refreshing
      if (token) {
        original.headers = { ...(original.headers ?? {}), Authorization: `Bearer ${token}` }
        return http(original)
      }
      useAuth.getState().logout()
    }
    return Promise.reject(error)
  },
)

/** 从错误对象提取可读信息 */
export function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const body = err.response?.data as ApiErrorBody | undefined
    if (body?.message) return body.message
    if (err.response?.status === 403) return '没有权限执行该操作'
    if (err.code === 'ECONNABORTED') return '请求超时，请稍后重试'
    return err.message
  }
  return err instanceof Error ? err.message : String(err)
}

export const api = {
  get: async <T = any>(url: string, params?: Record<string, unknown>) => (await http.get<T>(url, { params })).data,
  post: async <T = any>(url: string, body?: unknown, params?: Record<string, unknown>) =>
    (await http.post<T>(url, body, { params })).data,
  put: async <T = any>(url: string, body?: unknown) => (await http.put<T>(url, body)).data,
  del: async <T = any>(url: string) => (await http.delete<T>(url)).data,
  upload: async <T = any>(url: string, file: File, fields?: Record<string, string | number | boolean>) => {
    const form = new FormData()
    form.append('file', file)
    Object.entries(fields ?? {}).forEach(([k, v]) => form.append(k, String(v)))
    return (await http.post<T>(url, form)).data
  },
}

/** 清理空参数 */
export function cleanParams(params: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === '') return
    out[k] = v
  })
  return out
}

/** 下载文件（导出 Excel / 模板），自动带上登录凭证 */
export async function download(url: string, params?: Record<string, unknown>, fallbackName = 'export.xlsx') {
  const resp = await http.get(url, { params: params ? cleanParams(params) : undefined, responseType: 'blob' })
  const disposition: string = resp.headers['content-disposition'] ?? ''
  const match = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  const name = match ? decodeURIComponent(match[1]) : fallbackName
  const href = URL.createObjectURL(resp.data as Blob)
  const a = document.createElement('a')
  a.href = href
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(href)
}
