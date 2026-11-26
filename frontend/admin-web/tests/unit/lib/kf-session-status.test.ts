// case_ids: KF-029
/**
 * 微信客服工作台的展示纯函数（issue #9202 / 母单 #9194 子项 2 前端面）。
 *
 * 页面渲染由 `tests/unit/pages/human-sessions-kf.test.tsx` 判；这里判**规则本身**：
 * 状态文案不留空白、额度只对微信客服生效（普通会话不得被锁死）。
 */
import { describe, it, expect } from 'vitest'
import {
  isKfBudgetExhausted,
  kfBudgetLabel,
  kfSendStatusLabel,
} from '@/lib/kf-session-status'

describe('KF-029 微信客服展示规则', () => {
  it('发送状态五态各有人话；缺失 / 未知值都退到「状态未知」，不留空白', () => {
    expect(kfSendStatusLabel('pending')).toBe('待发送')
    expect(kfSendStatusLabel('sending')).toBe('发送中')
    expect(kfSendStatusLabel('accepted')).toBe('已接收')
    expect(kfSendStatusLabel('failed')).toBe('发送失败')
    expect(kfSendStatusLabel('unknown')).toBe('状态未知')
    expect(kfSendStatusLabel(undefined)).toBe('状态未知')
    expect(kfSendStatusLabel(null)).toBe('状态未知')
    expect(kfSendStatusLabel('not-a-status')).toBe('状态未知')
  })

  it('额度读数：已用/上限；字段缺失按 0/5 兜底', () => {
    expect(kfBudgetLabel({ channel: 'wechat_kf', budgetUsed: 2, budgetLimit: 5 })).toBe('2/5')
    expect(kfBudgetLabel({ channel: 'wechat_kf', budgetUsed: 5 })).toBe('5/5')
    expect(kfBudgetLabel({ channel: 'wechat_kf' })).toBe('0/5')
  })

  it('额度用尽只对微信客服成立（普通人工会话不得被输入框禁用）', () => {
    expect(isKfBudgetExhausted({ channel: 'wechat_kf', budgetUsed: 5, budgetLimit: 5 })).toBe(true)
    expect(isKfBudgetExhausted({ channel: 'wechat_kf', budgetUsed: 6, budgetLimit: 5 })).toBe(true)
    expect(isKfBudgetExhausted({ channel: 'wechat_kf', budgetUsed: 4, budgetLimit: 5 })).toBe(false)
    expect(isKfBudgetExhausted({ channel: null, budgetUsed: 99, budgetLimit: 5 })).toBe(false)
    expect(isKfBudgetExhausted({ budgetUsed: 99 })).toBe(false)
    expect(isKfBudgetExhausted(null)).toBe(false)
  })
})
