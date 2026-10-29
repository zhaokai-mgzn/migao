// case_ids: PG-018, BM-006, DF-017
//
// 工人端 H5 **发货页**（issue #7761）：全完工待发货列表 + 50mm × 70mm 发货联（整套出库单，issue #7786）。
//
// 用户 2026-10-25 逐字：「发货工人要能看到全部完结的订单列表，即订单内的多套窗帘全完工的数据。
// 支持工人对完工的订单进行发货标签打印，包含客户的收货信息，走哪个物流/快递方式和公司」。
//
// 本文件的判据（每条都能单独变红）：
//   ① **筛选不在前端**：服务端给几行就渲染几行；**半完工行不得被前端补成「全完工」**，
//      也不得被前端偷偷丢掉（丢掉 = 出了事看不出是谁改的口径）；
//   ② **标签行清单是唯一真值**：行序 + 缺值 `—` + 不印两遍「客户」+ 物流类型**不回退「快递」**；
//   ③ **纸型只有一个来源**：`SHIP_LABEL_PAGE_SIZE` 必须逐字等于介质矩阵 `print-media.json`
//      的 `label-50x70.pageSize`，且 `@page` **只在** `ship-label.css` 出现（类级守卫：
//      混进共用的 styles.css ⇒ 报工页也被印成 50×70）；
//   ④ **打印只有一个调用点**：点「打印标签」才调 `window.print()`，且**只调一次**；
//      没打开预览时点不到打印（不出现「点一下打两张」）；
//   ⑤ 未登录（401）⇒ 显式回落登录页；读面失败**不冒充空态**（「没有单」≠「读不到」）；
//   ⑥ **纸长按内容撑开**（issue #7776）：`shipLabelLengthMm`/`shipLabelPageRule` 上取整 + 夹在
//      `[70,150]mm`、宽度恒 50mm；预览打开与点打印都按**当前**纸面重量 ⇒ 屏幕上看到的纸 = 打出来的纸。
import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  SHIP_LABEL_MAX_LENGTH_MM,
  SHIP_LABEL_MEDIA_ID,
  SHIP_LABEL_MIN_LENGTH_MM,
  SHIP_LABEL_MISSING,
  SHIP_LABEL_PAGE_SIZE,
  SHIP_LABEL_WIDTH_MM,
  buildShipLabelRows,
  renderReadyOrders,
  renderShipLabel,
  shipLabelLengthMm,
  shipLabelPageRule,
} from '../src/shipment.mjs'
import { createApi, SESSION_HEADER, STORAGE_KEY } from '../src/api.mjs'
import { createShipmentApp, SHIPMENT_LOGIN_HREF } from '../src/shipment-app.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const H5_SRC = path.join(HERE, '..', 'src')
const PRINT_MEDIA = path.join(HERE, '..', '..', 'admin-web', 'src', 'lib', 'print-media.json')

/** 服务端列表行夹具（**全部套已完工**；字段面 = `WorkerShipmentReadyService.rowView`）。 */
const READY_ROW = {
  order_id: 'o-1',
  order_no: '0901-000084',
  status: 'producing',
  status_label: '生产中',
  created_at: '2026-09-01T10:00:00+08:00',
  customer_name: '肖风伟',
  customer_phone: '13849944707',
  customer_address: '洛阳市涧西区某某路 18 号 3 单元 502',
  logistics_type: 'logistics',
  logistics_type_label: '物流专线',
  logistics_company: '四季安',
  total_sets: 3,
  completed_sets: 3,
  processing_order_no: 'JG-20260901-001',
  remark: '样品货款 600 元',
}

/** 老实说：这一行**不该**由服务端下发（半完工），夹具里放它是为了钉住「前端不自己补算」。 */
const HALF_ROW = { ...READY_ROW, order_id: 'o-2', order_no: '0901-000085', total_sets: 3, completed_sets: 1 }

// ── ① 列表：服务端说什么就渲染什么（前端不筛、不补算） ─────────────────────────────

