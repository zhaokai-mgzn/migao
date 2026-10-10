// case_ids: UI-086
//
// 宽表**关键列 / 主操作**在默认视口下的可达性（issue #6717）。
//
// 病灶（真机实测，main `2adad8660`，1440×980）：`/orders` 表格宽 1835px，容器
// `overflow-x-auto` 只有 1044px ⇒ 溢出 791px，**出屏 6 列**（制单人 1454 / 状态 **1542** /
// 加急 1644 / 到货日 1718 / 备注 1829 / 操作 **1929**）。商家必须横滚 791px 才能看到
// **订单状态**、够到**行操作**。同形态另有 `/inbound-orders`（1280 下操作列 1317 出屏）、
// `/production`（1280 下计件合计 + 操作 1368 出屏）；`/processing-orders` 是 `/production`
// 的重定向（`frontend/admin-web/src/app/(dashboard)/processing-orders/page.tsx` 只有
// `redirect('/production')`）⇒ 不单独测。
//
// 判据（**效果层几何**，不是类名快照）：
//   ① 关键列（本单现场 = 「状态」）在 `scrollLeft = 0` 时落在**表格可视区**内
//      —— 可视区 = 表格最近一个横向滚动容器的 client 盒；
//   ② 「操作」列**每个**行内按钮的中心点 `elementFromPoint` 命中**它自己或其内部节点**
//      —— 既有口径：被 `overflow` 裁掉不算、「命中祖先」不算（命中祖先 = 按钮被别的元素盖住）；
//   ③ 列集合与数据口径不变（列名集合逐字冻结，防「修可达性顺手改了列」）。
//
// ⚠️ 为什么必须效果层：vitest/jsdom **没有布局**（`getBoundingClientRect` 恒为 0），
// 「列在不在视口里」在单测里根本量不出来 ⇒ 那是本单的假绿形态（§15.3）。
// 类级静态那一半由 `frontend/admin-web/tests/unit/wide-table-action-column-guard.test.ts` 守。
import { test, expect } from '../../fixtures'
import type { Locator, Page, TestInfo } from '@playwright/test'

const VIEWPORTS = [
  { width: 1440, height: 980 },
  { width: 1280, height: 800 },
] as const

type Cell = { text: string; left: number; right: number; fully: boolean; partly: boolean; sticky: string; action: boolean }
type Reading = {
  overflow: number
  container: { left: number; right: number; clientWidth: number; scrollWidth: number; scrollLeft: number }
  cells: Cell[]
}

/**
 * 建立兜底 mock：本页挂载后还会打若干**非本判据**的接口（权限/菜单/简报…），本机/CI 无后端时
 * 它们会 401 ⇒ 应用拦截器**登出并跳登录页**，于是「页面在不在列表态」变成一个与被测行为无关的红
 * （先例 = `tests/e2e/specs/warehouse/inbound-orders-table-geometry.spec.ts` 的同款兜底）。
 * ⚠️ `/api/auth/me` 必须放行（`route.fallback()`）—— 认证夹具给的是真登录态，不能被这里吞掉。
 */
async function stubOtherApis(page: Page) {
  await page.route('**/api/**', (route) =>
    route
      .request()
      .url()
      .includes('/api/auth/me')
      ? route.fallback()
      : route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: null }) }),
  )
}

const ok = (body: unknown) => ({
  status: 200,
  contentType: 'application/json',
  body: JSON.stringify({ success: true, data: body }),
})

/** 打开页面 → 等非空首行（列面几何必须有数据行才有意义）→ 切到指定视口。 */
async function openWithRows(
  page: Page,
  path: string,
  viewport: { width: number; height: number },
  firstRow: Locator,
) {
  await page.setViewportSize({ ...viewport })
  // ⚠️ `waitUntil: 'domcontentloaded'`（不是默认的 `load`）：`next dev` 首次请求一条路由要在本机
  // 实测 **60~90s**（`/products` 冷编译 87.3s），而 `load` 还要等全部子资源（图片/字体/接口）
  // ⇒ 本地几乎必然超时、把「几何没达标」伪装成「页面打不开」。本判据只需要 DOM 到位后量几何，
  // 不需要子资源全绿；**非空前置**（下面这条）仍然硬等数据行 ⇒ 页面真坏时照样红。
  await page.goto(path, { waitUntil: 'domcontentloaded', timeout: 120_000 })
  await expect(
    firstRow,
    `${path} 没有渲染出数据行（冷编译超时 / 认证夹具没生效 / 接口 mock 没命中 ⇒ 本判据会在扫空气）`,
  ).toBeVisible({ timeout: 60_000 })
  // 视口尺寸在 goto 之后**再设一次**：Next dev 的 HMR / 布局重算偶发会读旧尺寸
  await page.setViewportSize({ ...viewport })
}

