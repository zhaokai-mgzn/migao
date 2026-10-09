'use client'

/**
 * 企业基础设置 `/settings` = **配置指挥台**（issue #6580；设计真值源
 * `docs/design/enterprise-settings-redesign.md`）。
 *
 * ## 形态（v1，逐条照设计 §0 / §4）
 *
 * ```
 * 企业基础设置
 * 配置本企业的口径与生产设置：先定怎么算钱，再定车间怎么干活，最后定料怎么省。
 * [ 配置主线 ]                      ← 常驻一行摘要（折叠态逐项 DOM 不渲染，§31 P1）
 * ┌ 一~四区 + 八个域 ┬ 当前域面板 ┐
 * ```
 *
 * 🔴 **本页不重造主线**：第一屏读数与三态判据全部来自 `@/lib/config-readiness` 的 `judge*`
 * （**唯一真值源**，有类级守卫 `tests/unit_ci_workflows/test_config_readiness_single_source.py`）——
 * 页面里**不写第二份判断**。右栏的状态徽标也取自**同一次读数**（设计 G4：与主线同源）。
 *
 * ## URL 兼容（旧深链不 404，仓内口径）
 *
 * | 旧 | 新 |
 * |---|---|
 * | `?tab=basic` | `?domain=enterprise` |
 * | `?tab=ai` | `?domain=ai` |
 * | `?tab=workerPages` | `?domain=worker-pages` |
 * | `?tab=notification` | `?domain=notifications` |
 * | `?tab=params` | `?domain=calc`（原「参数总览」面已并入本页的「算料口径」域） |
 *
 * 新形态一律用 `?domain=<key>`，并写 `#domain-<key>` 锚点（设计 G3：去配置 = 页内跳转 + 高亮）。
 *
 * ## 首屏纪律（设计 §4）
 *
 * 首屏 = 标题 + **主线一行** + 域导航 + **当前域**；**非当前域不挂载**（8 个域的表单不能全上屏）。
 * 同一屏**只有一个就绪度**（主线那条）；域内**不再套一层 tab**（两个 board 自带的内部 tab 见下）。
 *
 * ## 已知 v1 债务（**v2 拆解**，具名登记不粉饰）
 *
 * 0. **区归属的一处取舍**：设计 §2 把「工艺与路线」写进「报价与计费」那一格的合并格里，
 *    而「二 · 生产执行」区问的正是「这一单在车间怎么走」。本实现取**生产执行**
 *    （理由见 `frontend/admin-web/src/lib/config-center-domains.ts` 头部注释）——
 *    放一区会让二区**成为空区**，与「四区」形态相抵。
 * 1. `ProcessingBoard` / `ProcessConfigBoard` **各自带内部 tab**（`加工项 | 加工费组合`、
 *    工艺 / 算料 / 裁高）—— 这是设计 §2「判死线」第 3 条（域内再套一层 tab）的**已知 v1 债务**：
 *    v2 = 由本页左栏**独占表达编排**、两个 board 拆成不带内部导航的域面板。
 * 2. `ProcessConfigBoard` 页内自带一块**配置就绪度**（`process-readiness`）—— 同屏于是有**两个**
 *    就绪面（设计 §2 判死线第 2 条）。v2 随上一条一起拆；v1 **不在本页另造**第三个。
 * 3. 主线今天只覆盖「工艺 / 加工费组合 / 算料」三类 → 「加工项与加工费」「工艺与路线」两域
 *    的主线步骤不是一一对应 ⇒ 这两域**不显示状态徽标**（宁缺勿滥，不编读数）。
 *
 * ## 取数为什么在**页面**（不是风格偏好）
 *
 * 仓内口径 = 「页面源码里由 `useEffect` 驱动的可执行面 = 该页第一屏读端点」
 * （`tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `page_first_screen_text`，
 * 再由 `rbac/derive.py` 四跳现取端点码 ⇒ `rbac/manifest.json` 的 `pages[].units`）。
 * 五个生产域读面与三个企业级读面**全部**在本文的 effect 里发起（不藏进子组件）。
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { Building2, Bot, Bell, Newspaper, Smartphone, HardHat } from 'lucide-react'
import Image from 'next/image'
import { QRCodeSVG } from 'qrcode.react'
import { useRouter, useSearchParams } from 'next/navigation'
import { toast } from 'sonner'
import { Button } from '@/components/ui'
import { settingsApi, uploadApi, briefingApi, productionApi } from '@/lib/api'
import { WorkerPageConfigPanel } from '@/components/settings/WorkerPageConfigPanel'
import { CalcCaliberPanel } from '@/components/settings/CalcCaliberPanel'
import { RemnantItemSizesPanel } from '@/components/settings/RemnantItemSizesPanel'
import { ConfigReadinessBar } from '@/components/settings/ConfigReadinessBar'
import ProcessingItemsPanel from '@/components/production-config/ProcessingItemsPanel'
import FeeCombinationsPanel from '@/components/production-config/FeeCombinationsPanel'
import { OperationPricePanel } from '@/components/production-config/OperationPricePanel'
import { RoutingsPanel } from '@/components/production-config/RoutingsPanel'
import { CuttingHeightPanel } from '@/components/production-config/CuttingHeightPanel'
import { CalcFormulaPanel } from '@/components/production-config/CalcFormulaPanel'
import { readImageDimensions } from '@/lib/image-dimensions'
import { getBminiH5Url } from '@/lib/bmini-h5-url'
import { usePermission } from '@/lib/permission'
import { useAuthStore } from '@/store/auth'
import { REMNANT_PARAM_COPY } from '@/lib/tenant-params'
import {
  CONFIG_DOMAINS,
  CONFIG_ZONES,
  domainsOfZone,
  findDomain,
  type ConfigDomain,
  type ConfigDomainKey,
  domainOfMainlineStep,
  resolveDomainKey,
} from '@/lib/config-center-domains'
// 🔴 主线判据的**唯一真值源**（类级守卫：tests/unit_ci_workflows/test_config_readiness_single_source.py）
import {
  judgeBaseRoutesStep,
  judgeConfigSourceStep,
  judgeDefaultRouteStep,
  judgeFeeCombinationsStep,
  judgeOperationsStep,
  missingBaseRoutesOf,
  type ReadinessState,
  worstState,
  MAINLINE_STEPS,
} from '@/lib/config-readiness'
import type { SystemSettings, AiConfig, BriefingConfig, CraftCalcConfigResponse } from '@/types'

/** `request.get` 的返回壳（`{ data: { data: 载荷 } }`）；取不到一律 `null`（**不区分失败与空**） */
type Settled = PromiseSettledResult<{ data?: { data?: unknown } }>

