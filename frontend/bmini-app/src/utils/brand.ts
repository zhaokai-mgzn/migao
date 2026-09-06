/**
 * 品牌文案工具（B 端商家版，issue #2977）
 *
 * 覆盖:
 *  - buildBrandSubtitle: B 端导航栏副标题 = 企业名（租户名）· 商家经营助手
 *  - buildBotName: B 端智能客服名称（TenantAiConfig.botName，思考中/空态/导航名展示；未配置默认「米宝」）
 *
 * B 端语义：面向商家员工（老板/运营/客服），导航副标题企业名取自租户名，
 * 智能客服名默认「米宝」（与 C 端默认「小布」区分）。
 */
export function buildBrandSubtitle(tenantName?: string | null): string {
  if (tenantName && tenantName.trim()) {
    return `${tenantName.trim()} · 商家经营助手`
  }
  return '商家经营助手'
}

/** 智能客服名称：TenantAiConfig.botName 配置优先，未配置/为空默认「米宝」 */
export function buildBotName(botName?: string | null): string {
  if (botName && botName.trim()) {
    return botName.trim()
  }
  return '米宝'
}