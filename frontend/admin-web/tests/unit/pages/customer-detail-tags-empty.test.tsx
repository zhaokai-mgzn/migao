// case_ids: UI-133
/**
 * 客户详情「标签」卡片：**没有标签可加时，点「+」必须给出可见反馈 + 可点的去处**（issue #7526）。
 *
 * ## 修前形态（用户 2026-10-23 截图 + 逐字「当系统没有标签时，点击+号无反应，应该引导客户去添加标签」）
 *
 * 面板渲染条件 = `{showTagPicker && availableTags.length > 0 && (...)}`：
 * 点「+」只是把 `showTagPicker` 翻成 `true`，但 `availableTags` 为空时面板**永不渲染**
 * ⇒ 触发器「可点但零反馈」，商家以为按钮坏了。两种空态都会落到这里：
 * ① 系统还没有任何标签定义；② 标签存在、但该客户已经打满全部标签。
 *
 * ## 判据（每条都会红）
 *
 * 1. 系统无标签：点「+」⇒ `customer-tag-empty` 在场、文案说明原因、入口按钮把路由推到 `/customers?manageTags=1`；
 * 2. 客户已打满：同一面板给出另一句原因（不是把「没有标签」错报成事实）+ 入口仍可用；
 * 3. 负控：面板是「点击才出现」（未点击时 `customer-tag-empty` 取不到）；
 * 4. 负控：有可加标签时**不出**空态、选择器照常列出可加的那一条（空态不得掩盖正常选择器）。
 *
 * 🔴 红证（实测指令，本文件在修前版本上跑）：
 * `npx vitest run tests/unit/pages/customer-detail-tags-empty.test.tsx`
 * —— 修前 `getByTestId('customer-tag-empty')` 抛 `Unable to find an element`；修后 4 passed。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// 前进/后退都走同一个可断言的 push（页面用 `router.push('/customers?manageTags=1')` 给出去处）
const h = vi.hoisted(() => ({
  push: vi.fn(),
  /** 系统里定义的全部标签 */
  systemTags: [] as Array<{ id: string; name: string; color: string }>,
  /** 该客户已关联的标签 */
  customerTags: [] as Array<{ id: string; name: string; color: string }>,
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: h.push, back: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

vi.mock('@/lib/use-route-id', () => ({ useRouteId: () => 'cus-001' }))

vi.mock('@/lib/api', () => ({
  customerApi: {
    getCustomer: vi.fn(async () => ({
      data: {
        data: {
          id: 'cus-001',
          profile: { id: 'cus-001', wechatNickname: '张三', phone: '13800138000' },
          tags: h.customerTags,
          orders: [],
          sessions: [],
        },
      },
    })),
    getCustomerTags: vi.fn(async () => ({ data: { data: h.systemTags } })),
    getCredit: vi.fn(async () => ({
      data: { data: { customerId: 'cus-001', creditLimit: 10000, paymentTermsDays: 30, outstanding: 6000, available: 4000 } },
    })),
    addTagToCustomer: vi.fn(async () => ({ data: { success: true } })),
    removeTagFromCustomer: vi.fn(async () => ({ data: { success: true } })),
    updateCustomer: vi.fn(async () => ({ data: { success: true } })),
  },
}))

import CustomerDetailPage from '@/app/(dashboard)/customers/[id]/CustomerDetail'

const TAG_T1 = { id: 't1', name: '优质', color: '#48618f' }
const TAG_T2 = { id: 't2', name: '需要跟进', color: '#F59E0B' }

/** 打开「+」面板并等客户卡片就绪 */
async function openTagPicker() {
  render(<CustomerDetailPage />)
  await waitFor(() => expect(screen.getAllByText('张三').length).toBeGreaterThan(0))
  const trigger = screen.getByRole('button', { name: '添加标签' })
  fireEvent.click(trigger)
  return trigger
}

describe('客户详情「标签」空态（issue #7526）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    h.systemTags = []
    h.customerTags = []
  })

  it('系统还没有任何标签时，点「+」给出可见反馈 + 去处（修前是零反应）', async () => {
    const trigger = await openTagPicker()

    // 判据 1：面板真的出现（修前这里抛 Unable to find an element）
    expect(await screen.findByTestId('customer-tag-empty')).toBeInTheDocument()
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText(/系统还没有标签/)).toBeInTheDocument()

    // 去处要一步到位：直接带去客户列表页并打开「标签管理」
    fireEvent.click(screen.getByRole('button', { name: '去添加标签' }))
    expect(h.push).toHaveBeenCalledWith('/customers?manageTags=1')
  })

  it('客户已经打满全部标签时，给出的是「打满」而不是「系统没有标签」（两种空态不许混）', async () => {
    h.systemTags = [TAG_T1]
    h.customerTags = [TAG_T1]
    await openTagPicker()

    expect(await screen.findByTestId('customer-tag-empty')).toBeInTheDocument()
    expect(screen.getByText(/全部标签/)).toBeInTheDocument()
    expect(screen.queryByText(/系统还没有标签/)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '管理标签' }))
    expect(h.push).toHaveBeenCalledWith('/customers?manageTags=1')
  })

  it('负控：面板是「点击才出现」—— 未点击时既无空态面板、也没有按钮把路由推走', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => expect(screen.getAllByText('张三').length).toBeGreaterThan(0))

    expect(screen.queryByTestId('customer-tag-empty')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '添加标签' })).toHaveAttribute('aria-expanded', 'false')
    expect(h.push).not.toHaveBeenCalled()
  })

  it('负控：有可加标签时不出空态，选择器照常列出可加的那一条', async () => {
    h.systemTags = [TAG_T1, TAG_T2]
    h.customerTags = [TAG_T1]
    await openTagPicker()

    // 可加的那一条真的在面板里（修后分支仍然走得通）
    expect(await screen.findByText('需要跟进')).toBeInTheDocument()
    // 空态不得掩盖正常选择器
    expect(screen.queryByTestId('customer-tag-empty')).not.toBeInTheDocument()
  })
})
