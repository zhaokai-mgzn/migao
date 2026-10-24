// case_ids: UI-133
/**
 * 客户列表页的标签管理**深链**（issue #7526）。
 *
 * 客户详情「标签」空态里的「去添加标签」指向 `/customers?manageTags=1` —— 落到列表页时必须
 * **直接打开**「标签管理」模态，而不是把商家丢在客户列表上自己再找一遍。
 *
 * 判据（都会红）：
 * 1. 带 `?manageTags=1` ⇒ 模态内容（「新建标签」表单 / 「已有标签」块）在场；
 * 2. 负控：不带参数 ⇒ 不自动打开（否则每次进客户列表都弹窗）。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const h = vi.hoisted(() => ({
  getCustomers: vi.fn(),
  getCustomerTags: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  customerApi: {
    getCustomers: (...args: unknown[]) => h.getCustomers(...args),
    getCustomerTags: (...args: unknown[]) => h.getCustomerTags(...args),
    createCustomerTag: vi.fn(async () => ({ data: { success: true } })),
    updateCustomerTag: vi.fn(async () => ({ data: { success: true } })),
    deleteCustomerTag: vi.fn(async () => ({ data: { success: true } })),
  },
}))

import CustomersPage from '@/app/(dashboard)/customers/page'

describe('客户列表页 ?manageTags=1 深链（issue #7526）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    h.getCustomers.mockResolvedValue({
      data: { data: { items: [], total: 0, page: 1, pageSize: 10 } },
    })
    h.getCustomerTags.mockResolvedValue({
      data: { data: [{ id: 't1', name: '优质', color: '#48618f' }] },
    })
  })

  afterEach(() => {
    window.history.replaceState({}, '', '/')
  })

  it('带 ?manageTags=1 ⇒ 标签管理模态直接打开（不用商家再找入口）', async () => {
    window.history.replaceState({}, '', '/customers?manageTags=1')
    render(<CustomersPage />)

    // 「新建标签」表单只存在于模态里（页面本身只有「标签管理」按钮）
    expect(await screen.findByText('新建标签')).toBeInTheDocument()
    expect(screen.getByText('已有标签')).toBeInTheDocument()
  })

  it('负控：不带参数时不自动打开（进客户列表不该被弹窗打断）', async () => {
    window.history.replaceState({}, '', '/customers')
    render(<CustomersPage />)
    await waitFor(() => expect(h.getCustomerTags).toHaveBeenCalled())

    expect(screen.queryByText('新建标签')).not.toBeInTheDocument()
    expect(screen.queryByText('已有标签')).not.toBeInTheDocument()
  })
})
