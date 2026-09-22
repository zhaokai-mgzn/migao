'use client'

/**
 * 小件用料尺寸表（**行式可配参数**）—— 挂在「参数总览 → 余料回收」域**页内**（issue #5146）。
 *
 * ## 为什么不另开一个配置页（`migao-dev-flow` §22 P1）
 *
 * 用户裁定「**小件用料尺寸表，可以整个参数配置，未来让企业自定义**」。
 * 参数就该在**企业参数中心**里配 —— 再开一个 settings 段就是**第二个入口**，
 * 商家的「找不到」正是 §22 要治的那件事。所以本组件是**内联面板**（页内渲染），不是独立页面。
 *
 * ## §22 的落点（逐条）
 *
 * | 原则 | 本组件怎么做 |
 * |---|---|
 * | **P2 三件套** | `label` + `hint`（口径）+ `impact`（改它会怎样）由 `copy` 传入（单一真值在 `@/lib/tenant-params`）；**每一列**另有列内小字说明「用料长 / 用料宽」是什么 |
 * | **P3 默认值可见** | 表为空时显式标「**未配置（正在用默认值 = 空 ⇒ 未启用）**」；读面 `configured=false` 时把服务端的 `notice` **原样**贴出来（「没配」与「配了没匹配上」必须能分开读） |
 * | **P4 改钱的参数给护栏** | 🔴 本参数**不改钱**（不改对客价 / 加工费 / 成品尺寸）—— 组件把这句话**显式**印在参数下方，而不是让商家猜；「改完会怎样」= 启用/停用哪几个小件的余料匹配（由**真值**渲染，不写死） |
 * | **P5 术语可就地查** | 术语条目**就在本面板内**渲染（`REMNANT_TERMS`，独立锚点命名空间）；正文里的术语是**可点的锚点**，不跨页 |
 * | **基线 ① 文案不出现数字** | 本组件不写任何尺寸 / 金额字面量；一切数值来自服务端读面或用户输入 |
 *
 * ## 🔴 本组件不判任何口径、不算任何钱
 *
 * 「填了才启用」「填的键必须是工序库里真有的工序名」「余料装不装得下」全在**服务端**
 * （`RemnantService`）—— 组件只做「读出来 → 让商家改 → 提交 → 显示服务端回的结论」。
 * 提交被拒绝时**逐字**显示服务端的理由（不自己编文案、不静默丢弃）。
 */
import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, Check, Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui'
import { remnantApi } from '@/lib/api'
import { REMNANT_TERMS, glossaryRemnantAnchorOf } from '@/lib/craft-calc-glossary'
import type { ParamCopy } from '@/lib/tenant-params'
import type { RemnantSpecsView } from '@/types'

/** 编辑态的一行（尺寸在输入框里是**字符串**：不替商家做取整，提交时由服务端判定） */
interface DraftRow {
  itemKey: string
  lengthM: string
  widthM: string
  note: string
}

const EMPTY_ROW: DraftRow = { itemKey: '', lengthM: '', widthM: '', note: '' }

