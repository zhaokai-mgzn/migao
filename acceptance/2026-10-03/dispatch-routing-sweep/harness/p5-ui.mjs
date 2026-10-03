// P5：**工序管理页 UI 面**（真实登录 + DOM 断言 + 截图）—— 设置面是否可达、是否与后端读数一致
//
// 只看「页面能不能把设置展示出来」与「停用按钮点下去会发生什么」；数值准确性由 p2/p3 的 API+DB 断言负责。
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { api, loginApi, one, log, OUT, waitService, Recorder } from './lib.mjs'
import { createRequire } from 'node:module'

const REPO_ROOT = process.env.REPO_ROOT || join(process.cwd(), '..', '..', '..', '..')
const { chromium } = createRequire(join(REPO_ROOT, 'tests', 'package.json'))('playwright')
const WEB = process.env.BASE_URL || 'http://localhost:3001'
const SMS = process.env.SMS_CODE || '123456'
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const T = Number(process.env.TENANT_ID || 20)

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p5-ui.json')
  const { token } = await loginApi(PHONE)
  const shots = join(OUT, 'screenshots')
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const consoleErrors = []
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)) })

  try {
    // 登录（管理员 tab + 短信万能码，与仓内既有 harness 同一路径）
    await page.goto(WEB + '/login', { waitUntil: 'domcontentloaded', timeout: 45000 })
    await page.getByRole('tab', { name: /管理员登录/ }).click()
    await page.waitForSelector('#phone', { timeout: 45000 })
    await page.fill('#phone', PHONE)
    await page.fill('#code', SMS)
    await page.getByRole('button', { name: /登\s*录|登录/ }).last().click()
    await page.waitForURL('**/dashboard**', { timeout: 45000 })

    await page.goto(WEB + '/production/routings', { waitUntil: 'domcontentloaded', timeout: 45000 })
    await page.waitForSelector('[data-testid="operations-search"], table', { timeout: 45000 })
    await page.waitForTimeout(2500)
    const body = await page.innerText('body')
    await page.screenshot({ path: join(shots, 'p5-01-routings.png'), fullPage: true })

    // ① 工序管理页把「一道工序一个价」的表 + 具名路线 + 主线都渲染出来
    const catalog = (await api('GET', '/api/admin/production/operations-catalog', { token })).json?.data?.groups
      ?.flatMap((g) => g.operations.map((o) => o.name)) || []
    const uniqOps = [...new Set(catalog)]
    const missing = uniqOps.filter((n) => !body.includes(n))
    const routings = (await api('GET', '/api/admin/production/routings', { token })).json?.data?.routings || []
    const missingRoutes = routings.map((r) => r.name).filter((n) => !body.includes(n))
    missing.length === 0 && missingRoutes.length === 0
      ? R.pass('UI-01', '工序管理页渲染出全部逻辑工序与全部路线',
          `页面含 ${uniqOps.length}/${uniqOps.length} 道逻辑工序、${routings.length}/${routings.length} 条路线（默认=「${routings.find((r) => r.is_default)?.name}」）`,
          [`GET ${WEB}/production/routings`, `截图 out/screenshots/p5-01-routings.png`])
      : R.fail('UI-01', '工序管理页渲染出全部逻辑工序与全部路线',
          `缺工序=${missing.join(',') || '无'}；缺路线=${missingRoutes.join(',') || '无'}`, [`截图 out/screenshots/p5-01-routings.png`])

    // ② 抽屉可开（设置面「管理▸」入口）
    // 行尾「管理▸」的 testid = `matrix-manage-<逻辑工序名>`（实测 DOM；`ManageButton` 未传 testIdPrefix 时另有 undefined-* 形态，两代并存）
    let target = process.env.UI_TARGET_OP || '质检'
    let manage = page.locator(`[data-testid="matrix-manage-${target}"]`).first()
    if (!(await manage.count())) {
      const any = page.locator('[data-testid^="matrix-manage-"]').first()
      if (await any.count()) { target = (await any.getAttribute('data-testid')).replace('matrix-manage-', ''); manage = any }
    }
    let drawerOpened = false
    if (await manage.count()) {
      await manage.scrollIntoViewIfNeeded()
      await manage.click()
      try { await page.waitForSelector('[data-testid="operations-manage-drawer"]', { timeout: 8000 }); drawerOpened = true } catch { /* 未开 */ }
    }
    await page.screenshot({ path: join(shots, 'p5-02-manage-drawer.png'), fullPage: false })
    drawerOpened
      ? R.pass('UI-02', `「管理▸」抽屉可打开（目标工序「${target}」）`, `抽屉 [data-testid=operations-manage-drawer] 已渲染`, [`截图 out/screenshots/p5-02-manage-drawer.png`])
      : R.fail('UI-02', '「管理▸」抽屉可打开', `未找到 [data-testid="matrix-manage-${target}"] 或抽屉未渲染`)

    // ③ 点「停用」—— 观察真实结果（后端词表 = active/disabled，前端发 inactive）
    if (drawerOpened) {
      const before = one(`select status from production_operations where tenant_id=${T} and name='${target}' and coalesce(deleted,0)=0`)?.status
      const btn = page.locator('[data-testid="operations-manage-disable"]').first()
      let clicked = false
      if (await btn.count()) { await btn.click(); clicked = true }
      await page.waitForTimeout(2500)
      const reasons = await page.locator('[data-testid="operations-manage-op-reasons"]').first().innerText().catch(() => '')
      await page.screenshot({ path: join(shots, 'p5-03-disable-result.png'), fullPage: false })
      const after = one(`select status from production_operations where tenant_id=${T} and name='${target}' and coalesce(deleted,0)=0`)?.status
      const uiFailed = /status|不支持|active\/disabled|失败/.test(reasons) || before === after
      writeFileSync(join(OUT, 'p5-disable.json'), JSON.stringify({ target, before, after, clicked, reasons }, null, 2))
      uiFailed
        ? R.fail('UI-03', '「停用工序」按钮端到端可用（UI 词表 ↔ 后端受理词表一致）',
            `点击后库里 status 仍 = ${after}（改前 ${before}）；页面理由 = 「${reasons.slice(0, 160)}」⇒ 按钮点了不生效`,
            [`截图 out/screenshots/p5-03-disable-result.png`, `SQL: select status from production_operations where name='${target}'`])
        : R.pass('UI-03', '「停用工序」按钮端到端可用', `status ${before} → ${after}`, [`截图 out/screenshots/p5-03-disable-result.png`])
      // 还原
      if (after !== before) await api('PUT', `/api/admin/production/operations/${one(`select id from production_operations where tenant_id=${T} and name='${target}' and coalesce(deleted,0)=0`)?.id}`, { token, body: { status: before } })
    }

    R.pass('UI-04', '页面控制台错误（观察项，不阻塞）', consoleErrors.length === 0 ? '无 console error' : `${consoleErrors.length} 条：${consoleErrors.slice(0, 3).join(' ｜ ').slice(0, 300)}`)
  } catch (e) {
    await page.screenshot({ path: join(shots, 'p5-error.png'), fullPage: true }).catch(() => {})
    R.fail('UI-00', 'UI 巡视执行', `异常：${String(e).slice(0, 300)}`)
  } finally {
    await browser.close()
  }
  log(`summary=${JSON.stringify(R.summary())}`)
}

main().catch((e) => { console.error(e); process.exit(1) })
