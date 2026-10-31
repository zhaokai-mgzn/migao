/**
 * 跨工程**真值源的唯一引用点**（issue #5052 P3；issue #8287 起扩到 50×70 行式标签）
 *
 * 本页要用到几件已经有真值源的东西，它们都落在 `frontend/admin-web`：
 *
 * | 真值 | 真值源（仓库相对全路径） | 谁落的 |
 * |---|---|---|
 * | 入库标签（50×80mm）的**纸型 + 像素口径** | `frontend/admin-web/src/lib/print-media.json` | #5651 打印介质矩阵 |
 * | 成品入库标签 / 发货联（50×70mm）的**纸型 + 像素口径 + 纸长范围** | 同上（`label-50x70`） | #7761 / #7786 / #8287 |
 *
 * ## 🔴 为什么是「直接 import」，不是「各写一份」或「构建期拷贝」
 *
 * 复制一份 400 / 384 / 640 到 bmini ⇒ **同一物理口径出现第二份字面量**，改一处另一处静默漂移
 * （纸面尺寸错 = 打废纸，而**没有任何东西会变红**）。构建期拷贝产出的也是第二份文件，
 * 只是把漂移推迟到「谁忘了跑生成脚本」。⇒ 取**同一份文件、两个消费方**：
 * `frontend/admin-web/src/lib/print-media.json` 是这**唯一**一份（守卫
 * `frontend/bmini-app/tests/inbound-print-geometry-single-source.test.ts` 判「全仓只有一处写着这套字面量」）。
 *
 * ⚠️ 代价（照实登记）：bmini 的构建因此依赖 `frontend/admin-web/src/lib/print-media.json`
 * 这**一个文件路径**（monorepo 内同仓，构建腿在 `frontend/bmini-app` 下跑 `taro build`，路径稳定）。
 * 移动 / 改名它 ⇒ 本模块的 import 当场解析失败（**响亮**，不是静默漂移）。
 * 跨工程引用集中在本文件**一处**：其它 bmini 模块一律从这里取。
 *
 * ## ⚠️ 为什么**没有**把数量口径也 import 进来（照实登记一次实测）
 *
 * `frontend/admin-web/src/lib/stock-quantity.ts` 是 `.ts`，跨工程 import 会撞
 * bmini `tsconfig.json` 的 `rootDir`（实测 `tsc --noEmit`：`TS6059: File … is not under 'rootDir'`），
 * 而 CI 的 `bmini-app typecheck + unit tests` 腿**就跑** `npx tsc --noEmit` ⇒ 那条路走不通。
 * ⇒ 数量口径的真值**留在服务端**（`InboundOrderService.requireItemNumbers`：`> 0` 且最多 1 位小数，
 * 超 1 位**显式拒绝、不静默取整**），端侧**不另立一套数值判定**，只把服务端 400 的文案**原样上屏**
 * （判据：`tests/worker-inbound-page.test.tsx` 的 C5；`tests/inbound-sku-gate.test.ts` 的 C4）。
 */
import matrix from '../../../../admin-web/src/lib/print-media.json'

/**
 * 本页消费的介质 id —— 与 `print-media.json` 的 `media[].id` **逐字一致**。
 * 矩阵里没有它 / 字段缺失 ⇒ 本模块**抛错**（fail-closed：静默回落 = 按 0 像素画一张空标签）。
 */
export const INBOUND_LABEL_MEDIA_ID = 'label-50x80'

/**
 * 成品入库标签 / 发货联共用的介质 id（issue #8287）：50mm 宽连续纸卷、纸长按内容撑开。
 * 与 `frontend/worker-h5/src/shipment.mjs` 的 `SHIP_LABEL_MEDIA_ID` **逐字同名**（同一份真值）。
 */
export const SHIP_LABEL_MEDIA_ID = 'label-50x70'

/**
 * 标签码形态（设计 §7.1，**一次定死**）：`https://app.migaozn.com/i/<8 位短码>`。
 * 码一旦打印就是 URL ⇒ 换域名 / 改路径会让**已打印的码全部失效**，故它是常量、不接受环境变量覆盖。
 */
export const INBOUND_LABEL_CODE_ORIGIN = 'https://app.migaozn.com'
export const INBOUND_LABEL_CODE_PATH = '/i/'

/** 203dpi 热敏头的**像素口径**（矩阵里的 `dotGeometry`；本接口只是它的类型面） */
export interface DotGeometry {
  /** 打印头 dpi（实机 **DP235S** 口径 = 203；**待用 `getPrinterInfo().printerDPI` 复核**） */
  dpi: number
  /** 每毫米点数（203dpi ⇒ 8 dots/mm，取整值；矩阵里写明「= round(dpi / 25.4)」的取整） */
  dotsPerMm: number
  /** 纸宽像素（50mm × 8 = 400px）—— 纸的实际宽度，**不是**可打宽度 */
  widthPx: number
  /** **有效打印宽**像素 = min(纸宽, 打印头宽)：50mm 纸 > 48mm 头 ⇒ 384px（右侧约 2mm 打不到） */
  effectiveWidthPx: number
  /** **打印头宽**像素（48mm × 8 = 384px）：203dpi 的 2 英寸头常见值（**安全侧，待实测**） */
  headWidthPx: number
  /** 纸高像素（80mm × 8 = 640px） */
  heightPx: number
}

