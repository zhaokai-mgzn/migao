/**
 * 工人库存修正 · **拍照识别批次号**（issue #8210；用户 2026-10-31 逐字「通过拍照来识别批次号」）。
 *
 * ## 为什么是纯函数（而不是写在页面的 onClick 里）
 *
 * 入口顺序 = **扫标签二维码优先（0 次 LLM）→ 解不出才让服务端走 vision → 都失败就手输**，
 * 这是一条**成本守卫**（会烧钱的顺序）。写在页面里，下一个人加一条「重试」分支就可能
 * 把 vision 排到前面，而**没有任何东西会变红**（同 `inbound/recognizeFlow.ts` 的既有理由）。
 * ⇒ 顺序收敛成一个纯函数，判据用**假服务端计数**钉住：
 * 标签码命中时 `recognize` 一次都不许被调用（`tests/worker-stock-recognize.test.ts` ①）。
 *
 * ## 三条口径（与后端 / ai-agent 逐字对齐）
 *
 * 1. 🔴 **识别只做定位**：本模块只产出「批次号字符串」；选中批次、填实盘米数、二次确认、提交
 *    全是页面与人（提交仍是 `buildCorrectionBody` → `/correction`，本模块一个写请求都不发）；
 * 2. 🔴 **不猜**：批次号**精确相等**才算命中（`locateByBatchNo`）；同号多行 ⇒ 交人点选；
 *    识别不出来 ⇒ 明确给**手输出路**（不静默、也不拿「最近入库的批次」凑一个）；
 * 3. 🔴 **两种「没有」分开说**：`degraded`（图不行 / 没认出来）与 401（会话失效）是两件事 ——
 *    后者透出 `statusCode` 让页面引导登录，**不许**渲染成「没认出来」（那会让工人反复重拍）。
 */
import type { DecodeOutcome, PendingPhoto } from './inbound/barcodeDecode'
import { classifyScannedCode } from './inbound/codeSpace'
import type { StockBatchRow } from './workerStock'

/** 一次最多几张：与服务端 `WorkerBatchStockService#recognize` 的准入同一上限（不各写一份口径）。 */
export const STOCK_RECOGNIZE_MAX_PHOTOS = 3

/** 没认出来（degraded / 空值）：给手输出路，**不静默**。 */
export const STOCK_RECOGNIZE_MANUAL_HINT =
  '没认出批次号：把标签上的批次号拍清楚一点，或直接在搜索框手输'

/** 拍到了我们自己的标签，但这一批还没过账（`stock_batches` 里还没有批次号）。 */
export const STOCK_LABEL_NO_BATCH_HINT =
  '这张标签上的批次还没过账（没有批次号）—— 请核对是不是拍错了标签'

/** 标签读不到（404 / 网络）：与「没过账」分开说，且都给手输出路。 */
export const STOCK_LABEL_LOOKUP_FAILED_HINT = '读取标签失败，请重试；也可以直接在搜索框手输批次号'

/** 识别服务没响应（断网 / 离线）：不是「没认出来」。 */
export const STOCK_RECOGNIZE_OFFLINE_HINT = '识别服务没响应，请重试；也可以直接在搜索框手输批次号'

/** 识别端点报错（5xx 等）：原文留在请求层，屏上给可行动的一句。 */
export const STOCK_RECOGNIZE_FAILED_HINT = '识别没成功，请重试；也可以直接在搜索框手输批次号'

/** 用户拍完照但没选（取消）：什么都不做（页面据此静默返回，不弹错）。 */
export const STOCK_RECOGNIZE_CANCELLED_HINT = ''

/** 识别字段表里的一格（ai-agent 的出口形状；端侧只读 `key` / `value`，不重建表）。 */
export interface RecognizedFieldCell {
  key?: string | null
  label?: string | null
  value?: string | null
  source?: string | null
  reason?: string | null
  reference?: string | null
}

/**
 * 批次号归一：**去空白 + 大写**。
 *
 * 只做无损动作 —— **不补零、不换分隔符、不做全角→半角**：标签印的是大写 `PC-yyyyMMdd-NNNN`
 * （V111 的生成口径），OCR 偶尔带回抄写空格 / 小写；替 OCR 改字，改对了没人知道，
 * 改错了就是把 A 批的账记到 B 批上。
 */
export function normalizeBatchNo(raw: string | null | undefined): string {
  return String(raw ?? '').replace(/\s+/g, '').toUpperCase()
}

/**
 * 从识别字段表里取批次号：**只认 `batch_no` 一格**，值非空才采纳。
 *
 * 为什么不在端侧校验形态：形态硬闸在 ai-agent（`recognizer._normalise_batch_no`，唯一真值）。
 * 端侧再写一份正则 = 第二份会漂的口径；这里只做「取」与比对。
 */
export function pickRecognizedBatchNo(
  fields: RecognizedFieldCell[] | null | undefined,
): string | null {
  for (const cell of fields ?? []) {
    if (String(cell?.key ?? '') !== 'batch_no') continue
    const value = normalizeBatchNo(cell?.value)
    if (value !== '') return value
  }
  return null
}

/** 定位结果（三态分开：选中 / 同号多行 / 没有这个批次）。 */
export type BatchLocation =
  | { kind: 'selected'; row: StockBatchRow }
  | { kind: 'ambiguous'; rows: StockBatchRow[] }
  | { kind: 'not-found'; batchNo: string }

/**
 * 在搜索结果里按批次号**精确**定位。
 *
 * 🔴 不用 `includes` / 前缀匹配：`PC-20261031-0001` 与 `PC-20261031-00011` 是两个批次，
 * 模糊命中会把账改到错误的那一卷上。同号多行（数据异常）⇒ `ambiguous`，交人点选。
 */
