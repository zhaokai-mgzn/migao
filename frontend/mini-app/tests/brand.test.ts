/**
 * 品牌文案工具测试
 *
 * 覆盖: 导航副标题品牌名来源（企业设置租户名，非硬编码）
 *
 * UI-016: C 端品牌名去硬编码 — 导航副标题企业名取自企业设置（租户名）
 */
// case_ids: UI-016
import { buildBrandSubtitle } from '../src/utils/brand'

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
