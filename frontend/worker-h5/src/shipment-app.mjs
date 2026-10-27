// case_ids: PG-018, BM-006, DF-017
//
// 工人端 H5「发货」页 —— 装配层（列表 → 发货标签预览 → 浏览器打印），issue #7761。
//
// 判据都在 `shipment.mjs` 的纯函数里（`node --test` 直接钉住，无需 DOM）；本文件只做接线：
//   ① 首屏先拉 `GET /api/worker/me` 认身份（**页头常驻「当前工人」**：共用 PAD 的既有纪律
//      —— 发货留痕记的是 session 里的那个人，屏上必须能看出是「谁」）；
//   ② 列表**只**来自 `GET /api/worker/shipment/orders`（本页不筛、不排、不补算套数）；
//   ③ 401 ⇒ 显式回落「请先登录」+ 登录页真链接（不静默重试、不按上一个人的身份发货）；
//   ④ 打印**只有一个调用点**（`printLabel`）—— 预览里那个「打印标签」按钮，
//      打印态由 `ship-label.css` 隔离（只有标签上纸）。

import { createApi, SESSION_EXPIRED } from './api.mjs'
import { renderReadyOrders, renderShipLabel, shipLabelLengthMm, shipLabelPageRule } from './shipment.mjs'

/** 登录页（同源静态页；本页未登录时的出口）。 */
export const SHIPMENT_LOGIN_HREF = './'

/** 读面失败时的兜底文案（技术原文留在 `err.technical`，屏上只出现人话）。 */
export const SHIPMENT_UNREADABLE = '待发货订单读取失败：请检查网络后刷新'

/** HTML 转义（与 `render.mjs` / `shipment.mjs` 同口径）。 */
function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
}

/** 页头「当前工人」（**服务端**来源；发货留痕记的是 session 里的人，屏上必须看得见）。 */
function pageHeader(worker) {
  const name = esc(worker?.workerName ?? worker?.worker_name ?? '')
  const no = esc(worker?.workerNo ?? worker?.worker_no ?? '')
  if (!name) return ''
  return `<header class="wh5-header">
    <span class="wh5-worker" id="wh5-current-worker">当前工人：${name}${no ? `（工号 ${no}）` : ''}</span>
    <a class="wh5-ghost" id="wh5-shipment-back" href="./">返回报工</a>
  </header>`
}

/** 「登录已失效」的显式文案 + 回登录页真链接（本页没有登录面）。 */
function loginFallback() {
  return `<section class="wh5-card">
    <h1 class="wh5-title">发货</h1>
    <p class="wh5-error" id="wh5-shipment-login-required">登录已失效：请先用工号 + PIN 登录，再查看待发货订单。</p>
    <a class="wh5-entry" id="wh5-shipment-login" href="${SHIPMENT_LOGIN_HREF}">去登录</a>
  </section>`
}

/** 发货联（整套出库单）预览层（含唯一的打印入口）。 */
function labelSheet(order) {
  return `<section class="wh5-label-sheet" id="wh5-ship-label-sheet" role="dialog" aria-modal="true"
      aria-label="发货联预览">
    <p class="wh5-sub" id="wh5-label-hint">核对无误后打印：50mm × 70mm 标签纸，整单一张（该订单全部套），贴在箱上</p>
    ${renderShipLabel(order)}
    <div class="wh5-label-actions">
      <button type="button" class="wh5-entry" id="wh5-label-print">打印发货联</button>
      <button type="button" class="wh5-ghost" id="wh5-label-close">关闭</button>
    </div>
  </section>`
}

/**
 * 装配「发货」页。
 *
 * @param {object} deps
 * @param {Document} deps.doc
 * @param {object} deps.api
 * @param {object} [deps.win] 打印宿主（缺省 `globalThis`；测试注入替身即可断言「打印真的被调了一次」）
 * @param {Function} [deps.replace] 换页动作（缺省 `location.replace`）
 */
