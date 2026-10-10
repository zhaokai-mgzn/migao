// case_ids: UI-057, UI-058
/**
 * 共享失败提示件（issue #6703）：`/orders` `/finance` `/customers` `/after-sales` `/knowledge`
 * `/stock-ledger` 六页共用同一形态 —— 这一份判据钉住**接口契约**：
 *
 * ① 锚点 = 传入的 `testId`（沿用既有命名规范 `<页面>-load-error`），重试出口 = `${testId}-retry`；
 * ② 文案逐字上屏；
 * ③ 点重试**真的调用** `onRetry`（一次点击 = 一次调用，不是「按钮画在那就行」）；
 * ④ `retrying` 时按钮 disabled（在飞时不许连点重复请求）。
 *
 * 各页「失败时计数行不印 0」的那一半在
 * `frontend/admin-web/tests/unit/pages/list-count-failure-instances.test.tsx`（注入式实例判据）。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import ListLoadError from '@/components/common/ListLoadError'

describe('ListLoadError（共享失败提示件，issue #6703）', () => {
  it('锚点 = 传入的 testId，重试出口 = <testId>-retry（既有命名规范可被各页覆盖）', () => {
    render(<ListLoadError testId="orders-load-error" message="订单加载失败 —— 没读到数据" onRetry={vi.fn()} />)
    const alert = screen.getByTestId('orders-load-error')
    expect(alert).toBeInTheDocument()
    // 失败态必须被读屏器播报（#6691 同口径）
    expect(alert).toHaveAttribute('role', 'alert')
    expect(screen.getByTestId('orders-load-error-retry')).toHaveTextContent('重新加载')
    expect(alert).toHaveTextContent('订单加载失败 —— 没读到数据')
  })

  it('点重试真的调用 onRetry（一次点击 = 一次调用）', async () => {
    const user = userEvent.setup()
    const onRetry = vi.fn()
    render(<ListLoadError testId="finance-load-error" message="资金流水加载失败" onRetry={onRetry} />)
    await user.click(screen.getByTestId('finance-load-error-retry'))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('retrying 时按钮 disabled（在飞时不许连点重复请求）', async () => {
    const user = userEvent.setup()
    const onRetry = vi.fn()
    render(<ListLoadError testId="customers-load-error" message="客户列表加载失败" onRetry={onRetry} retrying />)
    const retry = screen.getByTestId('customers-load-error-retry')
    expect(retry).toBeDisabled()
    await user.click(retry)
    expect(onRetry).not.toHaveBeenCalled()
  })

  it('对照读数：`retrying` 缺省时不 disabled（正常可点）', () => {
    render(<ListLoadError testId="knowledge-load-error" message="知识卡片加载失败" onRetry={vi.fn()} />)
    expect(screen.getByTestId('knowledge-load-error-retry')).not.toBeDisabled()
  })
})
