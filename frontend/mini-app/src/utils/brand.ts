/**
 * 品牌文案工具
 *
 * 覆盖:
 *  - buildBrandSubtitle: C 端导航栏副标题 = 企业名（租户名，来自企业基础信息设置）· 智能购物助手
 *
 * UI-016: C 端品牌名去硬编码 — 导航副标题企业名取自企业设置（租户名），非写死「米高窗帘」
 */
export function buildBrandSubtitle(tenantName?: string | null): string {
  if (tenantName && tenantName.trim()) {
    return `${tenantName.trim()} · 智能购物助手`
  }
  return '智能购物助手'
}
