import { useMemo, useState, type ReactNode } from 'react'
import { Button, Card, DatePicker, Form, Input, Select, Space, Table, Tooltip } from 'antd'
import type { ColumnsType, TableProps } from 'antd/es/table'
import { DownloadOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { api, cleanParams, download, errorMessage, type Page } from '@/api/client'
import { App } from 'antd'

export interface FilterField {
  name: string
  label?: string
  type?: 'input' | 'select' | 'dateRange' | 'custom'
  placeholder?: string
  options?: { label: string; value: string | number | boolean }[]
  /** 日期区间映射的两个参数名，默认 date_from / date_to */
  names?: [string, string]
  render?: () => ReactNode
  width?: number
  initial?: unknown
}

export interface ToolbarCtx<T> {
  selectedRowKeys: React.Key[]
  selectedRows: T[]
  reload: () => void
  params: Record<string, unknown>
  clearSelection: () => void
}

interface Props<T> {
  queryKey: string
  url: string
  columns: ColumnsType<T>
  filters?: FilterField[]
  extraParams?: Record<string, unknown>
  toolbar?: (ctx: ToolbarCtx<T>) => ReactNode
  title?: ReactNode
  rowSelection?: boolean
  rowKey?: string | ((r: T) => React.Key)
  exportUrl?: string
  scrollX?: number | string
  pageSize?: number
  expandable?: TableProps<T>['expandable']
  summary?: (data: T[]) => ReactNode
  /** 表头上方附加区域（如状态页签） */
  header?: ReactNode
  size?: 'small' | 'middle'
  bordered?: boolean
  card?: boolean
}

function toParams(values: Record<string, unknown>, filters: FilterField[]): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const f of filters) {
    const v = values[f.name]
    if (f.type === 'dateRange') {
      const [a, b] = f.names ?? ['date_from', 'date_to']
      const range = v as [dayjs.Dayjs, dayjs.Dayjs] | undefined
      if (range?.[0]) out[a] = range[0].format('YYYY-MM-DD')
      if (range?.[1]) out[b] = range[1].format('YYYY-MM-DD')
    } else {
      out[f.name] = v
    }
  }
  return cleanParams(out)
}

/** 通用列表：筛选表单 + 工具栏 + 分页表格（基于 react-query） */
export default function DataTable<T extends object>(props: Props<T>) {
  const {
    queryKey, url, columns, filters = [], extraParams, toolbar, title, rowSelection, rowKey = 'id', exportUrl,
    scrollX, pageSize: defaultPageSize = 20, expandable, summary, header, size = 'middle', bordered, card = true,
  } = props
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const initialValues = useMemo(() => Object.fromEntries(filters.filter((f) => f.initial !== undefined).map((f) => [f.name, f.initial])), [filters])
  const [filterParams, setFilterParams] = useState<Record<string, unknown>>(() => toParams(initialValues, filters))
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(defaultPageSize)
  const [selected, setSelected] = useState<{ keys: React.Key[]; rows: T[] }>({ keys: [], rows: [] })
  const qc = useQueryClient()

  const params = useMemo(() => cleanParams({ ...filterParams, ...(extraParams ?? {}) }), [filterParams, extraParams])
  const { data, isFetching, error } = useQuery({
    queryKey: [queryKey, url, params, page, pageSize],
    queryFn: () => api.get<Page<T>>(url, { ...params, page, page_size: pageSize }),
    placeholderData: keepPreviousData,
  })

  const reload = () => qc.invalidateQueries({ queryKey: [queryKey] })
  const clearSelection = () => setSelected({ keys: [], rows: [] })
  const onSearch = () => {
    setFilterParams(toParams(form.getFieldsValue(), filters))
    setPage(1)
    clearSelection()
  }
  const onReset = () => {
    form.resetFields()
    setFilterParams(toParams(initialValues, filters))
    setPage(1)
    clearSelection()
  }

  const ctx: ToolbarCtx<T> = { selectedRowKeys: selected.keys, selectedRows: selected.rows, reload, params, clearSelection }

  const filterForm = filters.length > 0 && (
    <Form form={form} layout="inline" initialValues={initialValues} onFinish={onSearch} style={{ rowGap: 8, marginBottom: 12 }}>
      {filters.map((f) => (
        <Form.Item key={f.name} name={f.name} label={f.label} style={{ marginBottom: 0 }}>
          {f.type === 'select' ? (
            <Select allowClear placeholder={f.placeholder ?? f.label ?? '请选择'} options={f.options} style={{ width: f.width ?? 140 }} />
          ) : f.type === 'dateRange' ? (
            <DatePicker.RangePicker style={{ width: f.width ?? 240 }} />
          ) : f.type === 'custom' && f.render ? (
            f.render()
          ) : (
            <Input allowClear placeholder={f.placeholder ?? '关键词'} style={{ width: f.width ?? 200 }} />
          )}
        </Form.Item>
      ))}
      <Form.Item style={{ marginBottom: 0 }}>
        <Space>
          <Button type="primary" htmlType="submit" icon={<SearchOutlined />}>
            查询
          </Button>
          <Button onClick={onReset}>重置</Button>
        </Space>
      </Form.Item>
    </Form>
  )

  const toolbarRow = (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, gap: 8, flexWrap: 'wrap' }}>
      <Space wrap>
        {title && <span style={{ fontWeight: 600, fontSize: 15 }}>{title}</span>}
        {toolbar?.(ctx)}
      </Space>
      <Space>
        {selected.keys.length > 0 && <span style={{ color: '#888' }}>已选 {selected.keys.length} 项</span>}
        {exportUrl && (
          <Button
            icon={<DownloadOutlined />}
            onClick={() => download(exportUrl, params).catch((e) => message.error(errorMessage(e)))}
          >
            导出
          </Button>
        )}
        <Tooltip title="刷新">
          <Button icon={<ReloadOutlined />} onClick={reload} />
        </Tooltip>
      </Space>
    </div>
  )

  const table = (
    <Table<T>
      rowKey={rowKey as TableProps<T>['rowKey']}
      size={size}
      bordered={bordered}
      columns={columns}
      dataSource={data?.items ?? []}
      loading={isFetching}
      scroll={{ x: scrollX ?? 'max-content' }}
      expandable={expandable}
      locale={error ? { emptyText: errorMessage(error) } : undefined}
      rowSelection={
        rowSelection
          ? { selectedRowKeys: selected.keys, onChange: (keys, rows) => setSelected({ keys, rows }), preserveSelectedRowKeys: true }
          : undefined
      }
      summary={summary ? () => summary(data?.items ?? []) : undefined}
      pagination={{
        current: page,
        pageSize,
        total: data?.total ?? 0,
        showSizeChanger: true,
        pageSizeOptions: [20, 50, 100, 200],
        showTotal: (t) => `共 ${t} 条`,
        onChange: (p, ps) => {
          setPage(p)
          setPageSize(ps)
        },
      }}
    />
  )

  const body = (
    <>
      {filterForm}
      {header}
      {toolbarRow}
      {table}
    </>
  )
  return card ? <Card variant="borderless">{body}</Card> : body
}

export function useReload(queryKey: string) {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: [queryKey] })
}
