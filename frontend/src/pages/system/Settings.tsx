import { useEffect } from 'react'
import { App, Button, Card, Col, Form, Input, InputNumber, Row, Select, Switch, Typography } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, errorMessage } from '@/api/client'
import { WarehouseSelect } from '@/components/selects'
import { useAuth } from '@/store/auth'
import { ALLOCATION_METHOD, dictOptions } from '@/utils/dicts'

interface SettingItem {
  key: string
  value: unknown
  label: string
  description?: string
}

function SettingInput({ item }: { item: SettingItem }) {
  if (item.key === 'order.default_warehouse_id') return <WarehouseSelect excludeFba />
  if (item.key === 'fba.default_allocation') return <Select options={dictOptions(ALLOCATION_METHOD)} style={{ width: 200 }} />
  if (typeof item.value === 'boolean') return <Switch />
  if (typeof item.value === 'number' || item.value === null) return <InputNumber style={{ width: 200 }} />
  return <Input style={{ width: 300 }} />
}

export default function Settings() {
  const { message } = App.useApp()
  const qc = useQueryClient()
  const setProfile = useAuth((s) => s.setProfile)
  const { user, permissions } = useAuth()
  // 分销参数在「分销设置」页单独维护
  const { data: items } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get<SettingItem[]>('/system/settings'),
    select: (list) => list.filter((i) => !i.key.startsWith('distribution.')),
  })
  const { data: tenant } = useQuery({ queryKey: ['tenant'], queryFn: () => api.get('/system/tenant') })
  const [form] = Form.useForm()
  const [tForm] = Form.useForm()
  useEffect(() => { if (items) form.setFieldsValue(Object.fromEntries(items.map((i) => [i.key, i.value]))) }, [items, form])
  useEffect(() => { if (tenant) tForm.setFieldsValue(tenant) }, [tenant, tForm])

  const saveSettings = async () => {
    try {
      const values = Object.fromEntries(Object.entries(form.getFieldsValue(true)).filter(([k]) => !k.startsWith('distribution.')))
      await api.put('/system/settings', { values })
      message.success('系统参数已保存')
      qc.invalidateQueries({ queryKey: ['settings'] })
    } catch (e) {
      message.error(errorMessage(e))
    }
  }
  const saveTenant = async () => {
    try {
      const t = await api.put('/system/tenant', await tForm.validateFields())
      if (user) setProfile(user, t, permissions)
      message.success('企业信息已保存')
    } catch (e) {
      message.error(errorMessage(e))
    }
  }
  return (
    <Row gutter={16}>
      <Col xs={24} lg={14}>
        <Card variant="borderless" title="业务参数" extra={<Button type="primary" onClick={saveSettings}>保存</Button>}>
          <Form form={form} layout="horizontal" labelCol={{ span: 9 }} wrapperCol={{ span: 15 }}>
            {(items ?? []).map((i) => (
              <Form.Item key={i.key} name={i.key} label={i.label} valuePropName={typeof i.value === 'boolean' ? 'checked' : 'value'}
                extra={i.description}>
                <SettingInput item={i} />
              </Form.Item>
            ))}
          </Form>
        </Card>
      </Col>
      <Col xs={24} lg={10}>
        <Card variant="borderless" title="企业信息" extra={<Button type="primary" onClick={saveTenant}>保存</Button>}>
          <Form form={tForm} layout="vertical">
            <Form.Item label="企业编码"><Typography.Text copyable>{(tenant as Record<string, string> | undefined)?.code}</Typography.Text></Form.Item>
            <Form.Item name="name" label="企业名称" rules={[{ required: true }]}><Input /></Form.Item>
            <Form.Item name="base_currency" label="本位币（利润、成本统一折算币种）" extra="修改本位币后请同步维护对应汇率">
              <Select options={['CNY', 'USD', 'HKD', 'EUR', 'GBP'].map((c) => ({ value: c, label: c }))} />
            </Form.Item>
            <Form.Item name="timezone" label="时区"><Input /></Form.Item>
            <Form.Item name="contact_name" label="联系人"><Input /></Form.Item>
            <Form.Item name="contact_phone" label="联系电话"><Input /></Form.Item>
          </Form>
        </Card>
      </Col>
    </Row>
  )
}
