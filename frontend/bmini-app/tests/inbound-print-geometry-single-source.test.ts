// case_ids: BM-010
/**
 * **50×30mm 标签的像素口径：单一真值 + 逐值正确**（issue #5052 P3；设计 §7.2 / 验收判据 7）
 *
 * ## 为什么这条要单独成守卫
 *
 * 「同一物理口径出现第二份字面量」是本仓被点过名的形态：400 / 384 / 240 一旦在 bmini 的渲染器里
 * 再抄一份，**改纸型不会跟着改渲染器**（或反过来），而两边**都不会报错** —— 打出来的标签
 * 尺寸错、二维码被非整数倍重采样糊掉，直到工人扫不出来才发现。
 *
 * ## 真值在哪
 *
 * `frontend/admin-web/src/lib/print-media.json`（#5651 的打印介质矩阵是**唯一**机器可读真值源）；
 * bmini 侧由 `frontend/bmini-app/src/utils/inbound/truth.ts` **跨工程直接 import**（不复制、
 * 不做构建期拷贝）。本守卫钉四件事：
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | C1 | 逐值正确 + **派生关系自洽**（8 dots/mm × 50/48/30mm） | 把 `effectiveWidthPx` 改成 400 ⇒ 红 |
 * | C2 | **全仓只有一处**同时写着 384 与 240（= 介质矩阵自己） | 在渲染器里复制一份 `384/240` ⇒ 红 |
 * | C3 | 渲染/版面模块源码里**不出现**这组像素字面量（只能从 `truth` 取） | 同上（C3 会点名文件） |
 * | C4 | 判据本身能红（注入式：改坏真值 ⇒ 同一个判定函数判红） | 注入未生效 ⇒ 红（空断言） |
 *
 * ⚠️ C2 的语料**排除本文件自己**（`migao-dev-flow` §23.8 B1：判据语料必须排除判据自身，
 * 否则断言里的数字会把探针数成违规 ⇒ 判据永远是红的或永远抓不到真违规）。
 */
import fs from 'fs'
import path from 'path'
import {
  INBOUND_LABEL_MEDIA_ID,
  inboundLabelCodeUrl,
  inboundLabelGeometry,
  inboundLabelMedia,
} from '../src/utils/inbound/truth'
import { labelCodePayload, isValidShortCode } from '../src/utils/inbound/shortCode'
import { stripComments } from './helpers/h5PlatformLists'

/** `<repo>`（本文件在 `frontend/bmini-app/tests/`） */
const REPO_ROOT = path.join(__dirname, '..', '..', '..')
const MATRIX_REL = 'frontend/admin-web/src/lib/print-media.json'
/** 判据自身（B1）：它必须写出 384 / 240 才能断言它们 —— 不能把自己数成违规 */
const GUARD_REL = 'frontend/bmini-app/tests/inbound-print-geometry-single-source.test.ts'
/** 版面/渲染模块：这两个文件里**一个像素字面量都不许有** */
const RENDER_FILES = [
  'frontend/bmini-app/src/utils/inbound/labelLayout.ts',
  'frontend/bmini-app/src/utils/inbound/labelCanvas.ts',
  'frontend/bmini-app/src/utils/inbound/truth.ts',
]
const CODE_EXT = /\.(ts|tsx|js|jsx|mjs|json)$/
const SKIP_DIRS = new Set(['node_modules', 'dist', 'coverage', '.next', 'build', '.git'])

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith('.') && entry.name !== '.github') continue
    if (SKIP_DIRS.has(entry.name)) continue
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(full, out)
    else if (CODE_EXT.test(entry.name)) out.push(full)
  }
  return out
}

/** 全仓（frontend + backend）代码文件里，**同时**出现 `384` 与 `240` 的那些（相对路径） */
function filesWithBothPixelLiterals(): string[] {
  const hits: string[] = []
  for (const root of ['frontend', 'backend']) {
    const abs = path.join(REPO_ROOT, root)
    if (!fs.existsSync(abs)) continue
    for (const file of walk(abs)) {
      const rel = path.relative(REPO_ROOT, file)
      if (rel === GUARD_REL) continue
      const code = stripComments(fs.readFileSync(file, 'utf8'))
      if (/\b384\b/.test(code) && /\b240\b/.test(code)) hits.push(rel)
    }
  }
  return hits.sort()
}

