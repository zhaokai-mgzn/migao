/**
 * 识别主链：**先本机解码 → 解不出才让服务端走 vision**（issue #5052 P3；设计 §6.1 / §6.2）
 *
 * ## 顺序为什么写在这里而不是页面里
 *
 * 「照片含可解条码时不得走 LLM」是**成本守卫**（可以烧钱的那种），把它写在页面的 `onClick` 里
 * ⇒ 下一个人加一条"重试"分支就可能把 vision 排到前面，而**没有任何东西会变红**。
 * 故顺序收敛成一个纯函数，判据（`tests/inbound-decode-first.test.ts`）用一个**假服务端**计数：
 * 解码命中时 `llmCalls === 0`；把顺序反过来 ⇒ 当场红。
 *
 * ## 上传口径（为什么解码命中只传 1 张）
 *
 * 服务端 `recognize` 要求 `images` **至少 1 张**（`validImages`：空列表 ⇒ 400，理由是
 * 「系统不会拿空列表去问模型」）。解码命中时只需要**那一张**（留痕 + 服务端按条码查 SKU），
 * 传 3 张纯属浪费工人的流量 ⇒ 命中时只传解出码的那一张。
 *
 * ## 上限与来源
 *
 * 一次最多 3 张（与服务端 `WorkerInboundService.MAX_IMAGES` 同口径；超出由服务端 400 兜底，
 * 端侧先拦一次只是为了不让工人白等）。
 *
 * ## 不上屏（issue #7818；用户 2026-10-26 逐字「为什么会出现，移除掉」）
 *
 * 本链**不向页面投放过程叙述**：解码没命中而服务端认回来了 = **正常路径**，工人不需要知道
 * 「这一次走了哪一条路」（§31 P3 不摆内部标识）；要不要人工核对由**确认卡**说清
 * （`prefillFromRecognize().notice` + 卡标题），服务端 `message` 原样上屏。
 *
 * 旧形态（被用户点名的，截图见 issue #7818）：① 每张图解不出码的 `hint` 全部 push 进 `notices`；
 * ② 走 vision 兜底**成功后**又 push 一句「系统换一种方式再认了一次…」 ⇒ 一个良性事件说了两遍，
 * 而且切到「入库标签」步还在 —— 「下面的结果」那时已经不在屏上了。
 * 判据：frontend/bmini-app/tests/worker-inbound-page.test.tsx（C13）+ inbound-decode-first.test.ts（C4）。
 */
import type { DecodeOutcome, PendingPhoto } from './barcodeDecode'
import type { RecognizeLike } from './recognizeGate'

/** 与服务端 `WorkerInboundService.MAX_IMAGES` 同口径 */
export const MAX_INBOUND_PHOTOS = 3

/** 本次走的识别路径（端侧视角：**服务端回执里的 `path` 是权威**，这里只是「我送了什么」） */
export type RecognizeRoute = 'local-barcode' | 'server-vision'

export interface RecognizeFlowDeps {
  /** 已选照片（1~3 张；两端形态不同，见 `PendingPhoto`） */
  photos: PendingPhoto[]
  /** 本机解码（0 次 LLM）—— `decodeBarcodeFromPhoto` 或测试替身 */
  decode: (photo: PendingPhoto) => Promise<DecodeOutcome>
  /** 上传一张 ⇒ 拿 URL（`POST /api/worker/inbound/upload`） */
  upload: (photo: PendingPhoto) => Promise<string>
  /** 服务端识别（带 `barcode` ⇒ 服务端走解码优先路径、**零 LLM**） */
  recognize: (payload: { images: string[]; barcode?: string | null }) => Promise<RecognizeLike>
}

export interface RecognizeFlowResult {
  /** 服务端回执（原样，不在端侧二次加工） */
  response: RecognizeLike
  /** 端侧走了哪条路（用来在页面上说明「本次没问模型」/「本次走了识别」） */
  route: RecognizeRoute
  /** 本机解码的原文（服务端 vision 路径时为 null） */
  decodedBarcode: string | null
  /** 上传了几张（判据：解码命中 ⇒ 1 张） */
  uploadedCount: number
  /** 端侧**期望**的 LLM 调用次数（`local-barcode` ⇒ 0）—— 与假服务端计数比对用 */
  expectedLlmCalls: number
}

/**
 * 跑一次识别。
 *
 * @throws 一张照片都没有 ⇒ 抛错（服务端同样 400；端侧先说清比让用户等一次往返好）
 */
export async function runInboundRecognize(deps: RecognizeFlowDeps): Promise<RecognizeFlowResult> {
  const photos = (deps.photos || []).slice(0, MAX_INBOUND_PHOTOS)
  if (photos.length === 0) {
    throw new Error('请先拍照（至少 1 张上游标签 / 布卷包装照）')
  }

  let decodedBarcode: string | null = null
  let decodedIndex = -1

  // ── ① 本机解码优先（0 次 LLM）──────────────────────────────────────────────
  for (let index = 0; index < photos.length; index += 1) {
    const outcome = await deps.decode(photos[index])
    if (outcome.text) {
      decodedBarcode = outcome.text
      decodedIndex = index
      break
    }
  }

  // ── ② 解码命中 ⇒ 只传那一张，并把条码带上（服务端据此跳过 vision）────────────
  if (decodedBarcode) {
    const url = await deps.upload(photos[decodedIndex])
    const response = await deps.recognize({ images: [url], barcode: decodedBarcode })
    return {
      response,
      route: 'local-barcode',
      decodedBarcode,
      uploadedCount: 1,
      expectedLlmCalls: 0,
    }
  }

  // ── ③ 解码失败 ⇒ 全量上传 + 不带 barcode ⇒ 服务端 vision 兜底 ───────────────
  const urls: string[] = []
  for (const photo of photos) {
    urls.push(await deps.upload(photo))
  }
  const response = await deps.recognize({ images: urls })
  return {
    response,
    route: 'server-vision',
    decodedBarcode: null,
    uploadedCount: urls.length,
    expectedLlmCalls: 1,
  }
}
