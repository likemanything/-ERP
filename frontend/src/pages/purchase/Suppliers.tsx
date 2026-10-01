import { useState } from 'react'
import { Button, Col, Form, Input, InputNumber, Rate, Row, Select, Space } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import Perm from '@/components/Perm'
import { CurrencySelect, UserSelect } from '@/components/selects'
import { SETTLEMENT_TYPE, dictOptions } from '@/utils/dicts'

type S = Record<string, any>

export default function Suppliers() {
  const [editing, setEditing] = useState<S | null>(null)
  const [open, setOpen] = useState(false)
  const reload = useReload('suppliers')
  const qc = useQueryClient()
  const run = useAction()
  const done = () => { reload(); qc.invalidateQueries({ queryKey: ['options'] }) }
  return (
    <>
      <DataTable<S>
        queryKey="suppliers"
        url="/suppliers"
        filters={[
          { name: 'keyword', placeholder: '编码 / 名称 / 联系人 / 电话' },
          { name: 'status', type: 'select', label: '状态', options: [{ label: '正常', value: 'active' }, { label: '停用', value: 'disabled' }] },
          { name: 'settlement_type', type: 'select', label: '结算方式', options: dictOptions(SETTLEMENT_TYPE) },
        ]}
        toolbar={() => <Perm code="supplier:edit"><Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true) }}>新增供应商</Button></Perm>}
        columns={[
          { title: '编码', dataIndex: 'code' },
          { title: '名称', dataIndex: 'name', render: (v, r) => (r.website ? <a href={r.website} target="_blank" rel="noreferrer">{v}</a> : v) },
          { title: '联系人', dataIndex: 'contact', render: (v, r) => `${v ?? '-'} ${r.phone ?? ''}` },
          { title: '结算方式', dataIndex: 'settlement_type', render: (v, r) => `${SETTLEMENT_TYPE[v]?.[0] ?? v}${r.payment_days ? `（${r.payment_days}天）` : ''}` },
          { title: '币种', dataIndex: 'currency' },
          { title: '评级', dataIndex: 'rating', render: (v) => <Rate disabled value={v} style={{ fontSize: 12 }} /> },
          { title: '状态', dataIndex: 'status', render: (v) => (v === 'active' ? '正常' : '停用') },
          {
            title: '操作', key: 'op',
            render: (_, r) => (
              <Perm code="supplier:edit">
                <Space>
                  <a onClick={() => { setEditing(r); setOpen(true) }}>编辑</a>
                  <a style={{ color: '#cf1322' }} onClick={() => run(() => api.del(`/suppliers/${r.id}`), { confirm: `删除供应商「${r.name}」？`, onDone: done })}>删除</a>
                </Space>
              </Perm>
            ),
          },
        ]}
      />
      <FormModal open={open} title={editing ? '编辑供应商' : '新增供应商'} width={760} onCancel={() => setOpen(false)}
        initialValues={editing ?? { settlement_type: 'cash', payment_days: 0, currency: 'CNY', rating: 3, status: 'active' }}
        onSubmit={async (v) => {
          if (editing) await api.put(`/suppliers/${editing.id}`, v)
          else await api.post('/suppliers', v)
          done()
        }}>
        <Row gutter={16}>
          <Col span={8}><Form.Item name="code" label="编码（为空自动生成）"><Input /></Form.Item></Col>
          <Col span={16}><Form.Item name="name" label="供应商名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="contact" label="联系人"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="phone" label="电话"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="email" label="邮箱"><Input /></Form.Item></Col>
          <Col span={16}><Form.Item name="address" label="地址"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="website" label="网店链接"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="settlement_type" label="结算方式"><Select options={dictOptions(SETTLEMENT_TYPE)} /></Form.Item></Col>
          <Col span={8}><Form.Item name="payment_days" label="账期（天）"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={8}><Form.Item name="currency" label="结算币种"><CurrencySelect /></Form.Item></Col>
          <Col span={8}><Form.Item name="bank_name" label="开户行"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="bank_account" label="银行账号"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="account_name" label="户名"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="purchaser_id" label="对接采购"><UserSelect /></Form.Item></Col>
          <Col span={8}><Form.Item name="rating" label="评级"><Rate /></Form.Item></Col>
          <Col span={8}><Form.Item name="status" label="状态"><Select options={[{ value: 'active', label: '正常' }, { value: 'disabled', label: '停用' }]} /></Form.Item></Col>
          <Col span={24}><Form.Item name="remark" label="备注"><Input.TextArea rows={2} /></Form.Item></Col>
        </Row>
      </FormModal>
    </>
  )
}
