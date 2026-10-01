import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface CartItem {
  product_id: number
  sku: string
  title: string
  image_url?: string | null
  price: number
  currency: string
  min_qty: number
  qty: number
}

interface CartState {
  owner: number | null
  items: CartItem[]
  bind: (distributorId: number) => void
  add: (item: CartItem) => void
  setQty: (productId: number, qty: number) => void
  remove: (productId: number) => void
  clear: () => void
}

/** 门户购物车（按分销商隔离，保存在浏览器本地） */
export const useCart = create<CartState>()(
  persist(
    (set, get) => ({
      owner: null,
      items: [],
      bind: (id) => {
        if (get().owner !== id) set({ owner: id, items: [] })
      },
      add: (item) =>
        set((s) => {
          const exist = s.items.find((i) => i.product_id === item.product_id)
          if (exist) return { items: s.items.map((i) => (i.product_id === item.product_id ? { ...i, ...item, qty: i.qty + item.qty } : i)) }
          return { items: [...s.items, item] }
        }),
      setQty: (productId, qty) => set((s) => ({ items: s.items.map((i) => (i.product_id === productId ? { ...i, qty } : i)) })),
      remove: (productId) => set((s) => ({ items: s.items.filter((i) => i.product_id !== productId) })),
      clear: () => set({ items: [] }),
    }),
    { name: 'cloudsail-portal-cart' },
  ),
)
