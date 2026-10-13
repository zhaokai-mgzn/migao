// case_ids: UI-054
/**
 * 「算料口径」域面板（issue #6580 抽取；**issue #6825 起它成为算料配置的唯一写面**）。
 *
 * 本文件判两件事：
 *
 * **① 抽取后必须保持的三件事**（抽取的判据就是「行为一字不变」）
 * 1. 有读数 ⇒ 每个标量参数都有一行（人话 + 「改它会怎样」），不是只显示名字；
 * 2. `calcError` ⇒ 显示**传进来的**那句分流话术（面板不自己编话术 —— 归因判据在页面里），
 *    且**不**渲染参数行；`loading` ⇒ 不出现「未配置」这类结论（三态不互画）；
 * 3. 域自己就是编辑面 ⇒ **不许**再挂「去算料配置」那种跳出本页的外链。
 *
 * **② issue #6825：域内就地可改（唯一写面）**
 * - 8 个标量（`CALC_SCALAR_KEYS`）+ 档位表 + 拼色每折吃布表 + 备用公式，**逐键在位**；
 * - 改值 → 保存 ⇒ `PUT` 正文是**全量键**（后端是全量替换，缺键会静默回默认值 —— 缺键即红）；
 * - 422 ⇒ **逐条**理由上屏（`error.details[].message`）+ **草稿不回滚** + `source` 徽标不变；
 * - 读失败 ⇒ **没有输入框**、不出现「未配置」。
 *
 * ## 数值控件一律 `NumberInput`（issue #5198 / #5218）
 *
 * 旧形态 `type="number"` 会吞 `0.` 中间态、清空会渲染字面量 `NaN` ⇒ 本文件对每个数字格都判
 * 「是 `type="text"`（`NumberInput` 的形态）」+「清空后是空框，不是 `NaN`」。
 *
 * ## 2026-10-10 改判（issue #6663，判据面**只收紧不放宽**）
 *
 * 真机截图实证同一次读面失败在**一屏之内渲染了四处重复信号**（§31 P1 常驻面克制 / P2 信息不重复）。
 * 本面板的处置：**只留一条失败行**，并撤掉两处重复与一处冒充（数值位的 `—` / 键名那一行）。
 *
 * ## 迁移登记（issue #6825）
 *
 * `frontend/admin-web/src/components/production-config/CalcFormulaPanel.tsx` 已**删除**
 * （它的唯一消费者是本域；公式编辑与理由块并入本面板）。它原来承担的三条行为判据
 * （读失败只留一处失败信号 / 全量键 / 422 逐条理由）**全部迁进本文件**（见下面的分组）。
 */
import { useEffect, useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { toast } from 'sonner'

vi.mock('@/lib/api', () => ({
  productionApi: {
    getCraftCalcConfig: vi.fn(),
    updateCraftCalcConfig: vi.fn(),
  },
  // §22 P4 阈值试算块（本域常驻）与术语说明区块的算例读面
  autoFeaturesApi: { preview: vi.fn(() => Promise.resolve({ data: { success: true, data: { auto_features: [] } } })) },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: Record<string, unknown>) => (
    <a href={href as string} {...props}>
      {children as never}
    </a>
  ),
}))

import CalcCaliberPanel from '@/components/settings/CalcCaliberPanel'
import { productionApi } from '@/lib/api'
import { markErrorToastShown } from '@/lib/api-error'
import { CALC_SCALAR_KEYS } from '@/lib/craft-calc-glossary'
import type { CraftCalcConfig } from '@/types'

/**
 * 算料引擎**默认配置**（逐值写死 = 后端会回什么；**不从前端实现推导**）。
 *
 * 🔴 11 个键的清单也**写死在这里**（不从 `CALC_SCALAR_KEYS` 推导全量键 —— 那样
 * 「漏发某个键」会在两边同时漏掉，判据恒真）。`CALC_SCALAR_KEYS` 只用来逐个断言
 * 「8 个标量输入框都在」。
 */
const ENGINE_DEFAULT_CALC_CONFIG = {
  per_fold_single: 0.25,
  per_fold_mixed_times: { '1': 0.65, '2': 1.2 },
  margin_single: 0.2,
  margin_multi: 0.3,
  min_fullness: 1.5,
  tiers: {
    standard: { fullness: 2.0, label: '标准工艺' },
    economy: { fullness: 1.8, label: '经济工艺' },
  },
  default_formula: 'pleat',
  hem_margin: 0.3,
  meters_rounding_step: 0.1,
  oversize_width_threshold: 6,
  oversize_height_threshold: 4,
}

