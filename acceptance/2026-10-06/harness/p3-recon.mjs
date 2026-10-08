// p3-recon：写面侦察 —— 每个岗位在**自己的页面**上点「新建/新增」，把弹窗里的输入控件与按钮逐字 dump 出来。
// 目的：写面旅程的选择器必须**来自页面自身的 DOM**（不是猜的），侦察产物 = out/p3-recon.json。
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { OUT, WEB } from './lib.mjs'
import { launch, newPage, loginEmployeeUi, loginAdminUi, shot } from './ui.mjs'

const SESSION = JSON.parse(readFileSync(process.env.A06_SESSION || '/tmp/a06-session.json', 'utf8'))
const EMP_PWD = 'Migao@2026x'

const TARGETS = [
  { role: 'admin', path: '/employees', ident: null },
  { role: 'product_manager', path: '/products', ident: 'a06_product_manager' },
  { role: 'sales', path: '/orders', ident: 'a06_sales' },
  { role: 'finance', path: '/finance', ident: 'a06_finance' },
  { role: 'knowledge_editor', path: '/knowledge', ident: 'a06_knowledge_editor' },
  { role: 'operator', path: '/inbound-orders', ident: 'a06_operator' },
  { role: 'customer_service', path: '/after-sales', ident: 'a06_customer_service' },
]

const dump = async (page) => page.evaluate(() => {
  const vis = (el) => {
    const r = el.getBoundingClientRect()
    const s = getComputedStyle(el)
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'
  }
  const scopes = Array.from(document.querySelectorAll('[role="dialog"], [class*="Modal"], [class*="modal"]'))
  const scope = scopes.find(vis) || document
  const inputs = Array.from(scope.querySelectorAll('input, textarea, select')).filter(vis).map((el) => ({
    tag: el.tagName.toLowerCase(),
    id: el.id || null,
    name: el.getAttribute('name'),
    type: el.getAttribute('type'),
    placeholder: el.getAttribute('placeholder'),
    options: el.tagName === 'SELECT' ? Array.from(el.options).map((o) => o.textContent.trim()).slice(0, 12) : undefined,
  }))
  const buttons = Array.from(scope.querySelectorAll('button')).filter(vis).map((b) => (b.textContent || '').trim()).filter(Boolean)
  return { dialogOpen: scope !== document, inputs, buttons, bodyHead: (document.body.innerText || '').slice(0, 600) }
})

async function main() {
  const browser = await launch()
  const out = []
  for (const t of TARGETS) {
    const { ctx, page } = await newPage(browser)
    const rec = { ...t, ok: false }
    try {
      if (t.role === 'admin') await loginAdminUi(page, '13800138000')
      else await loginEmployeeUi(page, `${t.ident}@${SESSION.tenantCode}`, EMP_PWD)
      await page.goto(WEB + t.path, { waitUntil: 'domcontentloaded', timeout: 60000 })
      await page.waitForTimeout(2200)
      rec.pageShot = await shot(page, `recon-${t.role}-list`)
      rec.list = await dump(page)
      // 点「新建 / 新增 / 添加 / 创建」
      const btn = page.getByRole('button', { name: /新建|新增|添加|创建/ }).first()
      if (await btn.count()) {
        rec.buttonText = (await btn.textContent())?.trim()
        await btn.click({ timeout: 8000 }).catch((e) => { rec.clickError = String(e).slice(0, 160) })
        await page.waitForTimeout(2000)
        rec.dialogShot = await shot(page, `recon-${t.role}-dialog`)
        rec.dialog = await dump(page)
        rec.ok = true
      } else {
        rec.note = '页面上没有匹配 /新建|新增|添加|创建/ 的按钮'
      }
    } catch (e) {
      rec.error = String(e).slice(0, 300)
    }
    await ctx.close().catch(() => {})
    out.push(rec)
    console.log(`[${t.role}] ${t.path} ok=${rec.ok} button=${rec.buttonText || '-'} inputs=${rec.dialog?.inputs?.length ?? '-'}`)
  }
  await browser.close()
  writeFileSync(join(OUT, 'p3-recon.json'), JSON.stringify(out, null, 2))
}

main().catch((e) => { console.error(e); process.exit(1) })
