/**
 * 拍照**补打入库标签**的主链（issue #5640 功能②；设计 §6.1 / §7.1 / §7.3）
 *
 * 与 P3 的 `./recognizeFlow` **同族**，但这一条链只有一半：**解码优先且没有 vision 兜底**。
 *
 * ## 为什么补打链里不该有「问模型」这一支
 *
 * 补打的对象是**米高自己打印的入库标签**（纸上有 QR）、或者工人手里的**8 位人可读短码**：
 * 两者都是确定性的标识符 ⇒ 解不出码时**正确答案是「让工人重拍 / 手输」**，
 * 不是「让模型猜这是哪张单」。识别模型给一个**像模像样但错**的单号，工人照着打出来一张错标签，
 * 而纸面与服务端**都不会报错** —— 这正是本仓反复点名的形态。
 * ⇒ 本模块的依赖里**没有**上传 / 识别回调，`expectedLlmCalls` 恒为 0（结构事实，不是纪律）。
 *
 * ## 🔴 码空间门禁写在这里，不写在页面里
 *
 * 「`/s/` 洗水码绝不许拿去查入库详情」如果只写在页面的 `onClick` 里，下一个人加一条"重试"分支
 * 就会绕过去，而**没有任何东西会变红**。故**唯一**能发起详情查询的函数就是
 * {@link loadReprintDetail}：它第一件事就是判 `space !== 'inbound-label'` ⇒ 非入库码**一次请求都不发**。
 * 判据（`tests/inbound-reprint-flow.test.ts` 的 F2/F3 + 页面判据 P4）用**假服务端计数**钉住这一点。
 *
 * ## 404 / 410 必须分开（撤销是业务动作，不存在可能是抄错码）
 *
 * 两者在服务端就是两个状态码（`InboundLabelService.requirePrintableLabel`：跨租户/不存在 ⇒ **404**、
 * 已撤销 ⇒ **410**），处置也完全不同：**404 ⇒ 回去核对纸面**（可能是抄错一位）、
 * **410 ⇒ 这张纸作废了，要让文员按单据重新补打**（核对再多次也没用）。
 * 合成一句「标签有问题」= 把两种处境压成一句不可行动的话 ⇒ 判据 F5 明令两句话**不相等**。
 */
import type { InboundResponse } from '../../services/workerInboundService'
import type { DecodeOutcome, PendingPhoto } from './barcodeDecode'
import { classifyScannedCode, type LabelCodeAction, type LabelCodeReading, type LabelCodeSpace } from './codeSpace'
import type { InboundLabelView } from './labelLayout'

/** 解不出码时给工人的话（重拍要点 + 手输兜底 —— 补打的主场景就是码磨花了） */
export const REPRINT_RESHOOT_HINT =
  '照片里没解出码（太暗 / 太糊 / 反光 / 拍歪都可能）：请对着标签正面、光线足一点、离近一点重拍，或直接手输纸面上的 8 位短码。'

/** 404：码对不上任何一张标签（多半是抄错一位）⇒ 处置是**回去核对** */
export const REPRINT_NOT_FOUND_MESSAGE =
  '查无此码：系统里没有这个短码对应的入库标签。请核对纸面上的 8 位短码是否抄全（字母 O/I/L 会被当作 0/1 处理）；确认没抄错的话，请让文员在电脑端查这张单。'

/** 410：这张纸被撤销了（码是对的）⇒ 处置是**重新补打**，核对再多次也没用 */
export const REPRINT_REVOKED_MESSAGE =
  '该标签已撤销：这个短码对应的标签已被作废（不是抄错码 —— 码是对的，但纸已失效）。旧码不再可用、也不会回落到别的标签；请让文员按单据重新补打一张新标签。'

/** 网络 / 服务端其它故障（既不是"没有这个码"也不是"已撤销" ⇒ 不许冒充那两种） */
export const REPRINT_DETAIL_ERROR_MESSAGE =
  '读取单据详情失败（网络问题或服务端暂时不可用）。请重试；若反复失败，请把纸面上的 8 位短码报给文员在电脑端处理。'

/**
 * 「谁可以查入库详情」的**登记表**（类级守卫 `tests/inbound-reprint-code-space.test.ts` 的 G2 逐值核验）。
 *
 * 这一条治的是一类真实缺陷：**新增一处调用点绕过码空间门禁**（比如某个"顺手重查一下"的分支）——
 * 静态上没有任何东西会红，直到工人拍了一张洗水码。
 *
 * 🔴 登记粒度 = **调用点**（`文件` + `所在函数` + `该函数里的出现次数`），不是文件集合。
 * 历史缺陷（issue #5052 验收 D7-②）：旧口径只比对**文件集合** ⇒ 在**已登记**的
 * `src/pages/worker/reprint/index.tsx` 里新加一处不经 `loadReprintDetail` 的 `getInboundLabel(...)`
 * 仍然全绿 —— 而本表的注释宣称的是"调用点级"。⇒ 现在计数也进台账：多一处未登记即红。
 *
 * `gatedByCodeSpace: true` 的条目，其**所在函数**（不是整个文件）必须引用码空间判定
 * （`loadReprintDetail` 或 `classify*Code`）——文件级引用不算：那正是"同一文件里旁路恒绿"的成因。
 */
