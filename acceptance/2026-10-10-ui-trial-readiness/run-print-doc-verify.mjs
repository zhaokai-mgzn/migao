/**
 * S21 载体：**打印纸面**真机验证（可重放）—— 纸面缺值不许印 0.00 / 聚合「未知」不许摊成 0
 *
 * 为什么这条判据重要：纸面是"客户会拿着它跟顾客对账"的东西，缺值印成 0.00 是**事故级**错误；
 * 而它又"看不见"（`window.print()` 收敛在 effect 里、纸面在预览层）⇒ 只能靠响应注入造真形态再读纸。
 *
 * 手法（**纯读，不写任何数据**）：登录 → 订单列表点「查看」进详情（URL 里是订单 **UUID**，
 * ⚠️ 不能用 18 位订单号拼路由，会进"找不到"态）→ 点「打印报价单」→ 读预览纸面。
 *
 * 三轮（都在同一张真订单上）：
 *   A 控制轮：不注入 ⇒ 纸上必须有真实金额（证明探针真读到纸，不是空白恒绿）
 *   B 半可知轮：抹掉 `amount/unitPrice/quantity/subtotal`（保留 processingFee —— 与 #6720/#6731 的真形态一致）
 *   C 全未知轮：按名抹掉**所有**钱相关数值键（/amount|price|total|fee|pay|receiv|discount|money|yuan/i）
 *                ⇒ 纸上**任何**金额都不许再印数字（只许 `—`）——这是"未知会传染"的强判据
 *
 * 判据（都会红）：
 *   ① 控制轮纸上有真实金额；② B 轮：`本套金额`/`本单总金额`/行`价格`/`小计` 必须是 `—`（#6720/#6731/#6732 的目标）；
 *   ③ **独立值判据（自证）**：某个金额若在 A、B 两轮**逐字相同** ⇒ 它不依赖被抹字段（独立已知）⇒ 允许保留；
 *      若它在 B 轮变了却仍印数字（而不是 `—`）⇒ 判红；
 *   ④ C 轮：纸上不得再出现任何 `数字.数字` 形态的金额（`优惠金额 0.00` 这种"真 0"在 C 轮也应变成 `—`，因为其输入已被抹）。
 */
