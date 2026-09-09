// case_ids: ST-001, ST-003, ST-009, ST-010, UI-034, UI-037
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock lucide-react — 覆盖 settings page 使用的图标
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    Building2: stub('building2'),
    Bot: stub('bot'),
    Bell: stub('bell'),
    Save: stub('save'),
    KeyRound: stub('key-round'),
    History: stub('history'),
    ChevronLeft: stub('chevron-left'),
    ChevronRight: stub('chevron-right'),
    Zap: stub('zap'),
    Package: stub('package'),
    Search: stub('search'),
    FileX: stub('file-x'),
    Inbox: stub('inbox'),
    Loader2: stub('loader2'),
  }
})

// Mock request
const mockRequestGet = vi.fn()
const mockRequestPut = vi.fn()
vi.mock('@/lib/request', () => ({
  default: {
    get: (...args: any[]) => mockRequestGet(...args),
    put: (...args: any[]) => mockRequestPut(...args),
  },
}))

// Mock settings API
const mockGetSettings = vi.fn()
const mockUpdateSettings = vi.fn()
const mockGetAiConfig = vi.fn()
const mockUpdateAiConfig = vi.fn()
const mockUploadImage = vi.fn()

vi.mock('@/lib/api', () => ({
  settingsApi: {
    getSettings: (...args: any[]) => mockGetSettings(...args),
    updateSettings: (...args: any[]) => mockUpdateSettings(...args),
    getAiConfig: (...args: any[]) => mockGetAiConfig(...args),
    updateAiConfig: (...args: any[]) => mockUpdateAiConfig(...args),
  },
  uploadApi: {
    uploadImage: (...args: any[]) => mockUploadImage(...args),
  },
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock 图片尺寸读取（jsdom 无法真实解码图片）
const mockReadImageDimensions = vi.fn()
vi.mock('@/lib/image-dimensions', () => ({
  readImageDimensions: (...args: any[]) => mockReadImageDimensions(...args),
}))

// Mock next/navigation（searchParams 可逐用例控制，供 ?tab=ai 直达测试）
const mockRouterPush = vi.fn()
const mockRouterReplace = vi.fn()
const mockSearchParams = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockRouterPush, replace: mockRouterReplace }),
  useSearchParams: () => mockSearchParams(),
}))

// Mock auth store（#3099：保存企业信息后刷新用户信息，侧边栏/右上角即时同步）
const mockFetchUserInfo = vi.fn()
vi.mock('@/store/auth', () => ({
  useAuthStore: Object.assign(() => ({ user: null }), {
    getState: () => ({ fetchUserInfo: mockFetchUserInfo }),
  }),
}))

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: any) => ({
    format: (fmt: string) => date ? '2026-06-19 12:00' : '',
  }),
}))

// Mock sonner
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))
import { toast } from 'sonner'

import SettingsPage from '@/app/(dashboard)/settings/page'

function mockApiSuccess() {
  mockGetSettings.mockResolvedValue({
    data: {
      data: {
        companyName: '测试企业',
        logo: '',
        notificationEnabled: true,
      },
    },
  })
}

function mockAiConfigSuccess() {
  mockGetAiConfig.mockResolvedValue({
    data: {
      data: {
        botName: '小布',
        greetingTemplate: '您好，我是小布，有什么可以帮您？',
      },
    },
  })
}

// #3098: 左侧 tab 导航，切到指定 tab
async function switchToTab(user: ReturnType<typeof userEvent.setup>, label: string) {
  const tab = screen.getByRole('button', { name: new RegExp(label) })
  await user.click(tab)
}

