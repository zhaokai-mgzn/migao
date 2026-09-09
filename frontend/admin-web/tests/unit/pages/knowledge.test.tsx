import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
// case_ids: API-015, UI-033, UI-034

// Mock API — LLM WIKI 知识卡片页（issue #3051）：数据源必须来自 knowledgeApi.getCards（非硬编码）
vi.mock('@/lib/api', () => ({
  knowledgeApi: {
    getCards: vi.fn().mockResolvedValue({
      data: {
        success: true,
        data: { items: [{ id: 'entry_1', title: '雪尼尔面料会起球吗', category: 'faq', sourceType: 'manual', status: 'published', version: 2, answer: '雪尼尔织物起球概率较低……', updatedAt: '2026-09-08T10:30:00' }], total: 1, page: 1, size: 20 },
      },
    }),
    searchCards: vi.fn().mockResolvedValue({ data: { success: true, data: [] } }),
    createCard: vi.fn().mockResolvedValue({ data: { success: true, data: { id: 'entry_new', status: 'draft' } } }),
    updateCard: vi.fn().mockResolvedValue({ data: { success: true, data: { id: 'entry_1', status: 'published' } } }),
    deleteCard: vi.fn().mockResolvedValue({ data: { success: true } }),
    publishCard: vi.fn().mockResolvedValue({ data: { success: true, data: { id: 'entry_1', status: 'published' } } }),
    archiveCard: vi.fn().mockResolvedValue({ data: { success: true, data: { id: 'entry_1', status: 'archived' } } }),
    getCandidates: vi.fn().mockResolvedValue({ data: { success: true, data: { items: [{ id: 'c1', sourceType: 'conversation', suggestedTitle: '窗帘多久洗一次', suggestedAnswer: '建议每 3-6 个月清洗一次。', confidence: 0.9, status: 'pending', createdAt: '2026-09-08T10:00:00' }], total: 1 } } }),
    getPendingCount: vi.fn().mockResolvedValue({ data: { success: true, data: { pending: 1 } } }),
    adoptCandidate: vi.fn().mockResolvedValue({ data: { success: true, data: { id: 'card-1', status: 'published' } } }),
    rejectCandidate: vi.fn().mockResolvedValue({ data: { success: true } }),
    getTemplates: vi.fn().mockResolvedValue({ data: { success: true, data: [{ templateId: 'curtain', industry: 'curtain', name: '布艺窗帘行业模板', version: 1, entryCount: 32 }] } }),
    applyTemplate: vi.fn().mockResolvedValue({ data: { success: true, data: { templateId: 'curtain', created: 32, skipped: 0 } } }),
    distillConversations: vi.fn().mockResolvedValue({ data: { success: true, data: { sessions: 1, candidates: 2, created: 2, skipped: 0 } } }),
    distillDocument: vi.fn().mockResolvedValue({ data: { success: true, data: { candidates: 2, created: 2, skipped: 0 } } }),
  },
}))

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: any) => ({
    format: () => date || '2026-09-08 10:30',
  }),
}))

// Mock sonner
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Mock UI components（Table 用 data 而非 dataSource）
vi.mock('@/components/ui', () => ({
  Table: ({ dataSource, columns, loading, highlightRowKey }: any) => (
    <div data-testid="table">
      {loading && <div data-testid="table-loading">加载中...</div>}
      {dataSource?.map((record: any) => (
        <div key={record.id} data-testid={`row-${record.id}`} data-highlight={highlightRowKey === record.id ? 'true' : undefined}>
          {columns?.map((col: any) => (
            <span key={col.key} data-testid={`cell-${record.id}-${col.key}`}>
              {col.render ? col.render(record) : record[col.key]}
            </span>
          ))}
        </div>
      ))}
    </div>
  ),
  Pagination: () => <div data-testid="pagination">Pagination</div>,
  Modal: ({ open, title, children }: any) =>
    open ? (
      <div data-testid="modal" role="dialog">
        <h2>{title}</h2>
        {children}
      </div>
    ) : null,
  Button: ({ children, onClick, ...props }: any) => (
    <button onClick={onClick} {...props}>{children}</button>
  ),
  Badge: ({ children, color }: any) => (
    <span data-testid="badge" data-color={color}>{children}</span>
  ),
  SearchBar: ({ fields, onSearch, onReset }: any) => (
    <div data-testid="search-bar">
      {fields?.map((f: any) => (
        <input key={f.key} aria-label={f.placeholder} placeholder={f.placeholder} data-testid={`field-${f.key}`} />
      ))}
      <button onClick={() => onSearch({ keyword: '起球' })} data-testid="search-btn">搜索</button>
      <button onClick={onReset} data-testid="reset-btn">重置</button>
    </div>
  ),
}))

