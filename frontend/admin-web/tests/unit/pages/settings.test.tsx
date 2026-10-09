// case_ids: AU-009, ST-001, ST-003, ST-009, ST-010, UI-034, UI-037, UI-054, UI-064, PG-045
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// issue #6573：旧深链 `?tab=params` 的重定向**按目标页守卫码显隐**（`production:view`，本页是
// `system:manage` —— 源页的码不蕴含目标码）⇒ 本页要问权限。用可控替身：默认「能看」，单条用例翻面。
let mockCanSeeParamsPage = true
vi.mock('@/lib/permission', () => ({
  usePermission: () => ({
    has: (code?: string) => (code === 'production:view' ? mockCanSeeParamsPage : true),
    permissions: [],
    isAdmin: false,
  }),
}))

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
    // issue #3468: 智能每日经营简报图标
    Newspaper: stub('newspaper'),
    // issue #5131: 「参数总览」tab 与参数面板用到的图标
    SlidersHorizontal: stub('sliders-horizontal'),
    // issue #5668: 「手机端入口」卡片图标
    Smartphone: stub('smartphone'),
    // V141（母单 #5161）：「工人端页面」tab 图标
    HardHat: stub('hard-hat'),
    ChevronDown: stub('chevron-down'),
    AlertCircle: stub('alert-circle'),
    ExternalLink: stub('external-link'),
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
// 参数总览（issue #5131）：算料口径**只读**读面（面板不做任何判定与换算）
const mockGetCraftCalcConfig = vi.fn()
// 智能每日经营简报（issue #3468）：配置读写
const mockBriefingGetConfig = vi.fn()
const mockBriefingUpdateConfig = vi.fn()

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
  // 参数总览（issue #5131）：面板挂载时读算料口径
  productionApi: {
    getCraftCalcConfig: (...args: any[]) => mockGetCraftCalcConfig(...args),
  },
  // §22 P4 阈值试算（issue #5131）：算料域会挂载试算块（配置里没有阈值时不会发请求，mock 仍须在）
  autoFeaturesApi: {
    preview: () => Promise.resolve({ data: { success: true, data: { auto_features: [] } } }),
  },
  briefingApi: {
    getConfig: (...args: any[]) => mockBriefingGetConfig(...args),
    updateConfig: (...args: any[]) => mockBriefingUpdateConfig(...args),
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
        // #5485：企业编码由既有 GET /api/admin/settings 下发
        code: 'migao',
      },
    },
  })
}

function mockAiConfigSuccess() {
  mockGetAiConfig.mockResolvedValue({
    data: {
      data: {
        botName: '元元',
        greetingTemplate: '您好，我是元元，有什么可以帮您？',
      },
    },
  })
}

