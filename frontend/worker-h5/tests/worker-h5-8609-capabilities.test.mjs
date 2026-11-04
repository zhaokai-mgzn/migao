// case_ids: MC-192
//
// 工人端 `/w/` 的**第三轴：本机能力**（`window.migaoTerminal.capabilities`）—— issue #8609 B 包。
//
// 用户的裁定（2026-11-04 逐字）：
//   ①「安卓一体机和 window 一体机功能完全一样，也有串口和下发动作」
//   ②「手持标签机不需要裁高计算/下发」
//   ③「接受，我也希望一个包搞定」
// ⇒ **一份业务面 + 两个薄壳 + 一个 apk 覆盖两种安卓设备**：菜单 = `users.worker_pages`
//    ∩ 租户页面开关 ∩ **本机 capabilities**（三轴与）。前两轴已在 `effectivePages`（本文件**不**重造），
//    第三轴由本文件钉住：`cut.link` ⇒ 裁高计算入口；`print.label` ⇒ 打印入库标签。
//
// 四条判据（每条都能红；红证 = 注入后当场红、恢复后绿，读数见 PR body）：
//   ① **能力缺省即隐藏（fail-closed）**：桥缺失 / `capabilities` 缺失 / 非对象 / 空串 / 非字符串
//      ⇒ 两个硬件入口**都不渲染**（不是点了报错，也不留死按钮）。
//      红证：把 `terminalCapabilities` 的 `read()` 改成 `return 'ble'`（恒真）⇒ 手持机出现裁高入口 ⇒ 红。
//   ② **同一 `worker_pages` 两台设备菜单不同**（差异**只**来自 capabilities）：
//      同一份 pages（全开）下，手持机 = 只有标签机；一体机 = 只有裁高机；两者都在的设备 = 两个都有。
//      红证：把第三轴从判定里去掉（`caps.cut !== null` → `true`）⇒ 两台一模一样 ⇒ 本判据红。
//   ③ **无硬件不阻断其它功能**：裁高机 / 标签机都缺席 ⇒ 报工主流程（扫码提示 / 报工卡 / 返工记录入口）
//      照旧可用、按钮不禁用 —— 只少了那两个入口（`migao-dev-flow` §31 P1：不给整页摆红字）。
//   ④ **出错不白屏**：`window.migaoTerminal` **整块缺失**（浏览器直接打开 `/w/`）⇒ 装配层按
//      「无任何能力」跑，既有页面（登录卡 / 扫码页 / 页头）一个都不消失。这是回归面。
//
// 类级元守卫（`migao-dev-flow` §23 / 铁律 8）—— 让同类缺陷进不来：
//   a）**桥只在装配层碰一次**：`window.migaoTerminal` 的代码引用只许出现在 `src/app.mjs`（1 处），
//      `render.mjs` 是纯函数层（读 `state.terminal`，不碰全局）。第三处出现 ⇒ 红（那是第二份真值）。
//   b）**未登记即红**：`terminalCapabilities` 返回的能力轴必须与下面的 `CAPABILITY_LEDGER` **逐键相等**
//      —— 读取器加了一条能力却没登记入口 / 登记了没实现 ⇒ 红。
//   c）**登记了就必须双向判**：台账每一条都要在"在场"与"缺席"两种状态下各判一次（表驱动），
//      新增硬件入口不许只加渲染不加入口判据。
import { readdirSync, readFileSync } from 'node:fs'
import test from 'node:test'
import assert from 'node:assert/strict'

import { createApp } from '../src/app.mjs'
import {
  CAP_CUT_LINK,
  CAP_PRINT_LABEL,
  initialState,
  PAGE_CUT_CALC,
  PAGE_INSPECT,
  PAGE_REPORT,
  PAGE_REWORK,
  renderPage,
  terminalCapabilities,
} from '../src/render.mjs'

/**
 * 硬件入口台账（**类级元守卫的单一真值源**）：能力键 → 读取器的轴名 → 渲染出来的元素 id。
 *
 * ⚠️ 只登记**页面有对应面**的能力。issue #8609 能力表里另外三条（`scan.hid` / `scan.camera` /
 * `update.channel`）在 `/w/` 上**没有任何 UI 差异**（扫码是键盘楔，扫码枪与摄像头在页面看来一样；
 * 更新通道是壳自己的事）⇒ **有意不登记**：读了不用 = 假轴，判据会绿而屏幕上什么都没变。
 * 将来哪一条长出对应面（例如摄像头扫码给一个「扫」按钮），先在这里加一行，元守卫 b/c 会强制补判据。
 */