test('列表渲染服务端给的行：半完工行不得被补成「全完工」，也不得被前端自己丢掉', () => {
  const html = renderReadyOrders({ items: [READY_ROW, HALF_ROW], scan: { limit: 200, truncated: false } })
  assert.match(html, /id="wh5-ready-0"/)
  assert.match(html, /id="wh5-ready-1"/, '前端把服务端给的第二行丢了（等于在前端重做了一遍筛选）')
  assert.match(html, /3 套（全完工）/, '全完工那一行要明说全完工')
  assert.match(html, /1\/3 套/, '半完工行要照实说 1/3，不能显示成「全完工」')
  assert.match(html, /待发货 2 单/, '计数取服务端给的 items.length')
})

test('空列表 = 可行动空态（不是空白、不是「加载中」）', () => {
  const html = renderReadyOrders({ items: [], scan: { limit: 200, truncated: false } })
  assert.match(html, /id="wh5-ready-empty"/)
  assert.match(html, /最后一道工序报完后/, '空态要告诉工人「怎么才会有单」，不是只说「没有」')
  assert.ok(!html.includes('wh5-ready-0'), '空态不得再渲染行')
})

test('截断显式（不静默少显示）', () => {
  const html = renderReadyOrders({ items: [READY_ROW], scan: { limit: 200, truncated: true } })
  assert.match(html, /id="wh5-ready-truncated"/)
  assert.match(html, /200/, '把上限也说出来，工人知道「不是只有这一单」')
})

test('地址折行而不是省略（省略 = 工人不知道发去哪）', () => {
  const html = renderReadyOrders({ items: [READY_ROW] })
  assert.match(html, /洛阳市涧西区某某路 18 号 3 单元 502/)
  assert.ok(!/line-clamp|truncate/.test(html), '列表里的地址不得带截断类')
})

// ── ② 发货联：行清单是唯一真值 ─────────────────────────────────────────────────

test('标签行序与字段面：订单号 / 收货人 / 电话 / 地址 / 物流类型 / 物流公司 / 下单日期 / 套数 / 备注', () => {
  const rows = buildShipLabelRows(READY_ROW)
  assert.deepEqual(rows.map((r) => r.label),
    ['订单号', '收货人', '电话', '地址', '物流类型', '物流公司', '下单日期', '套数', '备注'])
  assert.equal(rows[0].value, '0901-000084')
  assert.equal(rows[1].value, '肖风伟')
  assert.equal(rows[2].value, '13849944707')
  assert.equal(rows[4].value, '物流专线', '物流类型取服务端展示名（express/logistics 这类内部键不得上纸）')
  // 术语（issue #8080）：这一栏是「物流类型」（快递 / 物流专线）。商家后台的「物流方式」专指
  // `shippingMethod`（物流发货 / 无需物流）—— 负控：把 label 改回「物流方式」⇒ 上面 deepEqual 与本行都红。
  assert.ok(!rows.some((r) => r.label === '物流方式'), '「物流方式」是发货方式的专名，两端不得共用一个词')
  assert.equal(rows[5].value, '四季安')
  assert.equal(rows[6].value, '2026-09-01', '下单日期 = 服务端 created_at 按业务时区的 YYYY-MM-DD（issue #7786）')
  assert.equal(rows[7].value, '3 套（全完工）')
  // 🔴 信息不重复：客户 = 收货人（同一列），不得印两遍（§31 P2）
  assert.equal(rows.filter((r) => r.value === '肖风伟').length, 1, '「客户」与「收货人」是同一列，印两遍只是白吃版面')
  assert.ok(!rows.some((r) => r.label === '客户'), '不得再有「客户」行')
})

