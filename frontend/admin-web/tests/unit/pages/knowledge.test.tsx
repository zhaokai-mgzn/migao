import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock API
vi.mock('@/lib/api', () => ({
  knowledgeApi: {},
}))

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: any) => ({
    format: () => date || '2026-04-15 10:30',
  }),
}))

// Mock sonner
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Mock UI components
vi.mock('@/components/ui', () => ({
  Table: ({ columns, dataSource, loading, rowKey }: any) => (
    <div data-testid="table">
      {loading && <div data-testid="table-loading">加载中...</div>}
      {dataSource?.map((record: any) => (
        <div key={record[rowKey || 'id']} data-testid={`row-${record.id}`}>
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
  Modal: ({ open, title, children, footer }: any) =>
    open ? (
      <div data-testid="modal" role="dialog">
        <h2>{title}</h2>
        {children}
        <div data-testid="modal-footer">{footer}</div>
      </div>
    ) : null,
  Button: ({ children, onClick, variant, ...props }: any) => (
    <button onClick={onClick} data-variant={variant} {...props}>{children}</button>
  ),
  Badge: ({ children, variant }: any) => (
    <span data-testid="badge" data-variant={variant}>{children}</span>
  ),
  SearchBar: ({ fields, onSearch, onReset, loading }: any) => (
    <div data-testid="search-bar">
      <button onClick={() => onSearch({})} data-testid="search-btn">搜索</button>
      <button onClick={onReset} data-testid="reset-btn">重置</button>
    </div>
  ),
}))

import KnowledgePage from '@/app/(dashboard)/knowledge/page'

describe('KnowledgePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should render page title', async () => {
    render(<KnowledgePage />)
    await waitFor(() => {
      expect(screen.getByText('知识库管理')).toBeInTheDocument()
    })
  })

  it('should render page description', async () => {
    render(<KnowledgePage />)
    await waitFor(() => {
      expect(screen.getByText('管理 AI 客服的知识库文档和问答')).toBeInTheDocument()
    })
  })

  it('should render upload document button', async () => {
    render(<KnowledgePage />)
    await waitFor(() => {
      expect(screen.getByText('上传文档')).toBeInTheDocument()
    })
  })

  it('should render search test button', async () => {
    render(<KnowledgePage />)
    await waitFor(() => {
      expect(screen.getByText('搜索测试')).toBeInTheDocument()
    })
  })

  it('should display mock documents in table', async () => {
    render(<KnowledgePage />)
    await waitFor(() => {
      expect(screen.getByText('窗帘常见问题 FAQ')).toBeInTheDocument()
      expect(screen.getByText('产品目录 2026')).toBeInTheDocument()
      expect(screen.getByText('窗帘尺寸测量指南')).toBeInTheDocument()
    })
  })

  it('should open upload modal when upload button clicked', async () => {
    const user = userEvent.setup()
    render(<KnowledgePage />)
    await waitFor(() => {
      expect(screen.getByText('上传文档')).toBeInTheDocument()
    })
    // 点击"上传文档"按钮（Modal 标题也是"上传文档"，用 role 区分）
    const uploadBtn = screen.getByRole('button', { name: /上传文档/ })
    await user.click(uploadBtn)
    // Modal 渲染后 modal 标题会再次出现
    await waitFor(() => {
      const modals = screen.queryAllByTestId('modal')
      expect(modals.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('should open search test modal when search test button clicked', async () => {
    const user = userEvent.setup()
    render(<KnowledgePage />)
    await waitFor(() => {
      expect(screen.getByText('搜索测试')).toBeInTheDocument()
    })
    await user.click(screen.getByText('搜索测试'))
    await waitFor(() => {
      const searchInput = document.querySelector('input[placeholder*="输入搜索内容"]')
      expect(searchInput).toBeInTheDocument()
    })
  })

  it('should render search bar with filters', async () => {
    render(<KnowledgePage />)
    await waitFor(() => {
      expect(screen.getByTestId('search-bar')).toBeInTheDocument()
    })
  })
})
