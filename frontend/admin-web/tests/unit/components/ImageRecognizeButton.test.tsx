// case_ids: UI-009, API-004
/**
 * ImageRecognizeButton（issue #5321 包 1「页面快通道」）
 *
 * 覆盖：点按钮开文件选择器 → 上传（`uploadApi.uploadImage`）→ 识别
 * （`imageRecognizeApi.recognize(targetType, [url])`）→ 字段回传并逐字段标注来源；
 * 内核**有意留空**的字段（`value: null`）在面板里连原因一起显示、但**不写进表单**；
 * `degraded` / 零可用字段 ⇒ 只弹错、不回调。
 *
 * 🔴 硬要求：本组件**永不落库** —— 不调任何 create/update、不发 fetch、不提交任何 form
 * （「识别结果只填表，提交永远是人的动作」）。
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import ImageRecognizeButton from '@/components/image-recognize/ImageRecognizeButton'

const mocks = vi.hoisted(() => ({
  uploadImage: vi.fn(),
  recognize: vi.fn(),
  // 存在的写端点：本组件**一个都不许调**（列在这里正是为了能断言「未调用」）
  createProduct: vi.fn(),
  updateProduct: vi.fn(),
  createOrder: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  uploadApi: { uploadImage: mocks.uploadImage },
  imageRecognizeApi: { recognize: mocks.recognize },
  productApi: { createProduct: mocks.createProduct, updateProduct: mocks.updateProduct },
  orderApi: { createOrder: mocks.createOrder },
}))

vi.mock('sonner', () => ({
  toast: { error: mocks.toastError, success: vi.fn(), info: vi.fn(), dismiss: vi.fn() },
}))

const UPLOADED_URL = 'https://oss.example.com/a.jpg'
const IMAGE_FILE = new File(['fake-bytes'], 'a.jpg', { type: 'image/jpeg' })
const EMPTY_MESSAGE = '未识别到可用字段，请手工填写或换一张更清晰的图片'

const FIELD_NAME = {
  key: 'name',
  label: '商品名称',
  value: '雪尼尔遮光窗帘',
  source: '[图片识别]',
  reason: null,
}
const FIELD_DOOR_WIDTH = {
  key: 'door_width',
  label: '门幅',
  value: null,
  source: null,
  reason: '图片未标注门幅',
}

/** 与内核响应同形：`{ data: { success, data: { targetType, degraded, fields } } }` */
function recognizeResponse(
  fields: unknown[] = [FIELD_NAME, FIELD_DOOR_WIDTH],
  degraded = false,
  targetType: 'product' | 'order' = 'product',
) {
  return { data: { success: true, data: { targetType, degraded, fields } } }
}

/** 渲染 + 走完「选图」这一步（返回组件的 props 断言用 spy） */
function renderAndPickFile(props: Partial<Parameters<typeof ImageRecognizeButton>[0]> = {}) {
  const onRecognized = vi.fn()
  render(
    <ImageRecognizeButton targetType="product" onRecognized={onRecognized} {...props} />,
  )
  fireEvent.change(screen.getByTestId('image-recognize-input'), {
    target: { files: [IMAGE_FILE] },
  })
  return { onRecognized }
}