const CAPABILITY_LEDGER = [
  { key: CAP_CUT_LINK, axis: 'cut', entry: 'wh5-machine-entry' },
  { key: CAP_PRINT_LABEL, axis: 'print', entry: 'wh5-fi-print' },
]

const HARDWARE_IDS = CAPABILITY_LEDGER.map((r) => r.entry)

const WORKER = { workerName: '张师傅', workerNo: 'W-001', idleMinutes: 43200 }

/** 全开页面集（含逐人开的 `inspect` / `rework`）—— 判的是第三轴，第一轴固定为"全开"。 */
const ALL_PAGES = [PAGE_REPORT, PAGE_CUT_CALC, PAGE_REWORK, PAGE_INSPECT, 'piecework', 'to_ship', 'order', 'shipment', 'stock', 'inbound', 'reprint']

/** 已登录 + 指定页面集（第一轴直接落在 state 上：本文件只测渲染，不走装配层）。 */
const loggedIn = (pages, extra = {}) => ({ ...initialState(), worker: WORKER, mode: 'scan', pages, ...extra })

/** 去 HTML 注释后的可见文本（注释里的锚点不是入口，与既有 pages 判据同口径）。 */
const visible = (html) => html.replace(/<!--[\s\S]*?-->/g, '')

/** 壳注入的能力表（**完整五键**，取值照 issue #8609 的能力表）。 */
const caps = (over = {}) => ({
  'scan.hid': true,
  'scan.camera': false,
  [CAP_CUT_LINK]: null,
  [CAP_PRINT_LABEL]: null,
  'update.channel': 'apk',
  ...over,
})

/** 壳注入的桥（`window.migaoTerminal` 的形状）。 */
const bridge = (over = {}) => ({ capabilities: caps(over) })

/** 手持标签机：有标签机、**没有**裁高机链路。 */
const HANDHELD = bridge({ [CAP_PRINT_LABEL]: 'ble' })

/** 安卓一体机：有裁高机链路（串口）、**没有**标签机。 */
const ALL_IN_ONE = bridge({ [CAP_CUT_LINK]: 'serial:COM3' })

/** 两个能力都有的设备（一台一体机外挂标签机时就是这个形态）。 */
const BOTH = bridge({ [CAP_CUT_LINK]: 'serial:COM3', [CAP_PRINT_LABEL]: 'ble' })

/** 扫到一件的详情视图（`operation` 在场 ⇒ 主屏 = 报工卡；成品入库卡挂在页头下面）。 */
const RESOLVED_VIEW = {
  granularity: 'set_position',
  set_no: 14,
  set_index: 13,
  position: { order_item_id: 'oi-1', position_name: '布帘' },
  operation: { operation_id: 'op-1', logical_name: '定型', unit: '米', qty: 11, unit_price: 3.5 },
  alternatives: [],
  needs_selection: [],
  completed: false,
}

/** 服务端随回执下发的成品入库块（打印按钮的数据源）。 */
const FINISHED = {
  inbound_no: 'RK20261104001',
  bin_code: 'A-01',
  label: { rows: [{ label: '款式', value: '遮光布' }], short_code: 'S-0001' },
}

/** 主屏（报工卡 + 成品入库卡 + 页头入口栏 = 两个硬件入口都在这一屏上）。 */
const mainScreen = (terminal, extra = {}) => visible(renderPage({
  ...loggedIn(ALL_PAGES),
  terminal,
  mode: 'main',
  view: RESOLVED_VIEW,
  finishedInbound: FINISHED,
  ...extra,
}))

/** 屏幕上**真的**出现了哪些硬件入口（按元素 id 判，不看注释、不看源码）。 */
const renderedIds = (html) => HARDWARE_IDS.filter((id) => visible(html).includes(`id="${id}"`))

const read = (p) => readFileSync(new URL(`../src/${p}`, import.meta.url), 'utf8')

/** 去掉注释后的代码（注释里提到 `window.migaoTerminal` 不算"读了它"）。 */
const stripComments = (src) => src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')

// ════════════════════════════════════════════════════════════════════════════════
// 判据 ①：能力缺省即隐藏（fail-closed）
// ════════════════════════════════════════════════════════════════════════════════

