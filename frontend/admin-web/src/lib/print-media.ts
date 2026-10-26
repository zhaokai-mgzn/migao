/**
 * 打印**介质矩阵**读取口（issue #5651）—— 介质是**参数**，不是复制粘贴出来的页面。
 *
 * ## 三层分层（本文件是第二层的唯一入口）
 *
 * | 层 | 是什么 | 落在哪 |
 * |---|---|---|
 * | ① 内容 / 字段映射 | 这张单据**印什么**（列清单 + 取值口径） | 各单据组件（`*Doc.tsx`），每份**只有一份**映射 |
 * | ② 介质 | 印在**什么纸**上（尺寸 / 边距 / 技术 / 复写份数 / 字号预算） | 本文件 + `print-media.json` |
 * | ③ 打印隔离 | 一次只放一份单据上纸 | `body > *:not(.print-doc)`（#4983） |
 *
 * 用户 2026-09-26 逐字裁定销售单要挂在**三联纸（针式 + 连续纸 + 压感复写）**上 —— 那是全仓
 * 此前**零支持**的第三种介质。同一份销售单字段映射既能落三联纸、也能落 A4 ⇒ 介质做成
 * `SalesDoc` 的 **prop**，而不是再写一个 A4 版组件。
 *
 * 🔴 **不许在单据里另写 `@page { size: … }`**：`printPageRule()` 是唯一写法；
 * 守卫 `tests/unit_ci_workflows/test_print_media_matrix_guard.py` 会把单据里的 `@page`
 * 逐字钉回 `print-media.json`（写岔 = 纸面尺寸错 = 打废纸，且**没有任何东西会因此变红**）。
 *
 * ⚠️ 真机参数（走纸长度 / 边距 / 每行行高 / 最小字号）本机拿不到 ⇒ 矩阵里用**通用参数**并把
 * 每一项**显式登记为待实测**（`measurement` + `pendingMeasurements`）。**不要**把推定值
 * 当实测值写进来。
 */
import matrix from './print-media.json'

/** 介质技术（决定版面预算，不是文案） */
export type PrintMediaTechnology = 'laser-inkjet' | 'thermal-transfer' | 'dot-matrix'

