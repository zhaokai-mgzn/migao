// case_ids: UI-063
// @vitest-environment jsdom

import { describe, it, expect } from 'vitest'
import matrix from '@/lib/print-media.json'
import {
  PRINT_MEDIA_IDS,
  PRINT_MEDIA_SPECS,
  isContinuousFeed,
  printBodyFontPt,
  printMediaSpec,
  printPageRule,
  printUsableHeightMm,
  type PrintMediaSpec,
} from '@/lib/print-media'

/**
 * 打印**介质矩阵**（issue #5651）—— 介质是**参数**，不是复制粘贴出来的页面。
 *
 * 断言的是**矩阵本身的机器可判形态**（真值源 = `src/lib/print-media.json`）：
 * ① id 字面量清单与 JSON 的 id 集**逐字一致**（只改一边 ⇒ 红：否则新增介质会
 *    「矩阵里有、类型上没有」，调用方只能 `as any` 绕过类型）；
 * ② 每种介质的 `@page` 规则由 `printPageRule()` **唯一生成**（单据不得自写 `@page size`）；
 * ③ **三联纸的待实测登记必须存在**（用户 2026-09-26 裁定 241mm × 140mm 两等分；
 *    真机参数本机拿不到 ⇒ 通用参数 + 显式登记，**不编造精确值**）；
 * ④ 连续走纸的单联可用高度算得出来（= 页长 − 上下边距）—— 它是「不许跨联」的版面预算。
 *
 * ⚠️ 判据只读矩阵与纯函数，不读组件：组件侧的「切介质不产生第二份映射」由
 * `tests/unit/components/SalesDoc.test.tsx` + `tests/unit_ci_workflows/test_print_media_matrix_guard.py` 判。
 */
describe('打印介质矩阵（issue #5651）', () => {
  it('① id 字面量清单与 JSON 的 id 集逐字一致（只改一边 ⇒ 红）', () => {
    const fromJson = matrix.media.map((m) => m.id).sort()
    expect([...PRINT_MEDIA_IDS].sort()).toEqual(fromJson)
    // 反空跑：矩阵被清空/缩到 <3 ⇒ 本判据会空跑通过
    expect(fromJson.length).toBeGreaterThanOrEqual(3)
  })

  it('② 三种介质都在册，且技术/复写/连续走纸口径与 issue #5651 的矩阵表一致', () => {
    expect(matrix.media.map((m) => m.id)).toEqual(['a4', 'label-50x60', 'continuous-241x140'])
    const a4 = printMediaSpec('a4')
    expect(a4.technology).toBe('laser-inkjet')
    expect(a4.continuousFeed).toBe(false)
    expect(a4.carbonCopies).toBe(1)
    const label = printMediaSpec('label-50x60')
    expect(label.technology).toBe('thermal-transfer')
    expect(label.pageSize).toBe('50mm 60mm')
    const tri = printMediaSpec('continuous-241x140')
    expect(tri.technology).toBe('dot-matrix')
    expect(tri.continuousFeed).toBe(true)
    // 🔴 复写是**纸**的特性：一次打印即复写三份 ⇒ 软件只渲染一页（见 SalesDoc 的 DOM 判据）
    expect(tri.carbonCopies).toBe(3)
  })

  it('③ @page 规则由 printPageRule 唯一生成（三联纸 = 241mm 140mm，用户 2026-09-26 裁定）', () => {
    expect(printPageRule('a4')).toBe('@page { size: A4; margin: 12mm; }')
    expect(printPageRule('label-50x60')).toBe('@page { size: 50mm 60mm; margin: 0; }')
    expect(printPageRule('continuous-241x140')).toBe('@page { size: 241mm 140mm; margin: 6mm 12mm; }')
  })

  it('未知介质直接抛错（静默回落 = 把三联纸打成 A4 而不出声）', () => {
    // @ts-expect-error 故意传非法 id：必须抛，不许静默回落
    expect(() => printPageRule('a3')).toThrow(/未知打印介质/)
  })

  it('🔴 ③ 三联纸的**待实测**登记必须存在（红证：删掉 pendingMeasurements ⇒ 必红）', () => {
    const tri = printMediaSpec('continuous-241x140')
    expect(tri.measurement).toBe('pending-field-measurement')
    // 真机参数（走纸长度 / 边距 / 每行行高 / 最小字号）本机拿不到 ⇒ 逐项登记，不许留白
    expect(tri.pendingMeasurements.length).toBeGreaterThanOrEqual(3)
    for (const item of tri.pendingMeasurements) {
      expect(item.trim().length).toBeGreaterThan(5)
    }
    const joined = tri.pendingMeasurements.join('\n')
    for (const keyword of ['走纸长度', '边距', '行高', '字号']) {
      expect(joined).toContain(keyword)
    }
    // 有实测读数的介质则**不许**留待实测项（否则「待实测」会退化成永久标签）
    for (const id of ['a4', 'label-50x60'] as const) {
      expect(printMediaSpec(id).measurement).toBe('measured')
      expect(printMediaSpec(id).pendingMeasurements).toEqual([])
    }
  })

  it('④ 判据可红：删掉待实测登记 / 写坏 pageSize ⇒ 同一个判定函数必须判红', () => {
    /** 与守卫同口径的最小判定（注入式红证用；真实判定在 test_print_media_matrix_guard.py） */
    const problems = (spec: PrintMediaSpec): string[] => {
      const out: string[] = []
      if (spec.measurement !== 'measured' && spec.pendingMeasurements.length === 0) {
        out.push(`${spec.id}: 待实测介质没有登记待实测清单`)
      }
      if (!/^(A4|[0-9.]+mm( [0-9.]+mm)?)$/.test(spec.pageSize)) {
        out.push(`${spec.id}: pageSize 不是合法 CSS 尺寸：${spec.pageSize}`)
      }
      return out
    }
    const real = structuredClone(PRINT_MEDIA_SPECS['continuous-241x140']) as PrintMediaSpec
    expect(problems(real)).toEqual([])
    const noRegistry: PrintMediaSpec = { ...real, pendingMeasurements: [] }
    expect(problems(noRegistry)).not.toEqual([]) // 删掉登记 ⇒ 红
    const badSize: PrintMediaSpec = { ...real, pageSize: '241 x 140' }
    expect(problems(badSize)).not.toEqual([]) // 写坏纸型 ⇒ 红
  })

  it('④ 单联可用高度 = 页长 − 上下边距（连续纸「不许跨联」的版面预算）', () => {
    expect(printUsableHeightMm('continuous-241x140')).toBe(128)
    // 非连续 / 非 mm 尺寸 ⇒ null（**不猜**，不许把它当 A4 算）
    expect(printUsableHeightMm('a4')).toBeNull()
    expect(printUsableHeightMm('label-50x60')).toBe(60)
    expect(isContinuousFeed('continuous-241x140')).toBe(true)
    expect(isContinuousFeed('a4')).toBe(false)
    // 针打**不复用** A4 的字号预算（A4 的 6pt 量级在针打上会糊）
    expect(printBodyFontPt('continuous-241x140')).toBeGreaterThanOrEqual(printBodyFontPt('label-50x60'))
  })
})
