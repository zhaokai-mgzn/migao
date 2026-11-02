// p4d：补齐两条写面 ——
//   ① 用 API 造一张**真订单**当夹具（销售 UI 建单卡在「组合加工费未定价」的业务闸门，见 p4-writes.json W3）
//   ② 客服在「售后工单」页**用 UI** 建工单（引用该真订单）
//   ③ 商品管理员在「商品管理」页**用 UI** 建商品
// 纪律：夹具来源如实标注（订单=API 造，工单/商品=页面操作），不得把夹具说成 UI 旅程产物。
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { api, employeeLoginApi, psql, OUT, scrub, PROBE, SUBJECT_SHA, log, loginApi } from './lib.mjs'
import { launch, newPage, loginEmployeeUi, gotoLoaded, shot } from './ui.mjs'

const SESSION = JSON.parse(readFileSync(process.env.A06_SESSION || '/tmp/a06-session.json', 'utf8'))
const TENANT_ID = Number(process.env.TENANT_ID || 25)
const EMP_PWD = 'Migao@2026x'
const stamp = String(Date.now()).slice(-6)
const ROOT = join(import.meta.dirname, '..', '..')
const R = []
const rec = (state, id, name, detail, evidence = []) => R.push({ state, id, name, detail, evidence })
const bodyText = (page) => page.evaluate(() => document.body.innerText || '')

async function fixtureOrder() {
  const { token } = await employeeLoginApi(`a06_sales@${SESSION.tenantCode}`, EMP_PWD)
  const prod = psql(`select p.id as product_id, s.id as sku_id, s.price, p.name from products p join product_skus s on s.product_id=p.id
                     where p.tenant_id=${TENANT_ID} and p.deleted=0 order by p.created_at limit 1`)[0]
  const buyer = `${PROBE}夹具客户${stamp}`
  const variants = [
    { customerName: buyer, customerPhone: '13900000001', customerAddress: '浙江省绍兴市柯桥区夹具路 1 号', logisticsType: 'express', logisticsCompany: '四季安物流',
      items: [{ productId: prod.product_id, skuId: prod.sku_id, productName: prod.name, quantity: 1, unitPrice: Number(prod.price), subtotal: Number(prod.price) }] },
    { customerName: buyer, customerPhone: '13900000001', customerAddress: '浙江省绍兴市柯桥区夹具路 1 号', logisticsType: '快递', logisticsCompany: '四季安物流',
      items: [{ productId: prod.product_id, skuId: prod.sku_id, productName: prod.name, quantity: 1, price: Number(prod.price), subtotal: Number(prod.price) }] },
  ]
  const tries = []
  for (const body of variants) {
    const res = await api('POST', '/api/admin/orders', { token, body })
    tries.push({ status: res.status, text: res.text.slice(0, 220) })
    if (res.status === 200 && res.json?.success) {
      const row = psql(`select id, order_no, status, total_amount from orders where tenant_id=${TENANT_ID} and customer_name='${buyer}'`)[0]
      rec(row ? 'pass' : 'fail', 'P4D-1', 'API 夹具：真订单（供 W4 引用）',
        `HTTP 200；orders#${row?.id} order_no=${row?.order_no} status=${row?.status} 金额=${row?.total_amount}；商品=${prod?.name}`,
        ['POST /api/admin/orders（夹具，非 UI 旅程产物）'])
      return { orderNo: row?.order_no, buyer, tries }
    }
  }
  rec('fail', 'P4D-1', 'API 夹具：真订单（供 W4 引用）', `两版载荷均未成功：${JSON.stringify(tries)}`, ['POST /api/admin/orders'])
  return { tries }
}

async function uiTicket(browser, orderNo) {
  const desc = `${PROBE}UI工单${stamp}`
  const { ctx, page } = await newPage(browser)
  try {
    await loginEmployeeUi(page, `a06_customer_service@${SESSION.tenantCode}`, EMP_PWD)
    await gotoLoaded(page, '/after-sales')
    await page.getByRole('button', { name: /新建工单/ }).first().click()
    await page.waitForTimeout(1500)
    if (!orderNo) {
      rec('skip', 'P4D-2', '客服 UI 建工单', '前置不成立：无可用订单夹具 ⇒ 未覆盖', [])
      return
    }
    await page.locator('input[placeholder*="请输入订单号/客户姓名/手机号"]').first().fill(orderNo)
    await page.locator('textarea[placeholder*="请详细描述售后原因"]').first().fill(desc)
    await page.getByRole('button', { name: '退货', exact: true }).first().click().catch(() => {})
    await page.waitForTimeout(400)
    await shot(page, 'w4-ticket-form')
    await page.getByRole('button', { name: /提交工单/ }).first().click()
    await page.waitForTimeout(4000)
    const row = psql(`select id, ticket_no, ticket_type, status, order_id, description from after_sales_tickets where tenant_id=${TENANT_ID} and description='${desc}'`)[0]
    rec(row ? 'pass' : 'fail', 'P4D-2', '客服在「售后工单」页建工单（UI 操作 → DB 落库）',
      row ? `DB 落库 after_sales_tickets#${row.id} ticket_no=${row.ticket_no} type=${row.ticket_type} status=${row.status} order_id=${row.order_id}（引用夹具订单 ${orderNo}）`
          : `DB 无新行；页面文本尾=${JSON.stringify((await bodyText(page)).slice(-200))}`,
      ['out/shots/w4-ticket-form.png', 'SQL: select * from after_sales_tickets where description=…'])
    await shot(page, 'w4-ticket-after')
  } catch (e) {
    rec('fail', 'P4D-2', '客服 UI 建工单异常', String(e).slice(0, 300))
  } finally { await ctx.close().catch(() => {}) }
}