/** 全量替换的 11 个键（后端 `PUT` 契约；**写死**，不从实现推导） */
const FULL_KEYS = [
  'per_fold_single',
  'per_fold_mixed_times',
  'margin_single',
  'margin_multi',
  'min_fullness',
  'tiers',
  'default_formula',
  'hem_margin',
  'meters_rounding_step',
  'oversize_width_threshold',
  'oversize_height_threshold',
]

/** 后端 422 护栏信封（逐条理由；`details[].message`） */
const CALC_GUARD_REJECTION = {
  response: {
    status: 422,
    data: {
      success: false,
      error: {
        code: 'VALIDATION_ERROR',
        message: '算料配置有 2 处不合法，已整份拒绝',
        details: [
          { field: 'min_fullness', message: '不得低于行业红线 1.5' },
          { field: 'default_formula', message: '必须是 [pleat, fullness] 之一' },
        ],
      },
    },
  },
}

const ok = (data: unknown) => ({ data: { success: true, data } })

/** 读面替身：默认「已保存的商家配置」 */
function mockRead(overrides: Record<string, unknown> = {}) {
  vi.mocked(productionApi.getCraftCalcConfig).mockResolvedValue(
    ok({ source: 'stored', config: { ...ENGINE_DEFAULT_CALC_CONFIG, ...overrides } }) as never,
  )
}

/**
 * 宿主 = `/settings` 页那套编排的**最小替身**（取数在页面、草稿在页面、写面由页面给）：
 * 本文件判的是面板的写面形态，所以宿主只持有草稿 + 一次可注入的保存。
 */
function Host({
  onSave,
  config,
  source = 'stored',
}: {
  onSave: (draft: CraftCalcConfig) => Promise<void>
  config: CraftCalcConfig
  source?: 'stored' | 'default'
}) {
  const [draft, setDraft] = useState<CraftCalcConfig>(config)
  return (
    <CalcCaliberPanel
      calc={{ source, config } as never}
      loading={false}
      calcDraft={draft}
      onCalcDraftChange={setDraft}
      onCalcSave={() => onSave(draft)}
    />
  )
}

/** 渲染并等写面出现（写面 = 本域可编辑） */
/** 每次渲染用的读面（可按用例改写；`source` 决定口径徽标） */
let READ_CONFIG: CraftCalcConfig = ENGINE_DEFAULT_CALC_CONFIG as unknown as CraftCalcConfig
let READ_SOURCE: 'stored' | 'default' = 'stored'

async function renderPanel(onSave: (draft: CraftCalcConfig) => Promise<void> = async () => {}) {
  render(<Host onSave={onSave} config={READ_CONFIG} source={READ_SOURCE} />)
  await screen.findByTestId('calc-caliber-scalar-per_fold_single')
}

