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
 *
 * ❌ **不做**（见设计文档 §6 未实装登记）：
 * - **P4 改钱参数预览**（改阈值前先看算例）—— 增量 2；
 * - **P3 逐键「我改过没有」** —— 需要读面补 `defaults` 字段（增量 2）；
 * - **P6 变更留痕 / P7 AI 辅助** —— 增量 3。
 * ⇒ 本增量交付的是「**看得见**」，**不是「预演得了」**，不得写成已闭环。
 *
 * ## 纪律
 *
 * 🔴 **本组件不判任何口径、不算任何钱**：值一律来自服务端读面，原样展示；
 * 判定与取价只在服务端（同 `craft-calc-glossary.ts` 的纪律）。
 * 参数文案一律取自 `@/lib/tenant-params`（**文案里不出现数字**，§22 基线 ①，有守卫）。
 */
import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { AlertCircle, ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'
import { productionApi, settingsApi } from '@/lib/api'
import {
  PARAM_DOMAINS,
  isUsingEngineDefault,
  scalarCountOf,
  type ParamDomain,
  type ScalarParam,
} from '@/lib/tenant-params'
import type { AiConfig, CraftCalcConfigResponse } from '@/types'
import { OversizeThresholdPreview } from '@/components/settings/OversizeThresholdPreview'

export function TenantParamsPanel() {
  const [activeKey, setActiveKey] = useState<string>(PARAM_DOMAINS[0].key)
  const [calc, setCalc] = useState<CraftCalcConfigResponse | null>(null)
  const [ai, setAi] = useState<AiConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [calcError, setCalcError] = useState('')
  const [advancedOpen, setAdvancedOpen] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setCalcError('')
    // 两个读面各自独立：一个失败不影响另一个（AI 客服读面失败不该让算料区也空白）
    const [calcRes, aiRes] = await Promise.allSettled([
      productionApi.getCraftCalcConfig(),
      settingsApi.getAiConfig(),
    ])
    if (calcRes.status === 'fulfilled') {
      setCalc(calcRes.value.data?.data ?? null)
    } else {
      setCalc(null)
      // ⚠️ 读面受 `processing:manage` 门控：**权限拒绝是终态**，不是「参数有问题」——
      // 给可行动话术，不让商家反复重试（同族实证：issue #4103 的 P0 形态）。
      setCalcError('算料口径读取失败（可能是当前岗位没有「工艺配置」权限）—— 请联系管理员开权限后重试')
    }
    setAi(aiRes.status === 'fulfilled' ? (aiRes.value.data?.data ?? null) : null)
    setLoading(false)
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const domain = PARAM_DOMAINS.find((d) => d.key === activeKey) ?? PARAM_DOMAINS[0]
  const usingDefault = domain.key === 'calc' && isUsingEngineDefault(calc?.source)

  /** 值一律来自服务端读面，**原样**展示（本组件不做任何换算） */
  const valueOf = (d: ParamDomain, key: string): string => {
    const bag: unknown =
      d.key === 'calc' ? calc?.config : d.key === 'ai' ? ai : undefined
    const v = (bag as Record<string, unknown> | null | undefined)?.[key]
    return v === undefined || v === null || v === '' ? '—' : String(v)
  }

  const renderScalar = (d: ParamDomain, p: ScalarParam) => (
    <div
      key={p.key}
      data-testid={`param-${p.key}`}
      className="border border-neutral-200 rounded-lg p-4"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-neutral-900">{p.copy.label}</span>
            {usingDefault && (
              <span
                data-testid={`param-unset-${p.key}`}
                className="text-xs px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200"
              >
                未配置（正在用引擎默认值）
              </span>
            )}
          </div>
          <p className="text-xs text-neutral-500 mt-1">{p.copy.hint}</p>
        </div>
        <div className="text-right flex-shrink-0">
          <div data-testid={`param-value-${p.key}`} className="text-sm font-mono text-neutral-900">
            {loading ? '…' : valueOf(d, p.key)}
          </div>
          <div className="text-[11px] text-neutral-400 mt-0.5 font-mono">{p.key}</div>
        </div>
      </div>
      <p className="text-xs text-neutral-600 mt-2 pt-2 border-t border-neutral-100">
        改它会怎样：{p.copy.impact}
      </p>
    </div>
  )

  return (
    <div data-testid="tenant-params-panel" className="space-y-4">
      <div className="bg-white border border-neutral-200 rounded-lg p-6">
        <h2 className="text-lg font-semibold text-neutral-900">参数总览</h2>
        <p className="text-sm text-neutral-500 mt-1">
          一处查看本企业可配的参数与口径 —— 按域分组，逐项写清「这是什么」与「改它会怎样」。
        </p>
      </div>

      <div className="flex gap-6">
        {/* P1 域分组（第一层导航） */}
        <div className="w-40 flex-shrink-0">
          <nav className="space-y-1" aria-label="参数域">
            {PARAM_DOMAINS.map((d) => (
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
                {d.label}
                {scalarCountOf(d) > 0 && (
                  <span className="ml-1 text-[11px] text-neutral-400">{scalarCountOf(d)}</span>
                )}
              </button>
            ))}
          </nav>
        </div>

        <div className="flex-1 min-w-0 space-y-4">
          <div className="bg-white border border-neutral-200 rounded-lg p-6">
            <h3 className="text-base font-semibold text-neutral-900">{domain.label}</h3>
            <p className="text-sm text-neutral-600 mt-1">{domain.summary}</p>

            {domain.key === 'calc' && calcError && (
              <div
                data-testid="param-calc-error"
                className="mt-3 flex items-start gap-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2"
              >
                <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <span>{calcError}</span>
              </div>
            )}

            {usingDefault && !calcError && (
              <div
                data-testid="param-calc-using-default"
                className="mt-3 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2"
              >
                本企业尚未保存过算料口径 —— 下表**全部**为算料引擎默认值。
              </div>
            )}

            {/* P2 三件套（常用 / 高级渐进披露） */}
            {domain.common && domain.common.length > 0 && (
              <div className="mt-4 space-y-3">
                {domain.common.map((p) => renderScalar(domain, p))}
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
                    {domain.advanced.map((p) => renderScalar(domain, p))}
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
                      <span className="text-sm font-medium text-neutral-900">{r.label}</span>
                      <ExternalLink className="w-3.5 h-3.5 text-neutral-400" />
                    </div>
                    <p className="text-xs text-neutral-500 mt-1">{r.hint}</p>
                    <p className="text-xs text-neutral-600 mt-1">钱在哪：{r.money}</p>
                  </Link>
                ))}
              </div>
            )}

            {/* §22 P4：改钱的参数给预览（本页唯一能做**真预演**的两个参数 —— 见组件头注释） */}
            {domain.key === 'calc' && !calcError && (
              <OversizeThresholdPreview config={calc?.config ?? null} />
            )}

            {domain.edit && (
              <div className="mt-5 pt-4 border-t border-neutral-100">
                <Link
                  href={domain.edit.href}
                  data-testid={`param-edit-${domain.key}`}
                  className="inline-flex items-center gap-1 text-sm font-medium text-primary-700 hover:underline"
                >
                  {domain.edit.label}
                  <ExternalLink className="w-3.5 h-3.5" />
                </Link>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default TenantParamsPanel