test('帘种 / 安装小区 / 安装位置：有值就印、缺值整行不印（issue #7856），且排在地址之后', () => {
  const rows = buildShipLabelRows({
    ...READY_ROW,
    curtain_types: '布帘/纱帘',
    install_community: '春江花园 3栋2单元',
    install_rooms: '主卧/阳台',
  })
  const keys = rows.map((r) => r.key)
  // 随货标识紧跟在「地址」之后、物流之前（拣货的人先认地址，再认装到哪户哪扇窗）
  assert.equal(keys.indexOf('curtain_types'), keys.indexOf('customer_address') + 1)
  assert.equal(keys.indexOf('install_community'), keys.indexOf('curtain_types') + 1)
  assert.equal(keys.indexOf('install_rooms'), keys.indexOf('install_community') + 1)
  assert.equal(rows.find((r) => r.key === 'curtain_types').value, '布帘/纱帘')
  assert.equal(rows.find((r) => r.key === 'install_community').value, '春江花园 3栋2单元')
  assert.equal(rows.find((r) => r.key === 'install_rooms').value, '主卧/阳台')
  assert.equal(rows.find((r) => r.key === 'install_rooms').multiline, true, '安装位置可能多扇窗 ⇒ 允许折行')

  // 🔴 缺值（存量单 / C 端先空后补）= 整行不印，不印 `—` 白吃 50mm 版心
  const blank = buildShipLabelRows({ ...READY_ROW, curtain_types: '', install_community: null, install_rooms: '  ' })
  assert.ok(!blank.some((r) => r.key === 'curtain_types'))
  assert.ok(!blank.some((r) => r.key === 'install_community'))
  assert.ok(!blank.some((r) => r.key === 'install_rooms'))
})

test('缺值不编造：null / 空串 ⇒ `—`，且物流类型**不回退「快递」**', () => {
  const rows = buildShipLabelRows({
    order_no: '0901-000086', customer_name: '', customer_phone: null,
    customer_address: '   ', logistics_type: null, logistics_type_label: null,
    logistics_company: null, total_sets: 2, completed_sets: 2, remark: null,
  })
  const byKey = Object.fromEntries(rows.map((r) => [r.key, r.value]))
  assert.equal(byKey.consignee, SHIP_LABEL_MISSING)
  assert.equal(byKey.customer_phone, SHIP_LABEL_MISSING)
  assert.equal(byKey.customer_address, SHIP_LABEL_MISSING)
  assert.equal(byKey.logistics_type, SHIP_LABEL_MISSING, '未采集的物流类型不得被猜成「快递」（那会把物流专线发成快递）')
  assert.equal(byKey.logistics_company, SHIP_LABEL_MISSING)
  assert.ok(!rows.some((r) => r.key === 'remark'), '备注为空 ⇒ 整行不渲染（不留空行）')
  assert.ok(!rows.some((r) => r.value === '0' || r.value === 'undefined'), '缺值不得印成 0 / undefined')
})

test('下单日期按业务时区（Asia/Shanghai）出 YYYY-MM-DD：跨 UTC 日期的一天不得印成前一天', () => {
  // 2026-09-01T16:30:00Z = 上海 2026-09-02 00:30 ⇒ 纸面必须是 09-02；
  // 按 UTC / 按服务器本地时区切字符串都会印成 09-01（这就是本判据要钉住的那一类）。
  const rows = buildShipLabelRows({ ...READY_ROW, created_at: '2026-09-01T16:30:00Z' })
  assert.equal(rows.find((r) => r.key === 'order_date').value, '2026-09-02')
  // 反向对照：带 +08:00 偏移的同一时刻 ⇒ 仍是 09-02（不重复换算）
  const same = buildShipLabelRows({ ...READY_ROW, created_at: '2026-09-02T00:30:00+08:00' })
  assert.equal(same.find((r) => r.key === 'order_date').value, '2026-09-02')
})

test('下单日期缺值 / 坏值 ⇒ `—`（不猜今天、不印 Invalid Date）', () => {
  for (const bad of [null, undefined, '', '   ', 'not-a-date']) {
    const row = buildShipLabelRows({ ...READY_ROW, created_at: bad }).find((r) => r.key === 'order_date')
    assert.equal(row.value, SHIP_LABEL_MISSING, `created_at=${String(bad)} 时必须印 —`)
  }
})

test('半完工的套数照实印（纸面也不补算）', () => {
  const rows = buildShipLabelRows(HALF_ROW)
  assert.equal(rows.find((r) => r.key === 'sets').value, '1/3 套')
})

