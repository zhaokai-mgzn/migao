// case_ids: UI-009, API-004, PR-008
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
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import ImageRecognizeButton from '@/components/image-recognize/ImageRecognizeButton'

const mocks = vi.hoisted(() => ({
  uploadImage: vi.fn(),
  recognize: vi.fn(),
  interpret: vi.fn(),
  // 存在的写端点：本组件**一个都不许调**（列在这里正是为了能断言「未调用」）
  createProduct: vi.fn(),
  updateProduct: vi.fn(),
  createOrder: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  uploadApi: { uploadImage: mocks.uploadImage },
  imageRecognizeApi: { recognize: mocks.recognize, interpret: mocks.interpret },
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

  it('参考字段（#6529）：图上读到但没采纳 ⇒ **随行回传**（供查目录）并单独一行显示', async () => {
    const reference = {
      key: 'items',
      label: '商品明细',
      value: null,
      source: null,
      reason: '置信度 0.75 低于订单侧阈值 0.85，宁可不填',
      reference: '2698-11、C31',
    }
    mocks.recognize.mockResolvedValue(recognizeResponse([FIELD_NAME, reference], false, 'order'))
    const { onRecognized } = renderAndPickFile({ targetType: 'order' })

    await waitFor(() => expect(onRecognized).toHaveBeenCalledTimes(1))
    // 有值格 + 参考格**一起**回传；参考格的 `value` 仍是 null ⇒ 调用方的映射函数写不进表单
    expect(onRecognized.mock.calls[0][0]).toEqual([FIELD_NAME, reference])
    expect(screen.getByTestId('image-recognize-field-items').textContent).toContain('未识别')
    expect(screen.getByTestId('image-recognize-reference-items').textContent).toContain('2698-11、C31')
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

// ══════════════════════════════════════════════════════════════════════════════
// 解读模式（issue #6367 包 P3）：一句可选要求 → 上传 → **一次性**推理 → 内嵌结果卡
// ══════════════════════════════════════════════════════════════════════════════

const HINT_PLACEHOLDER = '补充一句（可选）：如 客厅用、韩褶、遮光'

/** 与后端计划的字段条目同形（`source` 决定它进卡片哪一段） */
const PLAN_FIELDS = [
  {
    key: 'name',
    label: '商品名称',
    value: '雪尼尔遮光窗帘',
    source: '[图片识别]',
    reason: null,
    candidates: [],
    note: '图上标题栏写着这个',
    note_source: '[图片识别]',
  },
  {
    key: 'craft',
    label: '工艺',
    value: '韩褶',
    source: '[米宝解读]',
    reason: null,
    candidates: [],
    note: '商家补充了「韩褶」，米宝折成规范工艺名',
    note_source: '[米宝解读]',
  },
]

function interpretResponse(fields: unknown[] = PLAN_FIELDS) {
  return {
    data: { success: true, data: { component: 'page_fill', target_type: 'product', fields } },
  }
}

describe('解读模式（issue #6367 包 P3）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.uploadImage.mockResolvedValue({ data: { success: true, data: { url: UPLOADED_URL } } })
    mocks.interpret.mockResolvedValue(interpretResponse())
  })

  it('① 选图 ⇒ 上传 + 调 interpret（一次；不调 recognize），结果**不自动填表**', async () => {
    const { onRecognized } = renderAndPickFile({ interpret: true })

    await waitFor(() => expect(mocks.interpret).toHaveBeenCalledTimes(1))
    expect(mocks.uploadImage).toHaveBeenCalledTimes(1)
    expect(mocks.uploadImage.mock.calls[0][0]).toBe(IMAGE_FILE)
    expect(mocks.recognize).not.toHaveBeenCalled()
    expect(mocks.interpret.mock.calls[0][0]).toBe('product')
    expect(mocks.interpret.mock.calls[0][1]).toEqual([UPLOADED_URL])

    // 一次性推理 = 结果先落在卡片里，**由商家点「一键填入」**才进表单
    expect(onRecognized).not.toHaveBeenCalled()
    expect(screen.getByTestId('form-interpret-card')).toBeInTheDocument()
  })

  it('①b hint 为空 ⇒ 逐字传空串（由 api 层丢掉该键，见 image-recognize-interpret-api.test.ts）', async () => {
    renderAndPickFile({ interpret: true })

    await waitFor(() => expect(mocks.interpret).toHaveBeenCalledTimes(1))
    expect(mocks.interpret.mock.calls[0][2]).toBe('')
  })

  it('⑥ 输入框 maxLength=200；≤200 字的要求**逐字**透传（不截断、不改写）', async () => {
    const hint = '客厅雪尼尔，韩褶，遮光'
    render(<ImageRecognizeButton targetType="product" interpret onRecognized={vi.fn()} />)

    const input = screen.getByTestId('image-recognize-hint') as HTMLInputElement
    expect(input.getAttribute('maxLength')).toBe('200')
    expect(input.getAttribute('placeholder')).toBe(HINT_PLACEHOLDER)

    fireEvent.change(input, { target: { value: hint } })
    fireEvent.change(screen.getByTestId('image-recognize-input'), {
      target: { files: [IMAGE_FILE] },
    })

    await waitFor(() => expect(mocks.interpret).toHaveBeenCalledTimes(1))
    expect(mocks.interpret.mock.calls[0][2]).toBe(hint)
  })

  it('③ 结果落成内嵌卡片：两段分组（识别 / 解读）+ 各格 note 依据可见', async () => {
    renderAndPickFile({ interpret: true })

    await waitFor(() => expect(screen.getByTestId('form-interpret-card')).toBeInTheDocument())

    const recognized = screen.getByTestId('form-interpret-group-recognized')
    expect(recognized.textContent).toContain('[图片识别]')
    expect(within(recognized).getByTestId('form-interpret-field-name')).toBeInTheDocument()
    expect(within(recognized).getByTestId('form-interpret-note-name').textContent).toContain(
      '图上标题栏写着这个',
    )

    const interpreted = screen.getByTestId('form-interpret-group-interpreted')
    expect(interpreted.textContent).toContain('[米宝解读]')
    expect(within(interpreted).getByTestId('form-interpret-field-craft')).toBeInTheDocument()
    expect(within(interpreted).getByTestId('form-interpret-note-craft').textContent).toContain(
      '米宝折成规范工艺名',
    )
  })

  it('④ 「一键填入」把选中格交给既有 onRecognized —— 只此一条填充路径，且**不落库**', async () => {
    const { onRecognized } = renderAndPickFile({ interpret: true })
    await waitFor(() => expect(screen.getByTestId('form-interpret-card')).toBeInTheDocument())

    fireEvent.click(screen.getByTestId('form-interpret-fill'))

    expect(onRecognized).toHaveBeenCalledTimes(1)
    expect(onRecognized.mock.calls[0][0].map((f: { key: string }) => f.key)).toEqual([
      'name',
      'craft',
    ])
    expect(mocks.createProduct).not.toHaveBeenCalled()
    expect(mocks.updateProduct).not.toHaveBeenCalled()
    expect(mocks.createOrder).not.toHaveBeenCalled()
  })

  it('⑤ 失败态给出**可行动**文案，且不渲染空卡片（不静默）', async () => {
    mocks.interpret.mockRejectedValue(new Error('interpret boom'))
    const { onRecognized } = renderAndPickFile({ interpret: true })

    await waitFor(() => expect(screen.getByTestId('image-recognize-failure')).toBeInTheDocument())
    expect(screen.getByTestId('image-recognize-failure').textContent).toContain('可重试或手工填写')
    expect(screen.queryByTestId('form-interpret-card')).not.toBeInTheDocument()
    expect(onRecognized).not.toHaveBeenCalled()
  })

  it('⑤b 计划里一个字段都没有 ⇒ 同一条可行动文案、不渲染空卡片', async () => {
    mocks.interpret.mockResolvedValue(interpretResponse([]))
    const { onRecognized } = renderAndPickFile({ interpret: true })

    await waitFor(() => expect(screen.getByTestId('image-recognize-failure')).toBeInTheDocument())
    expect(screen.getByTestId('image-recognize-failure').textContent).toContain('可重试或手工填写')
    expect(screen.queryByTestId('form-interpret-card')).not.toBeInTheDocument()
    expect(onRecognized).not.toHaveBeenCalled()
  })

  it('解读模式同样**不落库**：不调 create/update、不发 fetch、不提交所在 form', async () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault())
    const onRecognized = vi.fn()

    render(
      <form onSubmit={onSubmit}>
        <ImageRecognizeButton targetType="product" interpret onRecognized={onRecognized} />
      </form>,
    )
    fireEvent.change(screen.getByTestId('image-recognize-input'), {
      target: { files: [IMAGE_FILE] },
    })
    await waitFor(() => expect(screen.getByTestId('form-interpret-card')).toBeInTheDocument())

    // 「一键填入」在表单里 ⇒ 它必须是 `type="button"`（`type` 缺省是 submit）
    fireEvent.click(screen.getByTestId('form-interpret-fill'))
    await waitFor(() => expect(onRecognized).toHaveBeenCalledTimes(1))

    expect(mocks.createProduct).not.toHaveBeenCalled()
    expect(mocks.updateProduct).not.toHaveBeenCalled()
    expect(mocks.createOrder).not.toHaveBeenCalled()
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(onSubmit).not.toHaveBeenCalled()
  })
})