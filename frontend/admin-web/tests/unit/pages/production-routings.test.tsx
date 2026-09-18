// case_ids: PP-014
// PP-014（issue #4307，前端半边；契约所有者 = 后端 4308）：工艺路线页 /production/routings ——
// ① 路线列表渲染真实序列（部位 × 工艺 → 每道工序的分组/单位/单价/必完）；
// ② 序列编辑：从**工序库**选工序 → 上移/下移/删除 → 保存（PUT /production/routings/{id}，
//    body {operations:[...]} 且顺序等于屏幕顺序）；
// ③ 保存被拒时**逐条**展示后端护栏理由（error_messages），不得只弹「保存失败」；空序列本地拦；
// ④ 缺口区两只清单（有工序没进路线 / 无路线的信号组合）——真值源下 4 道「待客户确认」工序；
// ⑤ 新建路线 / 新增工序（POST /production/operations）/ 信号映射增删改（POST|PUT|DELETE）；
// ⑥ 任一只读端点失败不得白屏，失败处给可读提示。
// 反 placeholder：断言落**真实数据行**与**请求体**（新增/删除/顺序），不断言「页面存在」。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockGetRoutings = vi.fn()
const mockUpdateRoutingSequence = vi.fn()
const mockCreateRouting = vi.fn()
const mockGetOperationsCatalog = vi.fn()
const mockCreateOperation = vi.fn()
const mockGetRoutingGaps = vi.fn()
const mockGetRouteSignals = vi.fn()
const mockCreateRouteSignal = vi.fn()
const mockUpdateRouteSignal = vi.fn()
const mockDeleteRouteSignal = vi.fn()

vi.mock('@/lib/api', () => ({
  productionApi: {
    getRoutings: (...args: unknown[]) => mockGetRoutings(...args),
    updateRoutingSequence: (...args: unknown[]) => mockUpdateRoutingSequence(...args),
    createRouting: (...args: unknown[]) => mockCreateRouting(...args),
    getOperationsCatalog: (...args: unknown[]) => mockGetOperationsCatalog(...args),
    createOperation: (...args: unknown[]) => mockCreateOperation(...args),
    getRoutingGaps: (...args: unknown[]) => mockGetRoutingGaps(...args),
    getRouteSignals: (...args: unknown[]) => mockGetRouteSignals(...args),
    createRouteSignal: (...args: unknown[]) => mockCreateRouteSignal(...args),
    updateRouteSignal: (...args: unknown[]) => mockUpdateRouteSignal(...args),
    deleteRouteSignal: (...args: unknown[]) => mockDeleteRouteSignal(...args),
  },
}))

import RoutingsPage from '@/app/(dashboard)/production/routings/page'

const ok = (data: unknown) => ({ data: { success: true, data } })

/** 库口径：精裁-布 在库里是**必完**（完工门槛），编辑时该标记必须仍然可见 */
const CATALOG = {
  total: 3,
  groups: [
    {
      group: '裁剪',
      operations: [
        { id: 'op-v54-01', name: '精裁-布', group: '裁剪', position: '布帘', unit: '套', unit_price: 8.5, is_must_finish: true, is_start_marker: true },
        { id: 'op-v54-02', name: '裁剪-布', group: '裁剪', position: '布帘', unit: '套', unit_price: 7, is_must_finish: false, is_start_marker: false },
      ],
    },
    {
      group: '车位',
      operations: [
        { id: 'op-v54-03', name: '韩褶-布', group: '车位', position: '布帘', unit: '米', unit_price: 1.2, is_must_finish: false, is_start_marker: false },
      ],
    },
  ],
}

/**
 * 缺口真值（issue #4308 P4）：`裁剪-布 / 裁剪-纱 / 质检 / 腰靠垫` 是「有工序、有价、有意不消费
 * （待客户确认）」—— 双向可红：少一道 / 多一道都要能看出来，故此处给足 4 道。
 */