/** 一种打印介质的**机器可读**描述（真值源 = `print-media.json`，本接口只是它的类型面） */
export interface PrintMediaSpec {
  id: string
  label: string
  technology: PrintMediaTechnology
  /** `@page` 尺寸（CSS 值；三联纸 = 用户裁定的 241mm × 140mm 两等分单联） */
  pageSize: string
  /** `@page` 边距（CSS 值）—— **浏览器吃的那一层**：页眉页脚就画在这段边距里（见 {@link BROWSER_CHROME_MARGIN_MM}） */
  pageMargin: string
  /**
   * **版面内缩**（CSS 长度，缺省 = 用 `pageMargin`）：纸边到版心的真实距离。
   *
   * 只在「`@page` 边距必须写成 0」的介质上登记（目前只有 A4，issue #7309）——那种介质里
   * 内缩改由**单据容器的 padding** 承担（`printContentInsetCss()`），纸面观感与 `@page`
   * 边距直接写 12mm 时逐毫米一致。
   * 🔴 登记了它 ⇒ `pageMargin` 必须为 `0`（否则两层内缩叠加，版面悄悄变窄；`browserChromeMarginProblems()` 判红）。
   */
  contentInset?: string
  /**
   * **纸的整幅尺寸（mm）** —— 机器可读的「这张纸多大」：打印前的纸面自检（预览纸框 / 溢出与页数）
   * 读它。`pageSize` 是 CSS 值（可能是 `A4` 这种命名纸型，解析不出 mm），故 mm 口径单独放这里。
   * 🔴 与 `pageSize` 必须指同一张纸（改一处不改另一处 ⇒ 判据 `test_print_media_matrix_guard.py` 的目视面）。
   */
  pageBoxMm: { widthMm: number; heightMm: number }
  /** **连续走纸**（针式）：靠走纸孔定位，浏览器不许按内容分页（错位 = 跨联） */
  continuousFeed: boolean
  /** **压感复写份数**（纸承担；软件**只渲染一页**） */
  carbonCopies: number
  /** 正文基准字号（pt）—— 针打不许沿用 A4 的字号预算 */
  minFontPt: number
  /**
   * **纸长按内容撑开**（连续纸卷专用，issue #7776）。
   *
   * 登记了它 ⇒ `pageBoxMm.heightMm` / `pageSize` 描述的是**最短**纸长（驱动里该登记的那档），
   * 实际纸长由 `frontend/admin-web/src/lib/label-print/wash-label-metrics.ts` 的 `washLabelLengthMm()`
   * 按纸面内容算出、夹在 `[minMm, maxMm]`，`@page` 用 {@link printPageRuleForLength} 现拼。
   *
   * 🔴 三处必须读**同一个数**：系统打印的 `@page` / 蓝牙直连的画布高度 / 打印预览的纸框 ——
   * 各算一份 ⇒ 预览与纸上又会对不上（issue #6656 踩过的形态）。
   */
  lengthMm?: {
    mode: 'content'
    /** 最短纸长（mm）；等于 `pageBoxMm.heightMm` */
    minMm: number
    /** 最长纸长（mm）：再长说明内容该拆了，**夹住**而不是无限印 */
    maxMm: number
    /** 为什么按内容撑开（人读） */
    why: string
  }
  /** `measured` = 有实测读数；`pending-field-measurement` = 通用参数 + 待现场实测 */
  measurement: 'measured' | 'pending-field-measurement'
  /** 待实测清单（非 `measured` 时**必须非空** —— 守卫判红） */
  pendingMeasurements: string[]
  /** 人读说明：现在用的是哪个值、为什么 */
  note: string
  /**
   * **点阵口径**（仅热敏标签机这类「按 dots 出图」的介质有）—— issue #5052 的 30×40mm 入库标签。
   *
   * 🔴 它是 240 / 320 / 384 / 8 dots/mm 这组数字的**唯一一份字面量**：设备侧（bmini 的 canvas 渲染）
   * **跨工程直接 import 本 JSON** 取值，不复制、不做构建期拷贝
   * （守卫 `frontend/bmini-app/tests/inbound-print-geometry-single-source.test.ts`：别处出现第二份 ⇒ 红）。
   */
  dotGeometry?: {
    /** 打印头 dpi */
    dpi: number
    /** 每毫米点数 */
    dotsPerMm: number
    /** 纸宽像素（纸的实际宽度，**不是**可打宽度） */
    widthPx: number
    /** **有效打印宽**像素 = min(纸宽, 打印头宽) */
    effectiveWidthPx: number
    /** **打印头宽**像素（安全侧；未核实的机型参数按它取保守值） */
    headWidthPx: number
    /** 纸高像素 */
    heightPx: number
  }
}

/**
 * 介质 id 的**唯一字面量清单**（`PrintMediaId` 由它推出来）。
 * 🔴 与 `print-media.json` 的 `media[].id` 集必须逐字一致 —— 由
 * `tests/unit/lib/print-media.test.ts` 钉住：只改一边 ⇒ 必红（否则新增介质会静默地
 * 「矩阵里有、类型上没有」，调用方只能写 `as any` 绕过类型）。
 */
export const PRINT_MEDIA_IDS = ['a4', 'label-50x70', 'label-30x40', 'continuous-241x140'] as const

export type PrintMediaId = (typeof PRINT_MEDIA_IDS)[number]

const SPECS = matrix.media as unknown as PrintMediaSpec[]

/** 矩阵本身（按 id 索引）；未知 id 由 `printMediaSpec()` 显式抛错，不静默回落到 A4 */
export const PRINT_MEDIA_SPECS: Record<string, PrintMediaSpec> = Object.fromEntries(
  SPECS.map((spec) => [spec.id, spec])
)

