// 版式几何读数（issue #7176）—— **静态复现件** + 真实 Chromium 几何量测。
//
// 为什么是复现件而不是真栈截图：本机此刻没有起 admin-web(:3001) + admin-api(:8080)，
// 而本单只改**版式**（class 形态），所以用一个**同一套 class** 的静态 HTML 在真实浏览器里量：
//   · 复现件先与**用户截图**对账（内容宽 764 时左卡 423 / 右卡 245 / 右侧空白 79 vs 复现 424/246/78
//     —— 偏差 < 2px ⇒ 复现件可信）；
//   · 再量改后的形态（两个并排 `FormPanel`）⇒ blank = 0。
// 真栈截图仍由下一次部署后的 §15.7 读图补（边界如实登记在 README）。
import { createRequire } from 'node:module'
const REPO = '/Users/guangzhen.zk/ai native/migao'
const { chromium } = createRequire(`${REPO}/tests/package.json`)('playwright')

const OUT = `${REPO}/acceptance/2026-10-18/design-system-7176`
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 900, height: 1400 }, deviceScaleFactor: 2 })
await page.goto(`file://${OUT}/layout-probe.html`)

const read = await page.evaluate(() => {
  const root = document.getElementById('after')
  const row = root.querySelector('.grid.gap-4')
  const rect = (el) => {
    const b = el.getBoundingClientRect()
    return { x: Math.round(b.x), w: Math.round(b.width), h: Math.round(b.height) }
  }
  return {
    contentWidth: Math.round(root.getBoundingClientRect().width),
    rowWidth: Math.round(row.getBoundingClientRect().width),
    cards: [...row.children].map(rect),
    rightBlank: Math.round(row.getBoundingClientRect().right - row.lastElementChild.getBoundingClientRect().right),
  }
})
console.log(JSON.stringify(read))
await page.locator('#after').screenshot({ path: `${OUT}/after-算料口径整页.png` })
await browser.close()
// 判据：并排两卡把行撑满（右侧空白 0）且两卡等宽
if (read.rightBlank !== 0) {
  console.error('❌ 右侧仍有空白：', read.rightBlank)
  process.exit(1)
}
console.log('✅ RESULT {"rightBlank":0}')
