/**
 * 品牌文案工具
 *
 * 覆盖:
 *  - buildBrandSubtitle: C 端导航栏副标题 = 企业名（租户名，来自企业基础信息设置）· 智能购物助手
 *  - buildBotName: C 端智能客服名称（TenantAiConfig.botName，思考中/空态/导航名展示；未配置默认「小布」）
 *
 * UI-016: C 端品牌名去硬编码 — 导航副标题企业名取自企业设置（租户名），非写死「米高窗帘」
 * UI-018: C 端智能客服名称去硬编码 — 思考中/空态/导航名取自企业设置 botName，未配置默认「小布」
 */
export function buildBrandSubtitle(tenantName?: string | null): string {
  if (tenantName && tenantName.trim()) {
    return `${tenantName.trim()} · 智能购物助手`
  }
  return '智能购物助手'
}

/** 智能客服名称：TenantAiConfig.botName 配置优先，未配置/为空默认「小布」 */
export function buildBotName(botName?: string | null): string {
  if (botName && botName.trim()) {
    return botName.trim()
  }
  return '小布'
}
