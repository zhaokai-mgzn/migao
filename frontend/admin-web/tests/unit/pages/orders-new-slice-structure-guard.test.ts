// case_ids: MC-243
/**
 * 类级元守卫（issue #8725 第一档）：下单页切片的**单一真值**与**单一职责**。
 *
 * ## 它治什么
 *
 * 把 6,913 行的 `app/(dashboard)/orders/new/page.tsx` 切成几个单元，最危险的形态**不是**
 * 搬错行（那是编译错，`tsc` 当场报），而是：
 *
 * | 形态 | 为什么会发生 | 没有任何东西会红的后果 |
 * |---|---|---|
 * | **两份等价实现** | 「搬过去之后页面里再留一份旧的」/「新组件自己再抄一份工具函数」 | 两份各自漂，页面显示 ≠ 落库口径 |
 * | **单元名存实亡** | 页面没有真的 import 它（改了原文件、忘了删旧实现） | 切片看起来完成了，实际还在跑旧代码 |
 * | **孤儿单元** | 抽出来却没人用 | 死代码，还会被后来者当成真值源 |
 * | **职责含糊** | 单元头没写清「它做什么」 | 下一个人只能靠通读 1,800 行去猜 |
 *
 * 四条判据（各自独立、各自可归因）：
 * ① **扫描面非空自证**：扫的那 9 个文件**现取**必须是这 9 个（少一个 / 多一个都红）；
 * ② **单一真值**：登记的每个符号在**本切片面内**恰好定义 1 次，且就在登记的那个文件里；
 * ③ **页面只做装配**：页面**一处都不许**再定义这些符号，且必须从**每一个**单元 import；
 * ④ **单元可用**：每个单元都被至少一个别的源文件 import（无孤儿），且模块头声明了单一职责。
 *
 * ## 边界的诚实登记（§19.1）
 *
 * - **只判本切片面**（页面 + 8 个单元）。`formatAmount` 在**别的**页面里早就有 9 份同名实现
 *   （`orders/[id]` / `ship` / `suppliers` / …），那是切片**之前**就存在的存量，**本判据不为它背书**、
 *   也不在本单修（修 = 跨 10 个文件的另一档，会把这档的「行为 diff = 0」搅浑）；
 * - 判**源码形态**，不判渲染 —— 渲染面由 `orders-new-slice-characterization.test.tsx` 逐字节冻结；
 * - 形态学判据不做语义一刀切：把 `formatAmount` 改名成 `fmt` 再抄一份，本判据看不到
 *   （它会随改名一起红 —— 未登记的新名字不算命中，所以诚实的说法是「改了名它就管不到」）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'

const SRC = join(process.cwd(), 'src')

const PAGE = 'app/(dashboard)/orders/new/page.tsx'
const LIB = 'lib/order-create/'
const CMP = 'components/orders/order-create/'

/**
 * 切片单元台账（**双向**：登记了就必须仍在、且只在那里定义；现取多出未登记的文件 ⇒ 红）。
 * `symbols` = 该文件对外的**唯一职责面**（顶层声明）。
 */
