// case_ids: PG-018, BM-006, DF-017
//
// 一体机「裁高计算」（母单 #5161；设计 docs/design/cutting-height-config-and-terminal.md §2.6）。
// 文案（2026-10-10 用户裁定，issue #6635）：屏上/入口一律叫「裁高计算（一体机）」——「机台模式」是内部叫法。
//
// 形态（用户 2026-09-29 逐字裁定）：机器旁一块屏 + 一把**有线扫码枪**（= HID 键盘楔）。
//   扫观星台自己的水洗唛（部位级码 `/s/<短码>` 或 token）⇒ **同一屏**给出
//   ①订单详情 ②裁高值大字「请在机器屏输入 X.XXX 米」③【完成】按钮（点它 = 报工）；
//   另可进「裁高计算器」看命中项明细并手改**本次显示**。
//
// 🔴 本包**不写机器**（裁定①「下发先不做」）：不开串口、不发 Modbus、不写下发 —— 任何路径都不
//    产出「下发」这个动作面（判据 = tests/worker-h5-machine.test.mjs 的写面守卫）。
// 🔴 本包**不做**手机 ↔ 一体机联动（裁定②）：没有 SSE / 轮询 / 工位焦点。
// 🔴 裁高值**由服务端算**（复用 CuttingHeightConfigService.preview）：
//    本文件只做「渲染 + 本次显示的手改合计」，**不重算命中**（命中口径只有服务端一份）。
//    手改按裁定⑧**只改本次显示**：不落库、不留痕，刷新即回规则值。
// 🔴 **报工**（2026-09-29 追加裁定「一体机本期要做报工，且是一条链」）：扫水洗唛 ⇒ 同一屏出
//    ①订单详情 ②裁高值（大字）③【完成】按钮 —— 点【完成】= 报工。落法**照既有实现**：
//    调既有 `POST /api/worker/production/scan/complete`（工人页现用入口），**工序由服务端推断**。
//    前端**只发 token + 幂等键**：数量 / 工序 / 身份（计件归属）一律由服务端定 ——
//    手改的裁高取舍**不进**报工请求（报工与「给机器输值」是两件事）。
//
// 零依赖、零构建：纯函数（可被 `node --test` 直接钉住，无需 DOM）。

// 工序显示名走**唯一**口径（issue #4963）；模块位置在 issue #6306 迁进树内（`src/shared/`）——
// 原先住仓根 `frontend/shared/`（发布集之外）⇒ 线上被 SPA 兜底接成 `200 text/html` ⇒ 整页白屏。
import { operationDisplayName } from './shared/operation-display.mjs'

/** 缺值显示（**显式**：缺就显示这个，绝不猜 0 —— 给机器的值偏小 = 裁短 = 事故）。 */
export const EMPTY = '—'

/**
 * 「去报工页」出口（issue #6635）：机台那台屏被本机预设钉在裁高页（`?page=cut_calc`）后，
 * 工人临时要报普通工时得有**一条**出路 —— `keep=1` = **只本次**，绝不把机台的预设改掉
 * （改掉 ⇒ 这台屏下次开机就不再是机台模式了）。见 frontend/worker-h5/src/scan-input.mjs。
 */
export const MACHINE_REPORT_HREF = '/w/?page=report&keep=1'

/** 机器屏精度（三位小数 = mm；服务端 `rounding.digits` 是唯一真值，这里只是渲染兜底）。 */
export const DEFAULT_DIGITS = 3

/**
 * 登录页出口（issue #6667 第 1 条，P0）：机台那台屏**没有登录面**，未登录时只显示
 * 「请先用工号 + PIN 登录」而屏上**没有任何可点的登录入口** ⇒ 车间里盯着这块屏的人无路可走。
 *
 * 修法 = 给一条**真的**链接（`/w/` 才是登录那一页；机台页是同一静态根下的另一张页）。
 * 🔴 不把登录表单搬进机台页：本页刻意零文本输入元素（扫码枪的字符不被输入法吃掉，
 * 见 `createScanBuffer` 与 machine.html 的头注释）—— 搬进来等于把那条护栏拆掉。
 */
export const MACHINE_LOGIN_HREF = '/w/'

const esc = (v) =>
  String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])