/**
 * 量一次表头逐列坐标 + 表格可视区（`scrollLeft = 0`）。
 *
 * 口径：`rect.left` / `rect.right` 是**视口坐标**；可视区 = 表格最近一个
 * `overflow-x: auto|scroll` 容器的 `getBoundingClientRect()`（它就是商家眼里的「表格可见范围」）。
 * ⚠️ 必须先把滚动位置归零，否则「在不在视口里」量的是别人滚过的位置。
 */
async function measureColumns(table: Locator): Promise<Reading> {
  return table.evaluate((el) => {
    const container = (() => {
      let node: HTMLElement | null = el.parentElement
      while (node) {
        const ox = getComputedStyle(node).overflowX
        if (ox === 'auto' || ox === 'scroll') return node
        node = node.parentElement
      }
      return null
    })()
    if (!container) throw new Error('表格没有横向逃逸口（overflow-x: auto|scroll）—— 判据的坐标系不存在')
    container.scrollLeft = 0
    const box = container.getBoundingClientRect()
    const ths = Array.from(el.querySelectorAll('thead th')) as HTMLElement[]
    const bodyRows = Array.from(el.querySelectorAll('tbody tr')) as HTMLElement[]
    const actionIdxes = ths
      .map((th, i) => ((th.textContent ?? '').includes('操作') ? i : -1))
      .filter((i) => i >= 0)
    const cells: Cell[] = ths.map((th, i) => {
      const r = th.getBoundingClientRect()
      return {
        text: (th.textContent ?? '').replace(/\s+/g, ' ').trim() || '~',
        left: Math.round(r.left),
        right: Math.round(r.right),
        fully: r.left >= box.left - 0.5 && r.right <= box.right + 0.5,
        partly: r.right > box.left && r.left < box.right,
        sticky: getComputedStyle(th).position,
        action: actionIdxes.includes(i),
      }
    })
    void bodyRows
    return {
      overflow: Math.round(container.scrollWidth - container.clientWidth),
      container: {
        left: Math.round(box.left),
        right: Math.round(box.right),
        clientWidth: Math.round(container.clientWidth),
        scrollWidth: Math.round(container.scrollWidth),
        scrollLeft: container.scrollLeft,
      },
      cells,
    }
  })
}

/** 把逐列读数打成一行，便于粘进 PR body 当**可复制证据**。 */
function formatReading(label: string, r: Reading): string {
  const cols = r.cells
    .map((c) => `${c.text}@${c.left}${c.fully ? '' : c.partly ? '(半)' : '(出屏)'}${c.sticky === 'sticky' ? '[sticky]' : ''}`)
    .join(' | ')
  return `${label} 容器[${r.container.left},${r.container.right}] clientW=${r.container.clientWidth} scrollW=${r.container.scrollWidth} 溢出=${r.overflow}px :: ${cols}`
}

/**
 * 把一次读数的**可复算证据**挂到测试结果上（`testInfo.attach`）——不只是打进 stdout。
 * 用法：跑完 `--reporter=json` 后用 `node tests/e2e/scripts/dump-reading.mjs <run.json>` 提取，
 * 「改前 / 改后」两次都从同一份结构里取数 ⇒ PR 里的逐列坐标是**复算得出**的，不是手抄的。
 */
async function publishReading(testInfo: TestInfo, label: string, r: Reading) {
  console.log(formatReading(`[${label}]`, r))
  await testInfo.attach(`reading-${label}`, {
    contentType: 'application/json',
    body: JSON.stringify({ label, ...r }),
  })
}

/**
 * 「操作」列的**每一个**行内按钮中心点 `elementFromPoint` 必须命中**它自己或内部节点**。
 *
 * 判定 = `document.elementFromPoint(cx, cy)` 之后 `btn.contains(hit)`；`hit === btn` 也算命中。
 * ⇒ **命中祖先不算**（按钮被别的元素盖住时命中的是祖先 / 兄弟）、被 `overflow` 裁掉不算
 * （中心点落在裁剪区外时 `elementFromPoint` 命中的是别的元素，或返回 null）。
 */
async function actionButtonHits(table: Locator): Promise<
  { text: string; hit: string; ok: boolean; cx: number; cy: number; note: string }[]
