// case_ids: MC-222
/**
 * P2b 三个**读面**的判据（issue #7813；实现 = `src/utils/workerReadFaces.ts`）。
 *
 * 这一层钉的是 `/w/` 文件头那**四条硬约束**在读面上的形态 —— 不是「页面长什么样」，
 * 是「谁可以在哪一屏下结论」。全部是纯函数判据：不渲染、不联网、不需要 DOM。
 *
 * | # | 硬约束 | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|---|
 * | ① | 旧码 ⇒ 进 select 态，**绝不默认取第 1 套** | `applyReadScan` 对服务端降级形态 ⇒ `mode='select'` 且两截全空 | 变异体把第 1 套预置进 `selection` ⇒ 下面的不变式当场判红 |
 * | ② | 工序未确定 ⇒ **不得出现报工按钮** | `operationNotReadyHint` 给一句「去报工页定工序」；`canReport`（报工页同一份判据）为 false | 让 `operationNotReadyHint` 在 operation 为空时返回 null ⇒ 红 |
 * | ③ | 未登录 ⇒ **不得出现报工按钮** | `readFaceInitial(null).mode === 'unauthorized'`；未登录时 `applyReadScan` 拒收任何一屏 | 让 `readFaceInitial(null)` 回 'scan' ⇒ 红 |
 * | ④ | 屏上只认服务端给的结论（回执形态） | `qualityStateText`：读失败说「未读到」、**绝不说「正常」**；`reportHandoffUrl` 只交码 | 把 `error` 分支并进「正常」/ 把套号塞进交接参数 ⇒ 红 |
 *
 * 另钉两件事（越界即红）：
 * - **缺值不编造**：裁高的缺值 / 精裁清单的 `panel_*` 缺失 ⇒ `—`（不显示 0 / 1）；
 * - **只读**：本模块不导出任何写函数（写入口只在报工页），由页面判据再扫一次源码。
 */
import {
  CUT_PLAN_EMPTY_HINT,
  QUALITY_EMPTY_HINT,
  QUALITY_NOT_ENABLED_HINT,
  READ_ONLY_NOTICE,
  applyReadScan,
  cutBatchBlockedText,
  cutHeightDetailRows,
  cutHeightPosition,
  cutHeightText,
  cutHitRows,
  cutPlanRows,
  operationNotReadyHint,
  pieceText,
  qualityRecordRows,
  qualityStateText,
  readFaceInitial,
  readPickPosition,
  readPickSet,
  readSelection,
  readSetChoices,
  reportHandoffUrl,
  scannedPositionIndex,
  unresolvedRows,
  type CutHeightData,
  type ReadFaceState,
} from '../src/utils/workerReadFaces'
import { canReport, initialState, signedIn, type ReportView } from '../src/utils/reportState'

const WORKER = { worker_name: '张师傅', worker_no: 'W-001' }

/** 服务端降级响应的**真形态**（`ProductionScanService#degradedView`）。 */
const LEGACY_VIEW: ReportView = {
  granularity: 'order',
  set_no: null,
  operation: null,
  needs_selection: ['set', 'position'],
  selections: [
    {
      set_id: 'set-1',
      set_no: 1,
      positions: [{ order_item_id: 'item-1', position_name: '布帘', position_kind: '布帘' }],
    },
    {
      set_id: 'set-2',
      set_no: 2,
      positions: [{ order_item_id: 'item-3', position_name: '纱帘', position_kind: '纱帘' }],
    },
  ],
}

/** 新码一屏（有工序、有部位）。 */
const MAIN_VIEW: ReportView = {
  granularity: 'set_position',
  set_no: 2,
  position: { order_item_id: 'item-1', position_name: '布帘', position_kind: '布帘' },
  operation: { operation_id: 'op-1', logical_name: '车被', qty: 11, unit: '米' },
  alternatives: [],
  needs_selection: [],
  set_progress: { done: 1, total: 3 },
}

const loggedIn = (): ReadFaceState => readFaceInitial(WORKER)