test('发货联 HTML：抬头 + 每行稳定 data-label-key（纸面判据按 key 取，不按文案）', () => {
  const html = renderShipLabel(READY_ROW)
  for (const key of ['order_no', 'consignee', 'customer_phone', 'customer_address',
    'logistics_type', 'logistics_company', 'order_date', 'sets', 'remark']) {
    assert.match(html, new RegExp(`data-label-key="${key}"`), `发货联缺 ${key} 行`)
  }
  assert.match(html, /id="wh5-ship-label"/)
  assert.match(html, /发货联/, '抬头缺失（纸上第一眼不知道这是什么单）')
  assert.ok(!html.includes('发货标签'), '旧抬头「发货标签」必须退场（issue #7786 改判为发货联）')
  assert.ok(!html.includes('express') && !html.includes('logistics"'), '内部键不得上纸')
})

test('列表行内动作叫「发货联」，纸面 = 整套出库单（一单一张，覆盖该订单全部套）', () => {
  const html = renderReadyOrders({ items: [READY_ROW] })
  assert.match(html, /id="wh5-label-0"[^>]*>发货联</, '行内动作要叫发货联（不是「发货标签」）')
  assert.ok(!html.includes('>发货标签<'), '旧动作名必须退场')
  // 整套 = 纸面自己读得到「共 N 套」，不必回列表核对
  assert.match(renderShipLabel(READY_ROW), /3 套（全完工）/)
})

// ── ③ 纸型：单一真值 + 类级守卫 ────────────────────────────────────────────────

test('纸型 = 50mm 宽连续卷纸 + **纸长按内容撑开**（issue #7776），宽 / 上下限与介质矩阵逐值一致', () => {
  // 用户 2026-10-25 逐字选了「复用现有 50mm × 70mm（DP235S 标签纸）」；同一天又裁定
  // 「字体太小了，可以把长度延长些，因为长度可以无限长……上下两头留白太多了」
  // ⇒ 70mm 降级为**最短**纸长（驱动里该登记的那档），实际纸长按纸面内容算。
  assert.equal(SHIP_LABEL_PAGE_SIZE, '50mm 70mm', '静态兜底纸型（ship-label.css）必须与矩阵同值')

  const matrix = JSON.parse(fs.readFileSync(PRINT_MEDIA, 'utf8'))
  const spec = (matrix.media ?? []).find((m) => m.id === SHIP_LABEL_MEDIA_ID)
  assert.ok(spec, `介质矩阵里没有 ${SHIP_LABEL_MEDIA_ID}（纸型凭空出现了）`)
  assert.equal(SHIP_LABEL_WIDTH_MM, spec.pageBoxMm.widthMm, '纸宽必须与矩阵同一份')
  assert.equal(SHIP_LABEL_MIN_LENGTH_MM, spec.lengthMm?.minMm ?? spec.pageBoxMm.heightMm,
    '最短纸长必须 = 矩阵的 lengthMm.minMm（缺省退回 pageBoxMm.heightMm）')
  assert.equal(SHIP_LABEL_MAX_LENGTH_MM, spec.lengthMm?.maxMm ?? SHIP_LABEL_MAX_LENGTH_MM,
    '最长纸长必须 = 矩阵的 lengthMm.maxMm')
  assert.equal(SHIP_LABEL_PAGE_SIZE, `50mm ${spec.pageBoxMm.heightMm}mm`, '静态兜底与矩阵 pageSize 同值')
})

test('纸长按内容撑开：上取整到 1mm、夹在 [70,150]mm（量不到 ⇒ 最短，绝不裁内容）', () => {
  // 1 CSS px = 25.4/96 mm：200px ≈ 52.9mm < 下限 ⇒ 70；400px ≈ 105.8mm ⇒ 106（上取整）
  assert.equal(shipLabelLengthMm(200), 70, '短内容不短于最短纸长')
  assert.equal(shipLabelLengthMm(400), 106)
  assert.equal(shipLabelLengthMm(0), 70, '量不到（0 / NaN）⇒ 最短纸长，不退化成 0')
  assert.equal(shipLabelLengthMm(Number.NaN), 70)
  assert.equal(shipLabelLengthMm(99999), 150, '超长内容夹在上限（纸不可能无限长）')
  // 正向对照：**不是**恒返回下限（写死 70 ⇒ 上面那条 106 必红）
  assert.notEqual(shipLabelLengthMm(400), 70)

  assert.equal(shipLabelPageRule(106), '@page { size: 50mm 106mm; margin: 0; }')
  assert.equal(shipLabelPageRule(10), '@page { size: 50mm 70mm; margin: 0; }', '非法值夹到最短纸长')
})

