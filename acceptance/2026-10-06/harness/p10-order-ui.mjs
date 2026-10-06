// p10（v2）：销售在 /orders 页**真跑通**一张订单（布料形态），并**留存**数据供人查看
//
// v1 的两个教训（都写进判据）：
//   ① 售卖形态 chip 是 `role="radio"`（不是 button）—— 用 button 定位永远命中不了、又被 .catch 吞掉 ⇒ 静默留在「成品帘」；
//   ② 商品不是「弹窗里的一排按钮」，而是 **「点击搜索并选择商品」→ 搜索 → 选中**（v1 直接找商品按钮 ⇒ 15s 超时）。
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { psql, OUT, scrub, PROBE, SUBJECT_SHA, log } from './lib.mjs'
import { launch, newPage, loginEmployeeUi, gotoLoaded, shot } from './ui.mjs'

const SESSION = JSON.parse(readFileSync(process.env.A06_SESSION || '/tmp/a06-session.json', 'utf8'))
const TENANT_ID = Number(process.env.TENANT_ID || 25)
const PRODUCT = process.env.PRODUCT || '阳离子绒布'
const stamp = String(Date.now()).slice(-6)
const buyer = `${PROBE}下单客户${stamp}`
const R = []
const rec = (state, id, name, detail, evidence = []) => R.push({ state, id, name, detail, evidence })

