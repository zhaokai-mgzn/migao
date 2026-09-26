// case_ids: BM-009
/**
 * 计件工资报表（管理面手机端，issue #5654 项④）—— 端到端判据
 *
 * 链路：打开页面 → `GET /api/admin/production/piecework/summary?period=YYYY-MM` → 汇总 / 按工人 /
 *       按工序 / 未定价四块；期间切「上月」⇒ 重新请求带上月 `period`。
 *
 * 🔴 判据 1（**与 PC 端同源、绝不重算**）是本文件最强的一条：夹具刻意让
 * `per_worker` 之和（900 + 300 = 1200）**不等于** `total`（1234.56）——
 * 页面必须显示服务端的 `1234.56`。**红证**：把 `data.total` 换成
 * `workers.reduce((s, w) => s + w.amount, 0)` ⇒ 页面显示 1200.00 ⇒ 当场红。
 *
 * 其余判据：按工人/按工序渲染（工序显示名走 `operationDisplayName`：逻辑名 · 部位）、
 * **未定价块显式上屏**（未定价不进 total，不列出来就是静默吞掉一笔钱）、
 * 缺 `unpriced` 键 ⇒ 整块不出现（不写「未定价 0 件」）、403 ⇒ 逐字文案。
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn(() => ({ isLoggedIn: true, user: { id: 'u1', nickname: '王老板' } })),
}))

jest.mock('../src/services/adminOpsService', () => ({
  ...jest.requireActual('../src/services/adminOpsService'),
  fetchMyPermissions: jest.fn(),
  getPieceworkReport: jest.fn(),
}))

import AdminPieceworkPage from '../src/pages/admin/piecework/index'
import {
  fetchMyPermissions,
  getPieceworkReport,
  type PieceworkReport,
} from '../src/services/adminOpsService'

const mockReport = getPieceworkReport as jest.MockedFunction<typeof getPieceworkReport>
const mockPermissions = fetchMyPermissions as jest.MockedFunction<typeof fetchMyPermissions>

/** `total` **不等于** per_worker 之和 —— 用来证明页面渲染的是服务端值而不是本地求和 */
const REPORT: PieceworkReport = {
  period: '2026-09',
  total: 1234.56,
  per_worker: [
    { worker_name: '张三', amount: 900, qty: 300 },
    { worker_name: '李四', amount: 300, qty: 100 },
  ],
  per_operation: [
    { operation: '精裁-布', logical_name: '精裁', position: '布帘', amount: 1000, qty: 320 },
    { operation: '打卷', logical_name: null as any, position: null, amount: 234.56, qty: 80 },
  ],
  unpriced: {
    qty: 12,
    operations: [{ operation: '车边-纱', logical_name: '车边', position: '纱帘', qty: 12 }],
    hint: '去「工艺配置 → 部位价目」补价后重算',
  },
}

beforeEach(() => {
  jest.clearAllMocks()
  mockPermissions.mockResolvedValue(null)
  // 服务端**回声**请求的 period（后端 `pieceworkSummary` = `parsePeriod(period).toString()`）⇒
  // 夹具照此实现，页面头上的「期间」才是真值而不是猜的
  mockReport.mockImplementation(async ({ period }) => ({
    status: 'ok',
    data: { ...REPORT, period },
  }))
})

describe('管理面④计件工资报表（issue #5654）', () => {
  it('能打开能读数据：总额取**服务端 total**（不本地求和）、按工人逐行、按工序显示逻辑名·部位', async () => {
    render(<AdminPieceworkPage />)
    await screen.findByTestId('piecework-total')

    // 服务端 total = 1234.56，per_worker 之和 = 1200 ⇒ 显示服务端值才说明「没重算」
    expect(screen.getByTestId('piecework-total').textContent).toBe('¥1234.56')
    expect(screen.getByTestId('piecework-worker-0').textContent).toContain('张三')
    expect(screen.getByTestId('piecework-worker-0').textContent).toContain('¥900.00')
    expect(screen.getByTestId('piecework-worker-1').textContent).toContain('李四')
    // 工序显示名：logical_name · position（#4621/#4630 口径），不是快照名「精裁-布」
    expect(screen.getByTestId('piecework-operation-0').textContent).toContain('精裁 · 布帘')
    expect(screen.getByTestId('piecework-operation-0').textContent).not.toContain('精裁-布')
    // logical_name 缺 ⇒ 退回 operation 原文（不编名字）
    expect(screen.getByTestId('piecework-operation-1').textContent).toContain('打卷')
  })

  it('未定价块显式上屏（未定价不进 total，不列出来就是静默吞掉一笔钱）', async () => {
    render(<AdminPieceworkPage />)
    const unpriced = await screen.findByTestId('piecework-unpriced')
    expect(unpriced.textContent).toContain('12 件已报工但「未定价」')
    expect(unpriced.textContent).toContain('车边 · 纱帘 · 12 件')
    expect(unpriced.textContent).toContain('去「工艺配置 → 部位价目」补价后重算')
  })

  it('缺 unpriced 键 ⇒ 整块不出现（不渲染「未定价 0 件」这种假数据）', async () => {
    mockReport.mockResolvedValue({
      status: 'ok',
      data: { period: '2026-09', total: 0, per_worker: [], per_operation: [] },
    })
    render(<AdminPieceworkPage />)
    await screen.findByTestId('piecework-total')
    expect(screen.queryByTestId('piecework-unpriced')).toBeNull()
    expect(screen.getByTestId('admin-surface-empty')).toBeTruthy()
  })

  it('期间切换：点「上月」⇒ 请求带上一月的 period', async () => {
    // 🔴 **时刻由入参注入、期望值用字面量** —— 判据绝不依赖墙钟：
    // 若在断言里 `new Date()` 造期望值，跨月边界（如 1 日 00:00）会随机红；
    // 本仓类级守卫 `tests/unit_ci_workflows/time_flaky_guard.py` 专治这一形态
    // （本文件首版正是被它判红 ⇒ 这里改为「固定时刻 + 字面量」）。
    const FIXED_NOW = '2026-09-15T12:00:00+08:00'
    render(<AdminPieceworkPage now={new Date(FIXED_NOW)} />)
    await waitFor(() => expect(mockReport).toHaveBeenCalledTimes(1))
    expect(mockReport).toHaveBeenCalledWith({ period: '2026-09' })
    expect(screen.getByTestId('piecework-period').textContent).toContain('2026-09')

    fireEvent.click(screen.getByTestId('piecework-period-prev'))
    await waitFor(() => expect(mockReport).toHaveBeenCalledWith({ period: '2026-08' }))
    expect(screen.getByTestId('piecework-period').textContent).toContain('2026-08')
  })

  it('无权限有文案：403 ⇒ 逐字「无「计件工资报表」查看权限（需要权限码 processing:manage）」', async () => {
    mockReport.mockResolvedValue({
      status: 'forbidden',
      message: '无「计件工资报表」查看权限（需要权限码 processing:manage）',
    })
    render(<AdminPieceworkPage />)
    const block = await screen.findByTestId('admin-surface-forbidden')
    expect(block.textContent).toBe('无「计件工资报表」查看权限（需要权限码 processing:manage）')
  })
})