interface MediaSpec {
  id: string
  label: string
  pageSize: string
  pageMargin: string
  measurement: string
  pendingMeasurements?: string[]
  note?: string
  dotGeometry?: DotGeometry
  /** 纸型（mm）—— 版面只从这里取，不在渲染器里另写一份 */
  pageBoxMm?: { widthMm: number; heightMm: number }
  /** 连续纸卷的纸长范围（`mode=content` ⇒ 长度按内容撑开） */
  lengthMm?: { mode: string; minMm: number; maxMm: number }
}

/** 纸长范围（mm）：只对连续纸卷介质有；固定纸型 ⇒ 不提供。 */
export interface LabelLengthRange {
  minMm: number
  maxMm: number
}

/** 取介质条目；缺项 ⇒ 抛错（**不**回落到别的介质、**不**兜底默认值） */
function mediaById(id: string): MediaSpec {
  const specs = (matrix as unknown as { media: MediaSpec[] }).media || []
  const spec = specs.find((item) => item.id === id)
  if (!spec) {
    throw new Error(`介质矩阵里没有 \`${id}\`（真值源 = frontend/admin-web/src/lib/print-media.json）`)
  }
  if (!spec.dotGeometry) {
    throw new Error(`介质 \`${id}\` 缺 dotGeometry（纸型与像素口径必须同源在矩阵里）`)
  }
  return spec
}

/** 取本页消费的介质条目（保留旧签名：入库标签链路只认 50×80）。 */
export function inboundLabelMedia(): MediaSpec {
  return mediaById(INBOUND_LABEL_MEDIA_ID)
}

/**
 * 标签的**渲染口径**（标签渲染/打印适配层只读它，不自己写像素字面量）。
 *
 * 🔴 画布取**有效打印宽**（现在 = 头宽：50mm 纸宽于 48mm 头 ⇒ 右侧约 2mm 打不到），
 * 而**不是**任何推定值：DP235S 的**打印头 dpi 与宽度尚未核实**（设计 §8.5 ④），按安全侧设计 ——
 * 连上后读 `getPrinterInfo()` 的 `printerDPI` / `printerWidth` 回填矩阵即可。**1:1 不缩放、不裁切**。
 */
export function labelGeometry(
  id: string,
): DotGeometry & { canvasWidthPx: number; canvasHeightPx: number } {
  const geometry = mediaById(id).dotGeometry as DotGeometry
  return {
    ...geometry,
    canvasWidthPx: geometry.effectiveWidthPx,
    canvasHeightPx: geometry.heightPx,
  }
}

/** 入库标签（50×80）的渲染口径（旧调用点保持不变）。 */
export function inboundLabelGeometry(): DotGeometry & { canvasWidthPx: number; canvasHeightPx: number } {
  return labelGeometry(INBOUND_LABEL_MEDIA_ID)
}

/**
 * 纸型（mm）—— 版面 / 测试只从这里取。
 * 介质矩阵缺 `pageBoxMm` ⇒ 抛错（版面不能猜一个尺寸）。
 */
export function labelPaperBox(id: string): { widthMm: number; heightMm: number } {
  const box = mediaById(id).pageBoxMm
  if (!box || !box.widthMm || !box.heightMm) {
    throw new Error(`介质 \`${id}\` 缺 pageBoxMm（纸型必须同源在矩阵里）`)
  }
  return { widthMm: box.widthMm, heightMm: box.heightMm }
}

/**
 * 连续纸卷的纸长范围（mm）—— 发货联按内容撑开（下限 / 上限）的唯一真值。
 * 固定纸型 / 缺 `lengthMm` ⇒ 抛错（调用方要的是「按内容撑开」，不能静默按固定纸长出图）。
 */
export function labelLengthRange(id: string): LabelLengthRange {
  const range = mediaById(id).lengthMm
  if (!range || !range.minMm || !range.maxMm) {
    throw new Error(`介质 \`${id}\` 缺 lengthMm（按内容撑开的纸长范围必须同源在矩阵里）`)
  }
  return { minMm: range.minMm, maxMm: range.maxMm }
}

/** 短码 ⇒ 标签上的码内容（设计 §7.1 的唯一拼装处） */
export function inboundLabelCodeUrl(shortCode: string): string {
  return `${INBOUND_LABEL_CODE_ORIGIN}${INBOUND_LABEL_CODE_PATH}${shortCode}`
}