export function createShipmentApp({ doc, api, win = globalThis, replace = null }) {
  const root = doc.getElementById('shipment-root')
  let worker = null
  /** 服务端给的待发货行（**原样**持有；本页不再过滤/排序） */
  let orders = []
  /** 当前打开标签的那一单（`null` = 没开预览） */
  let labelOrderId = null
  let html = '<p class="wh5-sub" id="wh5-ship-loading">正在读取待发货订单…</p>'

  const draw = () => {
    if (root) root.innerHTML = `${pageHeader(worker)}${html}`
    bind()
  }

  const goLogin = () => {
    labelOrderId = null
    html = loginFallback()
    draw()
  }

  /** 列表 + （可能）标签预览：一次渲染，预览层只追加在列表之后 —— 列表本身不重排。 */
  const drawReady = () => {
    const open = labelOrderId == null ? null : orders.find((o) => o?.order_id === labelOrderId)
    html = `${renderReadyOrders({ items: orders })}${open ? labelSheet(open) : ''}`
    draw()
    // 🔴 预览层在列表**之后**（列表不重排）⇒ 单多时要滚下去才看得到。
    //    点了「发货标签」却看不到纸面 = 工人以为没反应，会连点（真机现场最容易发生的一类）。
    if (open && typeof doc.getElementById === 'function') {
      // 预览一打开就把纸长按内容定下来（屏幕上看到的纸 = 打出来的纸）
      fitLabelToPaper()
      const sheet = doc.getElementById('wh5-ship-label-sheet')
      if (sheet && typeof sheet.scrollIntoView === 'function') sheet.scrollIntoView({ block: 'start' })
    }
  }

  async function load() {
    try {
      const data = await api.listReadyShipments()
      orders = Array.isArray(data?.items) ? data.items : []
      labelOrderId = null
      drawReady()
    } catch (e) {
      if (e?.code === SESSION_EXPIRED) {
        goLogin()
        return
      }
      // 读面失败**不冒充空态**（「没有待发货订单」与「读不到」是两个事实，工人据此决定要不要等）
      html = `<section class="wh5-card">
        <h1 class="wh5-title">发货</h1>
        <p class="wh5-error" id="wh5-shipment-error">${esc(e?.message ?? SHIPMENT_UNREADABLE)}</p>
        <button type="button" class="wh5-entry" id="wh5-shipment-retry">重新读取</button>
      </section>`
      draw()
    }
  }

  /**
   * 纸长按内容撑开（issue #7776）：量一次纸面高度 ⇒ 定纸长 ⇒ **同时**改标签高度与 `@page`。
   *
   * 🔴 预览与打印走**同一条**：屏幕上看到的纸就是打出来的纸（改前固定 70mm ⇒ 短标签下沿一大段空白）。
   * 量高度前必须临时放开固定高（屏幕态也是 70mm），否则恒量到 70mm。
   */
  function fitLabelToPaper() {
    if (typeof doc?.getElementById !== 'function') return
    const label = doc.getElementById('wh5-ship-label')
    if (!label) return
    const previous = label.style?.height ?? ''
    if (label.style) label.style.height = 'auto'
    const px = Number(label.scrollHeight ?? 0)
    if (label.style) label.style.height = previous
    const lengthMm = shipLabelLengthMm(px)
    if (label.style) label.style.height = `${lengthMm}mm`
    let style = doc.getElementById('wh5-label-page-size')
    if (!style) {
      style = doc.createElement('style')
      style.id = 'wh5-label-page-size'
      doc.head?.appendChild?.(style)
    }
    style.textContent = shipLabelPageRule(lengthMm)
  }

  /** 打印**只有这一个调用点**（预览里的按钮）—— 别处再写一处就会出现「两次打印两张纸」。 */
  function printLabel() {
    // 打印前再量一次：字体 / 内容随设备与缩放变化，纸长每次都要按**当前**纸面算
    fitLabelToPaper()
    if (typeof win?.print === 'function') win.print()
  }

  function bind() {
    const retry = doc.querySelector('#wh5-shipment-retry')
    if (retry) retry.addEventListener('click', () => { void load() })
    const login = doc.querySelector('#wh5-shipment-login')
    if (login && typeof replace === 'function') {
      login.addEventListener('click', (event) => {
        event.preventDefault()
        replace(SHIPMENT_LOGIN_HREF)
      })
    }
    orders.forEach((order, index) => {
      const button = doc.querySelector(`#wh5-label-${index}`)
      if (!button) return
      button.addEventListener('click', () => {
        if (!order?.order_id) return
        labelOrderId = order.order_id
        drawReady()
      })
    })
    const print = doc.querySelector('#wh5-label-print')
    if (print) print.addEventListener('click', printLabel)
    const close = doc.querySelector('#wh5-label-close')
    if (close) {
      close.addEventListener('click', () => {
        labelOrderId = null
        drawReady()
      })
    }
  }

  return {
    get worker() { return worker },
    get orders() { return orders },
    get labelOrderId() { return labelOrderId },
    /**
     * 首屏：先认身份，再拉列表。
     *
     * 🔴 身份读不到（401）⇒ 显式回落登录页；其它失败（网络 / 形状）⇒ **仍然尝试拉列表**
     * （把「页头读不到」变成「活干不了」是更坏的失败 —— 与计件页同口径）。
     */
    async boot() {
      if (!api.sessionId()) {
        goLogin()
        return
      }
      try {
        worker = await api.currentWorker()
      } catch (e) {
        if (e?.code === SESSION_EXPIRED) {
          goLogin()
          return
        }
      }
      await load()
    },
    reload: () => load(),
    printLabel,
  }
}

/** 浏览器入口（`shipment.html` 用 `<script type="module">` 直接加载，无构建步骤）。 */
export async function boot() {
  const api = createApi({ storage: globalThis.localStorage, deviceLabel: 'H5' })
  const app = createShipmentApp({ doc: globalThis.document, api })
  await app.boot()
  return app
}

if (globalThis.document?.getElementById?.('shipment-root')) {
  boot()
}
