'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Plus, Trash2, Image as ImageIcon } from 'lucide-react'
import { Button, Input } from '@/components/ui'
import ImageUploader from './ImageUploader'
import type { ProductColor, ProductSku, SellingMethod } from '@/types'
import { SellingMethodLabels } from '@/types'

interface SkuMatrixProps {
  value: {
    colors: ProductColor[]
    sellingMethods: SellingMethod[]
    doorWidths: string[]
    skus: ProductSku[]
  }
  onChange: (v: {
    colors: ProductColor[]
    sellingMethods: SellingMethod[]
    doorWidths: string[]
    skus: ProductSku[]
  }) => void
  errors?: {
    colors?: string
    sellingMethods?: string
    doorWidths?: string
    skus?: string
  }
}

const SELLING_METHOD_OPTIONS: { value: SellingMethod; label: string }[] = [
  { value: 'bulk_cut', label: '散剪' },
  { value: 'full_roll', label: '整卷' },
]

const COMMON_DOOR_WIDTHS = ['2.8m', '3.0m', '3.2m', '3.4m', '3.6m', '4.0m']

export default function SkuMatrix({ value, onChange, errors }: SkuMatrixProps) {
  const { colors, sellingMethods, doorWidths, skus } = value

  // ========== 颜色管理 ==========
  const handleAddColor = () => {
    const newColor: ProductColor = {
      id: -(Date.now() + Math.random()),
      colorName: '',
      colorImageUrl: '',
      sortOrder: colors.length,
    }
    const nextColors = [...colors, newColor]
    onChange({ ...value, colors: nextColors, skus: rebuildSkus(nextColors, sellingMethods, doorWidths, skus) })
  }

  const handleUpdateColor = (idx: number, patch: Partial<ProductColor>) => {
    const nextColors = [...colors]
    nextColors[idx] = { ...nextColors[idx], ...patch }
    onChange({ ...value, colors: nextColors })
  }

  const handleRemoveColor = (idx: number) => {
    const removed = colors[idx]
    const nextColors = colors.filter((_, i) => i !== idx)
    const nextSkus = skus.filter((s) => s.colorId !== removed.id)
    onChange({ ...value, colors: nextColors, skus: nextSkus })
  }

  // ========== 售卖方式管理 ==========
  const handleToggleSellingMethod = (method: SellingMethod) => {
    let next: SellingMethod[]
    if (sellingMethods.includes(method)) {
      next = sellingMethods.filter((m) => m !== method)
    } else {
      next = [...sellingMethods, method]
    }
    onChange({ ...value, sellingMethods: next, skus: rebuildSkus(colors, next, doorWidths, skus) })
  }

  // ========== 门幅管理 ==========
  const [customWidth, setCustomWidth] = useState('')

  const handleToggleDoorWidth = (width: string) => {
    let next: string[]
    if (doorWidths.includes(width)) {
      next = doorWidths.filter((w) => w !== width)
    } else {
      next = [...doorWidths, width]
    }
    onChange({ ...value, doorWidths: next, skus: rebuildSkus(colors, sellingMethods, next, skus) })
  }

  const handleAddCustomWidth = () => {
    const w = customWidth.trim()
    if (!w || doorWidths.includes(w)) return
    const next = [...doorWidths, w]
    setCustomWidth('')
    onChange({ ...value, doorWidths: next, skus: rebuildSkus(colors, sellingMethods, next, skus) })
  }

  // ========== SKU 矩阵重建 ==========
  const rebuildSkus = (
    cs: ProductColor[],
    sms: SellingMethod[],
    dws: string[],
    existing: ProductSku[]
  ): ProductSku[] => {
    const result: ProductSku[] = []
    for (const color of cs) {
      for (const method of sms) {
        for (const width of dws) {
          const found = existing.find(
            (s) => s.colorId === color.id && s.sellingMethod === method && s.doorWidth === width
          )
          if (found) {
            result.push(found)
          } else {
            result.push({
              id: -(Date.now() + Math.random()),
              colorId: color.id,
              colorName: color.colorName,
              sellingMethod: method,
              doorWidth: width,
              price: 0,
              stock: 0,
              status: 'active',
            })
          }
        }
      }
    }
    return result
  }

  // ========== SKU 价格/库存编辑 ==========
  const handleSkuChange = (colorId: number, method: SellingMethod, width: string, field: 'price' | 'stock', val: number) => {
    const nextSkus = skus.map((s) => {
      if (s.colorId === colorId && s.sellingMethod === method && s.doorWidth === width) {
        return { ...s, [field]: val }
      }
      return s
    })
    onChange({ ...value, skus: nextSkus })
  }

  // ========== 渲染 ==========
  return (
    <div className="space-y-6">
      {/* 颜色列表 */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-sm font-medium text-gray-700">
            颜色管理<span className="text-red-500 ml-1">*</span>
          </h4>
          <Button type="button" size="sm" variant="secondary" onClick={handleAddColor}>
            <Plus className="w-4 h-4 mr-1" /> 添加颜色
          </Button>
        </div>
        {colors.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-4 border border-dashed border-gray-200 rounded-lg">
            请添加至少 1 种颜色
          </p>
        ) : (
          <div className="space-y-3">
            {colors.map((color, idx) => (
              <div
                key={color.id}
                className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg border border-gray-200"
              >
                <div className="w-16 h-16 shrink-0">
                  <ImageUploader
                    value={color.colorImageUrl ? [color.colorImageUrl] : []}
                    onChange={(urls) => handleUpdateColor(idx, { colorImageUrl: urls[0] || '' })}
                    max={1}
                  />
                </div>
                <div className="flex-1 min-w-0">
                  <Input
                    placeholder="颜色名称（如：米白）"
                    value={color.colorName}
                    onChange={(e) => handleUpdateColor(idx, { colorName: e.target.value })}
                  />
                </div>
                <div className="w-32">
                  <Input
                    placeholder="色值 #FFFFFF"
                    value={color.mainColorHex || ''}
                    onChange={(e) => handleUpdateColor(idx, { mainColorHex: e.target.value })}
                  />
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => handleRemoveColor(idx)}
                  className="text-red-500 hover:text-red-600 shrink-0"
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
            ))}
          </div>
        )}
        {errors?.colors && <p className="text-sm text-red-600 mt-1">{errors.colors}</p>}
      </div>

      {/* 售卖方式 */}
      <div>
        <h4 className="text-sm font-medium text-gray-700 mb-3">
          售卖方式<span className="text-red-500 ml-1">*</span>
        </h4>
        <div className="flex flex-wrap gap-3">
          {SELLING_METHOD_OPTIONS.map((opt) => {
            const active = sellingMethods.includes(opt.value)
            return (
              <label
                key={opt.value}
                className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg border cursor-pointer transition-colors ${
                  active
                    ? 'border-primary-500 bg-primary-50 text-primary-700'
                    : 'border-gray-300 text-gray-600 hover:border-gray-400'
                }`}
              >
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={active}
                  onChange={() => handleToggleSellingMethod(opt.value)}
                />
                <span className={`w-4 h-4 rounded border flex items-center justify-center ${
                  active ? 'bg-primary-500 border-primary-500' : 'border-gray-400'
                }`}>
                  {active && (
                    <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  )}
                </span>
                {opt.label}
              </label>
            )
          })}
        </div>
        {errors?.sellingMethods && <p className="text-sm text-red-600 mt-1">{errors.sellingMethods}</p>}
      </div>

      {/* 规格尺寸（门幅） */}
      <div>
        <h4 className="text-sm font-medium text-gray-700 mb-3">
          规格尺寸（门幅）<span className="text-red-500 ml-1">*</span>
        </h4>
        <div className="flex flex-wrap gap-2 mb-3">
          {COMMON_DOOR_WIDTHS.map((w) => {
            const active = doorWidths.includes(w)
            return (
              <button
                key={w}
                type="button"
                onClick={() => handleToggleDoorWidth(w)}
                className={`px-3 py-1.5 rounded border text-sm transition-colors ${
                  active
                    ? 'border-primary-500 bg-primary-50 text-primary-700'
                    : 'border-gray-300 text-gray-600 hover:border-gray-400'
                }`}
              >
                {w}
              </button>
            )
          })}
          {/* Show custom widths not in COMMON list */}
          {doorWidths
            .filter((w) => !COMMON_DOOR_WIDTHS.includes(w))
            .map((w) => (
              <button
                key={w}
                type="button"
                onClick={() => handleToggleDoorWidth(w)}
                className="px-3 py-1.5 rounded border text-sm border-primary-500 bg-primary-50 text-primary-700"
              >
                {w}
              </button>
            ))}
        </div>
        <div className="flex items-center gap-2">
          <Input
            placeholder="自定义门幅，如 3.5m"
            value={customWidth}
            onChange={(e) => setCustomWidth(e.target.value)}
            className="w-40"
          />
          <Button type="button" size="sm" variant="secondary" onClick={handleAddCustomWidth}>
            添加
          </Button>
        </div>
        {errors?.doorWidths && <p className="text-sm text-red-600 mt-1">{errors.doorWidths}</p>}
      </div>

      {/* SKU 矩阵表格 */}
      {colors.length > 0 && sellingMethods.length > 0 && doorWidths.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-gray-700 mb-3">SKU 价格与库存</h4>
          <div className="overflow-x-auto border border-gray-200 rounded-lg">
            <table className="w-full text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left text-gray-600 font-medium">颜色</th>
                  <th className="px-3 py-2 text-left text-gray-600 font-medium">售卖方式</th>
                  <th className="px-3 py-2 text-left text-gray-600 font-medium">门幅</th>
                  <th className="px-3 py-2 text-left text-gray-600 font-medium">价格 (¥)</th>
                  <th className="px-3 py-2 text-left text-gray-600 font-medium">库存</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {colors.map((color) =>
                  sellingMethods.map((method) =>
                    doorWidths.map((width, wIdx) => {
                      const sku = skus.find(
                        (s) => s.colorId === color.id && s.sellingMethod === method && s.doorWidth === width
                      )
                      return (
                        <tr key={`${color.id}-${method}-${width}`} className="hover:bg-gray-50/50">
                          <td className="px-3 py-2 text-gray-700">{color.colorName || '未命名'}</td>
                          <td className="px-3 py-2 text-gray-700">{SellingMethodLabels[method]}</td>
                          <td className="px-3 py-2 text-gray-700">{width}</td>
                          <td className="px-3 py-2">
                            <input
                              type="number"
                              min="0"
                              step="0.01"
                              className="w-24 px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-1 focus:ring-primary-500"
                              value={sku?.price || ''}
                              onChange={(e) =>
                                handleSkuChange(color.id, method, width, 'price', parseFloat(e.target.value) || 0)
                              }
                            />
                          </td>
                          <td className="px-3 py-2">
                            <input
                              type="number"
                              min="0"
                              step="1"
                              className="w-20 px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-1 focus:ring-primary-500"
                              value={sku?.stock || ''}
                              onChange={(e) =>
                                handleSkuChange(color.id, method, width, 'stock', parseInt(e.target.value) || 0)
                              }
                            />
                          </td>
                        </tr>
                      )
                    })
                  )
                )}
              </tbody>
            </table>
          </div>
          {errors?.skus && <p className="text-sm text-red-600 mt-2">{errors.skus}</p>}
        </div>
      )}
    </div>
  )
}
