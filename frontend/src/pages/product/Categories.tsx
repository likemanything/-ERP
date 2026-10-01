import { useState } from 'react'
import { Button, Col, Form, Input, InputNumber, Row, Space } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import Perm from '@/components/Perm'
import { CategorySelect } from '@/components/selects'
import { useCategoryOptions, useLabelMap } from '@/hooks/useOptions'

type Row = Record<string, any>

function SimpleCrud({ kind }: { kind: 'category' | 'brand' }) {
  const url = kind === 'category' ? '/product-categories' : '/product-brands'
  const label = kind === 'category' ? '分类' : '品牌'
  const [editing, setEditing] = useState<Row | null>(null)
  const [open, setOpen] = useState(false)
  const reload = useReload(url)
  const qc = useQueryClient()
  const run = useAction()
  const { data: cats } = useCategoryOptions()
  const catMap = useLabelMap(cats)
  const done = () => {
    reload()
    qc.invalidateQueries({ queryKey: ['options'] })
  }
  return (
    <>
      <DataTable<Row>
        queryKey={url}
        url={url}
        title={`产品${label}`}
        pageSize={50}
        filters={[{ name: 'keyword', placeholder: `${label}名称` }]}
        toolbar={() => (
          <Perm code="product:edit">
            <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true) }}>新增{label}</Button>
          </Perm>
        )}
        columns={[
          { title: '名称', dataIndex: 'name' },
          { title: '编码', dataIndex: 'code', render: (v) => v ?? '-' },
          ...(kind === 'category'
            ? [{ title: '上级分类', dataIndex: 'parent_id', render: (v: number) => (v ? catMap.get(v) ?? v : '-') }, { title: '排序', dataIndex: 'sort' }]
            : [{ title: '备注', dataIndex: 'remark', render: (v: string) => v ?? '-' }]),
          {
            title: '操作', key: 'op',
            render: (_, r) => (
              <Perm code="product:edit">
                <Space>
                  <a onClick={() => { setEditing(r); setOpen(true) }}>编辑</a>
                  <a style={{ color: '#ff4d4f' }} onClick={() => run(() => api.del(`${url}/${r.id}`), { confirm: `删除${label}「${r.name}」？`, onDone: done })}>删除</a>
                </Space>
              </Perm>
            ),
          },
        ]}
      />
      <FormModal
        open={open}
        title={`${editing ? '编辑' : '新增'}${label}`}
        width={480}
        onCancel={() => setOpen(false)}
        initialValues={editing ?? { sort: 0 }}
        onSubmit={async (v) => {
          if (editing) await api.put(`${url}/${editing.id}`, v)
          else await api.post(url, v)
          done()
        }}
      >
        <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="code" label="编码"><Input /></Form.Item>
        {kind === 'category' ? (
          <>
            <Form.Item name="parent_id" label="上级分类"><CategorySelect /></Form.Item>
            <Form.Item name="sort" label="排序"><InputNumber style={{ width: '100%' }} /></Form.Item>
          </>
        ) : (
          <Form.Item name="remark" label="备注"><Input /></Form.Item>
        )}
      </FormModal>
    </>
  )
}

export default function Categories() {
  return (
    <Row gutter={16}>
      <Col xs={24} lg={14}><SimpleCrud kind="category" /></Col>
      <Col xs={24} lg={10}><SimpleCrud kind="brand" /></Col>
    </Row>
  )
}
