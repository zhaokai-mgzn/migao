// p10-probe：看清「新增订单」弹窗打开后到底有什么（首轮 p10 在商品选择上超时的定位手段）
import { readFileSync } from 'node:fs'
import { log } from './lib.mjs'
import { launch, newPage, loginEmployeeUi, gotoLoaded, shot } from './ui.mjs'

const SESSION = JSON.parse(readFileSync(process.env.A06_SESSION || '/tmp/a06-session.json', 'utf8'))
const { ctx, page } = await newPage(await launch())
try {
  await loginEmployeeUi(page, `a06_sales@${SESSION.tenantCode}`, 'Migao@2026x')
  log('登录完成')
  await gotoLoaded(page, '/orders')
  log('订单页就位')
  const btn = page.getByRole('button', { name: /新增订单/ }).first()
  log(`新增订单按钮数=${await btn.count()}`)
  await btn.click({ timeout: 10000 })
  await page.waitForTimeout(4000)
  const btns = await page.getByRole('button').allInnerTexts().catch(() => [])
  log(`弹窗后按钮(${btns.length})：${JSON.stringify(btns.slice(0, 25))}`)
  const text = (await page.evaluate(() => document.body.innerText || '')).slice(0, 900)
  log(`正文头：${JSON.stringify(text)}`)
  const dialogs = await page.locator('[role="dialog"]').count()
  const modalText = dialogs ? (await page.locator('[role="dialog"]').last().innerText().catch(() => '')).slice(0, 700) : '(无 dialog)'
  log(`dialog 数=${dialogs} 内容=${JSON.stringify(modalText)}`)
  await shot(page, 'p10-probe-picker')
} catch (e) {
  log(`探针异常：${String(e).slice(0, 300)}`)
  await shot(page, 'p10-probe-error').catch(() => {})
} finally {
  await ctx.close().catch(() => {})
  process.exit(0)
}