> {
  return table.evaluate((el) => {
    const ths = Array.from(el.querySelectorAll('thead th')) as HTMLElement[]
    const idx = ths.findIndex((th) => (th.textContent ?? '').includes('操作'))
    const out: { text: string; hit: string; ok: boolean; cx: number; cy: number; note: string }[] = []
    if (idx < 0) return out
    const describe = (n: Element | null) =>
      !n
        ? 'null'
        : `${n.tagName.toLowerCase()}${n.getAttribute('data-testid') ? `[${n.getAttribute('data-testid')}]` : ''}` +
          `{"${(n.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 12)}"}`
    for (const tr of Array.from(el.querySelectorAll('tbody tr')) as HTMLElement[]) {
      const tds = Array.from(tr.children) as HTMLElement[]
      const cell = tds[idx]
      if (!cell) continue
      for (const btn of Array.from(cell.querySelectorAll('button')) as HTMLElement[]) {
        const r = btn.getBoundingClientRect()
        if (r.width < 1 || r.height < 1) {
          out.push({ text: (btn.textContent ?? '').trim(), hit: '-', ok: false, cx: Math.round(r.left), cy: Math.round(r.top), note: '按钮零尺寸（不可渲染）' })
          continue
        }
        const cx = Math.round(r.left + r.width / 2)
        const cy = Math.round(r.top + r.height / 2)
        const hit = document.elementFromPoint(cx, cy)
        // `contains` 覆盖「命中按钮自身」与「命中按钮内部节点」；**不含**祖先
        const ok = !!hit && btn.contains(hit)
        const clipped = hit === null
        out.push({
          text: (btn.textContent ?? '').trim(),
          hit: describe(hit),
          ok,
          cx,
          cy,
          note: clipped ? '中心点不在任何可命中元素上（被裁掉 / 视口外）' : ok ? '' : '命中的不是它自己或内部节点（被遮挡）',
        })
      }
    }
    return out
  })
}

/** 断言「操作」列的每个按钮都真可点，失败时逐条打印（带按钮文字与命中对象）。 */
async function expectActionsHittable(page: Page, table: Locator, label: string) {
  const hits = await actionButtonHits(table)
  expect(hits.length, `${label}：「操作」列一个行内按钮都没扫到（判据在扫空气）`).toBeGreaterThan(0)
  const bad = hits.filter((h) => !h.ok)
  expect(
    bad,
    `${label}：「操作」列有 ${bad.length}/${hits.length} 个按钮**点不到**（口径 = elementFromPoint(中心点) 必须命中它自己或内部节点；命中祖先 / 被 overflow 裁掉都不算）：\n` +
      hits.map((h) => `  · 「${h.text}」中心(${h.cx},${h.cy}) → ${h.hit} ${h.ok ? '✅' : '❌ ' + h.note}`).join('\n'),
  ).toEqual([])
}

// ⚠️ 本 spec 渲染**带数据的列表**，`next dev` 冷编译在负载高的机器上实测 >15s ⇒ 只放宽时间预算，
// 断言一字未放宽（页面渲染不出来时上面的非空前置照样红）。
test.describe.configure({ timeout: 120_000 })

// ── issue #6729：冻结列的**有效背景不透明度**（触发面 = 选中态，与 hover 无关） ──

/**
 * `getComputedStyle().backgroundColor` 的 alpha（`rgb(...)` ⇒ 1；`rgba(...,0.4)` ⇒ 0.4）。
 *
 * 🔴 判「有效不透明度」而不是「声明了背景色」：`bg-inherit` 在**继承到半透明行色**时
 * 声明了背景却仍半透明 ⇒ 冻结列会透出下层列的内容（issue #6729 的真机现象：alpha=0.4）。
 * 所以这里量的是**算出来的 alpha**。
 */
function alphaOf(color: string): number {
  const s = color.trim()
  if (s === 'none' || s === 'transparent' || s === 'rgba(0, 0, 0, 0)') return 0
  const m = s.match(/^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)\s*(?:[,/]\s*([\d.]+)\s*)?\)$/)
  if (!m) return -1
  return m[4] === undefined ? 1 : Number(m[4])
}

