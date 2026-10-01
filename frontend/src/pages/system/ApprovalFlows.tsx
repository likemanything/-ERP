import { useState } from 'react'
import { Alert, Button, Card, Col, Form, Input, InputNumber, Row, Select, Space, Switch, Table, Tag, Typography } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { FormModal, useAction } from '@/components/common'
import { RoleSelect, UserSelect } from '@/components/selects'
import { useLabelMap, useRoleOptions, useUserOptions } from '@/hooks/useOptions'
import { useBaseCurrency } from '@/store/auth'
import { fmtMoney } from '@/utils/format'

type Flow = Record<string, any>

const DOC_LABEL: Record<string, string> = { purchase_order: '采购单', payment_request: '请款单', recharge: '分销商充值' }

/** 审批节点编辑（Form.List），需放在 Form 内部 */
function StepsEditor() {
  const form = Form.useFormInstance()
  return (
    <Form.List name="steps">
      {(fields, { add, remove }) => (
        <div style={{ marginTop: 8 }}>
          {fields.map((f, i) => (
            <Row key={f.key} gutter={8} align="top">
              <Col span={1} style={{ paddingTop: 5 }}><Tag>{i + 1}</Tag></Col>
              <Col span={5}><Form.Item name={[f.name, 'name']} rules={[{ required: true, message: '节点名称' }]}><Input placeholder="节点名称" /></Form.Item></Col>
              <Col span={4}>
                <Form.Item name={[f.name, 'approver_type']}>
                  <Select options={[{ value: 'user', label: '指定人员' }, { value: 'role', label: '指定角色' }]}
                    onChange={() => form.setFieldValue(['steps', f.name, 'approver_ids'], [])} />
                </Form.Item>
              </Col>
              <Col span={9}>
                <Form.Item noStyle shouldUpdate>
                  {({ getFieldValue }) => (
                    <Form.Item name={[f.name, 'approver_ids']} rules={[{ required: true, message: '请选择审批人' }]}>
                      {getFieldValue(['steps', f.name, 'approver_type']) === 'role'
                        ? <RoleSelect mode="multiple" placeholder="选择角色" />
                        : <UserSelect mode="multiple" placeholder="选择人员" />}
                    </Form.Item>
                  )}
                </Form.Item>
              </Col>
              <Col span={4}>
                <Form.Item name={[f.name, 'mode']}>
                  <Select options={[{ value: 'any', label: '或签（一人通过）' }, { value: 'all', label: '会签（全部通过）' }]} />
                </Form.Item>
              </Col>
              <Col span={1} style={{ paddingTop: 4 }}>
                {fields.length > 1 && <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(f.name)} />}
              </Col>
            </Row>
          ))}
          <Button type="dashed" block icon={<PlusOutlined />} disabled={fields.length >= 10}
            onClick={() => add({ name: `第${fields.length + 1}级审批`, approver_type: 'user', approver_ids: [], mode: 'any' })}>
            添加审批节点
          </Button>
        </div>
      )}
    </Form.List>
  )
}

export default function ApprovalFlows() {
  const qc = useQueryClient()
  const run = useAction()
  const cur = useBaseCurrency()
  const [editing, setEditing] = useState<Flow | null>(null)
  const [open, setOpen] = useState(false)
  const [modalKey, setModalKey] = useState(0)
  const { data, isFetching } = useQuery({ queryKey: ['approval-flows'], queryFn: () => api.get<Flow[]>('/approval/flows') })
  const users = useLabelMap(useUserOptions().data)
  const roles = useLabelMap(useRoleOptions().data)
  const reload = () => qc.invalidateQueries({ queryKey: ['approval-flows'] })
  const approverText = (s: Flow) =>
    (s.approver_ids as number[]).map((id) => (s.approver_type === 'role' ? `角色:${roles.get(id) ?? id}` : users.get(id) ?? id)).join('、')

  return (
    <Card variant="borderless" title="审批流程" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setModalKey((k) => k + 1); setOpen(true) }}>新增流程</Button>}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        title="单据提交时按“单据类型 + 金额（折算本位币）”匹配启用的流程：金额 ≥ 门槛的流程中取门槛最高的一个；未匹配到流程时沿用原来的单级审批（按角色权限）。"
        description="每一级可指定人员或角色：或签 = 任一审批人通过即进入下一级；会签 = 所有人员（角色则每个角色至少一人）通过。任一级驳回即结束，单据退回。管理员可代审批。"
      />
      <Table<Flow>
        rowKey="id"
        loading={isFetching}
        dataSource={data ?? []}
        pagination={false}
        columns={[
          { title: '单据类型', dataIndex: 'doc_type', render: (v) => <Tag color="blue">{DOC_LABEL[v] ?? v}</Tag> },
          { title: '流程名称', dataIndex: 'name' },
          { title: '适用金额', dataIndex: 'min_amount', render: (v) => (v > 0 ? `≥ ${fmtMoney(v, cur)}` : '全部') },
          {
            title: '审批节点', dataIndex: 'steps',
            render: (steps: Flow[]) => (
              <Space orientation="vertical" size={2}>
                {steps.map((s, i) => (
                  <span key={i} style={{ fontSize: 12 }}>
                    {i + 1}. <b>{s.name}</b>：{approverText(s)}{s.approver_ids.length > 1 || s.approver_type === 'role' ? (s.mode === 'all' ? '（会签）' : '（或签）') : ''}
                  </span>
                ))}
              </Space>
            ),
          },
          { title: '状态', dataIndex: 'is_active', render: (v, r) => <Switch size="small" checked={v} onChange={(c) => run(() => api.put(`/approval/flows/${r.id}`, { is_active: c }), { onDone: reload })} /> },
          {
            title: '操作', key: 'op',
            render: (_, r) => (
              <Space>
                <a onClick={() => { setEditing(r); setModalKey((k) => k + 1); setOpen(true) }}>编辑</a>
                <a style={{ color: '#cf1322' }} onClick={() => run(() => api.del(`/approval/flows/${r.id}`), { confirm: `删除流程「${r.name}」？`, onDone: reload })}>删除</a>
              </Space>
            ),
          },
        ]}
      />
      <FormModal
        key={modalKey}
        open={open}
        preserve
        title={editing ? `编辑流程：${editing.name}` : '新增审批流程'}
        width={860}
        onCancel={() => setOpen(false)}
        initialValues={editing ?? { doc_type: 'purchase_order', min_amount: 0, is_active: true, steps: [{ name: '部门主管', approver_type: 'user', approver_ids: [], mode: 'any' }] }}
        onSubmit={async (v) => {
          if (editing) await api.put(`/approval/flows/${editing.id}`, { ...v, doc_type: undefined })
          else await api.post('/approval/flows', v)
          reload()
        }}
      >
        <Row gutter={16}>
          <Col span={8}><Form.Item name="doc_type" label="单据类型" rules={[{ required: true }]}><Select disabled={!!editing} options={Object.entries(DOC_LABEL).map(([value, label]) => ({ value, label }))} /></Form.Item></Col>
          <Col span={8}><Form.Item name="name" label="流程名称" rules={[{ required: true }]}><Input placeholder="如：大额采购审批" /></Form.Item></Col>
          <Col span={5}><Form.Item name="min_amount" label={`金额门槛（${cur}）`} tooltip="单据金额折算本位币后 ≥ 该值时使用本流程；0 表示全部"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={3}><Form.Item name="is_active" label="启用" valuePropName="checked"><Switch /></Form.Item></Col>
        </Row>
        <Typography.Text strong>审批节点（按顺序逐级审批）</Typography.Text>
        <StepsEditor />
      </FormModal>
    </Card>
  )
}