test('🔴 判据 ① 能力缺省即隐藏：桥缺失 / 缺键 / 非对象 / 空串 / 非字符串 ⇒ 两个硬件入口都不渲染', () => {
  // 每一种输入都是"壳没接上 / 接上了但没这条能力"的真实形态。**一律当没有能力。**
  const MALFORMED = [
    ['整块桥缺失（浏览器直接打开 /w/）', undefined],
    ['桥是 null', null],
    ['桥是空对象（壳注入了但不带能力表）', {}],
    ['桥是字符串（注入坏了）', 'migaoTerminal'],
    ['桥是数组', []],
    ['capabilities 缺失', { capabilities: undefined }],
    ['capabilities 是 null', { capabilities: null }],
    ['capabilities 是字符串', { capabilities: 'cut.link=serial:COM3' }],
    ['capabilities 是数组', { capabilities: [CAP_CUT_LINK] }],
    ['capabilities 是空对象', { capabilities: {} }],
    ['键值是空串 / 空白串', { capabilities: { [CAP_CUT_LINK]: '', [CAP_PRINT_LABEL]: '   ' } }],
    ['键值不是字符串（true / 1 / 对象）', { capabilities: { [CAP_CUT_LINK]: true, [CAP_PRINT_LABEL]: 1 } }],
    ['键值带了引号但内容为空白', { capabilities: { [CAP_CUT_LINK]: 'serial:COM3'.replace('serial:COM3', '') } }],
  ]
  const bad = []
  for (const [name, terminal] of MALFORMED) {
    const got = terminalCapabilities({ terminal })
    if (got.cut !== null || got.print !== null) bad.push(`${name}：能力读取器给了 ${JSON.stringify(got)}（缺省必须全空）`)
    const shown = renderedIds(mainScreen(terminal))
    if (shown.length > 0) bad.push(`${name}：屏上仍渲染了 ${shown.join(' / ')}（缺省必须一个都不出）`)
  }
  assert.deepEqual(bad, [], '缺省 fail-closed 破了：没有能力凭据却渲染出了硬件入口')

  // 🔴 对照（防空断言）：同一份 state 注入**真**能力凭据 ⇒ 入口必须出现。
  //    少了这两行，"永远不渲染"这种错实现也能把上面判绿。
  assert.deepEqual(renderedIds(mainScreen(ALL_IN_ONE)), ['wh5-machine-entry'],
    '对照失败：真给了 cut.link 却没渲染裁高计算入口（那说明本判据只是在断言"什么都没有"）')
  assert.deepEqual(renderedIds(mainScreen(HANDHELD)), ['wh5-fi-print'],
    '对照失败：真给了 print.label 却没渲染打印入库标签（同上）')
})

// ════════════════════════════════════════════════════════════════════════════════
// 判据 ②：同一 worker_pages 两台设备菜单不同（差异只来自 capabilities）
// ════════════════════════════════════════════════════════════════════════════════

test('🔴 判据 ② 同一份 worker_pages，两台设备菜单不同（差异只来自 capabilities）', () => {
  const handset = loggedIn(ALL_PAGES)
  const allInOne = loggedIn(ALL_PAGES)
  // 前两轴逐字相同（同一工人、同一份 pages、同一租户开关）—— 唯一变量就是本机能力
  assert.deepEqual(handset.pages, allInOne.pages, '对照组前提破了：两台设备的 worker_pages 必须完全一样')

  const handsetHtml = mainScreen(HANDHELD)
  const allInOneHtml = mainScreen(ALL_IN_ONE)

  assert.deepEqual(renderedIds(handsetHtml), ['wh5-fi-print'],
    '手持标签机：只该有「打印入库标签」，不该出现裁高计算入口（用户裁定②：手持机不需要裁高计算/下发）')
  assert.deepEqual(renderedIds(allInOneHtml), ['wh5-machine-entry'],
    '安卓一体机：只该有「裁高计算（一体机）」，不该出现打印标签（一体机没有标签机链路）')
  assert.notDeepEqual(renderedIds(handsetHtml), renderedIds(allInOneHtml),
    '两台设备的硬件入口一模一样 ⇒ 第三轴没进判定（这正是"把 capabilities 从判定里去掉"的形态）')

  // 一台设备同时具备两个能力 ⇒ 两个入口都在（第三轴是"与"，不是"二选一"）
  assert.deepEqual(renderedIds(mainScreen(BOTH)), ['wh5-machine-entry', 'wh5-fi-print'],
    '同时具备两个能力时两个入口都该出现（能力表是逐条判定，不是按设备型号分档）')

  // 同一份 pages 下，**非硬件入口不受第三轴影响**（返工记录 / 页头 / 报工卡逐字都在）
  for (const [name, html] of [['手持机', handsetHtml], ['一体机', allInOneHtml]]) {
    for (const id of ['wh5-worker-entries', 'wh5-rework-entry', 'wh5-report', 'wh5-current-worker']) {
      assert.equal(html.includes(`id="${id}"`), true, `${name}：第三轴不该动非硬件面，但 #${id} 不见了`)
    }
  }
})

