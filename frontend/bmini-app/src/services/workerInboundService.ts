/**
 * 工人**拍照入库**服务（issue #5052 P3）—— 全部端点都在 `/api/worker/inbound/**`，**零商家权限码**
 *
 * ## 端点字面量的真值在服务端（不是"照语义推测"）
 *
 * 六个端点与幂等头名逐字来自后端控制器（`WorkerInboundController` / `WorkerInboundLabelController`
 * / `WorkerInboundUploadController`）；守卫
 * `frontend/bmini-app/tests/inbound-api-contract.test.ts` 直接解析那三个 Java 源**逐值比对**
 * （端点多一个 / 少一个 / 拼错一个 ⇒ 红）。本仓有过「契约里的技术字面量凭语义推测」的实证
 * （`migao-dev-flow` §17.3）：写错的端点名在端侧**永远 404**，而类型检查与单测都不会报。
 *
 * ## 身份
 *
 * 一律 `workerSessionHeaders()`（`X-Worker-Session-Id`）。**请求体里没有** `worker_id` /
 * `operator` / `tenantId`（服务端 DTO 里根本没这些键）—— 身份真值只在服务端。
 *
 * ## 不新造
 *
 * 过账走既有 `POST /api/worker/inbound/drafts/{id}/post`（P1，内部复用
 * `InboundOrderService.post`）；标签读面/打印留痕走 P2。本文件**没有**任何建商品 / 建 SKU /
 * 改库存的调用（"零命中不自动建品"在端侧是结构事实）。
 */
import Taro from '@tarojs/taro'
import { get, post } from '../utils/request'
import { API_BASE_URL } from '../utils/constants'
import { workerSessionHeaders } from '../utils/workerSession'
import type { RecognizeLike, SkuMatch } from '../utils/inbound/recognizeGate'
import type { InboundLabelView } from '../utils/inbound/labelLayout'

/**
 * 端点字面量（守卫按后端 Java 逐值核验；占位符用服务端的写法 `{id}` / `{shortCode}`）。
 */
export const INBOUND_ENDPOINTS = {
  upload: '/api/worker/inbound/upload',
  recognize: '/api/worker/inbound/recognize',
  drafts: '/api/worker/inbound/drafts',
  draftPost: '/api/worker/inbound/drafts/{id}/post',
  labelDetail: '/api/worker/inbound/labels/{shortCode}',
  labelPrint: '/api/worker/inbound/labels/{shortCode}/print',
} as const

/**
 * 幂等键请求头 —— 逐字等于 `WorkerInboundController.IDEMPOTENCY_HEADER`。
 * ⚠️ 与报工那条链的 `X-Client-Request-Id` **不是同一个头**：入库端点读的是 `Idempotency-Key`
 * （设计 §5.2 逐字），写错 ⇒ 幂等**静默失效**（重复提交会真的入两次库，而两次都返回 200）。
 */
export const INBOUND_IDEMPOTENCY_HEADER = 'Idempotency-Key'

let requestSeq = 0

/** 生成一次入库动作的幂等键（重试沿用原键；前缀 `inbound-` 便于在服务端台账里一眼看出调用来源） */
export function newInboundRequestId(): string {
  requestSeq += 1
  const nativeUuid = (globalThis as any)?.crypto?.randomUUID
  const suffix =
    typeof nativeUuid === 'function'
      ? nativeUuid.call((globalThis as any).crypto)
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
  return `inbound-${suffix}-${requestSeq}`
}

/** 统一响应（沿用 bmini 既有形状：`success` + `data` + `message`，见 `productionService`） */
export interface InboundResponse<T> {
  success: boolean
  data?: T
  message: string
  /** 传输层失败（断网/超时）—— 有 HTTP 状态码 = 服务端已答复 */
  offline?: boolean
  /**
   * HTTP 状态码（issue #5640）：**404 与 410 是两件事** ——
   * 「查无此码」（可能是抄错）与「该标签已撤销」（码是对的、纸已失效）的处置完全不同，
   * 而它们**只**能从状态码/错误码上分辨 ⇒ 不带上它，端侧就只能把两种处境压成一句"标签有问题"。
   */
  statusCode?: number
  /** 服务端错误码（`NOT_FOUND` / `LABEL_REVOKED` …；比状态码更权威的那一半） */
  code?: string
  /** 服务端给的可行动建议（`ApiResponse.suggestion`）—— 原样上屏，端侧不另写一份 */
  suggestion?: string
}

