// case_ids: MC-192
//
// 工人端 `/w/` 的**第三轴：本机能力**（`window.migaoTerminal.capabilities`）—— issue #8609 B 包。
//
// 用户的裁定（2026-11-04 逐字三条，同一次裁定）：
//   「安卓一体机和 window 一体机功能完全一样，也有串口和下发动作」/「手持标签机不需要裁高计算/下发」/
//   「接受，我也希望一个包搞定」
// ⇒ **一份业务面 + 两个薄壳 + 一个 apk 覆盖两种安卓设备**：菜单 = `users.worker_pages`
//    ∩ 租户页面开关 ∩ **本机 capabilities**（三轴与）。前两轴已在 `effectivePages`（本文件**不**重造），
//    第三轴由本文件钉住：`cut.link` ⇒ 裁高计算入口；`print.label` ⇒ 打印入库标签。
//
// 🔴 **桥是三态**（压成两态会出两个方向的错，见 `terminalCapabilities`）：
//    ① `absent`  —— `window.migaoTerminal` 整块缺失（普通浏览器 / 没有壳）⇒ **两条都隐藏**（真没有串口/蓝牙）；
//    ② `unknown` —— **桥在场但没有 `capabilities`**（线上 1.0.2 旧壳，桥只有 `post`）⇒ **两条都不隐藏**
//       （迁移期口径「未知 ≠ 没有」；否则一体机的裁高入口 / 手持机的打印按钮会在真实工人手上消失）；
//    ③ `present` —— `capabilities` 是对象（A 包起）⇒ 逐键判定，缺键 / 空串 / 非字符串 = 没有该能力。
//
// 判据（每条都能红；红证 = 注入后当场红、恢复后绿，读数见 PR body）：
//   ① **无壳 ⇒ 隐藏**：桥整块缺失 / 非对象 ⇒ 两条入口都不渲染，而报工面照旧（不白屏）。
//   ①′ **旧壳 ⇒ 不隐藏（迁移期）**：桥在、`capabilities` 缺失 / 非对象 ⇒ 两条**都在**。
//      红证：把 `unknown` 并入 `absent` ⇒ 本判据当场红（这是本轮最重要的一条 —— 线上就是老壳）。
//   ①″ **有能力表 ⇒ fail-closed 主体**：缺键 / 空串 / 空白 / 布尔 / 数字 / 对象 ⇒ 该条隐藏；只给一条 ⇒ 只隐藏它自己。
//   ② **同一 `worker_pages` 两台设备菜单不同**（差异只来自 capabilities），非硬件面逐字不变。
//   ③ **无硬件不阻断其它功能**：两条都缺席 ⇒ 报工按钮在且未禁用、套号部位在、返工入口在、成品入库信息面在。
//   ④ **出错不白屏（回归面）**：桥整块缺失（浏览器直接开 `/w/`）⇒ 装配层落「无桥」，既有页面一个不消失。
//
// 类级元守卫（`migao-dev-flow` §23 / 铁律 8）：
//   a）桥的**代码级**引用只许在装配层且恰好 1 处；`render.mjs` 是纯函数层（不读全局）；两个硬件入口**只能**
//      经 `capabilityShown` 判定（旁路判定 ⇒ 红）；第三轴**只读** —— 页面侧出现 `capabilities` 的
//      **赋值**路径 ⇒ 红（壳注入、页面只读：为了显示某入口反过来写能力 = 页面替壳做决定，能力真值变两份）。
//   b）**未登记即红**：读取器暴露的能力轴 ⇄ 台账逐键相等（两个方向都判），且三态常量必须自洽。
//   c）**登记了就必须双向判**：台账每一条在 absent / unknown / present-缺键 / present-在场 四种状态下各判一次。
import { readdirSync, readFileSync } from 'node:fs'
import test from 'node:test'
import assert from 'node:assert/strict'