export function locateByBatchNo(
  rows: StockBatchRow[] | null | undefined,
  batchNo: string | null | undefined,
): BatchLocation {
  const wanted = normalizeBatchNo(batchNo)
  const exact =
    wanted === ''
      ? []
      : (rows ?? []).filter((row) => normalizeBatchNo(row?.batch_no) === wanted)
  if (exact.length === 1) return { kind: 'selected', row: exact[0] }
  if (exact.length > 1) return { kind: 'ambiguous', rows: exact }
  return { kind: 'not-found', batchNo: wanted }
}

/** 一次识别的依赖（页面注入真实现，判据注入替身 —— 顺序与计数才可被钉住）。 */
export interface StockRecognizeDeps {
  photos: PendingPhoto[]
  /** 本机解码（0 次 LLM）—— `decodeBarcodeFromPhoto` 或测试替身 */
  decode: (photo: PendingPhoto) => Promise<DecodeOutcome>
  /** 按短码读标签详情里的批次号（`GET /api/worker/inbound/labels/{短码}`） */
  lookupLabelBatchNo: (
    shortCode: string,
  ) => Promise<{ batchNo?: string | null; failed?: boolean }>
  /** 上传一张 ⇒ 拿 URL（`POST /api/worker/inbound/upload`，与拍照入库同一条上传腿） */
  upload: (photo: PendingPhoto) => Promise<string>
  /** 服务端识别（`POST /api/worker/batch-stock/recognize`） */
  recognize: (payload: { images: string[] }) => Promise<{
    success?: boolean
    data?: { fields?: RecognizedFieldCell[] | null; degraded?: boolean } | null
    message?: string | null
    statusCode?: number
    offline?: boolean
  }>
}

/** 端侧走了哪条路（`label-qr` ⇒ 本次**零** LLM 调用）。 */
export type StockRecognizeRoute = 'label-qr' | 'vision'

export interface StockRecognizeOutcome {
  route: StockRecognizeRoute
  /** 定位到的批次号（归一后）；`null` = 没识别出来 / 标签没有批次号 */
  batchNo: string | null
  /** 要对工人说的话（空 = 无事发生，正常进入定位）；**不上屏过程叙述**（§31 P3） */
  notice: string
  /** 端侧**期望**的 LLM 调用次数（判据据此与假服务端计数比对） */
  expectedLlmCalls: number
  /** 401 透出（页面据此引导登录） */
  statusCode?: number
}

/**
 * 跑一次「照片 → 批次号」。
 *
 * @throws 由 `decode` / `upload` / `recognize` 抛出的异常（页面统一兜底成「手输」提示，不吞在纯函数里）
 */
export async function runStockRecognize(
  deps: StockRecognizeDeps,
): Promise<StockRecognizeOutcome> {
  const photos = (deps.photos ?? []).slice(0, STOCK_RECOGNIZE_MAX_PHOTOS)
  if (photos.length === 0) {
    return {
      route: 'vision',
      batchNo: null,
      notice: STOCK_RECOGNIZE_MANUAL_HINT,
      expectedLlmCalls: 0,
    }
  }

  // ── ① 本机解码优先（0 次 LLM）：只有**入库标签**码谈得上查批次号 ────────────────
  for (const photo of photos) {
    const outcome = await deps.decode(photo)
    const reading = classifyScannedCode(outcome?.text ?? '')
    if (reading.space !== 'inbound-label' || !reading.shortCode) continue

    const label = await deps.lookupLabelBatchNo(reading.shortCode)
    if (label?.failed) {
      return {
        route: 'label-qr',
        batchNo: null,
        notice: STOCK_LABEL_LOOKUP_FAILED_HINT,
        expectedLlmCalls: 0,
      }
    }
    const batchNo = normalizeBatchNo(label?.batchNo)
    if (batchNo === '') {
      // 🔴 未过账的标签没有批次号：**不退回 OCR 去猜**（图上根本没有这一格，问模型只会得到幻觉）
      return {
        route: 'label-qr',
        batchNo: null,
        notice: STOCK_LABEL_NO_BATCH_HINT,
        expectedLlmCalls: 0,
      }
    }
    return { route: 'label-qr', batchNo, notice: '', expectedLlmCalls: 0 }
  }

  // ── ② 解不出标签码 ⇒ 上传后让服务端走 vision（1 次）──────────────────────────
  const urls: string[] = []
  for (const photo of photos) urls.push(await deps.upload(photo))
  const response = await deps.recognize({ images: urls })

  if (response?.statusCode === 401) {
    // 会话失效**不是**「没认出来」：透出去让页面引导登录（否则工人会反复重拍）
    return { route: 'vision', batchNo: null, notice: '', expectedLlmCalls: 1, statusCode: 401 }
  }
  if (!response?.success || !response.data) {
    return {
      route: 'vision',
      batchNo: null,
      notice: response?.offline ? STOCK_RECOGNIZE_OFFLINE_HINT : STOCK_RECOGNIZE_FAILED_HINT,
      expectedLlmCalls: 1,
    }
  }

  const batchNo = pickRecognizedBatchNo(response.data.fields)
  if (batchNo === null) {
    return {
      route: 'vision',
      batchNo: null,
      notice: STOCK_RECOGNIZE_MANUAL_HINT,
      expectedLlmCalls: 1,
    }
  }
  return { route: 'vision', batchNo, notice: '', expectedLlmCalls: 1 }
}