describe('① 旧码 ⇒ select 态，绝不默认取第 1 套', () => {
  test('服务端降级形态 ⇒ select，且套 / 部位两截都是空', () => {
    const next = applyReadScan(loggedIn(), LEGACY_VIEW)
    expect(next.mode).toBe('select')
    expect(next.selection).toEqual({ setId: null, orderItemId: null })
    expect(next.notice).toContain('旧码')
  })

  test('半截选择不成立（选完套还没选部位 ⇒ 不发请求）', () => {
    let state = applyReadScan(loggedIn(), LEGACY_VIEW)
    expect(readSelection(state)).toBeNull()
    state = readPickSet(state, 'set-2', 2)
    expect(readSelection(state)).toBeNull()
    state = readPickPosition(state, 'item-3', '纱帘')
    expect(readSelection(state)).toEqual({ setId: 'set-2', orderItemId: 'item-3' })
  })

  test('候选套清单来自服务端的 selections（标记串取不出套号）', () => {
    const state = applyReadScan(loggedIn(), LEGACY_VIEW)
    expect(readSetChoices(state).map((set) => set.set_id)).toEqual(['set-1', 'set-2'])
    expect(readSetChoices({ ...state, view: { needs_selection: ['set', 'position'] } })).toEqual([])
  })

  test('红证：变异体「默认取第 1 套」被这条不变式抓住', () => {
    // 变异体 = 改前最容易被写成的形态：解析完顺手把第 1 套塞进 selection
    const mutant = (state: ReadFaceState, view: ReportView): ReadFaceState => {
      const next = applyReadScan(state, view)
      return { ...next, selection: { setId: readSetChoices(next)[0]?.set_id ?? null, orderItemId: null } }
    }
    expect(mutant(loggedIn(), LEGACY_VIEW).selection.setId).toBe('set-1')
    // 不变式：任何「解析完成」的状态都必须是两截全空
    expect(applyReadScan(loggedIn(), LEGACY_VIEW).selection).not.toEqual(
      mutant(loggedIn(), LEGACY_VIEW).selection,
    )
  })
})

describe('② 工序未确定 ⇒ 读面不给动作，只说明为什么', () => {
  test('operation 为 null ⇒ 明说「这道工序还没定」并指到报工页', () => {
    const hint = operationNotReadyHint({ ...MAIN_VIEW, operation: null })
    expect(hint).toContain('这道工序还没定')
    expect(hint).toContain('报工页')
  })

  test('有工序 ⇒ 不出现这句提示（对照，证明上一条不是恒真）', () => {
    expect(operationNotReadyHint(MAIN_VIEW)).toBeNull()
  })

  test('同一份判据在报工面也成立：工序未确定 ⇒ canReport false', () => {
    const state = { ...signedIn(initialState(WORKER), WORKER) }
    expect(canReport({ ...state, view: { ...MAIN_VIEW, operation: null } })).toBe(false)
    expect(canReport({ ...state, view: MAIN_VIEW })).toBe(true)
  })

  test('红证：把提示改成 null（等于让读面「看起来一切正常」）⇒ 判据红', () => {
    const mutant = (): null => null
    expect(operationNotReadyHint({ ...MAIN_VIEW, operation: null })).not.toBe(mutant())
  })
})

describe('③ 未登录 ⇒ 读面没有任何动作', () => {
  test('没有工人身份 ⇒ unauthorized', () => {
    expect(readFaceInitial(null).mode).toBe('unauthorized')
    expect(readFaceInitial(WORKER).mode).toBe('scan')
  })

  test('未登录时即使拿到一屏也不接受（停在 unauthorized + 一句话）', () => {
    const next = applyReadScan(readFaceInitial(null), MAIN_VIEW)
    expect(next.mode).toBe('unauthorized')
    expect(next.view).toBeNull()
    expect(next.error).toContain('登录')
  })

  test('红证：把未登录的初值改成可操作态 ⇒ 判据红', () => {
    const mutant = readFaceInitial(null)
    expect(mutant.mode).not.toBe('scan')
  })
})

