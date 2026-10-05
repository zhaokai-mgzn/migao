// case_ids: PR-008
/**
 * FormInterpretCard（issue #6367 包 P3）—— 建品页表单里的「识别 + 一次性推理」结果卡。
 *
 * 用户口径（逐字）：按钮 + 一句文字输入框，**只做一次性推理**（不是对话、不留上下文）；
 * 结果以**内嵌卡片**呈现（不是弹窗 / 对话 / 气泡），分两段 —— `[图片识别]`（从图上抄的）/
 * `[米宝解读]`（米宝推的），每格可勾选，「一键填入」把**选中的**格子交给页面。
 *
 * 判据（会红）：
 * 1. 两段分组：`source` 决定格子进哪一段，组内可见该格 `note` 依据；
 * 2. 空值格（`value` 为空）**不是可填项**：没有勾选框，只展示 `reason`；
 * 3. 「一键填入」只调 `onFill`（= 页面既有的 `onRecognized`），**不落库**（零 create/update）；
 * 4. 默认全选、可逐格取消；一格不选 ⇒ 按钮不可用且点了也不回调。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

const mocks = vi.hoisted(() => ({
  // 存在的写端点：本卡片**一个都不许调**（列在这里正是为了能断言「未调用」）
  createProduct: vi.fn(),
  updateProduct: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  productApi: { createProduct: mocks.createProduct, updateProduct: mocks.updateProduct },
}))

// 与 `ImageUploader.test.tsx` / `ImageRecognizePrefill.test.tsx` 同一份 mock 口径
// （透传 props —— `data-testid` 要能落到真 `<img>` 上，否则缩略图判据是空断言）
vi.mock('next/image', () => ({
  default: (props: Record<string, unknown>) => {
    const React = require('react')
    return React.createElement('img', { ...props, src: props.src || '' })
  },
}))

import FormInterpretCard from '@/components/image-recognize/FormInterpretCard'
import {
  PAGE_FILL_SOURCE_INTERPRETED,
  PAGE_FILL_SOURCE_RECOGNIZED,
  type PageFillField,
} from '@/lib/agent-page-fill'

const IMAGE_URL = 'https://oss.example.com/a.jpg'

function field(over: Pick<PageFillField, 'key' | 'label'> & Partial<PageFillField>): PageFillField {
  return {
    value: null,
    source: null,
    reason: null,
    candidates: [],
    note: null,
    note_source: null,
    ...over,
  }
}

const RECOGNIZED_FIELD = field({
  key: 'name',
  label: '商品名称',
  value: '雪尼尔遮光窗帘',
  source: PAGE_FILL_SOURCE_RECOGNIZED,
  note: '图上标题栏写着这个',
})

/** 空值格：内核有意留空（不确定的宁可不填）—— 只展示原因，**不是可填项** */
const EMPTY_FIELD = field({ key: 'door_width', label: '门幅', reason: '图片未标注门幅' })

const INTERPRETED_FIELD = field({
  key: 'craft',
  label: '工艺',
  value: '韩褶',
  source: PAGE_FILL_SOURCE_INTERPRETED,
  note: '商家补充了「韩褶」，米宝折成规范工艺名',
})

const FIELDS: PageFillField[] = [RECOGNIZED_FIELD, EMPTY_FIELD, INTERPRETED_FIELD]

function renderCard(fields: PageFillField[] = FIELDS) {
  const onFill = vi.fn()
  render(<FormInterpretCard imageUrl={IMAGE_URL} fields={fields} onFill={onFill} />)
  return { onFill }
}

const keysOf = (fields: Array<{ key: string }>) => fields.map((f) => f.key)

describe('FormInterpretCard（issue #6367 包 P3）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('内嵌卡片形态：缩略图 = 已上传的图片 URL（不是弹窗）', () => {
    renderCard()
    expect(screen.getByTestId('form-interpret-card')).toBeInTheDocument()
    const thumb = screen.getByTestId('form-interpret-thumb') as HTMLImageElement
    expect(thumb.getAttribute('src')).toContain(IMAGE_URL)
  })

  it('判据 1：两段分组按 `source` 分（识别格进第一段、解读格进第二段），note 依据可见', () => {
    renderCard()

    const recognized = screen.getByTestId('form-interpret-group-recognized')
    expect(recognized.textContent).toContain(PAGE_FILL_SOURCE_RECOGNIZED)
    expect(within(recognized).getByTestId('form-interpret-field-name')).toBeInTheDocument()
    expect(within(recognized).queryByTestId('form-interpret-field-craft')).toBeNull()
    // 依据（note）跟着格子走，商家看得见「这格凭什么」
    expect(within(recognized).getByTestId('form-interpret-note-name').textContent).toContain(
      '图上标题栏写着这个',
    )

    const interpreted = screen.getByTestId('form-interpret-group-interpreted')
    expect(interpreted.textContent).toContain(PAGE_FILL_SOURCE_INTERPRETED)
    expect(within(interpreted).getByTestId('form-interpret-field-craft')).toBeInTheDocument()
    expect(within(interpreted).queryByTestId('form-interpret-field-name')).toBeNull()
    expect(within(interpreted).getByTestId('form-interpret-note-craft').textContent).toContain(
      '商家补充了「韩褶」',
    )
  })

  it('判据 2：空值格不可选（无勾选框）、reason 可见', () => {
    renderCard()

    expect(screen.queryByTestId('form-interpret-check-door_width')).toBeNull()
    expect(screen.getByTestId('form-interpret-reason-door_width').textContent).toContain(
      '图片未标注门幅',
    )
    // 有值格才有勾选框（对照组：证明「查不到」不是因为整卡没渲染勾选框）
    expect(screen.getByTestId('form-interpret-check-name')).toBeInTheDocument()
    expect(screen.getByTestId('form-interpret-check-craft')).toBeInTheDocument()
  })

  it('判据 3：默认全选，「一键填入」只调 onFill 一条路径（不落库）', () => {
    const { onFill } = renderCard()

    fireEvent.click(screen.getByTestId('form-interpret-fill'))

    expect(onFill).toHaveBeenCalledTimes(1)
    // 空值格**不在**回传里（页面拿到的只有能填的格子）
    expect(keysOf(onFill.mock.calls[0][0])).toEqual(['name', 'craft'])
    expect(mocks.createProduct).not.toHaveBeenCalled()
    expect(mocks.updateProduct).not.toHaveBeenCalled()
  })

  it('判据 4：取消勾选的格子不填（一格一格由商家说了算）', () => {
    const { onFill } = renderCard()

    fireEvent.click(screen.getByTestId('form-interpret-check-name'))
    fireEvent.click(screen.getByTestId('form-interpret-fill'))

    expect(keysOf(onFill.mock.calls[0][0])).toEqual(['craft'])
  })

  it('判据 4b：一格不选 ⇒ 填入按钮不可用，且点了也不回调（不产生空填充）', () => {
    const { onFill } = renderCard()

    fireEvent.click(screen.getByTestId('form-interpret-check-name'))
    fireEvent.click(screen.getByTestId('form-interpret-check-craft'))

    const fill = screen.getByTestId('form-interpret-fill')
    expect(fill).toBeDisabled()
    fireEvent.click(fill)
    expect(onFill).not.toHaveBeenCalled()
  })
})