/** 与 C1 同口径的纯判定（供注入式红证复用；真实判据 = 上面的断言） */
function geometryProblems(geometry: {
  dpi: number
  dotsPerMm: number
  widthPx: number
  effectiveWidthPx: number
  heightPx: number
}): string[] {
  const problems: string[] = []
  if (geometry.dpi !== 203) problems.push(`dpi=${geometry.dpi}（目标机口径 203dpi）`)
  if (geometry.dotsPerMm !== 8) problems.push(`dotsPerMm=${geometry.dotsPerMm}（203dpi ⇒ 8 dots/mm）`)
  if (geometry.widthPx !== geometry.dotsPerMm * 50) problems.push('widthPx ≠ dotsPerMm × 50mm')
  if (geometry.effectiveWidthPx !== geometry.dotsPerMm * 48) problems.push('effectiveWidthPx ≠ dotsPerMm × 48mm')
  if (geometry.heightPx !== geometry.dotsPerMm * 30) problems.push('heightPx ≠ dotsPerMm × 30mm')
  if (geometry.effectiveWidthPx > geometry.widthPx) problems.push('有效打宽 > 纸宽（物理上不成立）')
  return problems
}

describe('50×30mm 标签像素口径：单一真值（issue #5052 P3）', () => {
  it('C1 逐值正确，且与 mm↔dots 的派生关系自洽（不是四个孤立的数）', () => {
    const geometry = inboundLabelGeometry()
    expect(geometryProblems(geometry)).toEqual([])
    expect(inboundLabelMedia().pageSize).toBe('50mm 30mm')
    expect(inboundLabelMedia().pageMargin).toBe('0')
    // 画布 = **有效打宽 × 纸高**（安全侧：DP30S 有效打宽未核实，见设计 §8.5 ④）
    expect(geometry.canvasWidthPx).toBe(geometry.effectiveWidthPx)
    expect(geometry.canvasHeightPx).toBe(geometry.heightPx)
  })

  it('C1 真值源里 50×30 是**待实测**介质（真机参数没核实 ⇒ 不许写成 measured）', () => {
    const spec = inboundLabelMedia()
    expect(spec.id).toBe(INBOUND_LABEL_MEDIA_ID)
    expect(spec.measurement).toBe('pending-field-measurement')
    expect((spec.pendingMeasurements || []).length).toBeGreaterThanOrEqual(3)
    expect((spec.pendingMeasurements || []).join('\n')).toContain('有效打印宽度')
  })

  it('C2 全仓只有一处同时写着这组像素口径（= 介质矩阵；别处复制 ⇒ 红）', () => {
    expect(filesWithBothPixelLiterals()).toEqual([MATRIX_REL])
  })

  it('C3 版面/渲染模块里没有像素字面量（只能从 truth 取）', () => {
    const offenders: string[] = []
    for (const rel of RENDER_FILES) {
      const code = stripComments(fs.readFileSync(path.join(REPO_ROOT, rel), 'utf8'))
      for (const literal of [/\b400\b/, /\b384\b/, /\b240\b/]) {
        if (literal.test(code)) offenders.push(`${rel} → ${literal}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('C4 注入式红证：改坏真值 ⇒ 同一个判定函数必须判红（判据不是空断言）', () => {
    const real = inboundLabelGeometry()
    expect(geometryProblems(real)).toEqual([])
    // 注入 A：有效打宽被写成纸宽（"反正机器应该能打满" 这个想当然）
    expect(geometryProblems({ ...real, effectiveWidthPx: real.widthPx })).not.toEqual([])
    // 注入 B：dots/mm 漂到 8.47（有人按 215dpi 算过）
    expect(geometryProblems({ ...real, dotsPerMm: 8.47 })).not.toEqual([])
    // 注入 C：高度按 32mm 画（报错方向也要能红）
    expect(geometryProblems({ ...real, heightPx: 256 })).not.toEqual([])
  })

  it('C5 码形态一次定死：https://app.migaozn.com/i/<短码>（缺码 ⇒ null，不编造）', () => {
    expect(inboundLabelCodeUrl('ABCD2345')).toBe('https://app.migaozn.com/i/ABCD2345')
    expect(labelCodePayload('abcd2345')).toBe('https://app.migaozn.com/i/ABCD2345')
    expect(labelCodePayload(null)).toBeNull()
    expect(labelCodePayload('')).toBeNull()
    // 脏码（长度不对 / 含生成面不产出的 I L O U）⇒ 同样按缺码处置，绝不拼出一个"能扫但错的"URL
    expect(labelCodePayload('ABCD234')).toBeNull()
    expect(labelCodePayload('ABCD23456')).toBeNull()
    expect(labelCodePayload('ABCDI234')).toBeNull()
    expect(labelCodePayload('ABCDO234')).toBeNull()
    expect(isValidShortCode('ABCD2345')).toBe(true)
    expect(isValidShortCode('ABCDI234')).toBe(false)
  })
})
