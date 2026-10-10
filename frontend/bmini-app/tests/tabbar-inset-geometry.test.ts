// case_ids: BM-030, BM-049
/**
 * 挂底栏的 tab 页要按条高留位（**几何读数**，issue #6666 判据 1）
 *
 * ## 判据口径（主会话钉死，别换成「有没有留 50px」）
 *
 * 取「**滚到底后最靠下的叶子文本** bottom」与「底栏 top」比：`> 0` ⇒ 那一行落在底栏之下
 * ⇒ 永久不可读。承载体 = `acceptance/2026-10-09-bmini-three-fixes/bmini-geometry-probe.mjs`
 * 的 `tabbarInset`（真 Chrome / 真页面 / API 全桩 / 390×844）。
 *
 * ## 本文件判什么、不判什么（§19.1）
 *
 * jsdom **不做布局** ⇒ 几何读数只能在真浏览器里取（上方探针）。本文件守的是那套读数的
 * **可复算入口**与**坏形态判别力**：① 探针真的量了「叶子文本 bottom vs 底栏 top」这一对读数；
 * ② 判据在坏形态（`padding-bottom: 24px`）下会红 —— 用内存注入自证，不靠人记。
 * ⇒ **不要**把本文件读成「布局已被机器验过」；几何读数记在
 * `acceptance/2026-10-10-bmini-6666/README.md`。
 */
import fs from 'fs'
import path from 'path'

const ROOT = path.resolve(__dirname, '..')
const PROBE = path.resolve(
  ROOT,
  '..',
  '..',
  'acceptance',
  '2026-10-09-bmini-three-fixes',
  'bmini-geometry-probe.mjs',
)

/** 判据本体：叶子文本 bottom 与底栏 top 比（> 0 ⇒ 被压） */
function coveredPx(lowestLeafBottom: number, tabbarTop: number): number {
  return +(lowestLeafBottom - tabbarTop).toFixed(1)
}

describe('几何判据「叶子文本 vs 底栏顶边」的判别力（issue #6666 判据 1）', () => {
  it('🔴 线上修前读数（390×844，数据页滚到底）⇒ 判红', () => {
    // 逐字照 2026-10-10 线上实测（探针 tabbarInset.dashboard）
    const before = { lowestLeafBottom: 799.5, tabbarTop: 794 }
    expect(coveredPx(before.lowestLeafBottom, before.tabbarTop)).toBeGreaterThan(0)
  })

  it('对照读数：内容不溢出的页面（「我的」页 退出登录 bottom=342.6）⇒ 不判红', () => {
    expect(coveredPx(342.6, 794)).toBeLessThanOrEqual(0)
  })

  it('注入历史坏形态（padding-bottom: 24px）⇒ 同一判据会红（不是空断言）', () => {
    // 修前页面高 = 100vh + 24 设计 px（内容盒）⇒ 滚到底后最后一行落到底栏之下
    const viewport = 844
    const barHeight = 50 // calc(50PX + env(safe-area-inset-bottom))，无安全区
    const reserved = 24 / 2 // 24 设计 px = 12 CSS px（本仓 750 设计宽，1px = 1/40 rem）
    const lastLineBottom = viewport - reserved
    expect(coveredPx(lastLineBottom, viewport - barHeight)).toBeGreaterThan(0)
  })

  it('注入修后形态（padding-bottom: calc(50PX + env(...))）⇒ 不红', () => {
    const viewport = 844
    const barHeight = 50
    const reserved = 50
    expect(coveredPx(viewport - reserved, viewport - barHeight)).toBeLessThanOrEqual(0)
  })
})

describe('几何读数必须可复算（探针在场 + 量了那一对读数）', () => {
  const probe = fs.existsSync(PROBE) ? fs.readFileSync(PROBE, 'utf-8') : ''

  it('探针文件存在（缺了 ⇒ 没有复算入口 ⇒ 红）', () => {
    expect(fs.existsSync(PROBE)).toBe(true)
  })

  it('探针量的是「最靠下的叶子文本 bottom」与「底栏 top」这一对（不是别的近似量）', () => {
    expect(probe).toContain('lowestLeaf')
    expect(probe).toContain('tabbarTop')
    expect(probe).toContain('lowestLeafCoveredPx')
  })
})
