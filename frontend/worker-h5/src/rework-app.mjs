// case_ids: PG-098
//
// 工人端 H5「报返工的加工单」页 —— 装配层（issue #7860）。
//
// 判据都在 `rework.mjs` 的纯函数里（`node --test` 直接钉住，无需 DOM）；本文件只做接线：
//   ① 首屏先拉 `GET /api/worker/production/current-worker` 认身份（**页头常驻「当前工人」**：
//      共用 PAD 的既有纪律 —— 屏上必须能看出是「谁」在看）；
//   ② 列表**只**来自 `GET /api/worker/production/rework-orders`（本页不筛、不排、不补算）；
//   ③ 401 ⇒ 显式回落「登录已失效」+ `/w/` 登录页真链接（不静默重试）；
//   ④ 403 ⇒ 工人档案页面集里没有 `rework` 键 ⇒ **可行动**提示（不冒充「读不到」也不冒充「空」）；
//   ⑤ 身份读不到（非 401）仍**继续拉列表** —— 把「页头读不到」变成「活干不了」是更坏的失败。

import { createApi, SESSION_EXPIRED } from './api.mjs'
import {
  REWORK_LOGIN_HREF,
  renderPageHeader,
  renderReworkForbidden,
  renderReworkList,
  renderReworkLoginRequired,
  renderReworkUnreadable,
} from './rework.mjs'

/** 「页面集里没有 `rework` 键」的 HTTP 面（`api.mjs` 把服务端 status 原样挂在 `err.status` 上）。 */
const HTTP_FORBIDDEN = 403

/**
 * 装配「报返工的加工单」页。
 *
 * @param {object} deps
 * @param {Document} deps.doc
 * @param {object} deps.api
 * @param {Function} [deps.replace] 换页动作（缺省让 `<a href>` 自己跳 —— 真链接优先）
 */
export function createReworkApp({ doc, api, replace = null }) {
  const root = doc.getElementById('rework-root')
  let worker = null
  /** 服务端给的返工加工单行（**原样**持有；本页不再过滤/排序） */
  let orders = []
  let html = '<p class="wh5-sub" id="wh5-rework-loading">正在读取报返工的加工单…</p>'

  const draw = () => {
    if (root) root.innerHTML = `${renderPageHeader(worker)}${html}`
    bind()
  }

  const goLogin = () => {
    html = renderReworkLoginRequired()
    draw()
  }

  async function load() {
    try {
      const data = await api.listReworkOrders()
      orders = Array.isArray(data?.orders) ? data.orders : []
      html = renderReworkList({ orders })
      draw()
    } catch (e) {
      if (e?.code === SESSION_EXPIRED) {
        goLogin()
        return
      }
      // 页面没开（403）与「读不到」（网络 / 5xx）是**两个事实**，工人该做的事也不同
      html = e?.status === HTTP_FORBIDDEN ? renderReworkForbidden() : renderReworkUnreadable(e)
      draw()
    }
  }

  function bind() {
    const retry = doc.querySelector('#wh5-rework-retry')
    if (retry) retry.addEventListener('click', () => { void load() })
    // 登录 / 返回报工都是**真链接**（`<a href="/w/">`）：`replace` 只在被注入时才接管（测试替身）
    for (const id of ['wh5-rework-login', 'wh5-rework-back', 'wh5-rework-forbidden-back']) {
      const link = doc.querySelector(`#${id}`)
      if (link && typeof replace === 'function') {
        link.addEventListener('click', (event) => {
          event.preventDefault()
          replace(REWORK_LOGIN_HREF)
        })
      }
    }
  }

  return {
    get worker() { return worker },
    get orders() { return orders },
    /**
     * 首屏：先认身份，再拉列表。
     *
     * 🔴 未登录 ⇒ 显式回落登录页；身份读不到（非 401）⇒ **仍然尝试拉列表**
     * （页头那块空了不影响工人看返工名单 —— 与发货页 / 计件页同口径）。
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
  }
}

/** 浏览器入口（`rework.html` 用 `<script type="module">` 直接加载，无构建步骤）。 */
export async function boot() {
  const api = createApi({ storage: globalThis.localStorage, deviceLabel: 'H5' })
  const app = createReworkApp({ doc: globalThis.document, api })
  await app.boot()
  return app
}

if (globalThis.document?.getElementById?.('rework-root')) {
  boot()
}
