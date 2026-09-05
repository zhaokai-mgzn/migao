/**
 * 品牌文案工具测试
 *
 * 覆盖: 导航副标题品牌名来源（企业设置租户名，非硬编码）
 *
 * UI-016: C 端品牌名去硬编码 — 导航副标题企业名取自企业设置（租户名）
 * UI-018: C 端智能客服名称去硬编码 — 思考中/空态/导航名取 botName，未配置默认「小布」
 */
// case_ids: UI-016, UI-018
import { buildBrandSubtitle, buildBotName } from '../src/utils/brand'

describe('buildBrandSubtitle', () => {
  it('有租户名（企业设置公司名）→ 「{企业名} · 智能购物助手」', () => {
    expect(buildBrandSubtitle('米高窗帘')).toBe('米高窗帘 · 智能购物助手')
    expect(buildBrandSubtitle('林氏布艺')).toBe('林氏布艺 · 智能购物助手')
  })

  it('租户名为空 → 仅「智能购物助手」（不硬编码默认企业名）', () => {
    expect(buildBrandSubtitle(undefined)).toBe('智能购物助手')
    expect(buildBrandSubtitle(null)).toBe('智能购物助手')
    expect(buildBrandSubtitle('')).toBe('智能购物助手')
    expect(buildBrandSubtitle('   ')).toBe('智能购物助手')
  })
})

describe('buildBotName', () => {
  // UI-018: 配置了 botName（企业设置智能客服名称）→ 使用配置值
  it('有 botName（企业设置智能客服名称）→ 使用配置值', () => {
    expect(buildBotName('米宝')).toBe('米宝')
    expect(buildBotName('小云')).toBe('小云')
  })

  // UI-018: 未配置/为空 → 兜底「小布」（不硬编码 AI 等通用词）
  it('botName 为空/未配置 → 兜底「小布」', () => {
    expect(buildBotName(undefined)).toBe('小布')
    expect(buildBotName(null)).toBe('小布')
    expect(buildBotName('')).toBe('小布')
    expect(buildBotName('   ')).toBe('小布')
  })
})
