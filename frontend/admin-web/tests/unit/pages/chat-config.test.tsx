// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ================================================================
// Mock API modules
// ================================================================
// (lucide-react icons used by this page — Bot, MessageSquare, Save,
//  Plus, Trash2, Edit3, X, Check, Zap, Loader2 — are already
//  covered by the global mock in tests/setup.ts)
const mockGetAiConfig = vi.fn()
const mockUpdateAiConfig = vi.fn()
const mockGetTemplates = vi.fn()
const mockCreateTemplate = vi.fn()
const mockUpdateTemplate = vi.fn()
const mockDeleteTemplate = vi.fn()

vi.mock('@/lib/api', () => ({
  settingsApi: {
    getAiConfig: (...args: any[]) => mockGetAiConfig(...args),
    updateAiConfig: (...args: any[]) => mockUpdateAiConfig(...args),
  },
  quickReplyApi: {
    getTemplates: (...args: any[]) => mockGetTemplates(...args),
    createTemplate: (...args: any[]) => mockCreateTemplate(...args),
    updateTemplate: (...args: any[]) => mockUpdateTemplate(...args),
    deleteTemplate: (...args: any[]) => mockDeleteTemplate(...args),
  },
}))

// ================================================================
// Now import the page under test (after all mocks)
// ================================================================
import ChatConfigPage from '@/app/(dashboard)/chat/config/page'
import { toast } from 'sonner'

// ================================================================
// Helpers
// ================================================================

function mockBasicSuccess() {
  mockGetAiConfig.mockResolvedValue({
    data: {
      data: {
        botName: '小布',
        greetingTemplate: '您好，我是小布，有什么可以帮您？',
      },
    },
  })
}

function mockTemplatesSuccess(templates?: any[]) {
  mockGetTemplates.mockResolvedValue({
    data: {
      data: {
        items: templates ?? [
          {
            id: 't1',
            title: '欢迎语',
            content: '欢迎光临米高布艺！',
            category: '通用',
            usageCount: 5,
            updatedAt: '2026-06-15T08:00:00Z',
          },
          {
            id: 't2',
            title: '尺码咨询',
            content: '请问您需要什么尺寸？',
            category: '咨询',
            shortcut: '/sz',
            usageCount: 10,
            updatedAt: '2026-06-14T10:00:00Z',
          },
        ],
      },
    },
  })
}

// ================================================================
// Tests
// ================================================================