const GAPS = {
  unrouted_operations: [
    { name: '裁剪-布', group_name: '裁剪', unit: '套', unit_price: 7 },
    { name: '裁剪-纱', group_name: '裁剪', unit: '套', unit_price: 6 },
    { name: '质检', group_name: '后道', unit: '件', unit_price: 1.5 },
    { name: '腰靠垫', group_name: '其他', unit: '个', unit_price: 3 },
  ],
  signal_keys_without_route: [{ curtain_type: '罗马帘', craft: '韩褶' }],
}

const ROUTINGS = {
  total: 2,
  routings: [
    {
      id: 11,
      curtain_type: '布帘',
      craft: '韩褶',
      operation_count: 3,
      operations: [
        { seq: 1, operation: '精裁-布', group: '裁剪', unit: '套', unit_price: 8.5, is_must_finish: true, is_start_marker: true },
        { seq: 2, operation: '韩褶-布', group: '车位', unit: '米', unit_price: 1.2, is_must_finish: false, is_start_marker: false },
        { seq: 3, operation: '外帘装袋', group: '后道', unit: '件', unit_price: 0.4, is_must_finish: true, is_start_marker: false },
      ],
    },
    {
      id: 12,
      curtain_type: '纱帘',
      craft: '韩褶',
      operation_count: 1,
      operations: [
        { seq: 1, operation: '精裁-纱', group: '裁剪', unit: '套', unit_price: 6, is_must_finish: false, is_start_marker: false },
      ],
    },
  ],
}

const SIGNALS = {
  total: 2,
  signals: [
    { id: 31, signal: '帘头', curtain_type: '帘头', craft: '韩褶' },
    { id: 32, signal: '纱', curtain_type: '纱帘', craft: '韩褶' },
  ],
}

/** 后端护栏失败响应体（axios 形态：理由在 error.response.data） */
const guardError = (errorMessages: string[]) => ({
  response: { data: { success: false, error_messages: errorMessages } },
  message: 'Request failed with status code 400',
})

