/**
 * 裁高（定高）配置面板（母单 #5161；设计单 `docs/design/cutting-height-config-and-terminal.md`）。
 *
 * ## 它回答什么
 * 「这台机器这一刀该多高」：`裁剪高度(部位) = 成品高 + Σ(命中的增量项)`，本租户可配。
 *
 * ## v2（issue #7997；用户 2026-10-28）
 * 用户逐字：「裁高参数是根据工序来的」「如果有布绑带工序，则需要根据加工项韩褶还是打孔分别自动算高度」
 * 「如果有接高工序，则需要一个画线参数」「其他情况都是默认定高参数」
 * 「要根据特殊选项+加工项+部位来定高度」「再允许一个默认公共（兜底）裁高参数」。
 * ⇒ 配置分**两个区块**（`scope`）：工序专用 / 公共默认；每项的命中是**条件组**
 * （跨 kind 与、组内 values 或）+ 部位。兜底是**替换**语义（用户裁定 A）。
 *
 * ## 三条实现纪律（v1 起不变）
 * 1. **页面不持有默认值**：缺行时后端回的是**默认种子** + `source='default'` ⇒ 界面显式标
 *    「当前使用系统默认值」（把默认值伪装成商家配置 = 让商家以为改过、其实没改）。
 * 2. **命中口径由服务端判**：本面板只填 `scope / position / conditions`；
 *    「哪些项命中」一律由 `POST …/preview` 回答 —— 前端再写一份匹配 = 第二份口径。
 * 3. **本版只算不写机器**：面板的终点是「给人一个可核对的数」（用户 2026-09-29 裁定①：下发先不做）。
 *
 * ## 版式自查（本机没有运行栈时，怎么「真的看一眼」）
 *
 * 2026-10-28 实证：本面板第一版把条件下拉写成 `w-full`，它落在 `flex-wrap` 行里**独占一行**
 * ⇒ 取值按钮被顶到下一行、每条目高度翻倍、整页「乱套」——**这类形态单测看不出来**（jsdom 无几何）。
 * 可复算入口（不需要起 3001 / 不连后端，用本机已装的 chromium headless）：
 *
 * ```bash
 * cd frontend/admin-web
 * # ① 建 .harness/：entry.tsx 里 `createRoot(...).render(<CuttingHeightConfigPanel />)`
 * #    api-mock.ts 导出 `cuttingHeightApi` / `productionApi` 的固定夹具；sonner 同理
 * ./node_modules/.bin/tailwindcss -c tailwind.config.ts -i src/app/globals.css -o .harness/out.css
 * ./node_modules/.bin/esbuild .harness/entry.tsx --bundle --format=iife --jsx=automatic \
 *   --inject:./.harness/globals-shim.ts --alias:@=./src \
 *   --alias:@/lib/api=./.harness/api-mock.ts --alias:sonner=./.harness/sonner-mock.ts \
 *   --outfile=.harness/bundle.js
 * "$HOME/Library/Caches/ms-playwright/chromium_headless_shell-<版本>/chrome-headless-shell-mac-arm64/chrome-headless-shell" \
 *   --headless --hide-scrollbars --force-device-scale-factor=2 --window-size=1440,1150 \
 *   --screenshot=/tmp/panel.png "file://$PWD/.harness/index.html"
 * ```
 *
 * ⇒ 读图判定：条件 chip **一行**、`部位` 下拉文字与箭尖完整、无横向滚动。`.harness/` 是临时物，不入库。
 *
 * ## 版式（修 #7153 残留、issue #7997）
 * 表格已退场：**列宽 + 单元格内边距**是「布帘被裁成布」的成因（`SELECT_CONTROL` 的 `pl-3 pr-9`
 * 在 11% 宽的列里放不下两个字），靠调百分比只是在改临界点。现在每条增量项是一张卡（字段在上、
 * 控件满列），触发条件是一排**可折行**的 chips ⇒ 结构上不存在「窄列裁字」这一类。
 */
'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { AlertCircle, ChevronDown, X } from 'lucide-react'

