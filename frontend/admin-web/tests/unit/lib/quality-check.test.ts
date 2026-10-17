// case_ids: UI-118
import { describe, it, expect } from 'vitest'
import {
  QUALITY_STATE_LABELS,
  QUALITY_STATE_TONES,
  formatMoment,
  latestByItem,
  qualityItemName,
  qualityResultLabel,
  qualityStateChipClass,
  qualityStateLabel,
} from '@/lib/quality-check'
import type { QualityInspectionRecord } from '@/types'

/**
 * 质检记录的**展示口径**（`frontend/admin-web/src/lib/quality-check.ts`，issue #7140）。
 *
 * ## 为什么单独为它写判据
 *
 * 同一套标签 / 颜色 / 时刻格式要在**两个面**上用（质检记录页 + 作业单生产明细的质检区）。
 * 两处各写一份 ⇒ 迟早给出不同的判定名，商家与质检员看到的对不上。所以这里是**唯一实现**，
 * 也必须由**唯一一份**判据钉住：
 *
 * ① 三态中文名 = 服务端 `QualityCheckService.label()` 的**同一组词**（合格 / 返工 / 报废）；
 * ② 🔴 **未检 ≠ 合格**：`pending` 是「还没有任何记录」的事实，不是判定；
 * ③ 🔴 **缺值一律 `—`**：不折 0、不印 `undefined`、不编占位名（#5652 的口径）；
 * ④ 时刻按浏览器时区渲染，解析不出来 ⇒ `—`（不印 `Invalid Date`）。
 */

function rec(id: string, itemId: string, result: QualityInspectionRecord['result']): QualityInspectionRecord {
  return {
    id,
    order_item_id: itemId,
    processing_order_id: 'po-1',
    position_name: '布艺遮光帘A 米白',
    result,
    result_label: QUALITY_STATE_LABELS[result],
    reason: null,
    inspector_name: '质检员小李',
    inspected_at: '2026-10-17T10:00:00+08:00',
  }
}

describe('质检展示口径（lib/quality-check.ts）', () => {
  it('① 四态各有中文名与语义色（三态判定 + 一个「未检」事实）', () => {
    expect(QUALITY_STATE_LABELS).toEqual({
      pending: '未检',
      pass: '合格',
      rework: '返工',
      scrap: '报废',
    })
    // 🔴「未检」不得与「合格」共用一个色（否则屏幕上区分不开）
    expect(QUALITY_STATE_TONES.pending).not.toBe(QUALITY_STATE_TONES.pass)
    expect(QUALITY_STATE_TONES.pass).toBe('success')
    expect(QUALITY_STATE_TONES.rework).toBe('warning')
    expect(QUALITY_STATE_TONES.scrap).toBe('error')
    for (const state of ['pending', 'pass', 'rework', 'scrap'] as const) {
      expect(qualityStateChipClass(state).length).toBeGreaterThan(0)
    }
    expect(qualityStateLabel('pending')).toBe('未检')
  })

  it('② 判定标签优先用服务端下发的 result_label；缺键才本地兜底；未知 ⇒ —', () => {
    expect(qualityResultLabel('rework', '返工（复检）')).toBe('返工（复检）')
    expect(qualityResultLabel('scrap', null)).toBe('报废')
    expect(qualityResultLabel(null, null)).toBe('—')
    expect(qualityResultLabel('ok', null)).toBe('—')
  })

  it('③ 每件成品帘取**第一条**（读面已倒序 ⇒ 不重排），空输入 ⇒ 空表', () => {
    const records = [rec('qi-1', 'item-1', 'pass'), rec('qi-2', 'item-1', 'rework'), rec('qi-3', 'item-2', 'scrap')]
    const latest = latestByItem(records)
    expect(latest.get('item-1')?.id).toBe('qi-1')
    expect(latest.get('item-2')?.id).toBe('qi-3')
    expect(latestByItem([]).size).toBe(0)
    expect(latestByItem(null).size).toBe(0)
  })

  it('④ 成品帘名：商品名（色号）/ 只有其一时不拼空括号 / 都没有 ⇒ —', () => {
    expect(qualityItemName('布艺遮光帘A', '米白')).toBe('布艺遮光帘A（米白）')
    expect(qualityItemName('布艺遮光帘A', null)).toBe('布艺遮光帘A')
    expect(qualityItemName(null, '米白')).toBe('米白')
    expect(qualityItemName(null, null)).toBe('—')
    expect(qualityItemName('  ', '  ')).toBe('—')
  })

  it('⑤ 时刻：按浏览器时区渲染成 YYYY-MM-DD HH:mm；缺值 / 解析不出来 ⇒ —（不印 Invalid Date）', () => {
    const local = new Date(2026, 9, 17, 9, 5, 0)
    expect(formatMoment(local.toISOString())).toBe('2026-10-17 09:05')
    expect(formatMoment(null)).toBe('—')
    expect(formatMoment('')).toBe('—')
    expect(formatMoment('not-a-date')).toBe('—')
  })
})
