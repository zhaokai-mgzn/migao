// case_ids: MC-192, MC-234
//
// 壳差异验收矩阵（issue #8609 **C 包**）—— 把「**两端同一批用例**」与「**壳差异**」从**注释**变成**判据**。
//
// 用户裁定（2026-11-04 逐字三条，同一次裁定）：
//   「安卓一体机和 window 一体机功能完全一样，也有串口和下发动作」/「手持标签机不需要裁高计算/下发」/
//   「接受，我也希望一个包搞定」
// ⇒ 一份业务面 + 两个薄壳 + 一个 apk 覆盖两种安卓设备。本文件**不重造** B 包的判据面
//   （三态 / fail-closed / 元守卫 a/b/c 在 `worker-h5-8609-capabilities.test.mjs`，逐字保留），
//   只钉 B 包没有机械化的那一层（页面面 × 壳差异 × 两端同一批）：
//
//   ⑤ **设备档案矩阵**：五个档案（windows / android 一体机、手持标签机、线上旧壳、无壳）×
//      **同一批页面面**（登录 / 扫码 / 选套 / 报工-工序已定 / 报工-工序未确定）逐项断言；
//      去硬件入口 + 归一能力凭据后，五档渲染**逐字相同** —— 差异**只允许**来自 capabilities。
//   ②′ **两端同一批用例**：Windows 一体机 与 安卓一体机 capabilities 等价 ⇒ 渲染**逐字相同**
//      （唯一允许差异 = 能力凭据字符串本身：`serial:COM3` ⇄ `serial:/dev/ttyS1`）。
//      红证 = 把设备类型当成菜单判据（读 `update.channel` 分叉）⇒ 两台不同 ⇒ 当场红。
//   ⑥ **负向**：`scan.hid` / `scan.camera` / `update.channel` 在 `/w/` 上**没有任何 UI 面** ——
//      取值任意（在场 / 缺省 / 怪形态）⇒ 五个页面面渲染**逐字不变**。红证 = 给其中一键加一条
//      UI 分支 ⇒ 当场红。⚠️ 这三键**有意不进台账**（读了不用 = 假轴）；若某天确需 UI 面，
//      必须**另行裁定**（会改 B 包判据面与台账契约），本判据红 = 停手信号，不是「放宽一下」。
//   ⑦ **失败形态矩阵**：串口在/不在 × 蓝牙在/不在 × 摄像头在/不在（2³）逐组合断言；
//      `unknown`（旧壳「未知 ≠ 没有」）与 `absent`（无壳）语义保持不变（B 包已定，本包不改）。
//   元守卫 d：矩阵自身不是空表 —— 档位覆盖三种桥态、2³ 覆盖全部 8 组、硬件入口清单与
//      B 包台账 / `render.mjs` 常量三方同源、三条无 UI 面的键不在台账、矩阵文档在册。
//
// 🔴 本包只做**页面面与夹具**：真实壳能力桥（串口下发 / 单 apk 打包 / USB 权限）属 A 包
//    （`zhaokai-mgzn/migao-terminal`）⇒ 本文件**不伪造**这些可测性，边界与重启条件见
//    `docs/testing/terminal-shell-capability-matrix.md`。
import { readFileSync } from 'node:fs'
import test from 'node:test'
import assert from 'node:assert/strict'

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

const WORKER = { workerName: '张师傅', workerNo: 'W-001', idleMinutes: 43200 }

/** 全开页面集（第一轴固定为「全开」—— 本文件判的是第三轴：本机能力，不是页面权限）。 */
const ALL_PAGES = [PAGE_REPORT, PAGE_CUT_CALC, PAGE_REWORK, PAGE_INSPECT, 'piecework', 'to_ship', 'order', 'shipment', 'stock', 'inbound', 'reprint']

/** 已登录 + 指定页面集（第一轴直接落在 state 上：本文件只测渲染，不走装配层）。 */
const loggedIn = (extra = {}) => ({ ...initialState(), worker: WORKER, mode: 'scan', pages: ALL_PAGES, ...extra })

