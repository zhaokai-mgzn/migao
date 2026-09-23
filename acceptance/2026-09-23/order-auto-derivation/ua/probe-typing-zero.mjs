// UA 补充探针：真浏览器逐字符输入 `0.5`（用户原始报的 bug：不能直接输入 0 ⇒ 输不了 0.x）
// 目标站点 = 下单页「窗宽（米）」（共享 NumberInput / 页内 NumberField）
import { createRequire } from 'node:module'
const require = createRequire('/Users/guangzhen.zk/ai native/migao/tests/package.json')
const { chromium } = require('playwright')
const BASE = process.env.BASE_URL || 'http://localhost:3001'
const PHONE = process.env.PHONE || '13600136000'

const browser = await chromium.launch({ headless: true, args: ['--no-proxy-server'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } })
await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 60000 })
await page.waitForSelector('#phone', { timeout: 60000 })
await page.fill('#phone', PHONE)
await page.getByRole('button', { name: /获取验证码/ }).click()
await page.waitForTimeout(1500)
await page.fill('#code', '123456')
await page.getByRole('button', { name: /登\s*录|登录/ }).last().click()
await page.waitForURL('**/dashboard**', { timeout: 25000 })
console.log('✅ 登录成功')

await page.goto(`${BASE}/orders/new`, { waitUntil: 'domcontentloaded', timeout: 60000 })
await page.waitForTimeout(2500)
await page.fill('input[placeholder*="收货人姓名"]', 'UA探针')
await page.fill('input[placeholder*="手机号"]', '13900002222')
await page.fill('input[placeholder*="收货地址"]', '杭州市西湖区探针路 1 号')
await page.getByRole('button', { name: /选择商品/ }).first().click()
await page.waitForTimeout(1000)
const search = page.locator('[role="dialog"] input[placeholder*="搜索商品"]').first()
await search.waitFor({ state: 'visible', timeout: 10000 })
await search.fill('遮光窗帘')
await page.locator('[role="dialog"] button:has-text("搜索")').first().click()
await page.waitForTimeout(2000)
await page.locator('[role="dialog"] button').filter({ hasText: /遮光窗帘/ }).first().click()
await page.waitForTimeout(2500)
const colorChip = page.getByText('浅灰', { exact: true }).first()
if (await colorChip.count()) await colorChip.click()
await page.waitForTimeout(1500)
console.log('✅ 已选商品 + 颜色')

// ── 核心：逐字符敲 `0` `.` `5`，每一击都读 DOM 值 ──
const w = page.getByLabel('窗宽 (米)').first()
await w.click()
await w.fill('')
const per = []
for (const ch of ['0', '.', '5']) {
  await page.keyboard.type(ch)
  await page.waitForTimeout(120)
  per.push(`'${ch}'→${JSON.stringify(await w.inputValue())}`)
}
console.log(`窗宽（米）逐字符：${per.join('  ')}`)
console.log(`窗宽（米）终值 = ${JSON.stringify(await w.inputValue())}`)
const after5 = await w.inputValue()
// 再敲一次「0.6」验证可重复 + 清空后重来
await w.fill('')
const per2 = []
for (const ch of ['0', '.', '6']) {
  await page.keyboard.type(ch)
  await page.waitForTimeout(120)
  per2.push(`'${ch}'→${JSON.stringify(await w.inputValue())}`)
}
console.log(`窗宽（米）第二轮：${per2.join('  ')}  终值=${JSON.stringify(await w.inputValue())}`)
console.log(`判定：第一轮终值 ${after5 === '0.5' ? '✅ 0.5（正确）' : `❌ ${after5}`}；第二轮终值 ${(await w.inputValue()) === '0.6' ? '✅ 0.6（正确）' : `❌ ${await w.inputValue()}`}`)
await page.screenshot({ path: '/tmp/ua-evidence/05-逐字符输0.5.png' })
console.log('PROBE_DONE_OK')
await browser.close()