describe('④ 屏上只认服务端：质检状态词 / 交接参数', () => {
  test('读取中 / 未读到 / 正常 / 待复检 / 已判报废 五态分开', () => {
    expect(qualityStateText({ loading: true, latest: null, records: [] })).toBe('读取中')
    expect(qualityStateText({ loading: false, latest: null, records: [], error: '读不到' })).toBe('未读到')
    expect(qualityStateText({ loading: false, latest: null, records: [] })).toBe('正常')
    expect(qualityStateText({ loading: false, latest: { result: 'rework' }, records: [{ result: 'rework' }] })).toBe('待复检')
    expect(qualityStateText({ loading: false, latest: { result: 'scrap' }, records: [] })).toBe('已判报废')
  })

  test('🔴 读失败 ⇒ 绝不说「正常」（那是在替服务端断言这一件没问题）', () => {
    const text = qualityStateText({ loading: false, latest: null, records: [], error: '网络超时' })
    expect(text).toBe('未读到')
    expect(text).not.toContain('正常')
  })

  test('屏上不出现「合格」（用户 2026-10-25 裁定：默认没问题，不摆合格这个选项）', () => {
    const texts = [
      qualityStateText({ loading: false, latest: null, records: [] }),
      qualityStateText({ loading: false, latest: { result: 'pass' }, records: [] }),
      QUALITY_EMPTY_HINT,
    ]
    expect(texts.join('')).not.toContain('合格')
  })

  test('记录行：字典项中文名 + 自由补充 / 检验人（缺就缺，不摆空占位）', () => {
    const rows = qualityRecordRows([
      { result: 'rework', reason_label: '布面污渍', reason: '左下角', inspector_name: '李四', inspected_at: '2026-10-30 09:12' },
      { result: 'scrap', reason: '', inspector_name: '', inspected_at: '' },
    ])
    expect(rows[0].reason).toBe('布面污渍（左下角）')
    expect(rows[0].inspector).toBe('李四')
    expect(rows[1].reason).toBeNull()
    expect(rows[1].inspector).toBeNull()
  })

  test('红证：把读失败并进「正常」的变异体 ⇒ 上面那条当场红', () => {
    const mutant = (quality: { loading: boolean; latest?: any; records?: any[]; error?: string | null }): string =>
      quality.records?.length === 0 ? '正常' : '待复检'
    expect(mutant({ loading: false, latest: null, records: [], error: '网络超时' })).toBe('正常')
    expect(qualityStateText({ loading: false, latest: null, records: [], error: '网络超时' })).not.toBe('正常')
  })

  test('去报工只交这次扫到的码（不猜套 / 不猜工序）', () => {
    const url = reportHandoffUrl('/pages/worker/report/index', ' AB-12 ')
    expect(url).toBe('/pages/worker/report/index?t=AB-12')
    expect(url).not.toContain('set_id')
    expect(url).not.toContain('operation_id')
    expect(reportHandoffUrl('/pages/worker/report/index', '')).toBe('/pages/worker/report/index')
  })
})

describe('裁高计算：只格式化，不重算、不编造缺值', () => {
  const DATA: CutHeightData = {
    order: { processing_order_no: 'JG-001', set_no: 2, set_count: 3 },
    positions: [
      { order_item_id: 'item-1', position_name: '布帘', scanned: false, cutting_height: 2.9, base: 2.7, rounding: { mode: 'half_up', digits: 3 } },
      {
        order_item_id: 'item-2',
        position_name: '纱帘',
        scanned: true,
        base: 2.7,
        cutting_height: 3.028,
        rounding: { mode: 'half_up', digits: 3 },
        hits: [
          { key: 'hem', name: '卷边', value: 0.2, direction: 'add' },
          { key: 'shrink', name: '缩水', value: 0.128, direction: 'add' },
        ],
        misses: [{ name: '花距', reason: 'unresolved' }],
        missing: [],
      },
      { order_item_id: 'item-3', position_name: '帘头', cutting_height: null, base: null, missing: ['finished_height'], missing_reason: '缺少 finished_height，无法计算裁剪高度' },
    ],
  }

  test('默认选服务端标记 scanned 的那一件（不默认第 1 件）', () => {
    expect(scannedPositionIndex(DATA)).toBe(1)
    expect(cutHeightPosition(DATA, scannedPositionIndex(DATA))?.order_item_id).toBe('item-2')
  })

  test('大字口径与 /w/ 机台屏同一句（三位小数 = mm）', () => {
    expect(cutHeightText(cutHeightPosition(DATA, 1))).toBe('请在机器屏输入 3.028 米')
  })

  test('缺必需取值 ⇒ 明说缺什么，**不猜数**（不显示 0 / 不显示前一件的值）', () => {
    const text = cutHeightText(cutHeightPosition(DATA, 2))
    expect(text).toContain('缺少finished_height')
    expect(text).toContain('算不出裁剪高度')
    expect(text).not.toContain('0.000')
  })

  test('命中项带方向；未配置取值单独列出（不计入、也不算 0）', () => {
    const position = cutHeightPosition(DATA, 1)
    expect(cutHitRows(position).map((row) => `${row.direction}${row.value}`)).toEqual(['+0.200', '+0.128'])
    expect(unresolvedRows(position)).toEqual(['花距'])
  })

  test('取整位数尊重服务端（0 位也要认 —— 不能被当成缺值退回 3 位）', () => {
    const zero = { order_item_id: 'i', base: 2, cutting_height: 3, rounding: { mode: 'half_up', digits: 0 } }
    expect(cutHeightText(zero)).toBe('请在机器屏输入 3 米')
  })

  test('明细行缺值 ⇒ —（不摆 0）', () => {
    const rows = cutHeightDetailRows(cutHeightPosition(DATA, 2))
    expect(rows.find((row) => row.label === '成品高')?.value).toBe('—')
    expect(rows.find((row) => row.label === '裁高（系统算）')?.value).toBe('—')
  })

  test('批次：要批次却没指派 ⇒ 只指路到报工页（本面不填批次）', () => {
    expect(cutBatchBlockedText({ batch_required: true, batch_no: null })).toContain('报工页')
    expect(cutBatchBlockedText({ batch_required: true, batch_no: 'PC-01' })).toBeNull()
    expect(cutBatchBlockedText({ batch_required: false, batch_no: null })).toBeNull()
  })
})

