import { useEffect, useMemo, useState } from 'react'
import { Select, type SelectProps } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api, type Option } from '@/api/client'
import {
  useBrandOptions,
  useCategoryOptions,
  useChannelOptions,
  useCurrencies,
  useDeptOptions,
  useDistributorOptions,
  useLevelOptions,
  useProviderOptions,
  useRoleOptions,
  useShopOptions,
  useSupplierOptions,
  useUserOptions,
  useWarehouseOptions,
} from '@/hooks/useOptions'
import { dictOptions, type Dict } from '@/utils/dicts'

type BaseProps = Omit<SelectProps, 'options' | 'loading'>

function OptionSelect({ options, loading, placeholder, ...rest }: BaseProps & { options?: Option[]; loading?: boolean }) {
  return (
    <Select
      allowClear
      showSearch={{ optionFilterProp: 'label' }}
      placeholder={placeholder ?? '请选择'}
      options={options}
      loading={loading}
      style={{ minWidth: 160, ...(rest.style ?? {}) }}
      {...rest}
    />
  )
}

export function ShopSelect(props: BaseProps & { platform?: string }) {
  const { platform, ...rest } = props
  const { data, isLoading } = useShopOptions(platform)
  return <OptionSelect placeholder="选择店铺" options={data} loading={isLoading} {...rest} />
}

export function WarehouseSelect(props: BaseProps & { warehouseType?: string; excludeFba?: boolean }) {
  const { warehouseType, excludeFba, ...rest } = props
  const { data, isLoading } = useWarehouseOptions(warehouseType)
  const { data: fba } = useWarehouseOptions('fba')
  const options = useMemo(() => {
    if (!excludeFba || !data) return data
    const fbaIds = new Set((fba ?? []).map((o) => o.value))
    return data.filter((o) => !fbaIds.has(o.value))
  }, [data, fba, excludeFba])
  return <OptionSelect placeholder="选择仓库" options={options} loading={isLoading} {...rest} />
}

export function SupplierSelect(props: BaseProps) {
  const { data, isLoading } = useSupplierOptions()
  return <OptionSelect placeholder="选择供应商" options={data} loading={isLoading} {...props} />
}

export function UserSelect(props: BaseProps) {
  const { data, isLoading } = useUserOptions()
  return <OptionSelect placeholder="选择人员" options={data} loading={isLoading} {...props} />
}

export function RoleSelect(props: BaseProps) {
  const { data, isLoading } = useRoleOptions()
  return <OptionSelect placeholder="选择角色" options={data} loading={isLoading} {...props} />
}

export function DeptSelect(props: BaseProps) {
  const { data, isLoading } = useDeptOptions()
  return <OptionSelect placeholder="选择部门" options={data} loading={isLoading} {...props} />
}

export function ChannelSelect(props: BaseProps & { usage?: string }) {
  const { usage, ...rest } = props
  const { data, isLoading } = useChannelOptions(usage)
  return <OptionSelect placeholder="选择物流渠道" options={data} loading={isLoading} {...rest} />
}

export function ProviderSelect(props: BaseProps) {
  const { data, isLoading } = useProviderOptions()
  return <OptionSelect placeholder="选择物流商" options={data} loading={isLoading} {...props} />
}

export function CategorySelect(props: BaseProps) {
  const { data, isLoading } = useCategoryOptions()
  return <OptionSelect placeholder="选择分类" options={data} loading={isLoading} {...props} />
}

export function BrandSelect(props: BaseProps) {
  const { data, isLoading } = useBrandOptions()
  return <OptionSelect placeholder="选择品牌" options={data} loading={isLoading} {...props} />
}

export function DistributorSelect(props: BaseProps) {
  const { data, isLoading } = useDistributorOptions()
  return <OptionSelect placeholder="选择分销商" options={data} loading={isLoading} {...props} />
}

export function LevelSelect(props: BaseProps) {
  const { data, isLoading } = useLevelOptions()
  return <OptionSelect placeholder="选择等级" options={data} loading={isLoading} {...props} />
}