test('装配层：预览打开 / 点打印都按**当前**纸面定纸长（标签高度与 @page 同一个数）', async () => {
  const injected = []
  const label = { style: { height: '' }, scrollHeight: 400 }
  let injectedStyle = null  // 真 DOM：`getElementById('wh5-label-page-size')` 第 2 次起必须命中同一个节点
  const doc = {
    ...fakeDoc(),
    getElementById: (id) => {
      if (id === 'wh5-ship-label') return label
      if (id === 'wh5-label-page-size') return injectedStyle
      if (id === 'shipment-root') return doc._root
      return null
    },
    createElement: () => ({ id: '', textContent: '' }),
    head: {
      appendChild: (el) => {
        injected.push(el)
        injectedStyle = el
      },
    },
  }
  const api = {
    sessionId: () => 'sess-1',
    currentWorker: async () => ({ workerName: '张三' }),
    listReadyShipments: async () => ({ items: [READY_ROW] }),
  }
  const app = createShipmentApp({ doc, api, win: { print: () => {} } })
  await app.boot()
  doc._fire('#wh5-label-0')  // 打开预览 ⇒ 立刻定纸长
  assert.equal(label.style.height, '106mm', '预览纸面高度 = 量到内容换算的纸长')
  assert.equal(injected.at(-1)?.textContent, '@page { size: 50mm 106mm; margin: 0; }',
    '`@page` 必须跟着同一个数改（否则预览与纸上对不上）')
  const count = injected.length
  doc._fire('#wh5-label-print')  // 打印前重量一次（字体 / 缩放可能变）
  assert.equal(injected.length, count, '已注入的 style 复用，不重复 append')
  assert.equal(injected.at(-1)?.textContent, '@page { size: 50mm 106mm; margin: 0; }')
})

test('类级：`@page` 只在 ship-label.css 出现（混进共用的 styles.css ⇒ 报工页也被印成 50×70）', () => {
  // 🔴 去注释再扫：`styles.css` 里那句「`@page` 是文档级声明…」是**解释**，不是声明
  //    （不去注释 ⇒ 假红 —— 「引用即实例」这一族，见 migao-dev-flow §2.2）
  const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '')
  const cssFiles = fs.readdirSync(H5_SRC).filter((f) => f.endsWith('.css'))
  const withPage = cssFiles.filter((f) => /@page/.test(stripComments(fs.readFileSync(path.join(H5_SRC, f), 'utf8'))))
  assert.deepEqual(withPage, ['ship-label.css'],
    `声明 @page 的文件必须是且只有 ship-label.css，实际：${withPage.join(', ') || '（无）'}`)
  const labelCss = fs.readFileSync(path.join(H5_SRC, 'ship-label.css'), 'utf8')
  assert.match(labelCss, /size:\s*50mm 70mm/, '标签纸的 @page 尺寸与介质矩阵不一致')
  assert.match(labelCss, /@media print/, '缺打印态隔离（列表会被一起印出来）')
  assert.match(labelCss, /display:\s*none !important/, '打印隔离必须用 display:none（visibility 会留空白页）')
})

test('类级：原发布集里的 worker-h5 页面都能加载到新页（同源静态路径）', () => {
  const html = fs.readFileSync(path.join(HERE, '..', 'shipment.html'), 'utf8')
  assert.match(html, /src="\.\/src\/shipment-app\.mjs"/)
  assert.match(html, /href="\.\/src\/styles\.css"/)
  assert.match(html, /href="\.\/src\/ship-label\.css"/)
})

// ── ④ API + 装配层：打印只有一个调用点 ─────────────────────────────────────────

function memoryStorage(seed = {}) {
  const map = new Map(Object.entries(seed))
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
  }
}