// ════════════════════════════════════════════════════════════════════════════════
// 判据 ③：无硬件不阻断其它功能
// ════════════════════════════════════════════════════════════════════════════════

test('🔴 判据 ③ 无硬件不阻断其它功能：裁高机 / 标签机都缺席，报工面照旧可用（不整页禁用）', () => {
  const NO_HARDWARE = bridge({ [CAP_CUT_LINK]: null, [CAP_PRINT_LABEL]: null })

  // ① 主屏：报工卡与报工按钮照旧、且**按钮没有被禁用**（能力缺席 ≠ 整页禁用）
  const main = mainScreen(NO_HARDWARE)
  assert.deepEqual(renderedIds(main), [], '没有硬件时不该渲染任何硬件入口')
  assert.match(main, /id="wh5-report"[^>]*>\s*报\s*工\s*</, '报工按钮必须还在（无硬件不等于不能报工）')
  assert.deepEqual(
    main.match(/id="wh5-report"[^>]*disabled/g) ?? [],
    [],
    '报工按钮被禁用了 —— 用户裁定⑥「串口不存在 / 蓝牙未配对 ⇒ 其余功能仍可用，不整页禁用」',
  )
  assert.equal(main.includes('id="wh5-set"'), true, '这一件的套号/部位信息必须还在')
  assert.equal(main.includes('id="wh5-rework-entry"'), true, '返工记录入口（非硬件面）必须还在')
  assert.equal(main.includes('id="wh5-finished-inbound"'), true,
    '成品入库卡的信息面（入库单 / 仓位）与"本机能不能印"无关，仍要显示')

  // ② 扫码页（还没扫到东西）：照旧是扫码指路，不是"设备不支持"的空屏
  const scan = visible(renderPage({ ...loggedIn(ALL_PAGES), terminal: NO_HARDWARE }))
  assert.equal(scan.includes('id="wh5-scan-hint"'), true, '扫码页消失了（无硬件把整页挡掉了）')
  assert.match(scan, /扫码报工/, '扫码页的标题必须还在')
  assert.deepEqual(renderedIds(scan), [], '扫码页也不该凭空冒出硬件入口')
})

// ════════════════════════════════════════════════════════════════════════════════
// 判据 ④：出错不白屏（回归面）—— 桥整块缺失
// ════════════════════════════════════════════════════════════════════════════════

/** 极简 document 替身：只让装配层拿到 #worker-h5-root（与既有装配测试同口径，免引 jsdom）。 */
function stubDoc() {
  let html = ''
  const root = {
    get innerHTML() { return html },
    set innerHTML(v) { html = v },
  }
  return {
    visibilityState: 'visible',
    getElementById: (id) => (id === 'worker-h5-root' ? root : null),
    querySelectorAll: () => [],
    addEventListener() {},
    removeEventListener() {},
    get html() { return html },
  }
}

