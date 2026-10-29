#!/usr/bin/env node
/**
 * 验收证据脚本：**同一次出纸里两种纸高并存**（issue #8107）。
 *
 * ## 它回答的问题
 *
 * 用户 2026-10-29 逐字：「余料带回和绑带的水洗唛打印功能中，用户反馈打印的信息太多了，可以适当删减，
 * 保留货号，门幅，宽高，工艺和特殊选项 + 二维码即可」「把长度再缩减一些，能放下以上信息即可」。
 * 专属唛因此改用**短纸 50mm × 100mm**，而常规唛仍是 50mm × 140mm —— 两种纸长 = **两种标签纸**，
 * 但**同一次打印任务**里要并存。技术承载 = CSS **命名页**：
 *
 *   @page          { size: 50mm 140mm; margin: 0 }   ← 常规唛
 *   @page wash-label-option { size: 50mm 100mm; margin: 0 } ← 专属唛
 *   .task-card-label         { height: 140mm; … }
 *   .task-card-label--option { height: 100mm; page: wash-label-option; }
 *
 * 本脚本用 Chromium 按 `preferCSSPageSize: true` 出 PDF，**逐页读 MediaBox**，
 * 断言两页分别是 50mm × 140mm 与 50mm × 100mm（±0.5mm）。
 *
 * ## 边界（照实登记，别把它当"打印机验收"）
 *
 * - 这不是**真机热敏打印**读数：真机要各自登记两张自定义纸型、并且**真的换纸卷**；
 *   驱动侧的纸型登记与走纸精度本脚本量不到。
 * - 校验的是「Chromium 接受混合页高并逐页按命名页分页」这一条**浏览器事实**，
 *   以及两份纸型在 CSS 里指向**两个不同的尺寸**（同一张纸 ⇒ 断言当场红）。
 * - 与 `.task-card-label` 的同值项（宽度 / padding / 字号 / 二维码）本脚本不复刻判据 ——
 *   那些由 `frontend/admin-web/tests/unit/lib/label-print/wash-label-metrics.test.ts` 逐值钉住。
 *
 * ## 复算
 *
 *   node acceptance/2026-10-29-8107-option-label/verify.mjs
 *
 * 依赖：本仓 `tests/package.json` 的 `playwright`（`@playwright/test` 的同源包）+ 已安装的 chromium。
 * worktree 里没装 `tests/node_modules` 时按下面的候选列表回落（同一仓库、同一份 package-lock）。
 */
import { createRequire } from 'node:module'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(HERE, '../..')

/** playwright 的解析候选（本 worktree → 同仓主工作区；可用 PLAYWRIGHT_MODULE 覆盖） */
function loadPlaywright() {
  const candidates = [
    process.env.PLAYWRIGHT_MODULE,
    join(REPO_ROOT, 'tests/node_modules/playwright'),
    // worktree 里没装 tests 依赖时，复用同一仓库主工作区的依赖（同 package-lock、同版本）
    '/Users/guangzhen.zk/ai native/migao/tests/node_modules/playwright',
  ].filter(Boolean)
  const tried = []
  for (const candidate of candidates) {
    if (!existsSync(candidate)) {
      tried.push(`${candidate}（不存在）`)
      continue
    }
    try {
      const require = createRequire(candidate + '/')
      return { module: require(candidate), from: candidate, tried }
    } catch (error) {
      tried.push(`${candidate}（${error.message}）`)
    }
  }
  throw new Error(`取不到 playwright —— 未硬编任何读数。已尝试：\n  ${tried.join('\n  ')}`)
}

/** PDF 里的 `/MediaBox [x0 y0 x1 y1]`（单位 pt）—— 逐页按出现顺序取 */
function mediaBoxesMm(buffer) {
  const text = buffer.toString('latin1')
  const boxes = []
  const re = /\/MediaBox\s*\[\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*\]/g
  let match = re.exec(text)
  while (match !== null) {
    const [, x0, y0, x1, y1] = match.map(Number)
    boxes.push({ widthPt: x1 - x0, heightPt: y1 - y0 })
    match = re.exec(text)
  }
  return boxes
}

const PT_TO_MM = 25.4 / 72
const round1 = (value) => Math.round(value * 10) / 10

/** 与组件**同值**的 CSS（宽度 / padding / 字号 / 行高 / 二维码口径取 metrics 的现值） */
const CSS = `
  @page { size: 50mm 140mm; margin: 0; }
  @page wash-label-option { size: 50mm 100mm; margin: 0; }
  html, body { margin: 0; padding: 0; }
  .task-card-label {
    width: 50mm; height: 140mm; overflow: hidden; box-sizing: border-box;
    padding: 15mm 1.2mm 15mm; font-size: 11pt; line-height: 1.2;
    display: flex; flex-direction: column; border-bottom: 1px dashed #000;
    break-after: page; page-break-after: always;
  }
  .task-card-label--option { height: 100mm; page: wash-label-option; }
  .task-card-label:last-child { break-after: auto; page-break-after: auto; }
  .qr { margin-top: 0.5mm; height: 21.17mm; width: 21.17mm; background: #000; flex-shrink: 0; }
`