// 智能每日经营简报（issue #3468）：默认配置（关闭态）
function mockBriefingConfigSuccess() {
  mockBriefingGetConfig.mockResolvedValue({
    data: {
      data: {
        enabled: false,
        generateTime: '06:00',
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
    mockBriefingConfigSuccess()
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
      expect(screen.getByText(/配置顾客在对话中看到的 AI 客服助手（元元）的名称与欢迎语/)).toBeInTheDocument()
      // 不再出现「AI 客服配置」独立页面命名
      expect(screen.queryByText('AI 客服配置')).not.toBeInTheDocument()
    })

    it('默认「基本设置」tab 激活，AI 客服设置内容需切换后展示', async () => {
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByText('基本设置', { selector: 'h2' })).toBeInTheDocument()
      })
      // AI 客服设置内容（输入框）默认不展示
      expect(screen.queryByPlaceholderText('元元')).not.toBeInTheDocument()
    })

    it('加载 AI 客服配置并回填 AI 客服名称与欢迎语', async () => {
      const user = userEvent.setup()
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /AI 客服设置/ })).toBeInTheDocument()
      })
      await switchToTab(user, 'AI 客服设置')
      await waitFor(() => {
        expect(screen.getByDisplayValue('元元')).toBeInTheDocument()
      })
      expect(
        screen.getByDisplayValue('您好，我是元元，有什么可以帮您？'),
      ).toBeInTheDocument()
    })

    it('#5899: AI 客服名称为空 → 失焦不提交、报错并回退（无保存按钮可点）', async () => {
      mockGetAiConfig.mockResolvedValue({
        data: { data: { botName: '  ', greetingTemplate: '' } },
      })
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /AI 客服设置/ })).toBeInTheDocument()
      })
      await screen.findByRole('button', { name: /AI 客服设置/ })
      fireEvent.click(screen.getByRole('button', { name: /AI 客服设置/ }))
      // #5899：保存按钮已移除（改动即时生效）
      expect(screen.queryByRole('button', { name: '保存' })).not.toBeInTheDocument()
      const input = screen.getByPlaceholderText('元元')
      fireEvent.blur(input)
      expect(toast.error).toHaveBeenCalledWith('请输入 AI 客服名称')
      expect(mockUpdateAiConfig).not.toHaveBeenCalled()
    })

    it('#5899: AI 客服名称失焦即保存（无保存按钮），提示口径随之为「已保存」', async () => {
      const user = userEvent.setup()
      mockUpdateAiConfig.mockResolvedValue({ data: {} })
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /AI 客服设置/ })).toBeInTheDocument()
      })
      await switchToTab(user, 'AI 客服设置')
      const input = await screen.findByDisplayValue('元元')
      await user.clear(input)
      await user.type(input, '观星台助手')
      fireEvent.blur(input)
      await waitFor(() => {
        expect(mockUpdateAiConfig).toHaveBeenCalledWith(
          expect.objectContaining({ botName: '观星台助手' }),
        )
      })
      expect(toast.success).toHaveBeenCalledWith('AI 客服名称已保存')
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
      expect(screen.getByPlaceholderText('元元')).toBeInTheDocument()
    })
  })

  describe('旧链接 /settings?tab=ai 兼容（#3098 URL tab=ai → 直接激活 AI 客服设置 tab）', () => {
    it('URL 带 ?tab=ai 时默认激活「AI 客服设置」tab（不再重定向）', async () => {
      mockSearchParams.mockReturnValue(new URLSearchParams('tab=ai'))
      render(<SettingsPage />)
      // AI 客服设置内容直接呈现（tab 激活态）
      await waitFor(() => {
        expect(screen.getByPlaceholderText('元元')).toBeInTheDocument()
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

    it('#5899: 基本设置 tab **不再有「保存」按钮**（改完即存；底部按钮在长卡片里容易被忽略）', async () => {
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByLabelText('公司名称')).toBeInTheDocument()
      })
      expect(screen.queryByRole('button', { name: '保存' })).not.toBeInTheDocument()
      // 把「不用点保存」这件事**说出来** —— 否则商家会去找按钮
      expect(screen.getByText(/修改后自动保存/)).toBeInTheDocument()
    })

    it('#5899: 公司名称 / 企业编码 失焦即保存（有改动才发请求）', async () => {
      mockUpdateSettings.mockResolvedValue({ data: { data: {} } })
      render(<SettingsPage />)
      const name = await screen.findByLabelText('公司名称')
      fireEvent.change(name, { target: { value: '观星台布艺' } })
      fireEvent.blur(name)
      await waitFor(() => {
        expect(mockUpdateSettings).toHaveBeenCalledWith(expect.objectContaining({ companyName: '观星台布艺' }))
      })
      const code = screen.getByPlaceholderText('如 migao')
      fireEvent.change(code, { target: { value: 'migao_home' } })
      fireEvent.blur(code)
      await waitFor(() => {
        expect(mockUpdateSettings).toHaveBeenCalledWith(expect.objectContaining({ code: 'migao_home' }))
      })
    })

    it('#5899: 值没变时失焦**不发请求**（点进点出不写库）', async () => {
      render(<SettingsPage />)
      const name = await screen.findByLabelText('公司名称')
      fireEvent.blur(name)
      const code = screen.getByPlaceholderText('如 migao')
      fireEvent.blur(code)
      expect(mockUpdateSettings).not.toHaveBeenCalled()
    })

    it('#3099/#5899: 字段失焦保存成功后应刷新用户信息，侧边栏/右上角即时同步', async () => {
      mockUpdateSettings.mockResolvedValue({ data: { data: {} } })
      render(<SettingsPage />)
      const name = await screen.findByLabelText('公司名称')
      fireEvent.change(name, { target: { value: '新的企业名' } })
      fireEvent.blur(name)
      await waitFor(() => {
        expect(mockUpdateSettings).toHaveBeenCalledWith(expect.objectContaining({ companyName: '新的企业名' }))
      })
      // 保存成功后必须拉取最新用户信息（含企业名/Logo），否则侧边栏不刷新（#3099 修复）
      await waitFor(() => {
        expect(mockFetchUserInfo).toHaveBeenCalledTimes(1)
      })
    })
  })

  // ================================================================
  // #5485 企业编码（AU-009）：员工登录标识 `用户名@企业编码` 的后半段
  // —— 走**既有** GET/PUT /api/admin/settings 的 `code` 字段（后端未新开端点）
  // ================================================================

  describe('企业编码 — 显示 / 保存 / 服务端校验（#5485）', () => {
    it('#5485: 显示当前企业编码，并说明「员工用它登录：用户名@企业编码」', async () => {
      render(<SettingsPage />)
      const codeInput = await screen.findByPlaceholderText('如 migao')
      expect(codeInput).toHaveValue('migao')
      expect(screen.getByText(/用户名@企业编码/)).toBeInTheDocument()
      // 改编码会影响全员登录方式 ⇒ 影响说明必须在（护栏文案）
      expect(screen.getByText(/修改后员工需改用新编码登录/)).toBeInTheDocument()
    })

    it('#5485/#5899: 企业编码失焦即提交（不新开端点；无保存按钮）', async () => {
      mockUpdateSettings.mockResolvedValue({ data: { data: {} } })
      render(<SettingsPage />)
      const codeInput = await screen.findByPlaceholderText('如 migao')
      fireEvent.change(codeInput, { target: { value: 'migao_home' } })
      fireEvent.blur(codeInput)

      await waitFor(() => {
        expect(mockUpdateSettings).toHaveBeenCalled()
      })
      // 含下划线的编码原样提交（存量租户就是 tenant_7478359537 这种形态）
      expect(mockUpdateSettings.mock.calls[0][0]).toMatchObject({ code: 'migao_home' })
    })

    it('#5485: 编码不合规/被占用（422）→ 展示**服务端** message，并把输入框拉回已保存的值', async () => {
      mockUpdateSettings.mockRejectedValue({
        response: {
          status: 422,
          data: { success: false, error: { code: 'VALIDATION_ERROR', message: '企业编码已被占用，请换一个' } },
        },
      })
      render(<SettingsPage />)
      const codeInput = await screen.findByPlaceholderText('如 migao')
      fireEvent.change(codeInput, { target: { value: 'admin' } })
      fireEvent.blur(codeInput)

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('企业编码已被占用，请换一个')
      })
      // 未生效的编码不留在框里（否则看起来像是已经改好了）
      await waitFor(() => {
        expect(screen.getByPlaceholderText('如 migao')).toHaveValue('migao')
      })
      // 回滚 = 重新拉一次设置
      expect(mockGetSettings).toHaveBeenCalledTimes(2)
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
      // #5899：上传成功即落库 ⇒ 本用例必须让保存这步成功
      //（vi.clearAllMocks 不清实现，前序用例的 mockRejectedValue 会漏到这里）
      mockUpdateSettings.mockResolvedValue({ data: { data: {} } })

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
      // #5899：Logo 上传成功**即落库**（不再需要再点一次「保存」才生效）
      expect(mockUpdateSettings).toHaveBeenCalledWith(expect.objectContaining({ logo: logoUrl }))
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
      // #5899：移除即落库 ⇒ 让保存这步成功（同上：clearAllMocks 不清前序的实现）
      mockUpdateSettings.mockResolvedValue({ data: { data: {} } })
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
      // #5899：移除**即时落库**（改前要再点一次底部「保存」才生效）
      expect(mockUpdateSettings).toHaveBeenCalledWith(expect.objectContaining({ logo: '' }))
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

    it('开关即时保存（#3119）：点击开关 → 调用 updateSettings 携带 notificationEnabled，无保存按钮', async () => {
      const user = userEvent.setup()
      mockUpdateSettings.mockResolvedValue({ data: {} })
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /通知设置/ })).toBeInTheDocument()
      })
      await switchToTab(user, '通知设置')
      // #3119：移除独立「保存通知设置」按钮（开关类配置即时生效）
      expect(screen.queryByRole('button', { name: /保存通知设置/ })).not.toBeInTheDocument()
      // 点击开关（当前 notificationEnabled=true → 点击关闭）
      const toggle = screen.getByRole('button', { name: /系统通知开关/ })
      await user.click(toggle)
      await waitFor(() => {
        expect(mockUpdateSettings).toHaveBeenCalledWith(
          expect.objectContaining({ notificationEnabled: false }),
        )
      })
      expect(toast.success).toHaveBeenCalledWith('已关闭系统通知')
    })

    it('开关保存失败 → UI 回滚并提示（#3119 乐观更新回滚）', async () => {
      const user = userEvent.setup()
      mockUpdateSettings.mockRejectedValue(new Error('save failed'))
      render(<SettingsPage />)
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /通知设置/ })).toBeInTheDocument()
      })
      await switchToTab(user, '通知设置')
      const toggle = screen.getByRole('button', { name: /系统通知开关/ })
      await user.click(toggle)
      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('保存失败')
      })
    })
  })

  // ══ #5899 类级元守卫：设置页的**可编辑字段**必须「变更即保存」 ══
  // 缺陷的类 = 「页面上有个输入框，改完没提交」。改前它靠卡片**最底部**一个「保存」按钮兜着 ——
  // 长卡片里商家滚到一半就离开，改动静默丢失（用户 2026-10-01 原话：「保存按钮放置的太底端了，
  // 用户容易忽略」）。本守卫**枚举**当前 tab 里的每个文本框/文本域：改一下、失焦 ⇒ 必须打一次
  // 保存请求。将来往设置页加字段而忘了接「变更即保存」⇒ 当场红。
  it('#5899 类级守卫：基本设置 / AI 客服设置 里每个可编辑字段都变更即保存（漏接线即红）', async () => {
    const user = userEvent.setup()
    mockUpdateSettings.mockResolvedValue({ data: { data: {} } })
    mockUpdateAiConfig.mockResolvedValue({ data: {} })
    render(<SettingsPage />)
    await screen.findByLabelText('公司名称')

    const textFields = () =>
      Array.from(document.querySelectorAll('input[type="text"], textarea')) as (HTMLInputElement | HTMLTextAreaElement)[]

    // 基本设置 tab：公司名称 + 企业编码
    expect(textFields().length).toBeGreaterThan(0)
    for (const [index, el] of textFields().entries()) {
      mockUpdateSettings.mockClear()
      fireEvent.change(el, { target: { value: `guard-${index}` } })
      fireEvent.blur(el)
      await waitFor(() => {
        expect(mockUpdateSettings).toHaveBeenCalled()
      })
    }

    // AI 客服设置 tab：AI 客服名称 + 欢迎语
    await switchToTab(user, 'AI 客服设置')
    await screen.findByDisplayValue('元元')
    expect(textFields().length).toBeGreaterThan(0)
    for (const [index, el] of textFields().entries()) {
      mockUpdateAiConfig.mockClear()
      fireEvent.change(el, { target: { value: `guard-ai-${index}` } })
      fireEvent.blur(el)
      await waitFor(() => {
        expect(mockUpdateAiConfig).toHaveBeenCalled()
      })
    }
  })
})

