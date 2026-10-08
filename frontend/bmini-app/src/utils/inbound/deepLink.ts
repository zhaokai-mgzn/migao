/**
 * 落地页深链（`/b/?code=<短码>`）→ 工人面页面的**消费侧**（issue #5052 实现 PR；设计 §5.4）
 *
 * ## 这一层治的形态：「服务端 302 了，而**没有任何人读那个参数**」
 *
 * 纸上的码 = `https://app.migaozn.com/i/<短码>`（设计 §7.1 一次定死），服务端
 * `InboundLabelShortLinkController` 302 到 `/b/?code=<短码>&tenant_id=…`
 * （`InboundLabelService.landingLocation`）。**实测（修复前）**：全仓
 * `params.code` / `query.code` / `searchParams` **零命中** ⇒ 工人扫了自家标签，
 * 落到商家首页，**而且没有任何东西会变红**（码是好的、302 是好的、页面也没报错）。
 * 本模块就是那一半：把 `code` 读出来、**按码空间分流**、失败方向显式（不许静默当没有参数）。
 *
 * ## 两侧都要给得出路径（`?code=` 只存在于 h5）
 *
 * | 侧 | 码从哪来 | 谁读 |
 * |---|---|---|
 * | **h5**（唯一上线形态，用户 2026-09-26 裁定） | URL query（服务端 302 的 Landing URL） | {@link currentLandingCode} —— **h5 专有**，weapp 没有 URL query |
 * | **小程序** | **页面参数**（`navigateTo` 带参 / 页面路径 query） | {@link landingCodeFromParams}（= `Taro.getCurrentInstance().router.params`） |
 *
 * 两侧都落在**同一个下游**：`REPRINT_PAGE_ROUTE` + `?code=<原样>`（{@link reprintLandingUrl}）
 * ⇒ 小程序侧的路径不是"缺口"，它与 h5 共用 {@link landingCodeFromParams} 那一半。
 *
 * ## 判定**复用** `codeSpace.ts`，不新造口径
 *
 * 落地页 `code` 的**唯一生产者**是服务端 `/i/` 的 302，而它放的是**裸短码**（已归一化）
 * ⇒ 裸 8 位按「手输」口径判（= 入库标签，且短码**原样**交给服务端）；其余一律按「扫到」口径判
 * —— 洗水码 URL（`/s/<短码>`）**就在这里被分流**，绝不会被当成入库标签去查详情
 * （`loadReprintDetail` 的码空间门禁是下半场）。别域名 / 纯文本 ⇒ 「这不是观星台的标签」。
 *
 * ⚠️ **边界（不要把本模块读成覆盖面更大的东西）**：裸 8 位码**形态上无法区分** `/i/` 与 `/s/`
 * （两套短码规格故意同款，见 `codeSpace.ts` 文件头）。这里按「入库标签」判，依据是
 * **生产者唯一**（`/i/` 的 302 只放裸短码；`/s/` 的 302 目标是 `/w/?t=`，从不到 `/b/`）
 * —— 不是靠形态猜。真正携带 `/s/` 语义的形态（整条 URL）走 `classifyScannedCode`，判为洗水码。
 */
import { isH5 } from '../platform'
import { classifyManualCode, classifyScannedCode, type LabelCodeReading } from './codeSpace'
import { REPRINT_PAGE_ROUTE } from './gaps'

/**
 * 落地页的参数名 —— **与服务端逐字同名**。
 * 真值源 = `backend/admin-api/src/main/java/com/migao/admin/service/InboundLabelService.java`
 * 的 `LANDING_CODE_PARAM`（守卫 `tests/page-entry-reachability.test.ts` 的 L1 逐值比对
 * ⇒ 后端改参数名而这里没跟 ⇒ 红）。
 */
export const LANDING_CODE_PARAM = 'code'

/**
 * 读到的「码」——**读不到** 与 **读到空值** 是两件事，不许合并。
 *
 * `present: true` + `raw: ''`（如 `/b/?code=`）必须出**明确提示**：静默当"没有参数"
 * 就是本单要治的那个形态（工人扫了码，停在首页，没有任何东西变红）。
 */
export interface LandingCode {
  /** URL / 页面参数里**出现了**这个键 */
  present: boolean
  /** 原样值（URL 解码后）；未出现时为 `''` */
  raw: string
}