/** 去 HTML 注释后的可见文本（注释里的锚点不是入口，与既有 pages 判据同口径）。 */
const visible = (html) => html.replace(/<!--[\s\S]*?-->/g, '')

// ── 能力凭据（**两端唯一允许的差异**）──────────────────────────────────────────────
// Windows 一体机 = 板载/适配器串口 `serial:COM3`；安卓一体机 = 板载串口 `serial:/dev/ttyS1`
// （终端仓 #59 实装口径；判据 MC-234 已钉「取值不是白名单」）。
const CUT_WINDOWS = 'serial:COM3'
const CUT_ANDROID = 'serial:/dev/ttyS1'

/** 线上 1.0.2 旧壳注入的桥**真实形态**（只有 `post`，没有能力表 ⇒ 三态里的 `unknown`）。 */
const OLD_SHELL = { post: () => {} }

/** 能力表（**完整五键**，取值照 issue #8609 的能力表）。 */
const caps = (over = {}) => ({
  'scan.hid': true,
  'scan.camera': true,
  [CAP_CUT_LINK]: null,
  [CAP_PRINT_LABEL]: null,
  'update.channel': 'apk',
  ...over,
})

/**
 * **设备档案**（issue #8609「壳差异」的判据形态）：同一批页面面跑遍每一档。
 *
 * ⚠️ 期望入口 `entries` **不许**是「按档名硬编码的业务真相」—— 元守卫 d 会按台账逐档复算，
 * 档位期望与能力判定对不上 ⇒ 红（否则矩阵会变成第二份业务真值，壳一改就漂移）。
 */
const PROFILES = [
  {
    id: 'windows-all-in-one',
    label: 'Windows 一体机（串口 COM3 + 摄像头）',
    bridge: { capabilities: caps({ [CAP_CUT_LINK]: CUT_WINDOWS, [CAP_PRINT_LABEL]: null, 'update.channel': 'exe' }) },
    expectedState: CAP_STATE_PRESENT,
    entries: ['wh5-machine-entry'],
  },
  {
    id: 'android-all-in-one',
    label: '安卓一体机（串口 /dev/ttyS1 + 摄像头，功能与 Windows 逐项一致）',
    bridge: { capabilities: caps({ [CAP_CUT_LINK]: CUT_ANDROID, [CAP_PRINT_LABEL]: null, 'update.channel': 'apk' }) },
    expectedState: CAP_STATE_PRESENT,
    entries: ['wh5-machine-entry'],
  },
  {
    id: 'handheld-label',
    label: '手持标签机（只有 print.label=ble，无裁高/下发）',
    bridge: { capabilities: caps({ [CAP_CUT_LINK]: null, [CAP_PRINT_LABEL]: 'ble' }) },
    expectedState: CAP_STATE_PRESENT,
    entries: ['wh5-fi-print'],
  },
  {
    id: 'old-shell-1.0.2',
    label: '线上旧壳 1.0.2（桥在、无能力表 = unknown：迁移期「未知 ≠ 没有」）',
    bridge: OLD_SHELL,
    expectedState: CAP_STATE_UNKNOWN,
    entries: ['wh5-machine-entry', 'wh5-fi-print'],
  },
  {
    id: 'no-shell',
    label: '无壳（普通浏览器打开 /w/：桥整块缺失 = absent）',
    bridge: undefined,
    expectedState: CAP_STATE_ABSENT,
    entries: [],
  },
]

/** 硬件入口台账（C 包视角的**页面面清单**；与 B 包台账三方同源由元守卫 d 判）。 */
const HARDWARE_ENTRIES = [
  { key: CAP_CUT_LINK, axis: 'cut', id: 'wh5-machine-entry', label: '裁高计算' },
  { key: CAP_PRINT_LABEL, axis: 'print', id: 'wh5-fi-print', label: '打印入库标签' },
]
const HARDWARE_IDS = HARDWARE_ENTRIES.map((e) => e.id)

