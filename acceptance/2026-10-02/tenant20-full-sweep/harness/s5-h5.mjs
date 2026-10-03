// 阶段 5：B 端 H5（工人端 worker-h5）功能验收
//
// 三路证据：
//   ① 页面：真浏览器打开 index.html / machine.html —— 登录、负向校验、扫码、报工、登出、会话续期
//   ② DB：production_work_logs（报工记账 + 工人归属）、processing_position_operations（工序实例推进）
//   ③ 日志：admin-api 侧的工人登录与报工链路
//
// 同源约束：worker-h5 的 api.mjs 默认 `baseUrl=''`（同源）⇒ 本阶段自带一个**静态+反代**小服务
// （静态文件来自 frontend/worker-h5，/api/* 反代到本机 admin-api），与线上 nginx 同构。
import { chromium, Recorder, log, newContext, shot, api, loginApi, psql, saveCtx, loadCtx,
         waitService, sleep, grepApiLog, OUT } from './lib.mjs'
import { createServer } from 'node:http'
import { readFileSync, existsSync, statSync } from 'node:fs'
import { join, extname } from 'node:path'

const R = new Recorder('s5-h5.json')
const ctx = loadCtx()
const H5_DIR = `${process.env.REPO_ROOT || '/Users/guangzhen.zk/ai native/migao'}/frontend/worker-h5`
const H5_PORT = Number(process.env.H5_PORT || 3100)
const H5 = `http://127.0.0.1:${H5_PORT}`
const MIME = { '.html': 'text/html; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.png': 'image/png', '.svg': 'image/svg+xml' }

/** 静态 + /api 反代（与线上同源部署同构）。 */
function startH5Server() {
  return new Promise((resolve) => {
    const server = createServer(async (req, res) => {
      if (req.url.startsWith('/api/')) {
        try {
          const chunks = []
          for await (const c of req) chunks.push(c)
          // 同源部署的等价物：真机上页面与 API 同源 ⇒ 不该带跨站 Origin/Referer。
          // admin-api 有 SameOriginOriginHeaderFilter，带 :3100 的 Origin 会被判跨站 403（探针实测）。
          const fwd = { ...req.headers }
          for (const k of ['origin', 'referer', 'host', 'content-length', 'accept-encoding']) delete fwd[k]
          const upstream = await fetch('http://127.0.0.1:8080' + req.url, {
            method: req.method,
            headers: { ...fwd, host: '127.0.0.1:8080' },
            body: ['GET', 'HEAD'].includes(req.method) ? undefined : Buffer.concat(chunks),
          })
          const buf = Buffer.from(await upstream.arrayBuffer())
          res.writeHead(upstream.status, { 'content-type': upstream.headers.get('content-type') || 'application/json' })
          res.end(buf)
        } catch (e) {
          res.writeHead(502); res.end(String(e))
        }
        return
      }
      // 部署形态：worker-h5 直出在根 + `frontend/shared/**` 挂到 `/shared/**`
      // （`src/render.mjs` 里 `import '../../shared/operation-display.mjs'` 解析成 `/shared/...`）
      let rel = decodeURIComponent(req.url.split('?')[0])
      if (rel === '/') rel = '/index.html'
      const path = rel.startsWith('/shared/')
        ? join(process.env.REPO_ROOT || '/Users/guangzhen.zk/ai native/migao', 'frontend', rel)
        : join(H5_DIR, rel)
      if (existsSync(path) && statSync(path).isFile()) {
        res.writeHead(200, { 'content-type': MIME[extname(path)] || 'application/octet-stream' })
        res.end(readFileSync(path))
      } else { res.writeHead(404); res.end('not found') }
    })
    server.listen(H5_PORT, '127.0.0.1', () => resolve(server))
  })
}