/** 上传回执（`UploadedFileInfo`） */
export interface UploadedFileInfo {
  id?: string
  url: string
  name?: string
  size?: number
  type?: string
}

/** 草稿 / 过账回执（`WorkerInboundDraftView`） */
export interface InboundDraftView {
  draftId: string
  inboundNo: string
  status: string
  source?: string
  needsConfirmation?: boolean
  replayed?: boolean
  items?: {
    /** 雪花号 id：后端出参是**字符串**（> 2^53，JSON number 会丢精度，issue #6340） */
    skuId?: string
    skuCode?: string | null
    quantity?: number | string | null
    batchNo?: string | null
    /** 过账后每行一个短码（草稿态为 null）—— P3 用它出 30×40mm 标签 */
    shortCode?: string | null
    printCount?: number | null
  }[]
}

export type { InboundLabelView, RecognizeLike, SkuMatch }

/** 建草稿请求（**结构上没有任何"任意调整"字段**：无 `adjustment` / `delta` / `setStock` / `operator`） */
export interface InboundDraftRequest {
  productId: string
  /** 雪花号 id：**原样字符串**透传，禁止 Number()/parseInt()（后端出参形态，issue #6340） */
  skuId: string
  quantity: string | number
  unitCost?: string | number | null
  dyeLot?: string | null
  supplier?: string | null
  supplierDocNo?: string | null
  warehouse?: string | null
  rollLengthM?: string | number | null
  remark?: string | null
}

/** 归一化后端响应（HTTP 200 但 `success=false` 的业务拒绝也要把文案透出到页面） */
function toResponse<T>(res: any, fallback: string): InboundResponse<T> {
  const message = res?.message || res?.error?.message || fallback
  return {
    success: !!res?.success && res?.data !== undefined,
    data: res?.data,
    message,
    code: res?.error?.code,
    suggestion: res?.suggestion,
  }
}

function failure<T>(error: any, fallback: string): InboundResponse<T> {
  return {
    success: false,
    message: error?.data?.error?.message || error?.data?.message || error?.message || fallback,
    offline: !error?.statusCode,
    statusCode: error?.statusCode,
    code: error?.data?.error?.code,
    suggestion: error?.data?.suggestion,
  }
}

/**
 * 上传**一张**照片（`multipart`，字段名 `files`；服务端要求每次 1~3 张）。
 *
 * 为什么逐张传：`Taro.uploadFile` 一次只装一个文件（两端实现同此），而多张时我们本来也只需要
 * 「解出码的那一张」或「最多 3 张」——逐张传让「传几张」这件事在上层**可数、可判据化**。
 */
export async function uploadInboundPhoto(filePath: string): Promise<InboundResponse<UploadedFileInfo>> {
  try {
    const res: any = await Taro.uploadFile({
      url: `${API_BASE_URL}${INBOUND_ENDPOINTS.upload}`,
      filePath,
      name: 'files',
      header: workerSessionHeaders(),
    })
    let body: any = res?.data
    if (typeof body === 'string') {
      try {
        body = JSON.parse(body)
      } catch {
        return { success: false, message: '上传返回的不是 JSON，请重试' }
      }
    }
    return toResponse<UploadedFileInfo>(body, '照片上传失败，请重试')
  } catch (error: any) {
    return failure<UploadedFileInfo>(error, '照片上传失败，请重试')
  }
}

/**
 * 识别候选（**不落库、不动库存**）。
 *
 * 🔴 `barcode` 非空 ⇒ 服务端走解码优先路径、**零 LLM 调用**（设计 §6.1 的成本守卫）。
 */
