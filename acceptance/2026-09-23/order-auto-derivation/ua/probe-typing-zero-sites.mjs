// 逐字符读数探针（issue #5255 §B）：四个站点的 `'0' → '.' → '5'` 逐击读数 + 终值 + **提交值/回调值**
//
// 站点（与 issue #5228 的表一致）：
//   ① /products/<id>  ProductDetail.tsx 的行内改价 SkuPriceCell（type="number" + parseFloat）
//   ② /inbound-orders  建单弹窗的 数量 / 单价 / 卷长（type="number" ×3 + Number(x) / x===''?null:Number(x)）
//   ③ /finance         登记收支弹窗的 金额（type="number" + Number(form.amount) + amount<=0 拒）
//   ④ /orders          处理退款弹窗的 退款金额（type="number" + parseFloat(amountText) + >0 才可提交）
//
// 用法：
//   PHONE=13600136000 BASE_URL=http://localhost:3001 OUT_DIR=<空目录> \
//     PRODUCT_ID=prod_eval_dark_green node probe-typing-zero-sites.mjs
//
// ⚠️ 边界（issue #5255 §B 明写）：`type="number"` 的「`0.` 中间态」这条轴**已由真浏览器判定为无缺陷**
//    （#5228 评论）⇒ 本探针判的是**各站点自己的解析 / 回写口径**，不是重复那条判定。
import { createRequire } from 'node:module'
import { writeFileSync, mkdirSync } from 'node:fs'
const require = createRequire('/Users/guangzhen.zk/ai native/migao/tests/package.json')
const { chromium } = require('playwright')

const BASE = process.env.BASE_URL || 'http://localhost:3001'
const OUT = process.env.OUT_DIR || '/tmp/ua-typing-sites'
const PHONE = process.env.PHONE || '13600136000'
const SMS = process.env.SMS_CODE || '123456'
const PRODUCT_ID = process.env.PRODUCT_ID || 'prod_eval_dark_green'
mkdirSync(OUT, { recursive: true })

const lines = []
const say = (s) => { lines.push(s); console.log(s) }
const COMMIT_URL_RE = /\/skus\/|\/inbound-orders|\/finance\/|\/refund|\/transactions/
const commits = []

const browser = await chromium.launch({ headless: true, args: ['--no-proxy-server'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } })
page.on('pageerror', (e) => say(`  [pageerror] ${String(e).slice(0, 200)}`))
page.on('request', (r) => {
  const u = r.url()
  if (COMMIT_URL_RE.test(u) && r.method() !== 'GET') {
    commits.push({ method: r.method(), url: u.replace('http://localhost:8080', 'api'), data: r.postData() })
    say(`  [commit-req] ${r.method()} ${u.replace('http://localhost:8080', 'api')} :: ${r.postData()}`)
  }
})
page.on('response', async (r) => {
  const u = r.url()
  if (COMMIT_URL_RE.test(u) && r.request().method() !== 'GET') {
    let body = ''
    try { body = (await r.text()).slice(0, 300) } catch {}
    say(`  [commit-res] ${r.status()} ${u.replace('http://localhost:8080', 'api')} :: ${body}`)
  }
})
const shot = async (name) => { await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false }); say(`  [shot] ${OUT}/${name}.png`) }

/**
 * 逐字符敲 `0` `.` `5`，**每一击都读 el.value**；返回读数表 + 终值。
 * @param locator 目标输入框
 * @param label 站点字段名（写进读数表）
 */
const typeZeroDotFive = async (locator, label) => {
  await locator.click()
  await locator.fill('')
  const per = []
  for (const ch of ['0', '.', '5']) {
    await page.keyboard.type(ch)
    await page.waitForTimeout(150)
    per.push({ ch, value: await locator.inputValue() })
  }
  const finalValue = await locator.inputValue()
  const row = `  ${label}：` + per.map((p) => `'${p.ch}'→${JSON.stringify(p.value)}`).join('  ') + `   终值 = ${JSON.stringify(finalValue)}`
  say(row)
  return { label, per, finalValue, row }
}