// issue #6573（2026-10-08 用户裁定方案 C）：「参数总览」由本页 tab **升为一级菜单项**
// `/settings/params` ⇒ 本页的判据随之改判（**判据面缩小一格不放宽**）：
//   ① 本页**不再有**「参数总览」tab（tab 恰四个企业级设置）；
//   ② 旧深链 `?tab=params` 保留为重定向 ⇒ `router.replace('/settings/params')`（旧链接不 404）。
// 搬走后的参数面本体 = `frontend/admin-web/src/app/(dashboard)/settings/params/page.tsx`
// （本文件只判**本页的出口行为**：不再挂 tab + 旧深链重定向）。
describe('SettingsPage — 「参数总览」已升为独立菜单项 /settings/params（issue #6573）', () => {
  it('本页**不再**有「参数总览」tab；tab 恰四个：基本设置 / AI 客服设置 / 工人端页面 / 通知设置', async () => {
    mockApiSuccess()
    mockAiConfigSuccess()
    mockBriefingConfigSuccess()
    mockSearchParams.mockReturnValue(new URLSearchParams(''))
    render(<SettingsPage />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /基本设置/ })).toBeInTheDocument()
    })
    for (const label of ['基本设置', 'AI 客服设置', '工人端页面', '通知设置']) {
      expect(screen.getByRole('button', { name: new RegExp(label) })).toBeInTheDocument()
    }
    // 🔴 反面（判别力）：升为一级项后本页**不得**再出现「参数总览」tab —— 同一个配置面
    // 若两处都给入口，商家会在两个地方看到同一份参数（§31 P2「信息不重复」）
    expect(screen.queryByRole('button', { name: /参数总览/ })).toBeNull()
    // 面板也**不在**本页挂载（是搬走，不是复制一份）
    expect(screen.queryByTestId('tenant-params-panel')).toBeNull()
  })

  it('旧深链 `?tab=params` ⇒ `router.replace(\'/settings/params\')`（不 404；本页不挂面板）', async () => {
    mockCanSeeParamsPage = true
    mockApiSuccess()
    mockAiConfigSuccess()
    mockBriefingConfigSuccess()
    mockRouterReplace.mockClear()
    mockSearchParams.mockReturnValue(new URLSearchParams('tab=params'))
    render(<SettingsPage />)

    await waitFor(() => {
      expect(mockRouterReplace).toHaveBeenCalledWith('/settings/params')
    })
    // 判别力：不是「碰巧别处也调了 replace」—— 逐条只认这一个目标
    expect(mockRouterReplace.mock.calls.every(([to]) => to === '/settings/params')).toBe(true)
    // 重定向期间面板**不得**闪现在本页（旧深链只跳转，不渲染第二份参数面）
    expect(screen.queryByTestId('tenant-params-panel')).toBeNull()
  })

  it('🔴 不持目标页守卫码 `production:view` ⇒ **不**重定向：留在本页，而不是被送到一扇打不开的门前', async () => {
    // 跨权限域入口的现成判据（frontend/admin-web/tests/unit/cross-domain-nav-permission-guard.test.ts）：
    // 本页守卫 `system:manage` **不蕴含**目标页的 `production:view` ⇒ 入口必须按**目标码**显隐。
    mockCanSeeParamsPage = false
    mockApiSuccess()
    mockAiConfigSuccess()
    mockBriefingConfigSuccess()
    mockRouterReplace.mockClear()
    mockSearchParams.mockReturnValue(new URLSearchParams('tab=params'))
    render(<SettingsPage />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /基本设置/ })).toBeInTheDocument()
    })
    expect(mockRouterReplace).not.toHaveBeenCalled()
    expect(screen.queryByTestId('tenant-params-panel')).toBeNull()
    mockCanSeeParamsPage = true
  })
})

