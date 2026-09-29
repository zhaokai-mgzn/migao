// case_ids: BM-010
/**
 * **30×40mm 标签的像素口径：单一真值 + 逐值正确**（issue #5052 CP-1；设计 §7.2 / 验收判据 7）
 *
 * ## 为什么这条要单独成守卫
 *
 * 「同一物理口径出现第二份字面量」是本仓被点过名的形态：240 / 320 / 384 一旦在 bmini 的渲染器里
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
 * | C1 | 逐值正确 + **派生关系自洽**（8 dots/mm × 30mm 纸宽 / 40mm 纸高 / 48mm 头宽） | 把 `headWidthPx` 改成 240 ⇒ 红 |
 * | C2 | 🔴 **任一份**像素口径字面量都只许来自真值源：出图链路里 400 / 384 / 240 **一个都不许有** | 在 `labelPageKit.ts` 写一行 `const x = 384`（**只写 384**）⇒ 红 |
 * | C2b | 全仓范围内 `384`（打印头宽）只出现在介质矩阵（另外两个数与无关业务重号，口径见下） | 别处复制一份 `headWidthPx = 384` ⇒ 红 |
 * | C3 | 渲染/版面模块源码里**不出现**这组像素字面量（只能从 `truth` 取） | 同上（C3 会点名文件） |
 * | C4 | 判据本身能红（注入式：改坏真值 ⇒ 同一个判定函数判红） | 注入未生效 ⇒ 红（空断言） |
 *
 * ⚠️ C2 的语料**排除本文件自己**（`migao-dev-flow` §23.8 B1：判据语料必须排除判据自身，
 * 否则断言里的数字会把探针数成违规 ⇒ 判据永远是红的或永远抓不到真违规）。
 *
 * ⚠️ **D5 修复的口径变化（照实登记，不粉饰）**：旧 C2 的谓词是「**同时**出现 384 与 240」——
 * 于是**只写一个数**的第二份字面量会静默落地（验收方 L1 实测：在 `labelPageKit.ts` 追加
 * `const __probeWidthPx = 384` ⇒ 旧判据 6/6 全绿）。现在改成**逐字面量**判。
 * 而"逐字面量扫全仓"只对 `384` 成立：`240` 与 `400` 在无关业务里合法重号
 * （`frontend/admin-web/src/components/dashboard/TrendChart.tsx` 的图表高度 = 240；
 * HTTP 400 遍布各处）⇒ 这两个数的**全仓**白名单会造大量假红，故收窄到**出图链路**内判
 * （那正是"第二份像素口径"会落地的地方，也正是旧口径漏掉的地方）。
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
/** **出图链路**：标签版面 / 渲染 / 画布 / 两个工人页 —— 这里一个像素字面量都不许有 */
const PIPELINE_DIRS = [
  'frontend/bmini-app/src/utils/inbound',
  'frontend/bmini-app/src/pages/worker',
]
/** 像素口径字面量（**分别**判，不再是"两个数同时出现才算"） */
const PIXEL_LITERALS = [240, 320, 384]
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

/**
 * 逐字面量判定（真判据与注入式红证**共用同一份**）：
 * 每个数字**各自**统计，凡它出现在 `allow` 之外的文件 ⇒ 点名。
 */
function pixelLiteralProblems(
  files: { rel: string; code: string }[],
  literals: number[] = PIXEL_LITERALS,
  allow: string[] = [],
): string[] {
  const problems: string[] = []
  for (const file of files) {
    if (file.rel === GUARD_REL) continue
    const code = stripComments(file.code)
    for (const literal of literals) {
      if (new RegExp(`\\b${literal}\\b`).test(code) && !allow.includes(file.rel)) {
        problems.push(`${file.rel}: 自带像素口径字面量 ${literal}（只能从真值源 ${MATRIX_REL} 取）`)
      }
    }
  }
  return problems
}

/** 读某组根目录下的全部代码文件（相对仓库根） */
function readCorpus(roots: string[]): { rel: string; code: string }[] {
  const out: { rel: string; code: string }[] = []
  for (const root of roots) {
    const abs = path.join(REPO_ROOT, root)
    if (!fs.existsSync(abs)) continue
    if (fs.statSync(abs).isFile()) {
      out.push({ rel: root, code: fs.readFileSync(abs, 'utf8') })
      continue
    }
    for (const file of walk(abs)) {
      out.push({ rel: path.relative(REPO_ROOT, file), code: fs.readFileSync(file, 'utf8') })
    }
  }
  return out
}

/** 与 C1 同口径的纯判定（供注入式红证复用；真实判据 = 上面的断言） */
function geometryProblems(geometry: {
  dpi: number
  dotsPerMm: number
  widthPx: number
  effectiveWidthPx: number
  headWidthPx: number
  heightPx: number
}): string[] {
  const problems: string[] = []
  if (geometry.dpi !== 203) problems.push(`dpi=${geometry.dpi}（目标机口径 203dpi）`)
  if (geometry.dotsPerMm !== 8) problems.push(`dotsPerMm=${geometry.dotsPerMm}（203dpi ⇒ 8 dots/mm）`)
  if (geometry.widthPx !== geometry.dotsPerMm * 30) problems.push('widthPx ≠ dotsPerMm × 30mm')
  if (geometry.heightPx !== geometry.dotsPerMm * 40) problems.push('heightPx ≠ dotsPerMm × 40mm')
  if (geometry.headWidthPx !== geometry.dotsPerMm * 48) problems.push('headWidthPx ≠ dotsPerMm × 48mm')
  // 有效打宽 = min(纸宽, 打印头宽)：30mm 纸 < 48mm 头 ⇒ 整幅可打（240px）
  if (geometry.effectiveWidthPx !== Math.min(geometry.widthPx, geometry.headWidthPx)) {
    problems.push('effectiveWidthPx ≠ min(纸宽, 打印头宽)')
  }
  if (geometry.effectiveWidthPx > geometry.widthPx) problems.push('有效打宽 > 纸宽（物理上不成立）')
  return problems
}