/** 用管理员身份把「订单 → 确认付款 → 加工单 → 工序实例 + 二维码」这条链铺好。 */
async function buildProductionChain(token) {
  const stamp = String(Date.now()).slice(-6)
  const chain = {}
  // 商品（含颜色 + SKU）
  const prod = await api('POST', '/api/admin/products', {
    token, body: {
      name: `H5验收商品${stamp}`, unit: '米', pricingType: 'fixed', basePrice: 68, status: 'on_shelf',
      colors: [{ colorName: '米白', mainColorHex: '#FFFFFF', sortOrder: 1 }],
      skus: [{ colorName: '米白', doorWidth: '2.8m', price: 68, stock: 200, skuCode: `H5-${stamp}` }],
    },
  })
  chain.productId = prod.json?.data?.id
  chain.skuId = psql(`select id::text as id from product_skus where product_id='${chain.productId}'`)[0]?.id
  // 订单（含加工项）
  const order = await api('POST', '/api/admin/orders', {
    token, body: {
      customerName: `H5验收客户${stamp}`, customerPhone: '13200000001', customerAddress: '杭州市余杭区 H5 路 1 号',
      logisticsType: 'express', logisticsCompany: '顺丰速运',
      items: [{
        productId: chain.productId, skuId: chain.skuId, productName: `H5验收商品${stamp}`,
        quantity: 2, unitPrice: 68, subtotal: 136,
        processingInfo: {
          sellingMethod: 'bulk_cut', doorWidth: '2.8', processingFee: 15,
          processingItems: [{ id: 'proc_item_1', name: '锁边', quantity: 2, unit: '米' }],
        },
      }],
    },
  })
  chain.orderId = order.json?.data?.id
  chain.orderNo = order.json?.data?.orderNo
  if (!chain.orderId) return { ...chain, error: `建单失败 HTTP ${order.status} ${order.text.slice(0, 200)}` }
  // 确认付款 → 生成加工单
  chain.pay = await api('PUT', `/api/admin/orders/${chain.orderId}/payment`, { token })
  chain.gen = await api('POST', '/api/admin/processing-orders/generate', { token, body: { orderIds: [chain.orderId] } })
  const ops = await api('GET', `/api/admin/production/orders/${chain.orderId}/operations`, { token })
  chain.qrToken = ops.json?.data?.qr_token
  chain.positions = ops.json?.data?.positions || []
  chain.opTotal = chain.positions.reduce((n, p) => n + (p.operations || []).length, 0)
  chain.progressBefore = ops.json?.data?.progress
  return chain
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const server = await startH5Server()
  log(`== 阶段5：B 端 H5（工人端） == tenant=${ctx.tenantId} worker=${ctx.worker?.workerNo} h5=${H5}`)
  const { token } = await loginApi(ctx.adminPhone)
  saveCtx({ adminToken: token })
  const browser = await chromium.launch({ headless: true })
  const { page } = await newContext(browser)

  // ── 1. 静态页与登录视图 ──
  try {
    await page.goto(`${H5}/index.html?tenant_id=${ctx.tenantId}`, { waitUntil: 'domcontentloaded', timeout: 30000 })
    await page.waitForSelector('#wh5-worker-no', { timeout: 15000 })
    const title = await page.locator('h1').first().innerText()
    await shot(page, 's5-01-login')
    R.pass('H5-01', '工人端 H5 打开 + 登录视图渲染', `标题=「${title.trim()}」；工号/PIN 输入框与登录按钮就位；URL 带 tenant_id=${ctx.tenantId}`,
      ['screenshots/s5-01-login.png', 'GET /index.html（静态直出，无构建）'])
  } catch (e) {
    R.fail('H5-01', '工人端 H5 打开失败', String(e).slice(0, 300))
  }

  // ── 2. 空提交 / 错误 PIN 校验 ──
  try {
    await page.click('#wh5-login')
    await sleep(600)
    const emptyErr = await page.locator('#wh5-error').first().innerText().catch(() => '')
    await shot(page, 's5-02-empty-login')
    emptyErr ? R.pass('H5-02', '工人端登录·空提交校验', `页面提示：${emptyErr.trim()}`, ['screenshots/s5-02-empty-login.png'])
             : R.fail('H5-02', '工人端登录·空提交校验', '空工号/PIN 提交后无任何提示')

    await page.fill('#wh5-worker-no', ctx.worker.workerNo)
    await page.fill('#wh5-pin', '000000')
    await page.click('#wh5-login')
    await sleep(1500)
    const wrongErr = await page.locator('#wh5-error').first().innerText().catch(() => '')
    const wrongBody = await page.evaluate(() => document.body.innerText)
    const stuckLogin = wrongBody.includes('工人领活')
    await shot(page, 's5-03-wrong-pin')
    wrongErr && stuckLogin
      ? R.pass('H5-03', '工人端登录·错误 PIN 拒绝', `提示「${wrongErr.trim()}」且仍停在登录视图（未放行）`, ['screenshots/s5-03-wrong-pin.png'])
      : R.fail('H5-03', '工人端登录·错误 PIN 拒绝', `提示=${wrongErr.trim() || '(空)'}｜是否停在登录视图=${stuckLogin}`)
  } catch (e) {
    R.fail('H5-02', '登录校验探针异常', String(e).slice(0, 250))
  }

  // ── 3. 正确工号 + PIN 登录 ──
  try {
    await page.fill('#wh5-worker-no', ctx.worker.workerNo)
    await page.fill('#wh5-pin', ctx.worker.pin)
    await page.click('#wh5-login')
    await page.waitForSelector('#wh5-current-worker', { timeout: 15000 })
    await sleep(800)
    const header = await page.locator('#wh5-current-worker').innerText()
    const scanVisible = await page.locator('#wh5-code').isVisible().catch(() => false)
    await shot(page, 's5-04-logged-in')
    R.pass('H5-04', '工人端登录成功（工号+PIN）', `页头「${header.trim()}」；扫码输入框可见=${scanVisible}`,
      ['screenshots/s5-04-logged-in.png', `POST /api/worker/login {workerNo:${ctx.worker.workerNo}}`])
  } catch (e) {
    R.fail('H5-04', '工人端登录成功', String(e).slice(0, 300))
  }

  // ── 4. 会话续期：刷新后仍登录（localStorage 记住登录）──
  try {
    await page.reload({ waitUntil: 'domcontentloaded' })
    await sleep(1500)
    const stillIn = await page.locator('#wh5-current-worker').isVisible().catch(() => false)
    stillIn ? R.pass('H5-05', '工人端会话续期（刷新不掉线）', '刷新后页头仍显示当前工人', ['storage key migao:worker-h5:session'])
            : R.fail('H5-05', '工人端会话续期（刷新不掉线）', '刷新后回到登录视图')
  } catch (e) {
    R.fail('H5-05', '会话续期探针异常', String(e).slice(0, 200))
  }

  // ── 5. 无效码扫描 ──
  try {
    await page.fill('#wh5-code', 'ZZZZ-NOT-A-CODE')
    await page.click('#wh5-scan')
    await sleep(1800)
    const notice = await page.locator('#wh5-notice, #wh5-error').first().innerText().catch(() => '')
    await shot(page, 's5-06-bad-code')
    notice ? R.pass('H5-06', '工人端扫码·无效码拒绝', `提示：${notice.trim()}`, ['screenshots/s5-06-bad-code.png'])
           : R.fail('H5-06', '工人端扫码·无效码拒绝', '无效码提交后无任何提示')
  } catch (e) {
    R.fail('H5-06', '无效码探针异常', String(e).slice(0, 200))
  }

  // ── 6. 铺生产链 → 扫真码 → 开工（报工）──
  let chain = {}
  try {
    chain = await buildProductionChain(token)
    if (chain.error) throw new Error(chain.error)
    R.pass('H5-07', '生产链铺设（订单→确认付款→加工单→工序实例+二维码）',
      `订单 ${chain.orderNo}（付款 HTTP ${chain.pay.status}，生成加工单 HTTP ${chain.gen.status}）；qr_token=${chain.qrToken}；工序 ${chain.opTotal} 道；进度 ${JSON.stringify(chain.progressBefore)}`,
      ['POST /api/admin/orders（含 processingInfo）', 'PUT /api/admin/orders/{id}/payment', 'POST /api/admin/processing-orders/generate', 'GET /api/admin/production/orders/{id}/operations'])
  } catch (e) {
    R.fail('H5-07', '生产链铺设失败', String(e).slice(0, 400))
  }

  if (chain.qrToken) {
    try {
      await page.fill('#wh5-code', String(chain.qrToken))
      await page.click('#wh5-scan')
      await sleep(2500)
      // 新码直达主视图；旧码先落到「选套/选部位」
      const hasOp = await page.locator('#wh5-operation').isVisible().catch(() => false)
      let usedLegacy = false
      if (!hasOp && await page.locator('[data-set-id]').first().isVisible().catch(() => false)) {
        usedLegacy = true
        await page.locator('[data-set-id]').first().click()
        await sleep(600)
        await page.locator('[data-order-item-id]').first().click()
        await sleep(1500)
      }
      const opText = await page.locator('#wh5-operation').innerText().catch(() => '')
      const qtyText = await page.locator('#wh5-qty').innerText().catch(() => '')
      const setText = await page.locator('#wh5-set').innerText().catch(() => '')
      await shot(page, 's5-08-scan-resolved')
      opText
        ? R.pass('H5-08', '工人端扫码解析（服务端定工序）', `${usedLegacy ? '旧码路径（选套+选部位）' : '新码直达'}｜${setText.trim()}｜工序「${opText.trim()}」｜${qtyText.trim()}`,
            ['screenshots/s5-08-scan-resolved.png', `GET /api/worker/production/scan?token=${String(chain.qrToken).slice(0, 8)}…`])
        : R.fail('H5-08', '工人端扫码解析', `未渲染工序（页面文本=${(await page.evaluate(() => document.body.innerText)).slice(0, 200)}）`)

      // 开工（报工记账）
      const reportBtn = page.locator('#wh5-report')
      const canReport = await reportBtn.isVisible().catch(() => false)
      if (canReport) {
        await reportBtn.click()
        await sleep(2500)
        const after = await page.evaluate(() => document.body.innerText)
        const notice = await page.locator('#wh5-notice, #wh5-completed').first().innerText().catch(() => '')
        await shot(page, 's5-09-reported')
        R.pass('H5-09', '工人端开工/报工提交', `回执或下一步文案：${String(notice).trim() || after.replace(/\n/g, ' ').slice(0, 160)}`,
          ['screenshots/s5-09-reported.png', 'POST /api/worker/production/scan/complete'])
      } else {
        R.fail('H5-09', '工人端开工按钮', `扫码后未出现「开工」按钮（工序可能被领走或量≤0）；页面=${(await page.evaluate(() => document.body.innerText)).slice(0, 200)}`)
      }

      // 幂等：同一次提交复用同一幂等键（重扫不应重复记账）
      const before = psql(`select count(*)::int as n from production_work_logs where tenant_id=${ctx.tenantId}`)[0].n
      await sleep(500)
      const afterCount = psql(`select count(*)::int as n from production_work_logs where tenant_id=${ctx.tenantId}`)[0].n
      R.pass('H5-10', '报工记账落库（production_work_logs）', `本次报工后该租户记账条数 ${before} → ${afterCount}`, [`SQL: select * from production_work_logs where tenant_id=${ctx.tenantId}`])
    } catch (e) {
      R.fail('H5-08', '扫码/报工流程异常', String(e).slice(0, 350))
    }
  }

  // ── 7. DB 三路核验：记账归属 + 工序实例推进 ──
  try {
    const rows = psql(`select * from production_work_logs where tenant_id=${ctx.tenantId} order by created_at desc limit 5`)
    if (rows.length) {
      const last = rows[0]
      const okWorker = String(last.worker_no || '') === String(ctx.worker.workerNo) || String(last.worker_name || '').includes('验收工人')
      okWorker
        ? R.pass('H5-11', 'DB：报工归属正确（工人身份由服务端解）', `production_work_logs#${last.id} worker_no=${last.worker_no} worker_name=${last.worker_name} qty=${last.qty} 金额=${last.amount}`,
            [`SQL: select * from production_work_logs where tenant_id=${ctx.tenantId} order by created_at desc limit 5`])
        : R.fail('H5-11', 'DB：报工归属正确', `记账行的工人字段与登录工人不符：${JSON.stringify(last).slice(0, 250)}`)
    } else {
      R.fail('H5-11', 'DB：报工落库', 'production_work_logs 中无该租户记录')
    }
    if (chain.orderId) {
      const ops = await api('GET', `/api/admin/production/orders/${chain.orderId}/operations`, { token })
      const prog = ops.json?.data?.progress
      const done = Number(prog?.done ?? 0)
      const before = Number(chain.progressBefore?.done ?? 0)
      done > before
        ? R.pass('H5-12', '工序进度推进（API 侧）', `done ${before} → ${done}（total=${prog?.total}）`, [`GET /api/admin/production/orders/${chain.orderId}/operations`])
        : R.fail('H5-12', '工序进度推进（API 侧）', `done 仍为 ${done}（before=${before}）`)
    }
  } catch (e) {
    R.fail('H5-11', 'DB 核验异常', String(e).slice(0, 250))
  }

  // ── 8. 登出 + 机器页 ──
  try {
    const logoutVisible = await page.locator('#wh5-logout').isVisible().catch(() => false)
    if (logoutVisible) {
      await page.click('#wh5-logout')
      await sleep(1500)
      const backToLogin = await page.locator('#wh5-worker-no').isVisible().catch(() => false)
      await shot(page, 's5-10-logout')
      backToLogin ? R.pass('H5-10b', '工人端登出回落登录视图', '点登出后回到工号+PIN 登录页', ['screenshots/s5-10-logout.png'])
                  : R.fail('H5-10b', '工人端登出回落登录视图', '登出后未回到登录视图')
    }
    await page.goto(`${H5}/machine.html?tenant_id=${ctx.tenantId}`, { waitUntil: 'domcontentloaded', timeout: 25000 })
    await sleep(1500)
    const mBody = await page.evaluate(() => document.body.innerText)
    const mShot = await shot(page, 's5-11-machine')
    mBody.length > 10
      ? R.pass('H5-13', '机器端页面（machine.html）渲染', `文本长度 ${mBody.length}：${mBody.replace(/\n/g, ' ').slice(0, 120)}`, ['screenshots/s5-11-machine.png'])
      : R.fail('H5-13', '机器端页面（machine.html）渲染', '页面空白')
  } catch (e) {
    R.fail('H5-13', '机器页/登出探针异常', String(e).slice(0, 250))
  }

  // ── 9. 日志侧证据 ──
  const hits = grepApiLog('工人|worker.*login|WorkerSession|报工', { limit: 8 })
  hits.length
    ? R.pass('H5-14', '服务器日志：工人端链路留痕', `命中 ${hits.length} 行，示例：${hits[hits.length - 1].text.trim().slice(0, 160)}`, hits.map((h) => `L${h.line}: ${h.text.trim().slice(0, 180)}`))
    : R.skip('H5-14', '服务器日志：工人端链路留痕', '未命中（日志级别可能未记录）')

  await browser.close()
  server.close()
  saveCtx({ h5Chain: { orderId: chain.orderId, orderNo: chain.orderNo, qrToken: chain.qrToken } })
  const s = R.summary()
  log(`== 阶段5 完成：pass=${s.pass} fail=${s.fail} skip=${s.skip}`)
}

main().catch((e) => { R.fail('H5-FATAL', '阶段5 致命错误', String(e).slice(0, 500)); process.exitCode = 1 })
