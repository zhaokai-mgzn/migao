// case_ids: OB-001
// 复用既有用例 OB-001（注册提交契约；本单不新增用例 ID，理由见 PR body：新增用例会触发
// case-trust burn-down 预算 + 与 #4361 争生成物）。
// OB-001（issue #4363 前端半边 / 契约所有者 #4361）：行业取值**受控词表 v1** 的单一真值源。
// 词表冻结为 code（落库/提交用 code，显示用 label），注册页与后续任何消费者必须共用本模块
// —— 复制第二份词表 ⇒ 注册页写 `curtain`、别处写「布艺 / 窗帘」⇒ 模板键不可靠（本单的病根）。
// 反 placeholder：断言的是**具体取值**（code/label/是否套用模板），不是「数组非空」。
import { describe, expect, it } from 'vitest'
import { INDUSTRY_OPTIONS, industryLabel, industryAppliesTemplate } from '@/lib/industry'

describe('行业受控词表（issue #4361 冻结 v1）', () => {
  it('词表恰为 curtain / other 两项，code 与显示名逐字冻结', () => {
    expect(INDUSTRY_OPTIONS.map((o) => o.code)).toEqual(['curtain', 'other'])
    expect(INDUSTRY_OPTIONS.map((o) => o.label)).toEqual(['布艺 / 窗帘', '其他'])
  })

  it('只有 curtain 套用行业生产种子模板；other 显式不套用（不静默落默认模板）', () => {
    expect(industryAppliesTemplate('curtain')).toBe(true)
    expect(industryAppliesTemplate('other')).toBe(false)
    // 存量自由文本 / 空值一律**不**套用（未知 ≠ curtain）
    expect(industryAppliesTemplate('布艺纺织')).toBe(false)
    expect(industryAppliesTemplate('')).toBe(false)
    expect(industryAppliesTemplate(undefined)).toBe(false)
  })

  it('industryLabel 只认词表内的 code，未知取值不编造显示名', () => {
    expect(industryLabel('curtain')).toBe('布艺 / 窗帘')
    expect(industryLabel('other')).toBe('其他')
    expect(industryLabel('布艺纺织')).toBeUndefined()
    expect(industryLabel(undefined)).toBeUndefined()
  })
})
