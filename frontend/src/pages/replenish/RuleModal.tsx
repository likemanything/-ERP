import { Col, Form, InputNumber, Row, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { FormModal } from '@/components/common'

/** 补货参数设置：listingId 为空时编辑企业默认参数，否则编辑该 Listing 的个性化参数（空值继承默认） */
export default function RuleModal({ open, listingId, title, onClose, onDone }: {
  open: boolean
  listingId?: number | null
  title?: string
  onClose: () => void
  onDone: () => void
}) {
  const url = listingId ? `/replenishment/rules/${listingId}` : '/replenishment/rule'
  const { data, isFetched } = useQuery({ queryKey: ['replenish-rule', listingId ?? 0], queryFn: () => api.get(url), enabled: open })
  const n = (name: string, label: string, step = 1) => (
    <Col span={8}>
      <Form.Item name={name} label={label}>
        <InputNumber min={0} step={step} style={{ width: '100%' }} placeholder={listingId ? '继承默认' : undefined} />
      </Form.Item>
    </Col>
  )
  if (open && !isFetched) return null
  return (
    <FormModal open={open} title={title ?? (listingId ? '个性化补货参数' : '默认补货参数')} width={640} onCancel={onClose}
      initialValues={data ?? {}}
      onSubmit={async (v) => { await api.put(url, v); onDone() }}>
      <Typography.Paragraph type="secondary">
        日均销量 = 近7/14/30天日均按权重加权 × 增长系数；建议发货量 = 日均 ×（头程 + 安全 + 备货天数）- FBA 现有及在途库存。
      </Typography.Paragraph>
      <Row gutter={12}>
        {n('transit_days', '头程时效（天）')}
        {n('safety_days', '安全库存天数')}
        {n('cover_days', '备货可售天数')}
        {n('purchase_lead_days', '采购交期（空=产品设置）')}
        {n('inspection_days', '质检/处理天数')}
        {n('growth_factor', '增长系数', 0.1)}
        {n('weight_7d', '7天权重', 0.1)}
        {n('weight_14d', '14天权重', 0.1)}
        {n('weight_30d', '30天权重', 0.1)}
      </Row>
    </FormModal>
  )
}
