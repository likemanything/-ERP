import { useEffect, useState } from 'react'
import { Alert, App, Button, Card, Col, Form, Input, InputNumber, Row, Space, Switch, Table } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, errorMessage, type Page } from '@/api/client'
import { FormModal, useAction } from '@/components/common'
import Perm from '@/components/Perm'
import { ChannelSelect, WarehouseSelect } from '@/components/selects'
import { useBaseCurrency, usePerm } from '@/store/auth'

type L = Record<string, any>

function Levels() {
  const qc = useQueryClient()
  const run = useAction()
  const [editing, setEditing] = useState<L | null>(null)
  const [open, setOpen] = useState(false)
  const { data, isFetching } = useQuery({ queryKey: ['dist-levels'], queryFn: () => api.get<Page<L>>('/distribution/levels', { page_size: 200 }) })
  const done = () => {
    qc.invalidateQueries({ queryKey: ['dist-levels'] })
    qc.invalidateQueries({ queryKey: ['options'] })
  }
  return (
    <Card
      variant="borderless"
      title="分销等级"
      extra={<Perm code="distribution:edit"><Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true) }}>新增等级</Button></Perm>}
    >
      <Alert type="info" style={{ marginBottom: 12 }} title="分销价 = 商品的等级专属价；未设置专属价时 = 分销基础价 × 等级折扣（如 0.9 即九折）。" />
      <Table<L>
        rowKey="id"
        size="small"
        loading={isFetching}
        pagination={false}
        dataSource={data?.items ?? []}
        columns={[
          { title: '编码', dataIndex: 'code' },
          { title: '名称', dataIndex: 'name' },
          { title: '折扣', dataIndex: 'discount_rate', render: (v) => `${Number(v).toFixed(4).replace(/0+$/, '').replace(/\.$/, '')}（${(Number(v) * 100).toFixed(0)}%）` },
          { title: '排序', dataIndex: 'sort' },
          { title: '备注', dataIndex: 'remark', render: (v) => v ?? '-' },
          {
            title: '操作', key: 'op',
            render: (_, r) => (
              <Perm code="distribution:edit">
                <Space>
                  <a onClick={() => { setEditing(r); setOpen(true) }}>编辑</a>
                  <a style={{ color: '#cf1322' }} onClick={() => run(() => api.del(`/distribution/levels/${r.id}`), { confirm: `删除等级「${r.name}」？`, onDone: done })}>删除</a>
                </Space>
              </Perm>
            ),
          },
        ]}
      />
      <FormModal open={open} title={editing ? '编辑等级' : '新增等级'} width={480} onCancel={() => setOpen(false)}
        initialValues={editing ?? { discount_rate: 1, sort: 0 }}
        onSubmit={async (v) => {
          if (editing) await api.put(`/distribution/levels/${editing.id}`, v)
          else await api.post('/distribution/levels', v)
          done()
        }}>
        <Row gutter={16}>
          <Col span={12}><Form.Item name="code" label="编码" rules={[{ required: true }]}><Input placeholder="如 VIP" /></Form.Item></Col>
          <Col span={12}><Form.Item name="name" label="名称" rules={[{ required: true }]}><Input placeholder="如 VIP 分销商" /></Form.Item></Col>
          <Col span={12}><Form.Item name="discount_rate" label="折扣系数" extra="1 = 原价，0.9 = 九折" rules={[{ required: true }]}><InputNumber min={0.01} max={10} step={0.05} style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={12}><Form.Item name="sort" label="排序"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
          <Col span={24}><Form.Item name="remark" label="备注"><Input /></Form.Item></Col>
        </Row>
      </FormModal>
    </Card>
  )
}

function Params() {
  const { message } = App.useApp()
  const can = usePerm()
  const cur = useBaseCurrency()
  const [form] = Form.useForm()
  const { data } = useQuery({ queryKey: ['dist-settings'], queryFn: () => api.get<L>('/distribution/settings') })
  useEffect(() => { if (data) form.setFieldsValue(data) }, [data, form])
  const save = async () => {
    try {
      const v = await form.validateFields()
      form.setFieldsValue(await api.put('/distribution/settings', v))
      message.success('分销参数已保存')
    } catch (e) {
      if (e && typeof e === 'object' && 'errorFields' in e) return
      message.error(errorMessage(e))
    }
  }
  const editable = can('distribution:setting')
  return (
    <Card variant="borderless" title="分销参数" extra={editable && <Button type="primary" onClick={save}>保存</Button>}>
      <Form form={form} layout="vertical" disabled={!editable}>
        <Form.Item name="warehouse_ids" label="分销发货仓" extra="门户展示的可售库存 = 这些仓库的可用库存之和；为空则使用全部自有仓库">
          <WarehouseSelect mode="multiple" excludeFba allowClear placeholder="全部自有仓库" />
        </Form.Item>
        <Form.Item name="channel_ids" label="分销商可选物流渠道" extra="一件代发按所选渠道的运费规则计算运费；为空则开放全部启用的尾程渠道">
          <ChannelSelect mode="multiple" allowClear placeholder="全部尾程渠道" />
        </Form.Item>
        <Row gutter={16}>
          <Col span={8}>
            <Form.Item name="freight_markup_rate" label="运费加价比例" extra="0.1 = 在渠道运费基础上加收 10%">
              <InputNumber min={0} max={10} step={0.05} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="handling_fee_per_order" label={`代发操作费 / 单（${cur}）`} extra="按分销商币种折算收取">
              <InputNumber min={0} precision={2} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="handling_fee_per_item" label={`代发操作费 / 件（${cur}）`}>
              <InputNumber min={0} precision={2} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="auto_audit" label="库存充足时自动审核" valuePropName="checked" extra="开启后分销订单下单即锁定库存，进入待发货">
              <Switch />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="allow_cancel_after_audit" label="允许分销商取消已审核订单" valuePropName="checked" extra="发货前均可自助取消并自动退款">
              <Switch />
            </Form.Item>
          </Col>
        </Row>
      </Form>
    </Card>
  )
}

export default function DistributionSettings() {
  return (
    <Row gutter={16}>
      <Col xs={24} xl={12}><Params /></Col>
      <Col xs={24} xl={12}><Levels /></Col>
    </Row>
  )
}