import { createRequire } from 'node:module'
import { writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// 与同目录其它运行器同口径：从**主检出**的 tests 里取 @playwright/test（linked worktree 没有 node_modules）
const require = createRequire('/Users/guangzhen.zk/ai native/migao/tests/package.json')
const { chromium } = require('@playwright/test')

const BASE = process.env.BASE || 'http://localhost:3001'
const PHASE = process.env.PHASE || 'print'
// ⚠️ 必须用 fileURLToPath：URL.pathname 会把路径里的空格编码成 %20，把文件写到 `ai%20native/…` 那种假目录里（我踩过）
const OUT = process.env.OUT_DIR || fileURLToPath(new URL('./evidence/', import.meta.url))
mkdirSync(OUT, { recursive: true })

const results = []
const rep = (name, ok, detail) => { results.push({ name, ok, detail }); console.log(`${ok ? '✅' : '❌'} ${name} ${detail || ''}`) }
const moneyNumbers = (paper) => (paper.match(/(?:^|[\s\t])\d[\d,]*\.\d{2}(?=[\s\t]|$)/gm) || []).map((s) => s.trim())
const paperLine = (paper, label) => {
  const line = paper.split('\n').find((l) => l.trim().startsWith(label))
  return line ? line.trim() : null
}

const browser = await chromium.launch({ channel: 'chrome' })
let payload = { phase: PHASE, results }
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2 })
  const page = await ctx.newPage()
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('input', { timeout: 60000 }); await page.waitForTimeout(1200)
  try { await page.getByRole('tab', { name: /管理员登录/ }).first().click({ timeout: 5000 }) } catch {}
  await page.getByLabel('手机号', { exact: false }).first().fill('13800138000')
  await page.getByLabel('验证码', { exact: false }).first().fill('123456')
  await page.getByRole('button', { name: /登\s*录/ }).first().click()
  await page.waitForURL((u) => !/^\/login\b/.test(u.pathname), { timeout: 30000 })

  await page.goto(`${BASE}/orders`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(5000)
  const firstNo = await page.evaluate(() => (document.body.innerText.match(/\b20\d{14,}\b/) || [null])[0])
  await page.getByText('查看', { exact: true }).first().click({ timeout: 10000 })
  await page.waitForTimeout(5500)
  const detailUrl = page.url()
  const uuid = detailUrl.split('/orders/')[1] || ''
  rep('按应用导航进详情（取到 UUID）', uuid.length >= 20, `${firstNo} → ${uuid || detailUrl}`)

  const openPaper = async () => {
    await page.goto(detailUrl, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(4500)
    const stale = page.locator('[data-testid="print-preview-close"]')
    if (await stale.count()) { await stale.first().click({ timeout: 5000 }).catch(() => {}); await page.waitForTimeout(800) }
    await page.getByRole('button', { name: /打印报价单/ }).first().click({ timeout: 12000 })
    await page.waitForSelector('[data-testid="print-preview-paper"]', { timeout: 20000 })
    await page.waitForTimeout(1200)
    return page.evaluate(() => {
      const paper = document.querySelector('[data-testid="print-preview-paper"]')
      const check = document.querySelector('[data-testid="print-preview-check"]')
      return { paper: (paper ? paper.innerText : '').replace(/\n{2,}/g, '\n'), check: check ? check.innerText.replace(/\s+/g, ' ') : '' }
    })
  }
  const scrubAllMoney = (node) => {
    if (!node || typeof node !== 'object') return
    if (Array.isArray(node)) return node.forEach(scrubAllMoney)
    for (const [k, v] of Object.entries(node)) {
      if (typeof v === 'number' && /amount|price|total|fee|pay|receiv|discount|money|yuan|cost/i.test(k)) node[k] = null
      else scrubAllMoney(v)
    }
  }
  const withScrub = async (scrubber, tag) => {
    await page.unroute('**/api/admin/orders/**').catch(() => {})
    await page.route('**/api/admin/orders/**', async (route) => {
      const resp = await route.fetch()
      let body
      try { body = await resp.json() } catch { return route.fulfill({ response: resp }) }
      scrubber(body)
      return route.fulfill({ response: resp, json: body })
    })
    const r = await openPaper()
    await page.screenshot({ path: `${OUT}S21b-${tag}.png` })
    await page.unroute('**/api/admin/orders/**').catch(() => {})
    return r
  }

  // A 控制轮
  const A = await openPaper()
  await page.screenshot({ path: `${OUT}S21b-control.png` })
  rep('控制轮：纸上有真实金额（证明读到了纸）', moneyNumbers(A.paper).length > 0, `金额数=${moneyNumbers(A.paper).length} 校验行="${A.check}"`)

  // B 半可知轮（与 #6720/#6731 的真形态一致：只抹 amount/unitPrice/quantity/subtotal）
  const B = await withScrub((node) => {
    const walk = (o) => { if (!o || typeof o !== 'object') return; if (Array.isArray(o)) return o.forEach(walk)
      for (const k of ['amount', 'unitPrice', 'quantity', 'subtotal']) if (k in o) o[k] = null
      Object.values(o).forEach(walk) }
    walk(node)
  }, 'injected-B')
  // 只判**派生**聚合（本套金额 = Σ 行小计 + 套内加工费 ⇒ 其输入被抹就必须 —）；
  // **不许**把独立字段（本单总金额/本单应收/优惠金额 —— 各有自己的响应键）也要求成 —，那是**过度断言**：
  // 判据是下面那条"A、B 两轮逐字相同 ⇒ 独立已知 ⇒ 允许保留"。我第一版把真值当缺陷误报过一次，记在这里。
  const derived = paperLine(B.paper, '本套金额')
  rep('B 轮：**派生**聚合「本套金额」印 —（#6731/#6732）', !!derived && derived.includes('—'), `本套金额行=「${derived}」`)
  // 明细行的两个金额格（价格、小计）在纸上是**相邻的制表位单元格** ⇒ 命中形态 = `—\t—`
  // （别按"以布帘开头的行"解析：该格文本自身含换行，会只取到第一行 —— 我这么写错过一次）
  const moneyDashLine = B.paper.split('\n').find((l) => /—\t—/.test(l)) || ''
  rep('B 轮：明细行「价格/小计」两格印 —（#6720）', !!moneyDashLine, `命中行=${moneyDashLine.replace(/\t/g, ' | ').slice(0, 96)}`)
  // 独立值判据：A、B 逐字相同的金额行 ⇒ 独立已知 ⇒ 允许保留
  const bNums = moneyNumbers(B.paper)
  const aNums = moneyNumbers(A.paper)
  const stable = bNums.filter((n) => aNums.includes(n))
  rep('B 轮：剩下的数字必须是"两轮逐字相同"的独立已知值', bNums.length === 0 || stable.length === bNums.length,
    `B 轮数字=${JSON.stringify(bNums)} 其中两轮相同=${JSON.stringify(stable)}`)
  rep('B 轮：纸面仍可读（不是整片空白）', B.paper.trim().length > 40, `长度=${B.paper.length}`)

  // C 全未知轮：所有钱相关数值键都抹掉 ⇒ 纸上不该再有任何数字金额
  const C = await withScrub(scrubAllMoney, 'injected-C')
  const cNums = moneyNumbers(C.paper)
  rep('C 轮：任何金额都不许再印数字（未知必须传染到整张纸）', cNums.length === 0, `C 轮数字=${JSON.stringify(cNums)}`)
  await page.screenshot({ path: `${OUT}S21b-injected-C.png` })

  // ── 纸面**家族**：同一张订单上挂着三份单据（报价单/加工单/销售单）⇒ 用**与标签无关**的判据一次覆盖整族：
  //    控制轮该纸有金额（证明真读到） ＋ 全未知轮该纸**一个数字都没有**（未知传染整张纸）
  const docFamily = []
  const readPaperOf = async (docButton) => {
    await page.goto(detailUrl, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(4000)
    const c = page.locator('[data-testid="print-preview-close"]')
    if (await c.count()) { await c.first().click({ timeout: 5000 }).catch(() => {}); await page.waitForTimeout(600) }
    await page.getByRole('button', { name: docButton }).first().click({ timeout: 12000 })
    await page.waitForSelector('[data-testid="print-preview-paper"]', { timeout: 20000 })
    await page.waitForTimeout(1000)
    return page.evaluate(() => (document.querySelector('[data-testid="print-preview-paper"]')?.innerText || '').replace(/\n{2,}/g, '\n'))
  }
  const installScrub = async (scrubber) => {
    await page.unroute('**/api/admin/orders/**').catch(() => {})
    if (!scrubber) return
    await page.route('**/api/admin/orders/**', async (route) => {
      const resp = await route.fetch()
      let body
      try { body = await resp.json() } catch { return route.fulfill({ response: resp }) }
      scrubber(body)
      return route.fulfill({ response: resp, json: body })
    })
  }
  for (const doc of ['打印报价单', '打印加工单', '打印销售单']) {
    await installScrub(null)
    const ctrl = await readPaperOf(doc)
    await installScrub(scrubAllMoney)
    const unk = await readPaperOf(doc)
    await page.screenshot({ path: `${OUT}S21b-family-${doc}.png` })
    docFamily.push({ doc, controlPaper: ctrl, unknownPaper: unk, controlNums: moneyNumbers(ctrl), unknownNums: moneyNumbers(unk) })
    // 三态，**禁止空绿**：控制轮无金额 ⇒ 本判据对该单据**不可判别**（如实登记 ⊘），不许记成通过
    const cN = moneyNumbers(ctrl).length
    const uN = moneyNumbers(unk).length
    if (cN === 0) {
      rep(`纸面家族「${doc}」：⊘ 不可判别（该单据不含金额字段，本判据对它不适用）`, true, `控制轮金额数=0 ⇒ 全未知轮的"无数字"是空绿，已如实登记而非记通过`)
      results[results.length - 1].notApplicable = true
    } else {
      rep(`纸面家族「${doc}」：控制轮有金额(${cN}) + 全未知轮无数字`, uN === 0, `全未知数字=${JSON.stringify(moneyNumbers(unk))}`)
    }
  }
  await installScrub(null)

  payload = { phase: PHASE, orderNo: firstNo, uuid, A, B, C, docFamily, results }
} finally { await browser.close() }
writeFileSync(`${OUT}S21b-print-doc-${PHASE}.json`, JSON.stringify(payload, null, 2))
const red = results.filter((r) => !r.ok)
console.log(red.length ? `🔴 红项 ${red.length} 条（读数落盘 ${OUT}S21b-print-doc-${PHASE}.json）` : '✅ 全绿')
process.exit(red.length ? 1 : 0)
