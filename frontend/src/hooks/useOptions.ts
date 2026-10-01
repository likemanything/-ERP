import { useQuery } from '@tanstack/react-query'
import { api, type Option } from '@/api/client'

const STALE = 5 * 60 * 1000

function useOptionList(key: string, url: string, params?: Record<string, unknown>, enabled = true) {
  return useQuery({
    queryKey: ['options', key, params],
    queryFn: () => api.get<Option[]>(url, params),
    staleTime: STALE,
    enabled,
  })
}

export const useShopOptions = (platform?: string) => useOptionList('shops', '/shops/options', platform ? { platform } : undefined)
export const useWarehouseOptions = (warehouse_type?: string) =>
  useOptionList('warehouses', '/warehouses/options', warehouse_type ? { warehouse_type } : undefined)
export const useSupplierOptions = () => useOptionList('suppliers', '/suppliers/options', { status: 'active' })
export const useUserOptions = () => useOptionList('users', '/system/users/options')
export const useRoleOptions = () => useOptionList('roles', '/system/roles/options')
export const useChannelOptions = (usage?: string) =>
  useOptionList('channels', '/logistics-channels/options', usage ? { usage } : undefined)
export const useProviderOptions = () => useOptionList('providers', '/logistics-providers/options')
export const useCategoryOptions = () => useOptionList('categories', '/product-categories/options')
export const useBrandOptions = () => useOptionList('brands', '/product-brands/options')
export const useDeptOptions = () => useOptionList('depts', '/system/departments/options')
export const useDistributorOptions = () => useOptionList('distributors', '/distribution/distributors/options')
export const useLevelOptions = () => useOptionList('dist-levels', '/distribution/levels/options')

export function useCurrencies() {
  return useQuery({
    queryKey: ['options', 'currencies'],
    queryFn: () => api.get<{ code: string; name: string }[]>('/system/currencies'),
    staleTime: STALE,
  })
}

export function useMarketplaces(platform?: string) {
  return useQuery({
    queryKey: ['options', 'marketplaces', platform],
    queryFn: () =>
      api.get<{ code: string; name: string; currency: string; platform: string }[]>('/shops/marketplaces', platform ? { platform } : undefined),
    staleTime: STALE,
  })
}

/** 选项数组 → id→label 字典，用于表格中显示名称 */
export function useLabelMap(options?: Option[]) {
  const map = new Map<number | string, string>()
  options?.forEach((o) => map.set(o.value, o.label))
  return map
}
