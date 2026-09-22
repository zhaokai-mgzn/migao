// case_ids: PR-098
/**
 * 小件用料尺寸表（**行式可配参数**）的**渲染面**守卫（issue #5146 · `migao-dev-flow` §22 P2/P3/P5）。
 *
 * 分工：静态清单与文案守卫在 `frontend/lib/remnant-params.test.ts`；本文件只判**渲染**：
 * 三件套真的上屏、**默认值可见**（未配置 ⇒ 徽标 + 服务端说明**原样**上屏）、
 * 术语**就地**可跳（锚点真的存在）、保存把商家输入**原样**提交给服务端。
 *
 * 🔴 **服务端替身**：本组件不判任何口径（「填了才启用」「键必须是工序名」「装不装得下」全在服务端）
 * ⇒ 测试必须替身 `@/lib/api`（否则会打真实网络）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { RemnantSmallItemSpecsPanel } from '@/components/settings/RemnantSmallItemSpecsPanel'
import { REMNANT_PARAM_COPY } from '@/lib/tenant-params'
import { REMNANT_TERMS, glossaryRemnantAnchorOf } from '@/lib/craft-calc-glossary'

const smallItemSpecs = vi.fn()
const putSmallItemSpecs = vi.fn()

vi.mock('@/lib/api', () => ({
  remnantApi: {
    smallItemSpecs: () => smallItemSpecs(),
    putSmallItemSpecs: (items: unknown) => putSmallItemSpecs(items),
  },
}))

/** 服务端读面形状（未配置）：`configured=false` + **非空** notice（判据 4「未配置不静默」的载体）。 */
const UNSET = {
  data: {
    data: {
      configured: false,
      items: [],
      notice: '未配置小件用料尺寸 ⇒ 不产生匹配建议。本参数默认值为空（未启用）',
    },
  },
}

/** 服务端读面形状（已配置一行）。 */
const SET = {
  data: {
    data: {
      configured: true,
      items: [{ itemKey: '绑带-布', lengthM: 0.5, widthM: 0.2, note: '常规绑带' }],
      notice: null,
    },
  },
}

beforeEach(() => {
  smallItemSpecs.mockReset()
  putSmallItemSpecs.mockReset()
  smallItemSpecs.mockResolvedValue(UNSET)
  putSmallItemSpecs.mockResolvedValue(SET)
})

describe('判据 1：三件套上屏（§22 P2）', () => {
  it('label / hint / impact 都来自 `copy`（单一真值在 @/lib/tenant-params）', async () => {
    render(<RemnantSmallItemSpecsPanel copy={REMNANT_PARAM_COPY} />)
    expect(screen.getByText(REMNANT_PARAM_COPY.label)).toBeInTheDocument()
    expect(screen.getByText(REMNANT_PARAM_COPY.hint)).toBeInTheDocument()
    expect(screen.getByText(`改它会怎样：${REMNANT_PARAM_COPY.impact}`)).toBeInTheDocument()
    await waitFor(() => expect(smallItemSpecs).toHaveBeenCalled())
  })
})

