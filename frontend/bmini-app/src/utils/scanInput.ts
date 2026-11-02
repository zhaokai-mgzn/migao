/**
 * **扫码/落地入口的唯一解析**（issue #7879）—— h5 与小程序**共用同一份**，谁都不许再写第二份。
 *
 * ## 它治什么
 *
 * 纸上的码有**四种到达方式**，而改前它们各走一条路（甚至没有路）：
 *
 * | 到达方式 | 形态 | 谁给 |
 * |---|---|---|
 * | h5 落地（本包主路径） | `/b/?t=<token>&tenant_id=&tenant_code=` | 服务端 `/s/` `/o/` 的 **302**（`?code=` 那支走补打页） |
 * | 小程序内扫一扫 | `Taro.scanCode` 的 `result`：整条 URL（含 `/s/<短码>`）或裸短码 | 工人点「扫一扫」 |
 * | 小程序码（B 档，本期不生成） | `Taro.getEnterOptionsSync().query.scene`（≤32 字符，装 8 位短码，需 `decodeURIComponent`） | 微信 |
 * | 扫普通链接二维码进小程序（A 档，等后台规则） | `query.q` = **URL-encoded 的完整链接**（里面是 `/s/<短码>`） | 微信 |
 *
 * 页面参数 / 手输（`t` / `token` / `code` / 裸短码）也在这里归一。
 *
 * ## 三条纪律
 *
 * ① **提取出「码」就原样交给服务端**（`GET /api/worker/production/scan?token=<码>`）：码的形态判定
 *    （短码 ⇒ token 的换发、归一化、撤销）**只在服务端**（`ProductionScanService.normalizeScanKey`
 *    同时认短码与新 token）—— 前端**不判码形态、不做第二套映射**；
 * ② **只看「去哪一页」这一件事**：本模块的 `kind` 只在 `t`/`token`（报工页）与 `code`（补打页）之间
 *    分流，依据是**参数名 / 路径段**（与两个码空间的生产者一一对应），不是靠猜码的形状；
 * ③ **不依赖 `window`**：h5 侧把 `location.search` 传进来、小程序侧把 `query` / `params` 传进来，
 *    本模块纯函数 ⇒ 小程序侧无 `window` 也能跑（判据 `tests/scan-input.test.ts`）。
 */

/** 码从哪个形态取出来的（排查/判据用；**不上屏**） */
export type ScanLandingFrom =
  | 'param-t'
  | 'param-code'
  | 'scan-text'
  | 'mini-app-code'
  | 'link-qr'
  /** A 档 `q` 里的**部位短链**（`/s/<短码>`）：小程序不跟随 302 ⇒ 这份码要先换 token（issue #8196） */
  | 'link-qr-short'
  | 'none'

/** 该去哪一页：报工页 / 补打页 / 不去（不是落地形态） */
export type ScanLandingKind = 'report' | 'reprint' | 'none'

export interface ScanLanding {
  kind: ScanLandingKind
  /** 提取出的码（**原样**：归一化在服务端）；`kind: 'none'` 时为 `''` */
  code: string
  from: ScanLandingFrom
}

/**
 * 入口接收的全部形态（按需给，没给的当"没有这个来源"）。
 *
 * `present` 与"读到空"**必须可分**：`/b/?t=` 是"出现了但为空"（要给明确提示），
 * 与"根本没有落地参数"是两件事。
 */
export interface ScanEntry {
  /** h5：URL 的 search 段（`?t=…` / `?code=…`） */
  search?: string | null
  /** 小程序冷启动：`Taro.getEnterOptionsSync().query`（`scene` / `q` / `t` …） */
  query?: Record<string, any> | null
  /** 页面参数：`Taro.getCurrentInstance().router.params`（`t` / `token` / `code`） */
  params?: Record<string, any> | null
  /** 小程序内扫一扫的原文（`Taro.scanCode` 的 `result`） */
  text?: string | null
  /** 小程序码的 `scene`（单独给也行） */
  scene?: string | null
  /** 扫普通链接二维码进小程序的 `q`（URL-encoded 完整链接；单独给也行） */
  q?: string | null
}