describe('工艺路线页 /production/routings', () => {
  beforeEach(() => {
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS))
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG))
    mockGetRoutingGaps.mockReset().mockResolvedValue(ok(GAPS))
    mockGetRouteSignals.mockReset().mockResolvedValue(ok(SIGNALS))
    mockUpdateRoutingSequence.mockReset().mockResolvedValue(ok({ id: 11 }))
    mockCreateRouting.mockReset().mockResolvedValue(ok({ id: 13 }))
    mockCreateOperation.mockReset().mockResolvedValue(ok({ id: 'op-new' }))
    mockCreateRouteSignal.mockReset().mockResolvedValue(ok({ id: 33 }))
    mockUpdateRouteSignal.mockReset().mockResolvedValue(ok({ id: 31 }))
    mockDeleteRouteSignal.mockReset().mockResolvedValue(ok(undefined))
  })

  it('渲染真实路线数据：路线数 + 部位×工艺标题 + 每道工序（含单位/单价/必完标记）', async () => {
    render(<RoutingsPage />)

    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))
    const box = screen.getByTestId('routing-布帘×韩褶')
    expect(box).toHaveTextContent('3 道工序')
    expect(within(box).getByTestId('routing-step-布帘×韩褶-1')).toHaveTextContent('精裁-布')
    expect(within(box).getByTestId('routing-step-布帘×韩褶-1')).toHaveTextContent('¥8.50')
    expect(within(box).getByTestId('routing-step-布帘×韩褶-2')).toHaveTextContent('¥1.20')
    // is_must_finish 的工序必须带「必完」标记（完工门槛不可丢）
    expect(within(box).getByTestId('routing-step-布帘×韩褶-3')).toHaveTextContent('必完')
    expect(screen.getByTestId('routing-step-纱帘×韩褶-1')).toHaveTextContent('精裁-纱')
  })

  it('缺口区：4 道未进路线的工序逐条可见 + 无路线的信号组合（罗马帘×韩褶）', async () => {
    render(<RoutingsPage />)

    await waitFor(() => expect(screen.getByTestId('routings-gap-unrouted-count')).toHaveTextContent('4'))
    for (const name of ['裁剪-布', '裁剪-纱', '质检', '腰靠垫']) {
      expect(screen.getByTestId(`routings-gap-unrouted-${name}`)).toHaveTextContent(name)
    }
    expect(screen.getByTestId('routings-gap-unrouted-裁剪-布')).toHaveTextContent('¥7.00')
    // 无路线的信号组合：罗马帘目前会静默回落到默认路线，必须可见
    expect(screen.getByTestId('routings-gap-signal-罗马帘-韩褶')).toHaveTextContent('罗马帘 × 韩褶')
  })

  it('序列编辑：从工序库添加 → 保存 → PUT 提交的 operations 顺序等于屏幕顺序', async () => {
    render(<RoutingsPage />)
    await waitFor(() => expect(screen.getByTestId('routing-edit-布帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))
    // 既有序列进入编辑态，库口径的必完标记照旧可见
    expect(screen.getByTestId('routing-draft-step-布帘×韩褶-1')).toHaveTextContent('精裁-布')
    expect(screen.getByTestId('routing-draft-step-布帘×韩褶-1')).toHaveTextContent('必完')

    await userEvent.selectOptions(screen.getByTestId('routing-add-select-布帘×韩褶'), '裁剪-布')
    await userEvent.click(screen.getByTestId('routing-add-布帘×韩褶'))
    await userEvent.click(screen.getByTestId('routing-save-布帘×韩褶'))

    await waitFor(() =>
      expect(mockUpdateRoutingSequence).toHaveBeenCalledWith(11, {
        operations: ['精裁-布', '韩褶-布', '外帘装袋', '裁剪-布'],
      }),
    )
    // 保存成功要重新拉取（结果可见，不靠本地猜测）
    await waitFor(() => expect(mockGetRoutings).toHaveBeenCalledTimes(2))
    // 保存后退出编辑态
    await waitFor(() => expect(screen.queryByTestId('routing-save-布帘×韩褶')).not.toBeInTheDocument())
  })

  it('序列编辑：下移改变顺序后保存，PUT 请求体的顺序随之变化', async () => {
    render(<RoutingsPage />)
    await waitFor(() => expect(screen.getByTestId('routing-edit-布帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))
    await userEvent.click(screen.getByTestId('routing-draft-down-布帘×韩褶-1'))
    // 屏幕上第 1 行已换成原第 2 道
    expect(screen.getByTestId('routing-draft-name-布帘×韩褶-1')).toHaveTextContent('韩褶-布')
    await userEvent.click(screen.getByTestId('routing-save-布帘×韩褶'))

    await waitFor(() =>
      expect(mockUpdateRoutingSequence).toHaveBeenCalledWith(11, {
        operations: ['韩褶-布', '精裁-布', '外帘装袋'],
      }),
    )
  })

  it('序列编辑：删除一道后保存，被删工序不再出现在请求体里', async () => {
    render(<RoutingsPage />)
    await waitFor(() => expect(screen.getByTestId('routing-edit-布帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))
    await userEvent.click(screen.getByTestId('routing-draft-remove-布帘×韩褶-2'))
    expect(screen.queryByTestId('routing-draft-step-布帘×韩褶-3')).not.toBeInTheDocument()
    await userEvent.click(screen.getByTestId('routing-save-布帘×韩褶'))

    await waitFor(() =>
      expect(mockUpdateRoutingSequence).toHaveBeenCalledWith(11, {
        operations: ['精裁-布', '外帘装袋'],
      }),
    )
  })

  it('空序列：本地拦住不发请求，并说明为什么不能空', async () => {
    render(<RoutingsPage />)
    await waitFor(() => expect(screen.getByTestId('routing-edit-纱帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-纱帘×韩褶'))
    await userEvent.click(screen.getByTestId('routing-draft-remove-纱帘×韩褶-1'))
    await userEvent.click(screen.getByTestId('routing-save-纱帘×韩褶'))

    await waitFor(() => expect(screen.getByTestId('routing-error-纱帘×韩褶')).toBeInTheDocument())
    expect(screen.getByTestId('routing-error-item-0')).toHaveTextContent('序列不能为空')
    expect(mockUpdateRoutingSequence).not.toHaveBeenCalled()
    // 失败不刷新（避免把失败伪装成成功）
    expect(mockGetRoutings).toHaveBeenCalledTimes(1)
  })

  it('保存被拒（护栏）：后端每条理由**逐条**展示，不合并成一句「保存失败」', async () => {
    mockUpdateRoutingSequence.mockRejectedValueOnce(
      guardError([
        '工序「罗马帘-打孔」不在工序库中',
        '工序「裁剪-布」在序列中重复出现 2 次',
        '路线至少要有一道必完工序（当前 0 道）',
      ]),
    )
    render(<RoutingsPage />)
    await waitFor(() => expect(screen.getByTestId('routing-edit-布帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))
    await userEvent.click(screen.getByTestId('routing-save-布帘×韩褶'))

    await waitFor(() => expect(screen.getByTestId('routing-error-布帘×韩褶')).toBeInTheDocument())
    expect(screen.getByTestId('routing-error-item-0')).toHaveTextContent('工序不存在：工序「罗马帘-打孔」不在工序库中')
    expect(screen.getByTestId('routing-error-item-1')).toHaveTextContent('工序重复：')
    expect(screen.getByTestId('routing-error-item-2')).toHaveTextContent('缺少必完工序：')
    // 三条理由各占一行（不是一句通用文案）
    expect(within(screen.getByTestId('routing-error-布帘×韩褶')).getAllByTestId(/^routing-error-item-/)).toHaveLength(3)
    // 失败后不静默退出编辑态，也不刷新把错误冲掉
    expect(screen.getByTestId('routing-save-布帘×韩褶')).toBeInTheDocument()
    expect(mockGetRoutings).toHaveBeenCalledTimes(1)
  })

  it('保存被拒（单条 error 形态兼容）：理由仍逐条可读', async () => {
    mockUpdateRoutingSequence.mockRejectedValueOnce({
      response: { data: { success: false, error: '路线至少要有一道必完工序' } },
    })
    render(<RoutingsPage />)
    await waitFor(() => expect(screen.getByTestId('routing-edit-布帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))
    await userEvent.click(screen.getByTestId('routing-save-布帘×韩褶'))

    await waitFor(() =>
      expect(screen.getByTestId('routing-error-item-0')).toHaveTextContent('缺少必完工序：路线至少要有一道必完工序'),
    )
  })

  it('新增工序：提交名称/分组/单位/单价（POST /production/operations）并刷新工序库', async () => {
    render(<RoutingsPage />)
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))

    await userEvent.click(screen.getByTestId('routings-new-operation'))
    await userEvent.type(screen.getByTestId('routings-create-op-name'), '罗马帘-穿杆')
    await userEvent.type(screen.getByTestId('routings-create-op-group_name'), '车位')
    await userEvent.type(screen.getByTestId('routings-create-op-unit'), '套')
    await userEvent.type(screen.getByTestId('routings-create-op-unit_price'), '4.5')
    await userEvent.click(screen.getByTestId('routings-create-operation-submit'))

    await waitFor(() =>
      expect(mockCreateOperation).toHaveBeenCalledWith({
        name: '罗马帘-穿杆',
        group_name: '车位',
        unit: '套',
        unit_price: 4.5,
      }),
    )
    await waitFor(() => expect(mockGetOperationsCatalog).toHaveBeenCalledTimes(2))
  })

  it('新建路线：部位 + 工艺 → POST /production/routings，初版序列为空待排', async () => {
    render(<RoutingsPage />)
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))

    await userEvent.click(screen.getByTestId('routings-new-route'))
    await userEvent.type(screen.getByTestId('routings-create-curtain-type'), '罗马帘')
    await userEvent.type(screen.getByTestId('routings-create-craft'), '韩褶')
    await userEvent.click(screen.getByTestId('routings-create-route-submit'))

    await waitFor(() =>
      expect(mockCreateRouting).toHaveBeenCalledWith({ curtain_type: '罗马帘', craft: '韩褶', operations: [] }),
    )
    await waitFor(() => expect(mockGetRoutings).toHaveBeenCalledTimes(2))
  })

  it('信号映射：列表渲染 + 新增走 POST /production/route-signals', async () => {
    render(<RoutingsPage />)
    await waitFor(() => expect(screen.getByTestId('route-signal-31')).toHaveTextContent('帘头'))

    await userEvent.click(screen.getByTestId('route-signal-new'))
    await userEvent.type(screen.getByTestId('route-signal-signal'), '罗马帘')
    await userEvent.type(screen.getByTestId('route-signal-curtain_type'), '罗马帘')
    await userEvent.type(screen.getByTestId('route-signal-craft'), '韩褶')
    await userEvent.click(screen.getByTestId('route-signal-submit'))

    await waitFor(() =>
      expect(mockCreateRouteSignal).toHaveBeenCalledWith({ signal: '罗马帘', curtain_type: '罗马帘', craft: '韩褶' }),
    )
  })

  it('信号映射：编辑走 PUT /{id}、删除走 DELETE /{id}（二次确认后）', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<RoutingsPage />)
    await waitFor(() => expect(screen.getByTestId('route-signal-32')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('route-signal-edit-32'))
    const curtainInput = screen.getByTestId('route-signal-curtain_type')
    await userEvent.clear(curtainInput)
    await userEvent.type(curtainInput, '纱帘(改)')
    await userEvent.click(screen.getByTestId('route-signal-submit'))
    await waitFor(() =>
      expect(mockUpdateRouteSignal).toHaveBeenCalledWith(32, {
        signal: '纱',
        curtain_type: '纱帘(改)',
        craft: '韩褶',
      }),
    )

    await userEvent.click(screen.getByTestId('route-signal-delete-31'))
    await waitFor(() => expect(mockDeleteRouteSignal).toHaveBeenCalledWith(31))
    expect(confirmSpy).toHaveBeenCalled()
    confirmSpy.mockRestore()
  })

  it('路线列表加载失败：错误提示 + 重试（不白屏）', async () => {
    // 首次失败、重试成功：`mockReset()` 会清掉 beforeEach 的默认实现 ⇒ 必须重新给成功态，
    // 否则重试拿到 undefined（表现成「一直加载中」），红的是测试自身而不是被测行为。
    mockGetRoutings.mockReset().mockRejectedValueOnce(new Error('500')).mockResolvedValue(ok(ROUTINGS))
    render(<RoutingsPage />)

    await waitFor(() => expect(screen.getByTestId('routings-error')).toHaveTextContent('工艺路线加载失败'))
    await userEvent.click(screen.getByTestId('routings-retry'))
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))
    expect(screen.queryByTestId('routings-error')).not.toBeInTheDocument()
  })

  it('缺口/信号接口失败：页面不白屏，失败处给可读提示（路线列表照常渲染）', async () => {
    mockGetRoutingGaps.mockReset().mockRejectedValueOnce(new Error('500'))
    mockGetRouteSignals.mockReset().mockRejectedValueOnce(new Error('500'))
    render(<RoutingsPage />)

    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))
    expect(screen.getByTestId('routings-gaps-unavailable')).toHaveTextContent('缺口数据加载失败')
    expect(screen.getByTestId('route-signals-error')).toHaveTextContent('信号映射加载失败')
    expect(screen.getByTestId('routing-布帘×韩褶')).toBeInTheDocument()
  })
})