export async function recognizeInbound(payload: {
  images: string[]
  barcode?: string | null
}): Promise<InboundResponse<RecognizeLike>> {
  try {
    const body: Record<string, unknown> = { images: payload.images }
    if (payload.barcode) body.barcode = payload.barcode
    const res = await post<any>(INBOUND_ENDPOINTS.recognize, body, {
      baseURL: API_BASE_URL,
      headers: workerSessionHeaders(),
    })
    return toResponse<RecognizeLike>(res, '识别失败，请重试或手工录入')
  } catch (error: any) {
    return failure<RecognizeLike>(error, '识别失败，请重试或手工录入')
  }
}

/** 建入库单草稿（**不动库存**；带幂等键：手机重试不会建出两张单） */
export async function createInboundDraft(
  payload: InboundDraftRequest,
  requestId?: string,
): Promise<InboundResponse<InboundDraftView>> {
  try {
    const res = await post<any>(INBOUND_ENDPOINTS.drafts, payload, {
      baseURL: API_BASE_URL,
      headers: { [INBOUND_IDEMPOTENCY_HEADER]: requestId || newInboundRequestId(), ...workerSessionHeaders() },
    })
    return toResponse<InboundDraftView>(res, '建单失败，请重试')
  } catch (error: any) {
    return failure<InboundDraftView>(error, '建单失败，请重试')
  }
}

/**
 * 提交过账（**过账才动库存**；不可逆）。
 *
 * 🔴 `confirmed: true` 是服务端要求的**人工确认标记**（缺它 ⇒ 409）。这个字段**不是装饰**：
 * §6.5「不做免确认」靠它区分「工人确认过」与「跳过确认的提交」。
 */
export async function postInboundDraft(
  draftId: string,
  requestId?: string,
): Promise<InboundResponse<InboundDraftView>> {
  try {
    const url = INBOUND_ENDPOINTS.draftPost.replace('{id}', encodeURIComponent(draftId))
    const res = await post<any>(
      url,
      { confirmed: true },
      {
        baseURL: API_BASE_URL,
        headers: {
          [INBOUND_IDEMPOTENCY_HEADER]: requestId || newInboundRequestId(),
          ...workerSessionHeaders(),
        },
      },
    )
    return toResponse<InboundDraftView>(res, '过账失败，请重试')
  } catch (error: any) {
    return failure<InboundDraftView>(error, '过账失败，请重试')
  }
}

/** 按短码读标签详情（30×40mm 渲染所需的全部业务字段；跨租户 404 / 已撤销 410） */
export async function getInboundLabel(shortCode: string): Promise<InboundResponse<InboundLabelView>> {
  try {
    const url = INBOUND_ENDPOINTS.labelDetail.replace('{shortCode}', encodeURIComponent(shortCode))
    const res = await get<any>(url, { baseURL: API_BASE_URL, headers: workerSessionHeaders() })
    return toResponse<InboundLabelView>(res, '读标签详情失败，请重试')
  } catch (error: any) {
    return failure<InboundLabelView>(error, '读标签详情失败，请重试')
  }
}

/**
 * **打印留痕**（`print_count` 原子自增 + `audit_logs`）—— 设备侧打印**前**必调。
 *
 * 返回值里的 `printCount` 是**服务端读数**（第几次）：前端**原样展示**，不本地计数。
 */
export async function recordInboundLabelPrint(
  shortCode: string,
): Promise<InboundResponse<{ shortCode: string; printCount: number }>> {
  try {
    const url = INBOUND_ENDPOINTS.labelPrint.replace('{shortCode}', encodeURIComponent(shortCode))
    const res = await post<any>(url, {}, { baseURL: API_BASE_URL, headers: workerSessionHeaders() })
    return toResponse<{ shortCode: string; printCount: number }>(res, '打印留痕失败，请重试')
  } catch (error: any) {
    return failure<{ shortCode: string; printCount: number }>(error, '打印留痕失败，请重试')
  }
}

export default {
  INBOUND_ENDPOINTS,
  INBOUND_IDEMPOTENCY_HEADER,
  newInboundRequestId,
  uploadInboundPhoto,
  recognizeInbound,
  createInboundDraft,
  postInboundDraft,
  getInboundLabel,
  recordInboundLabelPrint,
}