/** `rgb()/rgba()` 字符串 → `[r,g,b]`。 */
function rgbOf(color: string): number[] | null {
  const m = color.match(/([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/)
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null
}

/**
 * 冻结列数据格的**有效背景 alpha** = 该格自己声明的 `backgroundColor` 的 alpha
 * **或**其**覆盖整个格子的不透明后代**（`position:absolute` 且铺满）的 alpha。
 *
 * 为什么允许「不透明后代」：合法修法之一是「冻结格自己铺不透明底 + 再叠一层继承行色的覆盖层」
 * —— 那时格子自身的 background 可能就是半透明行色，只有覆盖层不透明。
 * ⇒ 只看格子自身的 alpha 会把这种**合法**修法误判成红。
 */
async function stickyCellOpacity(cell: Locator): Promise<{ own: string; overlay: string; effective: number }> {
  return cell.evaluate((el) => {
    const own = getComputedStyle(el).backgroundColor
    let overlay = 'none'
    for (const child of Array.from(el.children) as HTMLElement[]) {
      const cs = getComputedStyle(child)
      if (cs.position !== 'absolute') continue
      const r = child.getBoundingClientRect()
      const host = el.getBoundingClientRect()
      if (r.width >= host.width - 1 && r.height >= host.height - 1) overlay = cs.backgroundColor
    }
    const alpha = (color: string): number => {
      const s = color.trim()
      if (s === 'none' || s === 'transparent' || s === 'rgba(0, 0, 0, 0)') return 0
      const m = s.match(/^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)\s*(?:[,/]\s*([\d.]+)\s*)?\)$/)
      if (!m) return -1
      return m[4] === undefined ? 1 : Number(m[4])
    }
    return { own, overlay, effective: Math.max(alpha(own), alpha(overlay)) }
  })
}

/**
 * 在冻结列的矩形内**布点采样**，返回「命中元素不属于该冻结列」的点。
 *
 * ⚠️ 口径沿用本批既有约定：**「命中祖先」不算**（命中 `body` / `main` / `table` ⇒ 该点已不在
 * 冻结列内，或透明穿过去了）。用的是**最上层**元素（`document.elementFromPoint`）。
 */
async function foreignHitsInCell(cell: Locator): Promise<{ x: number; y: number; hit: string }[]> {
  return cell.evaluate((el) => {
    const rect = el.getBoundingClientRect()
    const out: { x: number; y: number; hit: string }[] = []
    const describe = (n: Element | null) =>
      !n ? 'null' : `${n.tagName.toLowerCase()}${n.getAttribute('data-testid') ? `[${n.getAttribute('data-testid')}]` : ''}`
    for (const fx of [0.2, 0.5, 0.8]) {
      for (const fy of [0.25, 0.6, 0.85]) {
        const x = Math.round(rect.left + rect.width * fx)
        const y = Math.round(rect.top + rect.height * fy)
        const hit = document.elementFromPoint(x, y)
        if (!hit || !el.contains(hit)) out.push({ x, y, hit: describe(hit) })
      }
    }
    return out
  })
}

/** 冻结列的数据格（`tbody` 每行的最后一个 `td`）。 */
const frozenCells = (page: Page) => page.locator('table').first().locator('tbody tr td:last-child')

/**
 * issue #6729 的实例判据：冻结列在**选中态**下有效背景必须不透明，且勾选 + 横滚后
 * 冻结矩形内采不到别的列的节点。
 *
 * 触发面**精确到「选中态」**（集成侧实测：仅 hover 时冻结列仍是 `rgb(255,255,255)` / alpha=1
 * ⇒ hover **不**触发）⇒ 判据锚在「勾选」；**没有行复选框的表本身不存在这个缺陷**，
 * 那类表只判「底色不透明」（不硬造一个勾选，否则判据会在扫空气）。
 */
