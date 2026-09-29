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

import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { AlertCircle } from 'lucide-react'

import { cuttingHeightApi } from '@/lib/api'
import { cn } from '@/lib/utils'
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

export function CuttingHeightConfigPanel() {
  const [config, setConfig] = useState<CuttingHeightConfigBody | null>(null)
  const [source, setSource] = useState('')
  const [loadError, setLoadError] = useState('')
  const [saving, setSaving] = useState(false)
  const [preview, setPreview] = useState<CuttingHeightPreview | null>(null)
  const [previewError, setPreviewError] = useState('')
  const [probe, setProbe] = useState({ position: '布帘', finishedHeight: '', craft: '', options: '' })

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
        special_options: probe.options
          ? probe.options.split(/[,，\s]+/).filter(Boolean)
          : [],
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
              <table className="w-full text-sm" data-testid="cutting-height-items">
                <thead>
                  <tr className="text-left text-neutral-500">
                    <th className="py-1 pr-2">名称</th>
                    <th className="py-1 pr-2">取值（米）</th>
                    <th className="py-1 pr-2">触发</th>
                    <th className="py-1 pr-2">触发值</th>
                    <th className="py-1 pr-2">部位</th>
                    <th className="py-1 pr-2">启用</th>
                    <th className="py-1" />
                  </tr>
                </thead>
                <tbody>
                  {config.items.map((item, index) => (
                    <tr key={item.key} className="border-t border-neutral-100">
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
                          value={item.value === null ? '' : String(item.value)}
                          placeholder="留空 = 有项无值"
                          onChange={(e) =>
                            patchItem(index, { value: e.target.value.trim() === '' ? null : Number(e.target.value) })
                          }
                        />
                      </td>
                      <td className="py-1 pr-2">
                        <select
                          className={inputCls}
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
                          className={inputCls}
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
                      <td className="py-1 pr-2">
                        <input
                          type="checkbox"
                          aria-label={`启用-${index}`}
                          checked={item.enabled}
                          onChange={(e) => patchItem(index, { enabled: e.target.checked })}
                        />
                      </td>
                      <td className="py-1">
                        <button
                          type="button"
                          className="text-neutral-400 underline"
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
                  className={cn(inputCls, 'ml-1 inline-block w-auto')}
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
                  className={cn(inputCls, 'ml-1 inline-block w-auto')}
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

      <section className="rounded-lg border border-neutral-200 bg-white p-5">
        <h3 className="text-base font-medium text-neutral-900">预演（只读）</h3>
        <p className="text-sm text-neutral-500">
          填入一单的成品高与选配，看这次会给机器输什么值。<strong>不会写机器</strong>。
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-3 text-sm">
          <label>
            部位
            <select
              className={cn(inputCls, 'ml-1 inline-block w-auto')}
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
          </label>
          <label>
            成品高（米）
            <input
              className={cn(inputCls, 'ml-1 inline-block w-24')}
              aria-label="预演成品高"
              value={probe.finishedHeight}
              onChange={(e) => setProbe({ ...probe, finishedHeight: e.target.value })}
            />
          </label>
          <label>
            安装工艺
            <input
              className={cn(inputCls, 'ml-1 inline-block w-24')}
              aria-label="预演工艺"
              value={probe.craft}
              onChange={(e) => setProbe({ ...probe, craft: e.target.value })}
            />
          </label>
          <label>
            特殊选项（逗号分隔）
            <input
              className={cn(inputCls, 'ml-1 inline-block w-40')}
              aria-label="预演特殊选项"
              value={probe.options}
              onChange={(e) => setProbe({ ...probe, options: e.target.value })}
            />
          </label>
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
      </section>
    </div>
  )
}