function fakeDoc() {
  const handlers = new Map()
  const root = { _html: '' }
  Object.defineProperty(root, 'innerHTML', {
    get: () => root._html,
    set: (v) => { root._html = v; handlers.clear() },  // 真 DOM 里旧节点连同监听器一起被替换掉
  })
  return {
    getElementById: (id) => (id === 'shipment-root' ? root : null),
    querySelector: (sel) => ({
      addEventListener: (type, fn) => {
        const list = handlers.get(sel) ?? []
        list.push(fn)
        handlers.set(sel, list)
      },
    }),
    _root: root,
    _fire: (sel) => (handlers.get(sel) ?? []).forEach((fn) => fn({ preventDefault() {} })),
    _has: (sel) => handlers.has(sel),
  }
}

const LOGGED_IN = { [STORAGE_KEY]: JSON.stringify({ sessionId: 'sess-1', workerName: '张三' }) }

test('API：列表走 GET /api/worker/shipment/orders（身份只由会话头带）', async () => {
  const seen = []
  const api = createApi({
    storage: memoryStorage(LOGGED_IN),
    fetchImpl: async (url, init = {}) => {
      seen.push({ url, init })
      return { ok: true, status: 200, json: async () => ({ success: true, data: { items: [READY_ROW] } }) }
    },
  })
  const data = await api.listReadyShipments()
  assert.equal(data.items.length, 1)
  assert.match(seen[0].url, /\/api\/worker\/shipment\/orders$/)
  assert.equal(seen[0].init?.method ?? 'GET', 'GET')
  assert.equal(seen[0].init.headers[SESSION_HEADER], 'sess-1')
})

test('装配层：列表 → 点「发货联」才出纸面 → 点「打印发货联」只调一次 window.print()', async () => {
  let printed = 0
  const doc = fakeDoc()
  const api = {
    sessionId: () => 'sess-1',
    currentWorker: async () => ({ workerName: '张三', workerNo: 'W-001' }),
    listReadyShipments: async () => ({ items: [READY_ROW], scan: { limit: 200, truncated: false } }),
  }
  const app = createShipmentApp({ doc, api, win: { print: () => { printed += 1 } } })
  await app.boot()

  assert.match(doc._root.innerHTML, /0901-000084/)
  assert.ok(!doc._root.innerHTML.includes('id="wh5-ship-label"'), '没点开就不该有纸面（否则一进页就能打印）')
  assert.equal(printed, 0)

  doc._fire('#wh5-label-0')
  assert.equal(app.labelOrderId, 'o-1')
  assert.match(doc._root.innerHTML, /id="wh5-ship-label"/)

  doc._fire('#wh5-label-print')
  assert.equal(printed, 1, '打印必须恰好一次（两次 = 两张纸 / 两张标签）')

  doc._fire('#wh5-label-close')
  assert.equal(app.labelOrderId, null, '关闭后纸面不再挂在版面上')
  assert.ok(!doc._root.innerHTML.includes('id="wh5-ship-label"'))
})

test('装配层：401 ⇒ 显式回落登录页（不按上一个人的身份发货）', async () => {
  const doc = fakeDoc()
  const api = {
    sessionId: () => null,
    currentWorker: async () => { throw new Error('不该被调用') },
    listReadyShipments: async () => { throw new Error('不该被调用') },
  }
  const app = createShipmentApp({ doc, api, win: { print: () => {} } })
  await app.boot()
  assert.match(doc._root.innerHTML, /id="wh5-shipment-login-required"/)
  assert.match(doc._root.innerHTML, new RegExp(`href="${SHIPMENT_LOGIN_HREF}"`))
})

test('装配层：读面失败**不冒充空态**（「没有单」≠「读不到」）', async () => {
  const doc = fakeDoc()
  const api = {
    sessionId: () => 'sess-1',
    currentWorker: async () => ({ workerName: '张三' }),
    listReadyShipments: async () => { throw new Error('网络超时，请再按一次') },
  }
  const app = createShipmentApp({ doc, api, win: { print: () => {} } })
  await app.boot()
  assert.match(doc._root.innerHTML, /id="wh5-shipment-error"/)
  assert.match(doc._root.innerHTML, /网络超时/)
  assert.ok(!doc._root.innerHTML.includes('id="wh5-ready-empty"'), '读失败不得渲染「暂无全部完工的订单」')
  assert.match(doc._root.innerHTML, /id="wh5-shipment-retry"/)
})
