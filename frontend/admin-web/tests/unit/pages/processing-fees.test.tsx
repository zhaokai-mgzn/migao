// case_ids: PG-040
// PG-040（issue #4386，前端半边）：加工费管理页 /production/processing-fees ——
// ① 组合列表渲染**真实数据**（选配特征 + 单价 元/米）；
// ② 新建：勾选加工项（**顺序无关**）→ 提交 `POST /processing-fee-combinations`；
// ③ 护栏理由**逐条**展示：按**真实信封** `error.details[].message` 读（不读不存在的 `error_messages`）；
//    同一组合重复定价（409）也要给出可读理由，不得只弹「保存失败」；
// ④ 空组合**本地先拦**（不发无效请求）；
// ⑤ 缺口区：未定价组合（`GET /processing-fee-gaps`）逐条可见；
// ⑥ 改单价走 `PUT /{id}`（body 只有 unit_price）、停用走 `DELETE /{id}`（二次确认后）；
// ⑦ 侧边栏入口（生产管理组）指向本页。
// 反 placeholder：断言落**真实数据行**与**请求体**，不断言「页面存在」。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockGetFeeCombinations = vi.fn()
const mockCreateFeeCombination = vi.fn()
const mockUpdateFeeCombination = vi.fn()
const mockDisableFeeCombination = vi.fn()
const mockGetFeeGaps = vi.fn()
const mockGetProcessingItems = vi.fn()

vi.mock('@/lib/api', () => ({
  productionApi: {
    getFeeCombinations: (...args: unknown[]) => mockGetFeeCombinations(...args),
    createFeeCombination: (...args: unknown[]) => mockCreateFeeCombination(...args),
    updateFeeCombination: (...args: unknown[]) => mockUpdateFeeCombination(...args),
    disableFeeCombination: (...args: unknown[]) => mockDisableFeeCombination(...args),
    getFeeGaps: (...args: unknown[]) => mockGetFeeGaps(...args),
  },
  // 勾选源 = **加工项目录**（与后端护栏的校验源同一张表：processing_items）
  processingItemApi: {
    getProcessingItems: (...args: unknown[]) => mockGetProcessingItems(...args),
  },
}))

import ProcessingFeesPage from '@/app/(dashboard)/production/processing-fees/page'

const ok = (data: unknown) => ({ data: { success: true, data } })

/**
 * 加工项目录（勾选源）。**故意**打乱顺序：页面必须把「已勾选集合」原样提交，
 * 归一化是**服务端**的事（前端不得自己拼 key —— 那会变成第二份口径）。
 */
const CATALOG = {
  total: 3,
  items: [
    { id: 'pi-1', name: '韩褶', category_id: 'cat-1', pricing_method: 'per_meter', unit_price: 1.2, unit: '米', status: 'active' },
    { id: 'pi-2', name: '打孔', category_id: 'cat-1', pricing_method: 'per_meter', unit_price: 8, unit: '米', status: 'active' },
    { id: 'pi-3', name: '定型', category_id: 'cat-1', pricing_method: 'per_meter', unit_price: 3, unit: '米', status: 'active' },
  ],
}

/** 库口径：韩褶+打孔 ¥12.00/米、韩褶+打孔+定型 ¥18.00/米（用户裁定的两个组合）。 */
const COMBINATIONS = {
  total: 2,
  combinations: [
    {
      id: 'fc-1',
      composition_key: '打孔+韩褶',
      items: ['韩褶', '打孔'],
      unit_price: 12,
      unit: '元/米',
      status: 'active',
      sort_order: 0,
      source: '实证',
    },
    {
      id: 'fc-2',
      composition_key: '定型+打孔+韩褶',
      items: ['韩褶', '打孔', '定型'],
      unit_price: 18,
      unit: '元/米',
      status: 'active',
      sort_order: 1,
      source: null,
    },
  ],
}

