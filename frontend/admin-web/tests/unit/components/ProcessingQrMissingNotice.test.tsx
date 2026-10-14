// case_ids: UI-061
//
// issue #6867（B5 实现包）：**旧加工单打印前「无码」是静默的**。
//
// 病：纸面的码已是加工单级稳定短链 `{base}/o/{短码}`，而**存量加工单没有 `short_code`**
// （迁移 V155 明确不回填，补码只发生在实例化 / 重新生成二维码那条路径上）⇒ 商家对旧单直接点
// 「打印加工单」时，纸面**静默**印出「无码」+ 短码位 `—`：看起来打好了、纸却扫不了，
// 而页面上**没有任何东西**提示他先补码。
//
// 本文件把这一步「静默失败」变成「可见 + 一键可修」——**不新增后端端点**，
// 复用既有 `POST /api/admin/production/orders/{orderId}/qr-token/regenerate`（issue #4287，
// 只补缺失的码）。它的 **URL / 动词** 由 `frontend/admin-web/tests/unit/lib/production-api.test.ts`
// 的 `regenerateQrToken 打 POST /api/admin/production/orders/{orderId}/qr-token/regenerate` 锁死；
// 本文件锁的是**组件这一层**：什么时候出现、点它调谁、成功后回什么、失败怎么说。
//
// 五条判据（每条都有反面读数，见文件末的「红证」注释块）：
//   ① 有码 ⇒ 提示与按钮**都不**渲染（别对一张有效的纸喊缺码）
//   ② 缺码 ⇒ 提示可见 + 补码按钮可点，点它调**那个端点**（入参断言）+ 成功后通知调用方刷新
//   ③ 无 `processing:manage` ⇒ **补码按钮**不渲染（事实仍可见 —— 读面事实给所有人、
//      写面动作只给有权的人；照 #4287 既有口径，避免「按钮可见却 403」）
//   ④ 端点失败 ⇒ **可见**错误文案（不许静默 / 假装成功），且入口仍在可重试、不触发刷新
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockRegenerate = vi.fn()
vi.mock('@/lib/api', () => ({
  productionApi: {
    regenerateQrToken: (...args: unknown[]) => mockRegenerate(...args),
  },
  processingOrderApi: {},
}))

import ProcessingQrMissingNotice from '@/components/orders/ProcessingQrMissingNotice'

const NOTICE = 'processing-qr-missing-notice'
const ACTION = 'processing-qr-regenerate'

/** 渲染提示（`missing` / 权限 / 刷新回调逐用例指定） */
function renderNotice(overrides: Partial<{
  orderId: string
  missing: boolean
  canManage: boolean
  onRegenerated: () => void | Promise<void>
}> = {}) {
  const onRegenerated = overrides.onRegenerated ?? vi.fn()
  const props = {
    orderId: 'order-123',
    missing: true,
    canManage: true,
    onRegenerated,
    ...overrides,
  }
  const view = render(<ProcessingQrMissingNotice {...props} />)
  return { ...view, onRegenerated }
}

