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
  /** `@page` 边距（CSS 值） */
  pageMargin: string
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
export const PRINT_MEDIA_IDS = ['a4', 'label-50x60', 'label-30x40', 'continuous-241x140'] as const

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
  if (!geometry) throw new Error(`介质 ${media} 没有登记 dotGeometry（像素口径的唯一真值源）`)
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
 * `@page` 边距（mm）：CSS 简写 `上下 左右`；单值 = 四边同值。非 mm ⇒ 抛错（不猜）。
 * ⚠️ 三联纸的边距是**待实测**通用参数（见矩阵 `pendingMeasurements`）。
 */
export function printPageMarginMm(media: PrintMediaId): { xMm: number; yMm: number } {
  const spec = printMediaSpec(media)
  const parts = spec.pageMargin.trim().split(/\s+/).map(millimetres)
  const [first] = parts
  const second = parts.length > 1 ? parts[1] : parts[0]
  if (first === null || first === undefined || second === null || second === undefined) {
    throw new Error(`介质 ${media} 的 pageMargin=\`${spec.pageMargin}\` 解析不出 mm —— 不猜`)
  }
  return { xMm: second, yMm: first }
}

/**
 * 单张纸的**可用版面（mm）** = 纸 − 页边距。
 * 连续纸（针式）超出可用高度就会打到**下一联**（连续纸跨联 = 纸面与账目对不上的一种形态）。
 */
export function printUsableBoxMm(media: PrintMediaId): { widthMm: number; heightMm: number } {
  const box = printPageBoxMm(media)
  const margin = printPageMarginMm(media)
  return { widthMm: box.widthMm - margin.xMm * 2, heightMm: box.heightMm - margin.yMm * 2 }
}

/**
 * 连续纸的**单联可用高度（mm）** = 页长 − 上下边距（= {@link printUsableBoxMm} 的高度）。
 * ⚠️ 页长与边距都是**待实测**通用参数（见矩阵 `pendingMeasurements`）。
 */
export function printUsableHeightMm(media: PrintMediaId): number {
  return printUsableBoxMm(media).heightMm
}
