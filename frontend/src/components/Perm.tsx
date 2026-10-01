import type { ReactNode } from 'react'
import { usePerm } from '@/store/auth'

/** 按权限渲染子元素（按钮级权限控制） */
export default function Perm({ code, children, fallback = null }: { code?: string | string[]; children: ReactNode; fallback?: ReactNode }) {
  const can = usePerm()
  return <>{can(code) ? children : fallback}</>
}