/**
 * 只敲 `'0'` 一击：读 DOM 值（**「0 被当空」这条口径的直接判据** ——
 * issue #5255 §B 点名的 `parseInt` / `Number(x) || null` 那一族，会把 0 映射成空串/空值）。
 * 返回读数行；提交/守卫行为由调用方按站点各自记录（各站点口的校验不同）。
 */
const typeZeroOnly = async (locator, label) => {
  await locator.click()
  await locator.fill('')
  await page.keyboard.type('0')
  await page.waitForTimeout(250)
  const value = await locator.inputValue()
  const row = `  ${label}（只敲 '0'）：DOM 值 = ${JSON.stringify(value)}　尾随字符会否追加 = ${value === '0' ? '✅ 保留 "0"（未当空）' : `❌ 变成 ${JSON.stringify(value)}`}`
  say(row)
  return row
}

/** 读 sonner toast 的可见文本（各站点的守卫文案） */
const readToasts = async () => {
  const t = await page.evaluate(() =>
    Array.from(document.querySelectorAll('[data-sonner-toast], li[data-sonner-toast], [role="status"]'))
      .map((e) => (e.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean))
  return t
}

try {
  // ── 登录（一次）
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('#phone', { timeout: 60000 })
  await page.fill('#phone', PHONE)
  await page.getByRole('button', { name: /获取验证码/ }).click()
  await page.waitForTimeout(1200)
  await page.fill('#code', SMS)
  await page.getByRole('button', { name: /登\s*录|登录/ }).last().click()
  await page.waitForURL('**/dashboard**', { timeout: 30000 })
  say('✅ 登录成功')
  const readings = []

  // ══════════ 站点 ① ProductDetail.tsx / SkuPriceCell（行内改价） ══════════
  try {
    say('\n===== 站点① frontend/admin-web/src/app/(dashboard)/products/[id]/ProductDetail.tsx :: SkuPriceCell（行内改价）=====')
    await page.goto(`${BASE}/products/${PRODUCT_ID}`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(3000)
    const cell = page.locator('button[title="点击编辑价格"]').first()
    await cell.waitFor({ state: 'visible', timeout: 15000 })
    const before = (await cell.innerText()).trim()
    say(`  改价前显示值（商品 SKU 表）= ${JSON.stringify(before)}`)
    await cell.click()
    await page.waitForTimeout(600)
    const priceInput = page.locator('input[type="number"][step="0.01"]').first()
    await priceInput.waitFor({ state: 'visible', timeout: 8000 })
    say(`  [DOM] 输入框属性 = type=${await priceInput.getAttribute('type')} step=${await priceInput.getAttribute('step')}`)
    // ① a) 只敲 '0' ⇒ 读 DOM 值，再 Enter 提交（看「0 被当空」与否：`parseFloat('0')` 合法 ⇒ 应提交 0）
    say(await typeZeroOnly(priceInput, 'SKU 价格（行内改价）'))
    await page.waitForTimeout(600)
    await priceInput.press('Enter')
    await page.waitForTimeout(3000)
    say(`  '0' 提交后显示值 = ${JSON.stringify((await page.locator('button[title="点击编辑价格"]').first().innerText().catch(() => '')).trim())}`)
    // ① b) 再点开做 '0' → '.' → '5'
    await page.locator('button[title="点击编辑价格"]').first().click()
    await page.waitForTimeout(700)
    const priceInput2 = page.locator('input[type="number"][step="0.01"]').first()
    const r1 = await typeZeroDotFive(priceInput2, 'SKU 价格（行内改价）')
    readings.push(r1)
    await page.waitForTimeout(900) // ⚠️ 不 blur：该站点 onBlur 直接取消编辑（只认 Enter）
    await priceInput2.press('Enter')
    await page.waitForTimeout(3000)
    await shot('b1-改价-输入0.5')
    const afterCell = page.locator('button[title="点击编辑价格"]').first()
    const after = (await afterCell.innerText().catch(() => '')).trim()
    say(`  提交后显示值（回写口径）= ${JSON.stringify(after)}　（0.5 提交前 ${JSON.stringify(before)}）`)
  } catch (e) { say(`  ❌ 站点① 失败：${String(e).slice(0, 300)}`); await shot('b1-失败').catch(() => {}) }

  // ══════════ 站点 ② inbound-orders/page.tsx（数量 / 单价 / 卷长） ══════════
  try {
    say('\n===== 站点② frontend/admin-web/src/app/(dashboard)/inbound-orders/page.tsx :: 数量 / 单价 / 卷长 =====')
    await page.goto(`${BASE}/inbound-orders`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(3000)
    // ⚠️ 按钮文案是「新建入库单」（不含连续子串「建单」⇒ 用 /建单/ 会 30s 超时）
    await page.getByRole('button', { name: /新建入库单/ }).first().click()
    await page.waitForTimeout(1200)
    const dialog = page.locator('[role="dialog"]').first()
    const kw = dialog.locator('input').first()
    await kw.fill('遮光窗帘')
    await page.waitForTimeout(1500)
    await dialog.getByRole('button', { name: /遮光窗帘/ }).first().click()
    await page.waitForTimeout(2000)
    await dialog.locator('input[type="checkbox"]').first().check()
    await page.waitForTimeout(1200)
    const qty = page.locator('input[aria-label$="数量"]').first()
    const cost = page.locator('input[aria-label$="单价"]').first()
    const roll = page.locator('input[aria-label$="卷长"]').first()
    say(`  默认值：数量=${JSON.stringify(await qty.inputValue())} 单价=${JSON.stringify(await cost.inputValue())} 卷长=${JSON.stringify(await roll.inputValue())}`)
    // ② a) 三项各只敲 '0' ⇒ 读 DOM 值（「0 被当空」的直接判据）
    say(await typeZeroOnly(qty, '数量'))
    say(await typeZeroOnly(cost, '单价'))
    say(await typeZeroOnly(roll, '卷长'))
    await shot('b2a-入库-三项只敲0')
    // ② a2) 在「数量 = 0」的状态下尝试提交 ⇒ 记守卫行为（该站点的 `checkStockQuantity`）
    await page.getByRole('button', { name: /保存为草稿/ }).first().click()
    await page.waitForTimeout(2500)
    say(`  「数量=0」提交后 toast = ${JSON.stringify(await readToasts())}`)
    say(`  「数量=0」提交后弹窗是否仍在（true=被拦下）= ${await page.locator('[role="dialog"]').first().isVisible().catch(() => false)}`)
    // ② b) '0' → '.' → '5'（三项）
    readings.push(await typeZeroDotFive(qty, '数量'))
    readings.push(await typeZeroDotFive(cost, '单价'))
    readings.push(await typeZeroDotFive(roll, '卷长'))
    await shot('b2-入库-三项输0.5')
    await page.getByRole('button', { name: /保存为草稿/ }).first().click()
    await page.waitForTimeout(3500)
    await shot('b2-入库-提交后')
    say(`  提交后弹窗是否仍在（true=被拦下）= ${await page.locator('[role="dialog"]').first().isVisible().catch(() => false)}`)
  } catch (e) { say(`  ❌ 站点② 失败：${String(e).slice(0, 300)}`); await shot('b2-失败').catch(() => {}) }

  // ══════════ 站点 ③ finance/page.tsx（金额） ══════════
  try {
    say('\n===== 站点③ frontend/admin-web/src/app/(dashboard)/finance/page.tsx :: 金额 =====')
    await page.goto(`${BASE}/finance`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(3000)
    await page.getByRole('button', { name: /登记收支/ }).first().click()
    await page.waitForTimeout(1200)
    const amount = page.locator('[role="dialog"] input[type="number"]').first()
    await amount.waitFor({ state: 'visible', timeout: 8000 })
    say(`  [DOM] 输入框属性 = type=${await amount.getAttribute('type')} min=${await amount.getAttribute('min')} placeholder=${await amount.getAttribute('placeholder')}`)
    // ③ a) 只敲 '0' ⇒ 读 DOM 值；再试提交 ⇒ 记守卫文案（`amount <= 0` 拒）
    say(await typeZeroOnly(amount, '金额'))
    await page.locator('[role="dialog"]').getByRole('button', { name: /^提交$/ }).first().click()
    await page.waitForTimeout(2500)
    say(`  「金额=0」提交后 toast = ${JSON.stringify(await readToasts())}`)
    say(`  「金额=0」提交后弹窗是否仍在（true=被拦下）= ${await page.locator('[role="dialog"]').first().isVisible().catch(() => false)}`)
    // ③ b) '0' → '.' → '5'
    readings.push(await typeZeroDotFive(amount, '金额'))
    await shot('b3-财务-金额0.5')
    await page.locator('[role="dialog"]').getByRole('button', { name: /^提交$/ }).first().click()
    await page.waitForTimeout(3500)
    await shot('b3-财务-提交后')
    say(`  提交后弹窗是否仍在（true=被拦下）= ${await page.locator('[role="dialog"]').first().isVisible().catch(() => false)}`)
  } catch (e) { say(`  ❌ 站点③ 失败：${String(e).slice(0, 300)}`); await shot('b3-失败').catch(() => {}) }

  // ══════════ 站点 ④ RefundOrderModal.tsx（退款金额） ══════════
  try {
    say('\n===== 站点④ frontend/admin-web/src/components/orders/RefundOrderModal.tsx :: 退款金额 =====')
    await page.goto(`${BASE}/orders`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(3500)
    const refundLink = page.getByText('处理退款', { exact: true }).first()
    await refundLink.waitFor({ state: 'visible', timeout: 15000 })
    await refundLink.click()
    await page.waitForTimeout(1200)
    const amountInput = page.locator('#refund-amount')
    await amountInput.waitFor({ state: 'visible', timeout: 8000 })
    say(`  [DOM] 输入框属性 = type=${await amountInput.getAttribute('type')} min=${await amountInput.getAttribute('min')}`)
    // ④ a) 只敲 '0' ⇒ 读 DOM 值 + 「确定」是否被禁用（`amountValid = parseFloat > 0`）
    say(await typeZeroOnly(amountInput, '退款金额'))
    say(`  「退款金额=0」时「确定」是否禁用 = ${await page.locator('[role="dialog"]').getByRole('button', { name: /^确定$/ }).first().isDisabled().catch(() => 'n/a')}`)
    // ④ b) '0' → '.' → '5'
    readings.push(await typeZeroDotFive(amountInput, '退款金额'))
    await shot('b4-退款-金额0.5')
    const confirmBtn = page.locator('[role="dialog"]').getByRole('button', { name: /^确定$/ }).first()
    say(`  「确定」是否可点（disabled）= ${await confirmBtn.isDisabled().catch(() => 'n/a')}`)
    await confirmBtn.click()
    await page.waitForTimeout(3500)
    await shot('b4-退款-提交后')
    say(`  提交后弹窗是否仍在（true=被拦下）= ${await page.locator('[role="dialog"]').first().isVisible().catch(() => false)}`)
  } catch (e) { say(`  ❌ 站点④ 失败：${String(e).slice(0, 300)}`); await shot('b4-失败').catch(() => {}) }

  // ── 汇总：提交值 / 回调值（网络载荷为准）+ 逐字符读数行
  say('\n===== 提交值 / 回调值（POST/PATCH 载荷，逐字）=====')
  if (commits.length === 0) say('  ⚠️ 未捕获到任何提交请求')
  for (const c of commits) say(`  ${c.method} ${c.url} :: ${c.data}`)
  writeFileSync(`${OUT}/typing-sites-readings.txt`, lines.join('\n') + '\n')
  say(`\n[saved] ${OUT}/typing-sites-readings.txt`)
  say('PROBE_DONE_OK')
} catch (e) {
  say(`PROBE_FAILED: ${String(e).slice(0, 600)}`)
  await shot('99-失败现场').catch(() => {})
  writeFileSync(`${OUT}/typing-sites-readings.txt`, lines.join('\n') + '\n')
} finally {
  await browser.close()
}
