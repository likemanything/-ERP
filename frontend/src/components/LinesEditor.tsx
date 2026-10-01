import { Button, Input, InputNumber, Table } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import type { ReactNode } from 'react'
import { ListingSelect, ProductSelect, type ListingBrief, type ProductBrief } from './selects'

export type Line = Record<string, any> & { _key: string }

export interface LineColumn {
  key: string
  title: string
  type: 'product' | 'listing' | 'number' | 'money' | 'text' | 'readonly'
  width?: number
  min?: number
  required?: boolean
  render?: (line: Line) => ReactNode
  /** listing 类型可限定店铺 */
  shopId?: number
  excludeBundle?: boolean
}

let seq = 0
export const newKey = () => `l${Date.now()}_${seq++}`

/** 单据明细编辑表格（受控，value 为行数组），可直接作为 Form.Item 的子组件 */
export default function LinesEditor({
  value = [],
  onChange,
  columns,
  addText = '添加明细',
  disabled,
}: {
  value?: Line[]
  onChange?: (lines: Line[]) => void
  columns: LineColumn[]
  addText?: string
  disabled?: boolean
}) {
  const update = (key: string, patch: Record<string, unknown>) =>
    onChange?.(value.map((l) => (l._key === key ? { ...l, ...patch } : l)))
  const remove = (key: string) => onChange?.(value.filter((l) => l._key !== key))
  const add = () => onChange?.([...value, { _key: newKey() }])

  const cols = columns.map((c) => ({
    title: c.required ? (
      <span>
        <span style={{ color: '#ff4d4f' }}>* </span>
        {c.title}
      </span>
    ) : (
      c.title
    ),
    key: c.key,
    width: c.width,
    render: (_: unknown, line: Line) => {
      if (c.render) return c.render(line)
      switch (c.type) {
        case 'product':
          return (
            <ProductSelect
              value={line[c.key]}
              disabled={disabled}
              excludeBundle={c.excludeBundle}
              style={{ width: '100%' }}
              onPick={(p?: ProductBrief) => update(line._key, { [c.key]: p?.id, _product: p })}
            />
          )
        case 'listing':
          return (
            <ListingSelect
              value={line[c.key]}
              shopId={c.shopId}
              disabled={disabled}
              style={{ width: '100%' }}
              onPick={(l?: ListingBrief) => update(line._key, { [c.key]: l?.value, _listing: l })}
            />
          )
        case 'number':
        case 'money':
          return (
            <InputNumber
              value={line[c.key]}
              min={c.min ?? 0}
              precision={c.type === 'money' ? 4 : 0}
              disabled={disabled}
              style={{ width: '100%' }}
              onChange={(v) => update(line._key, { [c.key]: v })}
            />
          )
        case 'text':
          return <Input value={line[c.key]} disabled={disabled} onChange={(e) => update(line._key, { [c.key]: e.target.value })} />
        default:
          return line[c.key] ?? '-'
      }
    },
  }))
  if (!disabled) {
    cols.push({
      title: '',
      key: '_op',
      width: 48,
      render: (_: unknown, line: Line) => <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(line._key)} />,
    })
  }
  return (
    <div>
      <Table<Line> rowKey="_key" size="small" columns={cols} dataSource={value} pagination={false} bordered />
      {!disabled && (
        <Button type="dashed" block icon={<PlusOutlined />} onClick={add} style={{ marginTop: 8 }}>
          {addText}
        </Button>
      )}
    </div>
  )
}

/** 去掉前端辅助字段 */
export function stripLines<T extends Record<string, unknown>>(lines: Line[], fields: string[]): T[] {
  return lines.map((l) => Object.fromEntries(fields.filter((f) => l[f] !== undefined && l[f] !== null).map((f) => [f, l[f]])) as T)
}
