// case_ids: OR-034
/**
 * 跨端同源守卫：报价卡 `QuotationCard.tsx` 在 mini-app（C 端小布）/ bmini-app（B 端米宝）
 * **两份逐字节相同**。
 *
 * 病根（issue #4292，实测级）：两份文件改动前**逐字节相同**（`diff` 无输出），而 #4283 只修了
 * mini-app 那一份 ⇒ B 端报价卡仍只渲染理论褶倍（#4118 ④：客户自报 48 折时卡片显示
 * 「**2 倍褶皱 · 12.3 米面料**」，而实际 1.86 倍）—— **半边漂移发生了，且没有任何东西会变红**。
 *
 * 判据形态（与 `tests/unit_ci_workflows/test_craft_display_same_source.py` 的 C1 同族：
 * 三端同源副本用**逐字节相等**钉住，而不是靠人记得同步）：
 *
 * | # | 判据 | 红证（怎么让它红） |
 * |---|---|---|
 * | C1 | 两份 `QuotationCard.tsx` 逐字节相等 | 只改其中一份（本单的原始形态）⇒ 必红 |
 * | C2 | 两份都含实际褶倍的三个渲染语义片段 | 两份一起被清空/改写 ⇒ 必红（防 C1 空跑） |
 * | C3 | 两份文件都能读到 | 删/移动任一份 ⇒ 必红（路径漂移不得退化成静默跳过） |
 *
 * ⚠️ **不做成共享包**：issue #4292 明文「不合并两份组件为共享包」（跨 app 抽公共包是更大的重构，另议）。
 * 跨端重复文件的既有处置见 `src/utils/craft-display.ts` 文件头（「与 QuotationCard 等既有跨端重复文件同一处置」）。
 */
import { readFileSync } from 'fs'
import { join } from 'path'

/** 仓库根：`frontend/bmini-app/tests` 上溯三级 */
const REPO_ROOT = join(__dirname, '..', '..', '..')

/** 两份副本（唯一真相源 = 本守卫 + 上述文件头同步纪律） */
const COPIES = [
  'frontend/mini-app/src/components/cards/QuotationCard.tsx',
  'frontend/bmini-app/src/components/cards/QuotationCard.tsx',
] as const

/**
 * 非空锚点：实际褶倍渲染语义的三个关键片段（**类型字段 / 判定 / 文案**）。
 * 只锁「两份一样」不够 —— 两份一起被改没了同样满足相等 ⇒ 必须再钉住这条语义本身。
 */
const SEMANTIC_ANCHORS = [
  'fullness_actual?: number',
  'showActualFullness',
  '`（实际 ${data.fullness_actual} 倍）`',
] as const

/** 读一份副本；**读不到直接抛错**（C3：路径漂移 = 红，不得静默跳过） */
function readCopy(rel: string): string {
  try {
    return readFileSync(join(REPO_ROOT, rel), 'utf8')
  } catch {
    throw new Error(`副本不存在/不可读：${rel}（跨端同源守卫必须能读到它，路径漂移 = 红）`)
  }
}

describe('QuotationCard 跨端同源（issue #4292）', () => {
  it('C1：mini-app / bmini-app 两份 QuotationCard.tsx 逐字节相等', () => {
    const [cSide, bSide] = COPIES.map(readCopy)
    expect(bSide).toBe(cSide)
  })

  it('C2：两份都含实际褶倍的渲染语义关键片段（防两份一起被清空后 C1 空跑）', () => {
    for (const rel of COPIES) {
      const src = readCopy(rel)
      const missing = SEMANTIC_ANCHORS.filter((anchor) => !src.includes(anchor))
      expect({ file: rel, missing }).toEqual({ file: rel, missing: [] })
    }
  })
})
