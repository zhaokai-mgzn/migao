// 手机端黄金策表格渲染的**几何读数 + 截图**（issue #7235）
//
// 为什么是静态复现件：本机此刻没有起 bmini H5 运行栈（Taro 构建 + 商家登录 + 真会话），
// 而本单改的是**渲染形态**（DOM 结构 + 同一份 SCSS）⇒ 用复现件在真实 Chromium 里量几何，
// 与仓库既有先例同范式（acceptance/2026-10-18/design-system-7176/probe.mjs）。
// 边界（如实登记）：复现件不等于真机 H5；真栈截图由下一次发布后补（README 有登记）。
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
const REPO = '/Users/guangzhen.zk/ai native/migao'
const { chromium } = createRequire(`${REPO}/tests/package.json`)('playwright')

// ⚠️ 必须用 fileURLToPath：仓库路径含空格（`ai native`）⇒ pathname 是 %20 编码，截图会写到假目录
const HERE = fileURLToPath(new URL('.', import.meta.url))
const browser = await chromium.launch()
// 390×844 = iPhone 12/13 竖屏；页面按 750 设计宽渲染（与 Taro designWidth 同比例）
const page = await browser.newPage({ viewport: { width: 750, height: 1500 }, deviceScaleFactor: 2 })
await page.goto(`file://${HERE}table-probe.html`)

const read = await page.evaluate(() => {
  const rect = (el) => {
    const b = el.getBoundingClientRect()
    return { x: Math.round(b.x), w: Math.round(b.width), h: Math.round(b.height) }
  }
  const scrolls = [...document.querySelectorAll('.message-bubble__table-scroll')].map((el) => ({
    clientWidth: el.clientWidth,
    scrollWidth: el.scrollWidth,
    scrollable: el.scrollWidth > el.clientWidth,
    rect: rect(el),
  }))
  const tables = [...document.querySelectorAll('.message-bubble__table')].map((el) => ({
    rows: el.querySelectorAll('.message-bubble__table-row').length,
    cells: el.querySelectorAll('.message-bubble__table-cell').length,
    rect: rect(el),
  }))
  const wrappers = [...document.querySelectorAll('.message-bubble__wrapper')].map((el) => ({
    wide: el.classList.contains('message-bubble__wrapper--wide'),
    rect: rect(el),
  }))
  return {
    viewport: window.innerWidth,
    pageScrollWidth: document.documentElement.scrollWidth,
    scrolls,
    tables,
    wrappers,
    literalPipes: (document.body.textContent.match(/\|/g) || []).length,
  }
})
console.log(JSON.stringify(read, null, 2))
await page.screenshot({ path: `${HERE}screenshot-750.png`, fullPage: true })
await browser.close()

const fail = []
if (read.literalPipes !== 0) fail.push(`DOM 文本里仍有字面 | ×${read.literalPipes}`)
if (read.pageScrollWidth > read.viewport) fail.push(`页面横向溢出 ${read.pageScrollWidth} > ${read.viewport}`)
if (read.tables.length !== 2) fail.push(`表格数量 ${read.tables.length} ≠ 2`)
if (read.tables[0]?.rows !== 4) fail.push(`6 列表格行数 ${read.tables[0]?.rows} ≠ 4（表头 1 + 数据 3）`)
if (read.tables[0]?.cells !== 24) fail.push(`6 列表格单元数 ${read.tables[0]?.cells} ≠ 24`)
if (!read.scrolls[0]?.scrollable) fail.push('6 列表格不可横滑（scrollWidth ≤ clientWidth）—— 窄屏会被挤成一列')
const wide = read.wrappers.filter((w) => w.wide)
const plain = read.wrappers.filter((w) => !w.wide)
if (wide.length !== 2) fail.push(`宽气泡数量 ${wide.length} ≠ 2`)
if (!plain.length || wide[0].rect.w <= plain[0].rect.w) fail.push('宽气泡没有比纯文本气泡更宽')
if (fail.length) {
  console.error('❌ ' + fail.join('；'))
  process.exit(1)
}
console.log('✅ RESULT ' + JSON.stringify({
  literalPipes: 0,
  tableCount: read.tables.length,
  sixColScrollable: read.scrolls[0].scrollable,
  wideBubbleWidth: wide[0].rect.w,
  plainBubbleWidth: plain[0].rect.w,
}))
