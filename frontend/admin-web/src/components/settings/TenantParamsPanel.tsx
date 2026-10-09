'use client'

/**
 * 「参数总览」面板（issue #5131 · 增量 1）—— **企业参数中心**。
 *
 * 设计真值源 = `docs/design/tenant-params-center.md`；规范 = `migao-dev-flow` **§22 配置类页面规范**。
 *
 * ## 本组件做什么 / 不做什么（照实登记）
 *
 * ✅ **做**：把散在 6 个页面的商家可配参数**一处列出**（§22 P1 按域分组 + 常用/高级渐进披露），
 * 每个参数给 **三件套**（`label` + `hint` 口径 + `impact` 影响什么，§22 P2），
 * 并标出**该租户是否在用引擎默认值**（§22 P3，**租户级**）。
 * ✅ **还做 P4**：算料域挂 `OversizeThresholdPreview`（阈值试算，双列对照、服务端判定真值、不保存）
 * —— ⚠️ **只覆盖超高 / 超宽两个阈值键**（算料试算端点不收 `config`，其余算料参数做不到「改前预演」）。
 *
 * ✅ **#5146 起还承载「余料回收」域**（§22 P1）：小件用料尺寸表是**行式**参数，
 * 按「一处入口」的要求**挂进本页本域**（{@link RemnantItemSizesPanel} 页内渲染），
 * 而不是另开第二个配置页 / 第二个 settings 段。
 *
 * 🔵 **#6580 起算料域的编辑面搬进 `CalcCaliberPanel`**（企业基础设置页按域分栏也要渲染它）：
 * 本组件对算料域**委托**给那个面板（`param-*` / `calc-caliber-panel` 的 testid 与渲染形态逐条不变），
 * 其余域仍在本文内渲染。「参数总览」不再是独立菜单项（旧链 `/settings/params` 保留为**重定向**，
 * 见该路由的页头注释），但本面板仍是**可复用**的域渲染件（判据仍钉着它）。
 *
 * ## ❌ 不做（见设计文档 §6 未实装登记）
 *
 * - **P3 逐键「我改过没有」** —— 需要读面补 `defaults` 字段（增量 2）；
 * - **P4 推广到其余算料参数** —— 前置：给算料试算端点加 `config` 透传；
 * - **P6 变更留痕 / P7 AI 辅助** —— 增量 3。
 * ⇒ 本增量交付的是「**看得见 + 两个改钱参数能预演**」；**其余算料参数仍预演不了**，不得写成已闭环。
 *
 * ⚠️ **本段曾写「❌ 不做 P4 改钱参数预览 …… 本增量交付的是「看得见」，不是「预演得了」」** ——
 * 那是 P4 落地**之前**的登记；P4 随后并入本增量（同一文件即渲染它）⇒ 该句已过时，本次按实际改判（issue #5137）。
 *
 * ## 纪律
 *
 * 🔴 **本组件不判任何口径、不算任何钱**：值一律来自服务端读面，原样展示；
 * 判定与取价只在服务端（同 `craft-calc-glossary.ts` 的纪律）。
 * 参数文案一律取自 `@/lib/tenant-params`（**文案里不出现数字**，§22 基线 ①，有守卫）。
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import Link from 'next/link'
import { ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'
import { settingsApi } from '@/lib/api'
import { scalarCountOf, type ParamDomain } from '@/lib/tenant-params'
import { PARAM_DOMAINS } from '@/lib/tenant-params'
import type { AiConfig, CraftCalcConfigResponse } from '@/types'
import { CalcCaliberPanel, ParamScalarRow } from '@/components/settings/CalcCaliberPanel'
import { RemnantItemSizesPanel } from '@/components/settings/RemnantItemSizesPanel'
import { usePermission } from '@/lib/permission'
import { InlineMarkdown } from '@/lib/inline-markdown'

/** 本组件的入参（**受控**：算料域的数据由页面取，见下方 `TenantParamsPanelProps` 的说明） */
export interface TenantParamsPanelProps {
  /**
   * 算料域读面（**由页面取数**，issue #6573）：仓内口径是「页面源码里由 `useEffect` 驱动的
   * 可执行面 = 第一屏读端点」（`tests/unit_ci_workflows/test_agent_permission_parity.py` 的
   * `MENU_READ_ENDPOINT_ANCHORS` 那一跳要看得见它）⇒ 第一屏的取数**不藏在子组件里**。
   */
  calc: CraftCalcConfigResponse | null
  /** 算料读面的错误话术（空 = 没出错）；页面负责区分「没配」与「没权限」 */
  calcError: string
  /** 算料读面是否仍在路上（**不谎报**：加载中不把任何参数画成「未配置」） */
  loading: boolean
  /** 「配置主线」槽位（页面用 `@/lib/config-readiness` 的纯判据算好后渲染进来） */
  readiness?: ReactNode
}

