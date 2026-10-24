// 「审批中心改顶栏待办入口」的视觉验收（issue #7593，用户 2026-10-24 裁定）。
//
// 用法（frontend/admin-web 先 `npm run build`）：
//   1) `npx next start -p 3133`
//   2) `node scripts/visual-check/approvals-header.mjs`
// 产物：`/tmp/approvals-header-1-orders.png`（侧边栏交易管理组**没有**审批中心 + 顶栏有待审批徽标）
//       `/tmp/approvals-header-2-panel.png`（点开面板：待审前 5 条 + 去审批中心）
//
// 断言靠**人看**（本仓口径，见同目录 README）：
//   ① 交易管理组只剩「价格本 / 销售订单 / 财务对账」—— 不该再出现「审批中心」那一行；
//   ② 顶栏「待审批」图标带数字徽标（2 条），且**位置**在通知铃铛左侧、不与用户头像挤在一起；
//   ③ 面板里对象显示**人话**（「改价 · 遮光布 米白 2.8m」「盘点差异 · PD202610220001」），
//      不出现 `price_change` / `stocktake_diff` 这类内部码；
//   ④ 面板**没有**通过 / 驳回按钮（裁决是页面的活）。
const BASE = process.env.VISUAL_BASE || 'http://127.0.0.1:3133'

const PENDING = [
  {
    id: 'ap1', objectType: 'price_change', objectRef: 'sku-1', objectLabel: '遮光布 米白 2.8m',
    amount: 1200, payload: null, reason: '客户要 3% 折扣', status: 'pending',
    requestedBy: 'u-other', requestedByName: '王小美', requestedAt: '2026-10-23T10:00:00+08:00',
    decidedBy: null, decidedByName: null, decidedAt: null, decisionNote: null,
    consumedAt: null, consumedRef: null,
  },
  {
    id: 'ap2', objectType: 'stocktake_diff', objectRef: 'PD202610220001', objectLabel: 'PD202610220001',
    amount: 2, payload: null, reason: '盘库发现帘头受潮', status: 'pending',
    requestedBy: 'u-other2', requestedByName: '李明', requestedAt: '2026-10-22T16:30:00+08:00',
    decidedBy: null, decidedByName: null, decidedAt: null, decisionNote: null,
    consumedAt: null, consumedRef: null,
  },
]

const browser = await chromiumLaunch()
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
page.on('console', (m) => { if (m.type() === 'error') console.log('[console]', m.text().slice(0, 160)) })

const ok = (data) => ({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data }) })

await page.route('**/api/**', (r) => r.fulfill(ok([])))
await page.route('**/api/auth/refresh', (r) => r.fulfill(ok({ accessToken: 'dev-token', expiresIn: 3600 })))
const ME = { id: 'u1', username: 'admin', name: '管理员', tenantId: 1, roles: ['admin'], permissions: ['*'], menus: [] }
await page.route('**/api/auth/me', (r) => r.fulfill(ok(ME)))
await page.route('**/api/admin/user/info', (r) => r.fulfill(ok(ME)))
// 待审批（顶栏徽标 + 面板）
await page.route('**/api/admin/approvals?**', (r) => r.fulfill(ok(PENDING)))
await page.route('**/api/admin/approvals', (r) => r.fulfill(ok(PENDING)))

// 交易管理组默认展开（当前路由所在组）⇒ 侧边栏会画出组内三项
await page.goto(`${BASE}/orders`, { waitUntil: 'domcontentloaded' })
await page.waitForSelector('h1', { timeout: 45000 }).catch(() => {})
await page.waitForTimeout(1500)

const sidebarText = (await page.textContent('nav')) || ''
const headerText = (await page.textContent('header')) || ''
console.log('[读数] 侧边栏含「审批中心」:', sidebarText.includes('审批中心'))
console.log('[读数] 侧边栏含「财务对账」:', sidebarText.includes('财务对账'))
console.log('[读数] 顶栏徽标文本:', await page.getByTestId('approval-bell-badge').textContent().catch(() => '<无徽标>'))
await page.screenshot({ path: '/tmp/approvals-header-1-orders.png', fullPage: true })

await page.getByTestId('approval-bell').click()
await page.waitForTimeout(600)
console.log('[读数] 面板条数:', await page.getByTestId('approval-bell-item').count())
const panelText = (await page.textContent('body')) || ''
console.log('[读数] 面板出现内部码 price_change:', panelText.includes('price_change'),
  '| stocktake_diff:', panelText.includes('stocktake_diff'))
console.log('[读数] 面板出现「通过」/「驳回」动作:', /通过|驳回/.test(await page.textContent('[data-testid="approval-bell-panel"]') || ''))
console.log('[读数] 顶栏含「审批中心」入口文本:', headerText.includes('审批中心'))
await page.screenshot({ path: '/tmp/approvals-header-2-panel.png', fullPage: true })

console.log('shot | body len:', bodyLength(await page.textContent('body')))
await browser.close()

function bodyLength(t) { return (t || '').length }

async function chromiumLaunch() {
  // playwright 模块装在 /tmp（见同目录 README：ESM 不认 NODE_PATH）；按优先级解析
  const mods = ['playwright', '/tmp/node_modules/playwright/index.js']
  for (const m of mods) {
    try {
      const { chromium } = await import(m)
      return chromium.launch()
    } catch (e) { /* 换下一个 */ }
  }
  throw new Error('playwright 不可用：`npm --prefix /tmp i playwright` 后再跑（见 scripts/visual-check/README.md）')
}