import NumberInput from '@/components/ui/NumberInput'
// issue #7176：配置面表单的**唯一版式原语**（浅底面板 + 栅格 + 标签在上 + 单位入框）
import FormPanel, { Field, FormGrid, fieldControl } from '@/components/ui/FormPanel'
import { cuttingHeightApi, productionApi } from '@/lib/api'
import {
  CRAFT_OPTIONS,
  derivedSpecialOptionValues,
  selectedSpecialOptionDisplayNames,
  specialOptionDisplayOptions,
} from '@/lib/order-craft-fields'
import { cn } from '@/lib/utils'
import { SELECT_CONTROL, SELECT_CONTROL_FIELD } from '@/components/ui'
import type {
  CuttingHeightCondition,
  CuttingHeightConfigBody,
  CuttingHeightConfigResponse,
  CuttingHeightItem,
  CuttingHeightPreview,
  CuttingHeightRounding,
} from '@/types'

const TRIGGER_KINDS: { value: string; label: string }[] = [
  { value: 'option', label: '特殊选项' },
  { value: 'craft', label: '安装工艺' },
  { value: 'processing_item', label: '加工项' },
  { value: 'shaped', label: '是否定型' },
]

const SCOPES: { value: string; label: string; hint: string; addLabel: string }[] = [
  {
    value: 'specific',
    label: '工序专用参数',
    hint: '勾了布绑带 / 接高等工序时用这一组。只要有一条命中，「公共默认参数」整组就不参与。',
    addLabel: '添加工序专用项',
  },
  {
    value: 'fallback',
    label: '公共默认参数',
    hint: '没有任何工序专用参数命中时才用这一组（「其他情况都是默认定高参数」）。',
    addLabel: '添加默认项',
  },
]

const POSITIONS = ['布帘', '纱帘', '帘头']

const SHAPED_VALUES: Option[] = [
  { value: 'true', label: '是' },
  { value: 'false', label: '否' },
]

interface Option {
  value: string
  label: string
}

const SCOPE_SPECIFIC = 'specific'

/** 新项的初值（key 用时间戳保证与本租户已有 key 不撞；商家可改）。 */
function newItem(order: number, scope: string): CuttingHeightItem {
  const key = `item-${Date.now().toString(36)}`
  return {
    key,
    name: '',
    value: null,
    direction: 'add',
    height_join: false,
    scope,
    position: null,
    conditions: [],
    enabled: true,
    order,
  }
}

/**
 * 多选取值下拉（闭词表）—— 选项名是 join key，手输错一个字就不命中 ⇒ 不给自由文本。
 * §31 P1：常驻面只一段文字（已选取值 / 「选择取值」），点开才渲染复选项。
 */
function ValueMultiSelect({
  ariaLabel,
  options,
  values,
  onChange,
}: {
  ariaLabel: string
  options: Option[]
  values: string[]
  onChange: (next: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    function onMouseDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [open])

  const label = (value: string) => options.find((o) => o.value === value)?.label ?? value
  const text = values.length === 0 ? '选择取值' : values.map(label).join('、')

  const toggle = (value: string) => {
    onChange(values.includes(value) ? values.filter((v) => v !== value) : [...values, value])
  }

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        aria-label={ariaLabel}
        aria-expanded={open}
        title={values.length > 0 ? text : undefined}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          SELECT_CONTROL,
          'w-auto max-w-[13rem] text-left',
          values.length === 0 && 'text-neutral-400',
        )}
      >
        <span className="block truncate">{text}</span>
      </button>
      {open && (
        <div className="absolute left-0 top-full z-40 mt-1 max-h-56 w-52 overflow-y-auto rounded-lg border border-neutral-200 bg-white p-1 shadow-card-hover">
          {options.length === 0 ? (
            <p className="px-2 py-1.5 text-xs text-neutral-400">暂无可用取值</p>
          ) : (
            options.map((o) => (
              <label
                key={o.value}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
              >
                <input
                  type="checkbox"
                  aria-label={`${ariaLabel}-${o.label}`}
                  checked={values.includes(o.value)}
                  onChange={() => toggle(o.value)}
                />
                {o.label}
              </label>
            ))
          )}
        </div>
      )}
    </div>
  )
}