test('🔴 判据 ④ 桥整块缺失（浏览器直接开 /w/）⇒ 按「无任何能力」跑，既有页面一个都不消失', () => {
  const doc = stubDoc()
  // 浏览器里没有壳 ⇒ `globalThis.migaoTerminal` 就是 undefined。这里把"没传 terminal"这条路走一遍。
  const api = { sessionId: () => null, readMe: async () => ({ pages: ALL_PAGES }) }
  const app = createApp({ doc, api, location: 'https://app.migaozn.com/w/', storage: null })
  try {
    assert.equal(app.state.terminal, null, '没有壳时必须落成 null（不是 undefined / 不是"默认全开"的能力表）')
    // 首屏：装配层不自动重绘 ⇒ 走 boot 的同一条动作（`{type:'worker', worker:null}` = 未登录）
    app.dispatch({ type: 'worker', worker: null })
    assert.match(doc.html, /id="wh5-login"/, '首屏登录卡没了 = 白屏（浏览器直接打开就已经废了）')
    assert.match(doc.html, /工人报工/, '登录卡标题必须还在')

    // 登录 + 拿到页面集之后：报工面照旧，硬件入口一个都不出
    app.dispatch({ type: 'worker', worker: WORKER })
    app.dispatch({ type: 'pages', pages: ALL_PAGES })
    assert.equal(doc.html.includes('id="wh5-scan-hint"'), true, '登录后的扫码页消失了（回归面）')
    assert.equal(doc.html.includes('id="wh5-current-worker"'), true, '页头「当前工人」消失了（回归面）')
    assert.deepEqual(renderedIds(doc.html), [], '没有壳却渲染出硬件入口（fail-closed 破了）')
    assert.deepEqual(
      doc.html.match(/wh5-error"[^>]*>[^<]*/g) ?? [],
      [],
      '装配期不该往错误面写东西（缺桥不是工人的错，也不是"出错")',
    )
  } finally {
    app.destroy()
  }
})

// ════════════════════════════════════════════════════════════════════════════════
// 类级元守卫（让同类进不来）
// ════════════════════════════════════════════════════════════════════════════════

test('🔴 元守卫 a：桥只在装配层碰一次（纯函数层不读全局 ⇒ 不许出现第二份能力真值）', () => {
  const files = readdirSync(new URL('../src/', import.meta.url), { recursive: true })
    .filter((f) => typeof f === 'string' && f.endsWith('.mjs'))
  const bad = []
  const hits = []
  for (const file of files) {
    const code = stripComments(read(file))
    const n = (code.match(/migaoTerminal/g) ?? []).length
    if (n === 0) continue
    hits.push(`${file}×${n}`)
    if (file !== 'app.mjs') bad.push(`${file} 直接读了 window.migaoTerminal（×${n}）`)
  }
  assert.deepEqual(bad, [], '本机能力的唯一读取处是装配层 app.mjs；其它文件（含 render.mjs）只能读 state.terminal')
  assert.deepEqual(
    hits,
    ['app.mjs×1'],
    '装配层必须恰好读一次桥（多读一处 = 第二份能力真值；少读 = 第三轴根本没接上）',
  )
  // 反向钉住：读取器本身**不碰**任何全局（纯函数才能被 node --test 直接钉住）
  const reader = stripComments(read('render.mjs'))
  assert.deepEqual(
    ['window.', 'globalThis', 'document.'].filter((g) => reader.includes(g)),
    [],
    'render.mjs 是纯函数层：它不该读 window / globalThis / document（桥由装配层送进来）',
  )
})

test('🔴 元守卫 b：能力读取器的形状 = 台账（未登记即红，两个方向都判）', () => {
  const allOn = { capabilities: caps({ [CAP_CUT_LINK]: 'serial:COM3', [CAP_PRINT_LABEL]: 'ble' }) }
  const got = terminalCapabilities({ terminal: allOn })
  assert.deepEqual(
    Object.keys(got).sort(),
    CAPABILITY_LEDGER.map((r) => r.axis).sort(),
    '能力读取器暴露的轴与台账不一致：新增能力必须登记（否则它既不会被判据覆盖，也说不清该隐哪个入口）',
  )
  const values = CAPABILITY_LEDGER.map((r) => [r.axis, got[r.axis]])
  assert.deepEqual(
    values,
    [['cut', 'serial:COM3'], ['print', 'ble']],
    '读取器必须逐字保留能力凭据（`serial:COM3` / `ble`）—— 布尔化会丢掉"连哪台机器"这件事',
  )
  // 台账自身不许有重复条目（重复 = 两套口径，与"脚本改了但台账没改"同族）
  assert.equal(new Set(CAPABILITY_LEDGER.map((r) => r.axis)).size, CAPABILITY_LEDGER.length, '台账有重复的轴')
  assert.equal(new Set(CAPABILITY_LEDGER.map((r) => r.key)).size, CAPABILITY_LEDGER.length, '台账有重复的能力键')
})

test('🔴 元守卫 c：台账每一条都要双向判（在场 ⇒ 出现；缺席 ⇒ 消失，且不影响别条）', () => {
  const bad = []
  for (const row of CAPABILITY_LEDGER) {
    const present = mainScreen(bridge({ [row.key]: row.key === CAP_CUT_LINK ? 'serial:COM3' : 'ble' }))
    if (!present.includes(`id="${row.entry}"`)) bad.push(`${row.key} 在场时没渲染 #${row.entry}`)

    // 只把这一条置空（别条照旧在场）⇒ 只该消失它自己
    const others = CAPABILITY_LEDGER.filter((r) => r.axis !== row.axis)
    const cleared = mainScreen(bridge({
      [CAP_CUT_LINK]: 'serial:COM3',
      [CAP_PRINT_LABEL]: 'ble',
      [row.key]: null,
    }))
    if (cleared.includes(`id="${row.entry}"`)) bad.push(`${row.key} 缺席时仍渲染 #${row.entry}（fail-closed 破了）`)
    for (const other of others) {
      if (!cleared.includes(`id="${other.entry}"`)) {
        bad.push(`清空 ${row.key} 把别条 #${other.entry} 也弄没了（三条轴必须逐条判定）`)
      }
    }
  }
  assert.deepEqual(bad, [], '台账里有条目的双向判据没落地')
})
