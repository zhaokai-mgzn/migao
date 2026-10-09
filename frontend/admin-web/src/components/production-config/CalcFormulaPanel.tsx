'use client'

/**
 * **算料公式面板**（issue #6585 P1：配置指挥台 v2 的「① 算料口径」域里**板子独有**的那一块）。
 *
 * ## 为什么只有「公式 + 读数原因」两块（不是整个算料配置）
 *
 * v2 的口径：同一份配置（`GET/PUT /production/craft-calc-config`）**只许有一个编辑面**。
 * 「算料口径」域的参数标量面已经是 `frontend/admin-web/src/components/settings/CalcCaliberPanel.tsx`
 * （逐键只读展示 + 六档分组），而板子的「算料配置」tab 里**多出来**两块它没有的东西：
 *
 * 1. **公式编辑**（`craft-calc-config-default_formula`）—— 兜底公式是**写面**（`CalcCaliberPanel` 不写）；
 * 2. **读数原因**（`craft-calc-config-reasons`）—— 保存被拒时后端逐条理由就地展示。
 *
 * ⇒ 本面板**只搬这两块**，**不重复**搬标量/档位/拼色/保存按钮（那会造出第二份口径）。
 *
 * ## 为什么这里带保存按钮
 *
 * 读数原因**只在写面被拒时**产生（读面本身不产理由）。若本面板只渲染一个复选/只读公式，
 * 原因块就是**死代码**、公式也永远改不了 ⇒ 面板自带一个最小写面：本地草稿改公式 → 保存时
 * 发**全量键**（后端 `PUT` 是全量替换，缺键会静默回默认值 —— 与板子同一条契约），
 * 被拒时把 `error.details[].message` 逐条渲染进 `craft-calc-config-reasons`。
 *
 * ⚠️ **如实登记（集成面须知道）**：板子的「算料配置」tab 今日**仍在**渲染它自己那份公式 `<select>`
 * 与理由块（163 条判据逐条钉住它们，本包**零行为变更**）⇒ 在 v2 真正删掉板子那个 tab 之前，
 * 同一份配置会有**两个编辑面**。本包不擅自删板子那一份（那会让 `production-routings.test.tsx`
 * 的「公式值 / PUT 带全量键 / 422 逐条理由」三条判据当场红）；收敛动作属 v2 集成方的编排。
 *
 * ## `embedded`
 *
 * `embedded=true` ⇒ **不渲染本层区块标题**；其余（读面、公式控件、理由块、保存）一律相同。
 */
import { useCallback, useEffect, useState } from 'react'
import { AlertCircle } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui'
import { productionApi } from '@/lib/api'
import { isErrorToastShown } from '@/lib/api-error'
import { CALC_PARAM_COPY } from '@/lib/craft-calc-glossary'
import { craftCalcConfigGuardReasons } from '@/lib/production-guard-reasons'
import { CRAFT_CALC_FORMULA_LABELS } from '@/lib/craft-calc-request'
import { inputCls } from '@/components/production-config/utils'
import type { CraftCalcConfig, CraftCalcConfigResponse } from '@/types'

/**
 * 兜底公式的可读文案（取值域由后端枚举给；这里只做展示映射）。
 *
 * ⚠️ **单一真值** = `@/lib/craft-calc-request` 的 `CRAFT_CALC_FORMULA_LABELS`（issue #4878 独立复核）：
 * 与板子**同一张表**，不各写一份（改一处忘一处就静默分叉）。
 */
const CALC_FORMULA_LABEL: Record<string, string> = CRAFT_CALC_FORMULA_LABELS

