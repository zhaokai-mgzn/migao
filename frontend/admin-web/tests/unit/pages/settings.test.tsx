// case_ids: AU-009, ST-001, ST-003, ST-009, ST-010, UI-034, UI-037, UI-054, UI-064, PG-045
/**
 * 企业基础设置 `/settings` = **配置指挥台**（issue #6580）—— 页面形态与出口行为守卫。
 *
 * ## 2026-10-09 改判说明（形态变了，判据面**只收紧不放宽**）
 *
 * 本页从「4 个 tab 的平铺」改成「顶部配置主线 + 左栏四区八域 + 右栏当前域面板」。原来的断言对象
 * （`企业基础信息` 标题、`基本设置 / AI 客服设置 / 工人端页面 / 通知设置` 四个 tab 按钮、
 * `?tab=params` → `router.replace('/settings/params')`）**已随形态退场** —— 本章按新形态逐条改判，
 * **并新增**下面这些更严的判据：
 *
 * - **四区八域逐字在**（`CONFIG_ZONES` / `CONFIG_DOMAINS` 是单一真值源，页面不写死字面量）；
 * - **非当前域不挂载**（§4 首屏纪律：8 个域的表单不能同时上屏）；
 * - **同一屏只有一个就绪度**（`config-readiness` 恰一个 —— 设计 §2 判死线第 2 条）；
 * - **旧 `?tab=` 深链逐条映射到域且**不**再跳走**（仓内口径：旧深链不 404）；
 * - **不持码的域既不渲染也不发请求**（`/[A-Z]-[0-9]+/` 之外的硬要求：域级「看得见 ⇒ 打得开」）；
 * - **徽标与主线同源**（G4）：`config-domain-state-calc` 的文字 ≡ 主线里 `calc` 步的文字。
 *
 * ## 两个 board 为什么在这里是替身
 *
 * `ProcessingBoard` / `ProcessConfigBoard` 由**另一个包**产出（`frontend/admin-web/src/components/production-config/`），
 * 它们的**内部**行为由各自的测试与页面级 e2e 覆盖；本文件判的是**本页的编排**：
 * 哪个域挂哪个组件（`vi.mock` 替身带 testid，域→组件的映射因此可断言）。
 * 用真 board 会把「另一个包的文件还没写完」变成**本包**的红（畸形耦合）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// issue #6580：域按 `requiredCode` 显隐（复用 usePermission）。用可控替身：默认「八个域都看得见」，
// 单条用例翻面（`mockCanSee` 按码返回）。
const mockCanSee = vi.fn<(code?: string) => boolean>(() => true)
vi.mock('@/lib/permission', () => ({
  usePermission: () => ({
    has: (code?: string) => mockCanSee(code),
    permissions: [],
    isAdmin: false,
  }),
}))

// Mock lucide-react — 覆盖本页 + 子面板使用的图标
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
    ChevronDown: stub('chevron-down'),
    Zap: stub('zap'),
    Package: stub('package'),
    Search: stub('search'),
    FileX: stub('file-x'),
    Inbox: stub('inbox'),
    Loader2: stub('loader2'),
    Plus: stub('plus'),
    Trash2: stub('trash2'),
    Check: stub('check'),
    // issue #3468: 智能每日经营简报图标
    Newspaper: stub('newspaper'),
    // issue #5131 / #6580: 参数面板与域面板用到的图标
    SlidersHorizontal: stub('sliders-horizontal'),
    AlertCircle: stub('alert-circle'),
    ExternalLink: stub('external-link'),
    Pencil: stub('pencil'),
    RefreshCw: stub('refresh-cw'),
    ArrowDown: stub('arrow-down'),
    ArrowUp: stub('arrow-up'),
    Star: stub('star'),
    X: stub('x'),
    FolderTree: stub('folder-tree'),
    // issue #5668: 「手机端入口」卡片图标
    Smartphone: stub('smartphone'),
    // V141（母单 #5161）：「工人端页面」图标
    HardHat: stub('hard-hat'),
  }
})

// Mock request（子组件的写面替身）
const mockRequestGet = vi.fn()
const mockRequestPut = vi.fn()
vi.mock('@/lib/request', () => ({
  default: {
    get: (...args: any[]) => mockRequestGet(...args),
    put: (...args: any[]) => mockRequestPut(...args),
  },
}))

// Mock APIs（本页 + 各域子面板）
const mockGetSettings = vi.fn()
const mockUpdateSettings = vi.fn()
const mockGetAiConfig = vi.fn()
const mockUpdateAiConfig = vi.fn()
const mockUploadImage = vi.fn()
const mockGetOperationPositions = vi.fn()
const mockGetRoutings = vi.fn()
const mockGetFeeCombinations = vi.fn()
const mockGetFeeGaps = vi.fn()
const mockGetCraftCalcConfig = vi.fn()
const mockGetSmallItemSpecs = vi.fn()
const mockGetWorkerPageConfig = vi.fn()
const mockUpdateWorkerPageConfig = vi.fn()
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
  // 配置主线的五个生产域读面（issue #6573 / #6580）
  productionApi: {
    getOperationPositions: (...args: any[]) => mockGetOperationPositions(...args),
    getRoutings: (...args: any[]) => mockGetRoutings(...args),
    getFeeCombinations: (...args: any[]) => mockGetFeeCombinations(...args),
    getFeeGaps: (...args: any[]) => mockGetFeeGaps(...args),
    getCraftCalcConfig: (...args: any[]) => mockGetCraftCalcConfig(...args),
    // 两个 board 的读面（替身不由这里取，但模块形状必须完整 —— 页面 import 了它们）
    getOperationsCatalog: vi.fn().mockResolvedValue({ data: { data: null } }),
    getRouteRules: vi.fn().mockResolvedValue({ data: { data: [] } }),
    getRouteRuleOptions: vi.fn().mockResolvedValue({ data: { data: {} } }),
  },
  processingItemApi: {
    getProcessingItems: vi.fn().mockResolvedValue({ data: { data: { items: [] } } }),
  },
  processingCategoryApi: {
    getProcessingCategories: vi.fn().mockResolvedValue({ data: { data: [] } }),
  },
  cuttingHeightApi: { get: vi.fn().mockResolvedValue({ data: { data: null } }) },
  // §22 P4 阈值试算（算料域会挂载试算块；配置里没有阈值时不会发请求，mock 仍须在）
  autoFeaturesApi: {
    preview: () => Promise.resolve({ data: { success: true, data: { auto_features: [] } } }),
  },
  // 余料域的内联参数（小件用料尺寸表）
  remnantApi: {
    smallItemSpecs: (...args: any[]) => mockGetSmallItemSpecs(...args),
    putSmallItemSpecs: () => Promise.resolve({ data: { success: true, data: null } }),
  },
  // 工人端页面域
  workerPageConfigApi: {
    get: (...args: any[]) => mockGetWorkerPageConfig(...args),
    update: (...args: any[]) => mockUpdateWorkerPageConfig(...args),
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

// Mock next/navigation（searchParams 可逐用例控制，供 ?domain= / 旧 ?tab= 用例）
const mockRouterPush = vi.fn()
const mockRouterReplace = vi.fn()
const mockSearchParams = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockRouterPush, replace: mockRouterReplace }),
  useSearchParams: () => mockSearchParams(),
  usePathname: () => '/settings',
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

// 各域挂的功能体由**别的包**产出（见文件头）。本文件判「域 → 组件」的编排 ⇒ 用替身，
// 替身的 testid 就是那些域面板的机器读数。
// ⚠️ issue #6585：`processing-fee` 一个域拆成两个（加工项与分类 / 加工费组合）⇒ 替身也随之拆成两个。
vi.mock('@/components/production-config/ProcessingItemsPanel', () => ({
  default: ({ embedded }: { embedded?: boolean }) => (
    <div data-testid="stub-processing-items" data-embedded={String(!!embedded)} />
  ),
}))
vi.mock('@/components/production-config/FeeCombinationsPanel', () => ({
  default: ({ embedded }: { embedded?: boolean }) => (
    <div data-testid="stub-fee-combinations" data-embedded={String(!!embedded)} />
  ),
}))
// v2（#6585）：生产执行三个域各自挂**独立面板**（不再整块挂自带页签的 board）
vi.mock('@/components/production-config/OperationPricePanel', () => ({
  OperationPricePanel: ({ embedded }: { embedded?: boolean }) => (
    <div data-testid="stub-operation-price-panel" data-embedded={String(!!embedded)} />
  ),
}))
vi.mock('@/components/production-config/RoutingsPanel', () => ({
  RoutingsPanel: ({ embedded }: { embedded?: boolean }) => (
    <div data-testid="stub-routings-panel" data-embedded={String(!!embedded)} />
  ),
}))
vi.mock('@/components/production-config/CuttingHeightPanel', () => ({
  CuttingHeightPanel: ({ embedded }: { embedded?: boolean }) => (
    <div data-testid="stub-cutting-height-panel" data-embedded={String(!!embedded)} />
  ),
}))
vi.mock('@/components/production-config/CalcFormulaPanel', () => ({
  CalcFormulaPanel: ({ embedded }: { embedded?: boolean }) => (
    <div data-testid="stub-calc-formula-panel" data-embedded={String(!!embedded)} />
  ),
}))

import SettingsPage from '@/app/(dashboard)/settings/page'
import { calcReadErrorCopy } from '@/app/(dashboard)/settings/page'
import {
  CONFIG_DOMAINS,
  CONFIG_ZONES,
  domainsOfZone,
  findDomain,
  mainlineStepsOfDomain,
  LEGACY_DOMAIN_ALIASES,
  resolveDomainKey,
} from '@/lib/config-center-domains'
import { BASE_ROUTE_NAMES, MAINLINE_STEPS } from '@/lib/config-readiness'

/** `request.get` 的返回壳（子面板形状） */
const ok = (data: unknown) => ({ data: { success: true, data } })

