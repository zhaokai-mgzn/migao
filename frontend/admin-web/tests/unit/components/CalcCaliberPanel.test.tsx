// case_ids: UI-054
/**
 * 「算料口径」域面板（issue #6580 抽取；**issue #6825 起它成为算料配置的唯一写面**）。
 *
 * 本文件判两件事：
 *
 * **① 抽取后必须保持的三件事**（抽取的判据就是「行为一字不变」）
 * 1. 有读数 ⇒ 每个标量参数都有一行（人话名 + 口径提示），不是只显示名字；
 * 2. `calcError` ⇒ 显示**传进来的**那句分流话术（面板不自己编话术 —— 归因判据在页面里），
 *    且**不**渲染参数行；`loading` ⇒ 不出现「未配置」这类结论（三态不互画）；
 * 3. 域自己就是编辑面 ⇒ **不许**再挂「去算料配置」那种跳出本页的外链。
 *
 * **② issue #6825：域内就地可改（唯一写面）**
 * - 8 个标量（`CALC_SCALAR_KEYS`）+ 档位表 + 拼色配布长度表 + 备用公式，**逐键在位**；
 * - 改值 ⇒ `PUT` 正文是**全量键**（后端是全量替换，缺键会静默回默认值 —— 缺键即红）；
 * - 422 ⇒ **逐条**理由上屏（`error.details[].message`）+ **草稿不回滚** + `source` 徽标不变；
 * - 读失败 ⇒ **没有输入框**、不出现「未配置」。
 *
 * **③ issue #7183（2026-10-18 用户裁定）：变更即保存**
 * 底部保存条（「保存」+「恢复为默认值」）**整体退场**：草稿变更 → 防抖 0.6 秒 → 自动 `PUT`。
 * 判据集中在「判据 9」（零按钮 / 防抖 / 合并 / 首屏不写 / 在飞闸 / 422 不回滚 / 只读零请求 / 卸载补发）。
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
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
import { CALC_FIELD_GROUPS, CALC_PARAM_COPY, CALC_SCALAR_KEYS } from '@/lib/craft-calc-glossary'
import { PARAM_DOMAINS } from '@/lib/tenant-params'
import type { CraftCalcConfig } from '@/types'

/**
 * 算料引擎**默认配置**（逐值写死 = 后端会回什么；**不从前端实现推导**）。
 *
 * 🔴 **13 个键**的清单也**写死在这里**（不从 `CALC_SCALAR_KEYS` 推导全量键 —— 那样
 * 「漏发某个键」会在两边同时漏掉，判据恒真）。`CALC_SCALAR_KEYS` 只用来逐个断言
 * 「10 个标量输入框都在」。
 */
