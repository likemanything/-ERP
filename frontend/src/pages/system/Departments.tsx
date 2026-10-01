import { useState } from 'react'
import { Button, Form, Input, InputNumber, Space } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import { DeptSelect, UserSelect } from '@/components/selects'
import { useDeptOptions, useLabelMap, useUserOptions } from '@/hooks/useOptions'

type R = Record<string, any>

export default function Departments() {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<R | null>(null)
  const reload = useReload('depts')
  const qc = useQueryClient()
  const run = useAction()
  const deptMap = useLabelMap(useDeptOptions().data)
  const userMap = useLabelMap(useUserOptions().data)
  const done = () => { reload(); qc.invalidateQueries({ queryKey: ['options'] }) }
  return (
    <>
      <DataTable<R> queryKey="depts" url="/system/departments" title="部门" pageSize={100}
        toolbar={() => <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true) }}>新增部门</Button>}
        columns={[
          { title: '部门', dataIndex: 'name' },
          { title: '上级部门', dataIndex: 'parent_id', render: (v) => (v ? deptMap.get(v) : '-') },
          { title: '负责人', dataIndex: 'leader_id', render: (v) => (v ? userMap.get(v) : '-') },
          { title: '排序', dataIndex: 'sort' },
          { title: '操作', key: 'op', render: (_, r) => (
            <Space>
              <a onClick={() => { setEditing(r); setOpen(true) }}>编辑</a>
              <a style={{ color: '#cf1322' }} onClick={() => run(() => api.del(`/system/departments/${r.id}`), { confirm: '删除部门？', onDone: done })}>删除</a>
            </Space>
          ) },
        ]} />
      <FormModal open={open} title={editing ? '编辑部门' : '新增部门'} width={460} onCancel={() => setOpen(false)} initialValues={editing ?? { sort: 0 }}
        onSubmit={async (v) => { if (editing) await api.put(`/system/departments/${editing.id}`, v); else await api.post('/system/departments', v); done() }}>
        <Form.Item name="name" label="部门名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="parent_id" label="上级部门"><DeptSelect /></Form.Item>
        <Form.Item name="leader_id" label="负责人"><UserSelect /></Form.Item>
        <Form.Item name="sort" label="排序"><InputNumber style={{ width: '100%' }} /></Form.Item>
      </FormModal>
    </>
  )
}
