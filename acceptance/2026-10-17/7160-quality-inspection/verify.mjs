// 真栈多模态验收（issue #7160）——
// :3001 admin-web（dev，**本工作树**）+ 真登录 + 1440×980 截图 + 机器读数 + AI 读图。
//
// ⚠️ 本机 :8080 admin-api 是 **#7140 之前的构建**（实测 `GET /api/admin/quality-inspections/targets`
//    ⇒ 404 `NOT_FOUND`，见 result.liveApiProbe），且该租户当前无活跃加工单 ⇒ 待检清单真数据为 0 行。
//    因此**页面数据用 Playwright route 注入夹具**（真实前端 bundle / 真实样式 / 真实登录，只替换读面数据）；
//    端点的形状由后端单测 `QualityCheckTargetsTest`（判据 8）与本机实跑证明。
//
// 判据：
//   ① 待检清单有「订单号」列、**没有**「数量」列；订单号逐行渲染；
//   ② 点「录入判定」⇒ `role=dialog` **在视口内**当场可见（旧形态在列表最底部 ⇒ 点了像没反应）；
//   ③ 弹窗标题写明是哪一件成品帘；（弹窗体内是同一份表单）
//   ④ 「取消」⇒ 关闭、恢复 body 滚动；全程无 console.error。
import { createRequire } from 'node:module'
import { mkdirSync, writeFileSync } from 'node:fs'

const REPO_ROOT = '/Users/guangzhen.zk/ai native/migao'
const { chromium } = createRequire(`${REPO_ROOT}/tests/package.json`)('playwright')
const OUT = `${REPO_ROOT}/acceptance/2026-10-17/7160-quality-inspection`
mkdirSync(OUT, { recursive: true })
const BASE = 'http://localhost:3001'
const RESULT = { ok: false, apiMode: 'route-mocked（本机 admin-api 无 /targets）', checks: {}, consoleErrors: [] }

const TARGETS = {
  success: true,
  data: {
    items: [
      {
        order_item_id: 'item-a',
        processing_order_id: 'po-a',
        processing_order_no: 'JG-20261016-4441',
        order_no: 'DD-20261016-4411',
        processing_status: 'in_processing',
        product_name: '2699系列雪尼尔窗帘面料',
        color_name: '米白',
        quantity: 2,
        unit: '套',
        state: 'pending',
        latest: null,
      },
      {
        order_item_id: 'item-b',
        processing_order_id: 'po-b',
        processing_order_no: 'JG-20261016-4440',
        order_no: 'DD-20261016-4410',
        processing_status: 'in_processing',
        product_name: '2699系列雪尼尔窗帘面料',
        color_name: '浅灰',
        quantity: 2,
        unit: '套',
        state: 'pass',
        latest: {
          id: 'qi-b',
          order_item_id: 'item-b',
          processing_order_id: 'po-b',
          position_name: '2699系列雪尼尔窗帘面料 浅灰',
          result: 'pass',
          result_label: '合格',
          reason: null,
          inspector_name: '质检员小李',
          inspected_at: '2026-10-17T10:30:00+08:00',
        },
      },
    ],
    total: 2,
    page: 1,
    size: 20,
    counts: { pending: 1, pass: 1, rework: 0, scrap: 0 },
  },
}

const RECORDS = {
  success: true,
  data: [
    {
      id: 'qi-b',
      order_item_id: 'item-b',
      processing_order_id: 'po-b',
      position_name: '2699系列雪尼尔窗帘面料 浅灰',
      result: 'pass',
      result_label: '合格',
      reason: null,
      inspector_name: '质检员小李',
      inspected_at: '2026-10-17T10:30:00+08:00',
    },
  ],
}

const browser = await chromium.launch({ headless: true })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 980 } })
const page = await ctx.newPage()
page.on('console', (m) => {
  if (m.type() === 'error') RESULT.consoleErrors.push(m.text().slice(0, 200))
})

// 只替换读面数据；真实页面 bundle / 真实样式 / 真实路由照旧
await page.route('**/api/admin/quality-inspections/targets*', (route) =>
  route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TARGETS) }),
)
await page.route('**/api/admin/quality-inspections?*', (route) =>
  route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RECORDS) }),
)

// ── 真登录（persona 手机号 + 万能码，同 scripts/ui_smoke_merchant.sh） ──
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle', timeout: 60000 })
if (!(await page.locator('#phone').isVisible().catch(() => false))) {
  await page.getByRole('tab', { name: /手机/ }).click({ timeout: 10000 })
  await page.waitForSelector('#phone', { timeout: 10000 })
}
await page.fill('#phone', '13800138000')
await page.fill('#code', '123456')
await page.locator('button[type="submit"]:visible').last().click()
await page.waitForURL(/dashboard|\/settings|\/orders/, { timeout: 30000 }).catch(() => {})
await page.waitForTimeout(1500)
RESULT.checks.loggedIn = page.url().includes('/dashboard')

