/**
 * 落地页深链（`/b/?code=<短码>` / `/b/?t=<token>`）→ 工人面页面的**消费侧**
 * （issue #5052 实现 PR；`?t=` 支线 = issue #7879；设计 §5.4）
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
 * **参数名 + 形态**，不是靠猜：
 * - 入库标签那一支的参数名是 `code`，值是**裸 8 位短码**（`/i/` 的 302 只放裸短码）；
 * - 报工短链那一支的参数名是 `t`（{@link REPORT_TOKEN_PARAM}），值是**32 位 token**
 *   —— issue #7879 起 `/s/` 与 `/o/` 的 302 也落 `/b/`（`/b/?t=<token>&tenant_id=&tenant_code=`），
 *   但它们**走 `t` 支线**（{@link currentReportToken} → 报工页），与本模块的 `code` 支线**不串道**。
 *
 * 真正携带 `/s/` 语义的形态（整条 URL）走 `classifyScannedCode`，判为洗水码。
 */
import { isH5 } from '../platform'
import { readQueryParam } from '../scanInput'
import { classifyManualCode, classifyScannedCode, type LabelCodeReading } from './codeSpace'
import { REPORT_PAGE_ROUTE, REPRINT_PAGE_ROUTE } from './gaps'

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

/**
 * 从 URL query 串读**某个参数**（`?<name>=X` / `<name>=X`；无 ⇒ `present: false`）。
 *
 * 解析只有一份：`utils/scanInput.ts` 的 `readQueryParam`（issue #7879 起 h5 与小程序的入口
 * 归一都收口到那个模块）—— 这里只做"读哪个参数名"的包装。
 */
function readParam(search: string | null | undefined, name: string): LandingCode {
  const hit = readQueryParam(search, name)
  return hit.present ? { present: true, raw: hit.raw } : ABSENT
}

/**
 * 从 URL query 串读码（`?code=X` / `code=X`；无 ⇒ `present: false`）。
 *
 * 🔴 **自己解析而不是取 `Taro.getCurrentInstance().router.params`**：h5 落地时 URL 是
 * `/b/?code=X`（**search** 段，没有 hash 路由），而 router params 描述的是**当前路由**的 query
 * —— 依赖「Taro 恰好把 search 也并进 params」是把判据挂在实现细节上。这里读的是 URL 本身。
 */
export function landingCodeFromSearch(search?: string | null): LandingCode {
  return readParam(search, LANDING_CODE_PARAM)
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

/**
 * 报工落地页的参数名 —— **与服务端逐字同名**。
 * 真值源 = `backend/admin-api/src/main/java/com/migao/admin/service/WorkerShortLinkService.java`
 * 的 `reportPageLocation`（`REPORT_PAGE_PATH + "?t=" + token + …`）。
 *
 * 为什么 `t` 与 `code` 可以放心并存（issue #7879）：`/i/`（入库标签）302 只放
 * `?code=<裸 8 位短码>`，`/s/` `/o/`（报工短链）只放 `?t=<32 位 token>`
 * ⇒ **参数名与取值形态两两可区分**，不存在"这条 URL 属于哪个码空间"的歧义。
 * 分流只按参数名，**码空间判定与授权判据仍在服务端**（两张表不同，互不命中）。
 */
export const REPORT_TOKEN_PARAM = 't'

/** 从 URL query 串读报工 token（`?t=X` / `t=X`；无 ⇒ `present: false`）。 */
export function reportTokenFromSearch(search?: string | null): LandingCode {
  return readParam(search, REPORT_TOKEN_PARAM)
}

/**
 * **h5 当前 URL** 上的报工 token（启动时读一次）。
 *
 * 与 {@link currentLandingCode} 同形（weapp 恒 `present: false`：小程序没有 URL query，
 * 工人从微信扫一扫进小程序时走的是**页面参数**，不是这条 302），但下游**不同**：
 * 本支去 `REPORT_PAGE_ROUTE`（报工页），`code` 支去补打页 —— 两支**不串道**。
 */
export function currentReportToken(): LandingCode {
  if (!isH5()) return ABSENT
  if (typeof window === 'undefined') return ABSENT
  return reportTokenFromSearch(window.location?.search)
}

/**
 * **有没有落地意图**（`?code=` 或 `?t=` 任一在场）—— 「落地优先」的**唯一判据**。
 *
 * 🔴 issue #7887（2026-10-27 现场）：纯工人设备打开 `/b/?t=<token>` 落在**工人工作台**而不是报工页。
 * 根因不是启动器（`src/app.tsx` 的 302 搬运是对的），而是**商家面守卫**：
 * `utils/roleGuard.ts` 的 `useMerchantSurfaceGuard()` 是一个与首页 `initialize()` **平级**的 effect，
 * 它无条件把"纯工人设备"送回工人工作台 ⇒ 启动器随后发出的 `redirectTo(报工页/补打页)` 被吃掉。
 * 那句"落地优先"的判断此前只写在 chat 页的 `initialize()` 里，守卫看不见它。
 *
 * ⇒ 任何**要抢路由**的守卫/初始化都必须先问这一句：**落地参数在场时，谁都不许改路由**，
 * 由启动器把人送到那一页（报工页 / 补打页）。新增一个守卫却忘了问 ⇒ 现场会重演"扫纸上的码进工人菜单"。
 */
export function hasLandingIntent(): boolean {
  return currentLandingCode().present || currentReportToken().present
}

/**
 * 报工页的落地 URL（**唯一**拼装处：路由与参数名都在这里，启动器与页面不各写一份）。
 *
 * token **原样**带走（32 位十六进制；归一化与撤销判定都在服务端）。
 */
export function reportLandingUrl(token: string): string {
  return `${REPORT_PAGE_ROUTE}?${REPORT_TOKEN_PARAM}=${encodeURIComponent(String(token ?? ''))}`
}
