// case_ids: BM-014, BM-015, BM-025
/**
 * 扫码报工的**状态机判据**（issue #7812 P2a；实现 = `src/utils/reportState.ts`）。
 *
 * 这一层是本页最危险的地方（报一笔 = 一笔计件工资），所以判据**全部**钉在纯函数上：
 * 不渲染、不联网、不需要 DOM。
 *
 * ## 四条硬约束（每条都有独立红证）
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | ① | 旧码（`granularity:'order'` / `needs_selection` 非空）⇒ `mode='select'`、`selection` 清空，**绝不默认取第 1 套** | `applyScan` 里把 `selection` 预置成第一套 ⇒ 红 |
 * | ② | 工序未确定（`operation == null`）⇒ `canReport` false | 删掉 `!view.operation?.operation_id` 那一行 ⇒ 红 |
 * | ③ | 未登录（`worker == null`）⇒ `canReport` false | 删掉 `!state.worker` 那一行 ⇒ 红 |
 * | ④ | 回执只认服务端的 `next_operation` / `set_completed`，**前端不猜下一道** | 让 `receiptLine` 在没有 `next_operation` 时自己编一道 ⇒ 红 |
 *
 * 另外三条与线上事故直接相关：
 * - **提交在飞不清屏**：`applyScan` 之后 `submitting` 必须归零（否则上一屏的「提交中」把这一屏按钮禁死）；
 * - **半截选择不发给服务端**：`legacySelection` 只有「套 + 部位」都齐才返回；
 * - **码解析三形态**：短链 / `?t=` / 裸码（印在纸上的三种都有）。
 */
import {
  DEFAULT_WORK_TYPE,
  MISSING,
  WORK_TYPES,
  applyReceipt,
  applyScan,
  canReport,
  initialState,
  isLegacyScan,
  isQualityOperation,
  kindText,
  legacySelection,
  operationName,
  pickPosition,
  pickSet,
  progressText,
  qtyText,
  receiptLine,
  signedIn,
  titleText,
  tokensFromScanResult,
  type ReportState,
  type ReportView,
} from '../src/utils/reportState'

const WORKER = { worker_name: '张师傅', worker_no: 'W-001' }

/** 新码一屏（有工序、可报工）。 */
const MAIN_VIEW: ReportView = {
  granularity: 'set_position',
  set_no: 2,
  position: { order_item_id: 'item-1', position_name: '布帘', position_kind: '布帘' },
  operation: { operation_id: 'op-1', logical_name: '车被', qty: 11, unit: '米' },
  alternatives: [],
  needs_selection: [],
  set_progress: { done: 1, total: 3 },
}

/** 旧码一屏（必须选套 + 部位）。 */
const LEGACY_VIEW: ReportView = {
  granularity: 'order',
  set_no: null,
  operation: null,
  needs_selection: [
    {
      set_id: 'set-1',
      set_no: 1,
      positions: [
        { order_item_id: 'item-1', position_name: '布帘', position_kind: '布帘' },
        { order_item_id: 'item-2', position_name: '纱帘', position_kind: '纱帘' },
      ],
    },
    {
      set_id: 'set-2',
      set_no: 2,
      positions: [{ order_item_id: 'item-3', position_name: '布帘', position_kind: '布帘' }],
    },
  ],
}

const loggedIn = (): ReportState => signedIn(initialState(WORKER), WORKER)

describe('① 旧码：进选套态，绝不默认取第 1 套', () => {
  test('applyScan 把旧码判成 select 态，且 selection 清空', () => {
    const next = applyScan(loggedIn(), LEGACY_VIEW)
    expect(next.mode).toBe('select')
    expect(next.selection).toEqual({ setId: null, orderItemId: null })
    expect(next.notice).toContain('旧码')
  })

  test('isLegacyScan 两条判据都认（granularity 与 needs_selection）', () => {
    expect(isLegacyScan(LEGACY_VIEW)).toBe(true)
    expect(isLegacyScan({ granularity: 'order' })).toBe(true)
    expect(isLegacyScan({ needs_selection: [{ set_id: 's', positions: [] }] })).toBe(true)
    expect(isLegacyScan(MAIN_VIEW)).toBe(false)
    expect(isLegacyScan(null)).toBe(false)
  })

  test('旧码未选完 ⇒ 不可报工；选完套 + 部位 ⇒ legacySelection 才齐', () => {
    let state = applyScan(loggedIn(), LEGACY_VIEW)
    expect(canReport(state)).toBe(false)
    state = pickSet(state, 'set-2', 2)
    expect(state.selection.setId).toBe('set-2')
    expect(legacySelection(state)).toBeNull() // 半截选择不发
    state = pickPosition(state, 'item-3', '布帘')
    expect(legacySelection(state)).toEqual({ setId: 'set-2', orderItemId: 'item-3' })
  })

  test('红证对照：把 selection 预置成第一套就是本判据要拦的形态', () => {
    const bad = { ...applyScan(loggedIn(), LEGACY_VIEW), selection: { setId: 'set-1', orderItemId: null } }
    expect(bad.selection.setId).toBe('set-1')
    expect(applyScan(loggedIn(), LEGACY_VIEW).selection.setId).toBeNull()
  })
})