async function expectFrozenCellOpaqueWhenSelected(page: Page, label: string) {
  const table = page.locator('table').first()
  const count = await frozenCells(page).count()
  expect(count, `${label}：冻结列一行都没扫到 ⇒ 判据在扫空气`).toBeGreaterThan(0)

  // 复位横向滚动，取「未勾选」时的读数（反向对照的基线）
  await table.evaluate((el) => {
    const c = el.parentElement as HTMLElement
    c.scrollLeft = 0
  })
  await page.mouse.move(5, 5)
  const beforeFirst = await stickyCellOpacity(frozenCells(page).first())
  // 选中**之前**的行底色（这是「冻结格该取哪个色」的真值：选中态的行色就是从这里变过去的）
  const baseRowBg = await frozenCells(page)
    .first()
    .evaluate((el) => getComputedStyle(el.parentElement as HTMLElement).backgroundColor)

  const selectable = (await table.locator('tbody input[type="checkbox"]').count()) > 0
  if (selectable) {
    // 用 DOM 事件勾选（`check()` 在本机高负载下 actionability 等待会稳定超时；本判据只关心勾选之后的状态）
    await table
      .locator('tbody tr')
      .first()
      .locator('input[type="checkbox"]')
      .evaluate((el: HTMLInputElement) => el.click())
    await page.mouse.move(5, 5) // 移开鼠标 ⇒ 证明与 hover 无关
    // 等「选中态真的落到 DOM 上」（React 重渲染是异步的；不等就会读到未选中的行底色，
    // 本包实测因此得到「冻结格与行底色不一致」的**假红**）
    await expect(frozenCells(page).first().locator('xpath=..')).not.toHaveClass(/bg-white(?![-\w])/, {
      timeout: 5_000,
    })
  }

  const selected = frozenCells(page).first()
  const opacity = await stickyCellOpacity(selected)
  expect(
    opacity.effective,
    `${label}：${selectable ? '**勾选后**' : '（本表无行复选框 ⇒ 无选中态）'}冻结列数据格的有效背景 alpha = ` +
      `${opacity.effective}（本格 ${opacity.own} / 不透明覆盖层 ${opacity.overlay}）` +
      ` ⇒ < 1 时横滚会看到下层列内容透过来（issue #6729 真机现象：勾选行的冻结列叠印「姓名 / 电话 / 地址」）`,
  ).toBeGreaterThanOrEqual(1)

  // 横滚一段，让下层列的内容真的滚到冻结列下面
  await table.evaluate((el) => {
    const c = el.parentElement as HTMLElement
    c.scrollLeft = Math.min(300, c.scrollWidth - c.clientWidth)
  })
  await page.mouse.move(5, 5)
  const foreign = await foreignHitsInCell(selected)
  expect(
    foreign,
    `${label}：勾选 + 横滚后，冻结列矩形内有 ${foreign.length} 个采样点命中的**不是**冻结列自身/其后代：\n` +
      foreign.map((f) => `  · (${f.x},${f.y}) → ${f.hit}`).join('\n'),
  ).toEqual([])

  // 反向对照①：未勾选的那一行不受影响（不许为了不透明白底化整张表）
  if (count >= 2) {
    const unselected = await stickyCellOpacity(frozenCells(page).nth(1))
    expect(
      unselected.effective,
      `${label}：**未勾选**行的冻结列有效背景 alpha = ${unselected.effective}（必须仍是不透明白底）`,
    ).toBeGreaterThanOrEqual(1)
  }

  // 反向对照②：**冻结格的观感与「同行其它格」同像素等色**。
  // 自我校验：可选中时必须真的进了选中态（行底色不再是白），否则这一条退化成空断言。
  // 改前的可视色 = 行底色叠在卡片白底上（选中行 `rgba(238,242,248,0.4)` over white = 248.2/249.8/252.2）；
  // 修后允许把它换成**等效不透明色** ⇒ 判「不透明层的层色 ≈ 该可见色」（差 ≤1/255）。
  // 这一条同时拦住两种坏修法：白底化（层色 → 255/255/255）、把选中色改掉（层色 → 238/242/248）。
  // ⚠️ 与行底色的**机制**无关（表格无关、自校验）；退回 `bg-inherit` 时它也会红。
  const parts = await selected.evaluate((el) => {
    const out: { color: string; alpha: number }[] = []
    const alpha = (c: string): number => {
      const s2 = c.trim()
      if (s2 === 'none' || s2 === 'transparent' || s2 === 'rgba(0, 0, 0, 0)') return 0
      const mm = s2.match(/^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)\s*(?:[,/]\s*([\d.]+)\s*)?\)$/)
      return mm ? (mm[4] === undefined ? 1 : Number(mm[4])) : -1
    }
    const nodes: HTMLElement[] = [el as HTMLElement, ...(Array.from(el.children) as HTMLElement[])]
    for (const n of nodes) {
      const c = getComputedStyle(n).backgroundColor
      out.push({ color: c, alpha: alpha(c) })
    }
    return out
  })
  const rowBg = baseRowBg
  const rowColor = rgbOf(rowBg)
  expect(rowColor, `${label}：解析不了行底色 ${rowBg}`).not.toBeNull()
  const rowAlpha = alphaOf(rowBg)
  if (selectable) {
    // 自我校验：勾选后**行底色必须真的变了**（否则「与行底色同色」这一条无从判起，退化成空断言）
    const afterRowBg = await selected.evaluate((el) => getComputedStyle(el.parentElement as HTMLElement).backgroundColor)
    expect(
      afterRowBg !== baseRowBg,
      `${label}：勾选后行底色仍是 ${afterRowBg}（= 选中前）⇒ 没进选中态（本判据退化成空断言）`,
    ).toBe(true)
    // 并且冻结格必须取「选中色」—— 与**未选中时的行色**不同（否则等于没有为选中态换色）
    expect(
      opaque.some((v, i) => Math.abs(v - visible[i]) > 1) === false,
      `${label}：勾选后冻结格仍是「未选中」的色（层色 = [${opaque.join(',')}]）`,
    ).toBe(true)
  }
  const visible = rowColor!.map((v) => v * rowAlpha + 255 * (1 - rowAlpha))
  const opaqueLayers = parts
    .filter((p2) => p2.alpha >= 0.999)
    .map((p2) => rgbOf(p2.color))
    .filter((rgb): rgb is number[] => rgb !== null)
  expect(opaqueLayers.length, `${label}：冻结格没有**不透明**背景层（层栈 ${JSON.stringify(parts)}）`).toBeGreaterThan(0)
  const opaque = opaqueLayers[opaqueLayers.length - 1]
  if (selectable) {
    // 只有「行底色会变」的表才有"同色"对象（本表行底色 = 选中色；无复选框的表行底色恒为白）
    expect(
      opaque.every((v, i) => Math.abs(v - visible[i]) <= 1),
      `${label}：冻结格的观感与行底色不一致 —— 不透明层色 = [${opaque.join(',')}]，行底色 \`${rowBg}\` ` +
        `叠在白底上的可见色 = [${visible.map((v) => v.toFixed(1)).join(',')}]` +
        `（容差 1/255：不许为了不透明白底化、也不许改掉选中色）`,
    ).toBe(true)
  } else {
    // 无复选框的表：没有选中态可判（触发面不存在）。此处只判「层色是**浅色**」——
    // 拦住「为了不透明糊一层深色/彩色」的反向劣化；具体取哪个浅色由各表自己的行底色决定
    // （本包：`/production` 行底色 `bg-white` ⇒ 取白；`/inbound-orders` 行底色含 hover
    //  `bg-neutral-50/60` ⇒ 取它的已合成色 `#faf7f2`）。
    expect(
      opaque.every((v) => v >= 240),
      `${label}：冻结格的不透明层色 = [${opaque.join(',')}] 不是浅色（不许为了不透明糊深色/彩色）`,
    ).toBe(true)
  }

  // 反向对照③：未勾选时的观感与改前一致。
  // 判「不透明 + 与该表**选中前**的行底色叠在白底上的可见色同色」——表格无关、自校验
  //（`/orders` 未选中行底色 = 白 ⇒ 白；`/inbound-orders` 行底色 = 白 + 半透明 hover ⇒ 取等效浅色）。
  expect(alphaOf(beforeFirst.own), `${label}：未勾选时冻结列数据格背景必须不透明`).toBeGreaterThanOrEqual(1)
  const beforeColor = rgbOf(beforeFirst.own)
  expect(beforeColor, `${label}：解析不了未勾选时的底色 ${beforeFirst.own}`).not.toBeNull()
  expect(
    beforeColor!.every((v) => v >= 235),
    `${label}：未勾选时冻结列数据格应当是浅色底（改前是 rgb(255,255,255)），现为 [${beforeColor!.join(',')}]`,
  ).toBe(true)
}