describe('SettingsPage — AI 客服设置合并进企业基础信息 (#3081)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockApiSuccess()
    mockAiConfigSuccess()
    // 默认无 URL tab 参数（默认激活「基本设置」tab）
    mockSearchParams.mockReturnValue(new URLSearchParams())
    // 默认图片尺寸满足最小分辨率（128×128）
    mockReadImageDimensions.mockResolvedValue({ width: 128, height: 128 })
  })

  // ================================================================
  // #3081/#3098: AI 客服配置（原 /chat/config 独立页）合并进企业基础信息，
  // 以左侧 tab 并排展示（基本设置 / AI 客服设置 / 通知设置）
  // ================================================================

  describe('#3081/#3098 AI 客服设置 tab', () => {
    it('tab 导航渲染三个入口：基本设置 / AI 客服设置 / 通知设置（并排展示）', async () => {
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /基本设置/ })).toBeInTheDocument()
      })
      expect(screen.getByRole('button', { name: /AI 客服设置/ })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /通知设置/ })).toBeInTheDocument()
    })

    it('切到「AI 客服设置」tab 渲染区块标题与作用说明（名称+欢迎语，顾客侧可见）', async () => {
      const user = userEvent.setup()
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /AI 客服设置/ })).toBeInTheDocument()
      })
      await switchToTab(user, 'AI 客服设置')
      // 副文案说明作用：配置顾客在对话中看到的 AI 客服助手
      expect(screen.getByText(/配置顾客在对话中看到的 AI 客服助手（小布）的名称与欢迎语/)).toBeInTheDocument()
      // 不再出现「AI 客服配置」独立页面命名
      expect(screen.queryByText('AI 客服配置')).not.toBeInTheDocument()
    })

    it('默认「基本设置」tab 激活，AI 客服设置内容需切换后展示', async () => {
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByText('基本设置', { selector: 'h2' })).toBeInTheDocument()
      })
      // AI 客服设置内容（输入框）默认不展示
      expect(screen.queryByPlaceholderText('小布')).not.toBeInTheDocument()
    })

    it('加载 AI 客服配置并回填 AI 客服名称与欢迎语', async () => {
      const user = userEvent.setup()
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /AI 客服设置/ })).toBeInTheDocument()
      })
      await switchToTab(user, 'AI 客服设置')
      await waitFor(() => {
        expect(screen.getByDisplayValue('小布')).toBeInTheDocument()
      })
      expect(
        screen.getByDisplayValue('您好，我是小布，有什么可以帮您？'),
      ).toBeInTheDocument()
    })

    it('AI 客服名称为空时保存报错且不调用 updateAiConfig', async () => {
      const user = userEvent.setup()
      mockGetAiConfig.mockResolvedValue({
        data: { data: { botName: '  ', greetingTemplate: '' } },
      })
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /AI 客服设置/ })).toBeInTheDocument()
      })
      await switchToTab(user, 'AI 客服设置')
      const saveBtn = await screen.findByRole('button', { name: /保存 AI 客服设置/ })
      await user.click(saveBtn)
      expect(toast.error).toHaveBeenCalledWith('请输入 AI 客服名称')
      expect(mockUpdateAiConfig).not.toHaveBeenCalled()
    })

    it('保存 AI 客服设置 → 调用 updateAiConfig 并提示生效', async () => {
      const user = userEvent.setup()
      mockUpdateAiConfig.mockResolvedValue({ data: {} })
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /AI 客服设置/ })).toBeInTheDocument()
      })
      await switchToTab(user, 'AI 客服设置')
      const input = await screen.findByDisplayValue('小布')
      await user.clear(input)
      await user.type(input, '米高助手')
      await user.click(screen.getByRole('button', { name: /保存 AI 客服设置/ }))
      await waitFor(() => {
        expect(mockUpdateAiConfig).toHaveBeenCalledWith(
          expect.objectContaining({ botName: '米高助手' }),
        )
      })
      expect(toast.success).toHaveBeenCalledWith('AI 客服设置已保存，顾客侧将按新配置生效')
    })

    it('AI 客服设置加载失败 → toast 提示', async () => {
      mockGetAiConfig.mockRejectedValue(new Error('Network error'))
      render(<SettingsPage />)
      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('加载 AI 客服设置失败')
      })
    })
  })

  // ================================================================
  // #3006: 修改密码/登录日志已隐藏 —— 登录日志无记录、未来统一短信码登录
  // ================================================================

  describe('#3006/#3098 企业基础信息页 — 左侧 tab 导航布局（修改密码/登录日志不恢复）', () => {
    it('tab 导航含 基本设置/AI 客服设置/通知设置；修改密码/登录日志不渲染', async () => {
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByText('企业基础信息')).toBeInTheDocument()
      })
      // #3098 恢复 tab 导航：三个 tab 入口并排展示
      expect(screen.getByRole('button', { name: /基本设置/ })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /AI 客服设置/ })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /通知设置/ })).toBeInTheDocument()
      // #3006 已隐藏：登录日志无记录 + 修改密码未来由短信码取替代 → 不再出现这两个 tab
      expect(screen.queryByRole('button', { name: /修改密码/ })).toBeNull()
      expect(screen.queryByRole('button', { name: /登录日志/ })).toBeNull()
      expect(screen.queryByText('暂无登录日志')).toBeNull()
      expect(screen.queryByPlaceholderText('请输入当前密码')).toBeNull()
      // 不应出现 AI 配置 / 账户安全 tab
      expect(screen.queryByRole('button', { name: /AI 配置/ })).toBeNull()
      expect(screen.queryByRole('button', { name: /账户安全/ })).toBeNull()
    })

    it('AI 客服名称输入框在「AI 客服设置」tab 内容区渲染（#3081 合并后不再隐藏）', async () => {
      const user = userEvent.setup()
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /AI 客服设置/ })).toBeInTheDocument()
      })
      await switchToTab(user, 'AI 客服设置')
      expect(screen.getByPlaceholderText('小布')).toBeInTheDocument()
    })
  })

  describe('旧链接 /settings?tab=ai 兼容（#3098 URL tab=ai → 直接激活 AI 客服设置 tab）', () => {
    it('URL 带 ?tab=ai 时默认激活「AI 客服设置」tab（不再重定向）', async () => {
      mockSearchParams.mockReturnValue(new URLSearchParams('tab=ai'))
      render(<SettingsPage />)
      // AI 客服设置内容直接呈现（tab 激活态）
      await waitFor(() => {
        expect(screen.getByPlaceholderText('小布')).toBeInTheDocument()
      })
      // 不再重定向到 /chat/config（该页面已删除）
      expect(mockRouterReplace).not.toHaveBeenCalledWith('/chat/config')
    })
  })

  describe('企业信息 — 功能保留', () => {
    it('公司名称输入框应该可用', async () => {
      render(<SettingsPage />)
      await waitFor(() => {
        // 公司名称在组件中初始为空，API 加载后变为 '测试企业'
        const input = document.querySelector('input[type="text"]')
        expect(input).toBeInTheDocument()
      })
    })

    it('保存设置按钮应该存在（基本设置 tab 默认激活）', async () => {
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /保存设置/ })).toBeInTheDocument()
      })
    })

    it('保存企业信息成功后应刷新用户信息，侧边栏/右上角即时同步（#3099）', async () => {
      const user = userEvent.setup()
      mockUpdateSettings.mockResolvedValue({ data: { data: {} } })
      render(<SettingsPage />)
      await waitFor(() => {
        // #3100 tab 布局：企业信息区块按钮名为「保存设置」（原「保存企业信息」）
        expect(screen.getByRole('button', { name: /保存设置/ })).toBeInTheDocument()
      })
      await user.click(screen.getByRole('button', { name: /保存设置/ }))
      await waitFor(() => {
        expect(mockUpdateSettings).toHaveBeenCalled()
      })
      // 保存成功后必须拉取最新用户信息（含企业名/Logo），否则侧边栏不刷新（#3099 修复）
      await waitFor(() => {
        expect(mockFetchUserInfo).toHaveBeenCalledTimes(1)
      })
    })
  })

  // ================================================================
  // Logo 上传 — Issue #645: 上传 Logo 按钮无 onClick，点击无反应
  // ================================================================

  describe('Logo 上传 — 企业信息区块', () => {
    it('点击「上传 Logo」按钮应触发隐藏文件输入', async () => {
      const user = userEvent.setup()
      render(<SettingsPage />)

      // 确保企业信息区块已加载
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /上传 Logo/ })).toBeInTheDocument()
      })

      // 验证隐藏的 file input 存在
      const fileInput = document.querySelector('input[type="file"]')
      expect(fileInput).toBeInTheDocument()
      expect(fileInput).toHaveAttribute('accept', expect.stringContaining('image'))
    })

    it('点击按钮 → fileInputRef.click() 被调用', async () => {
      const user = userEvent.setup()
      // Spy on HTMLInputElement.prototype.click 验证按钮点击链
      const clickSpy = vi.spyOn(HTMLInputElement.prototype, 'click')

      render(<SettingsPage />)

      const uploadBtn = await screen.findByRole('button', { name: /上传 Logo/ })
      await user.click(uploadBtn)

      // 修复后：按钮 onClick 应调用 fileInputRef.current?.click()
      expect(clickSpy).toHaveBeenCalled()

      clickSpy.mockRestore()
    })

    it('选择图片文件后应调用 uploadApi.uploadImage', async () => {
      const user = userEvent.setup()
      mockUploadImage.mockResolvedValue({
        data: { data: { url: 'https://oss.example.com/logos/test.png', id: 'f1' } },
      })

      render(<SettingsPage />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /上传 Logo/ })).toBeInTheDocument()
      })

      // 模拟文件选择
      const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
      const file = new File(['dummy'], 'logo.png', { type: 'image/png' })
      await user.upload(fileInput, file)

      // 验证 uploadApi.uploadImage 被调用
      await waitFor(() => {
        expect(mockUploadImage).toHaveBeenCalledWith(file)
      })
    })

    it('上传中按钮应显示 loading 态', async () => {
      const user = userEvent.setup()
      // 让 upload 不立即 resolve，模拟上传中
      let resolveUpload: (value: unknown) => void
      const uploadPromise = new Promise((resolve) => { resolveUpload = resolve })
      mockUploadImage.mockReturnValue(uploadPromise)

      render(<SettingsPage />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /上传 Logo/ })).toBeInTheDocument()
      })

      const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
      const file = new File(['dummy'], 'logo.png', { type: 'image/png' })
      await user.upload(fileInput, file)

      // 上传中按钮应处于 disabled 状态
      await waitFor(() => {
        const btn = screen.getByRole('button', { name: /上传 Logo/ })
        expect(btn).toBeDisabled()
      })

      // 完成上传
      resolveUpload!({ data: { data: { url: 'https://oss.example.com/logos/test.png', id: 'f1' } } })
      await waitFor(() => {
        const btn = screen.getByRole('button', { name: /上传 Logo/ })
        expect(btn).not.toBeDisabled()
      })
    })

    it('不支持的图片格式应 toast 报错', async () => {
      const { toast } = await import('sonner')

      render(<SettingsPage />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /上传 Logo/ })).toBeInTheDocument()
      })

      // 使用 fireEvent 绕过 user-event 对 accept 属性的浏览器级校验
      // 验证 JS 层防御性校验：text/plain 应被 handleLogoUpload 拦截
      const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
      const file = new File(['text'], 'doc.txt', { type: 'text/plain' })
      fireEvent.change(fileInput, { target: { files: [file] } })

      // toast.error 应被调用（JS 层格式校验）
      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('格式'))
      })

      // uploadApi.uploadImage 不应被调用
      expect(mockUploadImage).not.toHaveBeenCalled()
    })

    it('超过 5MB 文件应 toast 报错', async () => {
      const user = userEvent.setup()
      const { toast } = await import('sonner')

      render(<SettingsPage />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /上传 Logo/ })).toBeInTheDocument()
      })

      // 创建超过 5MB 的文件
      const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
      const largeFile = new File(['x'.repeat(6 * 1024 * 1024)], 'large.png', { type: 'image/png' })
      await user.upload(fileInput, largeFile)

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('5MB'))
      })

      expect(mockUploadImage).not.toHaveBeenCalled()
    })

    it('分辨率过低（<128px）应 toast 报错且不调用上传接口', async () => {
      const user = userEvent.setup()
      const { toast } = await import('sonner')
      mockReadImageDimensions.mockResolvedValue({ width: 64, height: 64 })

      render(<SettingsPage />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /上传 Logo/ })).toBeInTheDocument()
      })

      const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
      const file = new File(['dummy'], 'small.png', { type: 'image/png' })
      await user.upload(fileInput, file)

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('分辨率过低'))
      })
      expect(mockReadImageDimensions).toHaveBeenCalled()
      expect(mockUploadImage).not.toHaveBeenCalled()
    })

    it('分辨率满足最小要求（≥128px）时可正常上传', async () => {
      const user = userEvent.setup()
      mockReadImageDimensions.mockResolvedValue({ width: 512, height: 256 })
      mockUploadImage.mockResolvedValue({ data: { data: { url: 'https://oss.example.com/ok.png', id: 'f3' } } })

      render(<SettingsPage />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /上传 Logo/ })).toBeInTheDocument()
      })

      const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
      const file = new File(['dummy'], 'wide.png', { type: 'image/png' })
      await user.upload(fileInput, file)

      await waitFor(() => {
        expect(mockUploadImage).toHaveBeenCalledWith(file)
      })
    })

    it('上传成功后应更新 Logo 预览', async () => {
      const user = userEvent.setup()
      const logoUrl = 'https://oss.example.com/logos/company-logo.png'
      mockUploadImage.mockResolvedValue({
        data: { data: { url: logoUrl, id: 'f2' } },
      })

      render(<SettingsPage />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /上传 Logo/ })).toBeInTheDocument()
      })

      // Logo 预览区初始为占位图标（data-testid 来自 lucide-react mock）
      const initialPlaceholder = document.querySelector('[data-testid="icon-building2"]')
      expect(initialPlaceholder).toBeInTheDocument()

      // 选择并上传文件
      const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
      const file = new File(['dummy'], 'logo.png', { type: 'image/png' })
      await user.upload(fileInput, file)

      // 上传成功后，Image 组件应渲染（通过 alt="Logo" 查找）
      await waitFor(() => {
        const logoImg = screen.getByAltText('Logo')
        expect(logoImg).toBeInTheDocument()
        expect(logoImg).toHaveAttribute('src', logoUrl)
      })
    })

    it('未设置 Logo 时展示占位图标（不渲染 img）', async () => {
      mockGetSettings.mockResolvedValue({
        data: { data: { companyName: '测试企业', logo: '', notificationEnabled: false } },
      })
      render(<SettingsPage />)
      await waitFor(() => {
        expect(document.querySelector('[data-testid="icon-building2"]')).toBeInTheDocument()
      })
      expect(screen.queryByAltText('Logo')).not.toBeInTheDocument()
    })

    it('已设置 Logo 时可点击「移除 Logo」回到未设置状态（保存后落库为 NULL）', async () => {
      const user = userEvent.setup()
      mockGetSettings.mockResolvedValue({
        data: { data: { companyName: '测试企业', logo: 'https://oss.example.com/logo.png', notificationEnabled: false } },
      })
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByAltText('Logo')).toBeInTheDocument()
      })
      expect(screen.getByRole('button', { name: /移除 Logo/ })).toBeInTheDocument()

      await user.click(screen.getByRole('button', { name: /移除 Logo/ }))

      // 预览回到占位图标
      await waitFor(() => {
        expect(document.querySelector('[data-testid="icon-building2"]')).toBeInTheDocument()
      })
      expect(screen.queryByAltText('Logo')).not.toBeInTheDocument()
    })

    it('Logo 加载失败时预览回退到占位图标', async () => {
      mockGetSettings.mockResolvedValue({
        data: { data: { companyName: '测试企业', logo: 'https://broken.example.com/expired.png', notificationEnabled: false } },
      })
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByAltText('Logo')).toBeInTheDocument()
      })
      // 模拟图片加载失败
      fireEvent.error(screen.getByAltText('Logo'))
      await waitFor(() => {
        expect(document.querySelector('[data-testid="icon-building2"]')).toBeInTheDocument()
      })
    })
  })

  // ── #3003 系统通知开关 —— 描述与实际行为一致（租户级自动站内信总开关）──

  describe('通知设置 — 启用系统通知（#3098 通知设置独立 tab）', () => {
    it('渲染开关与口径说明（关闭后不再产生新的站内通知，历史保留）', async () => {
      const user = userEvent.setup()
      mockGetSettings.mockResolvedValue({
        data: { data: { companyName: '测试企业', logo: '', notificationEnabled: true } },
      })
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /通知设置/ })).toBeInTheDocument()
      })
      await switchToTab(user, '通知设置')
      await waitFor(() => {
        expect(screen.getByText('启用系统通知')).toBeInTheDocument()
      })
      // #3003：描述与后端接线一致（tenants.notification_enabled 控制自动站内信），
      // 不再出现「（当前为站内通知开关）」这种含糊/与实际脱节的文案
      expect(screen.getByText(/关闭后不再产生新的站内通知（历史通知保留）/)).toBeInTheDocument()
      expect(screen.queryByText(/当前为站内通知开关/)).not.toBeInTheDocument()
      // #3103：通知邮箱为僵尸字段（站内信无需邮箱）——不再渲染邮箱输入框
      expect(screen.queryByText('通知邮箱')).not.toBeInTheDocument()
      expect(screen.queryByPlaceholderText(/接收通知的邮箱地址/)).not.toBeInTheDocument()
    })

    it('保存通知设置按钮存在（#3081 分区块保存）', async () => {
      const user = userEvent.setup()
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /通知设置/ })).toBeInTheDocument()
      })
      await switchToTab(user, '通知设置')
      expect(screen.getByRole('button', { name: /保存通知设置/ })).toBeInTheDocument()
    })
  })
})
