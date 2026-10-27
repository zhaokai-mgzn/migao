// case_ids: PG-018, BM-006, DF-017
//
// 工人端 H5「我的计件」——装配层（DOM 绑定 + 月份切换 + 会话失效回落）。
//
// 判据都在 `piecework.mjs` 的纯函数里（可被 `node --test` 直接钉住，无需 DOM）；本文件只做接线：
//   ① 首屏先拉 `GET /api/worker/me` 认身份（**页头常驻「当前工人」**是共用 PAD 的既有纪律，
//      session 默认 30 天不过期 ⇒ 屏上必须能看出「这笔钱会记到谁头上」）；
//   ② 计件读数**只**来自 `GET /api/worker/piecework`（本页不求和、不算月份边界）；
//   ③ 401 ⇒ 显式回落「请先登录」，并给登录页真链接（不静默重试、不按上一个人的身份读钱）。

import { createApi, SESSION_EXPIRED } from './api.mjs'
import { PIECEWORK_UNREADABLE, renderPiecework } from './piecework.mjs'

/** 登录页（同源静态页；本页未登录时的出口）。 */
export const PIECEWORK_LOGIN_HREF = './'

/** 从 URL 读 `?month=YYYY-MM`（深链用；缺省 = 服务端按当前自然月）。 */
export function monthFromLocation(location) {
  try {
    const search = typeof location === 'string' ? location.split('?')[1] ?? '' : location?.search ?? ''
    const month = new URLSearchParams(search).get('month')
    return month && /^\d{4}-\d{2}$/.test(month) ? month : ''
  } catch {
    return ''
  }
}

/** HTML 转义（与 render.mjs 同口径）。 */
function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/**
 * 页头「当前工人」（**服务端**来源，共用 PAD 纪律）。
 *
 * 🔴 为什么本页也必须有：计件 = 工资凭证，而 session 默认 30 天不过期
 * （`WorkerSessionService.DEFAULT_IDLE_MINUTES`）⇒ 屏上必须能看出「这笔钱会记到谁头上」，
 * 否则上一班没登出时下一个人看到的是别人的工资。
 */
function pageHeader(worker) {
  const name = esc(worker?.workerName ?? '')
  const no = esc(worker?.workerNo ?? '')
  if (!name) return ''
  return `<header class="wh5-header">
    <span class="wh5-worker" id="wh5-current-worker">当前工人：${name}${no ? `（工号 ${no}）` : ''}</span>
    <a class="wh5-ghost" id="wh5-piecework-back" href="./">返回报工</a>
  </header>`
}

/** 「登录已失效」的显式文案 + 回登录页真链接（本页没有登录面）。 */
function loginFallback() {
  return `<section class="wh5-card">
    <h1 class="wh5-title">我的计件</h1>
    <p class="wh5-error" id="wh5-piecework-login-required">登录已失效：请先用工号 + PIN 登录，再查看计件。</p>
    <a class="wh5-entry" id="wh5-piecework-login" href="${PIECEWORK_LOGIN_HREF}">去登录</a>
  </section>`
}

/**
 * 装配「我的计件」页。
 *
 * @param {object} deps
 * @param {Document} deps.doc
 * @param {object} deps.api
 * @param {Location|string} [deps.location]
 * @param {Function} [deps.replace] 换页动作（缺省 `location.replace`）
 */
export function createPieceworkApp({ doc, api, location = globalThis.location, replace = null }) {
  const root = doc.getElementById('piecework-root')
  let month = monthFromLocation(location)
  let worker = null
  let html = '<p class="wh5-sub" id="wh5-piecework-loading">正在读取计件…</p>'

  const draw = () => {
    if (root) root.innerHTML = `${pageHeader(worker)}${html}`
    bind()
  }

  const goLogin = () => {
    html = loginFallback()
    draw()
  }

  /** 拉一次读数并渲染（月份切换 = 带 `month` 再拉一次，**前端不做任何金额/月份计算**）。 */
  async function load(nextMonth = month) {
    month = nextMonth
    try {
      const data = await api.readPiecework({ month })
      html = renderPiecework(data)
      draw()
    } catch (e) {
      if (e?.code === SESSION_EXPIRED) {
        goLogin()
        return
      }
      // 读数形状 / 网络失败：**显式**上屏（涉钱面不静默当 0）
      html = `<section class="wh5-card">
        <h1 class="wh5-title">我的计件</h1>
        <p class="wh5-error" id="wh5-piecework-error">${e?.message ?? PIECEWORK_UNREADABLE}</p>
      </section>`
      draw()
    }
  }

  function bind() {
    const prev = doc.querySelector('#wh5-piecework-prev')
    if (prev) prev.addEventListener('click', () => { void load(prev.dataset.month) })
    const next = doc.querySelector('#wh5-piecework-next')
    if (next) next.addEventListener('click', () => { void load(next.dataset.month) })
    const login = doc.querySelector('#wh5-piecework-login')
    if (login && typeof replace === 'function') {
      login.addEventListener('click', (event) => {
        event.preventDefault()
        replace(PIECEWORK_LOGIN_HREF)
      })
    }
  }

  return {
    get month() { return month },
    get worker() { return worker },
    /**
     * 首屏：先认身份（页头「当前工人」来自**服务端**），再拉本页读数。
     *
     * 🔴 身份读不到（401）⇒ 显式回落登录页；其它失败（网络 / 形状）⇒ 仍然尝试拉读数
     * （把「页头读不到」变成「钱看不到」是更坏的失败）。
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
      await load(month)
    },
    /** 供装配层/测试显式刷新。 */
    reload: () => load(month),
  }
}

/** 浏览器入口（`piecework.html` 用 `<script type="module">` 直接加载，无构建步骤）。 */
export async function boot() {
  const api = createApi({ storage: globalThis.localStorage, deviceLabel: 'H5' })
  const app = createPieceworkApp({ doc: globalThis.document, api })
  await app.boot()
  return app
}

if (globalThis.document?.getElementById?.('piecework-root')) {
  boot()
}