const UNITS: Array<{ file: string; responsibility: string; symbols: string[] }> = [
  {
    file: `${LIB}types.ts`,
    responsibility: '共享形状（类型 / 售卖形态常量）—— 零实现',
    symbols: [
      'OrderProductSku', 'ProductDetail', 'OrderLineItem', 'SaleForm',
      'SALE_FORM_FINISHED', 'SystemAutoFeatureRow', 'AutoFeatureDecision', 'ProductGroup',
    ],
  },
  {
    file: `${LIB}display.ts`,
    responsibility: '展示 / 价格预览口径 —— 数字与枚举变用户可读的字，不做算料、不发请求',
    symbols: [
      'CRAFT_PLAN_ITEM_TESTIDS', 'CRAFT_PLAN_MANUAL_SOURCE_BY_LABEL', 'OPEN_COUNT_LABEL',
      'formatAmount', 'PRICING_ENTRY', 'UNPRICED_NO_COMPOSITION', 'unpricedCombinationLabel',
      'FEE_SOURCE_LABELS', 'feePreviewErrorText', 'SPLICE_OVERRIDE_OPTIONS',
      'uniqueColors',
    ],
  },
  {
    file: `${CMP}SizeAutoBadges.tsx`,
    responsibility: '尺寸自动特征徽标 —— 只读展示，不含裁决入口',
    symbols: ['sizeAutoBadgesOf'],
  },
  {
    file: `${LIB}calc.ts`,
    responsibility: '算料联动 —— 行录入推导成引擎入参 / 加工信息 / 加工项数量，全纯',
    symbols: [
      'genId', 'deriveProcessingQty', 'CRAFT_CALC_DEBOUNCE_MS', 'SHOW_MANUAL_OVERRIDES',
      'FEE_PREVIEW_DEBOUNCE_MS', 'SHAPED_ITEM_NAME', 'DEFAULT_CRAFT_ITEM_NAME',
      'handPickableProcessingItems', 'craftFromItems', 'isShapedFromItems', 'derivedCraftSpec',
      'cuttingModeOf', 'withShapedDefault', 'withCraftItemDefault', 'withRecommendedItemDefaults',
      'recommendedItemNamesOf', 'pickAutoSkuForColor', 'autoFeaturesOf', 'autoFeatureParamsOf',
      'autoFeatureParamsSignature', 'doorWidthParamsOf', 'doorWidthParamsSignature',
      'autoFeaturesBlockReason', 'autoFeatureNoticesOf', 'MANUAL_ADD_REASON', 'derivedOptionInputOf',
      'isHandPickedProcessingItem', 'joinSpliceReasonOf', 'autoFeatureRowsOf',
      'effectiveAutoFeaturesOf', 'processingDetailsOf', 'buildLineProcessingInfo',
      'requantifyProcessing', 'heightFromDoorWidth', 'mergePlanOverrides', 'positiveOrNull',
      'nonNegativeOrNull', 'defaultRollLengthOf', 'rollFieldsOf', 'createEmptyLineItem',
      'calcInputOf', 'edgeUnitPriceOf', 'edgeMetersOf',
    ],
  },
  {
    file: `${CMP}primitives.tsx`,
    responsibility: '内联小组件 —— 只负责一行字怎么排，不含业务判断',
    symbols: ['SectionTitle', 'Label', 'Row', 'CostRow'],
  },
  {
    file: `${CMP}WizardStep.tsx`,
    responsibility: '折叠骨架 —— 折叠/展开的唯一实现（button 语义 + aria-expanded）',
    symbols: ['CollapsibleHeader', 'WizardStep'],
  },
  {
    file: `${CMP}FabricRow.tsx`,
    responsibility: '布料行 —— 按米卖布的米数 / 单价 / 卷数录入',
    symbols: ['FabricRow'],
  },
  {
    file: `${CMP}LineItemBlock.tsx`,
    responsibility: '部位行 —— 工艺规格 + 算料读数 + 加工项 + 加工费（不持状态、不发请求）',
    symbols: ['LineItemBlockProps', 'REMARK_MAX_LENGTH', 'LineItemBlock'],
  },
  {
    file: `${CMP}ProductGroupBlock.tsx`,
    responsibility: '商品组卡 —— 一块布 = 一组，组级属性改一处同步全组',
    symbols: ['ProductGroupBlockProps', 'ProductGroupBlock'],
  },
]

/** 本判据的**扫描面**：页面 + 8 个单元（顺序无关） */
const SCOPE = [`app/(dashboard)/orders/new/page.tsx`, ...UNITS.map((u) => u.file)].sort()

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.(ts|tsx)$/.test(entry)) out.push(full)
  }
  return out
}

const ALL_FILES = walk(SRC)
const rel = (full: string) => relative(SRC, full).split(sep).join('/')

function stripComments(code: string): string {
  return code
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/\/\/[^\n]*/g, ' ')
}

/** 判「**定义了哪些符号**」用：还要摘掉 import —— `import { type Foo }` 的行内 `type` 修饰符
 *  **长得和** `type Foo = …` 一模一样，不摘掉它，「定义了几次」会被每个 import 方各数一次
 *  （实测踩过：8 个类型被判成定义了 4 份）。 */
function stripImports(code: string): string {
  return code.replace(/import\s+[\s\S]*?\s+from\s+'[^']+'/g, ' ')
}

const textOf = (relPath: string) => readFileSync(join(SRC, relPath), 'utf8')
/** 去注释（**保留** import）—— 判「有没有 import 某个单元」用 */
const codeOf = (relPath: string) => stripComments(textOf(relPath))
/** 去注释 + 去 import —— 判「定义了哪些符号」用 */
const defsOf = (relPath: string) => stripImports(codeOf(relPath))

const KIND = '(?:export\\s+)?(?:default\\s+)?(?:declare\\s+)?(?:async\\s+)?(?:function|const|let|var|class|interface|type)\\s+'

/** 某符号**在本切片面内**被定义在哪些文件里（去注释后再判，避免注释里提到就当定义） */
function definersOf(symbol: string): string[] {
  const re = new RegExp(`(?:^|\\n)\\s*${KIND}${symbol}\\b`)
  return SCOPE.filter((file) => re.test(defsOf(file)))
}