describe('判据 2：默认值可见（§22 P3）—— 未配置必须显式标出来', () => {
  it('未配置 ⇒ 徽标「未配置（正在用默认值：空 ⇒ 未启用）」+ 服务端说明**原样**上屏', async () => {
    render(<RemnantSmallItemSpecsPanel copy={REMNANT_PARAM_COPY} />)
    await waitFor(() => expect(screen.getByTestId('remnant-specs-unset')).toBeInTheDocument())
    expect(screen.getByTestId('remnant-specs-unset').textContent).toContain('未启用')
    expect(screen.getByTestId('remnant-specs-notice').textContent).toContain('不产生匹配建议')
    expect(screen.getByTestId('remnant-specs-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('remnant-specs-configured')).not.toBeInTheDocument()
  })

  it('红证：已配置 ⇒ 两个「未配置」信号都不许出现（谎报未配置 = 让商家以为没生效）', async () => {
    smallItemSpecs.mockResolvedValue(SET)
    render(<RemnantSmallItemSpecsPanel copy={REMNANT_PARAM_COPY} />)
    await waitFor(() => expect(screen.getByTestId('remnant-specs-configured')).toBeInTheDocument())
    expect(screen.queryByTestId('remnant-specs-unset')).not.toBeInTheDocument()
    expect(screen.queryByTestId('remnant-specs-notice')).not.toBeInTheDocument()
    // 当前值由**真值**渲染（不是写死的文案）
    expect(screen.getByDisplayValue('绑带-布')).toBeInTheDocument()
    expect(screen.getByDisplayValue('0.5')).toBeInTheDocument()
    expect(screen.getByDisplayValue('0.2')).toBeInTheDocument()
  })
})

describe('判据 3：保存把商家输入原样提交（本组件不判口径、不取整）', () => {
  it('加一行并填值 ⇒ 提交 `{itemKey, lengthM, widthM}` 给服务端', async () => {
    render(<RemnantSmallItemSpecsPanel copy={REMNANT_PARAM_COPY} />)
    await waitFor(() => expect(smallItemSpecs).toHaveBeenCalled())
    fireEvent.click(screen.getByTestId('remnant-spec-add'))
    fireEvent.change(screen.getByLabelText('小件（工序名）'), { target: { value: '帘头制作' } })
    fireEvent.change(screen.getByLabelText('用料长'), { target: { value: '1.2' } })
    fireEvent.change(screen.getByLabelText('用料宽'), { target: { value: '0.4' } })
    fireEvent.click(screen.getByTestId('remnant-spec-save'))
    await waitFor(() =>
      expect(putSmallItemSpecs).toHaveBeenCalledWith([
        { itemKey: '帘头制作', lengthM: 1.2, widthM: 0.4, note: undefined },
      ])
    )
  })

  it('删掉唯一一行并保存 ⇒ 提交空数组（= 清空 = 回到未配置）', async () => {
    smallItemSpecs.mockResolvedValue(SET)
    render(<RemnantSmallItemSpecsPanel copy={REMNANT_PARAM_COPY} />)
    await waitFor(() => expect(screen.getByTestId('remnant-spec-row-0')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('remnant-spec-remove-0'))
    fireEvent.click(screen.getByTestId('remnant-spec-save'))
    await waitFor(() => expect(putSmallItemSpecs).toHaveBeenCalledWith([]))
  })

  it('服务端拒绝 ⇒ **原样**显示服务端理由（不自己编文案、不静默丢弃）', async () => {
    putSmallItemSpecs.mockRejectedValue({
      response: { data: { error: { message: '工序库里没有「绑带布」这道工序 ⇒ 该小件永远不会被匹配到' } } },
    })
    render(<RemnantSmallItemSpecsPanel copy={REMNANT_PARAM_COPY} />)
    await waitFor(() => expect(smallItemSpecs).toHaveBeenCalled())
    fireEvent.click(screen.getByTestId('remnant-spec-add'))
    fireEvent.change(screen.getByLabelText('小件（工序名）'), { target: { value: '绑带布' } })
    fireEvent.change(screen.getByLabelText('用料长'), { target: { value: '0.5' } })
    fireEvent.change(screen.getByLabelText('用料宽'), { target: { value: '0.2' } })
    fireEvent.click(screen.getByTestId('remnant-spec-save'))
    await waitFor(() =>
      expect(screen.getByTestId('remnant-specs-error').textContent).toContain(
        '工序库里没有「绑带布」这道工序'
      )
    )
  })
})

describe('判据 4：术语**就地**查（§22 P5）—— 锚点真的在面板里', () => {
  it('每条术语都有对应的锚点节点与可点链接（链接不指空）', async () => {
    const { container } = render(<RemnantSmallItemSpecsPanel copy={REMNANT_PARAM_COPY} />)
    await waitFor(() => expect(smallItemSpecs).toHaveBeenCalled())
    for (const term of REMNANT_TERMS) {
      const anchorId = glossaryRemnantAnchorOf(term.name)
      expect(container.querySelector(`#${CSS.escape(anchorId)}`)).not.toBeNull()
      const link = screen.getByTestId(`remnant-term-link-${term.name}`)
      expect(link.getAttribute('href')).toBe(`#${anchorId}`)
    }
  })
})