/** 数值 → 固定位数文本；`null` / 非数 ⇒ {@link EMPTY}（不显示 0）。 */
export function fmtNumber(value, digits = DEFAULT_DIGITS) {
  if (value === null || value === undefined || value === '') return EMPTY
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(digits) : EMPTY
}

/** 缺值兜底：空串 / null / undefined ⇒ {@link EMPTY}。 */
export function dataOr(value) {
  if (value === null || value === undefined) return EMPTY
  const text = String(value).trim()
  return text === '' ? EMPTY : text
}

/** 取整位数（服务端 `rounding.digits`；缺 ⇒ 三位小数 —— 机器屏口径）。 */
export function digitsOf(position) {
  const digits = Number(position?.rounding?.digits)
  return Number.isInteger(digits) && digits >= 0 && digits <= 3 ? digits : DEFAULT_DIGITS
}

/**
 * 本次显示值 = 成品高 + Σ(勾选项 × direction)。
 *
 * 🔴 **只影响本次显示**（裁定⑧：不落库、不留痕；刷新回规则值）—— 权威值永远是服务端的
 * `cutting_height`（页面同时显示「规则值」）。不做勾选（默认全勾）时本函数必须与服务端值相等
 * （判据见 tests：`不勾选 ⇒ 本次值 == 服务端值`）。
 *
 * 实现按**显示精度做整数运算**（每个加数先按 digits 定点），避免二进制浮点把 2.700+0.0625+…
 * 算成 3.0274999999999994 而显示成 3.027（服务端 BigDecimal 给的是 3.028）。
 */
export function machineTotal(position, unchecked = []) {
  const base = position?.base
  if (base === null || base === undefined) return null
  const unit = 10 ** digitsOf(position)
  const scale = (v) => Math.round(Number(v) * unit)
  let scaled = scale(base)
  for (const hit of position?.hits ?? []) {
    if (unchecked.includes(hit?.key)) continue
    const value = Number(hit?.value)
    if (!Number.isFinite(value)) continue
    scaled += (hit?.direction === 'subtract' ? -1 : 1) * scale(value)
  }
  return scaled / unit
}

/** 手改过没有（勾选状态 ≠ 服务端的全命中）。 */
export function isEdited(position, unchecked = []) {
  return unchecked.length > 0
}

/** 命中项行（服务端预勾 = 全部命中项；`unchecked` = 工人本次取消的）。 */
export function hitRows(position, unchecked = []) {
  return (position?.hits ?? []).map((hit) => ({
    key: hit?.key,
    name: dataOr(hit?.name),
    value: hit?.value,
    direction: hit?.direction === 'subtract' ? 'subtract' : 'add',
    heightJoin: hit?.height_join === true,
    checked: !unchecked.includes(hit?.key),
  }))
}

/** 未配置取值的项（服务端 `misses[].reason='unresolved'`）—— **标黄、不计入**（不按 0 算）。 */
export function unresolvedRows(position) {
  return (position?.misses ?? []).filter((miss) => miss?.reason === 'unresolved')
}

export function positionsOf(data) {
  return Array.isArray(data?.positions) ? data.positions : []
}

export function selectedPosition(state) {
  const positions = positionsOf(state?.data)
  if (!positions.length) return null
  const index = Number.isInteger(state?.positionIndex) ? state.positionIndex : 0
  return positions[Math.min(Math.max(index, 0), positions.length - 1)]
}

// ══════════════════════════════════════════════════════════════════════════════
// 常驻扫码枪缓冲（HID 键盘楔）
//
// 🔴 **不依赖 `focus()`**：监听挂在 `document` 上（见 machine-app.mjs），
//    HID 楔的按键直接进全局 `keydown` 流 —— 车间里没人会先去点一下输入框。
// 🔴 **输入法**：机台页**没有任何文本输入元素**（无 `input[type=text]` / `textarea` / `contenteditable`，
//    只有按钮与勾选框）⇒ IME 根本没有合成目标；再加两道兜底：
//    `event.isComposing === true` 与 `compositionstart/end` 之间的按键**一律不进食**
//    （中文输入法把字符吃掉/换成候选的过程不会污染缓冲）。
//    为什么不用 `keypress` / `beforeinput`：`beforeinput` 只对**可编辑目标**触发（本页没有，
//    所以它永远不会 fire，用它 = 空断言）；`keypress` 已废弃且同样以「有输入目标」为前提。
//    `keydown` 是唯一「无焦点也能收到、且带 Enter」的通道。
// 🔴 **后缀兼容**：枪的 `CR` / `LF` / `CR+LF` 到了浏览器都是 `key === 'Enter'`（个别固件给 '\r' / '\n'）
//    ⇒ 遇终结符就交出缓冲；**空缓冲时的终结符直接忽略**（双 Enter / CR+LF 的第二下不会交出空码）。
// ══════════════════════════════════════════════════════════════════════════════