/** 失败形态矩阵的三条轴（串口 / 蓝牙 / 摄像头 在不在 ⇒ 2³ = 8 组）。 */
const FAILURE_AXES = {
  cut: [CUT_WINDOWS, null],
  print: ['ble', null],
  camera: [true, false],
}
const FAILURE_COMBOS = []
for (const cut of FAILURE_AXES.cut) {
  for (const print of FAILURE_AXES.print) {
    for (const camera of FAILURE_AXES.camera) FAILURE_COMBOS.push({ cut, print, camera })
  }
}

// ── 页面面（**同一批用例**跑遍全部档案）─────────────────────────────────────────────
// 只挑「硬件入口可能出现」的那几种屏：登录卡（没有页头 ⇒ 一个入口都不该有）、扫码页、
// 选套/部位（`renderPage` 的第三个视图）、报工-工序已定 / 工序未确定（两张都挂成品入库卡）。
const SELECT_VIEW = {
  granularity: 'order',
  processing_order_no: 'JG-20261104-001',
  needs_selection: ['set', 'position'],
  selections: [{ set_id: 'set-1', set_no: 14, positions: [{ order_item_id: 'oi-1', position_name: '布帘' }] }],
}
const SELECTION = { setId: 'set-1', orderItemId: 'oi-1' }

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

