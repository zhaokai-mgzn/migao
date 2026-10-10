// case_ids: UI-056
/**
 * 几何判据（issue #6668 盲区③）：**条高 / 被常驻面遮住 / 主控件高度 / 首屏被常驻面占掉**。
 *
 * ## 为什么 jsdom 判不了、本文件判什么
 *
 * jsdom **不做布局** ⇒ 真几何只能在真浏览器里取。复算入口 =
 * `acceptance/2026-10-10-admin-web-6668/admin-web-geometry-probe.mjs`（真 Chrome / 1440×980 /
 * 滚到底后取读数）。本文件守的是**那套读数的入口与判别力**（同族先例 =
 * `frontend/bmini-app/tests/tabbar-inset-geometry.test.ts`）：
 *
 * 1. **探针在场**（删掉 ⇒ 没有复算入口 ⇒ 红）；
 * 2. **探针仍量着那四对读数**（选择器 / 判据函数不被悄悄改掉）；
 * 3. **四个判据函数在坏形态上各自判红、在好形态上放行**（内存注入，不靠人记）；
 * 4. **阈值与基线文档逐值一致**（文档说 36 而探针用 40 ⇒ 红）。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 🔴 **本包没有跑真浏览器**（本机没起 `:3001`）⇒ 本文件**不等于**"几何已验过"。
 *   真读数必须由验收会话跑一次探针（命令写在
 *   `acceptance/2026-10-10-admin-web-6668/README.md`），登记为**未跑项**；
 * - 探针的射程 = 桌面商家后台三个代表页（`/dashboard` `/orders` `/production/pool`）；
 *   `worker-h5` / Taro 两个触屏门面**不在本探针射程**（它们另有 `bmini-geometry-probe.mjs`）；
 * - 不改任何门禁的通过条件、不新增 required check。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

import {
  GEOMETRY_LIMITS,
  VIEWPORT,
  PERSISTENT_FACE_SELECTOR,
  TAP_TARGET_SELECTOR,
  checkBarHeight,
  checkFirstScreen,
  checkOcclusion,
  checkTapTarget,
  firstScreenShare,
  judge,
  occludedPx,
} from '../../../../acceptance/2026-10-10-admin-web-6668/admin-web-geometry-probe.mjs'

const ROOT = process.cwd()
const REPO = join(ROOT, '..', '..')
const PROBE = join(REPO, 'acceptance/2026-10-10-admin-web-6668/admin-web-geometry-probe.mjs')
const BASELINE = join(REPO, 'docs/design/design-baseline.md')

describe('几何读数必须可复算（探针在场 + 量的还是那四对读数）', () => {
  const probe = existsSync(PROBE) ? readFileSync(PROBE, 'utf-8') : ''

  it('探针文件在场（缺了 ⇒ 没有复算入口 ⇒ 红）', () => {
    expect(existsSync(PROBE), `缺 ${PROBE}`).toBe(true)
  })

  it('探针仍量着四条读数（选择器 / 判据函数名都不许被悄悄改掉）', () => {
    for (const anchor of [
      'tapTargets',
      'bars',
      'leafBottom',
      PERSISTENT_FACE_SELECTOR.split(',')[0].trim(), // header
      TAP_TARGET_SELECTOR.split(',')[0].trim(), // button
    ]) {
      expect(probe, `探针里找不到「${anchor}」`).toContain(anchor)
    }
  })

  it('探针把「浮在内容之上的面」与文档流里的面分开（否则顶栏恒被判遮挡）', () => {
    expect(probe).toContain('浮在内容之上')
    expect(probe).toContain('b.overlays &&')
  })

  it('探针声明的视口是 1440×980（与 §15.7 的读图口径一致）', () => {
    expect(VIEWPORT).toEqual({ width: 1440, height: 980 })
  })
})

describe('四条几何判据的判别力（注入式，各自判红 / 好形态放行）', () => {
  it('① 主控件高度：24px 判红、36px 放行（36 = `h-9`，与 Button/Input 逐字一致）', () => {
    expect(checkTapTarget({ width: 100, height: 24, top: 0, bottom: 24 })).toBe(false)
    expect(checkTapTarget({ width: 100, height: 36, top: 0, bottom: 36 })).toBe(true)
    expect(GEOMETRY_LIMITS.minControlHeight).toBe(36)
  })

  it('② 常驻面高度：140px 判红、64px 放行（上限 96 = §31 P1 的常驻面克制）', () => {
    expect(checkBarHeight({ width: 1440, height: 140, top: 0, bottom: 140 })).toBe(false)
    expect(checkBarHeight({ width: 1440, height: 64, top: 0, bottom: 64 })).toBe(true)
    expect(GEOMETRY_LIMITS.maxBarHeight).toBe(96)
  })

  it('③ 被常驻面压住：799.5 vs 794 判红（同族先例的真机读数）、342.6 vs 794 放行', () => {
    expect(occludedPx(799.5, 794)).toBeCloseTo(5.5, 1)
    expect(checkOcclusion(799.5, 794)).toBe(true)
    expect(checkOcclusion(342.6, 794)).toBe(false)
  })

  it('④ 首屏占比：三条常驻面 64+120+48 ⇒ 23.7% 放行；64+300+80 ⇒ 45.3% 判红', () => {
    expect(firstScreenShare([64, 120, 48])).toBeCloseTo(0.2367, 3)
    expect(checkFirstScreen([64, 120, 48])).toBe(true)
    expect(checkFirstScreen([64, 300, 80])).toBe(false)
  })

  it('综合判据 `judge`：坏形态逐条具名报出、好形态零报错（不是恒红 / 恒绿）', () => {
    const bad = judge(
      {
        tapTargets: [{ tag: 'button', text: '查', width: 24, height: 24 }],
        bars: [{ selector: 'header', overlays: true, width: 1440, height: 140, top: 0, bottom: 140 }],
        leafBottom: 900,
        viewport: { w: 1440, h: 980 },
      },
      '/x',
    )
    expect(bad.join('\n')).toContain('GE-control-height')
    expect(bad.join('\n')).toContain('GE-bar-height')
    expect(bad.join('\n')).toContain('GE-occlusion')

    const good = judge(
      {
        tapTargets: [{ tag: 'button', text: '查询', width: 80, height: 36 }],
        bars: [{ selector: 'header', overlays: false, width: 1440, height: 64, top: 0, bottom: 64 }],
        leafBottom: 700,
        viewport: { w: 1440, h: 980 },
      },
      '/x',
    )
    expect(good).toEqual([])
  })

  it('文档流里的顶栏不判遮挡（对照读数：只有 overlays 的面才判）', () => {
    const docFlow = judge(
      { tapTargets: [], bars: [{ selector: 'header', overlays: false, height: 64, top: 0, bottom: 64 }], leafBottom: 900, viewport: { w: 1440, h: 980 } },
      '/x',
    )
    expect(docFlow).toEqual([])
  })
})

describe('阈值与基线文档逐值一致（文档说 36 而探针用 40 ⇒ 红）', () => {
  const baseline = readFileSync(BASELINE, 'utf-8')

  it('基线文档在场且声明了真值源', () => {
    expect(baseline).toContain('tailwind.config.ts')
  })

  it.each([
    ['主控件高度下限', String(GEOMETRY_LIMITS.minControlHeight)],
    ['常驻面高度上限', String(GEOMETRY_LIMITS.maxBarHeight)],
    ['首屏占比上限', String(GEOMETRY_LIMITS.maxFirstScreenShare)],
    ['触屏触达区下限', String(GEOMETRY_LIMITS.minTapTarget)],
  ])('基线文档写明了「%s」= %s', (_name, value) => {
    expect(baseline, `基线文档缺 ${value}`).toContain(value)
  })

  it('基线文档把「谁守这段几何」指到探针与判据（不是复制一份阈值就完事）', () => {
    expect(baseline).toContain('acceptance/2026-10-10-admin-web-6668/admin-web-geometry-probe.mjs')
    expect(baseline).toContain('frontend/admin-web/tests/unit/design-baseline-geometry.test.ts')
  })
})