// 本机 admin-api 的实际形状（登录后同类请求，**不经页面 route**）：证明「为什么用夹具」
const live = await ctx.request
  .get(`http://localhost:8080/api/admin/quality-inspections/targets?page=1&size=20`, { timeout: 10000 })
  .catch(() => null)
RESULT.apiProbe = live ? { status: live.status(), body: (await live.text()).slice(0, 160) } : null

// ── 质检记录页 ──
await page.goto(`${BASE}/quality-inspections`, { waitUntil: 'domcontentloaded' })
await page.waitForSelector('[data-testid="quality-targets-card"]', { timeout: 30000 })
await page.waitForTimeout(1500)
RESULT.checks.url = page.url()

const headers = await page.$$eval('table th', (ths) => ths.map((t) => t.textContent.trim()))
RESULT.checks.headers = headers
RESULT.checks.hasOrderNoColumn = headers.includes('订单号')
RESULT.checks.hasNoQuantityColumn = !headers.includes('数量')
RESULT.checks.columnOrder = headers.filter((h) => ['加工单号', '订单号', '成品帘', '数量', '最新判定', '操作'].includes(h))

const rows = await page.$$eval('tbody tr[data-testid^="quality-target-"]', (trs) =>
  trs.slice(0, 3).map((tr) => Array.from(tr.querySelectorAll('td')).map((td) => td.textContent.trim())),
)
RESULT.checks.firstRows = rows
RESULT.checks.orderNoRendered = rows.length === 2 && rows[0][1] === 'DD-20261016-4411' && rows[1][1] === 'DD-20261016-4410'

// 旧形态：表单在页内（列表最底部）。点之前页面里必须没有它。
RESULT.checks.formAbsentBeforeClick =
  (await page.locator('[data-testid="quality-inspection-form"]').count()) === 0

await page.screenshot({ path: `${OUT}/待检清单-首屏.png` })
await page.screenshot({ path: `${OUT}/待检清单-整页.png`, fullPage: true })

// ── 点「录入判定」⇒ 弹窗 ──
await page.locator('tr[data-testid^="quality-target-"] [data-testid^="quality-target-record-"]').first().click()
await page.waitForSelector('[role="dialog"]', { timeout: 10000 })
const dialog = page.locator('[role="dialog"]')
const box = await dialog.boundingBox()
RESULT.checks.dialogBox = box
  ? { x: Math.round(box.x), y: Math.round(box.y), w: Math.round(box.width), h: Math.round(box.height) }
  : null
RESULT.checks.dialogInViewport = !!box && box.y >= 0 && box.y + box.height <= 980
RESULT.checks.dialogTitle = (await dialog.locator('h3').textContent())?.trim() ?? ''
RESULT.checks.dialogTitleHasSubject = RESULT.checks.dialogTitle.includes('2699系列雪尼尔窗帘面料')
RESULT.checks.dialogHasForm = (await dialog.locator('[data-testid="quality-inspection-form"]').count()) === 1
RESULT.checks.bodyScrollLocked = (await page.evaluate(() => document.body.style.overflow)) === 'hidden'
RESULT.checks.dialogButtons = (await dialog.locator('button').allInnerTexts()).map((t) => t.trim()).filter(Boolean)
await page.screenshot({ path: `${OUT}/录入判定-弹窗.png` })

// ── 取消 ⇒ 关闭 ──
await page.getByRole('button', { name: '取消' }).click()
await page.waitForTimeout(400)
RESULT.checks.dialogClosed = (await page.locator('[role="dialog"]').count()) === 0
RESULT.checks.bodyScrollRestored = (await page.evaluate(() => document.body.style.overflow)) === ''

RESULT.ok =
  RESULT.checks.loggedIn &&
  RESULT.checks.hasOrderNoColumn &&
  RESULT.checks.hasNoQuantityColumn &&
  RESULT.checks.orderNoRendered &&
  JSON.stringify(RESULT.checks.columnOrder) === JSON.stringify(['加工单号', '订单号', '成品帘', '最新判定', '操作']) &&
  RESULT.checks.formAbsentBeforeClick &&
  RESULT.checks.dialogInViewport &&
  RESULT.checks.dialogHasForm &&
  RESULT.checks.dialogTitleHasSubject &&
  RESULT.checks.bodyScrollLocked &&
  RESULT.checks.dialogClosed &&
  RESULT.checks.bodyScrollRestored &&
  RESULT.consoleErrors.length === 0

writeFileSync(`${OUT}/result.json`, JSON.stringify(RESULT, null, 2))
console.log(JSON.stringify(RESULT, null, 2))
await browser.close()
process.exit(RESULT.ok ? 0 : 1)