const { ctx, page } = await newPage(await launch())
try {
  await loginEmployeeUi(page, `a06_sales@${SESSION.tenantCode}`, 'Migao@2026x')
  await gotoLoaded(page, '/orders')
  await page.getByRole('button', { name: /新增订单/ }).first().click({ timeout: 10000 })
  await page.waitForTimeout(2500)

  // ① 选商品：先点「点击搜索并选择商品」把搜索面打开
  await page.getByText(/点击搜索并选择商品/).first().click({ timeout: 8000 }).catch(() => {})
  await page.waitForTimeout(1200)
  const searchInput = page.locator('input[placeholder*="搜索"], input[placeholder*="商品名称"], input[placeholder*="请输入商品"]').first()
  let searchFilled = false
  if (await searchInput.count()) { await searchInput.fill(PRODUCT).catch(() => {}); searchFilled = true }
  else { await page.keyboard.type(PRODUCT, { delay: 60 }); searchFilled = true }
  await page.waitForTimeout(2500)
  await shot(page, 'w3c-picker')
  // 选中该商品（列表项可能是 button / li / 文本）
  let picked = false
  for (const loc of [
    page.getByRole('button', { name: new RegExp(PRODUCT) }),
    page.getByRole('option', { name: new RegExp(PRODUCT) }),
    page.getByText(new RegExp(`^${PRODUCT}`)),
  ]) {
    if (await loc.first().count()) { await loc.first().click({ timeout: 6000 }).catch(() => {}); picked = true; break }
  }
  await page.waitForTimeout(2500)

  // ② 售卖形态 = 布料（role=radio）
  const fabric = page.getByRole('radio', { name: '布料', exact: true }).first()
  const fabricCount = await fabric.count()
  if (fabricCount) await fabric.click({ timeout: 6000 }).catch(() => {})
  await page.waitForTimeout(1500)
  const fabricChecked = fabricCount ? await fabric.getAttribute('aria-checked').catch(() => null) : null

  // ②b 颜色（组级必填；本商品 SKU 只有「咖色」——DB 现取 product_skus.color_name）
  //     chip 形态与售卖形态同类：先按 role=radio 找，再退到 button / 文本
  let colorPicked = null
  for (const name of (process.env.COLORS || '咖色').split(',')) {
    for (const loc of [
      page.getByRole('radio', { name, exact: true }),
      page.getByRole('button', { name, exact: true }),
      page.getByText(name, { exact: true }),
    ]) {
      if (await loc.first().count()) { await loc.first().click({ timeout: 6000 }).catch(() => {}); colorPicked = name; break }
    }
    if (colorPicked) break
  }
  await page.waitForTimeout(2000)

  // ③ 收货信息
  for (const [ph, val] of [['请输入收货人姓名', buyer], ['请输入 11 位手机号', '13900000002'], ['请输入详细收货地址', '浙江省绍兴市柯桥区演示路 1 号']]) {
    const el = page.locator(`input[placeholder="${ph}"]`).first()
    if (await el.count()) await el.fill(val).catch(() => {})
  }
  // ④ 常用物流
  await page.locator('[data-testid="logistics-section"] summary').first().click().catch(() => {})
  await page.waitForTimeout(500)
  await page.locator('[data-testid="order-logistics-type"]').first().selectOption({ index: 1 }).catch(() => {})
  await page.locator('[data-testid="logistics-section"] input').last().fill('四季安物流').catch(() => {})

  const totalLine = await page.evaluate(() => (document.body.innerText.match(/合计[^\n]*/) || [''])[0])
  await shot(page, 'w3c-order-form')

  // ⑤ 提交
  await page.getByRole('button', { name: /提交订单/ }).first().click({ timeout: 10000 }).catch(() => {})
  await page.waitForTimeout(5000)
  const validation = (await page.evaluate(() => (document.body.innerText.match(/还差[\s\S]{0,200}/) || [''])[0])).replace(/\n/g, ' | ')
  await shot(page, 'w3c-order-after')
  const row = psql(`select id, order_no, status, total_amount, logistics_type, logistics_company from orders where tenant_id=${TENANT_ID} and customer_name='${buyer}'`)[0]
  rec(row ? 'pass' : 'fail', 'P10-W3', '销售在「订单列表」页新建订单（布料形态 · 页面操作 → DB 落库）',
    row ? `DB 落库 orders#${row.id} order_no=${row.order_no} status=${row.status} 金额=${row.total_amount} 物流=${row.logistics_type}/${row.logistics_company}；选品=${picked} 搜索框填词=${searchFilled} 布料 chip=${fabricCount} aria-checked=${fabricChecked} 颜色=${colorPicked} 合计=${JSON.stringify(totalLine)}`
        : `DB 无新行；选品=${picked} 搜索框填词=${searchFilled} 布料 chip=${fabricCount} aria-checked=${fabricChecked} 颜色=${colorPicked} 合计=${JSON.stringify(totalLine)} 校验=${JSON.stringify(validation)}`,
    ['out/shots/w3c-picker.png', 'out/shots/w3c-order-form.png', 'out/shots/w3c-order-after.png', `SQL: select * from orders where customer_name='${buyer}'`])
  if (row) {
    const n = psql(`select count(*)::int as n from orders where tenant_id=${TENANT_ID}`)[0]?.n
    rec('pass', 'P10-LIVE', '订单留存（用户 2026-10-06 要求看到订单数据）', `租户 ${TENANT_ID} 现有订单 ${n} 张；本轮演示单 ${row.order_no}（布料形态，未清理）`, [`SQL: select count(*) from orders where tenant_id=${TENANT_ID}`])
  }
} catch (e) {
  rec('fail', 'P10-W3', '销售新建订单异常', String(e).slice(0, 400))
  await shot(page, 'w3c-error').catch(() => {})
} finally {
  const counts = R.reduce((a, x) => ({ ...a, [x.state]: (a[x.state] || 0) + 1 }), {})
  writeFileSync(join(OUT, 'p10-order-ui.json'), JSON.stringify(scrub({ at: new Date().toISOString(), subjectSha: SUBJECT_SHA, tenantId: TENANT_ID, stamp, buyer, counts, rows: R }), null, 2))
  log(`== p10 counts: ${JSON.stringify(counts)}`)
  for (const x of R) log(`  [${x.state}] ${x.id} ${x.name} — ${x.detail.slice(0, 400)}`)
  await ctx.close().catch(() => {})
  process.exit(0)
}