export function TenantParamsPanel({
  calc,
  calcError,
  loading,
  readiness,
}: TenantParamsPanelProps) {
  const { has } = usePermission()
  /**
   * 域级「看得见 ⇒ 打得开」（issue #6573）：**不持该码的域既不渲染也不请求**。
   *
   * 本页的门是 `production:view`（= 算料域的读码）；AI 客服域另需 `system:manage`、
   * 余料回收域另需 `processing:manage` —— 三个码各自管自己的域，谁也不替谁开门。
   * ⚠️ 这里**不是**在放宽门禁：能打开某域的人，本来就是该域读端点放行的人。
   */
  const visibleDomains = PARAM_DOMAINS.filter((d) => !d.requiredCode || has(d.requiredCode))
  const [activeKey, setActiveKey] = useState<string>(
    visibleDomains[0]?.key ?? PARAM_DOMAINS[0].key,
  )
  const [ai, setAi] = useState<AiConfig | null>(null)
  const [aiRequested, setAiRequested] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)

  /** AI 客服域的读面（懒加载；只在**持码**且切到该域时发一次，失败即 `null` ⇒ 该域不谎报值） */
  const loadAi = useCallback(async () => {
    const res = await settingsApi.getAiConfig().catch(() => null)
    setAi(res?.data?.data ?? null)
  }, [])

  const aiVisible = has('system:manage')
  useEffect(() => {
    if (activeKey !== 'ai' || !aiVisible || aiRequested) return
    setAiRequested(true)
    void loadAi()
  }, [activeKey, aiVisible, aiRequested, loadAi])

  const domain = visibleDomains.find((d) => d.key === activeKey) ?? visibleDomains[0] ?? PARAM_DOMAINS[0]
  /**
   * 「未配置（正在用引擎默认值）」**只有在真知道答案时才许说**（issue #6573 收口）：
   * 读面还在路上（`loading`）或读失败（`calcError`）时 `calc === null`，而
   * `isUsingEngineDefault(undefined) === true` —— 不设栏就会在**首屏那一瞬**把「还不知道」
   * 说成「你没配」（`param-unset-*` 徽标 + 顶部那条横幅）。这与本仓的「不谎报」纪律相抵
   * （同族：`config-readiness.ts` 把读失败判成 `unknown` 而不是 `todo`）。
   *
   * ⚠️ 算料域的那一份由 {@link CalcCaliberPanel} 自己按同样的口径算（同一 props 输入）；
   * 本变量只服务**非算料**域（当前 = AI 客服域）。
   */
  const usingDefault = !loading && !calcError && domain.key === 'calc' && calc?.source !== 'stored'

  /** 值一律来自服务端读面，**原样**展示（本组件不做任何换算） */
  const valueOf = (d: ParamDomain, key: string): string => {
    const bag: unknown = d.key === 'ai' ? ai : undefined
    const v = (bag as Record<string, unknown> | null | undefined)?.[key]
    return v === undefined || v === null || v === '' ? '—' : String(v)
  }

  return (
    <div data-testid="tenant-params-panel" className="space-y-4">
      <div className="bg-white border border-neutral-200 rounded-lg p-6">
        <h2 className="text-lg font-semibold text-neutral-900">参数总览</h2>
        <p className="text-sm text-neutral-500 mt-1">
          一处查看本企业可配的参数与口径 —— 按域分组，逐项写清「这是什么」与「改它会怎样」。
        </p>
      </div>

      {/* 配置主线（issue #6573）：跨页配置的**一条路径** —— 常驻一行摘要 + 按需展开（§31 P1）。
          它排在最上面：用户进这一页要回答的第一个问题是「我还缺什么、下一步去哪」。
          本槽位由页面传入（取数与判定都在页面的 effect 驱动面上，见本文件头注释）。 */}
      {readiness}

      <div className="flex gap-6">
        {/* P1 域分组（第一层导航） */}
        <div className="w-40 flex-shrink-0">
          <nav className="space-y-1" aria-label="参数域">
            {visibleDomains.map((d) => (
              <button
                key={d.key}
                type="button"
                data-testid={`param-domain-${d.key}`}
                aria-selected={activeKey === d.key}
                onClick={() => {
                  setActiveKey(d.key)
                  setAdvancedOpen(false)
                }}
                className={`w-full text-left px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  activeKey === d.key
                    ? 'bg-primary-50 text-primary-700'
                    : 'text-neutral-600 hover:bg-neutral-50 hover:text-neutral-900'
                }`}
              >
                <InlineMarkdown text={d.label} />
                {scalarCountOf(d) > 0 && (
                  <span className="ml-1 text-[11px] text-neutral-400">{scalarCountOf(d)}</span>
                )}
              </button>
            ))}
          </nav>
        </div>

        <div className="flex-1 min-w-0 space-y-4">
          <div className="bg-white border border-neutral-200 rounded-lg p-6">
            <h3 className="text-base font-semibold text-neutral-900">
              <InlineMarkdown text={domain.label} />
            </h3>
            <p className="text-sm text-neutral-600 mt-1">
              <InlineMarkdown text={domain.summary} />
            </p>

            {/* 算料域（#6580）：整段交给抽出后的编辑面 —— testid / 文案 / 三态口径逐条不变，
                两处（本面板 + 企业基础设置页的「算料口径」域）**同一份实现**。 */}
            {domain.key === 'calc' ? (
              <div className="mt-4">
                <CalcCaliberPanel calc={calc} calcError={calcError} loading={loading} />
              </div>
            ) : (
              <>
                {domain.common && domain.common.length > 0 && (
                  <div className="mt-4 space-y-3">
                    {domain.common.map((p) => (
                      <ParamScalarRow
                        key={p.key}
                        param={p}
                        value={loading ? '…' : valueOf(domain, p.key)}
                        unset={usingDefault && domain.key === 'ai'}
                      />
                    ))}
                  </div>
                )}

                {domain.advanced && domain.advanced.length > 0 && (
                  <div className="mt-4">
                    <button
                      type="button"
                      data-testid={`param-advanced-toggle-${domain.key}`}
                      aria-expanded={advancedOpen}
                      onClick={() => setAdvancedOpen((v) => !v)}
                      className="flex items-center gap-1 text-xs font-medium text-neutral-600 hover:text-neutral-900"
                    >
                      {advancedOpen ? (
                        <ChevronDown className="w-4 h-4" />
                      ) : (
                        <ChevronRight className="w-4 h-4" />
                      )}
                      高级（{domain.advanced.length}）—— 一般不常改
                    </button>
                    {advancedOpen && (
                      <div data-testid={`param-advanced-${domain.key}`} className="mt-3 space-y-3">
                        {domain.advanced.map((p) => (
                          <ParamScalarRow
                            key={p.key}
                            param={p}
                            value={loading ? '…' : valueOf(domain, p.key)}
                            unset={usingDefault}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* 行式配置：只给入口（列表编辑与标量表单不是一类） */}
                {domain.rows && domain.rows.length > 0 && (
                  <div className="mt-4 space-y-3">
                    {domain.rows.map((r) => (
                      <Link
                        key={r.href}
                        href={r.href}
                        data-testid={`param-row-${r.href}`}
                        className="block border border-neutral-200 rounded-lg p-4 hover:border-primary-300"
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-neutral-900">
                            <InlineMarkdown text={r.label} />
                          </span>
                          <ExternalLink className="w-3.5 h-3.5 text-neutral-400" />
                        </div>
                        <p className="text-xs text-neutral-500 mt-1">
                          <InlineMarkdown text={r.hint} />
                        </p>
                        <p className="text-xs text-neutral-600 mt-1">钱在哪：{r.money}</p>
                      </Link>
                    ))}
                  </div>
                )}

                {/* 内联编辑的参数（`inline`，issue #5146）：行式参数**挂进本域、编辑器在本页内** ——
                    §22 P1 要求「一处入口」，所以不为它另开一个配置页 / 第二个 settings 段。
                    加了面板而不加这个渲染分支 ⇒ 参数**静默不显示**（配置页最坏的形态）
                    ⇒ 守卫 `tests/unit/components/TenantParamsPanel.test.tsx` 逐面板钉住这一条。 */}
                {domain.inline?.panel === 'remnant-specs' && (
                  <div className="mt-4">
                    <RemnantItemSizesPanel copy={domain.inline.copy} />
                  </div>
                )}

                {domain.edit && (
                  <div className="mt-5 pt-4 border-t border-neutral-100">
                    <Link
                      href={domain.edit.href}
                      data-testid={`param-edit-${domain.key}`}
                      className="inline-flex items-center gap-1 text-sm font-medium text-primary-700 hover:underline"
                    >
                      <InlineMarkdown text={domain.edit.label} />
                      <ExternalLink className="w-3.5 h-3.5" />
                    </Link>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default TenantParamsPanel
