/**
 * 观星台**两个码空间**的客户端判定 + 手输短码口径（issue #5640 功能②；设计 §7.1）
 *
 * ## 为什么这一层必须存在（而不是在页面里 `split('/').pop()`）
 *
 * 观星台纸面上有两套**语义完全不同**的短码：
 *
 * | 码空间 | 形态 | 承载 | 扫到之后该去哪 |
 * |---|---|---|---|
 * | **入库标签** | `https://app.migaozn.com/i/<短码>` | `inbound_labels`（一张入库标签） | 本页：读单据详情 → 补打 |
 * | **洗水码 / 报工短链** | `https://app.migaozn.com/s/<短码>` | `processing_set_part_tokens`（一个部位） | 报工页（服务端 302 → `/w/?t=<token>`） |
 *
 * 两者**短码规格故意同款**（8 位 Crockford Base32、去 `I/L/O/U`）——「同款」是为了**人可读可抄**，
 * 不是为了**可以互相串**。串了的下场很具体：工人拍一张洗水码 ⇒ 拿它的 8 位短码去查入库详情 ⇒
 * **404** ⇒ 界面说「查无此码」⇒ 工人以为是自己抄错了码，而真相是**走错了门**。
 * 服务端那一侧已有静态守卫（`tests/unit_ci_workflows/test_public_code_spaces_are_disjoint.py`）；
 * 端侧这一半（码是在**手机上**被判定分流的）此前**没有任何判据** ⇒ 本模块就是那一半。
 *
 * ## 🔴 客户端**不归一化**短码（抄错归一化的真值在服务端）
 *
 * 工人抄写必然出错：`0` 抄成 `O`、`1` 抄成 `I/L`。归一化**已经**在服务端实现
 * （`WorkerShortLinkService.normalize`：`O→0`、`I/L→1`，且生成面从不产出这三个字母 ⇒ 不会造出歧义）。
 * ⇒ 本模块只把**抄写分隔符**（空格 / 连字符 / 下划线，工人会写成 `ABCD 2345`）去掉，
 * **其余一律原样交给服务端**（含大小写与 `O/I/L`）。
 * 若在客户端先按「严格字母表」拦一道（`isValidShortCode` 就干这个），抄错的码**永远送不到**服务端
 * ⇒ 工人明明抄对了纸面、系统却说「格式不对」（本单验收判据 5 的红证正是这个形态）。
 * ⚠️ 客户端也**不生成**短码（生成面唯一写方 = 服务端 `allocateUniqueCode()`）。
 *
 * ## 认主机、不认 scheme
 *
 * 纸上的码是 URL，**主机名就是身份**：`app.migaozn.com` 上的 `/i/` 才是观星台的入库标签；
 * 别人域名上的 `/i/<8 位>` 与我们无关（当观星台标签去查 = 拿陌生码打自家接口）。
 * 故 `https://evil.example/i/ABCD2345` ⇒ `foreign`（明确告知「这不是观星台的标签」），
 * scheme 本身（http/https）不参与判定 —— 换 scheme 不改变「这是不是观星台的码」。
 *
 * ## 五个空间的边界（每个都对应一种真实结局，不许合并）
 *
 * - `inbound-label`：**唯一**能去查入库详情的空间；
 * - `wash-code`：洗水码 ⇒ 说清 + 给报工入口（**绝不**当入库标签查）；
 * - `foreign`：不是观星台的码 ⇒ 说清（不猜、不去查）；
 * - `invalid-input`：手输形态不合法（非 8 位字母数字）⇒ 说清 + **一次请求都不发**；
 * - `undecoded`：照片里没解出码（磨花 / 太暗 / 反光）⇒ 提示重拍 + 手输兜底。
 */
import { INBOUND_LABEL_CODE_ORIGIN, INBOUND_LABEL_CODE_PATH } from './truth'

/**
 * 洗水码 / 报工短链的路径前缀。
 * 🔴 真值源 = `backend/admin-api/.../controller/WorkerShortLinkController.java` 的
 * `@GetMapping("/s/{shortCode}")`（守卫 `tests/inbound-reprint-code-space.test.ts` 的 G1 逐值比对
 * ⇒ 后端换前缀而这里没跟 ⇒ 红）。
 */
export const WASH_CODE_PATH = '/s/'