describe('下单页切片结构守卫（issue #8725 第一档）', () => {
  it('① 扫描面非空自证：扫的就是这 9 个文件（少一个 / 多一个都红）', () => {
    // 现取：src 下确实存在这些文件（不存在 ⇒ 下面每条都会「扫 0 处 = 恒绿」，所以先钉死）
    expect(ALL_FILES.map(rel).filter((f) => f === PAGE || f.startsWith(LIB) || f.startsWith(CMP)).sort())
      .toEqual(SCOPE)
    // 反向自证：扫描器真能读到内容（不是空文件 / 读错路径）
    for (const file of SCOPE) expect(textOf(file).length, `${file} 是空文件`).toBeGreaterThan(200)
  })

  it('② 单一真值：登记的每个符号在本切片面内恰好定义 1 次，且就在登记的文件里', () => {
    const ghosts: string[] = []
    for (const unit of UNITS) {
      for (const symbol of unit.symbols) {
        const definers = definersOf(symbol)
        if (definers.length !== 1 || definers[0] !== unit.file) {
          ghosts.push(`${symbol} → 期望只在 ${unit.file}，实得 [${definers.join(', ') || '无'}]`)
        }
      }
    }
    expect(ghosts).toEqual([])
  })

  it('③ 页面只做装配：一处都不再定义这些符号，且从每个单元 import', () => {
    const pageCode = codeOf(PAGE)
    const pageDefs = defsOf(PAGE)
    // ① 页面里不许再出现任何单元的顶层声明（搬漏 / 搬完又抄回来的形态）
    const redefined = UNITS.flatMap((u) => u.symbols).filter((symbol) =>
      new RegExp(`(?:^|\\n)\\s*${KIND}${symbol}\\b`).test(pageDefs)
    )
    expect(redefined).toEqual([])
    // ② 页面必须从**每一个**单元 import（少一个 = 那个单元名存实亡，页面还在跑旧代码）
    // ② 页面**用到**的单元必须真被 import（用不到的不强求：`WizardStep` / `FabricRow` /
    //    `SizeAutoBadges` 是给别的组件用的 ⇒ 它们由下面的判据 ④「无孤儿」兜住）
    const usedButNotImported = UNITS
      .filter((u) => u.symbols.some((symbol) =>
        new RegExp(`(?<![\\w$.])${symbol}(?![\\w$])`).test(pageDefs)))
      .map((u) => `@/${u.file.replace(/\.(tsx|ts)$/, '')}`)
      .filter((spec) => !pageCode.includes(`from '${spec}'`))
    expect(usedButNotImported).toEqual([])
    // 反向自证：页面**确实**装配了这几层（否则上面那条在「页面什么都没用」时也会绿）
    expect(['types', 'display', 'calc'].map((n) => `from '@/lib/order-create/${n}'`)
      .filter((frag) => !pageCode.includes(frag))).toEqual([])
  })

  it('④ 单元可用：无孤儿单元，且模块头声明了单一职责', () => {
    const orphans: string[] = []
    const noDuty: string[] = []
    for (const unit of UNITS) {
      const spec = `@/${unit.file.replace(/\.(tsx|ts)$/, '')}`
      // 有别的源文件真的 import 它（页面之外也算 —— 组件之间互相引用同样有效）
      const imported = ALL_FILES.map(rel)
        .filter((f) => f !== unit.file)
        .filter((f) => codeOf(f).includes(`from '${spec}'`))
      if (imported.length === 0) orphans.push(unit.file)
      // 模块头第一块注释必须讲清「单一职责」（下一个人不用通读 1,800 行去猜）
      const head = textOf(unit.file).slice(0, 1200)
      if (!head.includes('单一职责')) noDuty.push(unit.file)
    }
    expect(orphans).toEqual([])
    expect(noDuty).toEqual([])
    // 台账自身的健全性：职责一句话必须**真的写了一句话**（防「登记成空串」把判据架空）
    expect(UNITS.filter((u) => u.responsibility.trim().length < 6)).toEqual([])
  })

  it('⑤ 依赖方向单向：算料层不许被展示层反向依赖（否则两个单元又在说同一件事）', () => {
    expect(codeOf(`${LIB}display.ts`)).not.toContain("from '@/lib/order-create/calc'")
    expect(codeOf(`${LIB}types.ts`)).not.toContain("from '@/lib/order-create/calc'")
    // 正向必须真接上（否则「一个方向」是空的）：算料层确实用了一次展示层的取色口
    expect(codeOf(`${LIB}calc.ts`)).toContain("from '@/lib/order-create/display'")
  })
})