// ── 逐页用例：两档视口 ×（关键列可见 + 操作列真可点 + 列集合冻结） ──

test.describe('/orders（issue #6717 现场）', () => {
  for (const vp of VIEWPORTS) {
    test(`${vp.width}×${vp.height}：状态列可见 + 操作列每个按钮可点`, async ({ page }, testInfo) => {
      await stubOtherApis(page)
      // ⚠️ 订单列表接口的分页壳是 `{ data: { items, total } }`（页面读 `res.data.data.items`
      // —— 见 frontend/admin-web/src/app/(dashboard)/orders/page.tsx 的 `loadOrders`）。
      // 裸数组是**另一种**形状 ⇒ 页面渲染成空列表、判据在扫空气（本包实测踩过）。
      await page.route('**/api/admin/orders**', (route) =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { items: ORDERS, total: ORDERS.length } }) }),
      )
      await openWithRows(page, '/orders', vp, page.getByRole('row', { name: /MG202610110001/ }))
      const table = page.locator('table').first()
      const r = await measureColumns(table)
      await publishReading(testInfo, `orders-${vp.width}`, r)

      const status = r.cells.find((c) => c.text === '状态')
      expect(status, '找不到「状态」列（列集合已漂移 ⇒ 判据坐标系不对）').toBeTruthy()
      expect(
        status!.fully,
        `${vp.width}×${vp.height}：scrollLeft=0 时「状态」列 [${status!.left},${status!.right}] 不在表格可视区 ` +
          `[${r.container.left},${r.container.right}] 内（商家要横滚 ${r.overflow}px 才看得到订单状态）`,
      ).toBe(true)

      const action = r.cells.find((c) => c.action)
      expect(action, '找不到「操作」列').toBeTruthy()
      expect(
        action!.fully,
        `${vp.width}×${vp.height}：「操作」列表头 [${action!.left},${action!.right}] 不在可视区内`,
      ).toBe(true)

      // 列集合与数据口径不变（逐字冻结；顺序允许变化 —— 本单改的正是列序）
      expect(new Set(r.cells.map((c) => c.text))).toEqual(new Set(ORDER_COLUMNS))

      await expectActionsHittable(page, table, `/orders ${vp.width}×${vp.height}`)

      // 冻结列**滚到底也要**在（判的是 sticky 真的生效，不是「恰好没滚」）：
      // 滚到底后左端的列会滚到容器左侧之外，而冻结列必须仍贴在容器右缘、按钮仍可点。
      await table.evaluate((el) => {
        const c = el.parentElement as HTMLElement
        c.scrollLeft = c.scrollWidth
      })
      const after = await measureColumns(table)
      const stickyAfter = after.cells.find((c) => c.action)
      expect(
        stickyAfter!.fully && Math.abs(stickyAfter!.right - r.container.right) <= 2,
        `滚到底后「操作」列表头 [${stickyAfter!.left},${stickyAfter!.right}] 不再贴容器右缘 ${r.container.right}（sticky 没生效）`,
      ).toBe(true)
      await expectActionsHittable(page, table, `/orders ${vp.width}×${vp.height}（滚到底）`)

      // issue #6729：**勾选（选中态）**后冻结列必须仍不透明（触发面 = 选中，与 hover 无关）
      await expectFrozenCellOpaqueWhenSelected(page, `/orders ${vp.width}×${vp.height}（选中态）`)

      // 截图证据（§15.7 读图）：冻结列**必须不透明** —— 滚到底时它正压在「采购明细」等
      // 内容之上，若背景透明会看到穿过去的文字。`elementFromPoint` 判不了透明度
      // （它按盒模型命中，不理会视觉穿透）⇒ 这一条**只能靠读图**，故落一张裁剪图 + 全图。
      await page.screenshot({ path: testInfo.outputPath(`orders-${vp.width}-scrolled-full.png`), fullPage: false })
      await page.screenshot({
        path: testInfo.outputPath(`orders-${vp.width}-scrolled-action-column.png`),
        clip: {
          x: Math.max(0, stickyAfter!.left - 8),
          y: 0,
          width: Math.min(vp.width - Math.max(0, stickyAfter!.left - 8), 60 + stickyAfter!.right - stickyAfter!.left),
          height: vp.height,
        },
      })
    })
  }
})

