// p4b：订单页「选择商品」弹窗侦察（W3 卡在「提交订单」不可点 ⇒ 先把弹窗的真实结构 dump 出来）
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { OUT } from './lib.mjs'
import { launch, newPage, loginEmployeeUi, gotoLoaded, shot } from './ui.mjs'

const SESSION = JSON.parse(readFileSync(process.env.A06_SESSION || '/tmp/a06-session.json', 'utf8'))
const EMP_PWD = 'Migao@2026x'

const main = async () => {
  const browser = await launch()
  const { ctx, page } = await newPage(browser)
  const out = {}
  try {
    await loginEmployeeUi(page, `a06_sales@${SESSION.tenantCode}`, EMP_PWD)
    await gotoLoaded(page, '/orders')
    await page.getByRole('button', { name: /新增订单/ }).first().click()
    await page.waitForTimeout(1500)
    await page.getByRole('button', { name: /点击搜索并选择商品/ }).first().click().catch(() => {})
    await page.waitForTimeout(1500)
    const dlg = page.locator('[role="dialog"]').last()
    const search = dlg.locator('input').first()
    if (await search.count()) { await search.fill('布'); await dlg.getByRole('button', { name: /搜索/ }).first().click().catch(() => {}) }
    for (let i = 0; i < 20; i++) { const t = await dlg.innerText().catch(() => ''); if (!/加载中/.test(t)) break; await page.waitForTimeout(800) }
    out.dialogText = (await dlg.innerText().catch(() => '')).slice(0, 700)
    out.dialogButtons = await dlg.getByRole('button').allInnerTexts().catch(() => [])
    out.rows = await dlg.evaluate((el) => Array.from(el.querySelectorAll('tr, [role="row"], li, div[class*="cursor-pointer"]'))
      .slice(0, 12).map((r) => ({ tag: r.tagName, cls: (r.className || '').toString().slice(0, 60), text: (r.textContent || '').trim().slice(0, 80) }))).catch(() => [])
    await shot(page, 'recon-order-picker')
    // 尝试点第一行 + 观察弹窗是否关闭、合计是否变化
    const firstRow = dlg.locator('tr, [role="row"]').nth(1)
    if (await firstRow.count()) { await firstRow.click({ timeout: 5000 }).catch((e) => { out.rowClickError = String(e).slice(0, 120) }) }
    await page.waitForTimeout(1200)
    out.afterRowClickDialogText = (await dlg.innerText().catch(() => '')).slice(0, 400)
    out.dialogStillOpen = await dlg.isVisible().catch(() => false)
    out.bodyAfterPick = (await page.evaluate(() => document.body.innerText)).slice(-600)
    await shot(page, 'recon-order-picker-after')
  } catch (e) { out.error = String(e).slice(0, 300) }
  await ctx.close().catch(() => {})
  await browser.close()
  writeFileSync(join(OUT, 'p4b-order-recon.json'), JSON.stringify(out, null, 2))
  console.log(JSON.stringify(out, null, 2).slice(0, 2500))
}
main().catch((e) => { console.error(e); process.exit(1) })