export function CalcFormulaPanel({ embedded = false }: { embedded?: boolean } = {}) {
  /** 读面响应（含 `source`：`default` = 系统默认值 / `stored` = 已保存的商家配置） */
  const [calcConfig, setCalcConfig] = useState<CraftCalcConfigResponse | null>(null)
  /** 表单草稿（**全量** —— 写面是全量替换，缺键会静默回默认） */
  const [calcDraft, setCalcDraft] = useState<CraftCalcConfig | null>(null)
  const [calcError, setCalcError] = useState('')
  /** 保存被拒的逐条理由（**不吞**成一句「保存失败」—— 后端一次列出每一处不合法） */
  const [calcReasons, setCalcReasons] = useState<string[]>([])
  const [calcBusy, setCalcBusy] = useState(false)

  /**
   * 读本租户生效的算料配置。
   *
   * 页面**不持有任何默认值**：本租户没配置行时后端回的是**算料引擎默认值**
   * （`source='default'`）⇒ 直接渲染它（在 TS 侧抄一份默认值 = 第二份会漂的默认值）。
   */
  const loadCalcConfig = useCallback(async () => {
    try {
      const res = await productionApi.getCraftCalcConfig()
      const data = res.data?.data ?? null
      setCalcConfig(data)
      setCalcDraft(data?.config ?? null)
      setCalcError('')
    } catch (e) {
      setCalcConfig(null)
      setCalcDraft(null)
      setCalcError('算料配置加载失败，请稍后重试')
      if (!isErrorToastShown(e)) toast.error('算料配置加载失败')
    }
  }, [])

  useEffect(() => {
    if (calcConfig === null && calcError === '') void loadCalcConfig()
  }, [calcConfig, calcError, loadCalcConfig])

  /**
   * 保存（`PUT` = **全量替换**）。
   *
   * 失败 ⇒ **逐条**展示后端理由 + **不**改本地草稿（更不静默写回默认值 —— 静默 = 商家以为改了、
   * 系统按默认算 ⇒ 算错钱且无人知道）。
   */
  async function saveCalcConfig() {
    if (!calcDraft) return
    setCalcBusy(true)
    setCalcReasons([])
    try {
      const res = await productionApi.updateCraftCalcConfig(calcDraft)
      const data = res.data?.data ?? null
      setCalcConfig(data)
      setCalcDraft(data?.config ?? calcDraft)
      toast.success('算料配置已保存，之后的算料按当前配置计算')
    } catch (e) {
      setCalcReasons(craftCalcConfigGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('算料配置保存失败')
    } finally {
      setCalcBusy(false)
    }
  }

  return (
    <section className="space-y-3" data-testid="calc-formula-panel">
      {!embedded && (
        <div className="mb-1">
          <h2 className="text-base font-medium text-neutral-900">算料公式</h2>
          <p className="mt-0.5 text-sm text-neutral-500">
            兜底公式：韩褶 / 打孔按工艺自动推导；推导不适用时用这条备用公式。
          </p>
        </div>
      )}

      {calcError !== '' && (
        <div className="flex items-center gap-3 text-sm text-danger-600" data-testid="craft-calc-config-error">
          <AlertCircle className="h-4 w-4" />
          <span>{calcError}</span>
          <Button
            size="sm"
            variant="secondary"
            data-testid="craft-calc-config-retry"
            onClick={() => void loadCalcConfig()}
          >
            重试
          </Button>
        </div>
      )}

      {calcError === '' && !calcDraft && (
        <p className="text-sm text-neutral-400" data-testid="craft-calc-config-loading">
          正在读取算料配置…
        </p>
      )}

      {calcDraft && (
        <div className="space-y-4 text-sm">
          {/* 兜底公式（工艺能推导时以工艺为准，这里只是推导表缺失时的兜底） */}
          <div>
            <label className="mb-1 block text-neutral-600" htmlFor="craft-calc-config-formula">
              {CALC_PARAM_COPY.default_formula.label}
            </label>
            <select
              id="craft-calc-config-formula"
              className={inputCls}
              data-testid="craft-calc-config-default_formula"
              value={calcDraft.default_formula}
              onChange={(e) => setCalcDraft((d) => (d ? { ...d, default_formula: e.target.value } : d))}
            >
              {Object.keys(CALC_FORMULA_LABEL).map((k) => (
                <option key={k} value={k}>
                  {CALC_FORMULA_LABEL[k]}
                </option>
              ))}
            </select>
            <span className="mt-1 block text-xs text-neutral-400">
              韩褶 / 打孔按工艺自动推导公式；推导不适用时，用这条备用公式。
            </span>
          </div>

          <div className="flex items-center gap-3">
            <Button loading={calcBusy} data-testid="craft-calc-config-save" onClick={saveCalcConfig}>
              保存配置
            </Button>
            <span className="text-xs text-neutral-400">
              保存后按当前配置计算；非法值会被整份拒绝并逐条说明理由。
            </span>
          </div>

          {/* 护栏理由**逐条**展示（后端一次列出每一处不合法）—— 不吞成一句「保存失败」 */}
          {calcReasons.length > 0 && (
            <ul className="space-y-1 text-danger-600" data-testid="craft-calc-config-reasons">
              {calcReasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

export default CalcFormulaPanel