/** 取介质描述；**未知 id 直接抛错**（静默回落 = 把三联纸打成 A4 而不出声） */
export function printMediaSpec(media: PrintMediaId): PrintMediaSpec {
  const spec = PRINT_MEDIA_SPECS[media]
  if (!spec) throw new Error(`未知打印介质：${String(media)}（登记在 lib/print-media.json）`)
  return spec
}

/** 设备侧**点阵口径**（`dotGeometry` 块）—— 像素字面量的真正归属地（issue #6439） */
export interface PrintDotGeometry {
  dpi: number
  dotsPerMm: number
  /** 纸宽换来的像素数（未受打印头限制） */
  widthPx: number
  /** **实际可打**像素数（= min(纸宽像素, 打印头像素)）—— 出图必须用这个 */
  effectiveWidthPx: number
  headWidthPx: number
}

/**
 * 取某介质的设备点阵口径。
 *
 * 🔴 这是**像素字面量的唯一出口**：渲染模块（洗水码 / 入库标签）不许再写第二份 `384` ——
 * 写死一处、另一处漂移，打出来就是「标签尺寸错 / 二维码被非整数倍重采样糊掉」，
 * 而两边都不会报错（`frontend/bmini-app/tests/inbound-print-geometry-single-source.test.ts` 的 C2b 钉住）。
 *
 * 缺登记 ⇒ **抛错**（fail-closed）：静默回落到一个通用值 = 把别人的纸打成我们的口径。
 */
export function printDotGeometry(media: PrintMediaId): PrintDotGeometry {
  const spec = PRINT_MEDIA_SPECS[media] as (PrintMediaSpec & { dotGeometry?: PrintDotGeometry }) | undefined
  const geometry = spec?.dotGeometry
  if (!geometry) throw new Error(`介质 ${media} 还没登记像素参数，无法换算尺寸`)
  return geometry
}

/**
 * `@page` 规则的**唯一写法**（单据用它，不自己拼字符串）。
 * 例：`@page { size: 241mm 140mm; margin: 6mm 12mm; }`
 */
export function printPageRule(media: PrintMediaId): string {
  const spec = printMediaSpec(media)
  return `@page { size: ${spec.pageSize}; margin: ${spec.pageMargin}; }`
}

/**
 * 纸长**按内容撑开**的介质（连续纸卷）的纸长区间（mm）；没登记 ⇒ `null`。
 * 真值源 = 矩阵的 `lengthMm`（本文件不写第二份）。
 */
export function printLengthRangeMm(media: PrintMediaId): { minMm: number; maxMm: number } | null {
  const length = printMediaSpec(media).lengthMm
  if (!length) return null
  return { minMm: length.minMm, maxMm: length.maxMm }
}

/**
 * `@page` 规则的**动态纸长写法**（issue #7776）：宽 / 边距仍取自矩阵，**长度由调用方给**
 * （= `washLabelLengthMm()` 算出的纸长，夹在 `lengthMm.minMm ~ maxMm`）。
 *
 * 🔴 只对登记了 `lengthMm` 的介质开放：别的介质（A4 / 三联纸）纸型是固定的，
 * 传长度进来 = 把别人的纸打成我们的口径 ⇒ **显式抛错**（fail-closed，不静默忽略）。
 */
export function printPageRuleForLength(media: PrintMediaId, lengthMm: number): string {
  const spec = printMediaSpec(media)
  const range = printLengthRangeMm(media)
  if (!range) {
    throw new Error(`介质 ${media} 没有登记 lengthMm（纸长按内容撑开）—— 不许用动态纸长覆盖固定纸型`)
  }
  const value = Number.isFinite(lengthMm) ? lengthMm : range.minMm
  const clamped = Math.min(Math.max(value, range.minMm), range.maxMm)
  return `@page { size: ${spec.pageBoxMm.widthMm}mm ${clamped}mm; margin: ${spec.pageMargin}; }`
}

/** 正文基准字号（pt）：介质决定版面预算，单据只读它、不自己定字号 */
export function printBodyFontPt(media: PrintMediaId): number {
  return printMediaSpec(media).minFontPt
}