const HTML = `<!doctype html><html><head><meta charset="utf-8"><style>${CSS}</style></head><body>
  <div class="task-card-label" data-print-sheet data-sheet-paper-mm="50x140">
    <div>亿家纺织</div><div>成品定制</div>
    <div>单号: 20261021-8237</div><div>客户: 赵凯</div><div>安装小区: 春江花园</div>
    <div>安装位置: 主卧</div><div>第 1 套 / 共 2 套</div><div>帘种: 布帘</div>
    <div>货号: 米白</div><div>门幅: 2.8米</div><div>用料: 6.3米</div><div>宽高: 3×2.75米</div>
    <div>韩褶 · 超高 · 倒幅 · 双开 · 定型</div><div>褶法: 韩褶公式 52折</div>
    <div>特殊选项: 余料带回、布绑带</div><div>备注: 加铅块</div><div>布料批次: PC-20261026-0001</div>
    <div class="qr"></div>
  </div>
  <div class="task-card-label task-card-label--option" data-print-sheet data-sheet-paper-mm="50x100">
    <div>亿家纺织</div><div>成品定制 · 余料带回</div>
    <div>货号: 米白</div><div>门幅: 2.8米</div><div>宽高: 3×2.75米</div>
    <div>韩褶 · 超高 · 倒幅 · 双开 · 定型</div><div>特殊选项: 余料带回、布绑带</div>
    <div class="qr"></div>
  </div>
</body></html>`

const EXPECTED = [
  { name: '常规唛', widthMm: 50, heightMm: 140 },
  { name: '专属唛', widthMm: 50, heightMm: 100 },
]
const TOLERANCE_MM = 0.5

async function main() {
  const { module: playwright, from } = loadPlaywright()
  const { chromium } = playwright
  const browser = await chromium.launch()
  const page = await browser.newPage()
  await page.setContent(HTML, { waitUntil: 'load' })
  const pdf = await page.pdf({ preferCSSPageSize: true, printBackground: true })
  await browser.close()

  const outDir = join(HERE, 'out')
  mkdirSync(outDir, { recursive: true })
  const pdfPath = join(outDir, 'wash-label-two-papers.pdf')
  writeFileSync(pdfPath, pdf)

  const boxes = mediaBoxesMm(pdf).map((box) => ({
    widthMm: round1(box.widthPt * PT_TO_MM),
    heightMm: round1(box.heightPt * PT_TO_MM),
  }))
  const reading = `pages: ${boxes.length} | ${boxes.map((box) => `${box.widthMm}x${box.heightMm}mm`).join(' | ')}`
  console.log(`playwright: ${from}`)
  console.log(reading)
  console.log(`pdf: ${pdfPath}`)

  const problems = []
  if (boxes.length !== EXPECTED.length) {
    problems.push(`页数 ${boxes.length} ≠ 期望 ${EXPECTED.length}（两种纸型必须各自成页）`)
  }
  EXPECTED.forEach((expected, index) => {
    const got = boxes[index]
    if (!got) return
    if (Math.abs(got.widthMm - expected.widthMm) > TOLERANCE_MM) {
      problems.push(`第 ${index + 1} 页（${expected.name}）宽 ${got.widthMm}mm ≠ ${expected.widthMm}mm`)
    }
    if (Math.abs(got.heightMm - expected.heightMm) > TOLERANCE_MM) {
      problems.push(
        `第 ${index + 1} 页（${expected.name}）高 ${got.heightMm}mm ≠ ${expected.heightMm}mm（±${TOLERANCE_MM}）`,
      )
    }
  })
  // 反向对照：两种纸高必须**不同**（同一张纸 ⇒ 命名页没生效，本证据就没有意义）
  if (boxes.length === 2 && Math.abs(boxes[0].heightMm - boxes[1].heightMm) <= TOLERANCE_MM) {
    problems.push('两页纸高相同 ⇒ 命名页 `@page wash-label-option` 没生效（专属唛退化回 140mm）')
  }

  if (problems.length > 0) {
    console.error(`\n❌ ${problems.join('\n❌ ')}`)
    process.exit(1)
  }
  console.log('✅ 两页纸型 = 50×140 与 50×100（±0.5mm），命名页混排被 Chromium 接受')
}

main().catch((error) => {
  console.error(`\n❌ ${error.message}`)
  process.exit(1)
})
