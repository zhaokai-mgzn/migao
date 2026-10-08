/**
 * 品牌文案工具测试（B 端商家版，issue #2977）
 *
 * 覆盖: 导航副标题品牌名来源（企业设置租户名，非硬编码）
 * B 端语义：面向商家员工，副标题「· 商家经营助手」，AI 名默认「黄金策」（与 C 端「元元」区分）
 */
// case_ids: UI-016, UI-018
import { buildBrandSubtitle, buildBotName } from '../src/utils/brand'

describe('buildBrandSubtitle', () => {
  it('有租户名（企业设置公司名）→ 「{企业名} · 商家经营助手」', () => {
    expect(buildBrandSubtitle('观星台窗帘')).toBe('观星台窗帘 · 商家经营助手')
    expect(buildBrandSubtitle('林氏布艺')).toBe('林氏布艺 · 商家经营助手')
  })

  it('租户名为空 → 仅「商家经营助手」（不硬编码默认企业名）', () => {
    expect(buildBrandSubtitle(undefined)).toBe('商家经营助手')
    expect(buildBrandSubtitle(null)).toBe('商家经营助手')
    expect(buildBrandSubtitle('')).toBe('商家经营助手')
    expect(buildBrandSubtitle('   ')).toBe('商家经营助手')
  })
})

describe('buildBotName', () => {
  // UI-018: 配置了 botName（企业设置智能客服名称）→ 使用配置值
  it('有 botName（企业设置智能客服名称）→ 使用配置值', () => {
    expect(buildBotName('黄金策')).toBe('黄金策')
    expect(buildBotName('小云')).toBe('小云')
  })

  // UI-018: 未配置/为空 → 兜底「黄金策」（B 端口径，与 C 端「元元」区分）
  it('botName 为空/未配置 → 兜底「黄金策」', () => {
    expect(buildBotName(undefined)).toBe('黄金策')
    expect(buildBotName(null)).toBe('黄金策')
    expect(buildBotName('')).toBe('黄金策')
    expect(buildBotName('   ')).toBe('黄金策')
  })
})