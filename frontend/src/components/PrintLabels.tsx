import { useEffect, useState } from 'react'
import { Alert, App, Col, Form, Input, InputNumber, Modal, Radio, Row, Select, Table, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api, errorMessage, openPdf } from '@/api/client'

export interface LabelLine {
  key: string | number
  listing_id?: number
  product_id?: number
  code?: string
  title?: string | null
  /** 展示用：MSKU / SKU */
  name: string
  qty: number
}

type Kind = 'fnsku' | 'sku' | 'barcode'

interface Size {
  value: string
  label: string
  sheet: boolean
  per_page: number
}

const KIND_LABEL: Record<Kind, string> = { fnsku: 'FNSKU 标签（亚马逊入仓）', sku: 'SKU 标签（自有仓）', barcode: '商品条码标签（UPC/EAN）' }

/** 标签打印弹窗：选择规格、份数，生成 PDF 在新窗口打印 */
export default function PrintLabelsModal({
  open, onClose, lines, kinds = ['fnsku', 'sku', 'barcode'],
}: {
  open: boolean
  onClose: () => void
  lines: LabelLine[]
  kinds?: Kind[]
}) {
  const { message } = App.useApp()
  const [rows, setRows] = useState<LabelLine[]>([])
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm()
  const { data: sizes } = useQuery({ queryKey: ['label-sizes'], queryFn: () => api.get<Size[]>('/print/label-sizes'), staleTime: Infinity, enabled: open })
  const size = Form.useWatch('size', form) as string | undefined
  const kind = (Form.useWatch('kind', form) as Kind | undefined) ?? kinds[0]
  const sheet = sizes?.find((s) => s.value === size)?.sheet

  useEffect(() => {
    if (open) setRows(lines.map((l) => ({ ...l })))
  }, [open, lines])

  const submit = async () => {
    const v = await form.validateFields()
    const items = rows.filter((r) => r.qty > 0 && !(kind === 'fnsku' && r.listing_id && !r.code)).map((r) => ({ listing_id: r.listing_id, product_id: r.product_id, code: r.code, title: r.title || undefined, qty: r.qty }))
    if (!items.length) {
      message.warning('请填写打印数量')
      return
    }
    setLoading(true)
    try {
      await openPdf('/print/labels.pdf', { body: { ...v, items } })
      onClose()
    } catch (e) {
      message.error(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  const missing = kind === 'fnsku' ? rows.filter((r) => r.listing_id && !r.code) : []
  const total = rows.filter((r) => !missing.includes(r)).reduce((s, r) => s + (r.qty || 0), 0)
  return (
    <Modal open={open} title="打印标签" width={760} onCancel={onClose} onOk={submit} okText={`生成 PDF（${total} 张）`} confirmLoading={loading} destroyOnHidden>
      <Form form={form} layout="vertical" initialValues={{ kind: kinds[0], size: '60x30', condition: 'New', skip: 0 }} preserve={false}>
        <Row gutter={16}>
          <Col span={24}>
            <Form.Item name="kind" label="标签类型">
              <Radio.Group options={kinds.map((k) => ({ value: k, label: KIND_LABEL[k] }))} />
            </Form.Item>
          </Col>
          <Col span={10}>
            <Form.Item name="size" label="标签规格">
              <Select options={sizes?.map((s) => ({ value: s.value, label: s.label }))} />
            </Form.Item>
          </Col>
          {kind === 'fnsku' && (
            <Col span={4}>
              <Form.Item name="condition" label="新旧状态"><Input /></Form.Item>
            </Col>
          )}
          <Col span={kind === 'fnsku' ? 6 : 10}>
            <Form.Item name="extra" label="附加文字"><Input placeholder="如 Made in China" /></Form.Item>
          </Col>
          {sheet && (
            <Col span={4}>
              <Form.Item name="skip" label="跳过格数" tooltip="A4 标签纸已用掉的格子数，从下一格开始打印">
                <InputNumber min={0} max={100} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          )}
        </Row>
      </Form>
      {missing.length > 0 && (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          title={`${missing.map((r) => r.name).join('、')} 没有 FNSKU（通常为自发货 Listing），将跳过；可改为打印 SKU 标签`} />
      )}
      <Table<LabelLine>
        size="small"
        rowKey="key"
        pagination={false}
        dataSource={rows}
        scroll={{ y: 320 }}
        columns={[
          { title: kind === 'fnsku' ? 'MSKU / FNSKU' : 'SKU', dataIndex: 'name', render: (v, r) => <div>{v}{r.code && <div><Typography.Text type="secondary" style={{ fontSize: 12 }}>{r.code}</Typography.Text></div>}</div> },
          {
            title: '标签标题（可修改）', dataIndex: 'title',
            render: (v, r, i) => <Input size="small" value={v ?? ''} onChange={(e) => setRows((x) => x.map((y, j) => (j === i ? { ...y, title: e.target.value } : y)))} placeholder={r.name} />,
          },
          {
            title: '张数', dataIndex: 'qty', width: 110,
            render: (v, _r, i) => <InputNumber size="small" min={0} max={5000} value={v} onChange={(n) => setRows((x) => x.map((y, j) => (j === i ? { ...y, qty: Number(n) || 0 } : y)))} />,
          },
        ]}
      />
    </Modal>
  )
}
