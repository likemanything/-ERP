import { useState } from 'react'
import { Button, Tag, Tooltip } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import DataTable, { useReload } from '@/components/DataTable'
import { ImportModal } from '@/components/common'
import Perm from '@/components/Perm'
import ProductCell from '@/components/ProductCell'
import { ShopSelect } from '@/components/selects'
import { fmtDateTime } from '@/utils/format'

type R = Record<string, any>

export default function FbaInventory() {
  const [open, setOpen] = useState(false)
  const reload = useReload('fba-inventory')
  return (
    <>
      <DataTable<R>
        queryKey="fba-inventory"
        url="/fba-inventory"
        title="FBA 库存（平台快照）"
        filters={[{ name: 'keyword', placeholder: 'MSKU / FNSKU / ASIN' }, { name: 'shop_id', type: 'custom', render: () => <ShopSelect /> }]}
        toolbar={() => <Perm code="fba:shipment:edit"><Button icon={<UploadOutlined />} onClick={() => setOpen(true)}>导入库存报告</Button></Perm>}
        columns={[
          { title: 'Listing', key: 'l', fixed: 'left', render: (_, r) => <ProductCell image={r.image_url} title={r.msku} sub={r.title} extra={`${r.asin ?? '-'} · ${r.fnsku ?? '-'}`} /> },
          { title: '店铺', dataIndex: 'shop_name' },
          { title: 'SKU', dataIndex: 'sku', render: (v) => v ?? <Tag color="orange">未配对</Tag> },
          { title: '可售', dataIndex: 'fulfillable', align: 'right', render: (v) => <b>{v}</b> },
          { title: '预留', dataIndex: 'reserved', align: 'right' },
          { title: '计划入库', dataIndex: 'inbound_working', align: 'right' },
          { title: '在途', dataIndex: 'inbound_shipped', align: 'right' },
          { title: '入库中', dataIndex: 'inbound_receiving', align: 'right' },
          { title: '不可售', dataIndex: 'unfulfillable', align: 'right', render: (v) => (v ? <span style={{ color: '#cf1322' }}>{v}</span> : 0) },
          { title: '30天日均', dataIndex: 'daily_sales', align: 'right' },
          {
            title: <Tooltip title="(可售 + 预留) ÷ 日均">可售天数</Tooltip>, dataIndex: 'days_of_supply', align: 'right',
            render: (v) => (v === null || v === undefined ? '-' : <Tag color={v < 15 ? 'red' : v < 30 ? 'orange' : 'green'}>{v} 天</Tag>),
          },
          { title: '更新时间', dataIndex: 'snapshot_at', render: fmtDateTime },
        ]}
      />
      <ImportModal open={open} onClose={() => setOpen(false)} title="导入 FBA 库存" uploadUrl="/fba-inventory/import"
        templateUrl="/fba-inventory/import-template" onDone={reload} />
    </>
  )
}