describe('精裁清单：缺值不渲染假数据；缺整块 ⇒ 具名空态', () => {
  const VIEW: ReportView = {
    ...MAIN_VIEW,
    set_overview: {
      set_no: '2',
      cut_plan: [
        {
          order_item_id: 'item-1',
          position_name: '布帘',
          component: '左片',
          panel_length_m: 6.15,
          panel_count: 2,
          fabric_meters: 12.3,
          batch_no: 'PC-01',
          batch_meters: 12.3,
        },
        { order_item_id: 'item-2', position_name: '纱帘', panel_length_m: null, panel_count: null, fabric_meters: null },
        { order_item_id: 'item-3', position_name: '帘头', panel_length_m: 1.2, panel_count: 1, missing_reason: '缺用料米数' },
        { position_name: '没有行键的脏数据' },
      ],
    },
  }

  test('逐条格式化（裁多长 × 几片 / 部位·组件 / 用料 / 批次）；脏行不渲染', () => {
    const rows = cutPlanRows(VIEW)
    expect(rows).toHaveLength(3)
    expect(rows[0].size).toBe('裁 6.150 米 × 2 片')
    expect(rows[0].name).toBe('布帘 · 左片')
    expect(rows[0].meters).toBe('用料 12.300 米')
    expect(rows[0].batch).toBe('批次 PC-01 · 裁 12.300 米')
  })

  test('缺值 ⇒ —（不显示 0 / 1）；未指派批次 ⇒ 该格不渲染', () => {
    const rows = cutPlanRows(VIEW)
    expect(rows[1].size).toBe('裁 — × —')
    expect(rows[1].meters).toBe('用料 —')
    expect(rows[1].batch).toBeNull()
  })

  test('缺什么要看得见（missing_reason 原样上屏）', () => {
    expect(cutPlanRows(VIEW)[2].reason).toBe('缺用料米数')
  })

  test('cut_plan 缺失 / 空 ⇒ 空数组（页面据此出具名空态，不是空白）', () => {
    expect(cutPlanRows(MAIN_VIEW)).toEqual([])
    expect(cutPlanRows({ ...MAIN_VIEW, set_overview: { cut_plan: [] } })).toEqual([])
    expect(CUT_PLAN_EMPTY_HINT).toContain('没有精裁输出')
  })

  test('本件说法：第 N 套 · 部位（三个读面同一句）', () => {
    expect(pieceText(MAIN_VIEW)).toBe('第 2 套 · 布帘')
    expect(pieceText({ set_no: null })).toBe('第 — 套')
  })
})

describe('读面的公开面（越界即红）', () => {
  test('只读纪律写在屏上（工人知道这里不会记账）', () => {
    expect(READ_ONLY_NOTICE).toContain('只')
    expect(READ_ONLY_NOTICE).toContain('报工')
  })

  test('未开通质检面的话是**可行动**的（不责备、不摆内部标识）', () => {
    expect(QUALITY_NOT_ENABLED_HINT).toContain('管理员')
    expect(QUALITY_NOT_ENABLED_HINT).not.toContain('接口')
    expect(QUALITY_NOT_ENABLED_HINT).not.toContain('权限码')
  })
})