// ── 手机端入口二维码（issue #5668，用例 UI-064）───────────────────────────────
// 用户逐字：「你在商家后端合适的位置搞个二维码，方便用户扫码使用」+「二维码放『系统设置 / 企业设置』页」。
// 两条判据的**反面**都要在：① 有值 ⇒ 二维码内容**逐字等于**该配置值（不是拼一个大概的地址）；
// ② 无值 ⇒ 明确「未配置」且**一个二维码都不画**（画假码 = 用户扫出白屏/别的站点，
//    而页面上一切看起来正常 —— 同族判据：洗水码「缺码不画假码」）。
describe('SettingsPage — 手机端入口二维码（issue #5668）', () => {
  // 🔴 用**哨兵值**（与线上域名不同）：若实现把地址写成硬编码/拼接，这条必红。
  //    （实测教训：夹具值 = 线上域名时，「把 value 改成硬编码线上地址」这种变异**判不出来** ——
  //     那是空断言方向；线上真实取值由下一格单独覆盖。）
  const SENTINEL_URL = 'https://bmini-entry.invalid/b/'

  beforeEach(() => {
    mockApiSuccess()
    mockSearchParams.mockReturnValue(new URLSearchParams(''))
    vi.unstubAllEnvs()
  })

  it('配置了 NEXT_PUBLIC_BMINI_H5_URL ⇒ 二维码内容逐字等于该值（哨兵值 ⇒ 硬编码实现必红）', async () => {
    vi.stubEnv('NEXT_PUBLIC_BMINI_H5_URL', SENTINEL_URL)
    render(<SettingsPage />)

    const qr = await screen.findByTestId('bmini-h5-qr')
    expect(qr.tagName.toLowerCase()).toBe('svg')
    // `title` 就是二维码承载的内容（同 TaskCardPrint 的既有口径）
    expect(qr.querySelector('title')?.textContent).toBe(SENTINEL_URL)
    expect(qr.querySelectorAll('path').length).toBeGreaterThan(0)
    expect(screen.getByTestId('bmini-h5-url')).toHaveTextContent(SENTINEL_URL)
    expect(screen.getByRole('button', { name: '复制链接' })).toBeInTheDocument()
  })

  it('线上真实取值（app.migaozn.com/b/）逐字进码 —— 值由配置决定，不由源码决定', async () => {
    vi.stubEnv('NEXT_PUBLIC_BMINI_H5_URL', 'https://app.migaozn.com/b/')
    render(<SettingsPage />)

    const qr = await screen.findByTestId('bmini-h5-qr')
    expect(qr.querySelector('title')?.textContent).toBe('https://app.migaozn.com/b/')
  })

  it('手机端入口挂在「设置 / 企业设置」页（基本设置 tab）—— 且不影响既有 tab', async () => {
    vi.stubEnv('NEXT_PUBLIC_BMINI_H5_URL', SENTINEL_URL)
    render(<SettingsPage />)

    expect(await screen.findByTestId('bmini-h5-entry')).toBeInTheDocument()
    expect(screen.getByText('手机浏览器扫码使用黄金策商家端')).toBeInTheDocument()
    // 既有四个 tab 一个不少（零回归：只加卡片，不动导航）
    // （#6573：「参数总览」已升为一级菜单项 ⇒ 本页第四个 tab 是「工人端页面」）
    for (const label of ['基本设置', 'AI 客服设置', '工人端页面', '通知设置']) {
      expect(screen.getByRole('button', { name: new RegExp(label) })).toBeInTheDocument()
    }
    expect(screen.queryByRole('button', { name: /参数总览/ })).toBeNull()
  })

  it('未配置 ⇒ 明确「未配置」提示，且**不生成二维码**（缺码不画假码）', async () => {
    vi.stubEnv('NEXT_PUBLIC_BMINI_H5_URL', '')
    render(<SettingsPage />)

    const entry = await screen.findByTestId('bmini-h5-entry')
    expect(screen.getByTestId('bmini-h5-unconfigured')).toHaveTextContent('移动端地址未配置')
    expect(screen.queryByTestId('bmini-h5-qr')).toBeNull()
    // 该卡片里连一个 svg 都没有（空断言方向：不是"没找到 testid"，而是"确实没画"）
    expect(entry.querySelector('svg')).toBeNull()
  })

  it('只有空白字符的配置值同样按「未配置」处理（不许画一个指向空白的码）', async () => {
    vi.stubEnv('NEXT_PUBLIC_BMINI_H5_URL', '   ')
    render(<SettingsPage />)

    const entry = await screen.findByTestId('bmini-h5-entry')
    expect(screen.getByTestId('bmini-h5-unconfigured')).toBeInTheDocument()
    expect(entry.querySelector('svg')).toBeNull()
  })

  it('点「复制链接」把**该配置值**逐字写进剪贴板', async () => {
    vi.stubEnv('NEXT_PUBLIC_BMINI_H5_URL', SENTINEL_URL)
    const writeText = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    const original = navigator.clipboard
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    try {
      render(<SettingsPage />)
      await user.click(await screen.findByRole('button', { name: '复制链接' }))
      expect(writeText).toHaveBeenCalledWith(SENTINEL_URL)
    } finally {
      Object.defineProperty(navigator, 'clipboard', { value: original, configurable: true })
    }
  })
})
