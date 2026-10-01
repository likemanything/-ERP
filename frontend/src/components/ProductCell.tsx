import { Image, Space, Typography } from 'antd'

interface Props {
  image?: string | null
  title?: string | null
  sub?: string | null
  extra?: string | null
  size?: number
}

/** 图片 + 主标题 + 副标题 的商品单元格 */
export default function ProductCell({ image, title, sub, extra, size = 40 }: Props) {
  return (
    <Space align="start" size={8}>
      {image ? (
        <Image src={image} width={size} height={size} style={{ objectFit: 'cover', borderRadius: 4 }} preview={false} />
      ) : (
        <div style={{ width: size, height: size, background: '#f5f5f5', borderRadius: 4 }} />
      )}
      <div style={{ lineHeight: 1.4, maxWidth: 260 }}>
        <Typography.Text strong copyable={!!title && { tooltips: false }} style={{ fontSize: 13 }}>
          {title || '-'}
        </Typography.Text>
        {sub && (
          <div>
            <Typography.Text type="secondary" ellipsis={{ tooltip: sub }} style={{ fontSize: 12, maxWidth: 240 }}>
              {sub}
            </Typography.Text>
          </div>
        )}
        {extra && (
          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {extra}
            </Typography.Text>
          </div>
        )}
      </div>
    </Space>
  )
}