export const LABEL_DETAIL_CALLERS: {
  file: string
  /** 调用点所在的函数名（判据按「文件 + 函数」定位，见 `tests/helpers/inboundCallSites.ts`） */
  in: string
  /** 该函数里 `getInboundLabel(` 的**出现次数**（多一处 / 少一处都红） */
  calls: number
  why: string
  gatedByCodeSpace: boolean
}[] = [
  {
    file: 'src/services/workerInboundService.ts',
    in: 'getInboundLabel',
    calls: 1,
    why: '端点唯一封装（`INBOUND_ENDPOINTS.labelDetail`）：函数自己就是 HTTP 面，不做码空间判定（判定在调用方）',
    gatedByCodeSpace: false,
  },
  {
    file: 'src/pages/worker/inbound/index.tsx',
    in: 'onSubmit',
    calls: 1,
    why: 'P3 过账回执带回的 `shortCode`（不是扫来的码）⇒ 回读详情出标签，与码空间无关',
    gatedByCodeSpace: false,
  },
  {
    file: 'src/pages/worker/inbound/index.tsx',
    in: 'onPrint',
    calls: 1,
    why: '打印成功后刷新标签详情（短码取自已过账的回执，不经用户输入）',
    gatedByCodeSpace: false,
  },
  {
    file: 'src/pages/worker/reprint/index.tsx',
    in: 'lookup',
    calls: 1,
    why: '补打的详情查询：每一次 lookup 都经 `loadReprintDetail` 的码空间门禁（`/s/` 与陌生码在这里就停）',
    gatedByCodeSpace: true,
  },
  {
    file: 'src/pages/worker/reprint/index.tsx',
    in: 'onPrint',
    calls: 1,
    why: '打印成功后刷新标签详情（短码取自**已过门禁**的 reading，不再经用户输入）',
    gatedByCodeSpace: false,
  },
]

/** 端侧走了哪条路（`manual-required` = 没解出码 ⇒ 页面必须给手输入口，**不猜单**） */
export type ReprintRoute = 'local-decode' | 'manual-required'

export interface ReprintResolveDeps {
  /** 待解码的那一张照片（补打只需要拍标签本身） */
  photo: PendingPhoto
  /** 本机解码（0 次 LLM）—— `decodeBarcodeFromPhoto` 或测试替身 */
  decode: (photo: PendingPhoto) => Promise<DecodeOutcome>
}

export interface ReprintResolveResult {
  /** 码空间判定（只有 `inbound-label` 谈得上查详情） */
  reading: LabelCodeReading
  /** 解码过程要对工人说的话（非空即必须上屏，**不许静默**） */
  notices: string[]
  route: ReprintRoute
  /** 端侧**期望**的 LLM 调用次数：本链恒为 0（结构事实：依赖里没有 vision 这一支） */
  expectedLlmCalls: 0
}

/**
 * 跑一次「照片 → 短码」。
 *
 * @throws 由 `decode` 抛出的异常（页面负责上屏；本函数不吞）
 */
export async function runReprintResolve(deps: ReprintResolveDeps): Promise<ReprintResolveResult> {
  const outcome = await deps.decode(deps.photo)
  const notices: string[] = []
  if (outcome.hint) notices.push(outcome.hint)

  if (!outcome.text) {
    // 🔴 解不出码 ⇒ 手输（不猜单、不预填、不问模型）
    notices.push(REPRINT_RESHOOT_HINT)
    return {
      reading: classifyScannedCode(''),
      notices,
      route: 'manual-required',
      expectedLlmCalls: 0,
    }
  }
  return {
    reading: classifyScannedCode(outcome.text),
    notices,
    route: 'local-decode',
    expectedLlmCalls: 0,
  }
}

/**
 * 详情读取的**终态**（页面按 kind 渲染 —— 每一类都有自己的文案与出路，不许合并）。
 */
export type ReprintDetailState =
  | { kind: 'ready'; view: InboundLabelView }
  | { kind: 'blocked'; space: LabelCodeSpace; message: string; action: LabelCodeAction | null }
  | { kind: 'not-found'; message: string }
  | { kind: 'revoked'; message: string }
  | { kind: 'error'; message: string }

function joinHint(base: string, extra?: string | null): string {
  const tail = String(extra ?? '').trim()
  return tail ? `${base} ${tail}` : base
}

/**
 * 按**码空间判定结果**取详情（本单唯一的详情入口）。
 *
 * 🔴 顺序是硬的：**先判空间，再发请求** —— 非 `inbound-label`（洗水码 / 陌生码 / 形态不合法 /
 * 没解出码）⇒ 直接 `blocked`，`lookup` **一次都不调用**（判据 F2/F3 用替身计数钉住）。
 */
export async function loadReprintDetail(deps: {
  reading: LabelCodeReading
  lookup: (shortCode: string) => Promise<InboundResponse<InboundLabelView>>
}): Promise<ReprintDetailState> {
  const reading = deps.reading
  if (reading.space !== 'inbound-label' || !reading.shortCode) {
    return { kind: 'blocked', space: reading.space, message: reading.message, action: reading.action }
  }

  const res = await deps.lookup(reading.shortCode)
  if (res.success && res.data) return { kind: 'ready', view: res.data }

  // 410 先判：撤销与 404 是两个不同的世界（错误码比状态码更权威 —— 两者任意一个命中都算）
  if (res.statusCode === 410 || res.code === 'LABEL_REVOKED') {
    return { kind: 'revoked', message: joinHint(REPRINT_REVOKED_MESSAGE, res.suggestion) }
  }
  if (res.statusCode === 404 || res.code === 'NOT_FOUND') {
    return { kind: 'not-found', message: joinHint(REPRINT_NOT_FOUND_MESSAGE, res.suggestion) }
  }
  // 200 但无 data 也走这里（**不**当 ready：空详情 = 一张假标签）
  return { kind: 'error', message: joinHint(REPRINT_DETAIL_ERROR_MESSAGE, res.message) }
}