test.describe('/inbound-orders（同形态）', () => {
  for (const vp of VIEWPORTS) {
    test(`${vp.width}×${vp.height}：操作列每个按钮可点`, async ({ page }, testInfo) => {
      await stubOtherApis(page)
      await page.route('**/api/admin/inbound-orders**', (route) => route.fulfill(ok(INBOUNDS)))
      await openWithRows(page, '/inbound-orders', vp, page.getByRole('row', { name: /RK-202610110001/ }))
      const table = page.locator('table').first()
      const r = await measureColumns(table)
      await publishReading(testInfo, `inbound-orders-${vp.width}`, r)
      expect(new Set(r.cells.map((c) => c.text))).toEqual(new Set(INBOUND_COLUMNS))
      await expectActionsHittable(page, table, `/inbound-orders ${vp.width}×${vp.height}`)
      await expectFrozenCellOpaqueWhenSelected(page, `/inbound-orders ${vp.width}×${vp.height}（选中态）`)
    })
  }
})

test.describe('/production（同形态；/processing-orders 是它的重定向）', () => {
  for (const vp of VIEWPORTS) {
    test(`${vp.width}×${vp.height}：操作列每个按钮可点`, async ({ page }, testInfo) => {
      await stubOtherApis(page)
      await page.route('**/api/admin/processing-orders**', (route) => route.fulfill(ok(PROCESSING_ORDERS)))
      await openWithRows(page, '/production', vp, page.getByText('JG202610110001', { exact: true }))
      const table = page.locator('table').first()
      const r = await measureColumns(table)
      await publishReading(testInfo, `production-${vp.width}`, r)
      expect(new Set(r.cells.map((c) => c.text))).toEqual(new Set(PRODUCTION_COLUMNS))
      await expectActionsHittable(page, table, `/production ${vp.width}×${vp.height}`)
      await expectFrozenCellOpaqueWhenSelected(page, `/production ${vp.width}×${vp.height}（选中态）`)
    })
  }
})

