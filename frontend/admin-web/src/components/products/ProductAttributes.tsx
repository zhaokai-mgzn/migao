'use client'

import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Button, Input, Select } from '@/components/ui'

interface ProductAttributesProps {
  value: {
    skuCode: string
    brand: string
    unit: string
    specifications: Record<string, string>
  }
  onChange: (patch: {
    skuCode?: string
    brand?: string
    unit?: string
    specifications?: Record<string, string>
  }) => void
  errors?: {
    skuCode?: string
    unit?: string
  }
}

const UNIT_OPTIONS = [
  { value: '', label: '请选择' },
  { value: '米', label: '米' },
  { value: '卷', label: '卷' },
  { value: '件', label: '件' },
  { value: '套', label: '套' },
  { value: '平方米', label: '平方米' },
]

const SPEC_KEY_OPTIONS = [
  { value: 'material', label: '材质' },
  { value: 'weight', label: '克重' },
  { value: 'function', label: '功能' },
  { value: 'style', label: '风格' },
  { value: 'craft', label: '工艺' },
  { value: 'pattern', label: '花型' },
  { value: 'origin', label: '产地' },
  { value: 'washable', label: '可否水洗' },
]

export default function ProductAttributes({
  value,
  onChange,
  errors,
}: ProductAttributesProps) {
  const { skuCode, brand, unit, specifications } = value

  const specEntries = Object.entries(specifications)

  const handleAddSpec = () => {
    // Find the first unused key
    const usedKeys = new Set(Object.keys(specifications))
    const available = SPEC_KEY_OPTIONS.find((opt) => !usedKeys.has(opt.value))
    if (!available) return
    const next = { ...specifications, [available.value]: '' }
    onChange({ specifications: next })
  }

  const handleRemoveSpec = (key: string) => {
    const next = { ...specifications }
    delete next[key]
    onChange({ specifications: next })
  }

  const handleSpecKeyChange = (oldKey: string, newKey: string) => {
    if (newKey === oldKey) return
    const next: Record<string, string> = {}
    for (const [k, v] of Object.entries(specifications)) {
      if (k === oldKey) {
        next[newKey] = v
      } else {
        next[k] = v
      }
    }
    onChange({ specifications: next })
  }

  const handleSpecValueChange = (key: string, val: string) => {
    onChange({ specifications: { ...specifications, [key]: val } })
  }

  return (
    <div className="space-y-5">
      {/* 货号 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <Input
            label="货号"
            required
            placeholder="请输入货号（最多 30 字）"
            maxLength={30}
            value={skuCode}
            onChange={(e) => onChange({ skuCode: e.target.value })}
            error={errors?.skuCode}
          />
        </div>
        <div>
          <Input
            label="品牌"
            placeholder="请输入品牌名称"
            value={brand}
            onChange={(e) => onChange({ brand: e.target.value })}
          />
        </div>
      </div>

      {/* 计价单位 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div id="pf-unit">
          <Select
            label="计价单位"
            required
            options={UNIT_OPTIONS}
            value={unit}
            onChange={(e) => onChange({ unit: e.target.value })}
            error={errors?.unit}
          />
        </div>
      </div>

      {/* 扩展属性 */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <label className="text-sm font-medium text-gray-700">扩展属性</label>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={handleAddSpec}
            disabled={specEntries.length >= SPEC_KEY_OPTIONS.length}
          >
            <Plus className="w-4 h-4 mr-1" /> 添加属性
          </Button>
        </div>

        {specEntries.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-3 border border-dashed border-gray-200 rounded-lg">
            暂未添加扩展属性，点击右上方按钮添加
          </p>
        ) : (
          <div className="space-y-2">
            {specEntries.map(([key, val]) => (
              <div key={key} className="flex items-end gap-3 p-3 bg-gray-50 rounded border border-gray-200">
                <div className="w-40">
                  <Select
                    label="属性名"
                    options={SPEC_KEY_OPTIONS.map((opt) => ({
                      ...opt,
                      disabled: opt.value !== key && Object.keys(specifications).includes(opt.value),
                    }))}
                    value={key}
                    onChange={(e) => handleSpecKeyChange(key, e.target.value)}
                  />
                </div>
                <div className="flex-1">
                  <Input
                    label="属性值"
                    placeholder="请输入属性值"
                    value={val}
                    onChange={(e) => handleSpecValueChange(key, e.target.value)}
                  />
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => handleRemoveSpec(key)}
                  className="text-red-500 hover:text-red-600"
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
