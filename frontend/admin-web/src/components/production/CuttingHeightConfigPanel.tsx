/**
 * 裁高（定高）配置面板（母单 #5161；设计单 `docs/design/cutting-height-config-and-terminal.md`）。
 *
 * ## 它回答什么
 * 「这台机器这一刀该多高」：`裁剪高度(部位) = 成品高 + Σ(命中的增量项)`，本租户可配。
 *
 * ## 三条实现纪律
 * 1. **页面不持有默认值**：缺行时后端回的是**默认种子** + `source='default'` ⇒ 界面显式标
 *    「当前使用系统默认值」（把默认值伪装成商家配置 = 让商家以为改过、其实没改）。
 * 2. **命中口径由服务端判**：本面板只填 `trigger_kind / trigger_value / position`；
 *    「哪些项命中」一律由 `POST …/preview` 回答 —— 前端再写一份匹配 = 第二份口径。
 * 3. **本版只算不写机器**：面板的终点是「给人一个可核对的数」（用户 2026-09-29 裁定①：下发先不做）。
 */
'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { AlertCircle, ChevronDown } from 'lucide-react'

import { formatDraft } from '@/components/ui/NumberInput'
// issue #7176：配置面表单的**唯一版式原语**（与「阈值试算」同一套：浅底面板 + 栅格 + 标签在上 + 单位入框）
import FormPanel, { FIELD_CONTROL, Field, FormGrid, fieldControl } from '@/components/ui/FormPanel'
import { cuttingHeightApi } from '@/lib/api'
import { CRAFT_OPTIONS, SPECIAL_OPTIONS } from '@/lib/order-craft-fields'
import { cn } from '@/lib/utils'
import { SELECT_CONTROL, SELECT_CONTROL_FIELD } from '@/components/ui'
import type {
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

const POSITIONS = ['布帘', '纱帘', '帘头']

const inputCls =
  'w-full rounded border border-neutral-300 px-2 py-1 text-sm focus:border-primary-500 focus:outline-none'

/** 新项的初值（key 用时间戳保证与本租户已有 key 不撞；商家可改）。 */
function newItem(order: number): CuttingHeightItem {
  const key = `item-${Date.now().toString(36)}`
  return {
    key,
    name: '',
    value: null,
    direction: 'add',
    height_join: false,
    hit: { trigger_kind: 'option', trigger_value: '', position: null },
    hit_expr: null,
    enabled: true,
    order,
  }
}

/**
 * 特殊选项多选下拉（issue #7213）—— 19 项**闭词表**（与下单页 `OrderExtraOptions` 同一份
 * `SPECIAL_OPTIONS`；选项名是 join key，手输错一个字就不命中 ⇒ 这里不给自由文本）。
 * §31 P1：常驻面只一行（未选择 / 已选 N 项），点开才渲染复选项。
 */
function OptionsMultiSelect({ value, onChange }: { value: string[]; onChange: (next: string[]) => void }) {
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
        id="cutting-height-probe-options"
        aria-label="预演特殊选项"
        aria-expanded={open}
        title={value.length > 0 ? value.join('、') : undefined}
        onClick={() => setOpen((v) => !v)}
        className={cn(FIELD_CONTROL, 'flex items-center justify-between text-left')}
      >
        <span className={value.length === 0 ? 'text-neutral-400' : undefined}>
          {value.length === 0 ? '未选择' : `已选 ${value.length} 项`}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-neutral-400" />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-40 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-neutral-200 bg-white p-1 shadow-card-hover">
          {SPECIAL_OPTIONS.map((name) => (
            <label
              key={name}
              className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
            >
              <input
                type="checkbox"
                checked={value.includes(name)}
                onChange={() => toggle(name)}
                aria-label={`特殊选项-${name}`}
              />
              {name}
            </label>
          ))}
        </div>
      )}
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
  const [probe, setProbe] = useState({ position: '布帘', finishedHeight: '', craft: '', options: [] as string[] })

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

  const patchItem = (index: number, patch: Partial<CuttingHeightItem>) => {
    setConfig((prev) => {
      if (!prev) return prev
      const items = prev.items.map((item, i) => (i === index ? { ...item, ...patch } : item))
      return { ...prev, items }
    })
  }

  const patchHit = (index: number, patch: Partial<CuttingHeightItem['hit']>) => {
    setConfig((prev) => {
      if (!prev) return prev
      const items = prev.items.map((item, i) =>
        i === index ? { ...item, hit: { ...item.hit, ...patch } } : item,
      )
      return { ...prev, items }
    })
  }

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
        special_options: probe.options,
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
          裁剪高度 = 成品高 + 命中的增量项。命中按下面的「触发」判：触发值要<strong>逐字</strong>
          等于订单上勾的特殊选项 / 安装工艺 / 加工项名（写错一个字就不命中）。
          <strong>取值留空 = 有项无值</strong>：它会命中、但会被显式报出「未配置取值」，
          <strong>不按 0 算</strong>。
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
          <div className="mt-4 space-y-4">
            <div className="overflow-x-auto">
              {/* 列宽**显式**给（issue #7153）：此前 `w-full` + auto 布局 + 每格 `w-full` 控件 ⇒
                  宽输入框吃掉余量后把 select 列压到**低于内容宽度**（真机实测「特殊选:」「布厂」被裁、
                  「启用」「删除」竖排）。现在 `table-fixed` + `colgroup` 定比例、`min-w` 兜底：
                  窄屏走横向滚动，**不压缩控件到裁字**。 */}
              <table
                className="w-full min-w-[700px] table-fixed text-sm"
                data-testid="cutting-height-items"
              >
                <colgroup>
                  <col className="w-[20%]" />
                  <col className="w-[14%]" />
                  <col className="w-[16%]" />
                  <col className="w-[18%]" />
                  <col className="w-[11%]" />
                  <col className="w-[9%]" />
                  <col className="w-[12%]" />
                </colgroup>
                <thead>
                  <tr className="text-left text-neutral-500">
                    <th className="whitespace-nowrap py-1 pr-2">名称</th>
                    <th className="whitespace-nowrap py-1 pr-2">取值（米）</th>
                    <th className="whitespace-nowrap py-1 pr-2">触发</th>
                    <th className="whitespace-nowrap py-1 pr-2">触发值</th>
                    <th className="whitespace-nowrap py-1 pr-2">部位</th>
                    <th className="whitespace-nowrap py-1 pr-2 text-center">启用</th>
                    <th className="whitespace-nowrap py-1" />
                  </tr>
                </thead>
                <tbody>
                  {config.items.map((item, index) => (
                    <tr key={item.key} className="border-t border-neutral-100 align-middle">
                      <td className="py-1 pr-2">
                        <input
                          className={inputCls}
                          aria-label={`名称-${index}`}
                          value={item.name}
                          onChange={(e) => patchItem(index, { name: e.target.value })}
                        />
                      </td>
                      <td className="py-1 pr-2">
                        <input
                          className={inputCls}
                          aria-label={`取值-${index}`}
                          value={formatDraft(item.value)}
                          placeholder="可留空"
                          title="取值留空 = 有项无值：会命中，但会显式报出「未配置取值」，不按 0 算"
                          onChange={(e) =>
                            patchItem(index, { value: e.target.value.trim() === '' ? null : Number(e.target.value) })
                          }
                        />
                      </td>
                      <td className="py-1 pr-2">
                        <select
                          className={cn(SELECT_CONTROL, 'w-full')}
                          aria-label={`触发类型-${index}`}
                          value={item.hit.trigger_kind}
                          onChange={(e) => patchHit(index, { trigger_kind: e.target.value })}
                        >
                          {TRIGGER_KINDS.map((k) => (
                            <option key={k.value} value={k.value}>
                              {k.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="py-1 pr-2">
                        <input
                          className={inputCls}
                          aria-label={`触发值-${index}`}
                          value={item.hit.trigger_value}
                          onChange={(e) => patchHit(index, { trigger_value: e.target.value })}
                        />
                      </td>
                      <td className="py-1 pr-2">
                        <select
                          className={cn(SELECT_CONTROL, 'w-full')}
                          aria-label={`部位-${index}`}
                          value={item.hit.position ?? ''}
                          onChange={(e) => patchHit(index, { position: e.target.value || null })}
                        >
                          <option value="">不限</option>
                          {POSITIONS.map((p) => (
                            <option key={p} value={p}>
                              {p}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="py-1 pr-2 text-center">
                        <input
                          type="checkbox"
                          aria-label={`启用-${index}`}
                          checked={item.enabled}
                          onChange={(e) => patchItem(index, { enabled: e.target.checked })}
                        />
                      </td>
                      <td className="whitespace-nowrap py-1">
                        <button
                          type="button"
                          className="whitespace-nowrap text-neutral-400 underline"
                          data-testid={`cutting-height-remove-${index}`}
                          onClick={() =>
                            setConfig((prev) =>
                              prev ? { ...prev, items: prev.items.filter((_, i) => i !== index) } : prev,
                            )
                          }
                        >
                          删除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex flex-wrap items-end gap-3">
              <button
                type="button"
                className="rounded border border-neutral-300 px-2 py-1 text-sm"
                data-testid="cutting-height-add"
                /* 域写面出口标记（issue #6825）：类级守卫要求「可编辑控件 + 本域写出口」成对出现 */
                data-write-exit="cutting-height"
                onClick={() =>
                  setConfig((prev) =>
                    prev ? { ...prev, items: [...prev.items, newItem((prev.items.length + 1) * 10)] } : prev,
                  )
                }
              >
                添加增量项
              </button>
              <label className="text-sm text-neutral-600">
                取整
                <select
                  className={cn(SELECT_CONTROL, 'ml-1 inline-block w-auto')}
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
              </label>
              <label className="text-sm text-neutral-600">
                保留
                <select
                  className={cn(SELECT_CONTROL, 'ml-1 inline-block w-auto')}
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
              </label>
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

      {/* 🔴 issue #7176：本块与「阈值试算」是**同一套字段语言**（此前是「标签顺排在控件左边 + 定宽框」，
          与同页/同产品的其它配置面长得不一样 —— 用户逐字「一个产品不要出现多种设计和风格样式」）。 */}
      <FormPanel
        title="预演（只读）"
        hint={
          <>
            填入一单的成品高与选配，看这次会给机器输什么值。<strong>不会写机器</strong>。
          </>
        }
      >
        {/* 列数按**标签长度**选（本组标签较长 ⇒ 两列，与「阈值试算」的四列同一个 `FormGrid`） */}
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
            <OptionsMultiSelect
              value={probe.options}
              onChange={(options) => setProbe({ ...probe, options })}
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