// ── 数据与列集合（逐字冻结：列集合变了 ⇒ 本判据红，逼一次显式确认） ──

const ORDER_COLUMNS = [
  '~',
  '订单ID',
  '采购商品',
  '采购明细(名称:单价×数量+加工费)',
  '累计金额(元)',
  '实收款(元)',
  '收货人信息',
  '下单时间',
  '制单人',
  '状态',
  '加急',
  '到货日',
  '备注',
  '操作',
]

const INBOUND_COLUMNS = ['入库单号', '入库日期', '供应商', '仓库', '行数 / 总数量', '批次号', '金额', '状态', '操作']

const PRODUCTION_COLUMNS = ['加工单号', '订单号', '客户', '商品与数量', '状态', '工序进度', '计件合计', '操作']

/** 两行订单，覆盖三种状态分支（待付款 = 关闭 + 确认付款；待发货 = 发货；已发货 = 确认收货）。 */
const ORDERS = [
  {
    id: 'o1',
    orderNo: 'MG202610110001',
    customerName: '张先生',
    customerPhone: '13800138000',
    customerAddress: '浙江省杭州市西湖区文三路 100 号',
    status: 'pending_payment',
    totalAmount: 1280.5,
    actualAmount: 1280.5,
    createdAt: '2026-10-11T10:30:00+08:00',
    createdByName: '蒋雪云',
    requiredDeliveryDate: '2026-10-20',
    isUrgent: true,
    remark: '客户催单',
    items: [
      { id: 'i1', productName: '北欧简约遮光窗帘', productCode: 'CL-GY-001', unitPrice: 256.1, quantity: 5, amount: 1280.5 },
    ],
  },
  {
    id: 'o2',
    orderNo: 'MG202610110002',
    customerName: '李女士',
    customerPhone: '13900139000',
    customerAddress: '江苏省南京市玄武区中山路 200 号',
    status: 'shipped',
    totalAmount: 3560,
    actualAmount: 3560,
    createdAt: '2026-10-11T09:15:00+08:00',
    createdByName: '—',
    requiredDeliveryDate: null,
    isUrgent: false,
    items: [
      { id: 'i2', productName: '法式蕾丝纱帘', productCode: 'CL-WH-002', unitPrice: 356, quantity: 10, amount: 3560 },
    ],
  },
]

const INBOUNDS = [
  {
    id: 'b1',
    inboundNo: 'RK-202610110001',
    inboundDate: '2026-10-11',
    supplier: '广州中大轻纺城-A132档',
    warehouse: '门店后仓',
    status: 'posted',
    totalAmount: 4005,
    itemCount: 1,
    totalQuantity: 90,
    batchNos: 'PC-202610110001',
  },
  {
    id: 'b2',
    inboundNo: 'RK-202610110002',
    inboundDate: '2026-10-10',
    supplier: '柯桥金梭纺织有限公司',
    warehouse: '主仓（一楼）',
    status: 'draft',
    totalAmount: 18120,
    itemCount: 2,
    totalQuantity: 420,
    batchNos: null,
  },
]

const PROCESSING_ORDERS = [
  {
    id: 'p1',
    processingOrderNo: 'JG202610110001',
    orderId: 'o1',
    orderNo: 'MG202610110001',
    customerName: '张先生',
    status: 'in_processing',
    items: [{ productName: '北欧简约遮光窗帘', quantity: 5 }],
  },
  {
    id: 'p2',
    processingOrderNo: 'JG202610110002',
    orderId: 'o2',
    orderNo: 'MG202610110002',
    customerName: '李女士',
    status: 'pending',
    items: [{ productName: '法式蕾丝纱帘', quantity: 10 }],
  },
]