/** 连续走纸介质（针式）：容器必须按纸固定、`overflow: hidden`，否则会打到下一联 */
export function isContinuousFeed(media: PrintMediaId): boolean {
  return printMediaSpec(media).continuousFeed
}

/** `12mm` / `0` / `A4` ⇒ 数值或 null（只认 mm 与裸 `0`；其它单位一律 null，不猜） */
function millimetres(value: string): number | null {
  const text = value.trim()
  if (text === '0') return 0
  const hit = /^([0-9.]+)mm$/.exec(text)
  return hit ? Number(hit[1]) : null
}

/**
 * 浏览器（Chrome）**开始画页眉页脚**的页边距实测下限（mm）—— 历史读数，现在**只作说明**（issue #7309）。
 *
 * A4 + `displayHeaderFooter: true` + `preferCSSPageSize: true`（Chromium 1243 = Chrome 14x）：
 * `@page { margin: 8.7mm }` ⇒ **不画**；`8.8mm` ⇒ 画（版式日期 / 文档标题 / 页面 URL / 页码）；
 * 12mm（= A4 改前的值）⇒ 画；`0`（+ 容器内缩 12mm）⇒ 不画。
 *
 * 🔴 **2026-10-25 收口（用户逐字：「我希望做到即使勾着也不要打印出页眉和页脚」）**：
 * 8.7mm 是一条**未文档化**的分界 —— 拿「比它小一点的边距」去赌（例如三联纸原值 6mm）本质上
 * 是把纸面交给浏览器的实现细节。现在**全矩阵一律 `@page` 边距 = 0**（0 边距 = 没有可画的边距
 * = 结构性不出，不依赖任何阈值），版面内缩一律走 `contentInset` + 单据容器 padding。
 * 本常量保留**只作说明**（它解释了「为什么不能有小边距」），判据里**不再**拿它当容忍度
 * （见 {@link browserChromeMarginProblems}：非零上下边距直接判红）。
 */
export const BROWSER_CHROME_MARGIN_MM = 8.7

/**
 * 一份介质的**版面内缩**（mm）：`contentInset` 优先，缺省即 `@page` 边距（解析不出 ⇒ 抛错，不猜）。
 *
 * `PrintDocPreview` 的纸框与纸面自检（可用版面）读它 —— 「印出来占多大地方」是版面真值，
 * 与「浏览器把页眉页脚画在哪儿」是两件事，只有后者会被写成 0（issue #7309）。
 */
export function printContentInsetMm(media: PrintMediaId): { xMm: number; yMm: number } {
  const spec = printMediaSpec(media)
  const css = spec.contentInset ?? spec.pageMargin
  const parts = css.trim().split(/\s+/).map(millimetres)
  const [first] = parts
  const second = parts.length > 1 ? parts[1] : parts[0]
  if (first === null || first === undefined || second === null || second === undefined) {
    throw new Error(`介质 ${media} 的版面内缩「${css}」解析不出 mm —— 不猜`)
  }
  return { xMm: second, yMm: first }
}

/**
 * 单据容器要自己承担的**内缩 padding**（CSS 值）—— 与 `@page` 边距**互补**：
 * `@page` 边距为 0 的介质（A4）返回 `12mm`，其余介质返回 `0`（内缩已由 `@page` 边距给过）。
 *
 * 用法（单据的 `@media print`）：`padding: ${printContentInsetCss(media)};` 并配
 * `box-decoration-break: clone` —— 实测：不 clone 时第 2 页起 `padding-top` 不重复（内容贴到纸边）。
 */
export function printContentInsetCss(media: PrintMediaId): string {
  return printMediaSpec(media).contentInset ?? '0'
}