function unwrap(res: Settled): unknown {
  return res.status === 'fulfilled' ? (res.value?.data?.data ?? null) : null
}

function rec(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' ? (v as Record<string, unknown>) : {}
}

function arr(v: unknown): unknown[] | null {
  return Array.isArray(v) ? v : null
}

/**
 * 旧 `?tab=` → 新 `?domain=` 的**逐条**映射（仓内口径：旧深链保留、不 404）。
 *
 * 找不到（含 `?tab=params` 之外的未知值）⇒ `null`（由调用方退回第一个可见域，**不猜**）。
 */
const LEGACY_TAB_TO_DOMAIN: Record<string, ConfigDomainKey> = {
  basic: 'enterprise',
  ai: 'ai',
  workerPages: 'worker-pages',
  notification: 'notifications',
  // 原「参数总览」面已并入本页的「算料口径」域（旧链 → 域，语义等价）
  params: 'calc',
}

/**
 * 算料读面失败的**归因话术**（issue #6580；真实浏览器验收实测的缺陷）。
 *
 * 判据只有一条：**话术说的原因必须是真原因** ——
 * · `403` ⇒ 是权限（终态，给去处：找管理员开权限）；
 * · 其余（服务未起 / 超时 / 5xx）⇒ 是**服务不可用**，必须明说「不是你的权限问题」，
 *   否则商家会去要一个自己已经有的权限（实测形态：本机 ai-agent 未启动，读面 5xx，
 *   而文案写着「可能是当前岗位没有「工艺配置」权限」）。
 *
 * 顺带销账一处**陈旧菜单名**：改前文案里的「工艺配置」菜单在 issue #6580 已被删除。
 */
export function calcReadErrorCopy(err: unknown): string {
  const status =
    (err as { response?: { status?: number } })?.response?.status ??
    (err as { status?: number })?.status
  if (status === 403) {
    return '你没有查看「算料口径」的权限 —— 请联系管理员开「生产配置」权限后重试'
  }
  return '算料口径暂时读不到（读数服务暂时不可用，不是你的权限问题）—— 请稍后重试'
}

