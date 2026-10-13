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
import { RemnantItemSizesPanel, OPERATION_LIST_ID } from '@/components/settings/RemnantItemSizesPanel'
import { REMNANT_PARAM_COPY } from '@/lib/tenant-params'
import { REMNANT_TERMS, glossaryRemnantAnchorOf } from '@/lib/craft-calc-glossary'

const smallItemSpecs = vi.fn()
const putSmallItemSpecs = vi.fn()
/** issue #6827：工序名下拉辅助的**既有读面**（`GET /api/admin/production/operations-catalog`）。 */
const getOperationsCatalog = vi.fn()

vi.mock('@/lib/api', () => ({
  remnantApi: {
    smallItemSpecs: () => smallItemSpecs(),
    putSmallItemSpecs: (items: unknown) => putSmallItemSpecs(items),
  },
  productionApi: { getOperationsCatalog: () => getOperationsCatalog() },
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
  getOperationsCatalog.mockReset()
  smallItemSpecs.mockResolvedValue(UNSET)
  putSmallItemSpecs.mockResolvedValue(SET)
  // 缺省（未配置目录）：`data.data = null` —— 与仓内既有同族替身同形（tests/unit/pages/settings.test.tsx）
  getOperationsCatalog.mockResolvedValue({ data: { data: null } })
})

describe('判据 1：三件套上屏（§22 P2）', () => {
  it('label / hint / impact 都来自 `copy`（单一真值在 @/lib/tenant-params）', async () => {
    render(<RemnantItemSizesPanel copy={REMNANT_PARAM_COPY} />)
    expect(screen.getByText(REMNANT_PARAM_COPY.label)).toBeInTheDocument()
    expect(screen.getByText(REMNANT_PARAM_COPY.hint)).toBeInTheDocument()
    expect(screen.getByText(`改它会怎样：${REMNANT_PARAM_COPY.impact}`)).toBeInTheDocument()
    await waitFor(() => expect(smallItemSpecs).toHaveBeenCalled())
  })
})

describe('判据 2：默认值可见（§22 P3）—— 未配置必须显式标出来', () => {
  it('未配置 ⇒ 徽标「未配置（正在用默认值：空 ⇒ 未启用）」+ 服务端说明**原样**上屏', async () => {
    render(<RemnantItemSizesPanel copy={REMNANT_PARAM_COPY} />)
    await waitFor(() => expect(screen.getByTestId('remnant-specs-unset')).toBeInTheDocument())
    expect(screen.getByTestId('remnant-specs-unset').textContent).toContain('未启用')
    expect(screen.getByTestId('remnant-specs-notice').textContent).toContain('不产生匹配建议')
    expect(screen.getByTestId('remnant-specs-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('remnant-specs-configured')).not.toBeInTheDocument()
  })

  it('红证：已配置 ⇒ 两个「未配置」信号都不许出现（谎报未配置 = 让商家以为没生效）', async () => {
    smallItemSpecs.mockResolvedValue(SET)
    render(<RemnantItemSizesPanel copy={REMNANT_PARAM_COPY} />)
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
    render(<RemnantItemSizesPanel copy={REMNANT_PARAM_COPY} />)
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
    render(<RemnantItemSizesPanel copy={REMNANT_PARAM_COPY} />)
    await waitFor(() => expect(screen.getByTestId('remnant-spec-row-0')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('remnant-spec-remove-0'))
    fireEvent.click(screen.getByTestId('remnant-spec-save'))
    await waitFor(() => expect(putSmallItemSpecs).toHaveBeenCalledWith([]))
  })

  it('服务端拒绝 ⇒ **原样**显示服务端理由（不自己编文案、不静默丢弃）', async () => {
    putSmallItemSpecs.mockRejectedValue({
      response: { data: { error: { message: '工序库里没有「绑带布」这道工序 ⇒ 该小件永远不会被匹配到' } } },
    })
    render(<RemnantItemSizesPanel copy={REMNANT_PARAM_COPY} />)
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
    const { container } = render(<RemnantItemSizesPanel copy={REMNANT_PARAM_COPY} />)
    await waitFor(() => expect(smallItemSpecs).toHaveBeenCalled())
    for (const term of REMNANT_TERMS) {
      const anchorId = glossaryRemnantAnchorOf(term.name)
      // 强断言（不是「元素在」）：锚点节点的 id **逐字等于**期望值 —— 存在性断言在本仓是弱断言
      expect(container.querySelector(`#${CSS.escape(anchorId)}`)?.id).toBe(anchorId)
      const link = screen.getByTestId(`remnant-term-link-${term.name}`)
      expect(link.getAttribute('href')).toBe(`#${anchorId}`)
    }
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// issue #6663：小件用料尺寸表 —— 行内必填校验（不得把 NaN 发出去）
//
// 改前：`Number('')` ⇒ `NaN` 直接进 payload；校验只在服务端 ⇒ 提交后整表一条报错，
// 商家不知道是哪一行（而 `JSON.stringify(NaN)` 会静默变 `null`，两边口径还漂）。
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 6：行内必填 + 行内校验，不发 NaN（issue #6663）', () => {
  it('空尺寸/负数 ⇒ **行内**逐格提示、不发请求、不出现 NaN', async () => {
    render(<RemnantItemSizesPanel copy={REMNANT_PARAM_COPY} />)
    await waitFor(() => expect(screen.getByTestId('remnant-spec-add')).toBeTruthy())

    // 加一行，只填工序名 —— 长/宽留空（改前会发 `lengthM: NaN`）
    fireEvent.click(screen.getByTestId('remnant-spec-add'))
    fireEvent.change(screen.getByLabelText('小件（工序名）'), { target: { value: '绑带-布' } })
    fireEvent.click(screen.getByTestId('remnant-spec-save'))

    await waitFor(() => expect(screen.getByTestId('remnant-spec-row-0-lengthM-error')).toBeTruthy())
    expect(screen.getByTestId('remnant-spec-row-0-lengthM-error')).toHaveTextContent('填大于 0 的数')
    expect(screen.getByTestId('remnant-spec-row-0-widthM-error')).toHaveTextContent('填大于 0 的数')
    // 🔴 核心：**一个请求都没发**（改前会把 NaN 发出去）
    expect(putSmallItemSpecs).not.toHaveBeenCalled()
    expect(screen.getByTestId('remnant-specs-error').textContent).not.toMatch(/NaN/)
  })

  it('工序名留空也逐格提示（不许提交一个没有名字的小件）', async () => {
    render(<RemnantItemSizesPanel copy={REMNANT_PARAM_COPY} />)
    await waitFor(() => expect(screen.getByTestId('remnant-spec-add')).toBeTruthy())

    fireEvent.click(screen.getByTestId('remnant-spec-add'))
    fireEvent.change(screen.getByLabelText('用料长'), { target: { value: '0.5' } })
    fireEvent.change(screen.getByLabelText('用料宽'), { target: { value: '0.2' } })
    fireEvent.click(screen.getByTestId('remnant-spec-save'))

    await waitFor(() => expect(screen.getByTestId('remnant-spec-row-0-itemKey-error')).toBeTruthy())
    expect(putSmallItemSpecs).not.toHaveBeenCalled()
  })

  it('改正后就地清掉红标，保存发出去的是**数字**（不是 NaN / 字符串）', async () => {
    render(<RemnantItemSizesPanel copy={REMNANT_PARAM_COPY} />)
    await waitFor(() => expect(screen.getByTestId('remnant-spec-add')).toBeTruthy())

    fireEvent.click(screen.getByTestId('remnant-spec-add'))
    fireEvent.click(screen.getByTestId('remnant-spec-save'))
    await waitFor(() => expect(screen.getByTestId('remnant-spec-row-0-lengthM-error')).toBeTruthy())

    fireEvent.change(screen.getByLabelText('小件（工序名）'), { target: { value: '绑带-布' } })
    fireEvent.change(screen.getByLabelText('用料长'), { target: { value: '0.5' } })
    fireEvent.change(screen.getByLabelText('用料宽'), { target: { value: '0.2' } })
    // 改过的行红标就地消失（不把红标粘在已改的行上）
    expect(screen.queryByTestId('remnant-spec-row-0-lengthM-error')).toBeNull()

    fireEvent.click(screen.getByTestId('remnant-spec-save'))
    await waitFor(() => expect(putSmallItemSpecs).toHaveBeenCalledTimes(1))
    const payload = putSmallItemSpecs.mock.calls[0][0] as Array<Record<string, unknown>>
    expect(payload).toEqual([
      { itemKey: '绑带-布', lengthM: 0.5, widthM: 0.2, note: undefined },
    ])
    // 逐值硬断言：真数字，不是 NaN / 字符串
    expect(payload[0].lengthM).toBe(0.5)
    expect(typeof payload[0].lengthM).toBe('number')
    expect(Number.isNaN(payload[0].lengthM as number)).toBe(false)
  })

  it('服务端 422 的字段名与 JSON 示例不上屏，但**理由**一条不少（issue #6663）', async () => {
    putSmallItemSpecs.mockRejectedValue({
      response: {
        data: {
          error: {
            message: '小件配置有 1 处不合法',
            details: [{ field: 'items[0].lengthM', message: '必须为正数（item_key = 「绑带-布」）' }],
          },
        },
      },
    })
    render(<RemnantItemSizesPanel copy={REMNANT_PARAM_COPY} />)
    await waitFor(() => expect(screen.getByTestId('remnant-spec-add')).toBeTruthy())

    fireEvent.click(screen.getByTestId('remnant-spec-add'))
    fireEvent.change(screen.getByLabelText('小件（工序名）'), { target: { value: '绑带-布' } })
    fireEvent.change(screen.getByLabelText('用料长'), { target: { value: '0.5' } })
    fireEvent.change(screen.getByLabelText('用料宽'), { target: { value: '0.2' } })
    fireEvent.click(screen.getByTestId('remnant-spec-save'))

    await waitFor(() => expect(screen.getByTestId('remnant-specs-error')).toBeTruthy())
    const text = screen.getByTestId('remnant-specs-error').textContent ?? ''
    expect(text).toContain('必须为正数')       // 理由在
    expect(text).not.toContain('items[')       // 字段名不在
    expect(text).not.toContain('lengthM')
    expect(text).not.toContain('item_key')
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// issue #6827：小件（工序名）从**纯自由文本**改成**下拉辅助**（原生 `input[list]` + `datalist`）。
//
// 为什么：服务端 `RemnantService.putSpecs` 按 `production_operations.name` **逐字**校验 ⇒
// 打错一个字，这一行永远不会被命中（配了等于没配）。选项来自**既有读面**
// `productionApi.getOperationsCatalog()` —— **不新造第二份工序清单、不新增端点**。
// 🔴 fail-open：目录读不到（403 / 空）⇒ 静默退回纯文本输入，**不新增错误条**（功能不降级）。
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 7：「小件（工序名）」接工序库下拉辅助（issue #6827）', () => {
  /** 读面形状照 `OperationsCatalog`：`groups[].operations[].name`（**不取** `library_name`）。 */
  const CATALOG = {
    data: {
      data: {
        total: 3,
        groups: [
          { group: '裁剪', operations: [{ name: '精裁', library_name: '精裁-布' }, { name: '裁剪-布' }] },
          { group: '车位', operations: [{ name: '帘头制作' }, { name: '精裁' }] },
        ],
      },
    },
  }

  it('正控：输入框的 `list` 指向同屏 datalist，option 值 = 工序名（保序去重、库口径旧名不上屏）', async () => {
    getOperationsCatalog.mockResolvedValue(CATALOG)
    const { container } = render(<RemnantItemSizesPanel copy={REMNANT_PARAM_COPY} />)
    // 先等**规格读面**落地再交互：它落地时会把 rows 重置为服务端值（早点击会被冲掉）
    await waitFor(() => expect(smallItemSpecs).toHaveBeenCalled())
    fireEvent.click(screen.getByTestId('remnant-spec-add'))

    expect(screen.getByLabelText('小件（工序名）').getAttribute('list')).toBe(OPERATION_LIST_ID)
    await waitFor(() =>
      expect(
        Array.from(container.querySelectorAll(`#${OPERATION_LIST_ID} option`)).map((o) =>
          o.getAttribute('value')
        )
      ).toEqual(['精裁', '裁剪-布', '帘头制作'])
    )
    // 库口径旧名（`library_name`）**不得**上屏（web 界面禁止渲染该键）
    expect(container.querySelector(`#${OPERATION_LIST_ID}`)?.innerHTML).not.toContain('精裁-布')
    expect(screen.getByLabelText('小件（工序名）').getAttribute('placeholder')).toBe(
      '从工序库里选，或逐字输入工序名'
    )
  })

  it('负控：目录读不到（403）⇒ 静默退化，仍可逐字输入且**不新增错误条**', async () => {
    getOperationsCatalog.mockRejectedValue({ response: { status: 403 } })
    const { container } = render(<RemnantItemSizesPanel copy={REMNANT_PARAM_COPY} />)
    await waitFor(() => expect(getOperationsCatalog).toHaveBeenCalled())
    await waitFor(() => expect(smallItemSpecs).toHaveBeenCalled())

    fireEvent.click(screen.getByTestId('remnant-spec-add'))
    fireEvent.change(screen.getByLabelText('小件（工序名）'), { target: { value: '手工输入的小件' } })

    expect(screen.getByDisplayValue('手工输入的小件')).toBeInTheDocument()
    expect(screen.queryByTestId('remnant-specs-error')).toBeNull()
    expect(container.querySelectorAll(`#${OPERATION_LIST_ID} option`)).toHaveLength(0)
  })

  it('负控：读面回 `data.data = null`（目录拿不到）⇒ 同上，且读面失败的红条路径不受影响', async () => {
    getOperationsCatalog.mockResolvedValue({ data: { data: null } })
    const { container } = render(<RemnantItemSizesPanel copy={REMNANT_PARAM_COPY} />)
    await waitFor(() => expect(getOperationsCatalog).toHaveBeenCalled())
    await waitFor(() => expect(smallItemSpecs).toHaveBeenCalled())
    fireEvent.click(screen.getByTestId('remnant-spec-add'))

    expect(container.querySelectorAll(`#${OPERATION_LIST_ID} option`)).toHaveLength(0)
    expect(screen.queryByTestId('remnant-specs-error')).toBeNull()
    expect(smallItemSpecs).toHaveBeenCalled()
  })
})