/** 工序未确定（`operation: null`）：`mainView` 走「只给结论」分支，但页头 + 成品入库卡照旧。 */
const NO_OPERATION_VIEW = {
  granularity: 'set_position',
  set_no: 14,
  set_index: 13,
  position: { order_item_id: 'oi-1', position_name: '布帘' },
  operation: null,
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

// `surfaces` = 这一屏**能**出现哪几条硬件入口（裁高入口在页头入口栏；打印按钮只在成品入库卡里）——
// 期望入口 = 档位能力 ∩ 本屏面（两者缺一都不该渲染，见判据 ⑤）。
const FACES = [
  { id: 'login', label: '登录卡（无页头）', state: () => initialState(), anchor: 'wh5-login', surfaces: [] },
  { id: 'scan', label: '扫码页（未扫到件）', state: () => loggedIn(), anchor: 'wh5-scan-hint', surfaces: ['cut'] },
  { id: 'select', label: '选套/部位', state: () => loggedIn({ mode: 'select', view: SELECT_VIEW, selection: SELECTION }), anchor: 'wh5-legacy-hint', surfaces: ['cut'] },
  { id: 'report', label: '报工（工序已定 + 成品入库卡）', state: () => loggedIn({ mode: 'main', view: RESOLVED_VIEW, finishedInbound: FINISHED }), anchor: 'wh5-set', surfaces: ['cut', 'print'] },
  { id: 'report-no-operation', label: '报工（工序未确定 + 成品入库卡）', state: () => loggedIn({ mode: 'main', view: NO_OPERATION_VIEW, finishedInbound: FINISHED }), anchor: 'wh5-no-operation', surfaces: ['cut', 'print'] },
]

/** 某个档案在某个页面面上**该**出现哪些硬件入口（档位能力 ∩ 本屏面）。 */
const expectedEntries = (profile, face) => HARDWARE_ENTRIES
  .filter((entry) => face.surfaces.includes(entry.axis) && profile.entries.includes(entry.id))
  .map((entry) => entry.id)

/** 按档案渲染某个页面面（`terminal` = 壳注入的桥；`undefined` = 无壳）。 */
const renderFace = (face, bridge) => visible(renderPage({ ...face.state(), terminal: bridge }))

/** 屏幕上**真的**出现了哪些硬件入口（按元素 id 判，不看注释、不看源码）。 */
const renderedEntries = (html) => {
  const text = visible(html)
  return HARDWARE_IDS.filter((id) => text.includes(`id="${id}"`))
}

// ── 「差异只允许来自 capabilities」的可判形态：剥掉硬件入口块 + 归一能力凭据后逐字对照 ──
const STRIP_HARDWARE = [
  /<a[^>]*id="wh5-machine-entry"[^>]*>[^<]*<\/a>/g,
  /<div class="wh5-fl-actions">\s*<button[^>]*id="wh5-fi-print"[^>]*>[^<]*<\/button>\s*<\/div>/g,
]
const stripHardware = (html) => STRIP_HARDWARE.reduce((acc, re) => acc.replace(re, ''), html)

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
// `\\b` 边界是刻意的：`ble` 不得把 `disabled` 里的三个字母一起吃掉（元守卫 d 自证）。
const CREDENTIAL_RE = new RegExp(`\\b(?:${[CUT_WINDOWS, CUT_ANDROID, 'ble'].map(escapeRe).join('|')})\\b`, 'g')
const normalizeCredentials = (html) => html.replace(CREDENTIAL_RE, '«credential»')

// ════════════════════════════════════════════════════════════════════════════════
// 判据 ⑤：设备档案矩阵（五档 × 五个页面面）
// ════════════════════════════════════════════════════════════════════════════════

test('🔴 判据 ⑤ 设备档案矩阵：五档 × 五个页面面，入口逐项命中、非硬件面逐字相同（差异只来自 capabilities）', () => {
  const bad = []
  for (const profile of PROFILES) {
    for (const face of FACES) {
      const html = renderFace(face, profile.bridge)
      const want = expectedEntries(profile, face)
      const got = renderedEntries(html)
      if (got.join() !== want.join()) {
        bad.push(`${profile.id} / ${face.id}：入口 ${got.join('+') || '（无）'} ≠ 期望 ${want.join('+') || '（无）'}`)
      }
      if (!html.includes(`id="${face.anchor}"`)) {
        bad.push(`${profile.id} / ${face.id}：#${face.anchor} 不见了 —— 第三轴连坐了非硬件面`)
      }
      // 剥离自证（防空对照）：有入口 ⇒ 去硬件后必须真的变短；没入口 ⇒ 一个字节都不许动。
      const stripped = stripHardware(html)
      if (want.length > 0 && stripped === html) {
        bad.push(`${profile.id} / ${face.id}：剥离硬件入口时一个字节都没剥掉（剥离正则失效 ⇒ 下面的逐字对照会恒绿）`)
      }
      if (want.length === 0 && stripped !== html) {
        bad.push(`${profile.id} / ${face.id}：明明没有硬件入口，剥离却改动了 HTML（剥离范围越界）`)
      }
    }
  }
  assert.deepEqual(bad, [], '设备档案矩阵破了：入口集合与档位不符，或非硬件面被硬件能力连坐')

  // 🔴 差异**只允许**来自 capabilities：五档 × 五面，剥掉两个硬件入口块、归一一能力凭据后必须逐字相同。
  //    任何「按端/按档分叉」的渲染（设备名、端专属文案、端专属分支）都会在这里当场红。
  for (const face of FACES) {
    const forms = PROFILES.map((p) => [p.id, normalizeCredentials(stripHardware(renderFace(face, p.bridge)))])
    const [baseId, base] = forms[0]
    for (const [id, html] of forms.slice(1)) {
      assert.equal(
        html,
        base,
        `${face.id}：${id} 与 ${baseId} 的渲染不一致 —— 差异只能来自 capabilities，其余面必须逐字相同`,
      )
    }
  }
})

// ════════════════════════════════════════════════════════════════════════════════
// 判据 ②′：两端同一批用例（Windows 一体机 ⇄ 安卓一体机）
// ════════════════════════════════════════════════════════════════════════════════

test('🔴 判据 ②′ 两端同一批用例：capabilities 等价 ⇒ Windows 一体机与安卓一体机渲染逐字相同', () => {
  const ids = PROFILES.map((p) => p.id)
  assert.deepEqual(
    ids,
    ['windows-all-in-one', 'android-all-in-one', 'handheld-label', 'old-shell-1.0.2', 'no-shell'],
    '设备档案清单变了（少一档 = 矩阵在缩表；加档请同批补文档与期望）',
  )
  const win = PROFILES[ids.indexOf('windows-all-in-one')]
  const android = PROFILES[ids.indexOf('android-all-in-one')]
  const winCaps = win.bridge.capabilities
  const androidCaps = android.bridge.capabilities

  // 「等价」的前提自证：两端能力表的键集相同，且**唯一**差异是 cut.link 的凭据值与更新通道
  // （后者在 /w/ 上没有 UI 面，见判据 ⑥）。
  assert.deepEqual(Object.keys(winCaps).sort(), Object.keys(androidCaps).sort(),
    '"等价"的前提破了：两端能力表的键集不同')
  assert.deepEqual(
    Object.keys(winCaps).filter((k) => winCaps[k] !== androidCaps[k]).sort(),
    [CAP_CUT_LINK, 'update.channel'].sort(),
    '两端的能力差异只允许是 cut.link 的凭据值与更新通道 —— 多出任何一项都说明两档不再等价',
  )
  // 读取器层面：两端只在 cut 凭据上不同，print 都是 null（能力等价，凭据不同）。
  assert.deepEqual(
    [terminalCapabilities({ terminal: win.bridge }), terminalCapabilities({ terminal: android.bridge })],
    [
      { state: CAP_STATE_PRESENT, cut: CUT_WINDOWS, print: null },
      { state: CAP_STATE_PRESENT, cut: CUT_ANDROID, print: null },
    ],
    '能力读取器没有逐字保留两端凭据（布尔化会丢掉「连哪台机器」这件事）',
  )

  // 同一批页面面逐面跑：入口集合相同 + 归一凭据后 HTML 逐字相同。
  const bad = []
  for (const face of FACES) {
    const a = renderFace(face, win.bridge)
    const b = renderFace(face, android.bridge)
    if (renderedEntries(a).join() !== renderedEntries(b).join()) {
      bad.push(`${face.id}：入口 ${renderedEntries(a).join('+') || '（无）'} ≠ ${renderedEntries(b).join('+') || '（无）'}`)
    }
    if (normalizeCredentials(a) !== normalizeCredentials(b)) {
      bad.push(`${face.id}：归一能力凭据后两端 HTML 仍不同（设备类型被当成菜单判据了）`)
    }
  }
  assert.deepEqual(bad, [], '两端同一批用例不成立：capabilities 等价时渲染必须逐字相同（唯一允许差异 = 凭据本身）')

  // 具体期望（不是「两边一样地错」）：两端都必须出裁高入口、都不出打印按钮。
  for (const [label, bridge] of [['Windows', win.bridge], ['安卓', android.bridge]]) {
    assert.deepEqual(renderedEntries(renderFace(FACES[3], bridge)), ['wh5-machine-entry'],
      `${label}一体机：有串口就出裁高入口、没有标签机就不出打印按钮（用户裁定：Windows 与安卓功能逐项一致）`)
  }

  // 归一函数自证：把「只差凭据」的两段文本抹平；且不得把整段文本吞掉（边界见元守卫 d）。
  const probeA = 'port serial:COM3 ready'
  const probeB = 'port serial:/dev/ttyS1 ready'
  assert.notEqual(probeA, probeB)
  assert.equal(normalizeCredentials(probeA), normalizeCredentials(probeB), '归一函数没能把能力凭据抹平（那这条判据就是空的）')
  assert.equal(normalizeCredentials(probeA), 'port «credential» ready', '归一函数把凭据以外的文本也改动了')
})

// ════════════════════════════════════════════════════════════════════════════════
// 判据 ⑥：负向 —— 三条没有 UI 面的能力键
// ════════════════════════════════════════════════════════════════════════════════

test('🔴 判据 ⑥ 负向：scan.hid / scan.camera / update.channel 没有 UI 面（取值任意 ⇒ 五个页面面逐字不变）', () => {
  const NON_UI_KEYS = ['scan.hid', 'scan.camera', 'update.channel']
  const BASE_CAPS = caps({ [CAP_CUT_LINK]: CUT_WINDOWS, [CAP_PRINT_LABEL]: 'ble', 'update.channel': 'exe' })
  const OMIT = Symbol('omit')
  const SHAPES = [
    ['缺省（键不在）', OMIT],
    ['null', null],
    ['true', true],
    ['false（与基线相反）', false],
    ['空串', ''],
    ['数字 0', 0],
    ['空数组', []],
    ['空对象', {}],
    ['怪字符串', 'usb:whatever'],
  ]
  const fingerprint = (table) => FACES.map((face) => `${face.id}::${renderFace(face, { capabilities: table })}`).join('\n@@FACE@@\n')
  const baseline = fingerprint(BASE_CAPS)

  const bad = []
  for (const key of NON_UI_KEYS) {
    for (const [shape, value] of SHAPES) {
      const table = { ...BASE_CAPS }
      if (value === OMIT) delete table[key]
      else table[key] = value
      if (fingerprint(table) !== baseline) {
        bad.push(`注入 ${key}=${shape} ⇒ 五个页面面渲染变了（这条键在 /w/ 上必须没有 UI 面）`)
      }
      const read = terminalCapabilities({ terminal: { capabilities: table } })
      if (read.state !== CAP_STATE_PRESENT || read.cut !== CUT_WINDOWS || read.print !== 'ble') {
        bad.push(`注入 ${key}=${shape} ⇒ 能力读取器变了（${JSON.stringify(read)}）`)
      }
    }
  }
  assert.deepEqual(
    bad,
    [],
    '负向面破了：三条「没有 UI 面」的能力键开始影响页面渲染 —— 不许新造 UI 能力轴（确需 UI 面须另裁定并改台账）',
  )

  // 自证这条判据咬得住：把**真有** UI 面的能力键改掉，指纹必须变（否则指纹是空转）。
  assert.notEqual(
    fingerprint({ ...BASE_CAPS, [CAP_CUT_LINK]: null }),
    baseline,
    '对照失败：连真有 UI 面的 cut.link 都改不动渲染 ⇒ 本判据的指纹是空转',
  )
})

// ════════════════════════════════════════════════════════════════════════════════
// 判据 ⑦：失败形态矩阵（2³）
// ════════════════════════════════════════════════════════════════════════════════

test('🔴 判据 ⑦ 失败形态矩阵：串口 × 蓝牙 × 摄像头 2³ 逐组合；unknown / absent 语义不变', () => {
  const reportFace = FACES.find((f) => f.id === 'report')
  assert.equal(reportFace?.id, 'report', '页面面清单变了：找不到 report 面（失败形态矩阵只跑这一面 ⇒ 入口与卡片同屏）')
  assert.equal(FAILURE_COMBOS.length, 8, '2³ 必须正好 8 组')

  const NON_HARDWARE_IDS = ['wh5-current-worker', 'wh5-worker-entries', 'wh5-rework-entry', 'wh5-set', 'wh5-finished-inbound']
  const seen = new Map()
  const bad = []
  for (const { cut, print, camera } of FAILURE_COMBOS) {
    const table = caps({ [CAP_CUT_LINK]: cut, [CAP_PRINT_LABEL]: print, 'scan.camera': camera })
    const html = renderFace(reportFace, { capabilities: table })
    const want = [
      cut !== null ? 'wh5-machine-entry' : null,
      print !== null ? 'wh5-fi-print' : null,
    ].filter(Boolean)
    const got = renderedEntries(html)
    const combo = `串口=${cut ?? '不在'} / 蓝牙=${print ?? '不在'} / 摄像头=${camera ? '在' : '不在'}`
    if (got.join() !== want.join()) bad.push(`${combo}：入口 ${got.join('+') || '（无）'} ≠ 期望 ${want.join('+') || '（无）'}`)
    for (const id of NON_HARDWARE_IDS) {
      if (!html.includes(`id="${id}"`)) bad.push(`${combo}：#${id} 不见了（无硬件 / 有硬件都不许动非硬件面）`)
    }
    if (/id="wh5-report"[^>]*\bdisabled/.test(html)) bad.push(`${combo}：报工按钮被禁用 —— 无硬件不阻断其它功能`)
    const read = terminalCapabilities({ terminal: { capabilities: table } })
    if (read.state !== CAP_STATE_PRESENT || read.cut !== cut || read.print !== print) {
      bad.push(`${combo}：能力读取器 ${JSON.stringify(read)} 没有逐字保留凭据`)
    }
    seen.set(`${cut}|${print}|${camera}`, html)
  }
  assert.deepEqual(bad, [], '失败形态矩阵破了：串口 / 蓝牙 / 摄像头的组合没有逐组兑现（缺省 = 隐藏，且不连坐其它面）')

  // 摄像头这一轴**不是判据**：同串口 / 同蓝牙下，摄像头在不在必须逐字相同。
  for (const cut of FAILURE_AXES.cut) {
    for (const print of FAILURE_AXES.print) {
      assert.equal(
        seen.get(`${cut}|${print}|true`),
        seen.get(`${cut}|${print}|false`),
        `摄像头在/不在改变了渲染（串口=${cut ?? '不在'} / 蓝牙=${print ?? '不在'}）—— 摄像头不是菜单判据`,
      )
    }
  }

  // 三态语义保持不变（B 包已定，本包不改）：unknown（旧壳）= 未知 ≠ 没有 ⇒ 两条都在；absent（无壳）⇒ 两条都没有。
  assert.deepEqual(
    [terminalCapabilities({ terminal: OLD_SHELL }).state, terminalCapabilities({ terminal: undefined }).state],
    [CAP_STATE_UNKNOWN, CAP_STATE_ABSENT],
    '三态常量与桥形态的对应关系变了（absent / unknown / present 不许互相吞并）',
  )
  assert.deepEqual(renderedEntries(renderFace(reportFace, OLD_SHELL)), ['wh5-machine-entry', 'wh5-fi-print'],
    'unknown（线上旧壳）隐藏了入口 ⇒ 迁移期会把真实工人的功能拿掉（未知 ≠ 没有）')
  assert.deepEqual(renderedEntries(renderFace(reportFace, undefined)), [],
    'absent（无壳）仍渲染了硬件入口 ⇒ fail-closed 破了')
})

// ════════════════════════════════════════════════════════════════════════════════
// 元守卫 d：矩阵自身不是空表（让「矩阵缩表 / 台账漂移」这一类进不来）
// ════════════════════════════════════════════════════════════════════════════════

test('🔴 元守卫 d：档位覆盖三态 / 期望入口由台账复算 / 2³ 全覆盖 / 入口清单与 B 包台账同源 / 文档在册', () => {
  // a) 五种桥态档位齐全（压成两态 ⇒ 迁移期口径没地方放；issue #8609 的线上现实就是 unknown）。
  assert.deepEqual(
    PROFILES.map((p) => p.id),
    ['windows-all-in-one', 'android-all-in-one', 'handheld-label', 'old-shell-1.0.2', 'no-shell'],
    '设备档案清单缩表了（四档必备 + 线上旧壳迁移档）',
  )
  assert.deepEqual(
    [...new Set(PROFILES.map((p) => terminalCapabilities({ terminal: p.bridge }).state))].sort(),
    [CAP_STATE_ABSENT, CAP_STATE_PRESENT, CAP_STATE_UNKNOWN].sort(),
    '三态必须各至少有一档（缺少的那一态会变成没有判据的盲区）',
  )

  // b) 档位期望入口必须**由台账按能力复算得出**，不许是「按档名手写的业务真相」。
  const bad = []
  for (const profile of PROFILES) {
    const read = terminalCapabilities({ terminal: profile.bridge })
    if (read.state !== profile.expectedState) bad.push(`${profile.id}：三态 ${read.state} ≠ 期望 ${profile.expectedState}`)
    const want = HARDWARE_ENTRIES.filter((e) => capabilityShown(read, e.axis)).map((e) => e.id)
    if (want.join() !== profile.entries.join()) {
      bad.push(`${profile.id}：档位期望 ${profile.entries.join('+') || '（无）'} ≠ 台账按能力算出的 ${want.join('+') || '（无）'}`)
    }
  }
  assert.deepEqual(bad, [], '档位期望与能力判定不同源：矩阵正在变成第二份业务真值')

  // c) 2³ 全覆盖：三条轴各两个取值，笛卡尔积正好 8 组且不重复。
  assert.deepEqual(
    [FAILURE_AXES.cut.length, FAILURE_AXES.print.length, FAILURE_AXES.camera.length],
    [2, 2, 2],
    '失败形态矩阵的轴必须各两个取值（在 / 不在）',
  )
  assert.equal(new Set(FAILURE_COMBOS.map((c) => `${c.cut}|${c.print}|${c.camera}`)).size, 8, '2³ 组合有重复（少判了某个组合）')

  // d) 硬件入口清单 ⇄ B 包台账 ⇄ `render.mjs` 能力键常量：三方同源（漂移 = 矩阵静默漏判一个入口）。
  const renderSrc = readFileSync(new URL('../src/render.mjs', import.meta.url), 'utf8')
  const constantOf = Object.fromEntries(
    [...renderSrc.matchAll(/export const (CAP_[A-Z_]+) = '([^']+)'/g)].map((m) => [m[1], m[2]]),
  )
  const bTestSrc = readFileSync(new URL('./worker-h5-8609-capabilities.test.mjs', import.meta.url), 'utf8')
  const ledger = [...bTestSrc.matchAll(/\{\s*key:\s*(CAP_[A-Z_]+),\s*axis:\s*'([^']+)',\s*entry:\s*'([^']+)'\s*\}/g)]
    .map((m) => ({ key: constantOf[m[1]], axis: m[2], entry: m[3] }))
  assert.deepEqual(
    ledger.map((r) => [r.key, r.axis, r.entry]).sort(),
    HARDWARE_ENTRIES.map((e) => [e.key, e.axis, e.id]).sort(),
    '本矩阵的硬件入口清单与 B 包台账 / render.mjs 的能力键不同源（漂移 = 矩阵漏判一个入口而全绿）',
  )

  // e) 三条**没有 UI 面**的能力键有意不在台账（读了不用 = 假轴）；将来要 UI 面 = 另裁定 + 改台账。
  for (const key of ['scan.hid', 'scan.camera', 'update.channel']) {
    assert.equal(ledger.some((r) => r.key === key), false,
      `${key} 进了台账 —— 本包边界是不新造 UI 能力轴（确需 UI 面须另行裁定）`)
  }

  // f) 归一函数不吞正常文本：`\b` 边界下 `ble` 不得匹配 `disabled`（否则逐字对照会把真实差异抹掉）。
  assert.equal(normalizeCredentials('disabled'), 'disabled', '归一函数把 disabled 里的 ble 吃掉了（边界失效 ⇒ 对照会假绿）')
  assert.equal(normalizeCredentials('x serial:COM3 y'), 'x «credential» y', '归一函数没有按预期抹平能力凭据')

  // g) 矩阵文档在册（档名逐个出现 + 外部边界与重启条件写明）：文档与判据同源，避免「文档说一套、判据判一套」。
  const doc = readFileSync(new URL('../../../docs/testing/terminal-shell-capability-matrix.md', import.meta.url), 'utf8')
  for (const profile of PROFILES) {
    assert.equal(doc.includes(profile.id), true, `矩阵文档缺档位 ${profile.id}（docs/testing/terminal-shell-capability-matrix.md）`)
  }
  for (const token of ['migao-terminal', '本仓测不了', '重启条件']) {
    assert.equal(doc.includes(token), true, `矩阵文档缺「${token}」一节（本仓测不了什么 + 什么时候重启复探）`)
  }
})