describe('ChatConfigPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockBasicSuccess()
    mockTemplatesSuccess()
  })

  // ──────────────────────────────────────────────────────────────
  // Page rendering
  // ──────────────────────────────────────────────────────────────

  it('should render page title and description', async () => {
    render(<ChatConfigPage />)

    await waitFor(() => {
      expect(screen.getByText('机器人设置')).toBeInTheDocument()
    })
    expect(
      screen.getByText(/配置小布机器人的名称、欢迎语和快捷回复/),
    ).toBeInTheDocument()
  })

  it('should render both tab buttons', async () => {
    render(<ChatConfigPage />)

    await waitFor(() => {
      expect(screen.getByText('机器人设置')).toBeInTheDocument()
    })

    expect(screen.getByRole('button', { name: /基础设置/ })).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /快捷回复/ }),
    ).toBeInTheDocument()
  })

  it('should render basic settings tab content by default', async () => {
    render(<ChatConfigPage />)

    await waitFor(() => {
      expect(screen.getByText('基础设置', { selector: 'h2' })).toBeInTheDocument()
    })
  })

  // ──────────────────────────────────────────────────────────────
  // Basic settings: loading
  // ──────────────────────────────────────────────────────────────

  it('should show loading state while fetching AI config', () => {
    // Do NOT resolve getAiConfig — stays in loading
    mockGetAiConfig.mockReturnValue(new Promise(() => {}))
    render(<ChatConfigPage />)

    expect(screen.getByText('加载中...')).toBeInTheDocument()
  })

  // ──────────────────────────────────────────────────────────────
  // Basic settings: loaded state
  // ──────────────────────────────────────────────────────────────

  it('should display bot name input with loaded value', async () => {
    render(<ChatConfigPage />)

    await waitFor(() => {
      const input = screen.getByDisplayValue('小布')
      expect(input).toBeInTheDocument()
    })
  })

  it('should display greeting template textarea with loaded value', async () => {
    render(<ChatConfigPage />)

    await waitFor(() => {
      const textarea = screen.getByDisplayValue('您好，我是小布，有什么可以帮您？')
      expect(textarea).toBeInTheDocument()
    })
  })

  it('should render save button in basic settings', async () => {
    render(<ChatConfigPage />)

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /保存设置/ }),
      ).toBeInTheDocument()
    })
  })

  it('should show API error toast when loading fails', async () => {
    mockGetAiConfig.mockRejectedValue(new Error('Network error'))
    render(<ChatConfigPage />)

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('加载 AI 配置失败')
    })
  })

  // ──────────────────────────────────────────────────────────────
  // Basic settings: validation
  // ──────────────────────────────────────────────────────────────

  it('should show error when saving with empty bot name', async () => {
    const user = userEvent.setup()
    // load with empty botName
    mockGetAiConfig.mockResolvedValue({
      data: { data: { botName: '', greetingTemplate: '' } },
    })

    render(<ChatConfigPage />)

    // Wait for the rendered form
    const saveBtn = await screen.findByRole('button', { name: /保存设置/ })

    await user.click(saveBtn)

    expect(toast.error).toHaveBeenCalledWith('请输入机器人名称')
    expect(mockUpdateAiConfig).not.toHaveBeenCalled()
  })

  it('should show error when saving with whitespace-only bot name', async () => {
    const user = userEvent.setup()
    mockGetAiConfig.mockResolvedValue({
      data: { data: { botName: '   ', greetingTemplate: '' } },
    })

    render(<ChatConfigPage />)

    const saveBtn = await screen.findByRole('button', { name: /保存设置/ })

    await user.click(saveBtn)

    expect(toast.error).toHaveBeenCalledWith('请输入机器人名称')
    expect(mockUpdateAiConfig).not.toHaveBeenCalled()
  })

  // ──────────────────────────────────────────────────────────────
  // Basic settings: save success / failure
  // ──────────────────────────────────────────────────────────────

  it('should call updateAiConfig and show success toast on save', async () => {
    const user = userEvent.setup()
    mockUpdateAiConfig.mockResolvedValue({ data: {} })

    render(<ChatConfigPage />)

    const saveBtn = await screen.findByRole('button', { name: /保存设置/ })

    await user.click(saveBtn)

    await waitFor(() => {
      expect(mockUpdateAiConfig).toHaveBeenCalledWith({
        botName: '小布',
        greetingTemplate: '您好，我是小布，有什么可以帮您？',
      })
    })
    expect(toast.success).toHaveBeenCalledWith('机器人配置已保存')
  })

  it('should show error toast when save fails', async () => {
    const user = userEvent.setup()
    mockUpdateAiConfig.mockRejectedValue(new Error('Save failed'))

    render(<ChatConfigPage />)

    const saveBtn = await screen.findByRole('button', { name: /保存设置/ })

    await user.click(saveBtn)

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('保存失败')
    })
  })

  it('should update bot name when user types in input', async () => {
    const user = userEvent.setup()
    render(<ChatConfigPage />)

    const input = await screen.findByDisplayValue('小布')

    await user.clear(input)
    await user.type(input, '米高助手')

    expect(input).toHaveDisplayValue('米高助手')

    // Click save and verify the updated value is sent
    mockUpdateAiConfig.mockResolvedValue({ data: {} })
    const saveBtn = screen.getByRole('button', { name: /保存设置/ })
    await user.click(saveBtn)

    await waitFor(() => {
      expect(mockUpdateAiConfig).toHaveBeenCalledWith(
        expect.objectContaining({ botName: '米高助手' }),
      )
    })
  })

  it('should update greeting template when user types in textarea', async () => {
    const user = userEvent.setup()
    render(<ChatConfigPage />)

    const textarea = await screen.findByDisplayValue(
      '您好，我是小布，有什么可以帮您？',
    )

    await user.clear(textarea)
    await user.type(textarea, '欢迎光临！')

    expect(textarea).toHaveDisplayValue('欢迎光临！')

    mockUpdateAiConfig.mockResolvedValue({ data: {} })
    const saveBtn = screen.getByRole('button', { name: /保存设置/ })
    await user.click(saveBtn)

    await waitFor(() => {
      expect(mockUpdateAiConfig).toHaveBeenCalledWith(
        expect.objectContaining({ greetingTemplate: '欢迎光临！' }),
      )
    })
  })

  // ──────────────────────────────────────────────────────────────
  // Tab switching
  // ──────────────────────────────────────────────────────────────

  it('should switch to quick-replies tab on click', async () => {
    const user = userEvent.setup()
    // Return empty templates to make sure the empty state shows clearly
    mockGetTemplates.mockResolvedValue({
      data: { data: { items: [] } },
    })

    render(<ChatConfigPage />)

    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /快捷回复/ })).toBeInTheDocument()
    })

    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    // Quick reply heading should be visible
    await waitFor(() => {
      expect(screen.getByText('快捷回复', { selector: 'h2' })).toBeInTheDocument()
    })

    // Loads templates on tab switch
    expect(mockGetTemplates).toHaveBeenCalledWith({ page: 1, size: 100 })
  })

  // ──────────────────────────────────────────────────────────────
  // Quick replies: loading state
  // ──────────────────────────────────────────────────────────────

  it('should show loading state while fetching templates', async () => {
    const user = userEvent.setup()
    // Never resolve
    mockGetTemplates.mockReturnValue(new Promise(() => {}))

    render(<ChatConfigPage />)

    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    // Should see loading text
    await waitFor(() => {
      expect(screen.getByText('加载中...')).toBeInTheDocument()
    })
  })

  // ──────────────────────────────────────────────────────────────
  // Quick replies: empty state
  // ──────────────────────────────────────────────────────────────

  it('should show empty state when no templates exist', async () => {
    const user = userEvent.setup()
    mockGetTemplates.mockResolvedValue({
      data: { data: { items: [] } },
    })

    render(<ChatConfigPage />)

    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    await waitFor(() => {
      expect(screen.getByText('暂无快捷回复')).toBeInTheDocument()
    })
  })

  // ──────────────────────────────────────────────────────────────
  // Quick replies: template list
  // ──────────────────────────────────────────────────────────────

  it('should render template list with titles and categories', async () => {
    const user = userEvent.setup()

    render(<ChatConfigPage />)

    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    await waitFor(() => {
      expect(screen.getByText('欢迎语')).toBeInTheDocument()
      expect(screen.getByText('尺码咨询')).toBeInTheDocument()
    })

    // Categories as badges
    expect(screen.getByText('通用')).toBeInTheDocument()
    expect(screen.getByText('咨询')).toBeInTheDocument()

    // Content preview
    expect(screen.getByText('欢迎光临米高布艺！')).toBeInTheDocument()
    expect(screen.getByText('请问您需要什么尺寸？')).toBeInTheDocument()
  })

  it('should show shortcut badge when template has shortcut', async () => {
    const user = userEvent.setup()

    render(<ChatConfigPage />)

    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    await waitFor(() => {
      // t2 has shortcut '/sz'
      expect(screen.getByText('/sz')).toBeInTheDocument()
    })
  })

  it('should not show shortcut badge when template has no shortcut', async () => {
    const user = userEvent.setup()
    mockGetTemplates.mockResolvedValue({
      data: {
        data: {
          items: [
            {
              id: 't1',
              title: '欢迎语',
              content: '欢迎！',
              category: '通用',
              usageCount: 2,
              updatedAt: '2026-06-15T08:00:00Z',
            },
          ],
        },
      },
    })

    render(<ChatConfigPage />)
    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    await waitFor(() => {
      expect(screen.getByText('欢迎语')).toBeInTheDocument()
    })

    // No shortcut badge since shortcut is undefined
    // The icon testid for Zap (empty state) should still exist on the
    // "empty" paragraph, but not as a shortcut badge
    const iconZapElements = document.querySelectorAll('[data-testid="icon-zap"]')
    // all zap icons are from the empty state (not rendered here)
    expect(
      document.querySelector('span[class*="font-mono"]'),
    ).not.toBeInTheDocument()
  })

  it('should display usage count and updated date', async () => {
    const user = userEvent.setup()

    render(<ChatConfigPage />)
    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    await waitFor(() => {
      expect(screen.getByText('使用 5 次')).toBeInTheDocument()
      expect(screen.getByText('使用 10 次')).toBeInTheDocument()
    })
  })

  // ──────────────────────────────────────────────────────────────
  // Quick replies: create form
  // ──────────────────────────────────────────────────────────────

  it('should show create form when clicking "新建回复"', async () => {
    const user = userEvent.setup()

    render(<ChatConfigPage />)
    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    const newBtn = await screen.findByRole('button', { name: /新建回复/ })
    await user.click(newBtn)

    // Create form fields should appear
    expect(screen.getByText('新建快捷回复')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('例如：欢迎语')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('输入快捷回复内容...')).toBeInTheDocument()
  })

  it('should hide create form when toggling "新建回复" again', async () => {
    const user = userEvent.setup()

    render(<ChatConfigPage />)
    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    const newBtn = await screen.findByRole('button', { name: /新建回复/ })
    await user.click(newBtn)
    expect(screen.getByText('新建快捷回复')).toBeInTheDocument()

    await user.click(newBtn)
    await waitFor(() => {
      expect(screen.queryByText('新建快捷回复')).not.toBeInTheDocument()
    })
  })

  it('should hide create form when clicking cancel', async () => {
    const user = userEvent.setup()

    render(<ChatConfigPage />)
    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    const newBtn = await screen.findByRole('button', { name: /新建回复/ })
    await user.click(newBtn)

    const cancelBtn = screen.getByRole('button', { name: /取消/ })
    await user.click(cancelBtn)

    await waitFor(() => {
      expect(screen.queryByText('新建快捷回复')).not.toBeInTheDocument()
    })
  })

  it('should show validation error for empty create form', async () => {
    const user = userEvent.setup()

    render(<ChatConfigPage />)
    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    const newBtn = await screen.findByRole('button', { name: /新建回复/ })
    await user.click(newBtn)

    // Click create without filling fields
    const createBtn = screen.getByRole('button', { name: /确认创建/ })
    await user.click(createBtn)

    expect(toast.error).toHaveBeenCalledWith('请输入标题和回复内容')
    expect(mockCreateTemplate).not.toHaveBeenCalled()
  })

  it('should successfully create a quick reply template', async () => {
    const user = userEvent.setup()
    mockCreateTemplate.mockResolvedValue({ data: {} })

    render(<ChatConfigPage />)
    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    const newBtn = await screen.findByRole('button', { name: /新建回复/ })
    await user.click(newBtn)

    // Fill form
    await user.type(screen.getByPlaceholderText('例如：欢迎语'), '测试标题')
    await user.type(
      screen.getByPlaceholderText('输入快捷回复内容...'),
      '测试内容',
    )

    const createBtn = screen.getByRole('button', { name: /确认创建/ })
    await user.click(createBtn)

    await waitFor(() => {
      expect(mockCreateTemplate).toHaveBeenCalledWith({
        title: '测试标题',
        content: '测试内容',
        category: '通用',
      })
    })
    expect(toast.success).toHaveBeenCalledWith('快捷回复已创建')

    // Should reload templates after create
    expect(mockGetTemplates).toHaveBeenCalledTimes(2) // initial + after create
  })

  it('should show error toast when create fails', async () => {
    const user = userEvent.setup()
    mockCreateTemplate.mockRejectedValue(new Error('Create failed'))

    render(<ChatConfigPage />)
    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    const newBtn = await screen.findByRole('button', { name: /新建回复/ })
    await user.click(newBtn)

    // Fill form
    await user.type(screen.getByPlaceholderText('例如：欢迎语'), '测试标题')
    await user.type(
      screen.getByPlaceholderText('输入快捷回复内容...'),
      '测试内容',
    )

    const createBtn = screen.getByRole('button', { name: /确认创建/ })
    await user.click(createBtn)

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('创建失败')
    })
  })

  // ──────────────────────────────────────────────────────────────
  // Quick replies: edit mode
  // ──────────────────────────────────────────────────────────────

  it('should enter edit mode when clicking edit button', async () => {
    const user = userEvent.setup()

    render(<ChatConfigPage />)
    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    // Wait for templates to load
    await waitFor(() => {
      expect(screen.getByText('欢迎语')).toBeInTheDocument()
    })

    // Find and click edit button on the first template
    const editButtons = screen.getAllByTitle('编辑')
    await user.click(editButtons[0])

    // Edit form fields should show with current values
    await waitFor(() => {
      const titleInputs = screen.getAllByDisplayValue('欢迎语')
      expect(titleInputs.length).toBeGreaterThan(0)
    })
  })

  it('should cancel edit mode', async () => {
    const user = userEvent.setup()

    render(<ChatConfigPage />)
    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    await waitFor(() => {
      expect(screen.getByText('欢迎语')).toBeInTheDocument()
    })

    // Enter edit mode
    const editButtons = screen.getAllByTitle('编辑')
    await user.click(editButtons[0])

    // Click cancel button in edit form
    const cancelBtns = screen.getAllByRole('button', { name: /取消/ })
    // Filter for the one in edit form (not create form)
    const editCancelBtn = cancelBtns[0]
    await user.click(editCancelBtn)

    // Should be back to display mode
    await waitFor(() => {
      // The template title should still be visible in display mode
      expect(screen.getByText('欢迎语')).toBeInTheDocument()
      // Edit input should be gone
      expect(screen.queryByDisplayValue('欢迎语')).not.toBeInTheDocument()
    })
  })

  it('should show validation error for empty edit fields', async () => {
    const user = userEvent.setup()

    render(<ChatConfigPage />)
    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    await waitFor(() => {
      expect(screen.getByText('欢迎语')).toBeInTheDocument()
    })

    // Enter edit mode
    const editButtons = screen.getAllByTitle('编辑')
    await user.click(editButtons[0])

    // Clear title input
    const titleInput = screen.getByDisplayValue('欢迎语')
    await user.clear(titleInput)

    // Click save
    const saveBtn = screen.getByRole('button', { name: /保存/ })
    await user.click(saveBtn)

    expect(toast.error).toHaveBeenCalledWith('请输入标题和回复内容')
    expect(mockUpdateTemplate).not.toHaveBeenCalled()
  })

  it('should successfully update a template', async () => {
    const user = userEvent.setup()
    mockUpdateTemplate.mockResolvedValue({ data: {} })

    render(<ChatConfigPage />)
    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    await waitFor(() => {
      expect(screen.getByText('欢迎语')).toBeInTheDocument()
    })

    // Enter edit mode
    const editButtons = screen.getAllByTitle('编辑')
    await user.click(editButtons[0])

    // Modify title
    const titleInput = screen.getByDisplayValue('欢迎语')
    await user.clear(titleInput)
    await user.type(titleInput, '新标题')

    // Click save
    const saveBtn = screen.getByRole('button', { name: /保存/ })
    await user.click(saveBtn)

    await waitFor(() => {
      expect(mockUpdateTemplate).toHaveBeenCalledWith('t1', {
        title: '新标题',
        content: '欢迎光临米高布艺！',
        category: '通用',
      })
    })
    expect(toast.success).toHaveBeenCalledWith('快捷回复已更新')
  })

  it('should show error toast when update fails', async () => {
    const user = userEvent.setup()
    mockUpdateTemplate.mockRejectedValue(new Error('Update failed'))

    render(<ChatConfigPage />)
    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    await waitFor(() => {
      expect(screen.getByText('欢迎语')).toBeInTheDocument()
    })

    const editButtons = screen.getAllByTitle('编辑')
    await user.click(editButtons[0])

    const saveBtn = screen.getByRole('button', { name: /保存/ })
    await user.click(saveBtn)

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('更新失败')
    })
  })

  // ──────────────────────────────────────────────────────────────
  // Quick replies: delete
  // ──────────────────────────────────────────────────────────────

  it('should show confirm dialog when deleting a template', async () => {
    const user = userEvent.setup()
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)

    render(<ChatConfigPage />)
    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    await waitFor(() => {
      expect(screen.getByText('欢迎语')).toBeInTheDocument()
    })

    const deleteButtons = screen.getAllByTitle('删除')
    await user.click(deleteButtons[0])

    expect(confirmSpy).toHaveBeenCalledWith(
      expect.stringContaining('欢迎语'),
    )
    // User cancelled => deleteTemplate NOT called
    expect(mockDeleteTemplate).not.toHaveBeenCalled()

    confirmSpy.mockRestore()
  })

  it('should delete a template when user confirms', async () => {
    const user = userEvent.setup()
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    mockDeleteTemplate.mockResolvedValue({ data: {} })

    render(<ChatConfigPage />)
    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    await waitFor(() => {
      expect(screen.getByText('欢迎语')).toBeInTheDocument()
    })

    const deleteButtons = screen.getAllByTitle('删除')
    await user.click(deleteButtons[0])

    await waitFor(() => {
      expect(mockDeleteTemplate).toHaveBeenCalledWith('t1')
    })
    expect(toast.success).toHaveBeenCalledWith('已删除')

    confirmSpy.mockRestore()
  })

  it('should show error toast when delete fails', async () => {
    const user = userEvent.setup()
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    mockDeleteTemplate.mockRejectedValue(new Error('Delete failed'))

    render(<ChatConfigPage />)
    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    await waitFor(() => {
      expect(screen.getByText('欢迎语')).toBeInTheDocument()
    })

    const deleteButtons = screen.getAllByTitle('删除')
    await user.click(deleteButtons[0])

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('删除失败')
    })

    confirmSpy.mockRestore()
  })

  // ──────────────────────────────────────────────────────────────
  // Quick replies: load error
  // ──────────────────────────────────────────────────────────────

  it('should show error toast when template loading fails', async () => {
    const user = userEvent.setup()
    mockGetTemplates.mockRejectedValue(new Error('Load failed'))

    render(<ChatConfigPage />)
    const quickReplyTab = screen.getByRole('button', { name: /快捷回复/ })
    await user.click(quickReplyTab)

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('加载快捷回复失败')
    })
  })

  // ──────────────────────────────────────────────────────────────
  // Combined workflow
  // ──────────────────────────────────────────────────────────────

  it('full workflow: switch tabs → save basic config → load quick replies list', async () => {
    const user = userEvent.setup()

    render(<ChatConfigPage />)

    // 1. Basic settings tab loads by default
    await waitFor(() => {
      expect(screen.getByDisplayValue('小布')).toBeInTheDocument()
    })
    expect(mockGetAiConfig).toHaveBeenCalledTimes(1)

    // 2. Modify bot name and save
    const botInput = screen.getByDisplayValue('小布')
    await user.clear(botInput)
    await user.type(botInput, '智能助手')
    mockUpdateAiConfig.mockResolvedValue({ data: {} })

    await user.click(screen.getByRole('button', { name: /保存设置/ }))

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith('机器人配置已保存')
    })

    // 3. Switch to quick replies tab
    await user.click(screen.getByRole('button', { name: /快捷回复/ }))

    await waitFor(() => {
      expect(mockGetTemplates).toHaveBeenCalledWith({ page: 1, size: 100 })
      expect(screen.getByText('欢迎语')).toBeInTheDocument()
    })
  })
})
