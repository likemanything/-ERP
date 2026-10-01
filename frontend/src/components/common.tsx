import { useState, type ReactNode } from 'react'
import { Alert, App, Button, Form, Modal, Space, Typography, Upload, type FormInstance } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import { api, download, errorMessage } from '@/api/client'

/** 执行写操作：可选二次确认，统一提示成功/失败 */
export function useAction() {
  const { message, modal } = App.useApp()
  return async function run<R>(
    fn: () => Promise<R>,
    opts: { success?: string | ((r: R) => string); confirm?: ReactNode; onDone?: (r: R) => void; danger?: boolean } = {},
  ): Promise<R | undefined> {
    const exec = async () => {
      try {
        const r = await fn()
        const msg = typeof opts.success === 'function' ? opts.success(r) : opts.success
        if (msg !== '') message.success(msg ?? '操作成功')
        opts.onDone?.(r)
        return r
      } catch (e) {
        message.error(errorMessage(e))
        return undefined
      }
    }
    if (opts.confirm) {
      return new Promise((resolve) => {
        modal.confirm({
          title: '确认操作',
          content: opts.confirm,
          okButtonProps: { danger: opts.danger },
          onOk: async () => resolve(await exec()),
          onCancel: () => resolve(undefined),
        })
      })
    }
    return exec()
  }
}

/** 表单弹窗：提交时校验并调用 onSubmit，返回 true 时关闭 */
export function FormModal<V extends object = Record<string, any>>({
  open, title, onCancel, onSubmit, initialValues, width = 640, children, form: externalForm, okText,
}: {
  open: boolean
  title: ReactNode
  onCancel: () => void
  onSubmit: (values: V) => Promise<unknown>
  initialValues?: Record<string, any>
  width?: number
  children: ReactNode
  form?: FormInstance<V>
  okText?: string
}) {
  const [innerForm] = Form.useForm<V>()
  const form = externalForm ?? innerForm
  const [loading, setLoading] = useState(false)
  const { message } = App.useApp()
  const submit = async () => {
    const values = await form.validateFields()
    setLoading(true)
    try {
      await onSubmit(values)
      onCancel()
    } catch (e) {
      message.error(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }
  return (
    <Modal
      open={open}
      title={title}
      width={width}
      onCancel={onCancel}
      onOk={submit}
      confirmLoading={loading}
      destroyOnHidden
      okText={okText ?? '保存'}
      mask={{ closable: false }}
    >
      <Form form={form} layout="vertical" initialValues={initialValues as V} preserve={false} style={{ marginTop: 12 }}>
        {children}
      </Form>
    </Modal>
  )
}

interface ImportResult {
  created: number
  updated: number
  skipped: number
  errors: string[]
}

/** Excel 导入弹窗：下载模板 → 上传 → 展示结果 */
export function ImportModal({
  open, onClose, title, uploadUrl, templateUrl, fields, onDone, extra,
}: {
  open: boolean
  onClose: () => void
  title: string
  uploadUrl: string
  templateUrl?: string
  fields?: Record<string, string | number | boolean>
  onDone?: () => void
  extra?: ReactNode
}) {
  const [result, setResult] = useState<ImportResult | null>(null)
  const [loading, setLoading] = useState(false)
  const { message } = App.useApp()
  const close = () => {
    setResult(null)
    onClose()
  }
  return (
    <Modal open={open} title={title} onCancel={close} footer={<Button onClick={close}>关闭</Button>} width={640} destroyOnHidden>
      <Space orientation="vertical" style={{ width: '100%' }}>
        {templateUrl && (
          <Typography.Link onClick={() => download(templateUrl).catch((e) => message.error(errorMessage(e)))}>
            下载导入模板
          </Typography.Link>
        )}
        {extra}
        <Upload.Dragger
          accept=".xlsx"
          showUploadList={false}
          disabled={loading}
          customRequest={async ({ file }) => {
            setLoading(true)
            try {
              const r = await api.upload<ImportResult>(uploadUrl, file as File, fields)
              setResult(r)
              message.success('导入完成')
              onDone?.()
            } catch (e) {
              message.error(errorMessage(e))
            } finally {
              setLoading(false)
            }
          }}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p>{loading ? '正在导入…' : '点击或拖拽 .xlsx 文件到此处上传'}</p>
        </Upload.Dragger>
        {result && (
          <Alert
            type={result.errors.length ? 'warning' : 'success'}
            title={`新增 ${result.created}，更新 ${result.updated}，失败 ${result.skipped}`}
            description={
              result.errors.length > 0 && (
                <div style={{ maxHeight: 200, overflow: 'auto' }}>
                  {result.errors.map((e, i) => (
                    <div key={i}>{e}</div>
                  ))}
                </div>
              )
            }
          />
        )}
      </Space>
    </Modal>
  )
}

/** 页面标题区 */
export function PageTitle({ title, extra, sub }: { title: ReactNode; extra?: ReactNode; sub?: ReactNode }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
      <div>
        <Typography.Title level={4} style={{ margin: 0 }}>
          {title}
        </Typography.Title>
        {sub && <Typography.Text type="secondary">{sub}</Typography.Text>}
      </div>
      <Space>{extra}</Space>
    </div>
  )
}