/** 报工页路由（洗水码的唯一去处；`src/app.config.ts` 已登记 —— 进不了报工页的"入口"是空头支票） */
export const REPORT_PAGE_ROUTE = '/pages/production/index/index'

/** 码空间（见文件头「五个空间的边界」） */
export type LabelCodeSpace = 'inbound-label' | 'wash-code' | 'foreign' | 'invalid-input' | 'undecoded'

/** 该空间的动作去处（洗水码 ⇒ 报工页；其余空间没有"下一步按钮"） */
export interface LabelCodeAction {
  label: string
  route: string
}

export interface LabelCodeReading {
  space: LabelCodeSpace
  /** 入库标签的短码（**原样**取自纸面 / URL；归一化在服务端）；非入库空间为 `null` */
  shortCode: string | null
  /** 原始输入（供页面回显与排查） */
  raw: string
  /** 给工人看的一句话（**永远非空**：空提示 = 静默失败） */
  message: string
  action: LabelCodeAction | null
}

/** 洗水码的入口（文案与路由各一处定义，页面不另写一句） */
export const WASH_CODE_ACTION: LabelCodeAction = {
  label: '去「生产报工」扫水洗唛上的码',
  route: REPORT_PAGE_ROUTE,
}

export const WASH_CODE_MESSAGE =
  '这是水洗唛上的报工码（加工单上印的那个码），不是入库标签：它指向报工页，没有入库单据详情可看。请到「生产报工」里扫它报工；要补打入库标签，请拍入库标签或手输标签上的 8 位短码。'

export const FOREIGN_CODE_MESSAGE =
  '这不是观星台的标签：码里既不是入库标签的 /i/，也不是水洗唛报工码的 /s/。请确认拍的是观星台打印的标签（纸面左下角有 8 位短码），或直接手输那 8 位短码。'

export const MANUAL_CODE_INVALID_MESSAGE =
  '短码是纸面上的 8 位字母数字（如 7K3M9QP2）。请核对后重新输入；字母 O / I / L 直接照抄即可，系统会当作 0 / 1 处理。'

export const UNDECODED_CODE_MESSAGE =
  '照片里没解出码（太暗、太糊、反光或拍歪都会这样）。请对着标签正面、光线足一点、离近一点重拍；也可以直接手输纸面上的 8 位短码。'

/** 手输框提示语（页面直接用它，不另写一句） */
export const MANUAL_CODE_PLACEHOLDER = '输入标签上的 8 位短码（如 7K3M9QP2）'

/** 扫码（照片解码）得到入库码时的一句话（解码成功不等于查得到 —— 详情由服务端给） */
export const SCAN_INBOUND_MESSAGE = '已识别到入库标签，正在按短码读取单据详情…'

/** 手输入库码时的一句话 */
export const MANUAL_INBOUND_MESSAGE = '正在按这个短码读取单据详情…'

/** 观星台码主机名（取自 `./truth` 的码形态真值 —— 客户端不另写域名） */
const MIGAO_CODE_HOST = (() => {
  try {
    return new URL(INBOUND_LABEL_CODE_ORIGIN).host.toLowerCase()
  } catch {
    return ''
  }
})()

/** 抄写分隔符（工人会把 `ABCD2345` 写成 `ABCD 2345` / `ABCD-2345`）：去掉它们，**其余原样** */
const WRITTEN_SEPARATORS = /[\s\-_·．.]+/g

function makeReading(
  space: LabelCodeSpace,
  shortCode: string | null,
  raw: string,
  message: string,
  action: LabelCodeAction | null = null,
): LabelCodeReading {
  return { space, shortCode, raw, message, action }
}

