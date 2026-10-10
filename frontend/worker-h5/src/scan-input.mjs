// case_ids: PG-018, BM-006, DF-017, BM-045
//
// 工人端 H5 报工页 —— 扫码入口解析（设计 #4716 §1.3 / §1.4 / §1.5）。
//
// 纯函数、零依赖、不碰微信 API（裁定③）。**不判码的形态**：URL 只用来「把码值取出来」，
// 形态判定（短码 / 旧 token / 加工单号 / 订单号）是服务端 `resolveOrder` 的职责
// —— 在扫描侧再写一份就是第二份口径（#4687 §2.6 / 设计 C10）。

/** 只认这三个 query 键；其它参数一律不当码（避免把无关参数当码去扫）。 */
const CODE_KEYS = ['t', 'token', 'code']

/** 设备级预设（issue #6635）的合法取值：`cut_calc` = 钉在本机裁高计算页；`report` = 取消钉住。 */
const DEVICE_HOME_PAGES = ['cut_calc', 'report']

/** `keep=1` 之类的「只本次」记号（机台页上的「去报工页」用它，**不许**改掉机台的预设）。 */
const ONCE_VALUES = ['1', 'true', 'yes']

/** 企业编码：形态与后端 `LoginIdentifiers.TENANT_CODE_PATTERN` 同形（issue #6564）。 */
const TENANT_CODE_PATTERN = /^[a-z0-9][a-z0-9_-]{1,31}$/

/**
 * 从「扫码结果 / 手输内容」里取出码值。
 *
 * @param {string} raw 扫码结果（任意 HTTPS URL）或手输内容（短码 / 旧 token / 加工单号 / 订单号）
 * @returns {string} 码值；无法取出（空 / 纯空白 / URL 里没有码键）⇒ `''`（调用方据此**不发请求**）
 */
export function parseScanInput(raw) {
  const text = (raw ?? '').toString().trim()
  if (!text) return ''

  // 只有看起来像 URL（含协议）或站点内绝对路径时才走 URL 解析；否则**原样**当码值
  // （裸 token / 加工单号本身就是合法码值 —— 手输兜底路径）
  const looksLikeUrl = /^[a-z][a-z0-9+.-]*:\/\//i.test(text) || text.startsWith('/')
  if (!looksLikeUrl) return text

  let url
  try {
    url = new URL(text, 'https://app.migaozn.com')
  } catch {
    return text
  }

  for (const key of CODE_KEYS) {
    const v = url.searchParams.get(key)
    if (v && v.trim()) return v.trim()
  }
  // hash 形态（#t=…）：部分短链实现把参数放 hash
  const hash = url.hash.startsWith('#') ? url.hash.slice(1) : url.hash
  if (hash) {
    const hp = new URLSearchParams(hash)
    for (const key of CODE_KEYS) {
      const v = hp.get(key)
      if (v && v.trim()) return v.trim()
    }
  }
  // 路径段形态（/s/<短码> 或 /w/<token>）：最后一段非空即码值
  const segs = url.pathname.split('/').filter(Boolean)
  const last = segs.length ? segs[segs.length - 1] : ''
  return last === 'w' || last === 's' ? '' : last
}

/**
 * 企业编码：稳定短链 302 会把 `&tenant_code=<企业编码>` 带进 URL（issue #6564）——
 * 报工页据此**预填**登录表单的企业编码（仍是普通可编辑输入框）。
 *
 * 形态与后端 `LoginIdentifiers.TENANT_CODE_PATTERN` **同形**
 * （`^[a-z0-9][a-z0-9_-]{1,31}$`；含下划线是为兼容存量 `tenant_7478359537` 形态）；
 * 不合法 ⇒ `null`（当没带，由登录表单填）。
 *
 * @param {string} href 当前页面 URL
 * @returns {string|null} 企业编码；URL 里没有 / 形态不合法 ⇒ null
 */
/**
 * **本机默认页**的设备级预设（issue #6635；用户 2026-10-10 裁定 = 设备级、零后端改动）。
 *
 * `?page=cut_calc` ⇒ 机台那台屏钉在裁高计算页；`?page=report` ⇒ 取消钉住。
 * `keep=1` ⇒ **只本次**（机台页上的「去报工页」入口用它，绝不把机台的预设改掉）。
 * 不认识的 `page` 值 ⇒ 当没带（不把任意参数读成设备预设）。
 *
 * @param {string} href 当前页面 URL
 * @returns {{page: 'cut_calc'|'report'|null, once: boolean}}
 */
export function deviceHomeFromLocation(href) {
  let url
  try {
    url = new URL(href)
  } catch {
    return { page: null, once: false }
  }
  const page = url.searchParams.get('page')
  return {
    page: DEVICE_HOME_PAGES.includes(page) ? page : null,
    once: ONCE_VALUES.includes((url.searchParams.get('keep') ?? '').toLowerCase()),
  }
}

export function enterpriseCodeFromLocation(href) {
  let url
  try {
    url = new URL(href)
  } catch {
    return null
  }
  const q = url.searchParams.get('tenant_code')
  return q && TENANT_CODE_PATTERN.test(q) ? q : null
}

/**
 * 企业编码**归一**（issue #6738）：提交前统一转小写 + 去首尾空白。
 *
 * <p>🔴 <b>不重定义格式</b>：字符集与长度仍由服务端 `LoginIdentifiers.TENANT_CODE_PATTERN`
 * （本文件的 {@link TENANT_CODE_PATTERN} 是同形镜像）唯一裁定 —— 本函数只处理「用户把屏上的编码
 * 抄成大写 / 多打了空格」这一种手误，`-` 与 `_` **原样保留**，不做替换、不做补全。</p>
 *
 * <p>⚠️ 现场读数（2026-10-11，生产 `/api/worker/login` 实测）：大写企业编码**不会**被判格式错 ——
 * 服务端 `WorkerTenantResolver.resolve` 先过 `LoginIdentifiers.normalize()` 再解析，
 * 所以「大写 ⇒ 422」**不成立**（实测返回的是反枚举 401）。本归一的价值 = **前后端一致**：
 * 屏上填什么、请求里就是什么（对账/日志不再出现大小写两副面孔）。</p>
 *
 * @param {*} value 输入框的值（可能是 null / undefined）
 * @returns {string} 归一小写后的编码；空 / 空白 / 非字符串 ⇒ `''`（照旧原样提交，由服务端判）
 */
export function normalizeEnterpriseCode(value) {
  return String(value ?? '').trim().toLowerCase()
}
