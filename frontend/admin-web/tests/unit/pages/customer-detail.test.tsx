// case_ids: CU-001, CU-002, CU-009
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// Mock sonner toast
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}))

// Mock useRouteId to return a valid customer ID
vi.mock('@/lib/use-route-id', () => ({
  useRouteId: () => 'cus-001',
}))

// Mock UI components — only the ones used by CustomerDetail
vi.mock('@/components/ui', () => ({
  Button: ({ children, onClick, loading, ...props }: any) => (
    <button onClick={onClick} disabled={loading} {...props}>{children}</button>
  ),
  StatusBadge: ({ label, color, dot, className, onClick }: any) => React.createElement('span', { onClick, className, title: label }, dot ? React.createElement('span', { className: 'w-1.5 h-1.5 rounded-full' }) : null, label),
  Badge: ({ children, variant }: any) => <span data-variant={variant}>{children}</span>,
}))

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: string) => ({
    format: (fmt: string) => {
      if (!date) return ''
      if (fmt === 'YYYY-MM-DD') return '2026-01-15'
      return '2026-04-20 14:30'
    },
  }),
}))

// Mock lucide-react — icons used by CustomerDetail
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    ArrowLeft: stub('arrow-left'),
    Phone: stub('phone'),
    MapPin: stub('map-pin'),
    Star: stub('star'),
    Plus: stub('plus'),
    X: stub('x'),
    MessageSquare: stub('message-square'),
    ShoppingCart: stub('shopping-cart'),
    StickyNote: stub('sticky-note'),
    Save: stub('save'),
  }
})

// Mock customerApi — 模拟后端真实响应（{ id, profile, tags, orders, sessions }）
vi.mock('@/lib/api', () => {
  const mockDetail = {
    id: 'cus-001',
    profile: {
      id: 'cus-001',
      wechatNickname: '张三',
      phone: '13800138000',
      sourceChannel: 'wechat_mini',
      vipLevel: 'vip1',
      agentNotes: '老客户，偏好遮光窗帘',
      lastActiveAt: '2026-04-20T14:30:00',
      registeredAt: '2026-01-15T10:00:00',
      // 默认收货信息与常用物流（issue #4419，V70/V47 列）
      defaultReceiverName: '张三',
      defaultReceiverPhone: '13800138000',
      defaultReceiverAddress: '浙江省杭州市西湖区文三路1号1幢101室',
      defaultLogisticsType: 'logistics',
      defaultLogisticsCompany: '四季安物流',
    },
    tags: [
      { id: 't1', name: 'VIP客户', color: '#EF4444' },
      { id: 't2', name: '窗帘定制', color: '#48618f' },
    ],
    orders: [
      { id: 'o1', orderNo: 'ORD20260415001', totalAmount: 2680, status: 'completed', createdAt: '2026-04-15T10:00:00' },
    ],
    sessions: [
      { id: 's1', lastMessage: '我想看看新款遮光窗帘', channel: 'wechat_mini', isAI: true, createdAt: '2026-04-20T14:30:00' },
    ],
  }
  const mockAllTags = [
    { id: 't1', name: 'VIP客户', color: '#EF4444' },
    { id: 't2', name: '窗帘定制', color: '#48618f' },
    { id: 't3', name: '需要跟进', color: '#F59E0B' },
  ]
  return {
    customerApi: {
      getCustomer: vi.fn().mockResolvedValue({ data: { data: mockDetail } }),
      getCustomerTags: vi.fn().mockResolvedValue({ data: { data: mockAllTags } }),
      addTagToCustomer: vi.fn().mockResolvedValue({ data: { success: true } }),
      removeTagFromCustomer: vi.fn().mockResolvedValue({ data: { success: true } }),
      updateCustomer: vi.fn().mockResolvedValue({ data: { success: true } }),
    },
  }
})

import CustomerDetailPage from '@/app/(dashboard)/customers/[id]/CustomerDetail'
import { customerApi } from '@/lib/api'
import { toast } from 'sonner'

