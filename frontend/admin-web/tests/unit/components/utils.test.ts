// case_ids: UI-054
/**
 * `production-config/utils.tsx` —— 从 `ProcessConfigBoard` 拆出的**纯工具层**（issue #6585）。
 *
 * 它被判据门禁要求单测的原因不是「覆盖率好看」，而是这里面藏着**两条跨端一致性契约**
 * （选错行 = 改错价、收敛错行 = 界面上少一道工序），它们都不该只靠板子的端到端用例间接受守：
 *
 * 1. {@link pickConvergedCell} 的收敛规则必须与后端 `ProductionOperationQueryService#collapseToLogical`
 *    **同一把尺**（`position` 字典序 → `id` 升序）—— 两边选出不同行时，`PUT /operation-positions/{id}`
 *    改的就是**另一个价**（商家改 A 价、B 价变了）；
 * 2. {@link convergeByLogicalName} 收敛后必须**保留那一行的 `id`**（寻址键）且**保持服务端首次出现顺序**
 *    （`Map` 插入序）—— 前端重排会让行序抖、丢 id 会让写面找不到行。
 */
import { describe, expect, it } from 'vitest'
import {
  convergeByLogicalName,
  logicalNameOf,
  metaInconsistentOf,
  metaTextOf,
  money,
  pickConvergedCell,
  workshopLabel,
  workshopRank,
} from '@/components/production-config/utils'
import type { OperationPosition } from '@/types'

const cell = (over: Partial<OperationPosition> & { logical_name?: string | null }): OperationPosition =>
  ({ id: 'x', operation: '韩褶', position: '通用', ...over }) as unknown as OperationPosition

describe('money：金额一律两位小数，缺值**不吞成空**', () => {
  it('数值与数字串都按两位小数上屏', () => {
    expect(money(2.5)).toBe('¥2.50')
    expect(money('2.5')).toBe('¥2.50')
    expect(money(0)).toBe('¥0.00')
  })

  it('null / undefined / 空串 ⇒ ¥0.00（不是空串、不是 ¥NaN）', () => {
    expect(money(null)).toBe('¥0.00')
    expect(money(undefined)).toBe('¥0.00')
    expect(money('')).toBe('¥0.00')
  })
})

describe('logicalNameOf：逻辑工序名优先，缺省回落 operation', () => {
  it('有 logical_name ⇒ 用它（它是「同一道工序」的判据）', () => {
    expect(logicalNameOf(cell({ logical_name: '韩褶', operation: '韩褶-布' }))).toBe('韩褶')
  })

  it('老实例没给 logical_name（null / 缺键）⇒ 回落 operation，**不返回空串**', () => {
    expect(logicalNameOf(cell({ logical_name: null, operation: '打孔' }))).toBe('打孔')
    expect(logicalNameOf(cell({ operation: '打孔' }))).toBe('打孔')
  })
})

describe('pickConvergedCell：与后端 collapseToLogical **同一把尺**（选错行 = 改错价）', () => {
  it('单行 ⇒ 原样返回（连对象都是同一个，不做无谓拷贝）', () => {
    const only = cell({ id: 'p1' })
    expect(pickConvergedCell([only])).toBe(only)
  })

  it('多行 ⇒ position 字典序 → id 升序取首个（**不是**取数组第一个）', () => {
    const rows = [
      cell({ id: 'p3', position: '通用' }),
      cell({ id: 'p1', position: '通用' }),
      cell({ id: 'p0', position: '布帘' }),
    ]
    // position 字典序里「布帘」在「通用」之前 ⇒ 选 p0；若实现偷懒取数组首个会得到 p3 ⇒ 红
    expect(pickConvergedCell(rows).id).toBe('p0')
    const samePos = [cell({ id: 'p9' }), cell({ id: 'p2' })]
    expect(pickConvergedCell(samePos).id).toBe('p2')
  })

  it('不依赖入参顺序（同一把尺 ⇒ 打乱输入结果不变）', () => {
    const rows = [cell({ id: 'b' }), cell({ id: 'a' }), cell({ id: 'c' })]
    const shuffled = [rows[2], rows[0], rows[1]]
    expect(pickConvergedCell(rows).id).toBe('a')
    expect(pickConvergedCell(shuffled).id).toBe('a')
  })
})

describe('convergeByLogicalName：一行一道工序 + 保 id + 保服务端序', () => {
  it('同名多行收敛成一行，且**保留被选中那行的 id**（写面寻址键）', () => {
    const out = convergeByLogicalName([
      cell({ id: 'p2', logical_name: '韩褶' }),
      cell({ id: 'p1', logical_name: '韩褶' }),
      cell({ id: 'p5', logical_name: '打孔' }),
    ])
    expect(out.map((r) => r.id)).toEqual(['p1', 'p5'])
  })

  it('行序 = 服务端**首次出现**顺序（前端不重排）', () => {
    const out = convergeByLogicalName([
      cell({ id: 'p9', logical_name: '打孔' }),
      cell({ id: 'p1', logical_name: '韩褶' }),
      cell({ id: 'p8', logical_name: '打孔' }),
    ])
    expect(out.map((r) => logicalNameOf(r))).toEqual(['打孔', '韩褶'])
    expect(out.map((r) => r.id)).toEqual(['p8', 'p1'])
  })

  it('空输入 ⇒ 空数组（不发明行）', () => {
    expect(convergeByLogicalName([])).toEqual([])
  })
})

describe('车间分组正名与排序：认不出**原样返回**、排最后（不发明名字）', () => {
  it('认得出的前缀 ⇒ 行业正名（裁剪 / 车位 / 后整 / 质检）', () => {
    expect(workshopLabel('裁剪（裁床）')).toBe('裁剪（裁床）')
    expect(workshopLabel('车位（缝制）')).toBe('车位（缝制）')
    expect(workshopLabel('质检')).toBe('质检')
  })

  it('认不出的分组 ⇒ 原样返回（**不得**编一个名字）', () => {
    expect(workshopLabel('绣花')).toBe('绣花')
  })

  it('排序权重：认得出按表序、认不出排最后', () => {
    expect(workshopRank('裁剪（裁床）')).toBeLessThan(workshopRank('质检'))
    expect(workshopRank('绣花')).toBeGreaterThanOrEqual(workshopRank('其他'))
  })
})

describe('行尾元数据：不一致要**逐个列出**，不静默取第一个', () => {
  it('多个值 ⇒ 用 ` / ` 连接（「这道工序出现在两个分组里」不许消失）', () => {
    expect(metaTextOf(['车位 · 米', '后道 · 套'])).toBe('车位 · 米 / 后道 · 套')
  })

  it('查不到变体（空数组）⇒ `—`（不发明元数据）', () => {
    expect(metaTextOf([])).toBe('—')
    expect(metaInconsistentOf([])).toBe(false)
  })

  it('不一致判据 = 值多于一个', () => {
    expect(metaInconsistentOf(['a'])).toBe(false)
    expect(metaInconsistentOf(['a', 'b'])).toBe(true)
  })
})