export const NONE_LANDING: ScanLanding = { kind: 'none', code: '', from: 'none' }

/**
 * 入口参数名的**唯一清单**——与服务端 `ProductionScanService.normalizeScanKey` 的键序同源
 * （`t` → `token` → `code`）。顺序即优先级：`t` 出现就以 `t` 为准。
 */
export const SCAN_PARAM_KEYS = ['t', 'token', 'code'] as const

/** `decodeURIComponent` 遇到非法百分号编码会抛 —— 抛出去会把"读参数"变成白屏，故退回原样 */
export function decodeLoose(value: string): string {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

/** 从 URL query 串读**某个参数**（`?<name>=X` / `<name>=X`；无 ⇒ `present: false`）。 */
export function readQueryParam(
  search: string | null | undefined,
  name: string,
): { present: boolean; raw: string } {
  const text = String(search ?? '').replace(/^\?/, '')
  if (!text) return { present: false, raw: '' }
  for (const pair of text.split('&')) {
    if (!pair) continue
    const eq = pair.indexOf('=')
    const key = decodeLoose(eq < 0 ? pair : pair.slice(0, eq))
    if (key !== name) continue
    const value = eq < 0 ? '' : pair.slice(eq + 1)
    // `+` 在 query 里代表空格（工人从聊天记录里粘 URL 时会出现）：只做这一处还原
    return { present: true, raw: decodeLoose(value).replace(/\+/g, ' ') }
  }
  return { present: false, raw: '' }
}

/** 按 `keys` 的顺序在若干"参数包"里找第一个出现的键（`t` 优先于 `token` 优先于 `code`）。 */
function firstParam(
  keys: readonly string[],
  sources: Array<Record<string, any> | null | undefined>,
): { name: string; value: string } | null {
  for (const key of keys) {
    for (const source of sources) {
      if (!source) continue
      if (!(key in source)) continue
      const value = source[key]
      if (value === undefined) continue
      return { name: key, value: value === null ? '' : String(value) }
    }
  }
  return null
}

/** 整条 URL / 路径里某个 query 或 hash 键的值（`?t=` / `&t=` / `#t=` 都认）。 */
function paramInText(text: string, keys: readonly string[]): string {
  for (const key of keys) {
    const hit = new RegExp(`[?&#]${key}=([^&#]*)`).exec(text)
    if (hit) return decodeLoose(hit[1]).trim()
  }
  return ''
}

/** `/s/<码>` / `/o/<码>` / `/i/<码>` 的路径段（三个公开短码前缀，顺序无关）。 */
function segmentInText(text: string): string {
  const hit = /\/(?:s|o|i)\/([A-Za-z0-9_-]+)/.exec(text)
  return hit ? hit[1] : ''
}

/** URL / 路径形态（小程序的扫一扫给的是整条链接；裸短码与单号不是） */
const URL_LIKE = /^(https?:\/\/|\/)/i

/**
 * 扫到的**原文** ⇒ 码（原样，不归一化）。
 *
 * 三种形态都认（与 issue #7812 的 `tokensFromScanResult` **逐字同源**，那支现在委托到这里）：
 * 短链（`/s/<短码>`）/ 带 `t` 或 `token` 参数（`/b/?t=<token>`、兼容期的 `/w/?t=`）/ 裸短码或单号。
 * 认不出 ⇒ 原样返回（手输的单号也走这条路，由服务端判它是不是码）。
 */
export function codeFromScanText(text: string | null | undefined): string {
  const raw = String(text ?? '').trim()
  if (raw === '') return ''
  const byParam = paramInText(raw, SCAN_PARAM_KEYS)
  if (byParam !== '') return byParam
  const bySegment = segmentInText(raw)
  if (bySegment !== '') return bySegment
  // 形如 `?t=` 但值为空：仍是"这里的码是空的"，不是"没有码"（交给上层说清）
  if (URL_LIKE.test(raw) && /[?&#](?:t|token|code)=/.test(raw)) return ''
  return raw
}

/** 该去哪一页：`/i/` 是入库标签（补打页），其余（`/s/` `/o/` 裸码 / 单号）都是报工页。 */
function kindOfLink(text: string): ScanLandingKind {
  return /\/i\/[A-Za-z0-9_-]+/.test(text) ? 'reprint' : 'report'
}

/**
 * `q` 里的链接是不是**部位短链**（`https://app.migaozn.com/s/<短码>`，issue #8196）。
 *
 * 它判的是**码从哪个来源取出来的**（路径段 vs 查询参数），**不是**码的形状 ——
 * 与 {@link resolveScanLanding} 的 `kind` 同一条纪律（见模块头 ②）：前端仍不猜「这一串是不是短码」。
 * 为什么要区分：A 档（微信「扫普通链接二维码打开小程序」）里小程序**不跟随服务端 302**，
 * `/s/<短码>` 这一支必须先由短链 JSON 面换回 token（`services/workerShortLinkService.ts`），
 * 而 `…/b/report/?t=<token>` 这一支（302 的落点形态）直接把 `t` 当 token 用，**不需要**多一跳。
 */
export function isPartShortLink(text: string | null | undefined): boolean {
  const raw = String(text ?? '').trim()
  if (raw === '') return false
  // 显式 `t` / `token` / `code` 参数优先（那是 302 落点 / 手输形态）⇒ 码不来自路径段
  if (paramInText(raw, SCAN_PARAM_KEYS) !== '') return false
  return /\/s\/[A-Za-z0-9_-]+/.test(raw)
}

/**
 * **入口解析的唯一实现**：任意形态 ⇒ 「去哪一页 + 什么码」。
 *
 * 优先级（每个来源在真实世界里互斥，写死顺序只为结果确定）：
 * ① `q`（**A 档主路径**：小程序后台「扫普通链接二维码打开小程序」⇒ 微信把整条链接 URL-encoded
 *    放进 `getEnterOptionsSync().query.q`）→ ② `scene`（B 档「小程序码」，本期不生成但解析侧兼容）
 * → ③ `text`（小程序内扫一扫）→ ④ 页面参数 / 启动参数 → ⑤ h5 的 URL search。
 *
 * 🔴 `q` 那一支多给一个 `from` 取值：`/s/<短码>` ⇒ `'link-qr-short'`（要先换 token，issue #8196）；
 * 其余（`…/b/report/?t=` / `/o/` / `/i/`）⇒ `'link-qr'`（码原样可用，与改前逐字一致）。
 */
export function resolveScanLanding(entry: ScanEntry = {}): ScanLanding {
  const q = String(entry.q ?? entry.query?.q ?? entry.params?.q ?? '').trim()
  if (q !== '') {
    const link = decodeLoose(q)
    return {
      kind: kindOfLink(link),
      code: codeFromScanText(link),
      from: isPartShortLink(link) ? 'link-qr-short' : 'link-qr',
    }
  }
  const scene = String(entry.scene ?? entry.query?.scene ?? entry.params?.scene ?? '').trim()
  if (scene !== '') {
    return { kind: 'report', code: decodeLoose(scene).trim(), from: 'mini-app-code' }
  }
  const text = String(entry.text ?? '').trim()
  if (text !== '') {
    return { kind: kindOfLink(text), code: codeFromScanText(text), from: 'scan-text' }
  }
  const byObject = firstParam(SCAN_PARAM_KEYS, [entry.params, entry.query])
  if (byObject) {
    return {
      kind: byObject.name === 'code' ? 'reprint' : 'report',
      code: byObject.value,
      from: byObject.name === 'code' ? 'param-code' : 'param-t',
    }
  }
  for (const key of SCAN_PARAM_KEYS) {
    const hit = readQueryParam(entry.search, key)
    if (!hit.present) continue
    return {
      kind: key === 'code' ? 'reprint' : 'report',
      code: hit.raw,
      from: key === 'code' ? 'param-code' : 'param-t',
    }
  }
  return NONE_LANDING
}
