import DataTable from '@/components/DataTable'
import StatusTag from '@/components/StatusTag'
import { WarehouseSelect } from '@/components/selects'
import { usePerm } from '@/store/auth'
import { LEDGER_TYPE, dictOptions } from '@/utils/dicts'
import { fmtDateTime, fmtMoney } from '@/utils/format'

type R = Record<string, any>

export default function Ledger() {
  const can = usePerm()
  return (
    <DataTable<R>
      queryKey="ledger"
      url="/inventory/ledger"
      title="库存流水"
      pageSize={50}
      filters={[
        { name: 'keyword', placeholder: 'SKU / 品名 / 单号' },
        { name: 'warehouse_id', type: 'custom', render: () => <WarehouseSelect /> },
        { name: 'change_type', type: 'select', label: '类型', options: dictOptions(LEDGER_TYPE), width: 160 },
        { name: 'date', type: 'dateRange', label: '日期' },
      ]}
      columns={[
        { title: '时间', dataIndex: 'created_at', render: fmtDateTime },
        { title: '仓库', dataIndex: 'warehouse_name' },
        { title: 'SKU', dataIndex: 'sku' },
        { title: '品名', dataIndex: 'product_name', ellipsis: true },
        { title: '类型', dataIndex: 'change_type', render: (v) => <StatusTag dict={LEDGER_TYPE} value={v} /> },
        { title: '库存类别', dataIndex: 'stock_type', render: (v) => ({ good: '良品', defective: '次品', locked: '锁定' } as Record<string, string>)[v] ?? v },
        { title: '变动', dataIndex: 'qty_change', align: 'right', render: (v) => <b style={{ color: v > 0 ? '#389e0d' : '#cf1322' }}>{v > 0 ? `+${v}` : v}</b> },
        { title: '结存', dataIndex: 'qty_after', align: 'right' },
        ...(can('product:cost:view') ? [
          { title: '单位成本', key: 'uc', align: 'right' as const, render: (_: unknown, r: R) => fmtMoney((r.unit_purchase_cost ?? 0) + (r.unit_freight_cost ?? 0), undefined, 4) },
          { title: '金额', dataIndex: 'amount', align: 'right' as const, render: (v: number) => fmtMoney(v) },
        ] : []),
        { title: '关联单据', dataIndex: 'ref_no', render: (v) => v ?? '-' },
        { title: '备注', dataIndex: 'remark', ellipsis: true, render: (v) => v ?? '-' },
      ]}
    />
  )
}