beforeEach(() => {
  vi.clearAllMocks()
  READ_CONFIG = ENGINE_DEFAULT_CALC_CONFIG as unknown as CraftCalcConfig
  READ_SOURCE = 'stored'
  mockRead()
  vi.mocked(productionApi.updateCraftCalcConfig).mockResolvedValue(
    ok({ source: 'stored', config: ENGINE_DEFAULT_CALC_CONFIG }) as never,
  )
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 0：抽取后的行为面（读面 + 三件套 + 三态）
// ══════════════════════════════════════════════════════════════════════════════
describe('算料口径域面板（issue #6580 抽取后的行为面）', () => {
  it('有读数 ⇒ 逐条参数成行（人话名 + 「改它会怎样」都在）', async () => {
    renderPanel()
    expect(screen.getByTestId('param-per_fold_single')).toBeInTheDocument()
    expect(screen.getAllByText('单色每折吃布（米）').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/改它会怎样/).length).toBeGreaterThan(0)
  })

  it('🔴 引擎键名不上屏（§31 P3）—— 但机器锚点 `param-<key>` / `param-value-<key>` 全部保留', async () => {
    renderPanel()
    // 展示面：键名一个字都不许出现（改前 6 个键名原样印在数值位下方）
    for (const key of ['per_fold_single', 'margin_single', 'oversize_width_threshold']) {
      expect(screen.queryByText(key)).toBeNull()
    }
    // 机器锚点在（判据依赖它们，删了就是把判据一起删了）
    expect(screen.getByTestId('param-per_fold_single')).toBeInTheDocument()
    expect(screen.getByTestId('param-value-per_fold_single')).toHaveTextContent('0.25')
  })

  it('加载中 ⇒ 不出现「未配置（正在用引擎默认值）」这类结论（三态不互画）', () => {
    vi.mocked(productionApi.getCraftCalcConfig).mockReturnValue(new Promise(() => {}) as never)
    render(<CalcCaliberPanel />)
    expect(screen.queryByText(/未配置/)).toBeNull()
    expect(screen.queryByText(/引擎默认/)).toBeNull()
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 1（冻结）：域内 8 标量 + tiers + 拼色 + 公式**逐键在位**
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 1（#6825）：域内就地可改 —— 逐键在位', () => {
  it('8 个标量键各有一个输入框（键集取自 `CALC_SCALAR_KEYS`，逐键钉住）', async () => {
    await renderPanel()
    // 高级组默认收起（§22 P2 渐进披露）⇒ 先按**用户路径**展开，再逐键断言
    fireEvent.click(screen.getByTestId('param-advanced-toggle-calc'))
    for (const key of CALC_SCALAR_KEYS) {
      const input = screen.getByTestId(`calc-caliber-scalar-${key}`)
      // `NumberInput` 的形态：`type="text"`（`type="number"` 会吞 `0.` 中间态，issue #5198）
      expect(input).toHaveAttribute('type', 'text')
    }
    // 自证键集不是空集（空集上的循环是空断言）
    expect(CALC_SCALAR_KEYS.length).toBe(8)
  })

  it('高级组默认收起 ⇒ 展开后才渲染（渐进披露不变）', async () => {
    await renderPanel()
    const toggle = screen.getByTestId('param-advanced-toggle-calc')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(toggle)
    expect(screen.getByTestId('param-advanced-calc')).toBeInTheDocument()
  })

  it('档位表逐行可改：显示名中文化（标准档 / 经济档），但**键**仍是 standard / economy', async () => {
    await renderPanel()
    const rowOf = (name: string) =>
      screen.getByTestId(`calc-caliber-tier-${name}-fullness`).closest('tr') as HTMLElement
    expect(rowOf('standard')).toHaveTextContent('标准档')
    expect(rowOf('economy')).toHaveTextContent('经济档')
    // 提交给 API 的 tiers 键仍是英文键（中文只是显示名）
    expect(screen.getByTestId('calc-caliber-tier-standard-fullness')).toHaveValue('2')
    expect(screen.getByTestId('calc-caliber-tier-standard-label')).toHaveValue('标准工艺')
    // 未知档 ⇒ 回退原键（不吞掉、不猜中文）
    cleanup()
    READ_CONFIG = {
      ...ENGINE_DEFAULT_CALC_CONFIG,
      tiers: { ...ENGINE_DEFAULT_CALC_CONFIG.tiers, custom: { fullness: 2.4, label: '' } },
    } as unknown as CraftCalcConfig
    await renderPanel()
    expect(screen.getByTestId('calc-caliber-tier-custom-fullness').closest('tr')).toHaveTextContent('custom')
  })

  it('拼色每折吃布表逐行可改（拼 N 次 → 每折吃布）', async () => {
    await renderPanel()
    expect(screen.getByTestId('calc-caliber-mixed-1')).toHaveValue('0.65')
    expect(screen.getByTestId('calc-caliber-mixed-2')).toHaveValue('1.2')
  })

  it('备用公式是 select，取值域来自 `CRAFT_CALC_FORMULA_LABELS`（不另写一份映射）', async () => {
    await renderPanel()
    const select = screen.getByTestId('calc-caliber-default_formula')
    expect(select.tagName).toBe('SELECT')
    expect(select).toHaveValue('pleat')
    expect(within(select as HTMLElement).getAllByRole('option').map((o) => (o as HTMLOptionElement).value)).toEqual([
      'pleat',
      'fullness',
    ])
  })

  it('全域**只有一处**保存按钮（同一份配置不许两个写面 / 两个保存）', async () => {
    await renderPanel()
    expect(screen.getByTestId('calc-caliber-save')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /保存/ })).toHaveLength(1)
  })

  it('保留阈值预览（改钱参数的预览）与术语说明区块（口径与术语不丢功能）', async () => {
    await renderPanel()
    expect(screen.getByTestId('threshold-preview')).toBeInTheDocument()
    expect(screen.getByTestId('craft-calc-glossary')).toBeInTheDocument()
  })

  it('数字格清空 ⇒ 空框（不许变成字面量 `NaN`），0.x 小数能逐键录入', async () => {
    await renderPanel()
    const scalar = screen.getByTestId('calc-caliber-scalar-per_fold_single')
    const fullness = screen.getByTestId('calc-caliber-tier-standard-fullness')
    const mixed = screen.getByTestId('calc-caliber-mixed-1')

    await waitFor(() => expect(scalar).toHaveValue('0.25'))
    fireEvent.change(scalar, { target: { value: '0' } })
    fireEvent.change(scalar, { target: { value: '0.' } })
    expect(scalar).toHaveValue('0.')
    fireEvent.change(scalar, { target: { value: '0.5' } })
    expect(scalar).toHaveValue('0.5')

    for (const el of [scalar, fullness, mixed]) {
      fireEvent.change(el, { target: { value: '' } })
      expect(el).toHaveValue('')
    }
    const inputs = Array.from(document.querySelectorAll('input')) as HTMLInputElement[]
    expect(inputs.filter((el) => el.value === 'NaN')).toEqual([])
  })
})

/**
 * 判据 1b：术语说明区块与参数**同屏**，且它的行内标记**渲染成元素**（issue #4975 → #5194 改判）
 *
 * 红证：渲染层不做解析 ⇒ 整块 `textContent` 里出现字面 `**` 与反引号。
 * 正控：强调必须以元素形态呈现（**删标记**也能让「不含 `**`」变绿 ⇒ 必须另有这条）。
 *
 * ⚠️ 本判据原在 `frontend/admin-web/tests/unit/pages/production-routings.test.tsx`（板子 calc tab 那一段）
 * —— issue #6825 把术语块搬进本域，判据随被测对象一起迁到这里（**不留死判据**）。
 */
describe('判据 1b：术语说明区块与参数同屏（口径与术语不丢功能）', () => {
  it('区块在屏上，行内标记渲染成元素、裸标记不上屏', async () => {
    await renderPanel()
    const panel = screen.getByTestId('calc-caliber-panel')
    const glossary = within(panel).getByTestId('craft-calc-glossary')

    const text = glossary.textContent ?? ''
    // 自证非空：空区块上的「不含 `**`」恒真
    expect(text).toContain('术语怎么判')
    expect(text).not.toContain('**')
    expect(text).not.toContain('`')
    // 正控：强调必须以元素形态呈现（只把标记删掉也能让上面两条变绿 ⇒ 必须另有这条）
    expect(glossary.querySelectorAll('strong').length).toBeGreaterThan(0)
    // 参数旁「说明」锚点指到同页的说明条目（不指空 —— 指空即死链接）
    for (const key of ['per_fold_single', 'margin_single', 'margin_multi'] as const) {
      const href = screen.getByTestId(`param-doc-${key}`).getAttribute('href') ?? ''
      expect(href).toBe(`#glossary-param-${key}`)
      expect(document.getElementById(href.replace('#', ''))).not.toBeNull()
    }
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 2（冻结）：改值 → 保存 ⇒ `PUT` 正文是**全量键**
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 2（#6825）：保存发**全量键**（后端是整份替换，缺键会静默回默认值）', () => {
  it('改「单色每折吃布」⇒ PUT 正文逐键齐全（11 键）+ 改的那个键是新值', async () => {
    const sent: CraftCalcConfig[] = []
    await renderPanel(async (draft) => {
      sent.push(draft)
      await productionApi.updateCraftCalcConfig(draft)
    })
    const input = screen.getByTestId('calc-caliber-scalar-per_fold_single')
    fireEvent.change(input, { target: { value: '0.5' } })
    vi.mocked(productionApi.updateCraftCalcConfig).mockResolvedValueOnce(
      ok({ source: 'stored', config: { ...ENGINE_DEFAULT_CALC_CONFIG, per_fold_single: 0.5 } }) as never,
    )

    fireEvent.click(screen.getByTestId('calc-caliber-save'))
    await waitFor(() => expect(sent).toHaveLength(1))

    const body = sent[0] as unknown as Record<string, unknown>
    expect(Object.keys(body).sort()).toEqual([...FULL_KEYS].sort())
    expect(body.per_fold_single).toBe(0.5)
    // 档位 / 拼色 / 公式三块也在正文里（它们同样是配置键，缺了就被静默回默认）
    expect(body.tiers).toMatchObject({ standard: { fullness: 2 } })
    expect(body.per_fold_mixed_times).toMatchObject({ '1': 0.65 })
    expect(body.default_formula).toBe('pleat')
  })

  it('保存成功 ⇒ 成功回执 + 不出现理由块；口径徽标由页面侧的读面回答（`source` 变「已保存」）', async () => {
    READ_SOURCE = 'default'
    await renderPanel(async (draft) => {
      await productionApi.updateCraftCalcConfig(draft)
    })
    expect(screen.getByTestId('calc-caliber-source')).toHaveTextContent('当前使用系统默认值')
    fireEvent.click(screen.getByTestId('calc-caliber-save'))
    await waitFor(() => expect(toast.success).toHaveBeenCalled())
    expect(screen.queryByTestId('calc-caliber-reasons')).toBeNull()
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 3（冻结）：422 ⇒ 逐条理由 + 草稿不回滚 + `source` 徽标不变
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 3（#6825）：保存被拒 ⇒ 逐条理由上屏，草稿不回滚、不谎报已保存', () => {
  it('422 ⇒ `details[].message` **逐条**可见，用户输入仍在，`source` 仍是「当前使用系统默认值」', async () => {
    READ_SOURCE = 'default'
    await renderPanel(async (draft) => {
      await productionApi.updateCraftCalcConfig(draft)
    })
    fireEvent.click(screen.getByTestId('param-advanced-toggle-calc'))
    const input = screen.getByTestId('calc-caliber-scalar-min_fullness')
    await waitFor(() => expect(input).toHaveValue('1.5'))
    fireEvent.change(input, { target: { value: '1' } })
    vi.mocked(productionApi.updateCraftCalcConfig).mockRejectedValueOnce(CALC_GUARD_REJECTION as never)

    fireEvent.click(screen.getByTestId('calc-caliber-save'))
    const reasons = await screen.findByTestId('calc-caliber-reasons')
    expect(reasons).toHaveTextContent('不得低于行业红线 1.5')
    expect(reasons).toHaveTextContent('必须是 [pleat, fullness] 之一')
    // 不静默回退（草稿不回滚）+ 不谎报已保存
    expect(screen.getByTestId('calc-caliber-scalar-min_fullness')).toHaveValue('1')
    expect(screen.getByTestId('calc-caliber-source')).toHaveTextContent('当前使用系统默认值')
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('对照读数：保存成功 ⇒ 理由块不出现（不是恒显失败）', async () => {
    await renderPanel(async (draft) => {
      await productionApi.updateCraftCalcConfig(draft)
    })
    fireEvent.click(screen.getByTestId('calc-caliber-save'))
    await waitFor(() => expect(productionApi.updateCraftCalcConfig).toHaveBeenCalled())
    expect(screen.queryByTestId('calc-caliber-reasons')).toBeNull()
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 4（冻结）：读失败 ⇒ 无输入框、不出现「未配置」、只留一处失败信号
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 4（#6825）：读失败 ⇒ 无写面、不冒充「未配置」、只留一处失败信号', () => {
  beforeEach(() => {
    vi.mocked(productionApi.getCraftCalcConfig).mockRejectedValue(new Error('500') as never)
  })

  it('读失败 ⇒ 显示页面给的归因话术 + 一个重试出口；面板里**没有任何输入框 / 保存按钮**', async () => {
    render(<CalcCaliberPanel />)
    const failure = await screen.findByTestId('param-calc-error')
    expect(failure).toBeInTheDocument()
    // 失败态有出口（真可点）
    expect(within(failure).getByTestId('param-calc-retry')).toBeInTheDocument()

    // 🔴 没有写面（读不到就不许改 —— 改的是一份读不到的配置）
    expect(screen.queryByTestId('calc-caliber-scalar-per_fold_single')).toBeNull()
    expect(screen.queryByTestId('calc-caliber-save')).toBeNull()
    expect(screen.queryAllByRole('button', { name: /保存/ })).toHaveLength(0)
    // 一个参数卡都不渲染（不用一排 `—` 冒充读数），且失败类文案恰好一处
    expect(screen.queryByTestId('param-per_fold_single')).toBeNull()
    expect(screen.queryByText('—')).toBeNull()
    expect(screen.getAllByTestId('param-calc-error')).toHaveLength(1)
    // 读失败**不得**说「本企业尚未保存过算料口径」（那是读成功才知道的事）
    expect(screen.queryByTestId('param-calc-using-default')).toBeNull()
    expect(screen.queryByText(/未配置/)).toBeNull()
    // 保留「失败态发生过」的机器锚点
    expect(screen.getByTestId('param-calc-read-failed')).toBeInTheDocument()
  })

  it('读失败的**唯一**那处信号由本面板承载：不重复播报（toast 零次），读成功的对照读数零失败信号', async () => {
    vi.mocked(toast.error).mockClear()
    render(<CalcCaliberPanel />)
    await screen.findByTestId('param-calc-error')
    /**
     * `frontend/admin-web/src/lib/request.ts` 的响应拦截器对**所有**失败分支都已
     * `toast.error(...)` + `markErrorToastShown(error)` ⇒ 真 API 失败时面板再播一次就是同屏两处。
     * 本面板撤掉的是**重复**，不是**可见性**（失败仍看得见，且有「重试」出口）。
     */
    expect(toast.error, '面板已内联播报失败 ⇒ 不得再弹一次 toast').not.toHaveBeenCalled()

    // 对照：读成功 ⇒ 失败信号与 toast 都不出现（重新挂一份干净的面板）
    cleanup()
    await renderPanel()
    expect(screen.queryByTestId('calc-caliber-reasons')).toBeNull()
    expect(screen.queryByTestId('param-calc-error')).toBeNull()
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('读数：真 API 失败的命名形态（拦截器已播 + 已打标）⇒ 面板不重复播报，失败仍可见且有出口', async () => {
    const err = new Error('服务器内部错误')
    markErrorToastShown(err)
    vi.mocked(productionApi.getCraftCalcConfig).mockRejectedValue(err as never)
    vi.mocked(toast.error).mockClear()
    render(<CalcCaliberPanel />)
    const failure = await screen.findByTestId('param-calc-error')
    expect(within(failure).getByTestId('param-calc-retry')).toBeInTheDocument()
    expect(toast.error, '拦截器已播泛化 toast ⇒ 面板不得再播一次').not.toHaveBeenCalled()
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 5（冻结）：域自己就是编辑面 ⇒ 不许再把人送出本页
// ══════════════════════════════════════════════════════════════════════════════
it('不再挂「去算料配置」外链（域自己就是编辑面，不许把人送出页面）', () => {
  render(<CalcCaliberPanel calc={null} calcError="" loading={false} />)
  expect(screen.queryByTestId('param-edit-calc')).toBeNull()
  expect(screen.queryByText(/去算料配置/)).toBeNull()
})

/**
 * 只读退化（issue #6825）：**没给写面 props**（`calc` 由调用方传 + 无 `onCalcChange`）⇒ 不渲染写面。
 *
 * 这条保的是「只渲染」的既有挂载形态（`frontend/admin-web/src/components/settings/TenantParamsPanel.tsx`
 * 传 `calc` / `calcError` / `loading` 三件，不给写面回调）—— 那种形态下**一个输入框都不许出现**：
 * 读面不由本组件取 ⇒ 它没有可写的东西（渲染一个「保存」按钮在那里等于造第二个写面）。
 */
it('调用方传只读读数（无 `onCalcChange`）⇒ 只渲染读数，不出现任何写面', () => {
  render(
    <CalcCaliberPanel
      calc={{ source: 'stored', config: ENGINE_DEFAULT_CALC_CONFIG } as never}
      calcError=""
      loading={false}
    />,
  )
  expect(screen.getByTestId('param-value-per_fold_single')).toHaveTextContent('0.25')
  expect(screen.queryByTestId('calc-caliber-scalar-per_fold_single')).toBeNull()
  expect(screen.queryByTestId('calc-caliber-save')).toBeNull()
})