export function RemnantSmallItemSpecsPanel({ copy }: { copy: ParamCopy }) {
  const [view, setView] = useState<RemnantSpecsView | null>(null)
  const [rows, setRows] = useState<DraftRow[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [savedAt, setSavedAt] = useState('')

  const apply = useCallback((next: RemnantSpecsView) => {
    setView(next)
    setRows(
      next.items.map((item) => ({
        itemKey: item.itemKey,
        lengthM: String(item.lengthM),
        widthM: String(item.widthM),
        note: item.note ?? '',
      }))
    )
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await remnantApi.smallItemSpecs()
      const data = res.data?.data
      if (data) apply(data)
      else setView(null)
    } catch {
      // 读面受 `processing:manage` 门控：**权限拒绝是终态**，不是「参数有问题」——
      // 给可行动话术（同族实证：issue #4103 的 P0 形态）。
      setView(null)
      setError('小件用料尺寸读取失败（可能是当前岗位没有「工艺配置」权限）—— 请联系管理员开权限后重试')
    }
    setLoading(false)
  }, [apply])

  useEffect(() => {
    void load()
  }, [load])

  const save = useCallback(async () => {
    setSaving(true)
    setError('')
    setSavedAt('')
    try {
      const items = rows
        .filter((r) => r.itemKey.trim())
        .map((r) => ({
          itemKey: r.itemKey.trim(),
          lengthM: Number(r.lengthM),
          widthM: Number(r.widthM),
          note: r.note.trim() || undefined,
        }))
      const res = await remnantApi.putSmallItemSpecs(items)
      const data = res.data?.data
      if (data) {
        apply(data)
        setSavedAt(
          data.configured
            ? '已保存 —— 已启用的小件才会参与余料匹配'
            : '已保存（空表 = 未配置）—— 余料匹配不会产生任何建议'
        )
      }
    } catch (e) {
      // 服务端逐条理由**原样**显示（不自己编文案）：键必须是工序库里真有的工序名、尺寸必须为正
      const detail = (e as { response?: { data?: { error?: { message?: string } } } })?.response?.data
        ?.error?.message
      setError(detail || '保存失败（请检查：每一行都要填用料长与用料宽，且都为正数）')
    }
    setSaving(false)
  }, [rows, apply])

  const configured = !!view?.configured
  const enabledCount = view?.items.length ?? 0

  return (
    <div
      data-testid="param-remnant-specs"
      className="border border-neutral-200 rounded-lg p-4 space-y-3"
    >
      {/* ── §22 P2 三件套 ── */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-neutral-900">{copy.label}</span>
            {!loading && !configured && (
              <span
                data-testid="remnant-specs-unset"
                className="text-xs px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200"
              >
                未配置（正在用默认值：空 ⇒ 未启用）
              </span>
            )}
            {!loading && configured && (
              <span
                data-testid="remnant-specs-configured"
                className="text-xs px-1.5 py-0.5 rounded bg-primary-50 text-primary-700 border border-primary-200"
              >
                已启用（{enabledCount} 个小件）
              </span>
            )}
          </div>
          <p className="text-xs text-neutral-500 mt-1">{copy.hint}</p>
        </div>
      </div>

      {/* §22 P5：术语**就地**查（锚点在面板内，不跨页） */}
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
        {REMNANT_TERMS.map((term) => (
          <a
            key={term.name}
            href={`#${glossaryRemnantAnchorOf(term.name)}`}
            data-testid={`remnant-term-link-${term.name}`}
            className="text-primary-700 hover:underline"
          >
            {term.name}
          </a>
        ))}
      </div>

      {/* 🔴 「没配」与「配了但没匹配上」必须能分开读（§22 P3 + 判据 4「未配置不静默」） */}
      {!loading && view?.notice && (
        <div
          data-testid="remnant-specs-notice"
          className="flex items-start gap-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2"
        >
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>{view.notice}</span>
        </div>
      )}

      {error && (
        <div
          data-testid="remnant-specs-error"
          className="flex items-start gap-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2"
        >
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* ── 编辑面（一行一个小件；列 = 尺寸）── */}
      <div className="space-y-2">
        <div className="hidden sm:flex gap-2 text-[11px] text-neutral-500">
          <span className="w-40">小件（工序名）</span>
          <span className="w-28">用料长（沿卷长）</span>
          <span className="w-28">用料宽（沿门幅）</span>
          <span className="flex-1">备注</span>
        </div>
        {rows.map((row, index) => (
          <div key={index} data-testid={`remnant-spec-row-${index}`} className="flex flex-wrap gap-2">
            <input
              value={row.itemKey}
              aria-label="小件（工序名）"
              placeholder="工序名，须与工序库逐字一致"
              onChange={(e) =>
                setRows((prev) =>
                  prev.map((r, i) => (i === index ? { ...r, itemKey: e.target.value } : r))
                )
              }
              className="w-40 px-2 py-1 text-xs border border-neutral-300 rounded"
            />
            <input
              value={row.lengthM}
              aria-label="用料长"
              placeholder="用料长（米）"
              onChange={(e) =>
                setRows((prev) =>
                  prev.map((r, i) => (i === index ? { ...r, lengthM: e.target.value } : r))
                )
              }
              className="w-28 px-2 py-1 text-xs border border-neutral-300 rounded"
            />
            <input
              value={row.widthM}
              aria-label="用料宽"
              placeholder="用料宽（米）"
              onChange={(e) =>
                setRows((prev) =>
                  prev.map((r, i) => (i === index ? { ...r, widthM: e.target.value } : r))
                )
              }
              className="w-28 px-2 py-1 text-xs border border-neutral-300 rounded"
            />
            <input
              value={row.note}
              aria-label="备注"
              placeholder="备注（可选）"
              onChange={(e) =>
                setRows((prev) =>
                  prev.map((r, i) => (i === index ? { ...r, note: e.target.value } : r))
                )
              }
              className="flex-1 min-w-32 px-2 py-1 text-xs border border-neutral-300 rounded"
            />
            <button
              type="button"
              aria-label={`删除第 ${index + 1} 行`}
              data-testid={`remnant-spec-remove-${index}`}
              onClick={() => setRows((prev) => prev.filter((_, i) => i !== index))}
              className="px-2 text-neutral-400 hover:text-red-600"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ))}
        {rows.length === 0 && !loading && (
          <p data-testid="remnant-specs-empty" className="text-xs text-neutral-500">
            本企业还没有配置任何小件的用料尺寸 ⇒ 余料匹配**不会**产生建议（默认值为空 = 未启用）。
          </p>
        )}
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          data-testid="remnant-spec-add"
          onClick={() => setRows((prev) => [...prev, { ...EMPTY_ROW }])}
          className="inline-flex items-center gap-1 text-xs font-medium text-primary-700 hover:underline"
        >
          <Plus className="w-3.5 h-3.5" />
          加一个小件
        </button>
        <Button
          type="button"
          size="sm"
          data-testid="remnant-spec-save"
          disabled={saving || loading}
          onClick={() => void save()}
        >
          {saving ? '保存中…' : '保存'}
        </Button>
        {savedAt && (
          <span
            data-testid="remnant-specs-saved"
            className="inline-flex items-center gap-1 text-xs text-green-700"
          >
            <Check className="w-3.5 h-3.5" />
            {savedAt}
          </span>
        )}
      </div>

      {/* §22 P4 的护栏文案：本参数**不改钱** —— 明确说出来，而不是让商家猜 */}
      <p className="text-xs text-neutral-600 pt-2 border-t border-neutral-100">
        改它会怎样：{copy.impact}
      </p>

      {/* ── §22 P5 术语说明（**就地**：锚点就在本面板里）── */}
      <div className="pt-2 border-t border-neutral-100 space-y-2">
        <p className="text-xs font-medium text-neutral-700">口径与术语（点上面任一词跳到此处）</p>
        {REMNANT_TERMS.map((term) => (
          <div
            key={term.name}
            id={glossaryRemnantAnchorOf(term.name)}
            data-testid={`remnant-term-${term.name}`}
            className="text-xs text-neutral-600 scroll-mt-24"
          >
            <span className="font-medium text-neutral-900">{term.name}</span>
            <span className="mx-1">·</span>
            {term.definition}
            {term.criterion && <span className="block text-neutral-500">判据：{term.criterion}</span>}
            <span className="block text-neutral-500">影响：{term.impact}</span>
            {term.boundary && <span className="block text-neutral-400">边界：{term.boundary}</span>}
          </div>
        ))}
      </div>
    </div>
  )
}

export default RemnantSmallItemSpecsPanel
