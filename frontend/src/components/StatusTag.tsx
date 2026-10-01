import { Tag } from 'antd'
import type { Dict } from '@/utils/dicts'

export default function StatusTag({ dict, value }: { dict: Dict; value?: string | null }) {
  if (!value) return <span>-</span>
  const [label, color] = dict[value] ?? [value, 'default']
  return (
    <Tag color={color} style={{ marginInlineEnd: 0 }}>
      {label}
    </Tag>
  )
}