/**
 * **类级守卫**：介质矩阵里任何一行都不许落进「浏览器会画页眉页脚」的形态（issue #7309 → 2026-10-25 收口）。
 *
 * 三条判据（返回人读问题清单，空 = 合规）：
 * 1. 上下 `@page` 边距**不是 0** ⇒ 页眉页脚就有被画出来的路（Chrome 把日期 / 标题 / URL / 页码
 *    画在 `@page` 的页边距里；实测下限 8.7mm，但那是一条未文档化的分界，**不再当容忍度**）；
 * 2. 上下边距为 0 却**没登记 `contentInset`** ⇒ 内容贴到纸边（打印机不可打区会裁掉首末行）——
 *    热敏标签例外（整幅出图，纸边就是版心）；
 * 3. 登记了 `contentInset` 而 `@page` 边距不为 0 ⇒ 两层内缩叠加（版面悄悄变窄）。
 */
export function browserChromeMarginProblems(spec: PrintMediaSpec): string[] {
  const margin = (spec.pageMargin || '').trim()
  const parts = margin.split(/\s+/).map(millimetres)
  const [first] = parts
  const second = parts.length > 1 ? parts[1] : parts[0]
  if (first === null || first === undefined || second === null || second === undefined) {
    return [`介质 ${spec.id} 的纸型边距「${spec.pageMargin}」解析不出 mm —— 判不了会不会画出页眉页脚`]
  }
  const problems: string[] = []
  const vertical = first
  const thermal = spec.technology === 'thermal-transfer'
  if (vertical !== 0) {
    problems.push(
      `介质 ${spec.id} 的上下页边距是 ${vertical}mm（不是 0）⇒ 浏览器会在这段留白里印出日期、标题、` +
        '网址与页码四行（那不是我们画的内容）；把上下页边距写成 0，版面留白改由单据容器的内边距承担'
    )
  }
  if (vertical === 0 && !thermal && !spec.contentInset) {
    problems.push(
      `介质 ${spec.id} 的上下页边距是 0 且没有登记版面内缩 ⇒ 内容会贴到纸边` +
        '（打印机不能打印的边缘会裁掉首末行）；请登记版面内缩，由单据容器承担'
    )
  }
  if (spec.contentInset && vertical !== 0) {
    problems.push(
      `介质 ${spec.id} 同时有版面内缩 ${spec.contentInset} 与非零纸型边距 ${margin} ⇒ ` +
        '两层内缩会叠加（版面悄悄变窄）；版面内缩只在纸型边距为 0 时登记'
    )
  }
  return problems
}

/** 纸的**整幅尺寸（mm）**（真值源 = 矩阵的 `pageBoxMm`，命名纸型如 `A4` 也在这里落到 mm） */
export function printPageBoxMm(media: PrintMediaId): { widthMm: number; heightMm: number } {
  const spec = printMediaSpec(media)
  const box = spec.pageBoxMm
  if (!box || !Number.isFinite(box.widthMm) || !Number.isFinite(box.heightMm)) {
    throw new Error(`介质 ${media} 缺 pageBoxMm（纸的整幅 mm 尺寸）—— 纸面自检无从判定，不猜`)
  }
  return { widthMm: box.widthMm, heightMm: box.heightMm }
}

/**
 * 单张纸的**可用版面（mm）** = 纸 − 版面内缩（`printContentInsetMm`，不是 `@page` 边距 ——
 * A4 的 `@page` 边距是 0，内缩在容器 padding 上；issue #7309）。
 * 连续纸（针式）超出可用高度就会打到**下一联**（连续纸跨联 = 纸面与账目对不上的一种形态）。
 */
export function printUsableBoxMm(media: PrintMediaId): { widthMm: number; heightMm: number } {
  const box = printPageBoxMm(media)
  const margin = printContentInsetMm(media)
  return { widthMm: box.widthMm - margin.xMm * 2, heightMm: box.heightMm - margin.yMm * 2 }
}

/**
 * 连续纸的**单联可用高度（mm）** = 页长 − 上下边距（= {@link printUsableBoxMm} 的高度）。
 * ⚠️ 页长与边距都是**待实测**通用参数（见矩阵 `pendingMeasurements`）。
 */
export function printUsableHeightMm(media: PrintMediaId): number {
  return printUsableBoxMm(media).heightMm
}
