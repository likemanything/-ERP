import { Tag } from 'antd'
import DataTable from '@/components/DataTable'
import { WarehouseSelect } from '@/components/selects'
import { usePerm } from '@/store/auth'
import { fmtDateTime, fmtMoney } from '@/utils/format'

type R = Record<string, any>

const ageColor = (d: number) => (d > 180 ? 'red' : d > 90 ? 'orange' : d > 30 ? 'gold' : 'green')

export default function Batches() {
  const can = usePerm()
  return (
    <DataTable<R>
      queryKey="batches"
      url="/inventory/batches"
      title="库存批次（先进先出成本层）"
      pageSize={50}
      filters={[
        { name: 'keyword', placeholder: 'SKU / 品名 / 批次号' },
        { name: 'warehouse_id', type: 'custom', render: () => <WarehouseSelect /> },
        { name: 'remaining_only', type: 'select', label: '范围', initial: true, options: [{ label: '仅有结存', value: true }, { label: '全部批次', value: false }] },
      ]}
      columns={[
        { title: '批次号', dataIndex: 'batch_no' },
        { title: '仓库', dataIndex: 'warehouse_name' },
        { title: 'SKU', dataIndex: 'sku' },
        { title: '品名', dataIndex: 'product_name', ellipsis: true },
        { title: '来源单据', dataIndex: 'source_no', render: (v) => v ?? '-' },
        { title: '入库时间', dataIndex: 'received_at', render: fmtDateTime },
        { title: '库龄', dataIndex: 'age_days', render: (v) => <Tag color={ageColor(v)}>{v} 天</Tag> },
        { title: '入库数量', dataIndex: 'qty_in', align: 'right' },
        { title: '结存', dataIndex: 'qty_remaining', align: 'right', render: (v) => <b>{v}</b> },
        ...(can('product:cost:view') ? [
          { title: '采购单价', dataIndex: 'unit_purchase_cost', align: 'right' as const, render: (v: number) => fmtMoney(v, undefined, 4) },
          { title: '物流单价', dataIndex: 'unit_freight_cost', align: 'right' as const, render: (v: number) => fmtMoney(v, undefined, 4) },
          { title: '结存金额', key: 'v', align: 'right' as const, render: (_: unknown, r: R) => fmtMoney(r.qty_remaining * ((r.unit_purchase_cost ?? 0) + (r.unit_freight_cost ?? 0))) },
        ] : []),
      ]}
    />
  )
}
