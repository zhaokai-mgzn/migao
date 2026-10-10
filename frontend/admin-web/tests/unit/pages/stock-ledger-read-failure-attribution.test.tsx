// case_ids: UI-046, UI-057, UI-089, PP-010
/**
 * `/stock-ledger` 读面失败的**归因话术**（issue #6707）—— 实例判据。
 *
 * ## 病灶（issue #6702 同族第二处；集成侧真机 `run-count-row.mjs` 读数：该页权限归因=❌）
 *
 * 改前两处 `catch` **一律**说「库存明细/批次余量读取失败（可能是当前岗位没有「商品管理」权限）
 * —— 请联系管理员开权限后重试」：把 **5xx / 网络 / 超时**说成**权限问题** ⇒ 商家去找管理员
 * 开一个**本来就有的**权限，真因（服务侧）被话术掩盖。
 *
 * ## 判据（三条，各自红在自己那条断言上）
 *
 *   ① **非 403 ⇒ 不得出现权限归因**：文案里不许有「没有…权限」这种因果句（口径 = 集成侧收口
 *      仪器的检测式 `/没有[^。，；]*权限/`，见用例 ⑤ 的双向自证），且要**明说不是权限问题**、
 *      给下一步（稍后重试）；
 *   ② **403 ⇒ 才谈权限**，且点名**本页**对应的读码（本页两个读面的方法级读码都是 `product:list`，
 *      对商家的可见名 = 菜单「商品管理」）—— 不许像改前那样把「商品管理」当成万能归因；
 *   ③ **反向对照**：读成功且**确实为空** ⇒ 「暂无库存流水」与「共 0 条」**照旧显示**
 *      （真 0 不许被判红）；失败态下则不许出现「暂无库存流水」（读不到 ≠ 没有）。
 *
 * 另核 issue #6707 点名的第二件事：**失败态与「零值读数」不得并存** —— 本页的覆盖点是
 * 计数行 `共 {error ? '—' : total} 条` 与空态行的 `!error` 守卫（用例 ① ④ 直接断言屏上读数，
 * 不是断言源码里有那个三元），`setTotal` 在 `catch` 里**不被清零**（issue #6703 的既定口径）。
 *
 * 类级元守卫（同一形态不许再进来）= `tests/unit/read-failure-copy-attribution-guard.test.ts`；
 * 台账 `LEDGER` 里那条 `stock-ledger/page.tsx::B` 已**同批删除**（基线 1 ⇒ 0）。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const TEST_TIMEOUT = 20_000

const mockLedger = vi.fn()
const mockBatches = vi.fn()
const mockGetProducts = vi.fn()

vi.mock('@/lib/api', () => ({
  stockLedgerApi: { ledger: (...a: unknown[]) => mockLedger(...a) },
  batchStockApi: { batches: (...a: unknown[]) => mockBatches(...a) },
  productApi: { getProducts: (...a: unknown[]) => mockGetProducts(...a) },
}))

import StockLedgerPage, { stockLedgerReadErrorCopy } from '@/app/(dashboard)/stock-ledger/page'

/** 集成侧收口仪器（`run-count-row.mjs`）的**权限归因检测式**（逐字同口径，双向自证见用例 ⑤） */
const PERM_BLAME_RE = /没有[^。，；]*权限/

const apiErr = (status: number) => Object.assign(new Error(`HTTP ${status}`), { response: { status } })

const ok = (data: unknown) => ({ data: { data } })

beforeEach(() => {
  vi.clearAllMocks()
})