describe('加工单缺码提示 ProcessingQrMissingNotice（issue #6867 / B5）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockRegenerate.mockResolvedValue({
      data: { data: { order_id: 'order-123', qr_token: 'a'.repeat(32), part_codes: 0 } },
    })
  })

  it('① 有码 ⇒ 提示与按钮都不渲染（反面：缺码时也不渲染 = 本单原始缺陷）', () => {
    renderNotice({ missing: false })

    expect(screen.queryByTestId(NOTICE)).toBeNull()
    expect(screen.queryByTestId(ACTION)).toBeNull()
  })

  it('② 缺码 ⇒ 提示可见（说清后果）+ 按钮可点；点它调那个端点并通知调用方刷新', async () => {
    const user = userEvent.setup()
    const onRegenerated = vi.fn()
    renderNotice({ onRegenerated })

    const notice = screen.getByTestId(NOTICE)
    expect(notice).toBeVisible()
    // 说清后果，而不是只甩一个「缺码」（商家要能据此做决定）
    expect(notice.textContent).toMatch(/扫不了/)
    const action = screen.getByTestId(ACTION)
    expect(action).toBeEnabled()

    await user.click(action)

    // 🔴 端点断言：入参是 **orderId**（端点要的是订单 id，不是加工单 id —— 别取错对象）
    expect(mockRegenerate).toHaveBeenCalledTimes(1)
    expect(mockRegenerate).toHaveBeenCalledWith('order-123')
    // 成功 ⇒ 通知调用方重新读加工单（提示的退场以「读面真的有了码」为准，不是「请求回来了」）
    await waitFor(() => expect(onRegenerated).toHaveBeenCalledTimes(1))
    // 且给出可见的「已生成」而不是留一个还在等按钮的框
    await waitFor(() => expect(screen.getByTestId(NOTICE).textContent).toMatch(/已生成/))
    expect(screen.queryByTestId(ACTION)).toBeNull()
  })

  it('③ 无 `processing:manage` ⇒ 补码按钮不渲染（缺码事实仍可见）', () => {
    renderNotice({ canManage: false })

    // 两条一起才不退化成恒真断言：无权限 ⇒ 写入口不在，但「这张纸扫不了」这个**读**面事实照旧可见
    // （看不见它 = 让没有补码权限的岗位继续印废纸）；有权限时入口必在 = 判据 ②
    expect(screen.getByTestId(NOTICE)).toBeVisible()
    expect(screen.queryByTestId(ACTION)).toBeNull()
  })

  it('④ 端点失败 ⇒ 可见错误文案 + 入口仍在可重试 + 不触发刷新（不假装成功）', async () => {
    const user = userEvent.setup()
    const onRegenerated = vi.fn()
    mockRegenerate.mockRejectedValue(new Error('500'))
    renderNotice({ onRegenerated })

    await user.click(screen.getByTestId(ACTION))

    await waitFor(() => expect(screen.getByTestId(NOTICE).textContent).toMatch(/失败/))
    // 失败后入口不得消失（否则商家连重试的出口都没有）
    expect(screen.getByTestId(ACTION)).toBeEnabled()
    // 🔴 失败时**不得**通知刷新：那会让调用方把「没补上」当成「补上了」
    expect(onRegenerated).not.toHaveBeenCalled()
  })
})

/* ────────────────────────────────────────────────────────────────────────────
 * 红证（把被测实现**改回去 / 改错**时的实际读数；均为本包实测或按同一注入法复算）：
 *   ① 把 `if (!missing) return null` 改成 `if (missing) return null`（谓词反转）
 *      ⇒ ① 与 ② 同时红（实测整片 `5 failed`）—— 两条成对，谁都不能单独绿。
 *   ② 不接线端点（删掉 `productionApi.regenerateQrToken(orderId)` 调用）⇒
 *      `expect(mockRegenerate).toHaveBeenCalledWith('order-123')` 失败 ⇒ 红；
 *      传错对象（传加工单 id）⇒ 同一条红；去掉 `await onRegenerated()` ⇒
 *      `onRegenerated` 停在 0 次 ⇒ 红（不会「假装成功」）。
 *   ③ 入口不看权限（把 `{canManage && (…)}` 写成 `{true && (…)}`）
 *      ⇒ **实测** `expected <button …> to be null`（4 passed | 1 failed）⇒ 红；
 *      反向「无权限时连事实一起藏」（`if (!canManage) return null`）⇒ ③ 的 `NOTICE` 找不到 ⇒ 也红。
 *   ④ `catch {}` 静默（不 setError）⇒ 文案里没有「失败」⇒ 红；
 *      失败时也调 `onRegenerated()` ⇒ 末条断言红。
 * 折假值红证：若把缺码折成加工单号顶上去（画一个扫不开的码），① 会因「有码」而绿、②③④ 仍红 ⇒
 *   本文件对「折假值」不是零判别力；纸面另有
 *   `frontend/admin-web/tests/unit/components/ProcessingDoc.test.tsx` 的「缺码不画假码」判据。
 * ──────────────────────────────────────────────────────────────────────────── */
