import { Table } from 'antd'
import DataTable from '@/components/DataTable'
import { SupplierSelect } from '@/components/selects'
import { usePerm } from '@/store/auth'
import { fmtDateTime, fmtMoney } from '@/utils/format'

type R = Record<string, any>

export default function Receipts() {
  const can = usePerm()
  return (
    <DataTable<R>
      queryKey="purchase-receipts"
      url="/purchase-receipts"
      title="采购到货入库记录"
      filters={[
        { name: 'keyword', placeholder: '入库单号 / 物流单号' },
        { name: 'supplier_id', type: 'custom', render: () => <SupplierSelect /> },
      ]}
      expandable={{
        expandedRowRender: (r) => (
          <Table<R> size="small" rowKey="id" pagination={false} dataSource={r.lines} columns={[
            { title: 'SKU', dataIndex: 'sku' }, { title: '品名', dataIndex: 'product_name' },
            { title: '良品', dataIndex: 'qty_good' }, { title: '次品', dataIndex: 'qty_defective' },
            { title: '批次号', dataIndex: 'batch_no', render: (v) => v ?? '-' },
            ...(can('product:cost:view') ? [
              { title: '单位采购成本', dataIndex: 'unit_purchase_cost', render: (v: number) => fmtMoney(v, undefined, 4) },
              { title: '单位运杂费', dataIndex: 'unit_freight_cost', render: (v: number) => fmtMoney(v, undefined, 4) },
            ] : []),
          ]} />
        ),
      }}
      columns={[
        { title: '入库单号', dataIndex: 'receipt_no' },
        { title: '采购单号', dataIndex: 'po_no' },
        { title: '供应商', dataIndex: 'supplier_name' },
        { title: '入库仓', dataIndex: 'warehouse_name' },
        { title: '良品数', key: 'good', render: (_, r) => r.lines.reduce((s: number, l: R) => s + l.qty_good, 0) },
        { title: '次品数', key: 'bad', render: (_, r) => r.lines.reduce((s: number, l: R) => s + l.qty_defective, 0) },
        { title: '物流单号', dataIndex: 'tracking_no', render: (v) => v ?? '-' },
        { title: '入库时间', dataIndex: 'received_at', render: fmtDateTime },
      ]}
    />
  )
}
