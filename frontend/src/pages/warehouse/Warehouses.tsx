import { useState } from 'react'
import { Button, Col, Form, Input, Row, Select, Space, Switch, Tag } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import DataTable, { useReload } from '@/components/DataTable'
import { FormModal, useAction } from '@/components/common'
import Perm from '@/components/Perm'
import StatusTag from '@/components/StatusTag'
import { ShopSelect, WarehouseSelect } from '@/components/selects'
import { WAREHOUSE_TYPE, dictOptions } from '@/utils/dicts'

type R = Record<string, any>

function Bins() {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<R | null>(null)
  const reload = useReload('bins')
  const run = useAction()
  return (
    <>
      <DataTable<R>
        queryKey="bins"
        url="/warehouse-bins"
        title="库位"
        pageSize={50}
        filters={[{ name: 'keyword', placeholder: '库位编码 / 库区' }, { name: 'warehouse_id', type: 'custom', render: () => <WarehouseSelect /> }]}
        toolbar={() => <Perm code="warehouse:edit"><Button icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true) }}>新增库位</Button></Perm>}
        columns={[
          { title: '库位编码', dataIndex: 'code' },
          { title: '库区', dataIndex: 'zone', render: (v) => v ?? '-' },
          { title: '类型', dataIndex: 'bin_type', render: (v) => ({ storage: '存储位', pick: '拣货位', defective: '次品位', receiving: '收货位' } as Record<string, string>)[v] ?? v },
          { title: '状态', dataIndex: 'status', render: (v) => (v === 'active' ? '启用' : '停用') },
          {
            title: '操作', key: 'op',
            render: (_, r) => (
              <Perm code="warehouse:edit">
                <Space>
                  <a onClick={() => { setEditing(r); setOpen(true) }}>编辑</a>
                  <a onClick={() => run(() => api.del(`/warehouse-bins/${r.id}`), { confirm: '删除库位？', onDone: reload })}>删除</a>
                </Space>
              </Perm>
            ),
          },
        ]}
      />
      <FormModal open={open} title={editing ? '编辑库位' : '新增库位'} width={460} onCancel={() => setOpen(false)}
        initialValues={editing ?? { bin_type: 'storage', status: 'active' }}
        onSubmit={async (v) => { if (editing) await api.put(`/warehouse-bins/${editing.id}`, v); else await api.post('/warehouse-bins', v); reload() }}>
        {!editing && <Form.Item name="warehouse_id" label="仓库" rules={[{ required: true }]}><WarehouseSelect /></Form.Item>}
        <Form.Item name="code" label="库位编码" rules={[{ required: true }]}><Input placeholder="A-01-01" /></Form.Item>
        <Form.Item name="zone" label="库区"><Input /></Form.Item>
        <Form.Item name="bin_type" label="类型"><Select options={[{ value: 'storage', label: '存储位' }, { value: 'pick', label: '拣货位' }, { value: 'defective', label: '次品位' }, { value: 'receiving', label: '收货位' }]} /></Form.Item>
        <Form.Item name="status" label="状态"><Select options={[{ value: 'active', label: '启用' }, { value: 'disabled', label: '停用' }]} /></Form.Item>
      </FormModal>
    </>
  )
}

export default function Warehouses() {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<R | null>(null)
  const reload = useReload('warehouses')
  const qc = useQueryClient()
  const run = useAction()
  const done = () => { reload(); qc.invalidateQueries({ queryKey: ['options'] }) }
  return (
    <Row gutter={16}>
      <Col xs={24} xl={15}>
        <DataTable<R>
          queryKey="warehouses"
          url="/warehouses"
          title="仓库"
          filters={[{ name: 'keyword', placeholder: '编码 / 名称' }, { name: 'warehouse_type', type: 'select', label: '类型', options: dictOptions(WAREHOUSE_TYPE) }]}
          toolbar={() => <Perm code="warehouse:edit"><Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true) }}>新增仓库</Button></Perm>}
          columns={[
            { title: '编码', dataIndex: 'code' },
            { title: '名称', dataIndex: 'name', render: (v, r) => <Space>{v}{r.is_default && <Tag color="blue">默认</Tag>}</Space> },
            { title: '类型', dataIndex: 'warehouse_type', render: (v) => <StatusTag dict={WAREHOUSE_TYPE} value={v} /> },
            { title: '国家', dataIndex: 'country', render: (v) => v ?? '-' },
            { title: '状态', dataIndex: 'status', render: (v) => (v === 'active' ? '启用' : '停用') },
            {
              title: '操作', key: 'op',
              render: (_, r) => (
                <Perm code="warehouse:edit">
                  <Space>
                    <a onClick={() => { setEditing(r); setOpen(true) }}>编辑</a>
                    <a style={{ color: '#cf1322' }} onClick={() => run(() => api.del(`/warehouses/${r.id}`), { confirm: `删除仓库「${r.name}」？`, onDone: done })}>删除</a>
                  </Space>
                </Perm>
              ),
            },
          ]}
        />
      </Col>
      <Col xs={24} xl={9}><Bins /></Col>
      <FormModal open={open} title={editing ? '编辑仓库' : '新增仓库'} width={620} onCancel={() => setOpen(false)}
        initialValues={editing ?? { warehouse_type: 'local', status: 'active', is_default: false }}
        onSubmit={async (v) => { if (editing) await api.put(`/warehouses/${editing.id}`, v); else await api.post('/warehouses', v); done() }}>
        <Row gutter={12}>
          <Col span={8}><Form.Item name="code" label="编码" rules={[{ required: true }]}><Input /></Form.Item></Col>
          <Col span={16}><Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="warehouse_type" label="类型"><Select options={dictOptions(WAREHOUSE_TYPE)} /></Form.Item></Col>
          <Col span={8}><Form.Item name="country" label="国家"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="shop_id" label="所属店铺（FBA仓）"><ShopSelect /></Form.Item></Col>
          <Col span={24}><Form.Item name="address" label="地址"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="contact" label="联系人"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="phone" label="电话"><Input /></Form.Item></Col>
          <Col span={4}><Form.Item name="is_default" label="默认仓" valuePropName="checked"><Switch /></Form.Item></Col>
          <Col span={4}><Form.Item name="status" label="状态"><Select options={[{ value: 'active', label: '启用' }, { value: 'disabled', label: '停用' }]} /></Form.Item></Col>
        </Row>
      </FormModal>
    </Row>
  )
}
