import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'

export interface PortalDistributor {
  id: number
  code: string
  name: string
  contact?: string | null
  phone?: string | null
  email?: string | null
  country?: string | null
  address?: string | null
  currency: string
  balance: number
  credit_limit: number
  available_funds: number
  level_name?: string | null
  allow_dropship: boolean
  allow_wholesale: boolean
  has_api_key: boolean
}

export interface PortalMe {
  distributor: PortalDistributor
  username?: string | null
  real_name?: string | null
  company_name?: string | null
}

export interface PortalOrder {
  id: number
  order_no: string
  reference_no: string
  status: string
  distribution_type?: string | null
  created_at: string
  shipped_at?: string | null
  ship_name?: string | null
  ship_phone?: string | null
  ship_country?: string | null
  ship_state?: string | null
  ship_city?: string | null
  ship_address1?: string | null
  ship_address2?: string | null
  ship_postcode?: string | null
  channel_name?: string | null
  carrier?: string | null
  tracking_no?: string | null
  currency: string
  charge_detail?: Record<string, number | string> | null
  note?: string | null
  can_cancel: boolean
  items: { sku?: string | null; title?: string | null; quantity: number; unit_price: number; item_amount: number }[]
}

export function usePortalMe() {
  return useQuery({ queryKey: ['portal-me'], queryFn: () => api.get<PortalMe>('/portal/me'), staleTime: 15_000 })
}

export const STATUS_COLOR: Record<string, string> = {
  pending: 'default',
  to_audit: 'orange',
  to_ship: 'blue',
  shipped: 'green',
  delivered: 'cyan',
  cancelled: 'red',
}
