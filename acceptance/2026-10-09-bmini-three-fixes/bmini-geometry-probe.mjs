/**
 * B 端 H5（app.migaozn.com/b/）几何探针 —— **独立验收用**（不是开发者的自证）
 *
 * 目的：把用户 2026-10-09 反馈的两条「看得见」缺陷变成**机器读数**：
 *   ① #6596：聊天页输入条被自绘底栏遮挡（读数 = 输入条底边 − 底栏顶边 > 0 即重叠）
 *   ② #6597：「卡在哪」标签换行（读数 = 标签文本的行盒数 / 是否超出容器）
 *
 * 做法：真浏览器（本地 Chrome）+ 真线上页面，但**把后端 API 用 route 桩掉**（只读渲染，
 * 不产生任何真实写请求），并塞一个未过期的 JWT 形状 token 让 `checkAuth()` 通过
 * ⇒ 页面按登录态渲染真实的 MessageInput / MerchantTabBar / 任务标签。
 *
 * 用法：cd <repo>/tests && node /tmp/mg-probe/bmini-geometry.mjs [BASE_URL]
 * 输出：stdout 一行 JSON（机器读数）+ 截图（PNG 路径）
 */
// Playwright 由调用方提供：优先 `PLAYWRIGHT_PATH`，否则按仓内 `tests/node_modules`（脚本所在位置的相对路径）解析
const PW = process.env.PLAYWRIGHT_PATH
  || new URL('../../tests/node_modules/playwright/index.mjs', import.meta.url).href
const { chromium } = await import(PW)
import fs from 'node:fs'
import path from 'node:path'
import { createHash } from 'node:crypto'

const BASE = (process.argv[2] || 'https://app.migaozn.com').replace(/\/$/, '')
/** 路径前缀：线上 = /b（app.migaozn.com/b/）；本地 dist 由 http.server 服务在根 = '' */
const PREFIX = process.env.PROBE_PREFIX ?? (BASE.includes('migaozn.com') ? '/b' : '')
const OUT_DIR = process.env.PROBE_OUT || '/tmp/mg-probe/out'
fs.mkdirSync(OUT_DIR, { recursive: true })

/** 未过期的 JWT 形状 token（`checkTokenValidity()` 只解 payload.exp） */
function fakeToken(expSecondsFromNow = 86400) {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64').replace(/=+$/, '')
  return `${b64({ alg: 'none', typ: 'JWT' })}.${b64({ exp: Math.floor(Date.now() / 1000) + expSecondsFromNow, sub: 'probe' })}.sig`
}

const USER = {
  id: 'probe-user',
  username: 'probe',
  nickname: '探针',
  role: 'admin',
  tenantId: 1,
  roles: ['admin'],
  permissions: ['production:view'],
  botName: '黄金策',
  tenantName: '探针环境',
  capabilities: { mibaoChat: true },
}

const TODO_OVERVIEW = {
  generated_at: new Date().toISOString(),
  todo_total: 12,
  todos: [
    {
      id: 't1',
      type: 'stuck',
      type_label: '卡在哪', // 真值来自服务端（3 个汉字）—— 正是换行的那一条
      priority: 'high',
      title: '订单 20261006497350118 · 打包 上道做完未开工',
      reason: '这道还没开工（没报过工），上一道已完成，已等待 74.6 小时（超过阈值 4.0 小时，来源：default）',
      criterion: 'stuck_not_started_over_threshold',
      link: '/pages/production/order-detail/index?order_id=O1',
      target: { order_id: 'O1' },
      evidence: {},
    },
    {
      id: 't2',
      type: 'to_schedule',
      type_label: '待排产',
      priority: 'medium',
      title: '订单 20261006620530119 · 韩褶',
      reason: '还没有排产',
      criterion: 'no_processing_order',
      link: '/pages/production/order-detail/index?order_id=O2',
      target: { order_id: 'O2' },
      evidence: {},
    },
    ...Array.from({ length: 10 }, (_, i) => ({
      id: `tx${i}`,
      type: 'stuck',
      type_label: '卡在哪',
      priority: 'high',
      title: `订单 20261006${5000000 + i} · 打包 上道做完未开工`,
      reason: '这道还没开工（没报过工），上一道已完成，已等待 74.6 小时（超过阈值 4.0 小时，来源：default）',
      criterion: 'stuck_not_started_over_threshold',
      link: '/pages/production/order-detail/index?order_id=O' + i,
      target: {},
      evidence: {},
    })),
  ],
  stats: {
    todo_total: 12,
    by_type: { stuck: 1, to_schedule: 1 },
    operations: { not_started: 3, in_progress: 1, completed: 6 },
    stuck_threshold_hours: 4,
    threshold_source: 'default',
    scan: { order_scan_limit: 50, truncated: false },
  },
}


