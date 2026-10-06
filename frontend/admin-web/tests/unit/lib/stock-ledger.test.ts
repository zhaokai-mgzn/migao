// case_ids: UI-087
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 库存明细的**展示口径纯函数**（`frontend/admin-web/src/lib/stock-ledger.ts`，issue #6404）。
 *
 * ## 为什么这些断言值得单独一个文件
 *
 * 它们不是「格式化偏好」—— 两条都是**不许假绿**的口径，且都能在真库数据上立刻看出来：
 *
 * ① 🔴 **成本 `null` ⇒「未知」**，而 `0` ⇒ `¥0.00`。这对判别是本文件的**核心**：
 *    「读不出」与「不要钱」必须长得不一样。真值源 = `StockLedger` 的 javadoc 逐字：
 *    「NULL = 该次变更发生时成本未知（存量行全部为 NULL，**不伪造**）」；
 *    实测读数（2026-10-06 真库截图 `/tmp/ui-accept-6404/01-full.png`）：首屏 20 行成本列**全部**是「未知」。
 * ② **不重算**：本模块只做「值的搬运 + 形态」，不做四则运算 ⇒ 传进去什么值就出来什么值
 *    （页面侧同理，判别器 = 页面测试里的**见证行**）。
 *
 * 另附一条**类级**判据：`StockLedger` 的每个 `REASON_*` 常量都必须有中文标签 ——
 * 服务端加了新 reason 而前端没跟 ⇒ 本文件红（而不是商家在页面上看见一个英文标识符）。
 */

const ROOT = join(process.cwd(), '..', '..')
const STOCK_LEDGER_ENTITY = readFileSync(
  join(ROOT, 'backend/admin-api/src/main/java/com/migao/admin/entity/StockLedger.java'),
  'utf-8',
)

import {
  REASON_LABELS,
  formatCost,
  formatDelta,
  formatQty,
  formatTime,
  reasonLabel,
} from '@/lib/stock-ledger'

describe('库存明细展示口径（issue #6404 / UI-087）', () => {
  it('① 成本：null ⇒「未知」，而 0 ⇒「¥0.00」（读不出 ≠ 不要钱）', () => {
    // 未知这一侧（存量行全为 NULL）
    expect(formatCost(null)).toBe('未知')
    expect(formatCost(undefined)).toBe('未知')
    expect(formatCost('')).toBe('未知')
    expect(formatCost('abc')).toBe('未知')
    // 🔴 判别对：0 是**真值**，必须与「未知」区分开
    expect(formatCost(0)).toBe('¥0.00')
    expect(formatCost('0.00')).toBe('¥0.00')
    expect(formatCost('0')).not.toBe('未知')
    // 有值
    expect(formatCost('1240.00')).toBe('¥1240.00')
    expect(formatCost('74.40')).toBe('¥74.40')
    expect(formatCost(24.8)).toBe('¥24.80')
  })

  it('② 变动量：正数带 + 号、负数原样、0 无符号、缺值 ⇒「-」；且**不重算**', () => {
    expect(formatDelta('50.0')).toBe('+50')
    expect(formatDelta('-3.0')).toBe('-3')
    expect(formatDelta(0)).toBe('0')
    expect(formatDelta('0.0')).toBe('0')
    expect(formatDelta(null)).toBe('-')
    expect(formatDelta(undefined)).toBe('-')
    // 见证形态：传进来的值原样出来（若这里出现 from-before/after 的运算，值会变）
    expect(formatDelta('-2.0')).toBe('-2')
  })

  it('③ 数量：最多 1 位小数、去尾零（复用库存数量的既有口径）；缺值 ⇒「-」', () => {
    expect(formatQty('50.0')).toBe('50')
    expect(formatQty('47.5')).toBe('47.5')
    expect(formatQty('0.1')).toBe('0.1')
    expect(formatQty(0)).toBe('0')
    expect(formatQty(null)).toBe('-')
    expect(formatQty(undefined)).toBe('-')
    expect(formatQty('')).toBe('-')
    expect(formatQty('abc')).toBe('-')
  })

  it('④ 原因：已知取中文；**未知取值原样显示**（不吞成空白）；缺值 ⇒「—」', () => {
    expect(reasonLabel('order')).toBe('订单扣减')
    expect(reasonLabel('aftersales')).toBe('售后回补')
    expect(reasonLabel('manual')).toBe('手工调整')
    expect(reasonLabel('inbound')).toBe('入库过账')
    // 服务端加了新 reason 而前端没跟 ⇒ 商家至少看得见原始标记（不是空白、不是「其他」）
    expect(reasonLabel('stocktake')).toBe('stocktake')
    expect(reasonLabel(null)).toBe('—')
    expect(reasonLabel(undefined)).toBe('—')
    expect(reasonLabel('')).toBe('—')
  })

  it('⑤ 时间：本机时区可读形态；缺值 / 不可解析 ⇒「—」（不是空白、不是 Invalid Date）', () => {
    expect(formatTime(null)).toBe('—')
    expect(formatTime(undefined)).toBe('—')
    expect(formatTime('')).toBe('—')
    expect(formatTime('not-a-date')).toBe('—')
    const text = formatTime('2026-10-01T10:00:00+08:00')
    expect(text).not.toBe('—')
    expect(text).toContain('2026')
    expect(text).not.toContain('Invalid')
  })

  it('⑥ 类级：StockLedger 的每个 REASON_* 常量都有中文标签（新增 reason 而未跟 ⇒ 本判据红）', () => {
    const reasons = [...STOCK_LEDGER_ENTITY.matchAll(/String REASON_[A-Z]+\s*=\s*"([^"]+)"/g)].map(
      (m) => m[1],
    )
    // 解析失配自证：一个都没读到 ⇒ 红，不得静默通过（空集比空集是恒等 = 假绿）
    expect(reasons.length).toBeGreaterThan(0)
    const missing = reasons.filter((r) => !(r in REASON_LABELS))
    expect(missing, `后端新增 reason 但前端没有标签：${missing.join(', ')}`).toEqual([])
    // 反向也钉：标签表不得凭空多出后端不存在的 reason（陈旧即红）
    const stale = Object.keys(REASON_LABELS).filter((k) => !reasons.includes(k))
    expect(stale, `前端标签表有后端不存在的 reason：${stale.join(', ')}`).toEqual([])
  })
})