/** 三态徽标（**与主线同源**：文字取自这里，三态本身来自 `@/lib/config-readiness` 的判据） */
const STATE_BADGE: Record<ReadinessState, { text: string; className: string }> = {
  done: { text: '已配置', className: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  todo: { text: '待配置', className: 'bg-amber-50 text-amber-700 border-amber-200' },
  unknown: { text: '读不到', className: 'bg-neutral-100 text-neutral-600 border-neutral-200' },
}

export default function SettingsPage() {
  const searchParams = useSearchParams()
  const urlDomain = searchParams?.get('domain') ?? null
  const urlTab = searchParams?.get('tab') ?? null
  const router = useRouter()
  const { has } = usePermission()

  /** 域按 `requiredCode` 显隐（不持码的域**不渲染也不发请求**，issue #6573 的既定口径） */
  const visibleDomains = CONFIG_DOMAINS.filter((d) => has(d.requiredCode))

  /** 初始域：`?domain=` 优先，其次旧 `?tab=` 映射，都没有 ⇒ 第一个可见域 */
  const [activeKey, setActiveKey] = useState<string>(() => {
    // `?domain=` 走**兼容别名**（#6585 拆域后旧链接仍要能打开，见 LEGACY_DOMAIN_ALIASES）
    const fromUrl = findDomain(resolveDomainKey(urlDomain))
    if (fromUrl && has(fromUrl.requiredCode)) return fromUrl.key
    const legacy = urlTab ? LEGACY_TAB_TO_DOMAIN[urlTab] : null
    if (legacy && has(findDomain(legacy)?.requiredCode)) return legacy
    return CONFIG_DOMAINS.find((d) => has(d.requiredCode))?.key ?? CONFIG_DOMAINS[0].key
  })
  const activeDomain =
    visibleDomains.find((d) => d.key === activeKey) ??
    visibleDomains[0] ??
    CONFIG_DOMAINS[0]

  /** 切域 = 页内跳转 + 高亮（设计 G3）：URL 带 `?domain=<key>` 与 `#domain-<key>` 锚点 */
  const selectDomain = (key: string) => {
    setActiveKey(key)
    if (typeof window !== 'undefined') {
      window.history.replaceState(null, '', `/settings?domain=${key}#domain-${key}`)
    }
  }

  // ============ 配置主线（第一屏读数；判据全部来自 @/lib/config-readiness）============
  const [readinessLoading, setReadinessLoading] = useState(true)
  const [states, setStates] = useState<Record<string, ReadinessState>>({})
  const [calc, setCalc] = useState<CraftCalcConfigResponse | null>(null)
  const [calcError, setCalcError] = useState('')

  /**
   * 域徽标的三态（设计 G4：**与主线同源**）。
   *
   * 域 → 主线步骤的映射在 `config-center-domains.ts`（`mainlineSteps`）；「多步取最差」的判据在
   * `@/lib/config-readiness` 的 `worstState`（三态的唯一家）—— 本页只做**取值**，不写判断。
   */
  const stateOfDomain = (domain: ConfigDomain): ReadinessState | null =>
    worstState(domain.mainlineSteps.map((k) => states[k]))

  const load = useCallback(async () => {
    setReadinessLoading(true)
    setCalcError('')
    // 五个读面**各自独立**：一个失败不该让整块空白（失败的那步走 `unknown`，如实说「读不到」）
    const [posRes, routingsRes, comboRes, gapRes, calcRes] = await Promise.allSettled([
      productionApi.getOperationPositions(),
      productionApi.getRoutings(),
      productionApi.getFeeCombinations(),
      productionApi.getFeeGaps(),
      productionApi.getCraftCalcConfig(true),
    ])

    // ── 算料域读面（面板要的值 + 主线的第 ⑤ 步判据同源于它）
    if (calcRes.status === 'fulfilled') {
      setCalc(calcRes.value.data?.data ?? null)
    } else {
      setCalc(null)
      // ⚠️ 读面受生产域读码 `production:view` 门控（issue #5291；写面 `PUT` 仍 `processing:manage`）：
      // **权限拒绝是终态**，不是「参数有问题」—— 给可行动话术，不让商家反复重试（同族实证：issue #4103）。
      // 🔴 2026-10-09（issue #6580，真实浏览器验收实测）：改前**一律**说「可能是没有权限」——
      // 可本机 ai-agent 没起时读面同样失败（`[CRAFT_CALC_UNAVAILABLE]`），于是商家被指去找管理员
      // 开一个**本来就有的**权限（白跑一趟，且问题真因被话术掩盖）。按**状态**分流：
      setCalcError(calcReadErrorCopy(calcRes.reason))
    }

    // ── ① 工序与单价：孤儿工序跨页取不到 ⇒ 传 `null`（**不参与判定**，不是 0）
    const positions = arr(unwrap(posRes))
    const opsState = judgeOperationsStep({
      readFailed: positions === null,
      total: positions ? positions.length : 0,
      unpriced: positions ? positions.filter((p) => rec(p).unit_price == null).length : 0,
      orphans: null,
    })

    // ── ② 工艺路线 / ③ 默认路线：同一个读面
    const routeList = arr(rec(unwrap(routingsRes)).routings)
    const routesState =
      routeList === null
        ? 'unknown'
        : judgeBaseRoutesStep(missingBaseRoutesOf(routeList.map((r) => String(rec(r).name ?? ''))))
    const defaultState =
      routeList === null
        ? 'unknown'
        : judgeDefaultRouteStep(routeList.filter((r) => rec(r).is_default === true).length)

    // ── ④ 加工费组合：**缺口口径在服务端**（前端不重算组合命中）
    const comboPayload = rec(unwrap(comboRes))
    const comboCount =
      typeof comboPayload.total === 'number'
        ? comboPayload.total
        : (arr(comboPayload.combinations)?.length ?? null)
    const gapPayload = rec(unwrap(gapRes))
    const gapCount =
      typeof gapPayload.unpriced_combination_total === 'number'
        ? gapPayload.unpriced_combination_total
        : (arr(gapPayload.unpriced_combinations)?.length ?? null)

    // ── ⑤ 算料配置：`source` 三态（`stored` / `default` / 其余 ⇒ unknown）
    setStates({
      operations: opsState,
      routings: routesState,
      'default-route': defaultState,
      'fee-combinations': judgeFeeCombinationsStep(comboCount, gapCount),
      calc: judgeConfigSourceStep(
        calcRes.status === 'fulfilled'
          ? (rec(unwrap(calcRes)).source as string | undefined)
          : undefined,
      ),
    })
    setReadinessLoading(false)
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-neutral-900">企业基础设置</h1>
        <p className="text-sm text-neutral-500 mt-1">
          配置本企业的口径与生产设置：先定怎么算钱，再定车间怎么干活，最后定料怎么省。
        </p>
      </div>

      {/* 配置主线（设计 G1）：进页第一眼就是「还缺什么、下一步」—— 常驻一行摘要（§31 P1） */}
      <div className="mb-6">
        <ConfigReadinessBar
            states={states}
            loading={readinessLoading}
            // 设计 G3：「去配置」= **页内跳转**到承载这一步的那个域（不把人送出页面）
            onGoto={(stepKey) => {
              const target = domainOfMainlineStep(stepKey)
              if (target && has(target.requiredCode)) selectDomain(target.key)
              else if (target) window.location.href = MAINLINE_STEPS.find((s) => s.key === stepKey)?.href ?? '/settings'
            }}
          />
      </div>

      <div className="flex gap-6">
        {/* ── 左栏：四区 + 八个域（**唯一真值源** = @/lib/config-center-domains） ── */}
        <nav className="w-56 flex-shrink-0 space-y-5" aria-label="配置域">
          {CONFIG_ZONES.map((zone, zoneIndex) => {
            const zoneDomains = domainsOfZone(zone.key).filter((d) => has(d.requiredCode))
            // 本区一个域都看不见（不持码）⇒ 整区不渲染（不摆一个空壳区）
            if (zoneDomains.length === 0) return null
            return (
              <div key={zone.key} data-testid={`config-zone-${zone.key}`}>
                <div className="px-3 mb-1.5">
                  <div className="text-xs font-medium text-neutral-500">
                    {['一', '二', '三', '四'][zoneIndex]} · {zone.label}
                  </div>
                  <div className="text-[11px] text-neutral-400">{zone.question}</div>
                </div>
                <div className="space-y-0.5">
                  {zoneDomains.map((d) => {
                    const active = activeDomain.key === d.key
                    return (
                      <button
                        key={d.key}
                        type="button"
                        data-testid={`config-domain-${d.key}`}
                        aria-selected={active}
                        onClick={() => selectDomain(d.key)}
                        className={`w-full text-left px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                          active
                            ? 'bg-primary-50 text-primary-700'
                            : 'text-neutral-600 hover:bg-neutral-50 hover:text-neutral-900'
                        }`}
                      >
                        {d.label}
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </nav>

        {/* ── 右栏：当前域面板（**非当前域不挂载**，设计 §4 P1） ── */}
        <div className="flex-1 min-w-0 space-y-4">
          <div
            id={`domain-${activeDomain.key}`}
            data-testid={`config-domain-panel-${activeDomain.key}`}
            className="bg-white border border-neutral-200 rounded-lg p-6"
          >
            <div className="flex items-start justify-between gap-4 mb-4">
              <div className="min-w-0">
                <h2 className="text-lg font-semibold text-neutral-900">{activeDomain.label}</h2>
                <p className="text-sm text-neutral-500 mt-1">{activeDomain.summary}</p>
              </div>
              {/* 状态徽标（设计 G4）：**与主线同源** —— 取的就是喂给主线的那一份三态；
                  没被主线覆盖的域不显示徽标（不编读数） */}
              {(() => {
                const st = stateOfDomain(activeDomain)
                if (!st) return null
                const badge = STATE_BADGE[st]
                return (
                  <span
                    data-testid={`config-domain-state-${activeDomain.key}`}
                    className={`text-xs px-2 py-0.5 rounded border flex-shrink-0 ${badge.className}`}
                  >
                    {badge.text}
                  </span>
                )
              })()}
            </div>

            {activeDomain.key === 'calc' && (
              <div className="space-y-6">
                <CalcCaliberPanel calc={calc} calcError={calcError} loading={readinessLoading} />
                {/* 公式编辑：v1 时它在功能体的「算料配置」页签里，与左栏「算料口径」域编辑同一份配置
                    （`craft-calc-config`）⇒ 设计判死线第 1 条。v2 把它并进本域，功能体那份随之删除。 */}
                <CalcFormulaPanel embedded />
              </div>
            )}
            {activeDomain.key === 'processing-items' && <ProcessingItemsPanel embedded />}
            {activeDomain.key === 'fee-combinations' && <FeeCombinationsPanel embedded />}
            {activeDomain.key === 'operation-prices' && <OperationPricePanel embedded />}
            {activeDomain.key === 'craft-route' && <RoutingsPanel embedded />}
            {activeDomain.key === 'cutting-height' && <CuttingHeightPanel embedded />}
            {activeDomain.key === 'remnant-sizes' && (
              <RemnantItemSizesPanel copy={REMNANT_PARAM_COPY} />
            )}
            {activeDomain.key === 'enterprise' && <EnterpriseDomainPanel />}
            {activeDomain.key === 'ai' && <AiDomainPanel />}
            {activeDomain.key === 'worker-pages' && <WorkerPageConfigPanel />}
            {activeDomain.key === 'notifications' && <NotificationsDomainPanel />}
          </div>
        </div>
      </div>
    </div>
  )
}

/**
 * 一·报价与计费的 `enterprise` 域 —— 「企业信息」：从「基本设置」tab 原样搬入的编辑面。
 *
 * ⚠️ 本域**没有配置主线步骤**（见页头「已知 v1 债务」）⇒ 右栏不显示状态徽标。
 *
 * 🔴 **读面在本组件里由 `useEffect` 驱动**（`settings` / 简报），且本面板**只在当前域时挂载**
 * —— 仓内口径是「页面源码里由 `useEffect` 驱动的可执行面 = 第一屏读端点」
 * （`tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `page_first_screen_text`）。
 */

/** 简报配置的初值（关闭态）；真值由读面回填 */
const EMPTY_BRIEFING: BriefingConfig = { enabled: false, generateTime: '06:00' }

function EnterpriseDomainPanel() {
  // ============ 基本设置（企业信息）============
  // #3103: notificationEmail 为僵尸字段（站内信无需邮箱，后端无邮件消费逻辑），已从 UI/类型移除
  const [settings, setSettings] = useState<SystemSettings>({
    companyName: '',
    logo: '',
    notificationEnabled: false,
    // 企业编码（issue #5485）：员工登录用「用户名@企业编码」，改它会影响全员登录，故单独提示
    code: '',
  })
  const [uploadingLogo, setUploadingLogo] = useState(false)
  // Logo 预览加载失败标记：URL 失效/过期时回退到占位图标
  const [logoPreviewError, setLogoPreviewError] = useState(false)
  const [loadingSettings, setLoadingSettings] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // #5899：已落库基线 —— 字段失焦时用它判「到底改没改」：没改就不发请求（点进点出不写库）
  const savedSnapshot = useRef({ companyName: '', code: '', logo: '' })

  // ============ 智能每日经营简报（issue #3468）============
  const [briefingConfig, setBriefingConfig] = useState<BriefingConfig>(EMPTY_BRIEFING)
  const [loadingBriefing, setLoadingBriefing] = useState(false)

  const loadBriefingConfig = useCallback(async () => {
    setLoadingBriefing(true)
    try {
      const res = await briefingApi.getConfig()
      if (res.data.data) {
        setBriefingConfig({
          enabled: !!res.data.data.enabled,
          generateTime: res.data.data.generateTime || '06:00',
        })
      }
    } catch {
      // 简报配置读取失败保持默认（关闭态），不阻塞设置页
    } finally {
      setLoadingBriefing(false)
    }
  }, [])

  // 加载企业信息
  const loadSettings = useCallback(async () => {
    setLoadingSettings(true)
    try {
      const res = await settingsApi.getSettings()
      if (res.data.data) {
        setSettings({
          companyName: res.data.data.companyName || '',
          logo: res.data.data.logo || '',
          notificationEnabled: !!res.data.data.notificationEnabled,
          // #5485：企业编码由既有 GET /api/admin/settings 下发（不新开端点）
          code: res.data.data.code || '',
        })
        // Logo 变化时重置预览失败标记
        setLogoPreviewError(false)
        // #5899：记下已落库值（字段失焦判「改没改」的基线）
        savedSnapshot.current.companyName = res.data.data.companyName || ''
        savedSnapshot.current.code = res.data.data.code || ''
        savedSnapshot.current.logo = res.data.data.logo || ''
      }
    } catch (error) {
      toast.error('加载设置失败')
    } finally {
      setLoadingSettings(false)
    }
  }, [])

  // #5899：企业基础信息**取消底部「保存」按钮**（保存按钮放置太底端，用户容易忽略）。
  // 改为**字段失焦即落库**（口径与本页既有的即时保存同源：#3119 通知开关 / #3468 简报开关与生成时刻）
  const persistSettings = async (patch: Partial<SystemSettings>, successText: string) => {
    try {
      await settingsApi.updateSettings(patch)
      // #3099: 保存后立即刷新用户信息（企业名/Logo 在 /api/auth/me 内层 user.tenantName/tenantLogo），
      // 否则侧边栏/右上角需刷新页面才同步
      try {
        await useAuthStore.getState().fetchUserInfo()
      } catch {
        // 刷新失败不阻塞保存成功的提示（下次进入应用/刷新页面仍会同步）
      }
      toast.success(successText)
      return true
    } catch (error: any) {
      toast.error(error?.response?.data?.error?.message || '保存失败')
      // #5485：企业编码保存失败（格式/占用/保留字 ⇒ 422）时把输入框拉回已保存的值 ——
      // 别让一个「没生效的编码」留在框里，看起来像是已经改好了
      await loadSettings()
      return false
    }
  }

  // 公司名称（失焦即存；空值不提交，回退到已落库值）
  const commitCompanyName = async () => {
    const name = settings.companyName.trim()
    if (!name) {
      toast.error('请输入公司名称')
      await loadSettings()
      return
    }
    if (name === savedSnapshot.current.companyName) return
    if (await persistSettings({ companyName: name }, '公司名称已保存')) {
      savedSnapshot.current.companyName = name
      setSettings((prev) => ({ ...prev, companyName: name }))
    }
  }

  // 企业编码（失焦即存；它是**全员登录凭据的后半段** ⇒ 服务端校验理由原样展示并回退）
  const commitCode = async () => {
    const code = (settings.code || '').trim()
    if (!code) {
      toast.error('请输入企业编码')
      await loadSettings()
      return
    }
    if (code === savedSnapshot.current.code) return
    if (await persistSettings({ code }, '企业编码已保存')) {
      savedSnapshot.current.code = code
      setSettings((prev) => ({ ...prev, code }))
    }
  }

  // 手机端入口（issue #5668）：地址来自**单一配置** `NEXT_PUBLIC_BMINI_H5_URL`
  // （唯一读取点 = @/lib/bmini-h5-url，组件里不硬编码域名）；未配置 ⇒ 空串、**不画码**。
  const bminiH5Url = getBminiH5Url()

  const handleCopyBminiUrl = async () => {
    try {
      await navigator.clipboard.writeText(bminiH5Url)
      toast.success('链接已复制')
    } catch {
      // jsdom / 非安全上下文里没有 clipboard —— 不让复制失败变成一个未捕获异常
      toast.error('复制失败，请手动选择链接复制')
    }
  }

  const handleLogoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      toast.error('仅支持 JPG、PNG、WebP 格式')
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      toast.error('图片大小不能超过 5MB')
      return
    }
    // 分辨率校验：Logo 在侧边栏仅 32×32（预览 64×64，2x retina 即 128px），
    // 过小图片会被放大导致模糊。最小 128×128，建议正方形（展示区按正方形居中裁剪）。
    try {
      const dims = await readImageDimensions(file)
      if (dims.width < 128 || dims.height < 128) {
        toast.error(`图片分辨率过低（${dims.width}×${dims.height}），建议至少 128×128 像素且为正方形`)
        return
      }
    } catch {
      // 读取尺寸失败（环境不支持）时不阻断上传，交由后端格式/大小校验兜底
    }
    setUploadingLogo(true)
    try {
      const res = await uploadApi.uploadImage(file)
      const logoUrl = res.data.data.url
      setSettings((prev) => ({ ...prev, logo: logoUrl }))
      setLogoPreviewError(false)
      // #5899：Logo 不再有「保存」按钮 —— 上传成功即落库（失败由 persistSettings 回退并提示）
      await persistSettings({ logo: logoUrl }, 'Logo 已更新')
    } catch {
      toast.error('Logo 上传失败')
    } finally {
      setUploadingLogo(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  useEffect(() => {
    void loadSettings()
    void loadBriefingConfig()
  }, [loadSettings, loadBriefingConfig])

  return (
    <div className="space-y-6">
      {/* #5899：把「没有保存按钮」这件事**说出来** —— 否则商家会去找按钮 */}
      <p className="text-xs text-neutral-400 -mt-2">修改后自动保存，无需手动提交</p>
      {loadingSettings ? (
        <div className="text-sm text-neutral-500 py-8 text-center">加载中...</div>
      ) : (
        <div className="space-y-6">
          <div>
            <label className="block text-sm font-medium text-neutral-700 mb-1.5">
              公司名称 <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              aria-label="公司名称"
              className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              value={settings.companyName}
              onChange={(e) => setSettings({ ...settings, companyName: e.target.value })}
              onBlur={commitCompanyName}
            />
            <p className="text-xs text-neutral-400 mt-1">将展示在后台侧边栏与黄金策的企业身份中</p>
          </div>

          {/* 企业编码（issue #5485）：员工登录标识 `用户名@企业编码` 的后半段。
              ⚠️ 这是全员登录的凭据组成部分 —— 改了它，员工手上的登录方式就变了，
              所以既要能改（新企业要设可读编码），也要把影响说清楚。 */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 mb-1.5">企业编码</label>
            <input
              type="text"
              className="w-full h-9 px-3 rounded border border-neutral-300 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              placeholder="如 migao"
              value={settings.code || ''}
              onChange={(e) => setSettings({ ...settings, code: e.target.value })}
              onBlur={commitCode}
            />
            <p className="text-xs text-neutral-400 mt-1">
              员工用它登录：<span className="text-neutral-500">用户名@企业编码</span>（例如 zhangsan@{settings.code || 'migao'}）。
              全平台唯一，只能用 2~32 位小写字母、数字、连字符与下划线；格式或占用不合规时会提示原因。
            </p>
            <p className="text-xs text-amber-600 mt-1">
              修改后员工需改用新编码登录（原「用户名@旧编码」立即失效）—— 改完立即生效，请先通知员工再改。
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-neutral-700 mb-1.5">Logo</label>
            <div className="flex items-center gap-4">
              <div className="w-16 h-16 bg-neutral-100 rounded-lg flex items-center justify-center border border-neutral-200 overflow-hidden">
                {settings.logo && !logoPreviewError ? (
                  <Image
                    src={settings.logo}
                    alt="Logo"
                    width={64}
                    height={64}
                    className="w-full h-full object-cover rounded-lg"
                    unoptimized
                    onError={() => setLogoPreviewError(true)}
                  />
                ) : (
                  <Building2 className="w-8 h-8 text-neutral-400" />
                )}
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <Button variant="secondary" size="sm" onClick={() => fileInputRef.current?.click()} loading={uploadingLogo}>上传 Logo</Button>
                  {settings.logo && (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={async () => {
                        setSettings((prev) => ({ ...prev, logo: '' }))
                        setLogoPreviewError(false)
                        // #5899：移除也即时落库（不再需要点底部「保存」）
                        await persistSettings({ logo: '' }, 'Logo 已移除')
                      }}
                    >
                      移除 Logo
                    </Button>
                  )}
                </div>
                <input ref={fileInputRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={handleLogoUpload} />
                <p className="text-xs text-neutral-400 mt-1.5">
                  未设置时展示观星台默认 Logo；上传或移除后自动保存，将展示在后台侧边栏企业名旁
                </p>
              </div>
            </div>
          </div>

          {/* 手机端入口（issue #5668）：B 端 h5 落位 `app.migaozn.com/b/`，让商家**扫码就能用**。
              地址取自单一配置 NEXT_PUBLIC_BMINI_H5_URL（唯一读取点 = @/lib/bmini-h5-url）。
              🔴 未配置时**不画二维码**（只给一句明确说明）—— 画一个指向空/错地址的码，
              用户扫出来是白屏或别的站点，而页面上一切看起来正常（同族判据：缺码不画假码）。 */}
          <div className="border-t border-neutral-100 pt-6" data-testid="bmini-h5-entry">
            <div className="flex items-start gap-3 mb-4">
              <div className="w-9 h-9 rounded-lg bg-primary-50 flex items-center justify-center flex-shrink-0">
                <Smartphone className="w-5 h-5 text-primary-600" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-neutral-900">手机端入口</h3>
                <p className="text-sm text-neutral-500 mt-0.5">手机浏览器扫码使用黄金策商家端</p>
              </div>
            </div>
            {bminiH5Url ? (
              <div className="flex items-start gap-4">
                <div className="p-2 bg-white border border-neutral-200 rounded-lg">
                  <QRCodeSVG value={bminiH5Url} size={112} title={bminiH5Url} data-testid="bmini-h5-qr" />
                </div>
                <div className="min-w-0">
                  <p className="text-xs text-neutral-500">用手机相机或「扫一扫」打开：</p>
                  <code className="block mt-1 text-xs text-neutral-700 break-all" data-testid="bmini-h5-url">
                    {bminiH5Url}
                  </code>
                  <Button variant="secondary" size="sm" className="mt-2" onClick={handleCopyBminiUrl}>
                    复制链接
                  </Button>
                </div>
              </div>
            ) : (
              <p className="text-sm text-neutral-500" data-testid="bmini-h5-unconfigured">
                移动端地址未配置 —— 部署时设置 <code className="text-neutral-700">NEXT_PUBLIC_BMINI_H5_URL</code>
                后重新构建即可。未配置时这里不显示二维码，以免扫到无效地址。
              </p>
            )}
          </div>

          {/* 智能每日经营简报（issue #3468，企业开关） */}
          <div className="border-t border-neutral-100 pt-6">
            <div className="flex items-start gap-3 mb-4">
              <div className="w-9 h-9 rounded-lg bg-primary-50 flex items-center justify-center flex-shrink-0">
                <Newspaper className="w-5 h-5 text-primary-600" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-neutral-900">智能每日经营简报</h3>
                <p className="text-sm text-neutral-500 mt-0.5">
                  AI 每天清晨自动整理「昨日回顾 · 今日必办 · 风险预警 · 优化建议」，辅助管理者决策
                </p>
              </div>
            </div>
            {loadingBriefing ? (
              <div className="text-sm text-neutral-500 py-4 text-center">加载中...</div>
            ) : (
              <div className="space-y-4">
                {/* 企业开关（即时保存） */}
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-neutral-700">启用智能每日经营简报</div>
                    <div className="text-xs text-neutral-500">
                      开启后：立即生成今日简报、此后每日定时生成、侧边栏显示「每日简报」入口；关闭后：停止生成、入口隐藏（历史保留）
                    </div>
                  </div>
                  <button
                    aria-label="启用智能每日经营简报开关"
                    className={`relative w-11 h-6 shrink-0 rounded-full transition-colors ${
                      briefingConfig.enabled ? 'bg-primary-600' : 'bg-neutral-300'
                    }`}
                    onClick={async () => {
                      const next = !briefingConfig.enabled
                      const prev = briefingConfig
                      setBriefingConfig({ ...prev, enabled: next })
                      try {
                        const res = await briefingApi.updateConfig({ enabled: next })
                        // P2-4: toast 与真实结果一致 —— 开启后今日简报可能生成失败
                        // （LLM 不可用等），不无条件宣称「已生成」
                        const cfg = res.data.data
                        setBriefingConfig({
                          enabled: !!cfg?.enabled,
                          generateTime: cfg?.generateTime || '06:00',
                        })
                        toast.success(next
                          ? '已开启智能每日经营简报，今日简报将尽快生成'
                          : '已关闭智能每日经营简报')
                      } catch {
                        setBriefingConfig(prev)
                        toast.error('保存失败')
                      }
                    }}
                  >
                    <span
                      className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow ${
                        briefingConfig.enabled ? 'translate-x-5' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>

                {/* 生成时刻（即时保存） */}
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="text-sm font-medium text-neutral-700">每日生成时刻</div>
                    <div className="text-xs text-neutral-500">默认 06:00，按企业需要调整（24 小时制 HH:mm）</div>
                  </div>
                  <input
                    aria-label="简报每日生成时刻"
                    type="time"
                    value={briefingConfig.generateTime}
                    disabled={!briefingConfig.enabled}
                    onChange={(e) => setBriefingConfig({ ...briefingConfig, generateTime: e.target.value })}
                    onBlur={async () => {
                      const time = briefingConfig.generateTime
                      if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(time)) {
                        toast.error('生成时刻格式不正确，应为 HH:mm')
                        await loadBriefingConfig()
                        return
                      }
                      try {
                        await briefingApi.updateConfig({ generateTime: time })
                        toast.success('简报生成时刻已更新')
                      } catch {
                        toast.error('保存失败')
                        await loadBriefingConfig()
                      }
                    }}
                    className="h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 disabled:bg-neutral-50 disabled:text-neutral-400"
                  />
                </div>

                <p className="text-[11px] leading-relaxed text-neutral-400">
                  数据安全：简报仅使用经营聚合数据，客户隐私信息不会进入 AI 生成环节；所有数字与经营数据源核对一致后才展示。
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/** 四·企业与账号的 `ai` 域：从「AI 客服设置」tab 原样搬入的编辑面 */
function AiDomainPanel() {
  const defaultAiConfig: AiConfig = { botName: '元元', greetingTemplate: '' }
  const [aiConfig, setAiConfig] = useState<AiConfig>(defaultAiConfig)
  const [loadingAiConfig, setLoadingAiConfig] = useState(false)
  const savedAiSnapshot = useRef({ botName: '', greetingTemplate: '' })

  // 加载 AI 客服设置
  const loadAiConfig = useCallback(async () => {
    setLoadingAiConfig(true)
    try {
      const res = await settingsApi.getAiConfig()
      if (res.data.data) {
        setAiConfig({ ...defaultAiConfig, ...res.data.data })
        // #5899：同上的已落库基线（AI 客服名称 / 欢迎语）
        savedAiSnapshot.current.botName = res.data.data.botName || ''
        savedAiSnapshot.current.greetingTemplate = res.data.data.greetingTemplate || ''
      }
    } catch (e) {
      toast.error('加载 AI 客服设置失败')
    } finally {
      setLoadingAiConfig(false)
    }
  }, [])

  useEffect(() => {
    void loadAiConfig()
  }, [loadAiConfig])

  // AI 客服名称 / 欢迎语（#5899：失焦即存，取消底部「保存」按钮）
  const commitAiConfig = async (field: 'botName' | 'greetingTemplate') => {
    const value = field === 'botName' ? aiConfig.botName.trim() : aiConfig.greetingTemplate
    if (field === 'botName' && !value) {
      toast.error('请输入 AI 客服名称')
      await loadAiConfig()
      return
    }
    if (value === savedAiSnapshot.current[field]) return
    try {
      await settingsApi.updateAiConfig({ ...aiConfig, [field]: value })
      savedAiSnapshot.current[field] = value
      setAiConfig((prev) => ({ ...prev, [field]: value }))
      toast.success(field === 'botName' ? 'AI 客服名称已保存' : '欢迎语已保存，顾客侧将按新配置生效')
    } catch (e) {
      toast.error('保存失败')
      await loadAiConfig()
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-3 -mt-2">
        <div className="w-9 h-9 rounded-lg bg-primary-50 flex items-center justify-center flex-shrink-0">
          <Bot className="w-5 h-5 text-primary-600" />
        </div>
        <div>
          <p className="text-sm text-neutral-500 mt-0.5">
            配置顾客在对话中看到的 AI 客服助手（元元）的名称与欢迎语
          </p>
          {/* #5899：同「基本设置」—— 没有保存按钮，改动即时生效 */}
          <p className="text-xs text-neutral-400 mt-1">修改后自动保存，无需手动提交</p>
        </div>
      </div>
      {loadingAiConfig ? (
        <div className="text-sm text-neutral-500 py-8 text-center">加载中...</div>
      ) : (
        <div className="space-y-6">
          <div>
            <label className="block text-sm font-medium text-neutral-700 mb-1.5">
              AI 客服名称 <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              className="w-full h-9 px-3 rounded border border-neutral-300 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              placeholder="元元"
              value={aiConfig.botName}
              onChange={(e) => setAiConfig({ ...aiConfig, botName: e.target.value })}
              onBlur={() => void commitAiConfig('botName')}
            />
            <p className="text-xs text-neutral-500 mt-1.5">顾客在对话中看到的 AI 客服助手名称（默认：元元）</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-neutral-700 mb-1.5">欢迎语</label>
            <textarea
              rows={3}
              className="w-full px-3 py-2 rounded border border-neutral-300 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
              placeholder="您好，我是元元，有什么可以帮您？"
              value={aiConfig.greetingTemplate}
              onChange={(e) => setAiConfig({ ...aiConfig, greetingTemplate: e.target.value })}
              onBlur={() => void commitAiConfig('greetingTemplate')}
            />
            <p className="text-xs text-neutral-500 mt-1.5">顾客发起对话时看到的第一条消息，支持变量 {'{customer_name}'}</p>
          </div>
        </div>
      )}
    </div>
  )
}

/** 四·企业与账号的 `notifications` 域：从「通知设置」tab 原样搬入（#3119：开关即时保存） */
function NotificationsDomainPanel() {
  const [notificationEnabled, setNotificationEnabled] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const res = await settingsApi.getSettings()
        if (alive && res.data.data) setNotificationEnabled(!!res.data.data.notificationEnabled)
      } catch {
        // 读失败保持关闭态展示（开关本身仍可点，失败会 toast + 回滚）
      } finally {
        if (alive) setLoaded(true)
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  // #3119: 通知开关即时保存（开关类配置点击即生效，无需独立保存按钮）
  const handleToggleNotification = async () => {
    const next = !notificationEnabled
    // 乐观更新：先切 UI，失败回滚
    setNotificationEnabled(next)
    try {
      await settingsApi.updateSettings({ notificationEnabled: next })
      toast.success(next ? '已开启系统通知' : '已关闭系统通知')
    } catch (e) {
      setNotificationEnabled(!next)
      toast.error('保存失败')
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium text-neutral-700">启用系统通知</div>
          <div className="text-xs text-neutral-500">控制订单、客服等重要事件站内通知的发送；关闭后不再产生新的站内通知（历史通知保留）</div>
        </div>
        <button
          aria-label="启用系统通知开关"
          className={`relative w-11 h-6 shrink-0 rounded-full transition-colors ${
            notificationEnabled ? 'bg-primary-600' : 'bg-neutral-300'
          }`}
          onClick={handleToggleNotification}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow ${
              notificationEnabled ? 'translate-x-5' : 'translate-x-0'
            }`}
          />
        </button>
      </div>
      {!loaded && <p className="text-xs text-neutral-400">开关状态读取中…</p>}
    </div>
  )
}