/** 读面全绿（主线应判 5/5）——路线名取自 `BASE_ROUTE_NAMES`，不写第二份 */
function mockApiSuccess() {
  mockGetSettings.mockResolvedValue(
    ok({ companyName: '测试企业', logo: '', notificationEnabled: true, code: 'migao' }),
  )
  mockGetAiConfig.mockResolvedValue(ok({ botName: '元元', greetingTemplate: '您好' }))
  mockBriefingGetConfig.mockResolvedValue(ok({ enabled: false, generateTime: '06:00' }))
  mockGetOperationPositions.mockResolvedValue(ok([{ unit_price: 12 }, { unit_price: 8 }]))
  mockGetRoutings.mockResolvedValue(
    ok({
      routings: [
        { name: BASE_ROUTE_NAMES[0], is_default: true },
        { name: BASE_ROUTE_NAMES[1], is_default: false },
      ],
    }),
  )
  mockGetFeeCombinations.mockResolvedValue(ok({ total: 3, combinations: [] }))
  mockGetFeeGaps.mockResolvedValue(ok({ unpriced_combination_total: 0 }))
  mockGetCraftCalcConfig.mockResolvedValue(ok({ source: 'stored', config: { hem_margin: 0.4 } }))
  mockGetSmallItemSpecs.mockResolvedValue(
    ok({ configured: false, items: [], notice: '未配置小件用料尺寸 ⇒ 不产生匹配建议' }),
  )
  mockGetWorkerPageConfig.mockResolvedValue(ok({ source: 'default', pages: [], labels: {} }))
}

