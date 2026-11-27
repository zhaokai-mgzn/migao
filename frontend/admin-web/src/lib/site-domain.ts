/**
 * 站点域名的**唯一读取点**（issue #8941 / 生产验收 P0-3、P1-1；issue #8968 修正公开面落点）。
 *
 * 病根：同一份 admin-web 产物被部署到测试域 `migaozn.com` 与生产域 `cytda.com`，而站点级
 * 绝对地址（商家登录跳转 / canonical / og:image / sitemap / robots / proxy 的 host 分支）
 * 把 `migaozn.com` **写死在 5 个位置** ⇒ 生产环境出现三件静默错事：
 *   ① 官网「商家登录」把生产用户送去**测试域**；
 *   ② canonical / og / sitemap 把生产页登记成**测试域**；
 *   ③ `merchant.cytda.com/` 不跳登录页、`cytda.com/dashboard` 不跳商家域（proxy 不认识该域名）。
 *
 * 口径 = **一个构建期来源** `NEXT_PUBLIC_SITE_DOMAIN`（缺省 `migaozn.com`）：
 *   · `NEXT_PUBLIC_*` 是**构建期文本替换** ⇒ 换域名必须重新构建，不是改运行时 env；
 *   · 缺省值下除公开面 origin（issue #8968 已收成 apex）外，其余派生值与改前**逐字相同**。
 *
 * 🔴 **公开面 = 不产生跳转的那个 host = apex**（issue #8968）：
 *   `www.<domain>` → `<domain>` 的 **308** 由 `frontend/admin-web/next.config.mjs` 的
 *   `redirects()` 产生 —— 规则 `permanent: true`，而 Next 把 `permanent` 映射成
 *   `RedirectStatusCode.PermanentRedirect` = **308**（`next/dist/lib/redirect-status.js` 现取）；
 *   规则按本文件的 `siteDomain()` 参数化 ⇒ **对任意 `<domain>` 通用**（测试域与生产域实测同样 308）。
 *   ⇒ sitemap / robots / `metadataBase` / canonical 一律取 `siteOrigin()`（**apex**）：
 *     写 www 会让每条 `<loc>` 都先吃一次 308，canonical 与真实落点不一致（爬虫视角的假落点）。
 *   ⇒ `wwwHost()` 只留给**跳转判定**（`next.config.mjs` 的规则 / `src/proxy.ts` 的 host 分支），
 *     不再是公开面。
 *
 * ⚠️ 读值写在**函数体内**（不是模块级常量）：构建期替换照旧生效，同时单测可以
 *    `vi.stubEnv('NEXT_PUBLIC_SITE_DOMAIN', …)` 逐格给值（同 `src/lib/bmini-h5-url.ts` 口径）。
 * ⚠️ `next.config.mjs` 是 `.mjs`、无法 import 本文件 ⇒ 它读**同一个** env；两处缺省字面量的
 *    一致性由 `frontend/admin-web/tests/unit/pages/site-domain.test.ts` 钉住（不等即红）。
 */
export const DEFAULT_SITE_DOMAIN = 'migaozn.com'

/** 归一化成 host：容忍误传整条 origin / 末尾斜杠，大小写归一（畸形值的症状是 host 不匹配，很难查）。 */
function normalizeDomain(raw: string): string {
  return raw
    .trim()
    .replace(/^https?:\/\//i, '')
    .replace(/\/.*$/, '')
    .toLowerCase()
}

/** 站点 apex 域名（`migaozn.com` / `cytda.com`）。 */
export function siteDomain(): string {
  return normalizeDomain(process.env.NEXT_PUBLIC_SITE_DOMAIN || '') || DEFAULT_SITE_DOMAIN
}

/**
 * `www` 主机名 —— **只用于跳转判定**（`next.config.mjs` 的 www→apex 308 / `src/proxy.ts` 的 host 分支）。
 * 公开面请用 `siteOrigin()`（issue #8968：www 会 308，写进 sitemap / canonical 就是假落点）。
 */
export function wwwHost(): string {
  return `www.${siteDomain()}`
}

/** 商家端主机名 —— 官网「商家登录」跳转落点。 */
export function merchantHost(): string {
  return `merchant.${siteDomain()}`
}

/**
 * 站点公开面 origin（`https://<domain>` —— **apex**，不产生跳转的那个 host）——
 * `metadataBase` / sitemap / robots / canonical 的唯一真值源（issue #8968）。
 */
export function siteOrigin(): string {
  return `https://${siteDomain()}`
}

/** 官网「商家登录」绝对地址（桌面 + 移动两处导航共用，不各写一遍域名）。 */
export function merchantLoginUrl(): string {
  return `https://${merchantHost()}/login`
}