const ENGINE_DEFAULT_CALC_CONFIG = {
  per_fold_single: 0.25,
  per_fold_mixed_times: { '1': 0.65, '2': 1.2 },
  margin_single: 0.2,
  margin_multi: 0.3,
  margin_mixed_single: 0.15,
  margin_mixed_multi: 0.2,
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

/** 全量替换的 13 个键（后端 `PUT` 契约；**写死**，不从实现推导） */
const FULL_KEYS = [
  'per_fold_single',
  'per_fold_mixed_times',
  'margin_single',
  'margin_multi',
  'margin_mixed_single',
  'margin_mixed_multi',
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
  /** 引擎默认值整份（`defaults_source='engine'` 时后端才附）—— 只剩「默认值说明」类判据用 */
  defaults?: Partial<CraftCalcConfig>
  defaultsSource?: 'engine' | 'unavailable'
}) {
  const [draft, setDraft] = useState<CraftCalcConfig>(config)
  /**
   * 与 `/settings` 页**逐字同款**：读面落地 / 刷新时把草稿同步成服务端那份。
   *
   * 🔴 这是判据 d 的另一半：页面**真的会**在读面落地时覆盖草稿，而那不是「商家的变更」
   * ⇒ 面板必须凭「基线 = 读面配置」认出它、**不发**写请求（否则每次打开页面就写一次库）。
   */
  useEffect(() => {
    setDraft(config)
  }, [config])
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

/**
 * **同步**渲染同一套宿主（判据 9 专用）：不 await 任何 `findBy*`。
 *
 * 🔴 `vi.useFakeTimers()` 与 `waitFor` / `userEvent` 混用会互相等（表现为整条用例卡死）——
 * 仓内既有做法 = `fireEvent` + `act` + 显式 `vi.advanceTimersByTime`。本域的可写形态是
 * **同步首屏**（`calc` / `calcDraft` 由调用方给，不经过读面），所以同步取节点是安全的。
 */
function renderHostSync(
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
  return screen.getByTestId('calc-caliber-scalar-per_fold_single')
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
  it('有读数 ⇒ 逐条参数成行（人话名 + 口径提示；「改它会怎样」不上屏）', async () => {
    renderPanel()
    expect(screen.getByTestId('param-per_fold_single')).toBeInTheDocument()
    // 2026-10-16（issue #7007）：展示名「单色每折吃布」⇒「单色每折用料」（用户裁定方案 B：
    // 算料术语改叫法、保留业务词）。**只改展示名**：键名 `per_fold_single` / 公式 / 数值一字未动，
    // 同一 describe 内「引擎键名不上屏」与下文 `PUT` 全量键判据都照旧。
    expect(screen.getAllByText('单色每折用料（米）').length).toBeGreaterThan(0)
    // 2026-10-17（issue #7124 二轮）：**字段自己**的标签不再拖括号单位 —— 「（米）」拆成框内后缀
    // （上面那条命中的是下方术语表的完整标签；这条钉的是表单里的形态）。
    expect(screen.getByTestId('param-per_fold_single').textContent).toContain('单色每折用料')
    expect(screen.getByTestId('param-per_fold_single').textContent).toContain('米')
    // 🔴 2026-10-17 用户逐字「把算料口径里面的这行字都拿掉吧」= 「改它会怎样：… 说明」**整行**。
    // 注入：把那行加回 ⇒ 本条红（它是行内**唯一**被点名的形态）。
    expect(screen.queryAllByText(/改它会怎样/)).toEqual([])
    // 反向自证（撤的是**那一行**，不是把整行内容都删空）：同一行的**口径提示**仍在，
    // 文案取自单一真值 `CALC_PARAM_COPY`（去掉行内标记后逐字比对）。
    const row = screen.getByTestId('param-per_fold_single')
    const hint = CALC_PARAM_COPY.per_fold_single.hint.replace(/\*\*/g, '')
    expect(row.textContent).toContain(hint)
  })

  it('标准字段（issue #7176）：标签在上、控件满列、单位做框内后缀 —— 全站配置面只有这一种字段形态', async () => {
    await renderPanel()
    const field = screen.getByTestId('param-per_fold_single')
    // ① 字段 = `Field`：标签在上（`text-xs` 灰字），控件紧跟其后
    const label = field.querySelector('label') as HTMLElement | null
    expect(label?.tagName, '字段必须有标签元素').toBe('LABEL')
    expect(label?.className, '标签在上、12px 灰字（与「阈值试算」同一套）').toContain('text-xs')
    expect(field.firstElementChild, '标签必须是字段的第一个子元素（不顺排在控件左边）').toBe(label)
    // ② 控件**满列**：宽度交给栅格列（定宽框在「标签在上」的版式里会留一排空白 —— #7176 的病灶）
    const input = screen.getByTestId('calc-caliber-scalar-per_fold_single')
    expect(input.className, '控件满列').toMatch(/\bw-full\b/)
    expect(input.className, '控件不得再定宽').not.toMatch(/\bw-(32|36|40|64)\b/)
    // ③ 单位做**框内后缀**：控件右侧留出位置，单位仍来自 `CALC_PARAM_COPY` 的标签（只做展示拆分）
    expect(input.className, '带单位的数值框要留出单位位').toMatch(/\bpr-9\b/)
    expect(field.textContent).toContain('米')
    // ④ 同组字段落在同一个 `grid` 里（不再是「一行一条细线」的属性列表）
    const grid = field.parentElement as HTMLElement
    expect(grid.className, '同组字段落在栅格里').toContain('grid')
    expect(grid.className, '栅格有列定义（窄屏两列、sm 起按组铺开）').toMatch(/sm:grid-cols-(2|3|4)/)
    expect(grid.contains(screen.getByTestId('param-margin_single')), '同组字段同在').toBe(true)
    // ⑤ 组 = 浅底面板 + 标题（「阈值试算」那一套铬）
    const panel = grid.parentElement as HTMLElement
    expect(panel.className, '组是浅底面板').toContain('bg-neutral-50/50')
    expect(panel.querySelector('h4')?.textContent, '组标题取自单一真值').toBe('用布与余量')
    // 判别力自证：退回「属性行」形态（标签左 / 控件右 = justify-between；行间细线 = divide-y）即红
    expect(field.className).not.toContain('justify-between')
    expect(panel.querySelector('.divide-y'), '组内不再画行间细线').toBeNull()
  })

  it('区块标题把参数分组（用布与余量 / 工艺档位 / 拼色配布长度 / 备用用料公式 / 超高 / 超宽阈值）', async () => {
    await renderPanel()
    // 每个分组标题都钉在**它自己的面板**上（`getByText` 会被下方术语表里的同名术语撞到）
    const groups: [string, string][] = [
      ['calc-caliber-group-materials', '用布与余量'],
      ['calc-caliber-group-tiers', '工艺档位'],
      ['calc-caliber-group-mixed', '拼色配布长度'],
      ['calc-caliber-group-formula', '备用用料公式'],
      ['calc-caliber-group-thresholds', '超高 / 超宽阈值'],
    ]
    for (const [testid, title] of groups) {
      const panel = screen.getByTestId(testid)
      expect(within(panel).getByRole('heading').textContent, `缺区块标题「${title}」`).toBe(title)
    }
  })

  it('🔴 常用键**一个不漏**地落在某个分组里（漏一个 ⇒ 那个参数在写面上隐身）', () => {
    const calc = PARAM_DOMAINS.find((d) => d.key === 'calc')
    const common = (calc?.common ?? []).map((p) => p.key)
    const grouped = CALC_FIELD_GROUPS.flatMap((g) => [...g.keys])
    // 双向相等：漏一个 ⇒ 分组少键（参数隐身）；多一个 ⇒ 分组里有不存在的配置项
    expect([...grouped].sort()).toEqual([...common].sort())
    // 判别力自证：往「常用键」里注入一个键而分组没加 ⇒ 同一比较式判不等
    expect([...grouped].sort()).not.toEqual([...common, 'new_engine_scalar'].sort())
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
  it('10 个标量键各有一个输入框（键集取自 `CALC_SCALAR_KEYS`，逐键钉住）', async () => {
    await renderPanel()
    // 高级组默认收起（§22 P2 渐进披露）⇒ 先按**用户路径**展开，再逐键断言
    fireEvent.click(screen.getByTestId('param-advanced-toggle-calc'))
    for (const key of CALC_SCALAR_KEYS) {
      const input = screen.getByTestId(`calc-caliber-scalar-${key}`)
      // `NumberInput` 的形态：`type="text"`（`type="number"` 会吞 `0.` 中间态，issue #5198）
      expect(input).toHaveAttribute('type', 'text')
    }
    // 自证键集不是空集（空集上的循环是空断言）
    expect(CALC_SCALAR_KEYS.length).toBe(10)
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
    // issue #7176：不再是表格（没有 `<tr>`）—— 每档两个字段同在一个浅底面板里
    const tierPanel = () => screen.getByTestId('calc-caliber-group-tiers')
    expect(tierPanel()).toHaveTextContent('标准档')
    expect(tierPanel()).toHaveTextContent('经济档')
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
    expect(tierPanel()).toHaveTextContent('未命名档位')
    expect(tierPanel()).not.toHaveTextContent('custom')
  })

  it('拼色配布长度表逐行可改（拼 N 次 → 配布长度）', async () => {
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

// ══════════════════════════════════════════════════════════════════════════════
// 判据 10 / 11（2026-10-23 用户裁定，issue #7548）：3 位小数 + 允许设 0
// ══════════════════════════════════════════════════════════════════════════════
/**
 * 用户逐字：「算料口径的输入框都允许设置3位小数，当前是只能输入两位小数」「另外还要都允许设置为0」。
 *
 * 已定口径（同一轮裁定选 A）：3 位 = 毫米精度，与各列 `NUMERIC(6,3)` 同口径，**第 4 位仍归一**；
 * 0 只对「0 有含义」的键放开（每折吃布 / 档位褶倍仍须 > 0 —— 那几项 0 = 0 米 = 0 元报价）。
 */
describe('判据 10（#7548）：算料口径**所有**数字框允许 3 位小数（毫米口径）', () => {
  /** 面板里的**数字**框（`NumberInput` 的形态 = `inputmode=decimal`；档位「显示名」是文本 ⇒ 不在内） */
  function numericInputs(): HTMLInputElement[] {
    const panel = screen.getByTestId('calc-caliber-panel')
    return Array.from(panel.querySelectorAll('input')).filter(
      (el) => el.getAttribute('inputmode') === 'decimal',
    ) as HTMLInputElement[]
  }

  it('标量 / 档位褶倍 / 拼色配布：0.125 失焦后**原样留住**（改前被归一成 0.13）', async () => {
    await renderPanel()
    for (const id of [
      'calc-caliber-scalar-per_fold_single',
      'calc-caliber-tier-standard-fullness',
      'calc-caliber-mixed-1',
    ]) {
      const el = screen.getByTestId(id)
      fireEvent.change(el, { target: { value: '0.125' } })
      fireEvent.blur(el)
      expect(el, `${id} 必须留住第 3 位小数`).toHaveValue('0.125')
    }
  })

  it('类级：本域**每一个**数字框（含高级项与阈值试算 4 格）都按 3 位归一 ⇒ 新增字段漏传 `decimals` 即红', async () => {
    await renderPanel()
    fireEvent.click(screen.getByTestId('param-advanced-toggle-calc'))
    const inputs = numericInputs()
    // 自证非空：一个框都没取到时，下面的循环恒真（空断言 = 假绿）
    expect(inputs.length, '算料口径域应当有 ≥12 个数字框（8 标量 + 档位 + 拼色 + 试算 4 格）').toBeGreaterThanOrEqual(12)
    for (const el of inputs) {
      const label = el.getAttribute('data-testid') ?? el.id
      fireEvent.change(el, { target: { value: '0.125' } })
      fireEvent.blur(el)
      expect(el, `${label} 必须按 3 位小数归一`).toHaveValue('0.125')
      // 第 4 位仍归一：3 位是**口径**，不是「不限制位数」
      fireEvent.change(el, { target: { value: '0.1234' } })
      fireEvent.blur(el)
      expect(el, `${label} 第 4 位按 3 位归一`).toHaveValue('0.123')
    }
  })
})

describe('判据 11（#7548）：0 可设 —— 框里留住 0、正文就是 0（不是空、不回落默认值）', () => {
  it('单开余量输 0 ⇒ 框内 `0`，防抖后的 PUT 正文 `margin_single` = 0', async () => {
    const sent: CraftCalcConfig[] = []
    await renderPanel(async (draft) => {
      sent.push(draft)
      await productionApi.updateCraftCalcConfig(draft)
    })
    const el = screen.getByTestId('calc-caliber-scalar-margin_single')
    fireEvent.change(el, { target: { value: '0' } })
    fireEvent.blur(el)
    expect(el, '0 是合法值：不许被当成「空」清掉').toHaveValue('0')
    await waitFor(() => expect(sent).toHaveLength(1), { timeout: 5000 })
    expect((sent[0] as unknown as Record<string, unknown>).margin_single).toBe(0)
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
    expect(text).toContain('术语判定规则')
    expect(text).not.toContain('**')
    expect(text).not.toContain('`')
    // 🔴 2026-10-17（#7147）：**整页**（不止术语区块）不得再把口语 / 内部机制名摆给商家 ——
    // 「收不到这笔钱」「加工费组合」原本在阈值试算块里（#7147 一并改掉）。
    const pageText = panel.textContent ?? ''
    for (const marker of ['收不到这笔钱', '加工费组合', '改完先看']) {
      expect(pageText, `算料口径页出现了口语 / 机制名：${marker}`).not.toContain(marker)
    }
    // 正控：强调必须以元素形态呈现（只把标记删掉也能让上面两条变绿 ⇒ 必须另有这条）
    expect(glossary.querySelectorAll('strong').length).toBeGreaterThan(0)
    // 🔴 2026-10-17 用户逐字「把算料口径里面的这行字都拿掉吧」⇒ 参数旁的「说明」锚点
    //    （`param-doc-*`，原挂在那一行行尾）随该行**一起退场**。
    // 注入：把锚点加回 ⇒ 本条红（用户要的形态 = 该行整行不存在）。
    for (const key of ['per_fold_single', 'margin_single', 'margin_multi'] as const) {
      expect(screen.queryByTestId(`param-doc-${key}`)).toBeNull()
      // 反向自证（撤的是**指路入口**，不是目的地）：术语区块里该参数的条目仍在，
      // 且落在**它自己那一行**上（只断「有元素」= 存在性弱断言，换不来判别力）。
      const row = document.getElementById(`glossary-param-${key}`)
      expect(row?.textContent, `术语区块仍须有「${key}」的参数当前值行`).toContain(
        CALC_PARAM_COPY[key].label,
      )
    }
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 2（冻结）：保存发**全量键**（#7183 起触发方式 = 防抖自动保存，正文口径不变）
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 2（#6825；#7183 改判触发方式）：保存发**全量键**（后端是整份替换，缺键会静默回默认值）', () => {
  it('改「单色每折用料」⇒ 防抖后 PUT 正文逐键齐全（13 键）+ 改的那个键是新值', async () => {
    const sent: CraftCalcConfig[] = []
    await renderPanel(async (draft) => {
      sent.push(draft)
      await productionApi.updateCraftCalcConfig(draft)
    })
    fireEvent.change(screen.getByTestId('calc-caliber-scalar-per_fold_single'), { target: { value: '0.5' } })
    // 🔴 #7183：没有保存按钮 —— 变更自己进防抖窗口（本判据只关心正文形状，故用真计时器等它）
    await waitFor(() => expect(sent).toHaveLength(1), { timeout: 5000 })

    const body = sent[0] as unknown as Record<string, unknown>
    expect(Object.keys(body).sort()).toEqual([...FULL_KEYS].sort())
    expect(body.per_fold_single).toBe(0.5)
    // 档位 / 拼色 / 公式三块也在正文里（它们同样是配置键，缺了就被静默回默认）
    expect(body.tiers).toMatchObject({ standard: { fullness: 2 } })
    expect(body.per_fold_mixed_times).toMatchObject({ '1': 0.65 })
    expect(body.default_formula).toBe('pleat')
  })

  it('保存成功 ⇒ 保存态「已保存」+ 理由块不出现；**不弹成功 toast**（每次变更都弹会把商家淹掉）', async () => {
    READ_SOURCE = 'default'
    await renderPanel(async (draft) => {
      await productionApi.updateCraftCalcConfig(draft)
    })
    expect(screen.getByTestId('calc-caliber-source')).toHaveTextContent('当前使用系统默认值')
    fireEvent.change(screen.getByTestId('calc-caliber-scalar-per_fold_single'), { target: { value: '0.5' } })
    await waitFor(() => expect(productionApi.updateCraftCalcConfig).toHaveBeenCalledTimes(1), {
      timeout: 5000,
    })
    await waitFor(
      () => expect(screen.getByTestId('calc-caliber-save-state').textContent).toMatch(/^已保存 · \d{2}:\d{2}$/),
      { timeout: 5000 },
    )
    expect(screen.queryByTestId('calc-caliber-reasons')).toBeNull()
    // 🔴 #7183 改判（判据面只收紧不放宽）：成功回执从 toast 换成面板内的保存态
    expect(toast.success, '成功不再弹 toast').not.toHaveBeenCalled()
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 3（冻结）：422 ⇒ 逐条理由 + 草稿不回滚 + `source` 徽标不变（#7183 起由防抖触发）
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 3（#6825 / #7183）：保存被拒 ⇒ 逐条理由上屏，草稿不回滚、不谎报已保存', () => {
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

    // 🔴 #7183：没有保存按钮 —— 变更 → 防抖 → 自动 PUT（打回 422）
    const reasons = await screen.findByTestId('calc-caliber-reasons', {}, { timeout: 5000 })
    expect(reasons).toHaveTextContent('不得低于行业红线 1.5')
    expect(reasons).toHaveTextContent('必须是 [pleat, fullness] 之一')
    // 不静默回退（草稿不回滚）+ 不谎报已保存
    expect(screen.getByTestId('calc-caliber-scalar-min_fullness')).toHaveValue('1')
    expect(screen.getByTestId('calc-caliber-source')).toHaveTextContent('当前使用系统默认值')
    expect(screen.getByTestId('calc-caliber-save-state')).toHaveTextContent('保存失败 · 2 条理由')
    expect(toast.success, '被拒 ≠ 已保存，更不许弹成功回执').not.toHaveBeenCalled()
  })

  it('对照读数：保存成功 ⇒ 理由块不出现（不是恒显失败）', async () => {
    await renderPanel(async (draft) => {
      await productionApi.updateCraftCalcConfig(draft)
    })
    fireEvent.change(screen.getByTestId('calc-caliber-scalar-per_fold_single'), { target: { value: '0.5' } })
    await waitFor(() => expect(productionApi.updateCraftCalcConfig).toHaveBeenCalled(), { timeout: 5000 })
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
    // issue #7183：写面三件（保存 / 恢复默认 / 保存态）在读失败态**一个都不许出现**
    expect(screen.queryByTestId('calc-caliber-restore-defaults')).toBeNull()
    expect(screen.queryByTestId('calc-caliber-save-state')).toBeNull()
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
  // issue #7183：只读形态连「自动保存」的说明与保存态都不许有（它没有可保存的东西）
  expect(screen.queryByTestId('calc-caliber-save-state')).toBeNull()
  expect(screen.queryByText(/修改后自动保存/)).toBeNull()
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
describe('判据 8（issue #7176 改判；前身 #7124 / #7133）：标准字段 + 不标默认态', () => {
  it('🔴 字段自己不带行底细线、组内不画行间线（「8 行 8 条线」是用户判「丑陋」的那一版）', async () => {
    await renderPanel()
    const field = screen.getByTestId('param-per_fold_single')
    expect(field.className, '字段不再画行底细线').not.toContain('border-b')
    expect(field.parentElement?.className, '组内不画行间细线').not.toContain('divide-y')
    // 反向自证：口径提示仍在（撤的是线，不是信息）
    expect(field.textContent).toContain(CALC_PARAM_COPY.per_fold_single.hint.replace(/\*\*/g, ''))
  })

  it('🔴 本域**所有**控件满列、带单位的留单位位（退回定宽框 ⇒ 红）', async () => {
    await renderPanel()
    fireEvent.click(screen.getByTestId('param-advanced-toggle-calc'))
    const filled = [
      'calc-caliber-scalar-per_fold_single',
      'calc-caliber-scalar-min_fullness',
      'calc-caliber-tier-economy-fullness',
      'calc-caliber-mixed-1',
      'calc-caliber-tier-economy-label',
      'calc-caliber-default_formula',
    ]
    for (const id of filled) {
      const cls = screen.getByTestId(id).className
      expect(cls, `${id} 必须满列（宽度由栅格列给，issue #7176）`).toMatch(/\bw-full\b/)
      expect(cls, `${id} 不得再定宽（标签在上的版式里会留一排空白）`).not.toMatch(/\bw-(32|36|40|64)\b/)
    }
    // 带单位的字段：单位做**框内后缀** ⇒ 控件右侧留位（`pr-9`）；无单位的（褶倍）不留
    expect(screen.getByTestId('calc-caliber-scalar-per_fold_single').className).toMatch(/\bpr-9\b/)
    expect(screen.getByTestId('calc-caliber-mixed-1').className).toMatch(/\bpr-9\b/)
    expect(screen.getByTestId('calc-caliber-tier-economy-fullness').className).not.toMatch(/\bpr-9\b/)
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

  it('引擎默认值**本次取不到** ⇒ 不再有「恢复为默认值」入口（issue #7183 已撤该功能）', async () => {
    await renderPanel(async () => {}, { defaultsSource: 'unavailable' })
    // 用户裁定「不需要恢复默认功能」⇒ 那个按钮**整个不存在**（不是禁用，是没有）
    expect(screen.queryByTestId('calc-caliber-restore-defaults')).toBeNull()
    // 但「判不了」这件事仍要**说出来**（§22 P3）：退场的是**动作**，不是**信息**
    expect(screen.getByTestId('param-defaults-unavailable')).toBeInTheDocument()
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 9（issue #7183，2026-10-18 用户裁定）：**变更即保存**
//
// 用户逐字：「这里的两个按钮应该移除，一是不需要恢复默认功能，而是应该让用户在输入框变更后即保存，
// 这样增加界面简洁程度提高了用户体验」。
//
// 逐条判据（每条都能红）：
// a) 全域**零**保存 / 恢复默认按钮，也没有吸底条；「没有保存按钮」这件事被说出来；
// b) 改一个标量 ⇒ 600ms 前不发、之后 `onCalcSave` **恰好一次**；保存中不禁用输入；
// c) 窗口内连改两处 ⇒ 合并成**一次**（正文带两处的新值）；
// d) 首次挂载 / 读面刷新 ⇒ **零**请求（基线 = 读面给的整份配置）；
// e) 在飞闸：未回来前再改 ⇒ 不并发；回来后按**最新**草稿补发**一次**（不排队）；
// f) 422 ⇒ 理由逐条上屏、草稿**不回滚**、保存态「保存失败 · N 条理由」；改对后自动重试；
// g) 只读退化（不给 `onCalcSave`）⇒ 一个写请求都不发、不出现保存态；
// h) 卸载（换域）时待发的那一次仍会发出（不静默丢商家的输入）。
//
// ⚠️ 用 `vi.useFakeTimers()` 推进防抖窗口，**不**混用 `waitFor` / `userEvent`（假计时器下会互相等）。
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 9（issue #7183）：变更即保存 —— 两个按钮退场，防抖 0.6 秒自动 PUT', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('a) 全域**零**保存 / 恢复默认按钮与吸底条；自动保存说明与保存态在屏上', () => {
    renderHostSync()
    expect(screen.queryByTestId('calc-caliber-save')).toBeNull()
    expect(screen.queryByTestId('calc-caliber-restore-defaults')).toBeNull()
    expect(screen.queryByTestId('calc-caliber-save-dock')).toBeNull()
    expect(screen.queryAllByRole('button', { name: /保存|恢复/ })).toHaveLength(0)
    // 反向自证：写面本身还在（否则「没有保存按钮」可以靠「整块没渲染」蒙过去）
    expect(screen.getByTestId('calc-caliber-scalar-per_fold_single')).toBeInTheDocument()
    // 「没有保存按钮」必须**说出来** —— 否则商家会去找它（同 #5899 企业信息域）
    expect(screen.getByText('修改后自动保存（约 0.6 秒），无需手动提交')).toBeInTheDocument()
    expect(screen.getByTestId('calc-caliber-save-state')).toBeInTheDocument()
  })

  it('b) 改一个标量 ⇒ 600ms 前不发、之后 `onCalcSave` **一次**；保存中到「已保存 · HH:mm」', async () => {
    const onSave = vi.fn(async (_draft: CraftCalcConfig) => {})
    renderHostSync(onSave)
    const scalar = screen.getByTestId('calc-caliber-scalar-per_fold_single')
    fireEvent.change(scalar, { target: { value: '0.5' } })
    expect(onSave, '刚改完就发 = 防抖没生效').not.toHaveBeenCalled()
    act(() => {
      vi.advanceTimersByTime(599)
    })
    expect(onSave, '窗口内不得提前发').not.toHaveBeenCalled()
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(onSave).toHaveBeenCalledTimes(1)
    expect((onSave.mock.calls[0][0] as CraftCalcConfig).per_fold_single).toBe(0.5)
    expect(screen.getByTestId('calc-caliber-save-state')).toHaveTextContent('保存中…')
    // 在飞期间**输入不禁用**（商家可以接着改；改出来的会进下一次防抖）
    expect(screen.getByTestId('calc-caliber-scalar-per_fold_single')).not.toBeDisabled()
    await act(async () => {})
    expect(screen.getByTestId('calc-caliber-save-state').textContent).toMatch(/^已保存 · \d{2}:\d{2}$/)
    // 成功**不弹 toast**：每次变更弹一次会把商家淹掉（改判 #7183）
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('c) 窗口内连改两处 ⇒ 合并成**一次**（正文带两处的新值）', () => {
    const onSave = vi.fn(async (_draft: CraftCalcConfig) => {})
    renderHostSync(onSave)
    fireEvent.change(screen.getByTestId('calc-caliber-scalar-per_fold_single'), {
      target: { value: '0.5' },
    })
    act(() => {
      vi.advanceTimersByTime(300)
    })
    fireEvent.change(screen.getByTestId('calc-caliber-scalar-margin_single'), {
      target: { value: '0.25' },
    })
    act(() => {
      vi.advanceTimersByTime(300)
    })
    expect(onSave, '第一次的窗口已被第二次变更重置（不该发两次）').not.toHaveBeenCalled()
    act(() => {
      vi.advanceTimersByTime(300)
    })
    expect(onSave).toHaveBeenCalledTimes(1)
    const draft = onSave.mock.calls[0][0] as CraftCalcConfig
    expect(draft.per_fold_single).toBe(0.5)
    expect(draft.margin_single).toBe(0.25)
  })

  it('d) 首次挂载 / 读面刷新 ⇒ **零**请求（基线 = 读面给的整份配置）', () => {
    const onSave = vi.fn(async (_draft: CraftCalcConfig) => {})
    const { rerender } = render(<Host onSave={onSave} config={READ_CONFIG} source={READ_SOURCE} />)
    act(() => {
      vi.advanceTimersByTime(5000)
    })
    expect(onSave, '打开页面就写库 = 拿这一份覆盖商家配置').not.toHaveBeenCalled()
    // 读面刷新：换一个**新对象**（页面读面落地时把草稿同步成它）⇒ 那不是「商家的变更」
    rerender(
      <Host
        onSave={onSave}
        config={{ ...ENGINE_DEFAULT_CALC_CONFIG } as unknown as CraftCalcConfig}
        source={READ_SOURCE}
      />,
    )
    act(() => {
      vi.advanceTimersByTime(5000)
    })
    expect(onSave, '读面回写草稿不是「商家的变更」').not.toHaveBeenCalled()
  })

  it('e) 在飞闸：未回来前再改 ⇒ 不并发；回来后按**最新**草稿补发**一次**（不排队）', async () => {
    let release!: () => void
    const first = new Promise<void>((resolve) => {
      release = resolve
    })
    let calls = 0
    const onSave = vi.fn(async (_draft: CraftCalcConfig) => {
      calls += 1
      if (calls === 1) await first
    })
    renderHostSync(onSave)
    const scalar = screen.getByTestId('calc-caliber-scalar-per_fold_single')
    fireEvent.change(scalar, { target: { value: '0.5' } })
    act(() => {
      vi.advanceTimersByTime(600)
    })
    expect(onSave).toHaveBeenCalledTimes(1)
    // 第 1 发还没回来 ⇒ 期间**两次**变更都不得并发（也不得排成两发）
    fireEvent.change(scalar, { target: { value: '0.6' } })
    act(() => {
      vi.advanceTimersByTime(600)
    })
    fireEvent.change(scalar, { target: { value: '0.7' } })
    act(() => {
      vi.advanceTimersByTime(600)
    })
    expect(onSave, '在飞闸：一次没回来不许并发第二个').toHaveBeenCalledTimes(1)
    // 第 1 发回来 ⇒ 按**最新**草稿补发**一次**（两次变更坍缩成一次）
    await act(async () => {
      release()
    })
    expect(onSave, '补发必须只有一次（逐次排队 = 请求数随敲键数增长）').toHaveBeenCalledTimes(2)
    expect((onSave.mock.calls[1][0] as CraftCalcConfig).per_fold_single).toBe(0.7)
    await act(async () => {})
    expect(onSave).toHaveBeenCalledTimes(2)
  })

  it('f) 422 ⇒ 理由逐条上屏、草稿**不回滚**、保存态「保存失败 · N 条理由」', async () => {
    const onSave = vi.fn(async () => {
      throw CALC_GUARD_REJECTION
    })
    renderHostSync(onSave)
    const scalar = screen.getByTestId('calc-caliber-scalar-per_fold_single')
    fireEvent.change(scalar, { target: { value: '0.5' } })
    act(() => {
      vi.advanceTimersByTime(600)
    })
    await act(async () => {})
    const reasons = screen.getByTestId('calc-caliber-reasons')
    expect(reasons).toHaveTextContent('不得低于行业红线 1.5')
    expect(reasons).toHaveTextContent('必须是 [pleat, fullness] 之一')
    // 草稿不回滚（商家的输入还在；改对之后下一次变更会自动重试）
    expect(scalar).toHaveValue('0.5')
    expect(screen.getByTestId('calc-caliber-save-state')).toHaveTextContent('保存失败 · 2 条理由')
    // 失败仍播一次（既有 `isErrorToastShown` 去重口径）；成功文案不再出现
    expect(toast.error).toHaveBeenCalled()
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('f2) 失败后**改对再改一次** ⇒ 自动重试（没有「重试」按钮，也不用改完再点保存）', async () => {
    let attempt = 0
    const onSave = vi.fn(async () => {
      attempt += 1
      if (attempt === 1) throw CALC_GUARD_REJECTION
    })
    renderHostSync(onSave)
    const scalar = screen.getByTestId('calc-caliber-scalar-per_fold_single')
    fireEvent.change(scalar, { target: { value: '0.5' } })
    act(() => {
      vi.advanceTimersByTime(600)
    })
    await act(async () => {})
    expect(onSave).toHaveBeenCalledTimes(1)
    // 换成另一个与基线不同的合法值 ⇒ 下一次变更自己重试
    fireEvent.change(scalar, { target: { value: '0.3' } })
    act(() => {
      vi.advanceTimersByTime(600)
    })
    await act(async () => {})
    expect(onSave, '改对之后必须自动重试').toHaveBeenCalledTimes(2)
    expect(screen.queryByTestId('calc-caliber-reasons'), '重试成功 ⇒ 理由块退场').toBeNull()
    expect(screen.getByTestId('calc-caliber-save-state').textContent).toMatch(/^已保存 · \d{2}:\d{2}$/)
  })

  it('g) 只读退化（不给 `onCalcSave`）⇒ 一个写请求都不发、不出现保存态与自动保存说明', () => {
    const onDraftChange = vi.fn()
    render(
      <CalcCaliberPanel
        calc={{ source: 'stored', config: READ_CONFIG } as never}
        loading={false}
        calcDraft={READ_CONFIG}
        onCalcDraftChange={onDraftChange}
      />,
    )
    // 控件在（`writable` 由草稿回调决定），但**没有**自动保存：改它只进草稿，不发请求
    fireEvent.change(screen.getByTestId('calc-caliber-scalar-per_fold_single'), {
      target: { value: '0.5' },
    })
    act(() => {
      vi.advanceTimersByTime(5000)
    })
    expect(onDraftChange, '改动仍然交给调用方的草稿').toHaveBeenCalled()
    expect(productionApi.updateCraftCalcConfig, '只读退化 ⇒ 面板不许自己造写请求').not.toHaveBeenCalled()
    expect(screen.queryByTestId('calc-caliber-save-state')).toBeNull()
    expect(screen.queryByText(/修改后自动保存/)).toBeNull()
  })

  it('h) 卸载（切到别的域）⇒ 待发的那一次仍会发出（不静默丢商家的输入）', async () => {
    const onSave = vi.fn(async (_draft: CraftCalcConfig) => {})
    const { unmount } = render(<Host onSave={onSave} config={READ_CONFIG} source={READ_SOURCE} />)
    fireEvent.change(screen.getByTestId('calc-caliber-scalar-per_fold_single'), {
      target: { value: '0.5' },
    })
    act(() => {
      vi.advanceTimersByTime(100)
    })
    expect(onSave, '还在防抖窗口里').not.toHaveBeenCalled()
    unmount()
    await act(async () => {})
    expect(onSave, '敲完立刻切域就白改 = 静默丢输入').toHaveBeenCalledTimes(1)
    expect((onSave.mock.calls[0][0] as CraftCalcConfig).per_fold_single).toBe(0.5)
  })
})
