// case_ids: UI-056
// 类级元守卫（issue #5558）：`src/components/ui/**` 里凡是 `inline-flex` 基类的原语，**都必须**带
// `whitespace-nowrap` —— 否则它在 flex 行里是可收缩项、min-content = 一个汉字 ⇒ 被压到 ~1 字宽，
// 标签在固定高度的盒子里竖排（用户实测「入库单页按钮样式不对」）。
//
// 为什么是元守卫而不是只钉 Button：本仓 2026-09 已有同族先例（UI-041 设置页开关缺 shrink-0 ⇒
// 轨道被压扁、圆钮溢出）。「flex 行里的原语缺几何保护」是一类，不是一处：
// 发现规则是**机械的**（扫源码里有没有 `inline-flex`），新原语漏了即红，不靠人记得登记。
//
// 效果层几何由 `tests/e2e/specs/warehouse/inbound-orders-button-geometry.spec.ts`（Playwright
// boundingBox + 内容溢出）守；本判据守的是**每一次 PR**（admin-web 单测面）就能拦住的那一层。
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'fs'
import { join } from 'path'

const UI_DIR = join(process.cwd(), 'src/components/ui')

/**
 * 豁免台账（**只许缩短**）：登记「命中规则但确有必要」的文件名。
 * 当前为空 —— 空台账也要有腐坏检查（登记的条目必须仍然命中规则，否则就是死条目）。
 */
const EXEMPT: string[] = []

describe('UI 原语换行守卫（issue #5558）', () => {
  const files = readdirSync(UI_DIR).filter((f) => f.endsWith('.tsx'))
  const sourceOf = (f: string) => readFileSync(join(UI_DIR, f), 'utf-8')
  const inlineFlexPrimitives = files.filter((f) => sourceOf(f).includes('inline-flex'))

  it('普查面非空且覆盖已知原语（改名/搬走 ⇒ 本判据先红，而不是静默空跑）', () => {
    expect(files.length, 'ui 目录下应有一批原语（扫不到 ⇒ 判据在扫空气）').toBeGreaterThanOrEqual(10)
    for (const known of ['Button.tsx', 'Badge.tsx', 'StatusBadge.tsx']) {
      expect(inlineFlexPrimitives, `${known} 应命中 inline-flex 规则`).toContain(known)
    }
  })

  it('每个 inline-flex 原语都带 whitespace-nowrap（缺了 ⇒ 窄容器里标签竖排）', () => {
    const offenders = inlineFlexPrimitives.filter(
      (f) => !EXEMPT.includes(f) && !sourceOf(f).includes('whitespace-nowrap'),
    )
    expect(
      offenders,
      `这些原语缺 whitespace-nowrap（flex 行里会被压到 min-content、标签竖排）：${offenders.join('、')}。`
        + '出口：在它的基类 className 里补 whitespace-nowrap（Badge/StatusBadge 已有先例）。',
    ).toEqual([])
  })

  it('豁免台账不得腐坏（登记的文件必须仍然命中规则）', () => {
    for (const f of EXEMPT) {
      expect(inlineFlexPrimitives, `豁免条目 ${f} 已不命中规则 ⇒ 死条目，请删除`).toContain(f)
    }
  })
})