describe('#6707 /stock-ledger 读失败归因：按状态分流（403 才谈权限）', () => {
  it(
    '① 流水读失败（500）⇒ 不提权限、说服务侧 + 下一步；失败面与「共 — 条」在位，且无「暂无库存流水」',
    async () => {
      mockLedger.mockRejectedValueOnce(apiErr(500))
      render(<StockLedgerPage />)
      await waitFor(() => expect(mockLedger).toHaveBeenCalled())

      const surface = await screen.findByTestId('stock-ledger-error')
      expect(surface).toHaveAttribute('role', 'alert')
      expect(screen.getByText(/暂时读不到/)).toBeInTheDocument()
      expect(screen.getByText(/不是你的权限问题/)).toBeInTheDocument()
      // 🔴 改前**就是这条红**：文案是「（可能是当前岗位没有「商品管理」权限）」⇒ 归因错
      expect(PERM_BLAME_RE.test(surface.textContent || '')).toBe(false)
      // 失败态与零值读数**不得并存**：计数印 `—`，空态话术不许上屏
      expect(screen.getByTestId('ledger-total').textContent).toMatch(/共\s*—\s*条/)
      expect(screen.queryByText('暂无库存流水')).not.toBeInTheDocument()
    },
    TEST_TIMEOUT,
  )

  it(
    '② 流水 403 ⇒ 才谈权限，且点名**本页**读码（菜单「商品管理」），不误伤「库存明细」这个读面名',
    async () => {
      mockLedger.mockRejectedValueOnce(apiErr(403))
      render(<StockLedgerPage />)

      const surface = await screen.findByTestId('stock-ledger-error')
      expect(surface.textContent).toContain('你没有查看「库存明细」的权限')
      expect(surface.textContent).toContain('商品管理')
      expect(PERM_BLAME_RE.test(surface.textContent || '')).toBe(true)
      // 权限是**终态**：不给「稍后重试」这种会让人空等的安慰话术，给去处（找管理员）
      expect(surface.textContent).toContain('请联系管理员')
    },
    TEST_TIMEOUT,
  )

  it(
    '③ 批次余量读失败（500）⇒ 同一范式（不提权限），批次失败面在位、批次空态话术不上屏',
    async () => {
      const user = userEvent.setup()
      mockLedger.mockResolvedValue(ok({ items: [], total: 0 }))
      mockGetProducts.mockResolvedValue(ok({ items: [{ id: 'p-1', name: '雪尼尔遮光布' }], total: 1 }))
      mockBatches.mockRejectedValueOnce(apiErr(500))
      render(<StockLedgerPage />)

      await user.click(screen.getByRole('tab', { name: /批次余量/ }))
      await user.type(screen.getByLabelText('搜索商品'), '遮光')
      await user.click(screen.getByRole('button', { name: /搜索商品/ }))
      await user.click(await screen.findByTestId('product-option'))

      await waitFor(() => expect(mockBatches).toHaveBeenCalled())
      const batchSurface = await screen.findByTestId('batch-error')
      expect(batchSurface.textContent).toContain('批次余量暂时读不到')
      expect(PERM_BLAME_RE.test(batchSurface.textContent || '')).toBe(false)
      // 批次空态话术的守卫（`!batchError`）仍在位：读不到不说「暂无批次记录」
      expect(screen.queryByText(/该商品暂无批次记录/)).not.toBeInTheDocument()
    },
    TEST_TIMEOUT,
  )

  it(
    '④ 反向对照：读成功且**确实为空** ⇒ 「暂无库存流水」与「共 0 条」照旧（真 0 不许被判红）',
    async () => {
      mockLedger.mockResolvedValue(ok({ items: [], total: 0 }))
      render(<StockLedgerPage />)

      expect(await screen.findByText('暂无库存流水')).toBeInTheDocument()
      expect(screen.getByTestId('ledger-total').textContent).toMatch(/共\s*0\s*条/)
      expect(screen.queryByTestId('stock-ledger-error')).not.toBeInTheDocument()
    },
    TEST_TIMEOUT,
  )

  it('⑤ 判别力自证：改前逐字文案必被判红、修后 500 文案不红、403 文案红', () => {
    // 改前的两句（逐字取自 `git show origin/main~1:…/stock-ledger/page.tsx`）
    const before = [
      '库存明细读取失败（可能是当前岗位没有「商品管理」权限）—— 请联系管理员开权限后重试',
      '批次余量读取失败（可能是当前岗位没有「商品管理」权限）—— 请联系管理员开权限后重试',
    ]
    for (const text of before) expect(PERM_BLAME_RE.test(text), `改前文案应被判红：${text}`).toBe(true)

    // 修后：非 403 一律不命中（含裸 `status`、网络错误、超时三种形态）
    expect(PERM_BLAME_RE.test(stockLedgerReadErrorCopy(apiErr(500)))).toBe(false)
    expect(PERM_BLAME_RE.test(stockLedgerReadErrorCopy({ status: 503 }))).toBe(false)
    expect(PERM_BLAME_RE.test(stockLedgerReadErrorCopy(new Error('Network Error')))).toBe(false)
    expect(stockLedgerReadErrorCopy(new Error('timeout'))).toContain('不是你的权限问题')
    // 修后：403 命中，且两个读面各自具名
    expect(PERM_BLAME_RE.test(stockLedgerReadErrorCopy(apiErr(403)))).toBe(true)
    expect(stockLedgerReadErrorCopy(apiErr(403), '批次余量')).toContain('「批次余量」')
    // 通道自证：判据不是恒绿/恒红，同一函数在两种状态上给出相反判定
    expect(PERM_BLAME_RE.test(stockLedgerReadErrorCopy(apiErr(403)))).not.toBe(
      PERM_BLAME_RE.test(stockLedgerReadErrorCopy(apiErr(500))),
    )
  })
})