export function CurrencySelect(props: BaseProps) {
  const { data } = useCurrencies()
  const options = (data ?? []).map((c) => ({ value: c.code, label: `${c.code} ${c.name}` }))
  return <OptionSelect placeholder="币种" options={options} style={{ minWidth: 120 }} {...props} />
}

export function DictSelect(props: BaseProps & { dict: Dict }) {
  const { dict, ...rest } = props
  return <OptionSelect options={dictOptions(dict)} style={{ minWidth: 120 }} {...rest} />
}

// ------------------------------------------------------------------ 远程搜索
export interface ProductBrief {
  id: number
  sku: string
  name: string
  image_url?: string | null
  product_type: string
  unit?: string
}

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

/** 产品搜索选择（按 SKU/品名），onPick 返回完整产品摘要 */
export function ProductSelect(
  props: BaseProps & { excludeBundle?: boolean; onPick?: (p: ProductBrief | undefined) => void },
) {
  const { excludeBundle, onPick, value, onChange, ...rest } = props
  const [keyword, setKeyword] = useState('')
  const kw = useDebounced(keyword)
  const { data: found, isFetching } = useQuery({
    queryKey: ['product-options', kw, excludeBundle],
    queryFn: () => api.get<ProductBrief[]>('/products/options', { keyword: kw || undefined, exclude_bundle: excludeBundle }),
    staleTime: 30_000,
  })
  const ids = useMemo(() => (Array.isArray(value) ? value : value ? [value] : []) as number[], [value])
  const missing = ids.filter((id) => !(found ?? []).some((p) => p.id === id))
  const { data: selected } = useQuery({
    queryKey: ['product-options-ids', missing.join(',')],
    queryFn: () => api.get<ProductBrief[]>('/products/options', { ids: missing.join(',') }),
    enabled: missing.length > 0,
    staleTime: 60_000,
  })
  const all = useMemo(() => {
    const m = new Map<number, ProductBrief>()
    ;[...(selected ?? []), ...(found ?? [])].forEach((p) => m.set(p.id, p))
    return [...m.values()]
  }, [found, selected])
  return (
    <Select
      allowClear
      placeholder="输入 SKU / 品名搜索"
      showSearch={{ filterOption: false, onSearch: setKeyword }}
      loading={isFetching}
      value={value}
      onChange={(v, opt) => {
        onChange?.(v, opt)
        onPick?.(all.find((p) => p.id === v))
      }}
      options={all.map((p) => ({ value: p.id, label: `${p.sku}  ${p.name}` }))}
      style={{ minWidth: 220, ...(rest.style ?? {}) }}
      popupMatchSelectWidth={false}
      {...rest}
    />
  )
}

export interface ListingBrief {
  value: number
  label: string
  msku: string
  fnsku?: string | null
  product_id?: number | null
  sku?: string | null
  shop_id: number
}

/** Listing 搜索选择（按 MSKU/ASIN） */
export function ListingSelect(props: BaseProps & { shopId?: number; onPick?: (l: ListingBrief | undefined) => void }) {
  const { shopId, onPick, onChange, ...rest } = props
  const [keyword, setKeyword] = useState('')
  const kw = useDebounced(keyword)
  const { data, isFetching } = useQuery({
    queryKey: ['listing-options', kw, shopId],
    queryFn: () => api.get<ListingBrief[]>('/listings/options', { keyword: kw || undefined, shop_id: shopId }),
    staleTime: 30_000,
  })
  return (
    <Select
      allowClear
      placeholder="输入 MSKU / ASIN 搜索"
      showSearch={{ filterOption: false, onSearch: setKeyword }}
      loading={isFetching}
      onChange={(v, opt) => {
        onChange?.(v, opt)
        onPick?.((data ?? []).find((x) => x.value === v))
      }}
      options={(data ?? []).map((x) => ({ value: x.value, label: `${x.label}${x.sku ? ` → ${x.sku}` : ' (未配对)'}` }))}
      style={{ minWidth: 240, ...(rest.style ?? {}) }}
      popupMatchSelectWidth={false}
      {...rest}
    />
  )
}