describe('ImageRecognizeButton (#5321)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.uploadImage.mockResolvedValue({
      data: { success: true, data: { url: UPLOADED_URL } },
    })
    mocks.recognize.mockResolvedValue(recognizeResponse())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('渲染按钮 + 隐藏的 file 选择器，点击按钮即打开文件选择器', () => {
    const clickSpy = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => {})
    render(<ImageRecognizeButton targetType="product" onRecognized={vi.fn()} />)

    const button = screen.getByTestId('image-recognize-button')
    expect(button.textContent).toContain('拍照 / 上传识别')

    const input = screen.getByTestId('image-recognize-input') as HTMLInputElement
    expect(input.getAttribute('type')).toBe('file')
    expect(input.getAttribute('accept')).toBe('image/*')

    fireEvent.click(button)
    expect(clickSpy).toHaveBeenCalledTimes(1)
  })

  it('选图后先上传再识别：识别端点收到 targetType + 上传后的 URL', async () => {
    const { onRecognized } = renderAndPickFile()

    await waitFor(() => expect(mocks.recognize).toHaveBeenCalledTimes(1))
    expect(mocks.uploadImage).toHaveBeenCalledTimes(1)
    expect(mocks.uploadImage.mock.calls[0][0]).toBe(IMAGE_FILE)
    expect(mocks.recognize.mock.calls[0]).toEqual(['product', [UPLOADED_URL]])
    await waitFor(() => expect(onRecognized).toHaveBeenCalledTimes(1))
  })

  it('建单页 (targetType=order) 用的是 order 口径', async () => {
    mocks.recognize.mockResolvedValue(recognizeResponse([FIELD_NAME], false, 'order'))
    renderAndPickFile({ targetType: 'order' })

    await waitFor(() => expect(mocks.recognize).toHaveBeenCalledTimes(1))
    expect(mocks.recognize.mock.calls[0][0]).toBe('order')
  })

  it('有值字段回传并按 [图片识别] 逐字段标注；留空字段带原因显示但**不回传**', async () => {
    const { onRecognized } = renderAndPickFile()

    await waitFor(() => expect(onRecognized).toHaveBeenCalledTimes(1))
    // 只回传有值的字段（value: null 的「门幅」不在其中）
    expect(onRecognized.mock.calls[0][0]).toEqual([FIELD_NAME])
    expect(screen.getByTestId('image-recognize-field-name').textContent).toBe(
      '[图片识别] 商品名称：雪尼尔遮光窗帘',
    )
    expect(screen.getByTestId('image-recognize-field-door_width').textContent).toBe(
      '门幅：未识别（图片未标注门幅）',
    )
  })

  it('degraded ⇒ 弹「未识别到可用字段…」且不回传任何字段', async () => {
    mocks.recognize.mockResolvedValue(recognizeResponse([], true))
    const { onRecognized } = renderAndPickFile()

    await waitFor(() => expect(mocks.toastError).toHaveBeenCalledWith(EMPTY_MESSAGE))
    expect(onRecognized).not.toHaveBeenCalled()
  })

  it('未降级但零个可用字段（全是 value:null）⇒ 同一条提示、不回传', async () => {
    mocks.recognize.mockResolvedValue(recognizeResponse([FIELD_DOOR_WIDTH], false))
    const { onRecognized } = renderAndPickFile()

    await waitFor(() => expect(mocks.toastError).toHaveBeenCalledWith(EMPTY_MESSAGE))
    expect(onRecognized).not.toHaveBeenCalled()
  })

  it('上传失败 ⇒ 兜底 toast，且不再调识别、不回传', async () => {
    mocks.uploadImage.mockRejectedValue(new Error('upload boom'))
    const { onRecognized } = renderAndPickFile()

    await waitFor(() => expect(mocks.toastError).toHaveBeenCalledWith('图片识别失败，请重试'))
    expect(mocks.recognize).not.toHaveBeenCalled()
    expect(onRecognized).not.toHaveBeenCalled()
  })

  it('🔴 全程不落库：无 create/update、无 fetch、不提交所在 form', async () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault())
    const onRecognized = vi.fn()

    render(
      <form onSubmit={onSubmit}>
        <ImageRecognizeButton targetType="order" onRecognized={onRecognized} />
      </form>,
    )
    fireEvent.click(screen.getByTestId('image-recognize-button'))
    fireEvent.change(screen.getByTestId('image-recognize-input'), {
      target: { files: [IMAGE_FILE] },
    })

    await waitFor(() => expect(onRecognized).toHaveBeenCalledTimes(1))
    expect(mocks.createProduct).not.toHaveBeenCalled()
    expect(mocks.updateProduct).not.toHaveBeenCalled()
    expect(mocks.createOrder).not.toHaveBeenCalled()
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(onSubmit).not.toHaveBeenCalled()
  })
})