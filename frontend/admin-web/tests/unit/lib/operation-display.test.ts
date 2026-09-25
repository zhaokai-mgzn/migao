// case_ids: PP-011
// PP-011（issue #4621，web 面工序命名统一 · 阶段 1）：工序显示名的**唯一**口径 ——
// 显示名 = 逻辑工序名；该实例**有部位**时拼成「逻辑名 · 部位」（如 `三边 · 布帘`）；
// 部位无关工序（`外帘装袋`）⇒ 只显示逻辑名。
//
// 数据来源：后端读面**只加不改**地给出 `logical_name` + `position`（**读时派生、不写库**）；
// 既有 `operation` / `operation_name` 是**工人端快照名**（变体名 `精裁-布`）⇒ 只作老数据兜底。
// 各面（加工单进度表 / 任务卡打印 / 计件报表）一律调本函数 —— 各页各拼一份必然漂移。
import { describe, expect, it } from 'vitest'
import { operationDisplayName } from '@/lib/operation-display'

describe('operationDisplayName（工序显示名唯一口径）', () => {
  it('逻辑名 + 部位 ⇒ 「逻辑名 · 部位」', () => {
    expect(operationDisplayName({ operation: '精裁-布', logical_name: '精裁', position: '布帘' })).toBe(
      '精裁 · 布帘',
    )
    expect(operationDisplayName({ operation: '布三边', logical_name: '三边', position: '布帘' })).toBe(
      '三边 · 布帘',
    )
    expect(operationDisplayName({ operation: '韩褶-纱', logical_name: '韩褶', position: '纱帘' })).toBe(
      '韩褶 · 纱帘',
    )
  })

  it('部位无关工序（position 缺省 / null / 全空白）⇒ 只显示逻辑名，不拼空部位', () => {
    expect(operationDisplayName({ operation: '外帘装袋', logical_name: '外帘装袋' })).toBe('外帘装袋')
    expect(operationDisplayName({ operation: '外帘装袋', logical_name: '外帘装袋', position: null })).toBe(
      '外帘装袋',
    )
    expect(operationDisplayName({ operation: '外帘装袋', logical_name: '外帘装袋', position: '  ' })).toBe(
      '外帘装袋',
    )
  })

  it('老数据缺 logical_name ⇒ 退回 operation 原文（不显示空白）', () => {
    expect(operationDisplayName({ operation: '定型-布' })).toBe('定型-布')
    expect(operationDisplayName({ operation: '定型-布', logical_name: null })).toBe('定型-布')
    expect(operationDisplayName({ operation: '定型-布', logical_name: '  ' })).toBe('定型-布')
  })

  it('同义不同名：operation_name（报工流水读面键）也作快照名兜底（issue #5003②）', () => {
    // 改前兜底分支只认 `operation` ⇒ 读面行传进来时取不到值、显示空串（本行即那条红证）。
    expect(operationDisplayName({ operation_name: '定型-布' })).toBe('定型-布')
    expect(operationDisplayName({ operation_name: '定型-布', logical_name: '定型' })).toBe('定型')
    // 同义两键同时在 ⇒ `operation` 优先（口径显式，不靠对象字面量的书写顺序）
    expect(operationDisplayName({ operation: '精裁-布', operation_name: '三边-布' })).toBe('精裁-布')
  })

  it('有逻辑名时**不出现**变体名（快照名只作兜底）', () => {
    const text = operationDisplayName({ operation: '精裁-布', logical_name: '精裁', position: '布帘' })
    expect(text.includes('精裁-布')).toBe(false)
    expect(text).toBe('精裁 · 布帘')
  })

  it('两侧都缺 ⇒ 空串（调用方按空态渲染，不编占位名）', () => {
    expect(operationDisplayName({})).toBe('')
    expect(operationDisplayName(null)).toBe('')
    expect(operationDisplayName(undefined)).toBe('')
  })

  it('两侧的空白字符会被 trim（不留悬空空格 / 不出现「 · 」空壳）', () => {
    expect(operationDisplayName({ operation: 'x', logical_name: ' 精裁 ', position: ' 布帘 ' })).toBe(
      '精裁 · 布帘',
    )
    expect(operationDisplayName({ operation: ' 外帘装袋 ', logical_name: '  ' })).toBe('外帘装袋')
  })
})
