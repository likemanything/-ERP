import { useMemo, useState } from 'react'
import { Button, Card, Form, Input, Space, Table, Tag, Tree } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { FormModal, useAction } from '@/components/common'

type R = Record<string, any>

interface PermGroup {
  key: string
  name: string
  children: { code: string; name: string }[]
}

function PermTree({ value = [], onChange }: { value?: string[]; onChange?: (v: string[]) => void }) {
  const { data } = useQuery({ queryKey: ['perm-tree'], queryFn: () => api.get<PermGroup[]>('/system/permissions') })
  const treeData = useMemo(() => (data ?? []).map((g) => ({
    key: `g:${g.key}`, title: g.name, children: g.children.map((p) => ({ key: p.code, title: `${p.name}（${p.code}）` })),
  })), [data])
  return (
    <div style={{ maxHeight: 420, overflow: 'auto', border: '1px solid #f0f0f0', borderRadius: 6, padding: 8 }}>
      <Tree checkable defaultExpandAll treeData={treeData} checkedKeys={value} selectable={false}
        onCheck={(keys) => onChange?.((keys as string[]).filter((k) => !k.startsWith('g:')))} />
    </div>
  )
}

export default function Roles() {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<R | null>(null)
  const qc = useQueryClient()
  const run = useAction()
  const { data, isFetching } = useQuery({ queryKey: ['roles'], queryFn: () => api.get<R[]>('/system/roles') })
  const reload = () => { qc.invalidateQueries({ queryKey: ['roles'] }); qc.invalidateQueries({ queryKey: ['options'] }) }
  return (
    <Card variant="borderless" title="角色与权限" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true) }}>新增角色</Button>}>
      <Table<R> rowKey="id" loading={isFetching} dataSource={data ?? []} pagination={false} columns={[
        { title: '角色', dataIndex: 'name', render: (v, r) => <Space>{v}{r.is_system && <Tag>预置</Tag>}</Space> },
        { title: '编码', dataIndex: 'code' },
        { title: '说明', dataIndex: 'description', render: (v) => v ?? '-' },
        { title: '权限数', dataIndex: 'permissions', render: (v: string[]) => v.length },
        { title: '操作', key: 'op', render: (_, r) => (
          <Space>
            <a onClick={() => { setEditing(r); setOpen(true) }}>编辑权限</a>
            <a style={{ color: '#cf1322' }} onClick={() => run(() => api.del(`/system/roles/${r.id}`), { confirm: `删除角色「${r.name}」？`, onDone: reload })}>删除</a>
          </Space>
        ) },
      ]} />
      <FormModal open={open} title={editing ? `编辑角色 ${editing.name}` : '新增角色'} width={720} onCancel={() => setOpen(false)}
        initialValues={editing ?? { permissions: [] }}
        onSubmit={async (v) => {
          if (editing) await api.put(`/system/roles/${editing.id}`, { name: v.name, description: v.description, permissions: v.permissions })
          else await api.post('/system/roles', v)
          reload()
        }}>
        <Space style={{ width: '100%' }} align="start">
          <Form.Item name="name" label="角色名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="code" label="角色编码" rules={[{ required: true }]}><Input disabled={!!editing} /></Form.Item>
          <Form.Item name="description" label="说明"><Input style={{ width: 240 }} /></Form.Item>
        </Space>
        <Form.Item name="permissions" label="功能权限"><PermTree /></Form.Item>
      </FormModal>
    </Card>
  )
}