/** 一条命中条件：`{kind, values}`（跨 kind 与、组内或）。 */
function ConditionRow({
  itemIndex,
  conditionIndex,
  condition,
  optionsOf,
  onChange,
  onRemove,
}: {
  itemIndex: number
  conditionIndex: number
  condition: CuttingHeightCondition
  optionsOf: (kind: string) => Option[]
  onChange: (next: CuttingHeightCondition) => void
  onRemove: () => void
}) {
  return (
    // 关键：容器**不折行**、类型下拉**不定宽占满**（`w-full` 会在 flex 行里独占一行 ⇒ 取值被顶到下一行，
    // 那正是用户截图里「条件框两行、整页乱套」的成因）。chips 之间的换行由外层的 `flex-wrap` 负责。
    <div className="inline-flex max-w-full items-center gap-1">
      {/* 下拉走共享铬（issue #7397 的类级判据：业务面每个 `<select>` 必须引用 `SELECT_CONTROL*`） */}
      <select
        className={cn(SELECT_CONTROL, 'w-auto min-w-[6.25rem]')}
        aria-label={`条件类型-${itemIndex}-${conditionIndex}`}
        value={condition.kind}
        onChange={(e) => onChange({ kind: e.target.value, values: [] })}
      >
        {TRIGGER_KINDS.map((k) => (
          <option key={k.value} value={k.value}>
            {k.label}
          </option>
        ))}
      </select>
      <ValueMultiSelect
        ariaLabel={`条件取值-${itemIndex}-${conditionIndex}`}
        options={optionsOf(condition.kind)}
        // 存量配置里可能是派生键（`余料带回-布`）⇒ 展示态收回语义名（issue #8007）；保存时写语义名
        values={
          condition.kind === 'option'
            ? selectedSpecialOptionDisplayNames(condition.values)
            : condition.values
        }
        onChange={(values) => onChange({ ...condition, values })}
      />
      <button
        type="button"
        aria-label={`删除条件-${itemIndex}-${conditionIndex}`}
        className="shrink-0 rounded p-1 text-neutral-400 hover:text-danger-600"
        onClick={onRemove}
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}

/** 一条增量项：字段在上、条件 chips 折行。 */
function ItemRow({
  index,
  item,
  optionsOf,
  onChange,
  onRemove,
}: {
  index: number
  item: CuttingHeightItem
  optionsOf: (kind: string) => Option[]
  onChange: (patch: Partial<CuttingHeightItem>) => void
  onRemove: () => void
}) {
  const conditions = item.conditions ?? []
  const patchCondition = (conditionIndex: number, next: CuttingHeightCondition) =>
    onChange({ conditions: conditions.map((c, i) => (i === conditionIndex ? next : c)) })
  const removeCondition = (conditionIndex: number) =>
    onChange({ conditions: conditions.filter((_, i) => i !== conditionIndex) })
  const addCondition = () => {
    const used = new Set(conditions.map((c) => c.kind))
    const kind = TRIGGER_KINDS.find((k) => !used.has(k.value))?.value ?? TRIGGER_KINDS[0].value
    onChange({ conditions: [...conditions, { kind, values: [] }] })
  }

  return (
    <div
      className="rounded-lg border border-neutral-200 bg-white p-2.5"
      data-testid={`cutting-height-item-${index}`}
    >
      <div className="flex flex-wrap items-end gap-2">
        <Field label="名称" htmlFor={`ch-name-${index}`} className="w-[17rem] max-w-full">
          <input
            id={`ch-name-${index}`}
            className={fieldControl()}
            aria-label={`名称-${index}`}
            value={item.name}
            onChange={(e) => onChange({ name: e.target.value })}
          />
        </Field>
        <Field label="取值" unit="米" htmlFor={`ch-value-${index}`} className="w-28">
          {/* 🔴 必须用 `NumberInput`（issue #8003）：手写 `Number(e.target.value)` 往返会把
              「0.」这类中间态当场归一成 0 ⇒ 小数点打不出来（取值要 3 位小数：0.015 / 0.145）。 */}
          <NumberInput
            id={`ch-value-${index}`}
            className={fieldControl('米')}
            aria-label={`取值-${index}`}
            value={item.value}
            decimals={3}
            placeholder="可留空"
            title="取值留空 = 有项无值：会命中，但会显式报出「未配置取值」，不按 0 算"
            onChange={(value) => onChange({ value })}
          />
        </Field>
        <Field label="部位" htmlFor={`ch-position-${index}`} className="w-28">
          <select
            id={`ch-position-${index}`}
            className={cn(SELECT_CONTROL_FIELD, 'w-full')}
            aria-label={`部位-${index}`}
            value={item.position ?? ''}
            onChange={(e) => onChange({ position: e.target.value || null })}
          >
            <option value="">不限</option>
            {POSITIONS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </Field>
        <label className="flex h-9 items-center gap-1.5 whitespace-nowrap text-sm text-neutral-600">
          <input
            type="checkbox"
            aria-label={`启用-${index}`}
            checked={item.enabled}
            onChange={(e) => onChange({ enabled: e.target.checked })}
          />
          启用
        </label>
        <button
          type="button"
          className="h-9 whitespace-nowrap px-1 text-sm text-neutral-400 underline"
          data-testid={`cutting-height-remove-${index}`}
          onClick={onRemove}
        >
          删除
        </button>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="whitespace-nowrap text-xs text-neutral-500">条件（同时满足）</span>
        {conditions.map((condition, conditionIndex) => (
          <ConditionRow
            key={`${item.key}-${conditionIndex}`}
            itemIndex={index}
            conditionIndex={conditionIndex}
            condition={condition}
            optionsOf={optionsOf}
            onChange={(next) => patchCondition(conditionIndex, next)}
            onRemove={() => removeCondition(conditionIndex)}
          />
        ))}
        <button
          type="button"
          className="h-9 whitespace-nowrap px-1 text-xs text-primary-600 underline"
          data-testid={`cutting-height-add-condition-${index}`}
          onClick={addCondition}
        >
          + 条件
        </button>
        {conditions.length === 0 && (
          <span className="text-xs text-neutral-400">无附加条件（只按部位圈范围）</span>
        )}
      </div>
    </div>
  )
}

export function CuttingHeightConfigPanel() {
  const [config, setConfig] = useState<CuttingHeightConfigBody | null>(null)
  const [source, setSource] = useState('')
  const [loadError, setLoadError] = useState('')
  const [saving, setSaving] = useState(false)
  const [preview, setPreview] = useState<CuttingHeightPreview | null>(null)
  const [previewError, setPreviewError] = useState('')
  const [processingItems, setProcessingItems] = useState<string[]>([])
  const [probe, setProbe] = useState({
    position: '布帘',
    finishedHeight: '',
    craft: '',
    options: [] as string[],
    processingItems: [] as string[],
  })

  const load = useCallback(async () => {
    try {
      const res = await cuttingHeightApi.get()
      const data: CuttingHeightConfigResponse = res.data.data
      setConfig({
        items: (data.config.items ?? []) as CuttingHeightItem[],
        rounding: data.config.rounding as CuttingHeightRounding,
      })
      setSource(data.source)
      setLoadError('')
    } catch {
      setLoadError('裁高配置加载失败，请稍后重试')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // 条件取值域（活跃加工项目录）：拿不到就留空下拉 —— **不回落**任何写死的加工项清单
  //（写死 = 第二份会漂的词表；选错一个名字 = 永远不命中）。
  useEffect(() => {
    let alive = true
    // 取值域腿按能力调用：拿不到（接口未上 / 单测只 mock 了裁高面）⇒ 空词表，**不回落**写死的加工项清单。
    const loadOptions = productionApi?.getRouteRuleOptions
    if (typeof loadOptions !== 'function') return
    loadOptions
      .call(productionApi)
      .then((res) => {
        if (alive) setProcessingItems(res.data.data?.processing_items ?? [])
      })
      .catch(() => {
        if (alive) setProcessingItems([])
      })
    return () => {
      alive = false
    }
  }, [])

  const optionsOf = useCallback(
    (kind: string): Option[] => {
      // 🔴 issue #8007：取值词表是**语义选项**（`余料带回`），布/纱派生键不进配置面 ——
      //    条件里写 base 名 ⇒ 后端按「族」匹配该订单行的任一派生键（纱帘/布帘都命中）。
      if (kind === 'option') return specialOptionDisplayOptions().map((name) => ({ value: name, label: name }))
      if (kind === 'craft') return CRAFT_OPTIONS.map((name) => ({ value: name, label: name }))
      if (kind === 'processing_item') return processingItems.map((name) => ({ value: name, label: name }))
      if (kind === 'shaped') return SHAPED_VALUES
      return []
    },
    [processingItems],
  )

  const patchItem = (index: number, patch: Partial<CuttingHeightItem>) => {
    setConfig((prev) => {
      if (!prev) return prev
      const items = prev.items.map((item, i) => (i === index ? { ...item, ...patch } : item))
      return { ...prev, items }
    })
  }

  const removeItem = (index: number) =>
    setConfig((prev) => (prev ? { ...prev, items: prev.items.filter((_, i) => i !== index) } : prev))

  const addItem = (scope: string) =>
    setConfig((prev) =>
      prev ? { ...prev, items: [...prev.items, newItem((prev.items.length + 1) * 10, scope)] } : prev,
    )

  const save = async () => {
    if (!config) return
    setSaving(true)
    try {
      const res = await cuttingHeightApi.update(config)
      setSource(res.data.data.source)
      toast.success('裁高配置已保存，之后的裁剪高度按当前配置计算')
    } catch {
      toast.error('裁高配置保存失败')
    } finally {
      setSaving(false)
    }
  }

  const runPreview = async () => {
    setPreviewError('')
    setPreview(null)
    try {
      const res = await cuttingHeightApi.preview({
        position: probe.position,
        finished_height: probe.finishedHeight,
        craft: probe.craft || undefined,
        // 🔴 配置面只选语义名（`绑带` / `余料带回`）⇒ 发给服务端前按**部位帘种**派生落库键
        //    （issue #8007 / #8108 的「录入边界正向派生」）。不派生的话，存量以派生键存储的规则
        //    （如 `布绑带`）在预演里会静默不命中，而页面看不出任何异常。
        special_options: derivedSpecialOptionValues(probe.options, probe.position),
        processing_items: probe.processingItems,
      })
      setPreview(res.data.data)
    } catch {
      setPreviewError('预演失败：请检查成品高与部位')
    }
  }

  return (
    <div className="space-y-4" data-testid="cutting-height-config-panel">
      <section className="rounded-lg border border-neutral-200 bg-white p-5">
        <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-medium text-neutral-900">裁高（定高）配置</h2>
          <span
            className={cn(
              'rounded px-2 py-0.5 text-xs',
              source === 'stored' ? 'bg-primary-50 text-primary-700' : 'bg-neutral-100 text-neutral-600',
            )}
            data-testid="cutting-height-source"
          >
            {source === 'stored' ? '已保存为您的配置' : '当前使用系统默认值'}
          </span>
        </div>
        <p className="text-sm text-neutral-500">
          裁剪高度 = 成品高 + 命中的增量项。命中按「触发条件 + 部位」判：一条里的多个条件要
          <strong>同时满足</strong>（同一个条件里选多个取值 = 满足任一个即可），取值要
          <strong>逐字</strong>等于订单上的特殊选项名 / 安装工艺 / 加工项名（写错一个字就不命中）。
          <strong>取值留空 = 有项无值</strong>：它会命中、但会被显式报出「未配置取值」，<strong>不按 0 算</strong>。
        </p>

        {loadError !== '' && (
          <div className="mt-3 flex items-center gap-3 text-sm text-danger-600" data-testid="cutting-height-error">
            <AlertCircle className="h-4 w-4" />
            <span>{loadError}</span>
            <button type="button" className="underline" onClick={() => void load()}>
              重试
            </button>
          </div>
        )}

        {loadError === '' && !config && (
          <p className="mt-3 text-sm text-neutral-400" data-testid="cutting-height-loading">
            正在读取裁高配置…
          </p>
        )}

        {config && (
          <div className="mt-4 space-y-5" data-testid="cutting-height-items">
            {SCOPES.map(({ value: scope, label, hint, addLabel }) => {
              const rows = config.items
                .map((item, index) => ({ item, index }))
                .filter(({ item }) => (item.scope ?? SCOPE_SPECIFIC) === scope)
              return (
                <div key={scope} data-testid={`cutting-height-group-${scope}`}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-sm font-medium text-neutral-900">{label}</h3>
                    <button
                      type="button"
                      className="whitespace-nowrap rounded border border-neutral-300 px-2 py-1 text-sm"
                      data-testid={scope === SCOPE_SPECIFIC ? 'cutting-height-add' : 'cutting-height-add-fallback'}
                      /* 域写面出口标记（issue #6825）：类级守卫要求「可编辑控件 + 本域写出口」成对出现 */
                      data-write-exit="cutting-height"
                      onClick={() => addItem(scope)}
                    >
                      {addLabel}
                    </button>
                  </div>
                  <p className="mt-1 text-xs text-neutral-500">{hint}</p>
                  <div className="mt-2 space-y-2">
                    {rows.length === 0 ? (
                      <p className="rounded-lg border border-dashed border-neutral-200 px-3 py-4 text-sm text-neutral-400">
                        这一组还没有参数
                      </p>
                    ) : (
                      rows.map(({ item, index }) => (
                        <ItemRow
                          key={item.key}
                          index={index}
                          item={item}
                          optionsOf={optionsOf}
                          onChange={(patch) => patchItem(index, patch)}
                          onRemove={() => removeItem(index)}
                        />
                      ))
                    )}
                  </div>
                </div>
              )
            })}

            <div className="flex flex-wrap items-end gap-3 border-t border-neutral-100 pt-3">
              <Field label="取整" htmlFor="cutting-height-rounding-mode">
                <select
                  id="cutting-height-rounding-mode"
                  className={cn(SELECT_CONTROL_FIELD, 'w-full')}
                  aria-label="取整方式"
                  value={config.rounding.mode}
                  onChange={(e) =>
                    setConfig({ ...config, rounding: { ...config.rounding, mode: e.target.value } })
                  }
                >
                  <option value="half_up">四舍五入</option>
                  <option value="down">向下取整</option>
                  <option value="up">向上取整</option>
                </select>
              </Field>
              <Field label="保留位数" htmlFor="cutting-height-rounding-digits">
                <select
                  id="cutting-height-rounding-digits"
                  className={cn(SELECT_CONTROL_FIELD, 'w-full')}
                  aria-label="保留位数"
                  value={String(config.rounding.digits)}
                  onChange={(e) =>
                    setConfig({ ...config, rounding: { ...config.rounding, digits: Number(e.target.value) } })
                  }
                >
                  {[0, 1, 2, 3].map((d) => (
                    <option key={d} value={String(d)}>
                      {d} 位小数
                    </option>
                  ))}
                </select>
              </Field>
              <button
                type="button"
                className="rounded bg-primary-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
                data-testid="cutting-height-save"
                disabled={saving}
                onClick={() => void save()}
              >
                {saving ? '保存中…' : '保存'}
              </button>
            </div>
          </div>
        )}
      </section>

      {/* 🔴 issue #7176：本块与「阈值试算」是**同一套字段语言**（标签在上 + 控件满列 + 单位入框）。 */}
      <FormPanel
        title="预演（只读）"
        hint={
          <>
            填入一单的成品高与选配，看这次会给机器输什么值。<strong>不会写机器</strong>。
          </>
        }
      >
        <FormGrid cols={2}>
          <Field label="部位" htmlFor="cutting-height-probe-position">
            <select
              id="cutting-height-probe-position"
              className={cn(SELECT_CONTROL_FIELD, 'w-full')}
              aria-label="预演部位"
              value={probe.position}
              onChange={(e) => setProbe({ ...probe, position: e.target.value })}
            >
              {POSITIONS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </Field>
          <Field label="成品高" unit="米" htmlFor="cutting-height-probe-height">
            <input
              id="cutting-height-probe-height"
              className={fieldControl('米')}
              aria-label="预演成品高"
              value={probe.finishedHeight}
              onChange={(e) => setProbe({ ...probe, finishedHeight: e.target.value })}
            />
          </Field>
          <Field label="安装工艺" htmlFor="cutting-height-probe-craft">
            <select
              id="cutting-height-probe-craft"
              className={cn(SELECT_CONTROL_FIELD, 'w-full')}
              aria-label="预演工艺"
              value={probe.craft}
              onChange={(e) => setProbe({ ...probe, craft: e.target.value })}
            >
              <option value="">不指定</option>
              {CRAFT_OPTIONS.map((craft) => (
                <option key={craft} value={craft}>
                  {craft}
                </option>
              ))}
            </select>
          </Field>
          <Field label="特殊选项" htmlFor="cutting-height-probe-options">
            <OptionsProbe
              buttonId="cutting-height-probe-options"
              buttonLabel="预演特殊选项"
              optionLabelPrefix="特殊选项"
              options={specialOptionDisplayOptions()}
              value={probe.options}
              onChange={(options) => setProbe({ ...probe, options })}
            />
          </Field>
          <Field label="加工项" htmlFor="cutting-height-probe-items">
            <OptionsProbe
              buttonId="cutting-height-probe-items"
              buttonLabel="预演加工项"
              optionLabelPrefix="加工项"
              options={processingItems}
              value={probe.processingItems}
              onChange={(items) => setProbe({ ...probe, processingItems: items })}
            />
          </Field>
        </FormGrid>
        <div className="mt-3">
          <button
            type="button"
            className="rounded border border-neutral-300 px-3 py-1.5"
            data-testid="cutting-height-preview"
            onClick={() => void runPreview()}
          >
            预演
          </button>
        </div>

        {previewError !== '' && (
          <p className="mt-3 text-sm text-danger-600" data-testid="cutting-height-preview-error">
            {previewError}
          </p>
        )}

        {preview && (
          <div className="mt-4 space-y-2" data-testid="cutting-height-preview-result">
            <p className="text-2xl font-semibold text-primary-700">
              裁剪高度 {String(preview.cutting_height)} 米
            </p>
            <p className="text-sm text-neutral-500">
              成品高 {String(preview.base)} 米 +{' '}
              {preview.hits.length === 0
                ? '无命中增量项'
                : preview.hits.map((h) => `${h.name} ${String(h.value)}`).join(' + ')}
            </p>
            {preview.misses.length > 0 && (
              <ul className="text-sm text-amber-700">
                {preview.misses.map((m) => (
                  <li key={m.key}>
                    ⚠️ {m.name} 命中但<strong>未配置取值</strong>
                    {m.reason === 'unresolved' ? '' : `（${m.reason}）`}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </FormPanel>
    </div>
  )
}

/** 预演用的多选下拉（闭词表；§31 P1：默认折叠成一行）。 */
function OptionsProbe({
  buttonId,
  buttonLabel,
  optionLabelPrefix,
  options,
  value,
  onChange,
}: {
  buttonId: string
  buttonLabel: string
  optionLabelPrefix: string
  options: readonly string[]
  value: string[]
  onChange: (next: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    function onMouseDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [open])

  const toggle = (name: string) => {
    onChange(value.includes(name) ? value.filter((v) => v !== name) : [...value, name])
  }

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        id={buttonId}
        aria-label={buttonLabel}
        aria-expanded={open}
        title={value.length > 0 ? value.join('、') : undefined}
        onClick={() => setOpen((v) => !v)}
        className={cn(fieldControl(), 'flex items-center justify-between text-left')}
      >
        <span className={value.length === 0 ? 'text-neutral-400' : undefined}>
          {value.length === 0 ? '未选择' : `已选 ${value.length} 项`}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-neutral-400" />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-40 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-neutral-200 bg-white p-1 shadow-card-hover">
          {options.length === 0 ? (
            <p className="px-2 py-1.5 text-xs text-neutral-400">暂无可用取值</p>
          ) : (
            options.map((name) => (
              <label
                key={name}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
              >
                <input
                  type="checkbox"
                  checked={value.includes(name)}
                  onChange={() => toggle(name)}
                  aria-label={`${optionLabelPrefix}-${name}`}
                />
                {name}
              </label>
            ))
          )}
        </div>
      )}
    </div>
  )
}