const ABSENT: LandingCode = { present: false, raw: '' }

/** `decodeURIComponent` 遇到非法百分号编码会抛 —— 抛出去会把"读参数"变成白屏，故退回原样 */
function decodeLoose(value: string): string {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

/**
 * 从 URL query 串读码（`?code=X` / `code=X`；无 ⇒ `present: false`）。
 *
 * 🔴 **自己解析而不是取 `Taro.getCurrentInstance().router.params`**：h5 落地时 URL 是
 * `/b/?code=X`（**search** 段，没有 hash 路由），而 router params 描述的是**当前路由**的 query
 * —— 依赖「Taro 恰好把 search 也并进 params」是把判据挂在实现细节上。这里读的是 URL 本身。
 */
export function landingCodeFromSearch(search?: string | null): LandingCode {
  const text = String(search ?? '').replace(/^\?/, '')
  if (!text) return ABSENT
  for (const pair of text.split('&')) {
    if (!pair) continue
    const eq = pair.indexOf('=')
    const key = decodeLoose(eq < 0 ? pair : pair.slice(0, eq))
    if (key !== LANDING_CODE_PARAM) continue
    const value = eq < 0 ? '' : pair.slice(eq + 1)
    // `+` 在 query 里代表空格（工人从聊天记录里粘 URL 时会出现）：只做这一处还原，
    // 其余**原样**交给服务端（短码归一化在服务端，见 `codeSpace.ts` 文件头）
    return { present: true, raw: decodeLoose(value).replace(/\+/g, ' ') }
  }
  return ABSENT
}

/**
 * 从**页面参数**读码（`Taro.getCurrentInstance().router.params`）—— h5 路由 query 与
 * **小程序页面参数**共用这一侧（小程序深链的形态就是页面参数）。
 */
export function landingCodeFromParams(params?: Record<string, any> | null): LandingCode {
  if (!params) return ABSENT
  for (const key of Object.keys(params)) {
    if (key !== LANDING_CODE_PARAM) continue
    const value = params[key]
    if (value === undefined) return ABSENT
    return { present: true, raw: value === null ? '' : String(value) }
  }
  return ABSENT
}

/**
 * **h5 当前 URL** 上的落地码（启动时读一次）。
 *
 * weapp 恒 `present: false` —— 小程序没有 URL query，深链走页面参数
 * （{@link landingCodeFromParams}）。这条平台边界**显式登记**在
 * `src/utils/inbound/gaps.ts` 的 `WORKER_SURFACE_PLATFORM_GAPS` 里（照 gaps.ts 既有范式：
 * 缺口必须有登记，且由真的调用它的文件接线）。
 */
export function currentLandingCode(): LandingCode {
  if (!isH5()) return ABSENT
  if (typeof window === 'undefined') return ABSENT
  return landingCodeFromSearch(window.location?.search)
}

/**
 * 码原文 ⇒ 码空间（**复用** `codeSpace.ts` 的既有判定，不新造第五套口径）。
 *
 * 三条路：① 空 ⇒ 手输口径的 `invalid-input`（明确提示"8 位"，**不是** `undecoded` —— 没人在拍照）；
 * ② 裸 8 位（含抄写分隔符）⇒ 手输口径的 `inbound-label`（服务端 302 的唯一形态）；
 * ③ 其余 ⇒ 扫到口径（`/i/` 入库 · `/s/` 洗水码 · 别域名/纯文本 ⇒ `foreign`）。
 */
export function classifyLandingCode(raw?: string | null): LabelCodeReading {
  const text = String(raw ?? '').trim()
  if (!text) return classifyManualCode(text)
  const manual = classifyManualCode(text)
  if (manual.space === 'inbound-label') return manual
  return classifyScannedCode(text)
}

/**
 * 补打页的落地 URL（**唯一**拼装处：路由与参数名都在这里，启动器与页面不各写一份）。
 *
 * 码**原样**带走（不归一化、不截断）：归一化在服务端（`WorkerShortLinkService.normalize`）。
 */
export function reprintLandingUrl(raw: string): string {
  return `${REPRINT_PAGE_ROUTE}?${LANDING_CODE_PARAM}=${encodeURIComponent(String(raw ?? ''))}`
}