// Mock DateTimeCell
vi.mock('@/components/common/DateTimeCell', () => ({
  default: ({ value }: any) => <span data-testid="datetime">{value}</span>,
}))

import KnowledgePage from '@/app/(dashboard)/knowledge/page'

describe('KnowledgePage（LLM WIKI 知识卡片管理）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should render page title and description', async () => {
    render(<KnowledgePage />)
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '知识库' })).toBeInTheDocument()
    })
    expect(screen.getByText(/LLM WIKI 知识卡片管理/)).toBeInTheDocument()
  })

  it('should display entries from API in table (no hardcode)', async () => {
    render(<KnowledgePage />)
    await waitFor(() => {
      expect(screen.getByText('雪尼尔面料会起球吗')).toBeInTheDocument()
    })
    const api = (await import('@/lib/api')).knowledgeApi as any
    expect(api.getCards).toHaveBeenCalled()
  })

  it('should open create modal and save new entry as draft', async () => {
    const user = userEvent.setup()
    render(<KnowledgePage />)
    await waitFor(() => {
      expect(screen.getByText('新建知识卡片')).toBeInTheDocument()
    })

    await user.click(screen.getByText('新建知识卡片'))
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })

    await user.type(screen.getByPlaceholderText('如：雪尼尔面料会起球吗'), '窗帘多久洗一次')
    await user.type(screen.getByPlaceholderText('AI 客服将基于此内容回答'), '建议每 3-6 个月清洗一次。')
    await user.click(screen.getByText('保存'))

    const api = (await import('@/lib/api')).knowledgeApi as any
    await waitFor(() => {
      expect(api.createCard).toHaveBeenCalledWith(expect.objectContaining({ title: '窗帘多久洗一次' }))
    })
  })

  it('should publish draft entry via publish button', async () => {
    const api = (await import('@/lib/api')).knowledgeApi as any
    api.getCards.mockResolvedValueOnce({
      data: { success: true, data: { items: [{ id: 'entry_2', title: '退换货政策', category: 'aftersale', sourceType: 'manual', status: 'draft', version: 1, answer: '……', updatedAt: '2026-09-08T09:00:00' }], total: 1, page: 1, size: 20 } },
    })
    const user = userEvent.setup()
    render(<KnowledgePage />)
    await waitFor(() => {
      expect(screen.getByText('退换货政策')).toBeInTheDocument()
    })
    await user.click(screen.getByText('发布'))
    await waitFor(() => {
      expect(api.publishCard).toHaveBeenCalledWith('entry_2')
    })
  })

  it('should show pending candidates queue and adopt', async () => {
    const user = userEvent.setup()
    render(<KnowledgePage />)
    await waitFor(() => {
      expect(screen.getByText('待确认')).toBeInTheDocument()
    })
    await user.click(screen.getByText('待确认'))
    await waitFor(() => {
      expect(screen.getByText('窗帘多久洗一次')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByText('待确认 (1)')).toBeInTheDocument()
    })
    await user.click(screen.getByText('采纳'))
    const api = (await import('@/lib/api')).knowledgeApi as any
    await waitFor(() => {
      expect(api.adoptCandidate).toHaveBeenCalledWith('c1')
    })
  })

  it('should list industry templates and apply', async () => {
    const user = userEvent.setup()
    const api = (await import('@/lib/api')).knowledgeApi as any
    render(<KnowledgePage />)
    await waitFor(() => {
      expect(screen.getByText('行业模板')).toBeInTheDocument()
    })
    await user.click(screen.getByText('行业模板'))
    await waitFor(() => {
      expect(screen.getByText('布艺窗帘行业模板')).toBeInTheDocument()
    })
    await user.click(screen.getByText('一键套用'))
    // 确认弹窗先行：未确认不得调用套用接口（#3080）
    await waitFor(() => {
      expect(screen.getByText('套用行业模板')).toBeInTheDocument()
    })
    expect(api.applyTemplate).not.toHaveBeenCalled()
    await user.click(screen.getByText('确定套用'))
    await waitFor(() => {
      expect(api.applyTemplate).toHaveBeenCalledWith('curtain')
    })
  })

  it('after applying template, should switch to cards tab, refresh list and allow editing the applied card (#3070)', async () => {
    const user = userEvent.setup()
    const api = (await import('@/lib/api')).knowledgeApi as any
    render(<KnowledgePage />)
    // 等初始列表加载完成后再队列「套用后刷新」的返回
    await waitFor(() => {
      expect(screen.getByText('雪尼尔面料会起球吗')).toBeInTheDocument()
    })
    api.getCards.mockResolvedValueOnce({
      data: { success: true, data: { items: [{ id: 'entry_t1', title: '窗帘尺寸测量标准', category: 'measure', sourceType: 'template', status: 'published', version: 1, answer: '…', updatedAt: '2026-09-09T10:00:00' }], total: 1, page: 1, size: 20 } },
    })
    await user.click(screen.getByText('行业模板'))
    await waitFor(() => {
      expect(screen.getByText('布艺窗帘行业模板')).toBeInTheDocument()
    })
    await user.click(screen.getByText('一键套用'))
    // 确认弹窗先行（#3080）
    await waitFor(() => {
      expect(screen.getByText('确定套用')).toBeInTheDocument()
    })
    await user.click(screen.getByText('确定套用'))
    await waitFor(() => {
      expect(api.applyTemplate).toHaveBeenCalledWith('curtain')
    })
    // 跳转「知识卡片」Tab + 刷新列表：套用出的卡片立即可见
    await waitFor(() => {
      expect(screen.getByText('窗帘尺寸测量标准')).toBeInTheDocument()
    })
    // 且可直接编辑（打开编辑弹窗并回填标题）
    await user.click(screen.getByText('编辑'))
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument()
      expect(screen.getByText('编辑知识卡片')).toBeInTheDocument()
      expect(screen.getByDisplayValue('窗帘尺寸测量标准')).toBeInTheDocument()
    })
  })

  it('after adopting candidate, should switch to cards tab and show the published card (editable) (#3070)', async () => {
    const user = userEvent.setup()
    const api = (await import('@/lib/api')).knowledgeApi as any
    render(<KnowledgePage />)
    // 等初始列表加载完成后再队列「采纳后刷新」的返回
    await waitFor(() => {
      expect(screen.getByText('雪尼尔面料会起球吗')).toBeInTheDocument()
    })
    // 采纳后刷新 getCards：返回已发布的采纳卡片
    api.getCards.mockResolvedValueOnce({
      data: { success: true, data: { items: [{ id: 'entry_adopted', title: '窗帘多久洗一次', category: 'faq', sourceType: 'conversation', status: 'published', version: 1, answer: '建议每 3-6 个月清洗一次。', updatedAt: '2026-09-09T10:00:00' }], total: 1, page: 1, size: 20 } },
    })
    await user.click(screen.getByText('待确认'))
    await waitFor(() => {
      expect(screen.getByText('窗帘多久洗一次')).toBeInTheDocument()
    })
    await user.click(screen.getByText('采纳'))
    await waitFor(() => {
      expect(api.adoptCandidate).toHaveBeenCalledWith('c1')
    })
    // 跳转「知识卡片」Tab：采纳结果立即可见且可编辑
    await waitFor(() => {
      expect(screen.getByText('窗帘多久洗一次')).toBeInTheDocument()
    })
    await user.click(screen.getByText('编辑'))
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument()
      expect(screen.getByDisplayValue('窗帘多久洗一次')).toBeInTheDocument()
    })
  })

  it('adopting candidate shows location toast and highlights the new card row (结果可见, #3080)', async () => {
    const user = userEvent.setup()
    const api = (await import('@/lib/api')).knowledgeApi as any
    render(<KnowledgePage />)
    await waitFor(() => {
      expect(screen.getByText('雪尼尔面料会起球吗')).toBeInTheDocument()
    })
    // 采纳后刷新 getCards：返回采纳接口返回的同一张卡（id=card-1，用于高亮锚定）
    api.getCards.mockResolvedValueOnce({
      data: { success: true, data: { items: [{ id: 'card-1', title: '窗帘多久洗一次', category: 'faq', sourceType: 'conversation', status: 'published', version: 1, answer: '建议每 3-6 个月清洗一次。', updatedAt: '2026-09-09T10:00:00' }], total: 1, page: 1, size: 20 } },
    })
    await user.click(screen.getByText('待确认'))
    await waitFor(() => {
      expect(screen.getByText('采纳')).toBeInTheDocument()
    })
    await user.click(screen.getByText('采纳'))
    // 去向 toast：文案包含跳转去向（做了什么 + 去哪了）
    const { toast } = await import('sonner')
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('跳转知识卡片列表'))
    })
    // 成果物可见：新卡渲染在「知识卡片」列表
    await waitFor(() => {
      expect(screen.getByTestId('row-card-1')).toBeInTheDocument()
    })
    // 新卡行高亮定位（怎么找回来）
    expect(screen.getByTestId('row-card-1')).toHaveAttribute('data-highlight', 'true')
  })

  it('applying template gates behind confirm dialog, then locates via 来源=模板 filter (#3080)', async () => {
    const user = userEvent.setup()
    const api = (await import('@/lib/api')).knowledgeApi as any
    render(<KnowledgePage />)
    await waitFor(() => {
      expect(screen.getByText('雪尼尔面料会起球吗')).toBeInTheDocument()
    })
    // 套用后刷新：仅返回来源=模板的卡
    api.getCards.mockResolvedValueOnce({
      data: { success: true, data: { items: [{ id: 'entry_t1', title: '窗帘尺寸测量标准', category: 'measure', sourceType: 'template', status: 'published', version: 1, answer: '…', updatedAt: '2026-09-09T10:00:00' }], total: 1, page: 1, size: 20 } },
    })
    await user.click(screen.getByText('行业模板'))
    await waitFor(() => {
      expect(screen.getByText('布艺窗帘行业模板')).toBeInTheDocument()
    })
    await user.click(screen.getByText('一键套用'))
    // 确认弹窗先行，未确认不得调接口
    await waitFor(() => {
      expect(screen.getByText('套用行业模板')).toBeInTheDocument()
    })
    expect(api.applyTemplate).not.toHaveBeenCalled()
    await user.click(screen.getByText('确定套用'))
    await waitFor(() => {
      expect(api.applyTemplate).toHaveBeenCalledWith('curtain')
    })
    // 去向 toast：指明跳转 + 来源筛选
    const { toast } = await import('sonner')
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('来源=模板'))
    })
    // 跳转后按来源=模板定位：getCards 带 sourceType=template
    await waitFor(() => {
      expect(api.getCards).toHaveBeenCalledWith(expect.objectContaining({ sourceType: 'template' }))
    })
    // 成果物可见：模板卡渲染在列表
    await waitFor(() => {
      expect(screen.getByText('窗帘尺寸测量标准')).toBeInTheDocument()
    })
  })
})