/** 左栏的域按钮（用 testid 取，**不靠按钮文字** —— 域标题与导航项文案相同） */
function domainNav(key: string) {
  return screen.getByTestId(`config-domain-${key}`)
}

beforeEach(() => {
  vi.clearAllMocks()
  mockCanSee.mockImplementation(() => true)
  mockApiSuccess()
  mockSearchParams.mockReturnValue(new URLSearchParams())
  mockReadImageDimensions.mockResolvedValue({ width: 128, height: 128 })
  // jsdom 有 history，但清掉每条用例的调用记录（切域判据要读它）
  window.history.replaceState(null, '', '/settings')
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 1：顶部配置主线（G1）—— 唯一一个就绪面，常驻一行
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 1：配置主线（G1 / §4 P1）—— 一屏只有一个就绪度', () => {
  it('进页第一眼：标题 + 主线一行摘要（折叠态逐项不渲染）', async () => {
    render(<SettingsPage />)
    // 新形态的页头（原「企业基础信息」改名 —— 菜单三源同构由别的包负责，这里判本页文案）
    expect(screen.getByRole('heading', { name: '企业基础设置' })).toBeInTheDocument()
    // issue #6580 改判：副标题不许写实现腔的箭头链路（`user-copy-jargon-guard` S1）
    // ⇒ 现文案逐字钉住（换文案必须同时改这里，不许放宽成 /配置/ 这种恒真匹配）
    expect(
      screen.getByText('配置本企业的口径与生产设置：先定怎么算钱，再定车间怎么干活，最后定料怎么省。'),
    ).toBeInTheDocument()

    const headline = screen.getByTestId('config-readiness-headline')
    // 加载期**不谎报**
    expect(headline).toHaveTextContent('配置主线读取中…')
    await waitFor(() => expect(headline).toHaveTextContent('配置已完成 5/5'))
    // 折叠态：逐项 DOM **不渲染**（§31 P1；CSS 隐藏不算）
    expect(screen.queryByTestId('config-readiness-list')).toBeNull()
    for (const s of MAINLINE_STEPS) {
      expect(screen.queryByTestId(`readiness-item-${s.key}`)).toBeNull()
    }
  })

  it('🔴 同一屏**恰好一个**就绪度（`config-readiness` 恰一个）—— 设计 §2 判死线第 2 条', async () => {
    render(<SettingsPage />)
    await waitFor(() =>
      expect(screen.getByTestId('config-readiness-headline')).toHaveTextContent('配置已完成 5/5'),
    )
    expect(screen.getAllByTestId('config-readiness')).toHaveLength(1)
  })

  it('读失败 ⇒ 那一步是「读不到」而**不是**「待配置」（三态不互画）', async () => {
    mockGetFeeGaps.mockRejectedValue(new Error('500'))
    render(<SettingsPage />)
    const headline = screen.getByTestId('config-readiness-headline')
    await waitFor(() => expect(headline).toHaveTextContent('配置完成 4/5'))
    expect(headline).toHaveTextContent('1 项读不到')
    fireEvent.click(screen.getByTestId('config-readiness-toggle'))
    expect(screen.getByTestId('readiness-state-fee-combinations')).toHaveTextContent('读不到')
    expect(screen.queryAllByText('待配置')).toHaveLength(0)
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 2：左栏四区 + 八个域（G4 / 设计 §2）
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 2：四区八域导航（逐字取自 config-center-domains —— 页面不写死字面量）', () => {
  it('四个区的导航项都在（`config-zone-<key>`）', async () => {
    render(<SettingsPage />)
    await screen.findByTestId('config-domain-enterprise')
    for (const z of CONFIG_ZONES) {
      expect(screen.getByTestId(`config-zone-${z.key}`)).toBeInTheDocument()
    }
    // 八域一条不少，且**逐字**在左栏（有空区/漏域 ⇒ 红）
    for (const d of CONFIG_DOMAINS) {
      expect(domainNav(d.key)).toBeInTheDocument()
    }
  })

  it('每个域都挂在它登记的那个区里（域 ↔ 区不是各写一份）', async () => {
    render(<SettingsPage />)
    await screen.findByTestId('config-domain-enterprise')
    for (const d of CONFIG_DOMAINS) {
      expect(
        within(screen.getByTestId(`config-zone-${d.zone}`)).getByTestId(`config-domain-${d.key}`),
      ).toBeInTheDocument()
    }
    // 正控：区里的域数之和 = 域总数（不重复挂、不漏挂），且**四区都不为空**
    const inZones = CONFIG_ZONES.reduce((n, z) => n + domainsOfZone(z.key).length, 0)
    expect(inZones).toBe(CONFIG_DOMAINS.length)
    for (const z of CONFIG_ZONES) {
      expect(domainsOfZone(z.key).length).toBeGreaterThan(0)
    }
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 3：右栏 = 当前域（§4 首屏纪律：非当前域**不挂载**）
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 3：首屏只挂当前域（不把 8 个域的表单全渲染）', () => {
  it('默认停在第一个可见域（= CONFIG_DOMAINS 第一个）：只挂它一个面板', async () => {
    render(<SettingsPage />)
    // 默认域 = CONFIG_DOMAINS 的第一个（**单一真值源**；页面不写死默认域）
    const first = CONFIG_DOMAINS[0].key
    expect(screen.getByTestId(`config-domain-panel-${first}`)).toBeInTheDocument()
    for (const d of CONFIG_DOMAINS.filter((x) => x.key !== first)) {
      expect(screen.queryByTestId(`config-domain-panel-${d.key}`)).toBeNull()
    }
    // 非当前域的表单**不挂载**（不是 CSS 藏起来）
    expect(screen.queryByTestId('stub-processing-board')).toBeNull()
    expect(screen.queryByTestId('stub-routings-panel')).toBeNull()
    expect(screen.queryByTestId('worker-page-config')).toBeNull()
    expect(screen.queryByTestId('param-remnant-specs')).toBeNull()
  })

  it('切域只换右栏：旧面板卸载、新面板挂载（算料口径 → 企业信息）', async () => {
    render(<SettingsPage />)
    // 默认域（第一个）= 算料口径 ⇒ 抽出的编辑面在
    expect(await screen.findByTestId('calc-caliber-panel')).toBeInTheDocument()
    fireEvent.click(domainNav('enterprise'))
    expect(screen.getByTestId('config-domain-panel-enterprise')).toBeInTheDocument()
    expect(screen.queryByTestId('config-domain-panel-calc')).toBeNull()
    expect(screen.queryByTestId('calc-caliber-panel')).toBeNull()
    expect(await screen.findByLabelText('公司名称')).toBeInTheDocument()
  })

  it('域 → 组件映射：加工项与分类 / 加工费组合 / 工艺与路线 / 余料尺寸 / 工人端页面 各挂各的', async () => {
    render(<SettingsPage />)
    await screen.findByTestId('config-domain-enterprise')

    fireEvent.click(domainNav('processing-items'))
    expect(screen.getByTestId('stub-processing-items')).toBeInTheDocument()
    expect(screen.queryByTestId('stub-fee-combinations')).toBeNull()
    expect(screen.queryByTestId('stub-routings-panel')).toBeNull()

    fireEvent.click(domainNav('fee-combinations'))
    expect(screen.getByTestId('stub-fee-combinations')).toBeInTheDocument()
    expect(screen.queryByTestId('stub-processing-items')).toBeNull()

    fireEvent.click(domainNav('craft-route'))
    expect(screen.getByTestId('stub-routings-panel')).toBeInTheDocument()
    expect(screen.queryByTestId('stub-operation-price-panel')).toBeNull()

    fireEvent.click(domainNav('operation-prices'))
    expect(screen.getByTestId('stub-operation-price-panel')).toBeInTheDocument()
    expect(screen.queryByTestId('stub-routings-panel')).toBeNull()

    fireEvent.click(domainNav('cutting-height'))
    expect(screen.getByTestId('stub-cutting-height-panel')).toBeInTheDocument()
    expect(screen.queryByTestId('stub-operation-price-panel')).toBeNull()

    fireEvent.click(domainNav('remnant-sizes'))
    expect(await screen.findByTestId('param-remnant-specs')).toBeInTheDocument()

    fireEvent.click(domainNav('worker-pages'))
    expect(await screen.findByTestId('worker-page-config')).toBeInTheDocument()
  })

  it('切换域后主线的读数**不重来**（同一个就绪度，不因切域重新请求或改变）', async () => {
    render(<SettingsPage />)
    await waitFor(() =>
      expect(screen.getByTestId('config-readiness-headline')).toHaveTextContent('配置已完成 5/5'),
    )
    fireEvent.click(domainNav('notifications'))
    expect(screen.getByTestId('config-readiness-headline')).toHaveTextContent('配置已完成 5/5')
    // 五个读面各只发一次（切域不重拉第一屏）
    expect(mockGetOperationPositions).toHaveBeenCalledTimes(1)
    expect(mockGetCraftCalcConfig).toHaveBeenCalledTimes(1)
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 4：URL 兼容（旧深链不 404；新形态用 ?domain=）
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 4：URL —— `?domain=` 直达 + 旧 `?tab=` 逐条映射且**不跳走**', () => {
  it('`?domain=craft-route` 直达该域（右栏就是它）', async () => {
    mockSearchParams.mockReturnValue(new URLSearchParams('domain=craft-route'))
    render(<SettingsPage />)
    expect(await screen.findByTestId('config-domain-panel-craft-route')).toBeInTheDocument()
    expect(screen.getByTestId('stub-routings-panel')).toBeInTheDocument()
  })

  it('旧深链 `?tab=params` ⇒ 算料口径域（**不**再 replace 跳走；旧的 `/settings/params` 面已并入本页）', async () => {
    mockSearchParams.mockReturnValue(new URLSearchParams('tab=params'))
    render(<SettingsPage />)
    expect(await screen.findByTestId('config-domain-panel-calc')).toBeInTheDocument()
    expect(screen.getByTestId('calc-caliber-panel')).toBeInTheDocument()
    // 🔴 判别力：不许再把人送出本页
    expect(mockRouterReplace).not.toHaveBeenCalled()
    expect(mockRouterPush).not.toHaveBeenCalled()
  })

  it('旧深链 `?tab=ai` ⇒ AI 客服域（不跳走）', async () => {
    mockSearchParams.mockReturnValue(new URLSearchParams('tab=ai'))
    render(<SettingsPage />)
    expect(await screen.findByTestId('config-domain-panel-ai')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('元元')).toBeInTheDocument()
    expect(mockRouterReplace).not.toHaveBeenCalled()
  })

  it('旧深链 `?tab=basic` / `?tab=workerPages` / `?tab=notification` ⇒ 各自映射（不跳走）', async () => {
    mockSearchParams.mockReturnValue(new URLSearchParams('tab=workerPages'))
    const { unmount } = render(<SettingsPage />)
    expect(await screen.findByTestId('config-domain-panel-worker-pages')).toBeInTheDocument()
    unmount()

    mockSearchParams.mockReturnValue(new URLSearchParams('tab=notification'))
    render(<SettingsPage />)
    expect(await screen.findByTestId('config-domain-panel-notifications')).toBeInTheDocument()
    expect(mockRouterReplace).not.toHaveBeenCalled()
  })

  it('点左栏域 ⇒ 页内跳转 + 高亮（G3）：`?domain=<key>` 与 `#domain-<key>` 都写进 URL', async () => {
    render(<SettingsPage />)
    await screen.findByTestId('config-domain-enterprise')
    fireEvent.click(domainNav('ai'))
    expect(window.location.search).toBe('?domain=ai')
    expect(window.location.hash).toBe('#domain-ai')
    // 当前域被标记（高亮 = aria-selected）
    expect(domainNav('ai')).toHaveAttribute('aria-selected', 'true')
    expect(domainNav('enterprise')).toHaveAttribute('aria-selected', 'false')
    // 新形态的域用 ?domain=，**不**靠 router 送出页面
    expect(mockRouterPush).not.toHaveBeenCalled()
    expect(mockRouterReplace).not.toHaveBeenCalled()
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 5：域级权限（不持码 ⇒ 不渲染、不进入、也不发它的请求）
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 5：域按 requiredCode 显隐（复用 usePermission）', () => {
  it('不持 `production:view` ⇒ 算料 / 加工费 / 工艺三域**不在左栏**，且不挂它们的组件', async () => {
    mockCanSee.mockImplementation((code?: string) => code !== 'production:view')
    render(<SettingsPage />)
    await screen.findByTestId('config-domain-enterprise')
    // 「看得见 ⇒ 打得开」：不持码的域连导航项都不该有（不是渲染出来再让人撞 403）
    for (const key of ['calc', 'processing-items', 'fee-combinations', 'craft-route']) {
      expect(screen.queryByTestId(`config-domain-${key}`)).toBeNull()
    }
    expect(screen.queryByTestId('calc-caliber-panel')).toBeNull()
    // 三个企业级域仍在（同一个码 `system:manage`）
    for (const key of ['enterprise', 'ai', 'worker-pages', 'notifications']) {
      expect(screen.getByTestId(`config-domain-${key}`)).toBeInTheDocument()
    }
  })

  it('不持 `processing:manage` ⇒ 余料尺寸域不在，且**不发**它的读面（不渲染 = 不请求）', async () => {
    mockCanSee.mockImplementation((code?: string) => code !== 'processing:manage')
    render(<SettingsPage />)
    await screen.findByTestId('config-domain-enterprise')
    expect(screen.queryByTestId('config-domain-remnant-sizes')).toBeNull()
    expect(mockGetSmallItemSpecs).not.toHaveBeenCalled()
  })

  it('不持 `system:manage` ⇒ 四个企业级域全不在；默认域退回第一个**可见**域', async () => {
    mockCanSee.mockImplementation((code?: string) => code !== 'system:manage')
    render(<SettingsPage />)
    // 第一个可见域 = 算料口径（CONFIG_DOMAINS 里第一个 requiredCode 命中的）
    expect(await screen.findByTestId('config-domain-panel-calc')).toBeInTheDocument()
    for (const key of ['enterprise', 'ai', 'worker-pages', 'notifications']) {
      expect(screen.queryByTestId(`config-domain-${key}`)).toBeNull()
    }
    expect(screen.queryByTestId('config-domain-panel-enterprise')).toBeNull()
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 6：徽标与主线同源（G4）
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 6：域状态徽标**与主线同源**（G4），且没被主线覆盖的域**不编读数**', () => {
  it('算料域徽标文字 ≡ 主线里 `calc` 步的文字（同一次读数）', async () => {
    render(<SettingsPage />)
    await waitFor(() =>
      expect(screen.getByTestId('config-readiness-headline')).toHaveTextContent('配置已完成 5/5'),
    )
    fireEvent.click(domainNav('calc'))
    fireEvent.click(screen.getByTestId('config-readiness-toggle'))
    const mainlineText = screen.getByTestId('readiness-state-calc').textContent
    expect(screen.getByTestId('config-domain-state-calc')).toHaveTextContent(mainlineText ?? '')
  })

  it('工艺路线读面失败 ⇒ 算料域徽标仍「已配置」，主线 `calc` 步也是「已配置」（不被别步牵连）', async () => {
    mockGetRoutings.mockRejectedValue(new Error('500'))
    render(<SettingsPage />)
    await waitFor(() =>
      expect(screen.getByTestId('config-readiness-headline')).toHaveTextContent('配置完成 3/5'),
    )
    fireEvent.click(domainNav('calc'))
    expect(screen.getByTestId('config-domain-state-calc')).toHaveTextContent('已配置')
  })

  it('主线没覆盖的域（企业信息等）**不显示**徽标 —— 不编一个读数出来', async () => {
    render(<SettingsPage />)
    await screen.findByTestId('config-domain-enterprise')
    expect(screen.queryByTestId('config-domain-state-enterprise')).toBeNull()
    fireEvent.click(domainNav('worker-pages'))
    // 等它自己的读面落地再断言（否则子面板的异步 setState 会在测试外触发 act 警告）
    expect(await screen.findByTestId('worker-page-config')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.queryByTestId('config-domain-state-worker-pages')).toBeNull(),
    )
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 7：搬迁的能力零回归（企业信息 / AI 客服 / 通知设置）
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 7：原四个 tab 的能力迁入域后零回归', () => {
  it('企业信息域：公司名称 / 企业编码 失焦即保存（#5899，无保存按钮）', async () => {
    mockUpdateSettings.mockResolvedValue({ data: {} })
    mockSearchParams.mockReturnValue(new URLSearchParams('domain=enterprise'))
    render(<SettingsPage />)
    const name = await screen.findByLabelText('公司名称')
    expect(screen.queryByRole('button', { name: '保存' })).not.toBeInTheDocument()
    expect(screen.getByText(/修改后自动保存/)).toBeInTheDocument()
    fireEvent.change(name, { target: { value: '观星台布艺' } })
    fireEvent.blur(name)
    await waitFor(() =>
      expect(mockUpdateSettings).toHaveBeenCalledWith(
        expect.objectContaining({ companyName: '观星台布艺' }),
      ),
    )
    const code = screen.getByPlaceholderText('如 migao')
    fireEvent.change(code, { target: { value: 'migao_home' } })
    fireEvent.blur(code)
    await waitFor(() =>
      expect(mockUpdateSettings).toHaveBeenCalledWith(
        expect.objectContaining({ code: 'migao_home' }),
      ),
    )
  })

  it('AI 客服域：名称 / 欢迎语 失焦即保存，回填服务端值', async () => {
    mockUpdateAiConfig.mockResolvedValue({ data: {} })
    const user = userEvent.setup()
    mockSearchParams.mockReturnValue(new URLSearchParams('domain=ai'))
    render(<SettingsPage />)
    const input = await screen.findByDisplayValue('元元')
    await user.clear(input)
    await user.type(input, '观星台助手')
    fireEvent.blur(input)
    await waitFor(() =>
      expect(mockUpdateAiConfig).toHaveBeenCalledWith(
        expect.objectContaining({ botName: '观星台助手' }),
      ),
    )
    expect(toast.success).toHaveBeenCalledWith('AI 客服名称已保存')
  })

  it('通知域：开关即时保存 + 失败回滚（#3119）', async () => {
    mockUpdateSettings.mockResolvedValue({ data: {} })
    mockSearchParams.mockReturnValue(new URLSearchParams('domain=notifications'))
    render(<SettingsPage />)
    const toggle = await screen.findByRole('button', { name: '启用系统通知开关' })
    await waitFor(() => expect(mockGetSettings).toHaveBeenCalled())
    fireEvent.click(toggle)
    await waitFor(() =>
      expect(mockUpdateSettings).toHaveBeenCalledWith({ notificationEnabled: false }),
    )
    expect(toast.success).toHaveBeenCalledWith('已关闭系统通知')
  })

  it('手机端入口（#5668）：未配置 ⇒ 明确说明且**不画码**（缺码不画假码）', async () => {
    vi.stubEnv('NEXT_PUBLIC_BMINI_H5_URL', '')
    mockSearchParams.mockReturnValue(new URLSearchParams('domain=enterprise'))
    try {
      render(<SettingsPage />)
      const entry = await screen.findByTestId('bmini-h5-entry')
      expect(screen.getByTestId('bmini-h5-unconfigured')).toHaveTextContent('移动端地址未配置')
      expect(entry.querySelector('svg')).toBeNull()
      expect(screen.queryByTestId('bmini-h5-qr')).toBeNull()
    } finally {
      vi.unstubAllEnvs()
    }
  })

  it('手机端入口（#5668）：配置了地址 ⇒ 二维码内容逐字等于该值（哨兵值 ⇒ 硬编码必红）', async () => {
    const SENTINEL_URL = 'https://bmini-entry.invalid/b/'
    vi.stubEnv('NEXT_PUBLIC_BMINI_H5_URL', SENTINEL_URL)
    mockSearchParams.mockReturnValue(new URLSearchParams('domain=enterprise'))
    try {
      render(<SettingsPage />)
      const qr = await screen.findByTestId('bmini-h5-qr')
      expect(qr.querySelector('title')?.textContent).toBe(SENTINEL_URL)
      expect(screen.getByTestId('bmini-h5-url')).toHaveTextContent(SENTINEL_URL)
    } finally {
      vi.unstubAllEnvs()
    }
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 4：主线「去配置」= **页内跳转**（设计 G3）—— 不把人送出页面
//
// 为什么这条是「引导」的核心：改前的形态里「去配置」是**跨页链接**（跳到 /production/routings），
// 人跳过去以后就**回不到那条主线**了 —— 一条「走得完的路」断在半路。设计 §0 把它定成形态要求。
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 4：主线的「去配置」跳到**本页那个域**（G3），不是跳走', () => {
  it('展开主线 ⇒ 点「加工费组合」的去配置 ⇒ 右栏换成承载它的那个域（页内切换 + URL 跟上）', async () => {
    render(<SettingsPage />)
    await waitFor(() =>
      expect(screen.getByTestId('config-readiness-headline')).toHaveTextContent('配置已完成 5/5'),
    )
    expect(screen.getByTestId('config-domain-panel-calc')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('config-readiness-toggle'))
    fireEvent.click(screen.getByTestId('readiness-goto-fee-combinations'))

    await waitFor(() =>
      expect(screen.getByTestId('config-domain-panel-fee-combinations')).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('config-domain-panel-calc')).toBeNull()
    // URL 也跟着走（可分享 / 可回退；与左栏点击同一条路径）
    expect(window.location.search).toBe('?domain=fee-combinations')
  })

  it('🔴 判别力：**多步共用一个域**时，任一步的去配置都落到同一个域（不会跳到不存在的域）', async () => {
    render(<SettingsPage />)
    await waitFor(() =>
      expect(screen.getByTestId('config-readiness-headline')).toHaveTextContent('配置已完成 5/5'),
    )
    fireEvent.click(screen.getByTestId('config-readiness-toggle'))
    // 「工艺与路线」这一个域承载三步（工序 / 路线 / 默认路线）—— 按 `config-center-domains` 的声明现取
    const steps = mainlineStepsOfDomain(findDomain('craft-route')!)
    expect(steps.length).toBeGreaterThan(1)
    for (const step of steps) {
      fireEvent.click(screen.getByTestId(`readiness-goto-${step}`))
      await waitFor(() =>
        expect(screen.getByTestId('config-domain-panel-craft-route')).toBeInTheDocument(),
      )
    }
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 6：读失败的**归因**必须说真原因（issue #6580；真实浏览器验收实测的缺陷）
//
// 缺陷形态（改前）：算料读面**任何**失败都说「可能是当前岗位没有「工艺配置」权限 —— 请联系管理员」。
// 实测：本机 ai-agent 未启动 ⇒ 读面 5xx，商家被指去找管理员开一个**自己本来就有的**权限。
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 6：算料读失败的归因 —— 403 说权限、其余说服务（不许一律赖权限）', () => {
  it('服务不可用（500）⇒ 说「服务暂时不可用 / 不是你的权限问题」，**不**提权限、不喊找管理员', () => {
    const copy = calcReadErrorCopy({ response: { status: 500 } })
    expect(copy).toContain('不是你的权限问题')
    expect(copy).not.toContain('请联系管理员')
  })

  it('真·403 ⇒ 说权限并给去处（这一条才是权限问题）', () => {
    const copy = calcReadErrorCopy({ response: { status: 403 } })
    expect(copy).toContain('权限')
    expect(copy).toContain('请联系管理员')
  })

  it('🔴 判别力：入参形状变化（如 axios 直接把 status 挂在 error 上）也不许退回「一律赖权限」', () => {
    expect(calcReadErrorCopy({ status: 403 })).toContain('请联系管理员')
    // 没有状态码 = 归因不明 ⇒ 按服务侧说（**默认不猜测是权限**）
    expect(calcReadErrorCopy(new Error('network'))).toContain('不是你的权限问题')
  })

  it('页面上真的用上了：读面 rejected ⇒ 面板显示的是这条分流后的话术', async () => {
    mockGetCraftCalcConfig.mockRejectedValue({ response: { status: 503 } })
    render(<SettingsPage />)
    await waitFor(() =>
      expect(screen.getByText(/不是你的权限问题/)).toBeInTheDocument(),
    )
    expect(screen.queryByText(/请联系管理员开/)).toBeNull()
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 7：**域内零 tab**（issue #6585 / 设计 §2 判死线第 3 条）
//
// 缺陷形态（v1 实测）：左栏一套域导航，域内又是旧页面的 tab（工序管理 / 算料配置 / 裁高配置、
// 加工项 / 加工费组合）—— 两层导航并存正是用户说的「分不清该点哪个」。
// 本判据是 v1 漏掉的那条**类级**守卫：它不看某一个域，而是遍历**全部域**。
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 7：域内零 tab（两层导航并存 = 用户说的「分不清该点哪个」）', () => {
  /**
   * 🔴 **尚未拆域的域**（v2 分批把功能体按域拆开；这份清单**只许缩短**）。
   *
   * 每搬完一个域就从这里删一行 —— 留着一个已经拆好的条目 = 台账腐坏（下面的「无幽灵」断言会红）。
   */
  // 🔴 **2026-10-09（#6585）台账已清零** —— 11 个域全部拆到功能粒度，域内不再有第二层导航。
  // 这份清单**只许为空**：将来若真出现「拆不动」的域，必须在这里具名登记 + 在 PR 里说清为什么。
  const TABS_NOT_YET_SPLIT: string[] = []

  it('除已登记的未拆域外，**每个域的面板里都没有 `role="tablist"`**', async () => {
    render(<SettingsPage />)
    await screen.findByTestId('config-domain-enterprise')
    for (const d of CONFIG_DOMAINS) {
      if (TABS_NOT_YET_SPLIT.includes(d.key)) continue
      fireEvent.click(domainNav(d.key))
      const panel = screen.getByTestId(`config-domain-panel-${d.key}`)
      expect(
        panel.querySelectorAll('[role="tablist"]').length,
        `域「${d.label}」内部还有一套 tab —— 左栏已经有一套导航了（设计 §2 判死线第 3 条）`,
      ).toBe(0)
    }
  })

  it('台账无幽灵：登记的未拆域必须仍是**真实存在**的域 key（拼错 ⇒ 判据在对空气放行）', () => {
    const keys = CONFIG_DOMAINS.map((d) => d.key)
    for (const k of TABS_NOT_YET_SPLIT) {
      expect(keys, `台账里的「未拆域」${k} 已不是域 key ⇒ 判据在空跑，请删掉该条目`).toContain(k)
    }
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 4b：域 key 是**可分享的 URL 契约** —— v2 拆域不许让旧 key 落空白（issue #6585）
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 4b：拆域后的旧 `?domain=` 兼容（不许点开一个链接看到空页）', () => {
  it('🔴 `?domain=processing-fee`（v1 的「一个域两件事」）落到「加工项与分类」域', async () => {
    mockSearchParams.mockReturnValue(new URLSearchParams('domain=processing-fee'))
    render(<SettingsPage />)
    await waitFor(() =>
      expect(screen.getByTestId('config-domain-panel-processing-items')).toBeInTheDocument(),
    )
  })

  it('别名表是**单一真值**：里面每个 key 要么是现役域，要么是已登记的旧 key（不许有幽灵）', () => {
    for (const [from, to] of Object.entries(LEGACY_DOMAIN_ALIASES)) {
      // 旧 key **不得**再是现役域（否则别名是死的）
      expect(CONFIG_DOMAINS.map((d) => d.key), `${from} 已是现役域 ⇒ 别名条目陈旧`).not.toContain(from)
      // 目标必须真是现役域（打错字 ⇒ 旧链接落到空白）
      expect(CONFIG_DOMAINS.map((d) => d.key), `${from} → ${to} 的目标不是现役域`).toContain(to)
      expect(resolveDomainKey(from)).toBe(to)
    }
    // 现役 key 直接透传；未知 key 退回 undefined（由页面兜底到第一个可见域，不在这里编默认域）
    expect(resolveDomainKey('calc')).toBe('calc')
    expect(resolveDomainKey('nope')).toBeUndefined()
    expect(resolveDomainKey(null)).toBeUndefined()
  })
})