import { createApp } from '../src/app.mjs'
import {
  CAP_CUT_LINK,
  CAP_PRINT_LABEL,
  CAP_STATE_ABSENT,
  CAP_STATE_PRESENT,
  CAP_STATE_UNKNOWN,
  capabilityShown,
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
 */
const CAPABILITY_LEDGER = [
  { key: CAP_CUT_LINK, axis: 'cut', entry: 'wh5-machine-entry' },
  { key: CAP_PRINT_LABEL, axis: 'print', entry: 'wh5-fi-print' },
]

const HARDWARE_IDS = CAPABILITY_LEDGER.map((r) => r.entry)

/** 线上 1.0.2 旧壳注入的桥**真实形态**（证据见 `frontend/bmini-app/tests/inbound-print-channel.test.ts`）。 */
const OLD_SHELL = { post: () => {} }

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
// 判据 ①：无壳（absent）⇒ 两条都隐藏
// ════════════════════════════════════════════════════════════════════════════════

test('🔴 判据 ① 无壳（桥整块缺失 / 非对象）⇒ 两条硬件入口都隐藏：真没有串口与蓝牙', () => {
  const ABSENT = [
    ['整块桥缺失（浏览器直接打开 /w/）', undefined],
    ['桥是 null', null],
    ['桥是字符串（注入坏了）', 'migaoTerminal'],
    ['桥是数组', []],
    ['桥是数字', 42],
    ['桥是布尔', true],
  ]
  const bad = []
  for (const [name, terminal] of ABSENT) {
    const got = terminalCapabilities({ terminal })
    if (got.state !== CAP_STATE_ABSENT) bad.push(`${name}：三态应为 absent，实得 ${JSON.stringify(got.state)}`)
    if (capabilityShown(got, 'cut') || capabilityShown(got, 'print')) bad.push(`${name}：absent 却仍要渲染硬件入口`)
    const shown = renderedIds(mainScreen(terminal))
    if (shown.length > 0) bad.push(`${name}：屏上仍渲染了 ${shown.join(' / ')}（无壳必须一条都不出）`)
  }
  assert.deepEqual(bad, [], '无壳分支破了：没有串口/蓝牙的机器上冒出了硬件入口')

  // 🔴 对照（防空断言）：同一份 state 注入**真**能力凭据 ⇒ 入口必须出现。
  assert.deepEqual(renderedIds(mainScreen(ALL_IN_ONE)), ['wh5-machine-entry'], '对照失败：给了 cut.link 却不渲染裁高入口')
  assert.deepEqual(renderedIds(mainScreen(HANDHELD)), ['wh5-fi-print'], '对照失败：给了 print.label 却不渲染打印按钮')
})

// ════════════════════════════════════════════════════════════════════════════════
// 判据 ①′：旧壳（unknown）⇒ 两条都不隐藏（迁移期「未知 ≠ 没有」）
// ════════════════════════════════════════════════════════════════════════════════

test('🔴 判据 ①′ 旧壳（桥在、没有能力表）⇒ 两条入口**都在**：线上 1.0.2 不会退化', () => {
  // 线上 1.0.2 的桥 = `{ post }`（终端打印桥），**没有 capabilities** ⇒ 能力未知。
  // 「未知」不等于「没有」：这时隐藏入口 = 在真实工人手上把功能拿掉（用户可见退化）。
  const UNKNOWN = [
    ['线上旧壳的真实形态（只有 post）', OLD_SHELL],
    ['空对象（壳注入了但不带能力表）', {}],
    ['capabilities: undefined', { capabilities: undefined }],
    ['capabilities: null', { capabilities: null }],
    ['capabilities 是字符串（坏形态）', { capabilities: 'cut.link=serial:COM3' }],
    ['capabilities 是数组（坏形态）', { capabilities: [CAP_CUT_LINK] }],
    ['capabilities 是数字（坏形态）', { capabilities: 1 }],
  ]
  const bad = []
  for (const [name, terminal] of UNKNOWN) {
    const got = terminalCapabilities({ terminal })
    if (got.state !== CAP_STATE_UNKNOWN) bad.push(`${name}：三态应为 unknown，实得 ${JSON.stringify(got.state)}`)
    if (!capabilityShown(got, 'cut') || !capabilityShown(got, 'print')) bad.push(`${name}：unknown 却隐藏了入口`)
    const shown = renderedIds(mainScreen(terminal))
    if (shown.length !== HARDWARE_IDS.length) bad.push(`${name}：屏上只有 ${shown.join(' / ') || '（无）'}，迁移期应两条都在`)
  }
  assert.deepEqual(bad, [], '迁移期口径破了：旧壳（桥在无能力表）会把线上入口弄没')

  // 🔴 对照（防"unknown = 恒显示"）：**有能力表**但两条都缺 ⇒ 两条都隐藏。
  //    少了这一行，"unknown 分支写成了恒 true" 也会把上面判绿。
  assert.deepEqual(renderedIds(mainScreen(bridge())), [], '对照失败：present 且两条都缺时仍渲染了入口（那 unknown 判据就是空的）')

  // 三态必须**真的分开**：同一个 state 形状，桥在不在决定 absent / unknown —— 两条不许合并。
  const states = [
    ['没有桥', undefined, CAP_STATE_ABSENT],
    ['旧壳', OLD_SHELL, CAP_STATE_UNKNOWN],
    ['新壳', ALL_IN_ONE, CAP_STATE_PRESENT],
  ].map(([name, terminal, want]) => [name, terminalCapabilities({ terminal }).state, want])
  assert.deepEqual(
    states.filter(([, got, want]) => got !== want),
    [],
    '三态常量与桥形态的对应关系不对（absent / unknown / present 不许互相吞并）',
  )
})

// ════════════════════════════════════════════════════════════════════════════════
// 判据 ①″：有能力表（present）⇒ 缺键 / 空串 / 非字符串一律隐藏
// ════════════════════════════════════════════════════════════════════════════════

test('🔴 判据 ①″ 有能力表 ⇒ fail-closed 主体：缺键 / 空串 / 空白 / 布尔 / 数字 / 对象一律当没有', () => {
  const MALFORMED_CAPS = [
    ['能力表是空对象（一个键都没有）', {}],
    ['键值 = null', { [CAP_CUT_LINK]: null, [CAP_PRINT_LABEL]: null }],
    ['键值 = 空串 / 空白串', { [CAP_CUT_LINK]: '', [CAP_PRINT_LABEL]: '   ' }],
    ['键值不是字符串（true / 1）', { [CAP_CUT_LINK]: true, [CAP_PRINT_LABEL]: 1 }],
    ['键值是对象 / 数组（坏形态）', { [CAP_CUT_LINK]: {}, [CAP_PRINT_LABEL]: [] }],
    ['键名拼错（大小写 / 下划线）', { 'cut.link ': 'serial:COM3', print_label: 'ble' }],
  ]
  const bad = []
  for (const [name, table] of MALFORMED_CAPS) {
    const terminal = { capabilities: table }
    const got = terminalCapabilities({ terminal })
    if (got.state !== CAP_STATE_PRESENT) bad.push(`${name}：三态应为 present，实得 ${JSON.stringify(got.state)}`)
    if (got.cut !== null || got.print !== null) bad.push(`${name}：读取器给了 ${JSON.stringify(got)}（缺省必须全空）`)
    const shown = renderedIds(mainScreen(terminal))
    if (shown.length > 0) bad.push(`${name}：屏上仍渲染了 ${shown.join(' / ')}（缺省必须一个都不出）`)
  }
  assert.deepEqual(bad, [], 'present 分支破了：没有能力凭据却渲染出了硬件入口')

  // 只给一条 ⇒ **只隐藏它自己**（防"一条缺失就把两条都藏了"的一刀切）
  const onlyCut = mainScreen({ capabilities: caps({ [CAP_CUT_LINK]: 'tcp:192.168.2.9:502' }) })
  assert.deepEqual(renderedIds(onlyCut), ['wh5-machine-entry'], '只给了 cut.link 时不该冒出打印按钮、也不该把裁高入口一起藏掉')
  const onlyPrint = mainScreen({ capabilities: caps({ [CAP_PRINT_LABEL]: 'ble' }) })
  assert.deepEqual(renderedIds(onlyPrint), ['wh5-fi-print'], '只给了 print.label 时同理（逐键判定，不是一刀切）')
})

// ════════════════════════════════════════════════════════════════════════════════
// 判据 ②：同一 worker_pages 两台设备菜单不同（差异只来自 capabilities）
// ════════════════════════════════════════════════════════════════════════════════

test('🔴 判据 ② 同一份 worker_pages，两台设备菜单不同（差异只来自 capabilities）', () => {
  const handset = loggedIn(ALL_PAGES)
  const allInOne = loggedIn(ALL_PAGES)
  assert.deepEqual(handset.pages, allInOne.pages, '对照组前提破了：两台设备的 worker_pages 必须完全一样')

  const handsetHtml = mainScreen(HANDHELD)
  const allInOneHtml = mainScreen(ALL_IN_ONE)

  assert.deepEqual(renderedIds(handsetHtml), ['wh5-fi-print'],
    '手持标签机：只该有「打印入库标签」，不该出现裁高计算入口（用户裁定：手持机不需要裁高计算/下发）')
  assert.deepEqual(renderedIds(allInOneHtml), ['wh5-machine-entry'],
    '安卓一体机：只该有「裁高计算」，不该出现打印标签（一体机没有标签机链路）')
  assert.notDeepEqual(renderedIds(handsetHtml), renderedIds(allInOneHtml),
    '两台设备的硬件入口一模一样 ⇒ 第三轴没进判定（这正是"把 capabilities 从判定里去掉"的形态）')

  // 一台设备同时具备两个能力 ⇒ 两个入口都在（逐条判定，不是按设备型号分档）
  assert.deepEqual(renderedIds(mainScreen(BOTH)), ['wh5-machine-entry', 'wh5-fi-print'],
    '同时具备两个能力时两个入口都该出现')

  // 同一份 pages 下，**非硬件入口不受第三轴影响**
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

  const main = mainScreen(NO_HARDWARE)
  assert.deepEqual(renderedIds(main), [], '没有硬件时不该渲染任何硬件入口')
  assert.match(main, /id="wh5-report"[^>]*>\s*报\s*工\s*</, '报工按钮必须还在（无硬件不等于不能报工）')
  assert.deepEqual(
    main.match(/id="wh5-report"[^>]*disabled/g) ?? [],
    [],
    '报工按钮被禁用了 —— 「串口不存在 / 蓝牙未配对 ⇒ 其余功能仍可用，不整页禁用」',
  )
  assert.equal(main.includes('id="wh5-set"'), true, '这一件的套号/部位信息必须还在')
  assert.equal(main.includes('id="wh5-rework-entry"'), true, '返工记录入口（非硬件面）必须还在')
  assert.equal(main.includes('id="wh5-finished-inbound"'), true,
    '成品入库卡的信息面（入库单 / 仓位）与"本机能不能印"无关，仍要显示')

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

test('🔴 判据 ④ 桥整块缺失（浏览器直接开 /w/）⇒ 按「无壳」跑，既有页面一个都不消失', () => {
  const doc = stubDoc()
  const api = { sessionId: () => null, readMe: async () => ({ pages: ALL_PAGES }) }
  const app = createApp({ doc, api, location: 'https://app.migaozn.com/w/', storage: null })
  try {
    assert.equal(app.state.terminal, null, '没有壳时必须落成 null（不是 undefined / 不是"默认全开"的能力表）')
    app.dispatch({ type: 'worker', worker: null })
    assert.match(doc.html, /id="wh5-login"/, '首屏登录卡没了 = 白屏（浏览器直接打开就已经废了）')
    assert.match(doc.html, /工人报工/, '登录卡标题必须还在')

    app.dispatch({ type: 'worker', worker: WORKER })
    app.dispatch({ type: 'pages', pages: ALL_PAGES })
    assert.equal(doc.html.includes('id="wh5-scan-hint"'), true, '登录后的扫码页消失了（回归面）')
    assert.equal(doc.html.includes('id="wh5-current-worker"'), true, '页头「当前工人」消失了（回归面）')
    assert.deepEqual(renderedIds(doc.html), [], '没有壳却渲染出硬件入口（fail-closed 破了）')
    assert.deepEqual(
      doc.html.match(/wh5-error"[^>]*>[^<]*/g) ?? [],
      [],
      '装配期不该往错误面写东西（缺桥不是工人的错）',
    )
  } finally {
    app.destroy()
  }
})

test('🔴 判据 ④′ 旧壳（1.0.2 形态的桥）在同一装配层下 ⇒ 两条入口都在（迁移期不退化）', () => {
  const doc = stubDoc()
  const api = { sessionId: () => null }
  const app = createApp({ doc, api, location: 'https://app.migaozn.com/w/', storage: null, terminal: OLD_SHELL })
  try {
    app.dispatch({ type: 'worker', worker: WORKER })
    app.dispatch({ type: 'pages', pages: ALL_PAGES })
    assert.deepEqual(renderedIds(doc.html), ['wh5-machine-entry'],
      '旧壳（桥在无能力表）下装配层应判 unknown：裁高入口仍在（打印按钮要等扫到入库件才出现，这一屏没有）')
  } finally {
    app.destroy()
  }
})

// ════════════════════════════════════════════════════════════════════════════════
// 类级元守卫（让同类进不来）
// ════════════════════════════════════════════════════════════════════════════════

test('🔴 元守卫 a：桥只在装配层碰一次；两个硬件入口只能经 capabilityShown 判定（旁路 ⇒ 红）', () => {
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
  assert.deepEqual(hits, ['app.mjs×1'], '装配层必须恰好读一次桥（多读一处 = 第二份能力真值；少读 = 第三轴根本没接上）')

  // 渲染层：两个硬件入口**必须**走 `capabilityShown`（各写一份判定 = 两个入口可以各自漂移）
  const render = stripComments(read('render.mjs'))
  assert.deepEqual(
    ["capabilityShown(caps, 'cut')", "capabilityShown(terminalCapabilities(state), 'print')"].filter((s) => !render.includes(s)),
    [],
    '两个硬件入口没有都走 capabilityShown（旁路判定会让 absent/unknown/present 三态在某一处失效）',
  )
  assert.deepEqual(
    ['window.', 'globalThis', 'document.'].filter((g) => render.includes(g)),
    [],
    'render.mjs 是纯函数层：它不该读 window / globalThis / document（桥由装配层送进来）',
  )

  // 🔴 第三轴**只读**（issue #8609 边界的「壳注入、页面只读」）：页面侧不得出现对 capabilities 的
  //    **赋值**路径 —— 为了显示某个入口反过来写能力，就是页面替壳做决定（能力真值从此有两份，
  //    而壳再也不会纠正它）。四种写法都收：直接赋值 / 键赋值 / `Object.assign` / `defineProperty`。
  const WRITE_CAPS = /capabilities(?:\s*\[[^\]]{0,40}\]|\s*\.[\w$]+)?\s*=(?!=)|\bObject\.assign\s*\([^)]{0,80}capabilities|\bdefineProperty\s*\([^)]{0,80}capabilities/g
  const capsWrites = []
  const capsReaders = []
  for (const file of files) {
    const code = stripComments(read(file))
    for (const hit of code.match(WRITE_CAPS) ?? []) capsWrites.push(`${file}: ${hit}`)
    if (code.includes('.capabilities')) capsReaders.push(file)
  }
  assert.deepEqual(capsWrites, [], '页面侧出现了对 capabilities 的赋值路径：第三轴是壳注入、页面只读（写回 = 页面替壳做决定）')
  // 扫描面非空自证：**读取点本身**必须被扫到（`src/` 空集 / 读取写法被改名 ⇒ 上面那条会恒绿 = 空判据）。
  assert.deepEqual(capsReaders, ['render.mjs'], '能力读取点必须落在 render.mjs（扫不到任何读取点 = 这条判据自己就是空的）')
})

test('🔴 元守卫 b：能力读取器的形状 = 台账（未登记即红），三态常量自洽', () => {
  const allOn = { capabilities: caps({ [CAP_CUT_LINK]: 'serial:COM3', [CAP_PRINT_LABEL]: 'ble' }) }
  const got = terminalCapabilities({ terminal: allOn })
  assert.deepEqual(
    Object.keys(got).filter((k) => k !== 'state').sort(),
    CAPABILITY_LEDGER.map((r) => r.axis).sort(),
    '能力读取器暴露的轴与台账不一致：新增能力必须登记（否则它既不会被判据覆盖，也说不清该隐哪个入口）',
  )
  assert.deepEqual(
    CAPABILITY_LEDGER.map((r) => [r.axis, got[r.axis]]),
    [['cut', 'serial:COM3'], ['print', 'ble']],
    '读取器必须逐字保留能力凭据（`serial:COM3` / `ble`）—— 布尔化会丢掉"连哪台机器"这件事',
  )
  // 三态常量是**三个不同的值**（压成两态 = 迁移期口径没地方放）
  assert.deepEqual(
    [new Set([CAP_STATE_ABSENT, CAP_STATE_UNKNOWN, CAP_STATE_PRESENT]).size],
    [3],
    '三态常量必须互不相同',
  )
  // 台账自身不许重复
  assert.equal(new Set(CAPABILITY_LEDGER.map((r) => r.axis)).size, CAPABILITY_LEDGER.length, '台账有重复的轴')
  assert.equal(new Set(CAPABILITY_LEDGER.map((r) => r.key)).size, CAPABILITY_LEDGER.length, '台账有重复的能力键')
})

test('🔴 元守卫 c：台账每条要四态双向判（absent / unknown / present 缺键 / present 在场）', () => {
  const bad = []
  const states = [
    ['absent（无壳）', undefined],
    ['unknown（旧壳）', OLD_SHELL],
  ]
  for (const [label, terminal] of states) {
    const shown = renderedIds(mainScreen(terminal))
    const want = label.startsWith('absent') ? [] : HARDWARE_IDS
    if (shown.join() !== want.join()) bad.push(`${label}：入口集合 ${shown.join('/') || '（无）'} ≠ 期望 ${want.join('/') || '（无）'}`)
  }
  for (const row of CAPABILITY_LEDGER) {
    const value = row.key === CAP_CUT_LINK ? 'serial:COM3' : 'ble'
    const present = mainScreen(bridge({ [row.key]: value }))
    if (!present.includes(`id="${row.entry}"`)) bad.push(`${row.key} 在场时没渲染 #${row.entry}`)

    const cleared = mainScreen(bridge({
      [CAP_CUT_LINK]: 'serial:COM3',
      [CAP_PRINT_LABEL]: 'ble',
      [row.key]: null,
    }))
    if (cleared.includes(`id="${row.entry}"`)) bad.push(`${row.key} 缺席时仍渲染 #${row.entry}（fail-closed 破了）`)
    for (const other of CAPABILITY_LEDGER.filter((r) => r.axis !== row.axis)) {
      if (!cleared.includes(`id="${other.entry}"`)) bad.push(`清空 ${row.key} 把别条 #${other.entry} 也弄没了（逐条判定）`)
    }
  }
  assert.deepEqual(bad, [], '台账里有条目的四态判据没落地')
})