/**
 * 造一个扫码枪缓冲。
 *
 * @param {object} opts
 * @param {(code: string) => void} opts.onCode 交出一次完整码（非空）
 * @param {number} [opts.idleMs] 枪没配后缀时的兜底：静默这么久就交出（0 = 关闭）
 * @param {Function} [opts.schedule] 定时器（测试注入，保证判定与真实时钟无关）
 * @param {Function} [opts.cancel] 定时器取消
 */
export function createScanBuffer({ onCode, idleMs = 120, schedule = (fn, ms) => setTimeout(fn, ms), cancel = (id) => clearTimeout(id) } = {}) {
  let buffer = ''
  let composing = false
  let timer = null

  const stopIdle = () => {
    if (timer !== null) {
      cancel(timer)
      timer = null
    }
  }

  const clear = () => {
    stopIdle()
    buffer = ''
  }

  /** 交出缓冲并清空；**空缓冲 ⇒ 什么都不做**（忽略「空缓冲时的 Enter」）。 */
  const emit = () => {
    const code = buffer
    clear()
    if (code) onCode?.(code)
  }

  const armIdle = () => {
    stopIdle()
    if (!idleMs) return
    timer = schedule(() => {
      timer = null
      emit()
    }, idleMs)
  }

  return {
    /** 键盘事件入口（挂 document；**不要求任何元素有焦点**）。 */
    handleKeyDown(event) {
      if (!event) return
      // 输入法合成中的按键不进食（两种判据：标准 isComposing + 我们自己记的 composition 区间）
      if (composing || event.isComposing === true) return
      const key = event.key
      if (key === 'Enter' || key === '\r' || key === '\n') {
        // 机台页没有表单 ⇒ 吃掉默认行为既安全、又**必须**：
        // 枪的后缀是 CR+LF（两下 Enter），而工人刚点过的按钮/勾选框仍带着焦点
        // ⇒ 留下默认行为时第二下会「再点一次」它（屏自己跳走）。
        event.preventDefault?.()
        // 空缓冲时的 Enter 直接忽略（双 Enter / CR+LF 的第二下）；非空 ⇒ 一次完成的扫码
        if (!buffer) return
        emit()
        return
      }
      if (typeof key !== 'string' || key.length !== 1) return
      buffer += key
      armIdle()
    },
    handleCompositionStart() {
      composing = true
    },
    /** 合成结束：合成产生的文本**不**当码（那多半是有人在用中文输入法，不是扫码枪）。 */
    handleCompositionEnd() {
      composing = false
      clear()
    },
    /** 当前缓冲（诊断/测试用）。 */
    peek: () => buffer,
    clear,
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// 状态机（纯函数）
// ══════════════════════════════════════════════════════════════════════════════

export function initialMachineState() {
  return {
    mode: 'scan',
    worker: null,
    token: null,
    data: null,
    positionIndex: 0,
    unchecked: [],
    notice: null,
    error: null,
    // 报工（2026-09-29 追加裁定：一体机本期**要做报工**）—— 与裁高值同屏，但**两件事**：
    // 报工 = 推进工序/记计件（服务端推断工序、服务端解身份）；「请在机器屏输入 X 米」= 给人一个数。
    reporting: false,
    receipt: null,
    reportError: null,
  }
}

/**
 * 状态转移。`mode`：`scan`（等扫码）· `detail`（屏一 订单详情 + 裁高值 + 【完成】）·
 * `calc`（屏二 裁高计算器）· `error`。
 */
export function reduceMachine(state, action) {
  switch (action?.type) {
    case 'worker':
      return { ...state, worker: action.worker ?? null }
    case 'scanned':
      // 扫一次 ⇒ **直接**进屏一；默认选中「扫到的那个部位」（水洗唛就在手上那件帘上）
      return {
        ...state,
        mode: 'detail',
        token: action.token ?? null,
        data: action.data ?? null,
        positionIndex: scannedIndex(action.data),
        unchecked: [],
        notice: action.notice ?? null,
        error: null,
        // 新的一张码 = 新的一次报工：回执/报错不能跨码携带
        reporting: false,
        receipt: null,
        reportError: null,
      }
    case 'openCalc':
      return { ...state, mode: 'calc', notice: null, error: null }
    case 'back':
      return { ...state, mode: 'detail', notice: null }
    case 'pick': {
      const index = Number(action.index)
      if (!Number.isInteger(index)) return state
      // 换部位 ⇒ 手改重置（手改是「这一个部位的本次显示」，跨部位带着走会把上一件帘的取舍算进来）
      return { ...state, positionIndex: index, unchecked: [], notice: action.notice ?? null }
    }
    case 'toggleHit': {
      const key = action.key
      if (!key) return state
      const unchecked = state.unchecked.includes(key)
        ? state.unchecked.filter((k) => k !== key)
        : [...state.unchecked, key]
      return { ...state, unchecked }
    }
    case 'reportStart':
      return { ...state, reporting: true, reportError: null, notice: null }
    case 'reported':
      return {
        ...state,
        reporting: false,
        receipt: action.receipt ?? null,
        reportError: null,
        notice: reportNotice(action.receipt),
      }
    case 'reportFailed':
      // 🔴 失败**显式**：屏上大字报错，并且**绝不**留下一个看起来像成功的回执
      return { ...state, reporting: false, receipt: null, reportError: action.error ?? '报工失败' }
    case 'failed':
      return { ...state, mode: 'error', error: action.error ?? '未知错误', data: null, unchecked: [] }
    case 'notice':
      return { ...state, notice: action.notice ?? null }
    default:
      return state
  }
}

/** 报工回执 → 一句人话（「下一道」由**服务端**给，前端不猜工序）。 */
export function reportNotice(receipt) {
  if (!receipt) return null
  const next = receipt.nextOperation
  const nextLabel = next ? operationDisplayName(next) : null
  const tail = nextLabel ? `下一道 = ${nextLabel}` : (receipt.setCompleted ? '本套工序都已被领走' : '本套已无待做工序')
  return `已报工 · ${tail}${receipt.replayed === true ? '（系统按同一次提交处理，未重复计件）' : ''}`
}

/**
 * 本次提交可复用的幂等键（与手机报工页**同一份判据**：同一张码 + 同一工人）。
 *
 * 🔴 为什么必须跨刷新复用：`X-Client-Request-Id` 只活在内存里时，「已发出、答复丢了」这段窗口
 * 一刷新就没了 ⇒ 重扫同一张码会带**新键** ⇒ 服务端当成**新的一次报工**（多给钱）。
 * 任一条件不成立（换码 / 换工人 / 工人未知）⇒ `null`（fail-closed，退回新键）。
 */
export function resumePending(pending, { token, workerId } = {}) {
  if (!pending || !token || !workerId) return null
  return pending.token === token && pending.workerId === workerId ? pending.requestId : null
}


function scannedIndex(data) {
  const positions = positionsOf(data)
  const index = positions.findIndex((p) => p?.scanned === true)
  return index >= 0 ? index : 0
}

// ══════════════════════════════════════════════════════════════════════════════
// 渲染（HTML 字符串；机台页零可编辑元素）
// ══════════════════════════════════════════════════════════════════════════════

/** 屏一 订单详情：品牌 / 收货人 / 款式 / 套数 / 宽高 / 加工类型 / 安装工艺 / 褶倍 / 用料 / 部位备注。 */
export function detailRows(data, position) {
  return [
    ['品牌', position?.brand, ''],
    ['收货人', data?.order?.customer_name, ''],
    ['款式', dataOr(position?.product_name) === EMPTY ? position?.curtain_type : position?.product_name, ''],
    // 第 4 位 = 显示口径：'m' 三位小数（机器精度）· 'int' 整数 · 缺省原样（不替人四舍五入）
    ['套数', data?.order?.set_count, '套', 'int'],
    ['宽', position?.width, '米', 'm'],
    ['高', position?.height, '米', 'm'],
    ['加工类型', position?.cutting_mode, ''],
    ['开数', position?.open_count, '', 'int'],
    ['安装工艺', position?.craft, ''],
    ['褶倍', position?.fullness, '倍'],
    ['用料', position?.fabric_meters, '米', 'm'],
    // 部位备注（issue #6667 第 9 条）：备注是**商家挂在某个商品行上**的自由文本，多部位单里
    // 只印备注 ⇒ 工人不知道说的是哪一幅帘 ⇒ 印成「商品行名 · 备注」。缺商品行名 ⇒ 只印备注（不塞占位）。
    ['部位备注', remarkText(position), ''],
  ]
}

/** 「商品行名 · 部位备注」；两者都缺 ⇒ `null`（由 `dataOr` 兜成「—」）。 */
function remarkText(position) {
  const remark = dataOr(position?.position_remark)
  const product = dataOr(position?.product_name)
  if (remark === EMPTY) return product === EMPTY ? null : product
  return product === EMPTY ? remark : `${product} · ${remark}`
}

function kvRows(rows) {
  return rows
    .map(([label, value, unit, format]) => {
      let shown = dataOr(value)
      if (value !== null && value !== undefined && Number.isFinite(Number(value))) {
        if (format === 'm') shown = fmtNumber(value, DEFAULT_DIGITS)
        else if (format === 'int') shown = String(Math.trunc(Number(value)))
        else shown = String(Number(value))
      }
      return `<div class="wh5-machine__kv"><dt>${esc(label)}</dt><dd>${esc(shown)}${shown === EMPTY ? '' : esc(unit ?? '')}</dd></div>`
    })
    .join('')
}

function positionTabs(state) {
  const selected = Number.isInteger(state?.positionIndex) ? state.positionIndex : 0
  return positionsOf(state.data)
    .map((position, index) => {
      const label = `${dataOr(position?.position_name ?? position?.position_kind)}${position?.scanned ? '（扫到的）' : ''}`
      return `<button type="button" class="wh5-machine__tab${index === selected ? ' is-active' : ''}" data-machine-pick="${index}">${esc(label)}</button>`
    })
    .join('')
}

function noticeBlock(notice) {
  return notice ? `<p class="wh5-machine__notice">${esc(notice)}</p>` : ''
}

/** 缺项 → 一句人话（指名，不含糊：「缺少 finished_height」而不是「数据异常」）。 */
function missingText(missing) {
  const fields = (Array.isArray(missing) ? missing : []).map((m) => dataOr(m))
  return fields.length ? `缺少${fields.join(' / ')}` : '缺少必需取值'
}

/**
 * 报工区（**与裁高值同屏**，但两件事）：
 *   ① 大字「请在机器屏输入 X.XXX 米」（值 = 调用方给的显示值：屏一 = 服务端规则值；屏二 = 本次合计）
 *   ② 【完成】= 报工（`POST /api/worker/production/scan/complete`）：**工序由服务端推断**，
 *      前端只发 token + 幂等键 ⇒ 屏上这个数**不会**被写进报工请求（给机器的值与报工是两件事）
 *   ③ 失败**大字显式**（不假装成功）；成功 ⇒「已报工 · 下一道 = X」（下一道也由服务端给）
 */
function reportBlock(state, { value, digits, missingNote }) {
  const ready = value !== null && value !== undefined && Number.isFinite(Number(value))
  const big = ready
    ? `<p class="wh5-machine__big">请在机器屏输入 <b>${esc(fmtNumber(value, digits))}</b> 米</p>`
    : `<p class="wh5-machine__missing">⚠ ${esc(dataOr(missingNote))} ⇒ <b>算不出裁剪高度</b>，请在机器上按工艺复核（本页不猜数）</p>`
  const button = state.receipt
    ? '<button type="button" class="wh5-machine__cta" disabled>已报工</button>'
    : `<button type="button" class="wh5-machine__cta" data-machine-report${state.reporting ? ' disabled' : ''}>${state.reporting ? '报工中…' : '完成'}</button>`
  return `
    <div class="wh5-machine__report">
      ${big}
      ${state.reportError ? `<p class="wh5-machine__big wh5-machine__big--error">报工失败：${esc(dataOr(state.reportError))}</p>` : ''}
      ${state.receipt ? `<p class="wh5-machine__done">✅ ${esc(dataOr(reportNotice(state.receipt)))}</p>` : ''}
      <div class="wh5-machine__actions">${button}</div>
      ${state.receipt ? '<p class="wh5-machine__hint">继续下一件请再扫一次水洗唛（同一张码再扫 = 领下一道）</p>' : ''}
    </div>`
}

/** 屏二 裁高计算器：命中项（预勾 + 可手改）+ 未配置取值标黄 + 实时合计 + 大字。 */
export function renderCalc(state) {
  const position = selectedPosition(state)
  if (!position) return renderError('没有可算的部位：请重新扫码')

  const digits = digitsOf(position)
  const total = machineTotal(position, state.unchecked)
  const serverValue = position?.cutting_height
  const edited = isEdited(position, state.unchecked)
  const missing = Array.isArray(position?.missing) ? position.missing : []

  const hitList = hitRows(position, state.unchecked)
    .map((hit) => `<label class="wh5-machine__hit${hit.checked ? '' : ' is-off'}">
        <input type="checkbox" data-machine-hit="${esc(hit.key)}"${hit.checked ? ' checked' : ''} />
        <span class="wh5-machine__hit-name">${esc(hit.name)}</span>
        <span class="wh5-machine__hit-value">${hit.direction === 'subtract' ? '−' : '+'}${esc(fmtNumber(hit.value, digits))}</span>
      </label>`)
    .join('')

  const unresolved = unresolvedRows(position)
    .map((miss) => `<li class="wh5-machine__warn">${esc(dataOr(miss?.name))}：<b>未配置取值</b> ⇒ 不计入、也不按 0 算（请商家在「裁高配置」里补值）</li>`)
    .join('')

  return `
    <section class="wh5-machine__panel" data-machine-screen="calc">
      <header class="wh5-machine__head">
        <button type="button" class="wh5-machine__back" data-machine-back>◀ 订单详情</button>
        <h1>裁高计算器</h1>
        <span class="wh5-machine__worker">${esc(dataOr(state.worker?.workerName))}</span>
      </header>
      <nav class="wh5-machine__tabs">${positionTabs(state)}</nav>
      <div class="wh5-machine__body">
        <div class="wh5-machine__col">
          <h2>命中项（系统预勾，可手改本次显示）</h2>
          <div class="wh5-machine__hits">${hitList || '<p class="wh5-machine__empty">本部位没有任何命中的增量项</p>'}</div>
          ${unresolved ? `<h2>未配置取值（标黄：不计入）</h2><ul class="wh5-machine__warns">${unresolved}</ul>` : ''}
        </div>
        <div class="wh5-machine__col">
          <dl class="wh5-machine__sum">
            <div><dt>成品高</dt><dd>${esc(fmtNumber(position?.base, digits))}</dd></div>
            <div><dt>本次合计${edited ? '（手改）' : ''}</dt><dd>${esc(fmtNumber(total, digits))}</dd></div>
            <div><dt>规则值（系统）</dt><dd>${esc(fmtNumber(serverValue, digits))}</dd></div>
            <div><dt>取整</dt><dd>${esc(dataOr(position?.rounding?.mode))} · ${esc(dataOr(digits))} 位</dd></div>
          </dl>
          ${edited ? '<p class="wh5-machine__edited">本次手改只影响本屏显示：不会写进订单，刷新即回到规则值</p>' : ''}
          ${reportBlock(state, { value: total, digits, missingNote: missingText(missing) })}
        </div>
      </div>
      ${noticeBlock(state.notice)}
    </section>`
}

/** 屏一 订单详情。 */
export function renderDetail(state) {
  const position = selectedPosition(state)
  if (!position) return renderError('这次扫码没有解析出任何部位：请重新扫码')
  const missing = Array.isArray(position?.missing) && position.missing.length
    ? `<p class="wh5-machine__missing">⚠ 本部位缺 ${esc(position.missing.join(' / '))}：${esc(dataOr(position.missing_reason))}</p>`
    : ''
  return `
    <section class="wh5-machine__panel" data-machine-screen="detail">
      <header class="wh5-machine__head">
        <h1>订单详情</h1>
        <span class="wh5-machine__worker">${esc(dataOr(state.worker?.workerName))}</span>
      </header>
      <nav class="wh5-machine__tabs">${positionTabs(state)}</nav>
      <div class="wh5-machine__body">
        <dl class="wh5-machine__kv-list">${kvRows(detailRows(state.data, position))}</dl>
        <div class="wh5-machine__col">
          ${reportBlock(state, {
            value: position?.cutting_height,
            digits: digitsOf(position),
            missingNote: missingText(position?.missing),
          })}
          <div class="wh5-machine__actions">
            <button type="button" class="wh5-machine__back" data-machine-open-calc>裁高计算器 ▶（看命中项 / 手改）</button>
          </div>
        </div>
      </div>
      ${missing}
      ${noticeBlock(state.notice)}
    </section>`
}

/**
 * 等扫码 / 报错两态（大字 + 常驻扫码提示）。
 *
 * 🔴 两条现场出口（issue #6667）：
 *   ① **未登录时有登录入口**：改前这块屏只写「请先用工号 + PIN 登录」而**全文件零 `<a>`**
 *      ⇒ 车间里盯着屏的人无路可走（他连登录那一页都回不去）。修法见 {@link MACHINE_LOGIN_HREF}。
 *   ② **有工人时有「切换工人」**：机台与手机页共享同一份 `migao:worker-h5:session`，上一班登出后
 *      下一班扫自己的码，报工可能仍记在上一个人头上（**计件归属错 = 涉钱**）⇒ 给一个人人都会按的出口。
 *      ⚠️ **未做（如实登记）**：空闲超时自动回登录态**不在本包**——机台是常驻屏，「没人动」不等于
 *      「没人用」（工人把料搬过来那几分钟也算空闲），自动踢人会把「活干不了」变成新的现场故障；
 *      本包只落**人主动切**这条最小可行动作，边界与重启条件写在 PR body。
 */
export function renderScan(state) {
  const failed = state.mode === 'error'
  const hasWorker = Boolean(state.worker)
  return `
    <section class="wh5-machine__panel wh5-machine__panel--idle" data-machine-screen="${failed ? 'error' : 'scan'}">
      <header class="wh5-machine__head">
        <h1>裁高计算（一体机）</h1>
        ${hasWorker ? `<span class="wh5-machine__worker">${esc(dataOr(state.worker?.workerName))}</span>` : ''}
        ${hasWorker ? '<button type="button" class="wh5-machine__back" id="wh5-machine-switch-worker">切换工人</button>' : ''}
      </header>
      ${failed
        ? `<p class="wh5-machine__big wh5-machine__big--error">${esc(dataOr(state.error))}</p><p class="wh5-machine__hint">请重新扫一次水洗唛（同一张码再扫 = 领下一道）</p>`
        : '<p class="wh5-machine__big">请扫水洗唛</p><p class="wh5-machine__hint">扫一次即可看到订单详情与裁剪高度（无需点输入框）</p>'}
      ${hasWorker ? '' : `<p class="wh5-machine__hint">这台屏上扫的活记在<strong>当前工人</strong>名下 ⇒ 请先<a class="wh5-machine__back" id="wh5-machine-login" href="${MACHINE_LOGIN_HREF}">登录</a>（工号 + PIN）</p>`}
      <p class="wh5-machine__hint"><a class="wh5-machine__back" id="wh5-machine-to-report" href="${MACHINE_REPORT_HREF}">去报工页（本机不记住）</a></p>
      ${noticeBlock(state.notice)}
    </section>`
}

/** 整页（按 mode 分派）。 */
export function renderMachine(state) {
  if (state?.mode === 'detail') return renderDetail(state)
  if (state?.mode === 'calc') return renderCalc(state)
  return renderScan(state ?? initialMachineState())
}

function renderError(message) {
  return renderScan({ ...initialMachineState(), mode: 'error', error: message })
}