describe('CustomerDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows loading state initially', () => {
    render(<CustomerDetailPage />)
    expect(screen.getByText('加载中...')).toBeInTheDocument()
  })

  it('loads and displays real customer name from API (not hardcoded)', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(customerApi.getCustomer).toHaveBeenCalledWith('cus-001')
    })
    await waitFor(() => {
      expect(screen.getAllByText('张三').length).toBeGreaterThan(0)
    })
    // 硬编码的 mock 客户不应出现
    expect(screen.queryByText('张美丽')).not.toBeInTheDocument()
  })

  it('displays customer phone from API', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('13800138000')).toBeInTheDocument()
    })
  })

  it('displays linked tags from API', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('VIP客户')).toBeInTheDocument()
      expect(screen.getByText('窗帘定制')).toBeInTheDocument()
    })
  })

  it('displays tab bar with Orders, Sessions, Notes', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('订单历史')).toBeInTheDocument()
      expect(screen.getByText('会话历史')).toBeInTheDocument()
      expect(screen.getByText('跟进记录')).toBeInTheDocument()
    })
  })

  it('displays order list by default', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('ORD20260415001')).toBeInTheDocument()
    })
  })

  it('displays remark textarea', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      const textarea = screen.getByPlaceholderText('添加客户备注...')
      expect(textarea).toBeInTheDocument()
    })
  })

  it('calls addTagToCustomer API and renders newly added tag', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('张三')).toBeInTheDocument()
    })
    // 打开标签选择器（已关联 t1/t2，availableTags 中只剩 t3「需要跟进」）
    fireEvent.click(screen.getByTestId('icon-plus'))
    await waitFor(() => {
      expect(screen.getByText('需要跟进')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('需要跟进'))
    await waitFor(() => {
      expect(customerApi.addTagToCustomer).toHaveBeenCalledWith('cus-001', 't3')
    })
    // 打标成功后新标签出现在已选标签区（picker 已关闭，仅剩一处文本）
    await waitFor(() => {
      expect(screen.getAllByText('需要跟进')).toHaveLength(1)
    })
  })

  it('calls removeTagFromCustomer API and removes tag from display', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('VIP客户')).toBeInTheDocument()
    })
    // 第一个已选标签「VIP客户」(t1) 的移除按钮（X 图标）
    const removeButtons = screen.getAllByTestId('icon-x')
    fireEvent.click(removeButtons[0])
    await waitFor(() => {
      expect(customerApi.removeTagFromCustomer).toHaveBeenCalledWith('cus-001', 't1')
    })
    await waitFor(() => {
      expect(screen.queryByText('VIP客户')).not.toBeInTheDocument()
    })
  })

  it('calls updateCustomer API with remark when saving remark', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('张三')).toBeInTheDocument()
    })
    const textarea = screen.getByPlaceholderText('添加客户备注...')
    fireEvent.change(textarea, { target: { value: '测试备注内容' } })
    fireEvent.click(screen.getByTestId('save-remark'))
    await waitFor(() => {
      expect(customerApi.updateCustomer).toHaveBeenCalledWith('cus-001', { remark: '测试备注内容' })
    })
  })

  // ===== 收货信息 + 常用物流档案（issue #4419）=====

  it('显示客户档案里的收货信息与常用物流（不是前端编造的默认值）', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByTestId('receiver-card')).toBeInTheDocument()
    })
    expect(screen.getByPlaceholderText('收货人姓名')).toHaveValue('张三')
    expect(screen.getByPlaceholderText('收货人电话')).toHaveValue('13800138000')
    expect(screen.getByPlaceholderText('省市区 + 详细地址')).toHaveValue('浙江省杭州市西湖区文三路1号1幢101室')
    expect(screen.getByDisplayValue('物流/专线')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('选择或输入承运商')).toHaveValue('四季安物流')
  })

  it('保存收货信息时把默认收货地址与常用物流一并下发（缺一不可）', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByTestId('receiver-card')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByPlaceholderText('省市区 + 详细地址'), {
      target: { value: '江苏省苏州市吴中区越溪街道1号' },
    })
    fireEvent.change(screen.getByPlaceholderText('选择或输入承运商'), {
      target: { value: '跨越速运' },
    })
    fireEvent.change(screen.getByDisplayValue('物流/专线'), {
      target: { value: 'express' },
    })
    fireEvent.click(screen.getByTestId('save-receiver'))

    await waitFor(() => {
      expect(customerApi.updateCustomer).toHaveBeenCalledWith('cus-001', {
        defaultReceiverName: '张三',
        defaultReceiverPhone: '13800138000',
        defaultReceiverAddress: '江苏省苏州市吴中区越溪街道1号',
        defaultLogisticsType: 'express',
        defaultLogisticsCompany: '跨越速运',
      })
    })
  })

  it('承运商支持自定义填写（预置下拉之外的承运商也能记录）', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByTestId('receiver-card')).toBeInTheDocument()
    })
    // 预置候选以 datalist 提供（原生「下拉 + 可输入」），且不构成白名单
    const companyInput = screen.getByPlaceholderText('选择或输入承运商')
    expect(companyInput).toHaveAttribute('list', 'receiver-logistics-companies')
    fireEvent.change(companyInput, { target: { value: '本地专线·老王' } })
    fireEvent.click(screen.getByTestId('save-receiver'))
    await waitFor(() => {
      expect(customerApi.updateCustomer).toHaveBeenCalledWith(
        'cus-001',
        expect.objectContaining({ defaultLogisticsCompany: '本地专线·老王' }),
      )
    })
  })

  // ── 清空语义的反馈口径（issue #4443）────────────────────────────────────
  // 后端 updateCustomer 是「非空拷贝」：空白一律不覆盖（#4419 有意为之，由
  // CustomerReceiverAddressPersistTest.updateCustomer_BlankReceiverFieldsDoNotWipeExisting 钉住）。
  // 故前端**不得**把「清空」报成成功 —— 下面四条钉住「UI 反馈 == 实际效果」。

  it('唯一改动是清空时：不下发、不报「已保存」、明确告知不支持，且输入框恢复服务端真值', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByTestId('receiver-card')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByPlaceholderText('省市区 + 详细地址'), { target: { value: '' } })
    fireEvent.click(screen.getByTestId('save-receiver'))

    await waitFor(() => {
      expect(toast.warning).toHaveBeenCalledWith('暂不支持清空：收货地址')
    })
    // 没有可落库的改动 ⇒ 不得发请求，更不得报成功
    expect(customerApi.updateCustomer).not.toHaveBeenCalled()
    expect(toast.success).not.toHaveBeenCalled()
    // 界面必须回到服务端真值，否则「显示空白」是第二次谎报
    expect(screen.getByPlaceholderText('省市区 + 详细地址')).toHaveValue(
      '浙江省杭州市西湖区文三路1号1幢101室',
    )
  })

  it('没有任何改动时保存：不调 API、不报「已保存」，只提示无改动', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByTestId('receiver-card')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByTestId('save-receiver'))

    await waitFor(() => {
      expect(toast.info).toHaveBeenCalledWith('收货信息没有改动')
    })
    expect(customerApi.updateCustomer).not.toHaveBeenCalled()
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('清空与真实改动并存：空白键不下发、如实告知清空不支持、不报「已保存」', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByTestId('receiver-card')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByPlaceholderText('省市区 + 详细地址'), {
      target: { value: '江苏省苏州市吴中区越溪街道1号' },
    })
    fireEvent.change(screen.getByPlaceholderText('选择或输入承运商'), { target: { value: '' } })
    fireEvent.click(screen.getByTestId('save-receiver'))

    await waitFor(() => {
      expect(customerApi.updateCustomer).toHaveBeenCalled()
    })
    const payload = vi.mocked(customerApi.updateCustomer).mock.calls[0][1] as Record<string, unknown>
    expect(payload.defaultReceiverAddress).toBe('江苏省苏州市吴中区越溪街道1号')
    // 空白键不下发：下发也无效，只会让人以为已清空
    expect('defaultLogisticsCompany' in payload).toBe(false)
    // 非空未改动字段照旧下发（保住既有「缺一不可」语义）
    expect(payload.defaultReceiverName).toBe('张三')
    expect(toast.success).not.toHaveBeenCalled()
    expect(toast.warning).toHaveBeenCalledWith('已保存其余改动；暂不支持清空：常用物流公司')
    expect(screen.getByPlaceholderText('选择或输入承运商')).toHaveValue('四季安物流')
  })

  it('有真实改动且无清空时仍报「已保存」（防误伤）', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByTestId('receiver-card')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByPlaceholderText('省市区 + 详细地址'), {
      target: { value: '江苏省苏州市吴中区越溪街道1号' },
    })
    fireEvent.click(screen.getByTestId('save-receiver'))

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith('收货信息已保存')
    })
    expect(toast.warning).not.toHaveBeenCalled()
  })
})