/** Taro H5 会把已离开的页面留在 DOM（隐藏页）⇒ 必须挑**可见**的那个，否则读数会取到隐藏页 */
const VIS = `(sel) => {
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect()
    if (r.width > 0 && r.height > 0) return el
  }
  return null
}`

async function main() {
  const browser = await chromium.launch({ channel: 'chrome' })
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, // iPhone 12/13（与 tests/playwright.bmini.config.ts 同口径）
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  })

  // 先把登录态塞进 localStorage（Taro H5 的 storage 即 localStorage）
  await context.addInitScript(
    ([token, user]) => {
      try {
        // 🔴 Taro H5 的 setStorageSync 写的是 `JSON.stringify({data})`（读时取 .data）
        const wrap = (v) => JSON.stringify({ data: v })
        localStorage.setItem('auth_token', wrap(token))
        localStorage.setItem('auth_user', wrap(user))
        localStorage.setItem('tenant_id', wrap(1))
      } catch {}
    },
    [fakeToken(), USER],
  )

  const page = await context.newPage()
  let stuckPointRequests = 0

  // 只读桩：所有后端 API 都不真打（避免在测试环境产生真实副作用）
  await page.route('**/api/**', async (route) => {
    const url = route.request().url()
    const json = (data) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data }) })
    if (url.includes('/api/auth/me')) return json(USER)
    if (url.includes('/api/admin/production/todo-overview')) return json(TODO_OVERVIEW)
    if (url.includes('/api/admin/production/stuck-points')) {
      stuckPointRequests += 1
      return json({
        // 🔴 逐字照服务端 `ProductionStuckPointService.report()` 的行形状
        // （不是我自己发明的键名 —— 第一版探针用 operation_name/position_name 取不到工序名，
        //   那是**探针**的错，不是实现的错）
        mode: 'A',
        threshold_hours: 4,
        threshold_source: 'default',
        scope: { processing_order_id: 'PO1' },
        states: { not_started: 1, in_progress: 0, completed: 6 },
        stuck_total: 1,
        stuck: [
          {
            kind: 'not_started',
            processing_order_id: 'PO1',
            set_id: 'S1',
            set_no: '1',
            set_index: 1,
            position: { order_item_id: 'OI1', position_kind: 'curtain', position_name: '布帘' },
            operation: {
              operation_id: 'op7', logical_name: '打包', position: null, seq: 7,
              unit: '套', qty: 1, done_qty: 0, state: 'not_started',
            },
            predecessor: {
              operation_id: 'op1', logical_name: '精裁', seq: 1,
              done_at: new Date(Date.now() - 74.6 * 3600 * 1000).toISOString(),
            },
            stalled_hours: 74.6,
            threshold_hours: 4,
            threshold_source: 'default',
          },
        ],
      })
    }
    if (/\/api\/admin\/processing-orders\/[^/]+$/.test(url)) {
      return json({
        id: 'PO1', orderId: 'O1', orderNo: '20261006497350118',
        processingOrderNo: 'JG-20261006-8477', customerName: 'SD07演示客814127-095',
        expectedDeliveryDate: '2026-10-20',
      })
    }
    if (/\/api\/admin\/production\/orders\/[^/]+\/operations$/.test(url)) {
      return json({
        order_id: 'O1',
        progress: { done: 6, total: 9 },
        positions: [
          {
            position_name: '布帘',
            operations: [
              { id: 'op1', seq: 1, operation: '精裁-布', logical_name: '精裁', position: '布帘', group: 'g', unit: '米', qty: 6.2, unit_price: 1, is_must_finish: false, is_start_marker: true, status: 'done', done_qty: 6.2 },
              { id: 'op7', seq: 7, operation: '打包', logical_name: '打包', position: null, group: 'g', unit: '套', qty: 1, unit_price: 1, is_must_finish: false, is_start_marker: false, status: 'pending', done_qty: 0 },
              { id: 'op8', seq: 8, operation: '外帘装袋', logical_name: '外帘装袋', position: null, group: 'g', unit: '套', qty: 1, unit_price: 1, is_must_finish: false, is_start_marker: false, status: 'pending', done_qty: 0 },
            ],
          },
        ],
        work_logs: [],
      })
    }
    if (url.includes('/api/dashboard/stats') || url.includes('/api/dashboard')) {
      return json({ todaySales: 0, todayOrders: 0, monthRevenue: 0, todaySalesChange: 0, todayOrdersChange: 0, monthRevenueChange: 0 })
    }
    if (url.includes('/api/dashboard/tasks') || url.includes('/pending-tasks')) return json([])
    return json({})
  })

  // 线上 index.html 的字节指纹（= 被测版本的锚点；bmini 无内嵌 sha，只能用产物哈希）
  const resp = await page.goto(`${BASE}${PREFIX}/`, { waitUntil: 'domcontentloaded' })
  const servedHtml = await resp.text()
  const servedHash = createHash('sha256').update(servedHtml).digest('hex').slice(0, 16)

  // ── ① 聊天页：输入条 vs 自绘底栏 ──
  await page.goto(`${BASE}${PREFIX}/#/pages/chat/index/index`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.merchant-tabbar', { timeout: 20000 })
  await page.waitForTimeout(1500) // 等 MessageInput 挂载（授权门是异步的）
  await page.screenshot({ path: path.join(OUT_DIR, 'chat-page.png') })

  const chat = await page.evaluate(() => {
    const pick = (sel) => {
      for (const el of document.querySelectorAll(sel)) {
        const r = el.getBoundingClientRect()
        if (r.width > 0 && r.height > 0) return el
      }
      return null
    }
    const box = (sel) => {
      const el = pick(sel)
      if (!el) return null
      const r = el.getBoundingClientRect()
      return { top: +r.top.toFixed(1), bottom: +r.bottom.toFixed(1), height: +r.height.toFixed(1) }
    }
    return {
      viewportHeight: window.innerHeight,
      tabbar: box('.merchant-tabbar'),
      chatPage: box('.chat-page'),
      input: box('.message-input'),
      inputContainer: box('.message-input__container'),
      gateVisible: !!pick('.message-input'),
      bodyText: (document.body.innerText || '').slice(0, 200),
    }
  })

  // ── ② 「数据」页：待办标签是否换行 ──
  await page.goto(`${BASE}${PREFIX}/#/pages/dashboard/index/index`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.task-item__tag', { timeout: 20000 })
  await page.waitForTimeout(800)
  await page.screenshot({ path: path.join(OUT_DIR, 'dashboard-todo.png') })

  const tags = await page.evaluate(() => {
    const out = []
    const pickVis = (sel) => {
      for (const el of document.querySelectorAll(sel)) {
        const r = el.getBoundingClientRect()
        if (r.width > 0 && r.height > 0) return el
      }
      return null
    }
    for (const tag of document.querySelectorAll('.task-item__tag')) {
      if (tag.getBoundingClientRect().width === 0) continue // 隐藏页（Taro 留着上一页）不算
      const text = tag.querySelector('.task-item__tag-text') || tag
      const tr = text.getBoundingClientRect()
      const cr = tag.getBoundingClientRect()
      const cs = getComputedStyle(text)
      const lineHeight = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.2
      // Range 逐行盒：文本真的折了几行（比 height/lineHeight 更直接）
      let lineBoxes = 0
      try {
        const r = document.createRange()
        r.selectNodeContents(text)
        const tops = new Set([...r.getClientRects()].map((x) => Math.round(x.top)))
        lineBoxes = tops.size
      } catch {}
      out.push({
        lineBoxes,
        label: (text.textContent || '').trim(),
        lines: Math.round(tr.height / lineHeight),
        rects: text.getClientRects().length,
        textWidth: +tr.width.toFixed(1),
        tagWidth: +cr.width.toFixed(1),
        overflow: tr.width > cr.width + 0.5,
        tagHeight: +cr.height.toFixed(1),
      })
    }
    return out
  })

  // ── ③ 同类形态探测：底栏浮层是否让「最后一个待办」**永久不可达**（滚到底也看不到） ──
  const bottom = await page.evaluate(async () => {
    const pickVis = (sel) => {
      for (const el of document.querySelectorAll(sel)) {
        const r = el.getBoundingClientRect()
        if (r.width > 0 && r.height > 0) return el
      }
      return null
    }
    const items = document.querySelectorAll('.task-item')
    const last = items[items.length - 1]
    const bar = pickVis('.merchant-tabbar')
    if (!last || !bar) return null
    // 找最近的可滚动祖先（Taro 的 ScrollView）
    let sc = last.parentElement
    while (sc && sc !== document.body) {
      const cs = getComputedStyle(sc)
      if (/(auto|scroll)/.test(cs.overflowY) && sc.scrollHeight > sc.clientHeight + 1) break
      sc = sc.parentElement
    }
    if (sc && sc !== document.body) sc.scrollTop = sc.scrollHeight
    await new Promise((r) => setTimeout(r, 400))
    const lr = last.getBoundingClientRect()
    const br = bar.getBoundingClientRect()
    return {
      scrollContainer: sc && sc !== document.body ? sc.className || sc.tagName : null,
      lastItemBottom: +lr.bottom.toFixed(1),
      tabbarTop: +br.top.toFixed(1),
      /** > 0 ⇒ 滚到底之后最后一行仍被底栏压住 ⇒ 永久不可达 */
      lastItemCoveredPx: +(lr.bottom - br.top).toFixed(1),
    }
  })

  // ── ④ 加工单详情（从「卡在哪」待办点进来的落点）：有没有把「卡在哪」显示出来 ──
  await page.goto(`${BASE}${PREFIX}/#/pages/production/order-detail/index?order_id=20261006497350118`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2500)
  await page.screenshot({ path: path.join(OUT_DIR, 'order-detail.png') })

  const orderDetail = await page.evaluate(() => {
    // 用页面自身的根 class 定位（Taro 会把来过的页面都留在 DOM 里 ⇒ 不能用「最后一个可见页」猜）
    const root = document.querySelector('.order-detail')
    if (!root) return { rendered: false, text: '', mentionsStuck: false }
    const txt = (root.innerText || '').replace(/\s+/g, ' ')
    return {
      rendered: true,
      text: txt.slice(0, 500),
      /** 页面上有没有「卡在哪」类的信息（等待时长 / 卡点 / 阈值） */
      mentionsStuck: /卡在哪|卡点|已等待|超过阈值|等待\s*[0-9]/.test(txt),
      hasHeader: !!document.querySelector('[data-testid="order-detail-header"]'),
      hasOperations: !!document.querySelector('[data-testid="order-detail-operations"]'),
    }
  })
  orderDetail.stuckPointRequests = stuckPointRequests

  await browser.close()

  const overlap =
    chat.input && chat.tabbar ? +(chat.input.bottom - chat.tabbar.top).toFixed(1) : null

  const result = {
    base: BASE,
    servedIndexSha256_16: servedHash,
    viewport: { w: 390, h: 844 },
    chatInput: {
      rendered: chat.gateVisible,
      tabbarTop: chat.tabbar ? chat.tabbar.top : null,
      inputBottom: chat.input ? chat.input.bottom : null,
      inputHeight: chat.input ? chat.input.height : null,
      /** > 0 ⇒ 输入条被底栏压住（被遮挡像素数） */
      coveredPx: overlap,
      coveredVerdict: overlap === null ? 'UNDECIDABLE' : overlap > 0 ? 'COVERED' : 'OK',
      viewportHeight: chat.viewportHeight,
      chatPageHeight: chat.chatPage ? chat.chatPage.height : null,
    },
    todoTags: tags,
    dashboardBottomReach: bottom,
    orderDetail: orderDetail,
    tagWrapVerdict: tags.length === 0 ? 'UNDECIDABLE' : tags.some((t) => t.lineBoxes > 1 || t.lines > 1 || t.overflow) ? 'WRAPPED' : 'OK',
    screenshots: [path.join(OUT_DIR, 'chat-page.png'), path.join(OUT_DIR, 'dashboard-todo.png')],
    note: chat.gateVisible ? null : '聊天页输入条未渲染（授权门/会话未就绪）—— 聊天页读数不可用',
  }

  fs.writeFileSync(path.join(OUT_DIR, 'readings.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result, null, 2))
}

main().catch((e) => {
  console.error('PROBE FAILED:', e.message)
  process.exit(1)
})