describe('② 工序未确定 ⇒ 不得出报工按钮', () => {
  test('operation 为 null ⇒ canReport false', () => {
    const state = applyScan(loggedIn(), { ...MAIN_VIEW, operation: null })
    expect(canReport(state)).toBe(false)
  })

  test('有工序 ⇒ canReport true（对照，证明上一条不是恒 false）', () => {
    const state = applyScan(loggedIn(), MAIN_VIEW)
    expect(canReport(state)).toBe(true)
  })

  test('质检工序没有报工动作（判定即报工）', () => {
    expect(isQualityOperation({ operation_id: 'x', logical_name: '质检' })).toBe(true)
    const state = applyScan(loggedIn(), {
      ...MAIN_VIEW,
      operation: { operation_id: 'q-1', logical_name: '质检', qty: 1, unit: '套' },
    })
    expect(canReport(state)).toBe(false)
  })
})

describe('③ 未登录 ⇒ 不得出报工按钮', () => {
  test('worker 为 null ⇒ canReport false（哪怕一屏看起来完全可报）', () => {
    const state = { ...applyScan(initialState(WORKER), MAIN_VIEW), worker: null }
    expect(canReport(state)).toBe(false)
  })

  test('未登录时 applyScan 不给可报工状态（回落未登录 + 人话）', () => {
    const next = applyScan(initialState(null), MAIN_VIEW)
    expect(next.worker).toBeNull()
    expect(next.error).toContain('登录')
    expect(canReport(next)).toBe(false)
  })
})

describe('④ 回执只认服务端（前端不猜下一道）', () => {
  test('有 next_operation ⇒ 文案写那一道', () => {
    expect(receiptLine({ nextOperation: { operation_id: 'op-2', logical_name: '定型' } })).toContain('定型')
  })

  test('没有 next_operation 且本套未完成 ⇒ 只说「已报工」，**不编下一道**', () => {
    const line = receiptLine({ nextOperation: null, setCompleted: false })
    expect(line).toBe('已报工')
    expect(line).not.toContain('下一道')
  })

  test('set_completed ⇒ 本套已完成', () => {
    expect(receiptLine({ nextOperation: null, setCompleted: true })).toContain('本套')
  })

  test('applyReceipt 之后按钮消失（没有下一道就不可再报）', () => {
    const before = applyScan(loggedIn(), MAIN_VIEW)
    const after = applyReceipt(before, { nextOperation: null, setCompleted: true })
    expect(after.receipt).toContain('本套')
    expect(canReport(after)).toBe(false)
    expect(after.submitting).toBe(false)
  })
})

describe('状态机细节（线上事故回归）', () => {
  test('换一屏 ⇒ submitting / batchNo 归零（上一笔的「提交中」不带到下一屏）', () => {
    const dirty: ReportState = { ...loggedIn(), submitting: true, batchNo: 'B-1' }
    const next = applyScan(dirty, MAIN_VIEW)
    expect(next.submitting).toBe(false)
    expect(next.batchNo).toBeNull()
  })

  test('默认三态 = 正常（请求体不带 work_type），闭词表与后端同名', () => {
    expect(DEFAULT_WORK_TYPE).toBe('normal')
    expect(WORK_TYPES).toEqual(['normal', 'rework', 'scrap'])
  })

  test('缺值一律 `—`（不印 0、不印 undefined）', () => {
    expect(qtyText(null)).toBe(MISSING)
    expect(qtyText(undefined)).toBe(MISSING)
    expect(qtyText(0)).toBe('0')
    expect(progressText({})).toBe(MISSING)
    expect(kindText({})).toBe(MISSING)
    expect(operationName(null)).toBe(MISSING)
  })

  test('标题：第 N 套 · 部位；无 view ⇒ 扫码报工', () => {
    expect(titleText(MAIN_VIEW)).toBe('第 2 套 · 布帘')
    expect(titleText(null)).toBe('扫码报工')
  })
})

describe('码解析三形态（纸上三种都认）', () => {
  test('短链 / 带 t 参数 / 裸码', () => {
    expect(tokensFromScanResult('https://app.migaozn.com/s/ab12cd34')).toBe('ab12cd34')
    expect(tokensFromScanResult('https://app.migaozn.com/w/?t=tok-9')).toBe('tok-9')
    expect(tokensFromScanResult('ab12cd34')).toBe('ab12cd34')
    expect(tokensFromScanResult('JG-20260901-001')).toBe('JG-20260901-001')
    expect(tokensFromScanResult('')).toBe('')
    expect(tokensFromScanResult(undefined)).toBe('')
  })

  test('红证对照：解析不出 token 时不得回空串以外的东西（不编码）', () => {
    expect(tokensFromScanResult('   ')).toBe('')
  })
})