/** 从一段文本里读「主机 + 路径」；读不出来（纯短码 / 纯文本）⇒ 两者都为空 */
function splitHostAndPath(text: string): { host: string | null; path: string } {
  const value = text.trim()
  if (!value) return { host: null, path: '' }
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) {
    try {
      const url = new URL(value)
      return { host: url.host.toLowerCase(), path: url.pathname }
    } catch {
      return { host: null, path: '' }
    }
  }
  const slash = value.indexOf('/')
  if (slash < 0) return { host: null, path: '' }
  const head = value.slice(0, slash)
  const path = value.slice(slash).split(/[?#]/)[0]
  // `app.migaozn.com/i/XXXX` 这类**没写 scheme** 的形态也认（扫码器/聊天记录里常见）
  return { host: /^[\w.-]+\.[a-z]{2,}$/i.test(head) ? head.toLowerCase() : null, path }
}

/** 路径是否落在某个码空间前缀下；命中 ⇒ 返回紧随其后的那一段（到下一个 `/` 为止） */
function segmentUnder(path: string, prefix: string): string | null {
  if (!path.toLowerCase().startsWith(prefix)) return null
  const segment = path.slice(prefix.length).split('/')[0].trim()
  return segment || null
}

/** 主机是不是观星台（`null` = 只有路径的形态，如工人粘 `/i/<码>` ⇒ 认） */
function isMigaoHost(host: string | null): boolean {
  if (!host) return true
  return host === MIGAO_CODE_HOST
}

/** URL 形态 ⇒ 落在哪个码空间（既非 `/i/` 也非 `/s/`、或别的域名 ⇒ 两个都 `null`） */
function readSpaceFromUrl(text: string): { space: 'inbound-label' | 'wash-code'; shortCode: string } | null {
  const { host, path } = splitHostAndPath(text)
  if (!isMigaoHost(host)) return null
  const inbound = segmentUnder(path, INBOUND_LABEL_CODE_PATH)
  if (inbound) return { space: 'inbound-label', shortCode: inbound }
  const wash = segmentUnder(path, WASH_CODE_PATH)
  if (wash) return { space: 'wash-code', shortCode: wash }
  return null
}

/**
 * 判定**扫到的**（照片解码出来的）码。
 *
 * 🔴 扫到的一律是 **URL**（码就印成 URL，设计 §7.1）⇒ 不认识「裸短码」形态：
 * 一个既不是 `/i/` 也不是 `/s/` 的二维码 ⇒ `foreign`（明确告知），而不是拿它去碰运气查入库详情。
 * 解码结果为空（磨花 / 没拍清）⇒ `undecoded`（提示重拍 + 手输）。
 */
export function classifyScannedCode(raw: string | null | undefined): LabelCodeReading {
  const text = String(raw ?? '').trim()
  if (!text) return makeReading('undecoded', null, '', UNDECODED_CODE_MESSAGE)
  const hit = readSpaceFromUrl(text)
  if (hit?.space === 'inbound-label') return makeReading('inbound-label', hit.shortCode, text, SCAN_INBOUND_MESSAGE)
  if (hit?.space === 'wash-code') return makeReading('wash-code', hit.shortCode, text, WASH_CODE_MESSAGE, WASH_CODE_ACTION)
  return makeReading('foreign', null, text, FOREIGN_CODE_MESSAGE)
}

/**
 * 判定**手输**的短码（补打的主场景：标签磨花 / 破损 ⇒ 码根本没得扫）。
 *
 * 三条路，缺一不可：
 * ① 整条 URL 粘进来（工人从聊天记录 / 扫码器历史里复制）⇒ 按 URL 判空间；
 * ② 裸短码 8 位字母数字 ⇒ `inbound-label`，**原样**交给服务端归一化（含 `O/I/L` 抄错形态）；
 * ③ 其余 ⇒ `invalid-input`：说清「8 位」并**一次请求都不发**（发出去只会白等一次 404，
 *    而且 404 的文案会把「抄错」与「不存在」混在一起 —— 撤销那件事已经够容易混了）。
 */
export function classifyManualCode(raw: string | null | undefined): LabelCodeReading {
  const text = String(raw ?? '').trim()
  if (!text) return makeReading('invalid-input', null, '', MANUAL_CODE_INVALID_MESSAGE)
  const hit = readSpaceFromUrl(text)
  if (hit?.space === 'inbound-label') return makeReading('inbound-label', hit.shortCode, text, MANUAL_INBOUND_MESSAGE)
  if (hit?.space === 'wash-code') return makeReading('wash-code', hit.shortCode, text, WASH_CODE_MESSAGE, WASH_CODE_ACTION)
  const code = text.replace(WRITTEN_SEPARATORS, '')
  if (/^[0-9A-Za-z]{8}$/.test(code)) return makeReading('inbound-label', code, text, MANUAL_INBOUND_MESSAGE)
  return makeReading('invalid-input', null, text, MANUAL_CODE_INVALID_MESSAGE)
}