async function uiProduct(browser) {
  const pname = `${PROBE}商品${stamp}`
  const { ctx, page } = await newPage(browser)
  try {
    await loginEmployeeUi(page, `a06_product_manager@${SESSION.tenantCode}`, EMP_PWD)
    await gotoLoaded(page, '/products')
    const before = psql(`select count(*)::int as n from products where tenant_id=${TENANT_ID}`)[0]?.n
    await page.getByRole('button', { name: /新增商品/ }).first().click()
    await page.waitForTimeout(2000)
    // 商品名称（placeholder「最多可输入50汉字（100字符）」）
    await page.locator('input[placeholder*="50汉字"]').first().fill(pname).catch(() => {})
    await page.locator('input[placeholder*="请输入商品货号"]').first().fill(`A06-${stamp}`).catch(() => {})
    await page.locator('input[placeholder="价格"]').first().fill('66').catch(() => {})
    // 必填 6 项（截图逐字）：商品分类 / 主图 / 计价单位 / 售卖方式 …
    const pick = async (labelText) => {
      // 每个必填下拉前的 label 文案定位不到稳定选择器 ⇒ 按 select 顺序 + 未选中项兜底
      for (const s of await page.locator('select').all()) {
        const v = await s.inputValue().catch(() => null)
        const opts = await s.locator('option').allTextContents()
        if ((v === '' || v === null) && opts.length > 1) {
          await s.selectOption({ index: 1 }).catch(() => {})
          return opts[1]
        }
      }
      return null
    }
    const picked = []
    for (let i = 0; i < 3; i++) { const r = await pick(); if (r) picked.push(r) }
    const file = page.locator('input[type="file"]').first()
    if (await file.count()) await file.setInputFiles(join(ROOT, 'out', 'fixture-1440.png')).catch(() => {})
    for (const name of ['散剪', '整卷']) {
      const cb = page.getByRole('checkbox', { name }).first()
      if (await cb.count()) { await cb.check().catch(() => {}); break }
    }
    await page.getByText(/请至少添加 1 种售卖方式|散剪/).first().click({ timeout: 3000 }).catch(() => {})
    await page.waitForTimeout(800)
    await shot(page, 'w5-product-form')
    const allBtns = await page.getByRole('button').allInnerTexts().catch(() => [])
    let saveText = ''
    for (const re of [/^保存$/, /^创建$/, /^提交$/, /^确定$/, /保存/, /创建/, /提交/]) {
      const b = page.getByRole('button', { name: re }).last()
      if (await b.count()) {
        saveText = (await b.textContent().catch(() => ''))?.trim() || String(re)
        await b.click({ timeout: 8000 }).catch(() => {})
        break
      }
    }
    await page.waitForTimeout(4000)
    const after = psql(`select count(*)::int as n from products where tenant_id=${TENANT_ID}`)[0]?.n
    const row = psql(`select id, name, status, base_price from products where tenant_id=${TENANT_ID} and name='${pname}'`)[0]
    rec(row ? 'pass' : 'fail', 'P4D-3', '商品管理员在「商品管理」页建商品（UI 操作 → DB 落库）',
      `建前 ${before} → 建后 ${after}；保存按钮=「${saveText}」；下拉选中=${JSON.stringify(picked)}；最新行=${JSON.stringify(row)}；弹窗按钮=${JSON.stringify(allBtns.slice(-8))}`,
      ['out/shots/w5-product-form.png', 'SQL: select * from products where name=…'])
    await shot(page, 'w5-product-after')
  } catch (e) {
    rec('fail', 'P4D-3', '商品管理员建商品异常', String(e).slice(0, 300))
    await shot(page, 'w5-product-error').catch(() => {})
  } finally { await ctx.close().catch(() => {}) }
}

async function main() {
  const fx = await fixtureOrder()
  const browser = await launch()
  await uiTicket(browser, fx.orderNo)
  await uiProduct(browser)
  await browser.close()
  const counts = R.reduce((a, x) => ({ ...a, [x.state]: (a[x.state] || 0) + 1 }), {})
  writeFileSync(join(OUT, 'p4d-writes2.json'), JSON.stringify(scrub({
    at: new Date().toISOString(), subjectSha: SUBJECT_SHA, tenantId: TENANT_ID, stamp, counts, rows: R, fixture: fx,
  }), null, 2))
  log(`== p4d counts: ${JSON.stringify(counts)}`)
  for (const x of R) log(`  [${x.state}] ${x.id} ${x.name} — ${x.detail.slice(0, 300)}`)
}
main().catch((e) => { console.error('p4d 失败:', e); process.exit(1) })
