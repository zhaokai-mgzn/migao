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
import { CALC_PARAM_COPY, CALC_SCALAR_KEYS } from '@/lib/craft-calc-glossary'
import { PARAM_DOMAINS } from '@/lib/tenant-params'
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
  defaults,
  defaultsSource,
}: {
  onSave: (draft: CraftCalcConfig) => Promise<void>
  config: CraftCalcConfig
  source?: 'stored' | 'default'
  /** 引擎默认值整份（`defaults_source='engine'` 时后端才附）—— issue #6857「恢复为默认值」用 */
  defaults?: Partial<CraftCalcConfig>
  defaultsSource?: 'engine' | 'unavailable'
}) {
  const [draft, setDraft] = useState<CraftCalcConfig>(config)
  return (
    <CalcCaliberPanel
      calc={{ source, config, defaults, defaults_source: defaultsSource } as never}
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

async function renderPanel(
  onSave: (draft: CraftCalcConfig) => Promise<void> = async () => {},
  opts: { defaults?: Partial<CraftCalcConfig>; defaultsSource?: 'engine' | 'unavailable' } = {},
) {
  render(
    <Host
      onSave={onSave}
      config={READ_CONFIG}
      source={READ_SOURCE}
      defaults={opts.defaults}
      defaultsSource={opts.defaultsSource}
    />,
  )
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

  it('🔴 引擎键名不上屏（§31 P3）—— `param-<key>` 锚点在，但值**只由输入框承载**（§31 P2）', async () => {
    renderPanel()
    // 展示面：键名一个字都不许出现（改前 6 个键名原样印在数值位下方）
    for (const key of ['per_fold_single', 'margin_single', 'oversize_width_threshold']) {
      expect(screen.queryByText(key)).toBeNull()
    }
    // 机器锚点在（判据依赖它们，删了就是把判据一起删了）
    expect(screen.getByTestId('param-per_fold_single')).toBeInTheDocument()
    // 🔴 §31 P2（返修）：可写形态下右列值**不渲染** —— 它与输入框同源，是纯粹的第二遍
    expect(screen.queryByTestId('param-value-per_fold_single')).toBeNull()
    // 值本身没有丢：由输入框承载（唯一一处）
    expect(screen.getByTestId('calc-caliber-scalar-per_fold_single')).toHaveValue('0.25')
  })

  /**
   * §31 P2「信息不重复」的**成对判据**（2026-10-13 真机读图复核逼出来的返修）。
   *
   * 改前 `renderScalar` 里右列值 `valueOf(p.key)` 与输入框 `numberOf(displayConfig, p.key)`
   * **同源**（都读草稿）⇒ 同一行把同一个数印两遍（真机：8 个标量逐行同款），
   * 而两次都不可解释「谁是**要改的**那个」（是回声，不是「已保存 vs 正在改」的对照）。
   *
   * ⇒ 判据必须**成对**，否则「把右列值一律删掉」这种改法也能绿 —— 那会把**只读形态**
   * （`TenantParamsPanel`，没有输入框、值只能靠右列显示）一起砍掉。
   */
  describe('§31 P2：同一个数不许同屏印两遍（值只由一处承载）', () => {
    it('可写形态 ⇒ 右列值不渲染（输入框就是值）', async () => {
      await renderPanel()
      for (const key of CALC_SCALAR_KEYS) {
        expect(screen.queryByTestId(`param-value-${key}`)).toBeNull()
      }
      // 反向自证：输入框**在**（否则「没有右列值」可以靠「整块没渲染」蒙过去）
      fireEvent.click(screen.getByTestId('param-advanced-toggle-calc'))
      for (const key of CALC_SCALAR_KEYS) {
        expect(screen.getByTestId(`calc-caliber-scalar-${key}`)).toBeInTheDocument()
      }
    })

    it('只读形态（无写面回调）⇒ 右列值**在**（没有输入框，值只能靠它）', () => {
      render(
        <CalcCaliberPanel calc={{ source: 'stored', config: READ_CONFIG } as never} loading={false} />,
      )
      expect(screen.getByTestId('param-value-per_fold_single')).toHaveTextContent('0.25')
      expect(screen.queryByTestId('calc-caliber-scalar-per_fold_single')).toBeNull()
    })
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

  it('档位表逐行可改：显示名中文化（标准档 / 经济档），但**键**仍是 standard / economy；未知档给人话兜底', async () => {
    await renderPanel()
    const rowOf = (name: string) =>
      screen.getByTestId(`calc-caliber-tier-${name}-fullness`).closest('tr') as HTMLElement
    expect(rowOf('standard')).toHaveTextContent('标准档')
    expect(rowOf('economy')).toHaveTextContent('经济档')
    // 提交给 API 的 tiers 键仍是英文键（中文只是显示名）
    expect(screen.getByTestId('calc-caliber-tier-standard-fullness')).toHaveValue('2')
    expect(screen.getByTestId('calc-caliber-tier-standard-label')).toHaveValue('标准工艺')
    // 未知档 ⇒ **人话兜底「未命名档位」**：不把服务端机器键（`custom`）印上屏。
    // 🔴 改判（issue #6825）：改前是 `TIER_DISPLAY_LABEL[name] ?? name`，服务端新增档位时会把
    //    `economy` / `custom` 一类标识直接显示给商家；守卫 `design-baseline-expression-fallback.test.ts`
    //    （issue #6668 盲区①）的首选处置 = 换人话兜底，而不是登记豁免。
    cleanup()
    READ_CONFIG = {
      ...ENGINE_DEFAULT_CALC_CONFIG,
      tiers: { ...ENGINE_DEFAULT_CALC_CONFIG.tiers, custom: { fullness: 2.4, label: '' } },
    } as unknown as CraftCalcConfig
    await renderPanel()
    const customRow = screen.getByTestId('calc-caliber-tier-custom-fullness').closest('tr') as HTMLElement
    expect(customRow).toHaveTextContent('未命名档位')
    expect(customRow).not.toHaveTextContent('custom')
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
      // 锚点必须落在**该参数自己的术语行**上（只断「有元素」= 存在性弱断言，换不来判别力）
      const row = document.getElementById(href.replace('#', ''))
      expect(row?.textContent, `「说明」锚点须落在「${key}」的术语行`).toContain(CALC_PARAM_COPY[key].label)
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

  it('保存成功 ⇒ 成功回执 + 不出现理由块（徽标**不**由本面板翻转：本形态下 `source` 仍是「当前使用系统默认值」）', async () => {
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
it('不再挂「去算料配置」外链：判据落在**数据层**（calc 域定义里没有向外指路的 `edit`）', () => {
  // 🔴 **改判**（独立复核 B 抓到的「无法红的断言」）：改前只断言 DOM 里没有 `param-edit-calc`，
  //    而那个链接由 `{domain.edit && …}` 把守、calc 域**从来没有过** `edit` 字段
  //    ⇒ **把删掉的代码原样放回，那条断言仍然绿**（恒真）。
  //    ⇒ 判据上移到域定义：有人（重新）给 calc 挂上外链 ⇒ 这里当场红。
  const calc = PARAM_DOMAINS.find((d) => d.key === 'calc')
  expect(calc?.key, 'calc 域必须存在（域清单是单一真值源）').toBe('calc')
  expect(
    calc?.edit,
    '算料口径域**自己就是编辑面**（issue #6585 / #6825）⇒ 域定义里不许再有「把人送出本页」的 `edit` 入口',
  ).toBeUndefined()

  // 附带（DOM / 文案层）：本面板也不出现「去算料配置」字样 + 机器锚点 `param-edit-calc` 不在
  //（这两条单独不足以判红 —— 见上；留着是为了文案回归时先看见）
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
  // §31 P2 的对照面：只读形态**保留**右列值（可写形态才不渲染 —— 见上面那对判据）
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 8（issue #6857，用户裁定）：**行式紧凑版式** + 「恢复为默认值」
//
// 病灶（用户逐字「输入框也太长了点吧？如此糟糕的设计」「不要每行都写个默认，太丑了」）：
// #6825 把写面搬回来时沿用了**只读时代**的卡片（名称/提示/影响三段 + 右列只读值），
// 可编辑输入只能**另起一行**、且 `inputCls` 是 `w-full` ⇒ 两位数字被拉满整列（真机 ≈670px）。
// 判据 = 「输入框与名称**同一行**」+「定宽、非 `w-full`」+「行内不再有默认态徽标」。
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 8（#6857）：行式紧凑 —— 控件与名称同行、定宽、行内不标默认态', () => {
  it('🔴 输入框与**名称同一行**（退回「另起一行」⇒ 红）', async () => {
    await renderPanel()
    const input = screen.getByTestId('calc-caliber-scalar-per_fold_single')
    const labelRow = input.parentElement as HTMLElement
    expect(
      labelRow.textContent,
      '输入框必须与名称在同一个行容器里（判据按「同一行」钉死，不是「页面上有」）',
    ).toContain('单色每折吃布')
    expect(labelRow.className).toContain('flex')
    // 🔴 更紧的一刀：输入框的**紧邻前一个兄弟**就是名称 `<span>`（退回「另起一行」时它会变成行 div ⇒ 红）
    const prev = input.previousElementSibling as HTMLElement
    expect(prev?.tagName, '输入框紧邻前一个兄弟必须是名称元素（不是外层行容器）').toBe('SPAN')
    expect(prev.textContent).toContain('单色每折吃布')
    // 行容器（卡片形态带 border/rounded/p-4；紧凑形态不带）
    const row = input.closest('[data-testid="param-per_fold_single"]') as HTMLElement
    expect(row.className, '本域不再用卡片（改回卡片 ⇒ 行高与边框又回来了）').not.toContain('border')
  })

  it('🔴 本域**所有**数值输入定宽（`w-full` 回归 ⇒ 红）', async () => {
    await renderPanel()
    fireEvent.click(screen.getByTestId('param-advanced-toggle-calc'))
    const bounded = ['calc-caliber-scalar-per_fold_single', 'calc-caliber-scalar-min_fullness', 'calc-caliber-tier-economy-fullness', 'calc-caliber-mixed-1']
    for (const id of bounded) {
      const el = screen.getByTestId(id)
      const cls = el.className
      expect(cls, `${id} 必须带定宽 token（w-28）`).toMatch(/\bw-28\b/)
      expect(cls, `${id} 不得是整列宽（w-full）—— 正是 #6857 的病灶`).not.toMatch(/\bw-full\b/)
    }
    // 文本类与下拉也是定宽（显示名 w-40 / 备用公式 w-64）
    expect(screen.getByTestId('calc-caliber-tier-economy-label').className).toMatch(/\bw-40\b/)
    expect(screen.getByTestId('calc-caliber-default_formula').className).toMatch(/\bw-64\b/)
  })

  it('🔴 行内**一个默认态徽标都不标**（含 source=default 与 defaults 可用两种情形）', async () => {
    // 情形 1：整份读面就是默认值（旧形态会在每个键上挂「未配置（正在用引擎默认值）」）
    READ_SOURCE = 'default'
    await renderPanel()
    for (const key of ['per_fold_single', 'hem_margin', 'oversize_width_threshold']) {
      expect(screen.queryByTestId(`param-unset-${key}`), '行内不得再标未配置徽标').toBeNull()
      expect(screen.queryByTestId(`param-is-default-${key}`)).toBeNull()
      expect(screen.queryByTestId(`param-changed-${key}`)).toBeNull()
    }
    // 域级信号仍在（改判的是「逐行重复」，不是「看不见」）
    expect(screen.getByTestId('param-calc-using-default')).toBeInTheDocument()
    cleanup()

    // 情形 2：引擎默认值可用（旧形态会标「默认」/「已改（默认 X）」）
    READ_SOURCE = 'stored'
    await renderPanel(async () => {}, {
      defaults: { ...ENGINE_DEFAULT_CALC_CONFIG, hem_margin: 0.9 },
      defaultsSource: 'engine',
    })
    expect(screen.queryByTestId('param-is-default-hem_margin')).toBeNull()
    expect(screen.queryByTestId('param-changed-hem_margin')).toBeNull()
  })

  it('「恢复为默认值」：整份草稿写回引擎默认值，且**不自动保存**（必须还点「保存」）', async () => {
    const onSave = vi.fn(async () => {})
    READ_CONFIG = { ...ENGINE_DEFAULT_CALC_CONFIG, hem_margin: 0.9, default_formula: 'fullness' } as never
    mockRead({ hem_margin: 0.9, default_formula: 'fullness' })
    await renderPanel(onSave, {
      defaults: { ...ENGINE_DEFAULT_CALC_CONFIG } as Partial<CraftCalcConfig>,
      defaultsSource: 'engine',
    })
    // 改前：草稿 = 读面（0.9 / fullness）
    expect(screen.getByTestId('calc-caliber-scalar-hem_margin')).toHaveValue('0.9')
    fireEvent.click(screen.getByTestId('calc-caliber-restore-defaults'))
    // 恢复后：草稿 = 引擎默认值（含档位 / 拼色 / 公式 —— 整份，不是只回标量）
    expect(screen.getByTestId('calc-caliber-scalar-hem_margin')).toHaveValue('0.3')
    expect(screen.getByTestId('calc-caliber-default_formula')).toHaveValue('pleat')
    // 🔴 不自动保存：写面只在显式点「保存」时发 PUT
    expect(productionApi.updateCraftCalcConfig).not.toHaveBeenCalled()
  })

  it('引擎默认值**本次取不到** ⇒ 「恢复为默认值」禁用（不拿猜的值冒充默认值）', async () => {
    await renderPanel(async () => {}, { defaultsSource: 'unavailable' })
    expect(screen.getByTestId('calc-caliber-restore-defaults')).toBeDisabled()
  })
})