const GAPS = {
  unpriced_combinations: [
    {
      composition_key: '定型+韩褶',
      items: ['韩褶', '定型'],
      order_count: 3,
      note: '这个选配组合在订单里出现过，但「加工费组合」里没有它的价',
    },
  ],
  unpriced_combination_total: 1,
  scanned_order_items: 12,
  scanned_truncated: false,
}

beforeEach(() => {
  vi.clearAllMocks()
  mockGetFeeCombinations.mockResolvedValue(ok(COMBINATIONS))
  mockGetFeeGaps.mockResolvedValue(ok(GAPS))
  mockGetProcessingItems.mockResolvedValue(ok(CATALOG))
  mockCreateFeeCombination.mockResolvedValue(ok(COMBINATIONS.combinations[0]))
  mockUpdateFeeCombination.mockResolvedValue(ok(COMBINATIONS.combinations[0]))
  mockDisableFeeCombination.mockResolvedValue(ok({ id: 'fc-1', status: 'disabled' }))
})

describe('加工费管理页（issue #4386）', () => {
  it('组合列表渲染真实数据：选配特征 + 单价（元/米），不是「页面存在」', async () => {
    render(<ProcessingFeesPage />)
    await waitFor(() => expect(screen.getByTestId('fee-combinations-total')).toHaveTextContent('2'))

    const row = screen.getByTestId('fee-combination-fc-2')
    expect(within(row).getByTestId('fee-combination-items-fc-2')).toHaveTextContent('韩褶')
    expect(within(row).getByTestId('fee-combination-items-fc-2')).toHaveTextContent('打孔')
    expect(within(row).getByTestId('fee-combination-items-fc-2')).toHaveTextContent('定型')
    expect(within(row).getByTestId('fee-combination-price-fc-2')).toHaveTextContent('¥18.00')
    expect(within(row).getByTestId('fee-combination-price-fc-2')).toHaveTextContent('元/米')
  })

  it('新建：勾选加工项 + 单价 → POST /processing-fee-combinations（提交勾选集合，不自己拼 key）', async () => {
    render(<ProcessingFeesPage />)
    await waitFor(() => expect(screen.getByTestId('fee-combinations-total')).toHaveTextContent('2'))

    await userEvent.click(screen.getByTestId('fee-combination-new'))
    await userEvent.click(screen.getByTestId('fee-item-pick-定型'))
    await userEvent.click(screen.getByTestId('fee-item-pick-打孔'))
    await userEvent.type(screen.getByTestId('fee-combination-price-input'), '18')
    await userEvent.click(screen.getByTestId('fee-combination-submit'))

    await waitFor(() =>
      expect(mockCreateFeeCombination).toHaveBeenCalledWith({ items: ['定型', '打孔'], unit_price: 18 }),
    )
    await waitFor(() => expect(mockGetFeeCombinations).toHaveBeenCalledTimes(2))
  })

  it('新建弹窗只有一组底栏按钮：按钮走 Modal 的 footer（不叠加内置默认底栏「确定」）+ 文案不留字面 markdown 星号', async () => {
    render(<ProcessingFeesPage />)
    await waitFor(() => expect(screen.getByTestId('fee-combinations-total')).toHaveTextContent('2'))

    await userEvent.click(screen.getByTestId('fee-combination-new'))

    // ① 只有一组「取消」。形态判据：Modal 在 `footer === undefined` 时会渲染**内置默认底栏**
    //    （「取消」/「确定」，两个都只调 onClose）⇒ 消费者若把自绘按钮写进 children 且不传 footer，
    //    就会叠出两组按钮（issue #4415 的实测截图形态）。
    expect(screen.getAllByRole('button', { name: '取消' })).toHaveLength(1)
    // ② 内置默认底栏的「确定」只关窗、**不提交** ⇒ 它存在就等于「商家以为保存了，其实什么都没发生」。
    expect(screen.queryByRole('button', { name: '确定' })).toBeNull()
    // ③ 提示文案不得把 markdown 星号原样丢给商家（JSX 文本里的 `**一个价**` 会字面显示）。
    expect(screen.getByRole('dialog').textContent ?? '').not.toContain('**')

    // ④ 能力不退化：挪进 footer 的保存按钮仍然真的提交（不是只换了个位置就哑了）。
    await userEvent.click(screen.getByTestId('fee-item-pick-打孔'))
    await userEvent.type(screen.getByTestId('fee-combination-price-input'), '15')
    await userEvent.click(screen.getByTestId('fee-combination-submit'))
    await waitFor(() =>
      expect(mockCreateFeeCombination).toHaveBeenCalledWith({ items: ['打孔'], unit_price: 15 }),
    )
  })

  it('护栏理由逐条展示：读**真实信封** error.details[].message（三条 ⇒ 页面三条独立条目）', async () => {
    mockCreateFeeCombination.mockRejectedValueOnce({
      response: {
        data: {
          success: false,
          error: {
            code: 'VALIDATION_ERROR',
            message: '加工费组合未通过校验（3 条问题）',
            details: [
              { field: 'items[1]', message: '加工项「四爪钩」在加工项目录中不存在或已停用' },
              { field: 'items[2]', message: '加工项「韩褶」重复出现' },
              { field: 'unit_price', message: 'unit_price 不得为负数' },
            ],
          },
          suggestion: '逐条修好后重新提交',
        },
      },
    })
    render(<ProcessingFeesPage />)
    await waitFor(() => expect(screen.getByTestId('fee-combinations-total')).toHaveTextContent('2'))

    await userEvent.click(screen.getByTestId('fee-combination-new'))
    await userEvent.click(screen.getByTestId('fee-item-pick-打孔'))
    await userEvent.type(screen.getByTestId('fee-combination-price-input'), '9')
    await userEvent.click(screen.getByTestId('fee-combination-submit'))

    await waitFor(() => expect(screen.getByTestId('fee-combination-guard-reasons')).toBeInTheDocument())
    const reasons = screen.getAllByTestId(/^fee-combination-guard-reason-/)
    expect(reasons).toHaveLength(3)
    expect(reasons.map((r) => r.textContent).join('|')).toContain('四爪钩')
    expect(reasons.map((r) => r.textContent).join('|')).toContain('重复出现')
    expect(reasons.map((r) => r.textContent).join('|')).toContain('不得为负数')
    // 注入：把读法退化成 error.message 一句话 ⇒ 上面三条断言红（这正是 #4308 的假绿形态）
    expect(reasons.map((r) => r.textContent).join('|')).not.toContain('3 条问题')
  })

  it('同一组合重复定价（409）⇒ 也要给出可读理由，不得只弹「保存失败」', async () => {
    mockCreateFeeCombination.mockRejectedValueOnce({
      response: {
        data: {
          success: false,
          error: {
            code: 'CONFLICT',
            message: '加工费组合「打孔+韩褶」已存在定价',
          },
          suggestion: '同一组合只能有一个价：请直接编辑既有那一行',
        },
      },
    })
    render(<ProcessingFeesPage />)
    await waitFor(() => expect(screen.getByTestId('fee-combinations-total')).toHaveTextContent('2'))

    await userEvent.click(screen.getByTestId('fee-combination-new'))
    await userEvent.click(screen.getByTestId('fee-item-pick-打孔'))
    await userEvent.type(screen.getByTestId('fee-combination-price-input'), '15')
    await userEvent.click(screen.getByTestId('fee-combination-submit'))

    await waitFor(() =>
      expect(screen.getByTestId('fee-combination-guard-reasons')).toHaveTextContent('已存在定价'),
    )
  })

  it('空组合本地先拦：不发出 POST，并给出「至少选 1 个加工项」理由', async () => {
    render(<ProcessingFeesPage />)
    await waitFor(() => expect(screen.getByTestId('fee-combinations-total')).toHaveTextContent('2'))

    await userEvent.click(screen.getByTestId('fee-combination-new'))
    await userEvent.type(screen.getByTestId('fee-combination-price-input'), '12')
    await userEvent.click(screen.getByTestId('fee-combination-submit'))

    await waitFor(() =>
      expect(screen.getByTestId('fee-combination-guard-reasons')).toHaveTextContent('至少'),
    )
    expect(mockCreateFeeCombination).not.toHaveBeenCalled()
  })

  it('缺口区：未定价组合逐条可见（含出现次数），不是只显示条数', async () => {
    render(<ProcessingFeesPage />)
    await waitFor(() => expect(screen.getByTestId('fee-gaps-total')).toHaveTextContent('1'))

    const gap = screen.getByTestId('fee-gap-定型+韩褶')
    expect(within(gap).getByTestId('fee-gap-items-定型+韩褶')).toHaveTextContent('韩褶')
    expect(within(gap).getByTestId('fee-gap-items-定型+韩褶')).toHaveTextContent('定型')
    expect(within(gap).getByTestId('fee-gap-order-count-定型+韩褶')).toHaveTextContent('3')
  })

  it('改单价走 PUT /{id}（body 只有 unit_price）；停用走 DELETE /{id}（二次确认后）', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<ProcessingFeesPage />)
    await waitFor(() => expect(screen.getByTestId('fee-combination-fc-1')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('fee-combination-edit-fc-1'))
    const priceInput = screen.getByTestId('fee-combination-edit-price-fc-1')
    await userEvent.clear(priceInput)
    await userEvent.type(priceInput, '13.5')
    await userEvent.click(screen.getByTestId('fee-combination-edit-submit-fc-1'))
    await waitFor(() => expect(mockUpdateFeeCombination).toHaveBeenCalledWith('fc-1', { unit_price: 13.5 }))

    await userEvent.click(screen.getByTestId('fee-combination-disable-fc-1'))
    await waitFor(() => expect(mockDisableFeeCombination).toHaveBeenCalledWith('fc-1'))
    expect(confirmSpy).toHaveBeenCalled()
    confirmSpy.mockRestore()
  })

  it('列表加载失败：错误提示 + 重试（不白屏）', async () => {
    mockGetFeeCombinations
      .mockReset()
      .mockRejectedValueOnce(new Error('500'))
      .mockResolvedValue(ok(COMBINATIONS))
    render(<ProcessingFeesPage />)

    await waitFor(() => expect(screen.getByTestId('fee-combinations-error')).toHaveTextContent('加载失败'))
    await userEvent.click(screen.getByTestId('fee-combinations-retry'))
    await waitFor(() => expect(screen.getByTestId('fee-combinations-total')).toHaveTextContent('2'))
    expect(screen.queryByTestId('fee-combinations-error')).not.toBeInTheDocument()
  })

  it('缺口接口失败：只在缺口区给可读提示，组合列表照常渲染（不整页白屏）', async () => {
    mockGetFeeGaps.mockReset().mockRejectedValueOnce(new Error('500'))
    render(<ProcessingFeesPage />)

    await waitFor(() => expect(screen.getByTestId('fee-combinations-total')).toHaveTextContent('2'))
    expect(screen.getByTestId('fee-gaps-unavailable')).toHaveTextContent('缺口数据加载失败')
    expect(screen.getByTestId('fee-combination-fc-1')).toBeInTheDocument()
  })

  it('侧边栏：生产管理组含「加工费管理」→ /production/processing-fees（权限码 processing:manage）', async () => {
    const { menuGroups } = await import('@/config/menu')
    const production = menuGroups.find((g) => g.key === 'production')
    expect(production).toBeDefined()
    const entry = production!.children.find((c) => c.path === '/production/processing-fees')
    expect(entry).toBeDefined()
    expect(entry!.permissionCode).toBe('processing:manage')
    // 生产管理组归并结果必须仍在（本包只**追加**一项，不重排既有项）
    // ⚠️ issue #4416：原第 2 项「工序库」与第 3 项「工艺路线」已合并为「工艺配置」⇒
    //    /production/operations **不再是**菜单项（页面改为重定向，旧深链仍可达）
    expect(production!.children.map((c) => c.path)).toContain('/production/routings')
    expect(production!.children.map((c) => c.name)).toContain('工艺配置')
    expect(production!.children.map((c) => c.path)).not.toContain('/production/operations')
  })
})
