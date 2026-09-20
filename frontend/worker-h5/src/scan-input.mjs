// case_ids: PG-018, BM-006, DF-017
//
// 工人端 H5 报工页 —— 扫码入口解析（设计 #4716 §1.3 / §1.4 / §1.5）。
//
// 纯函数、零依赖、不碰微信 API（裁定③）。**不判码的形态**：URL 只用来「把码值取出来」，
// 形态判定（短码 / 旧 token / 加工单号 / 订单号）是服务端 `resolveOrder` 的职责
// —— 在扫描侧再写一份就是第二份口径（#4687 §2.6 / 设计 C10）。

/** 只认这三个 query 键；其它参数一律不当码（避免把无关参数当码去扫）。 */
const CODE_KEYS = ['t', 'token', 'code']

/** 租户子域：`<tenantId>.app.migaozn.com`（与后端 TenantDomainResolver 同形）。 */
const TENANT_SUBDOMAIN = /^(\d+)\.app\.migaozn\.com$/i

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
 * 租户 id：**优先** `<tenantId>.app.migaozn.com` 子域（与后端同一判据）；
 * 稳定短链域名（`app.migaozn.com`，无子域）⇒ 回落 `?tenant_id=`（打印的码不带租户 ⇒ 需要人给一次）。
 *
 * @param {string} href 当前页面 URL
 * @returns {number|null} 租户 id；判不出 ⇒ null（登录时由用户填/由服务端按域名判）
 */
export function tenantIdFromLocation(href) {
  let url
  try {
    url = new URL(href)
  } catch {
    return null
  }
  const m = TENANT_SUBDOMAIN.exec(url.hostname)
  if (m) return Number(m[1])
  const q = url.searchParams.get('tenant_id')
  return q && /^\d+$/.test(q) ? Number(q) : null
}