describe('30×40mm 标签像素口径：单一真值（issue #5052 CP-1）', () => {
  it('C1 逐值正确，且与 mm↔dots 的派生关系自洽（不是几个孤立的数）', () => {
    const geometry = inboundLabelGeometry()
    expect(geometryProblems(geometry)).toEqual([])
    expect(inboundLabelMedia().pageSize).toBe('30mm 40mm')
    expect(inboundLabelMedia().pageMargin).toBe('0')
    // 画布 = **有效打宽 × 纸高**（30mm 纸 < 48mm 头 ⇒ 有效打宽 = 纸宽，整幅可打）
    expect(geometry.canvasWidthPx).toBe(geometry.effectiveWidthPx)
    expect(geometry.canvasHeightPx).toBe(geometry.heightPx)
  })

  it('C1 真值源里 30×40 是**待实测**介质（真机参数没核实 ⇒ 不许写成 measured）', () => {
    const spec = inboundLabelMedia()
    expect(spec.id).toBe(INBOUND_LABEL_MEDIA_ID)
    expect(spec.measurement).toBe('pending-field-measurement')
    expect((spec.pendingMeasurements || []).length).toBeGreaterThanOrEqual(3)
    expect((spec.pendingMeasurements || []).join('\n')).toContain('有效打印宽度')
  })

  it('C2 出图链路里**一个**像素字面量都没有（240 / 320 / 384 逐个数，不放过"只写一个"）', () => {
    const pipeline = readCorpus(PIPELINE_DIRS)
    // 反空跑：射程真的扫到了出图链路的源码
    expect(pipeline.length).toBeGreaterThanOrEqual(10)
    expect(pixelLiteralProblems(pipeline)).toEqual([])
  })

  it('C2 🔴 红证：链路里写第二份像素字面量 ⇒ 判红（**只写 384** 也算，这正是旧口径漏掉的形态）', () => {
    // ① 坏形态作为**同一判定**的入参（复核方 L1 实测的注入：只写 384、不写 240）
    const injected = [
      { rel: 'frontend/bmini-app/src/utils/inbound/labelPageKit.ts', code: 'export const __probeWidthPx = 384\n' },
    ]
    const problems = pixelLiteralProblems(injected).join('\n')
    expect(problems).toContain('labelPageKit.ts')
    expect(problems).toContain('384')
    // 只写 240 / 只写 320 也各自命中（旧口径在这两种形态下同样恒绿）
    expect(pixelLiteralProblems([{ rel: 'a.ts', code: 'const h = 240\n' }]).join('\n')).toContain('240')
    expect(pixelLiteralProblems([{ rel: 'a.ts', code: 'const h = 320\n' }]).join('\n')).toContain('320')
    // ② 对照：真仓库的出图链路下同一判定判绿（否则上面那条"红"可能只是读错了语料）
    expect(pixelLiteralProblems(readCorpus(PIPELINE_DIRS))).toEqual([])
  })

  it('C2b 全仓 `384`（打印头宽）只许出现在介质矩阵（240/320 与无关业务重号，故按链路判，口径见文件头）', () => {
    const problems = pixelLiteralProblems(readCorpus(['frontend', 'backend']), [384], [MATRIX_REL])
    expect(problems).toEqual([])
    // 反空跑：真值源里**确实**写着这个数（否则"全仓 0 命中"会假绿）
    expect(readCorpus([MATRIX_REL]).some((file) => /\b384\b/.test(file.code))).toBe(true)
  })

  it('C3 版面/渲染模块里没有像素字面量（只能从 truth 取）', () => {
    const offenders: string[] = []
    for (const rel of RENDER_FILES) {
      const code = stripComments(fs.readFileSync(path.join(REPO_ROOT, rel), 'utf8'))
      for (const literal of [/\b240\b/, /\b320\b/, /\b384\b/]) {
        if (literal.test(code)) offenders.push(`${rel} → ${literal}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('C4 注入式红证：改坏真值 ⇒ 同一个判定函数必须判红（判据不是空断言）', () => {
    const real = inboundLabelGeometry()
    expect(geometryProblems(real)).toEqual([])
    // 注入 A：有效打宽被写成**比纸宽还大**（"反正机器应该能打满"这个想当然）
    expect(geometryProblems({ ...real, effectiveWidthPx: real.widthPx + real.dotsPerMm })).not.toEqual([])
    // 注入 B：dots/mm 漂到 8.47（有人按 215dpi 算过）
    expect(geometryProblems({ ...real, dotsPerMm: 8.47 })).not.toEqual([])
    // 注入 C：高度按 32mm 画（报错方向也要能红）
    expect(geometryProblems({ ...real, heightPx: 256 })).not.toEqual([])
    // 注入 D：打印头宽按 30mm 记（= 把纸宽当成头宽）⇒ 派生关系不再自洽
    expect(geometryProblems({ ...real, headWidthPx: real.widthPx })).not.toEqual([])
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
