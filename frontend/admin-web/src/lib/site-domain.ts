/**
 * 站点域名的**唯一读取点**（issue #8941 / 生产验收 P0-3、P1-1）。
 *
 * 病根：同一份 admin-web 产物被部署到测试域 `migaozn.com` 与生产域 `cytda.com`，而站点级
 * 绝对地址（商家登录跳转 / canonical / og:image / sitemap / robots / www→裸域 301 / proxy 的
 * host 分支）把 `migaozn.com` **写死在 5 个位置** ⇒ 生产环境出现三件静默错事：
 *   ① 官网「商家登录」把生产用户送去**测试域**；
 *   ② canonical / og / sitemap 把生产页登记成**测试域**；
 *   ③ `merchant.cytda.com/` 不跳登录页、`cytda.com/dashboard` 不跳商家域（proxy 不认识该域名）。
 *
 * 口径 = **一个构建期来源** `NEXT_PUBLIC_SITE_DOMAIN`（缺省 `migaozn.com`）：
 *   · `NEXT_PUBLIC_*` 是**构建期文本替换** ⇒ 换域名必须重新构建，不是改运行时 env；
 *   · 缺省值下所有派生值与改前**逐字相同**（测试环境在跑，不许有任何行为变化）。
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

/** `www` 主机名 —— 站点公开面（canonical / og:image / sitemap / robots）的落点，改前口径不变。 */
export function wwwHost(): string {
  return `www.${siteDomain()}`
}

/** 商家端主机名 —— 官网「商家登录」跳转落点。 */
export function merchantHost(): string {
  return `merchant.${siteDomain()}`
}

/** 站点公开面 origin（`https://www.<domain>`）—— `metadataBase` / sitemap / robots 的唯一真值源。 */
export function siteOrigin(): string {
  return `https://${wwwHost()}`
}

/** 官网「商家登录」绝对地址（桌面 + 移动两处导航共用，不各写一遍域名）。 */
export function merchantLoginUrl(): string {
  return `https://${merchantHost()}/login`
}
