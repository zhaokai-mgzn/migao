/* eslint-disable react/no-unescaped-entities */
'use client'

import { useMemo, useRef, useState, useEffect } from 'react'
import { Plus, Trash2, GripVertical, ImagePlus, Check } from 'lucide-react'
import { toast } from 'sonner'
import Image from 'next/image'
import { Button, Select } from '@/components/ui'
import { fileApi } from '@/lib/api'
import { resolveImageUrl } from '@/lib/utils'
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

const DOOR_WIDTH_OPTIONS = ['门幅2.8米', '门幅3.2米', '门幅3.4米']

const COLOR_NAME_MAX = 30
const MAX_COLORS = 200
const MAX_SKUS = 600

// 预设颜色（常用窗帘/布艺颜色）
const PRESET_COLORS: { name: string; hex: string }[] = [
  { name: '白色', hex: '#FFFFFF' },
  { name: '米白', hex: '#FFFDD0' },
  { name: '灰色', hex: '#808080' },
  { name: '黑色', hex: '#000000' },
  { name: '红色', hex: '#FF0000' },
  { name: '酒红', hex: '#722F37' },
  { name: '粉色', hex: '#FFC0CB' },
  { name: '橙色', hex: '#FFA500' },
  { name: '黄色', hex: '#FFFF00' },
  { name: '金色', hex: '#FFD700' },
  { name: '绿色', hex: '#008000' },
  { name: '青色', hex: '#00FFFF' },
  { name: '蓝色', hex: '#0000FF' },
  { name: '藏蓝', hex: '#003153' },
  { name: '紫色', hex: '#800080' },
  { name: '棕色', hex: '#8B4513' },
  { name: '咖啡', hex: '#6F4E37' },
  { name: '卡其', hex: '#C3B091' },
  { name: '驼色', hex: '#C19A6B' },
  { name: '银色', hex: '#C0C0C0' },
]

type BatchScope = 'all' | 'color' | 'method' | 'width'

// ========== 矩阵重建（保持原有逻辑） ==========
function rebuildSkus(
  cs: ProductColor[],
  sms: SellingMethod[],
  dws: string[],
  existing: ProductSku[]
): ProductSku[] {
  // 过滤接口中未选中的空占位值，避免生成无效 SKU
  const validSms = sms.filter((m) => !!m)
  const validDws = dws.filter((w) => !!w)
  const result: ProductSku[] = []
  for (const color of cs) {
    for (const method of validSms) {
      for (const width of validDws) {
        const found = existing.find(
          (s) =>
            s.colorId === color.id &&
            s.sellingMethod === method &&
            s.doorWidth === width
        )
        if (found) {
          result.push({ ...found, colorName: color.colorName })
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

export default function SkuMatrix({ value, onChange, errors }: SkuMatrixProps) {
  const { colors, sellingMethods, doorWidths, skus } = value

  // ========== 颜色管理 ==========
  const handleAddColor = () => {
    if (colors.length >= MAX_COLORS) {
      toast.warning(`最多只能添加 ${MAX_COLORS} 种颜色分类`)
      return
    }
    const newColor: ProductColor = {
      id: -(Date.now() + Math.random()),
      colorName: '',
      colorImageUrl: '',
      remark: '',
      sortOrder: colors.length,
    }
    const nextColors = [...colors, newColor]
    onChange({
      ...value,
      colors: nextColors,
      skus: rebuildSkus(nextColors, sellingMethods, doorWidths, skus),
    })
  }

  const handleAddColorWithPreset = (name: string, hex: string) => {
    if (colors.length >= MAX_COLORS) {
      toast.warning(`最多只能添加 ${MAX_COLORS} 种颜色分类`)
      return
    }
    const newColor: ProductColor = {
      id: -(Date.now() + Math.random()),
      colorName: name,
      mainColorHex: hex || undefined,
      colorImageUrl: '',
      remark: '',
      sortOrder: colors.length,
    }
    const nextColors = [...colors, newColor]
    onChange({
      ...value,
      colors: nextColors,
      skus: rebuildSkus(nextColors, sellingMethods, doorWidths, skus),
    })
  }

  const handleUpdateColor = (idx: number, patch: Partial<ProductColor>) => {
    const nextColors = [...colors]
    nextColors[idx] = { ...nextColors[idx], ...patch }
    // 同步 sku.colorName
    const nextSkus =
      patch.colorName !== undefined
        ? skus.map((s) =>
            s.colorId === nextColors[idx].id
              ? { ...s, colorName: patch.colorName! }
              : s
          )
        : skus
    onChange({ ...value, colors: nextColors, skus: nextSkus })
  }

  const handleRemoveColor = (idx: number) => {
    const removed = colors[idx]
    const nextColors = colors.filter((_, i) => i !== idx)
    const nextSkus = skus.filter((s) => s.colorId !== removed.id)
    onChange({ ...value, colors: nextColors, skus: nextSkus })
  }

  // 拖拽排序：颜色
  const [colorDragIdx, setColorDragIdx] = useState<number | null>(null)
  const [colorSortMode, setColorSortMode] = useState(false)
  const handleColorDrop = (target: number) => {
    if (colorDragIdx === null || colorDragIdx === target) return
    const list = [...colors]
    const [m] = list.splice(colorDragIdx, 1)
    list.splice(target, 0, m)
    const reordered = list.map((c, i) => ({ ...c, sortOrder: i }))
    onChange({
      ...value,
      colors: reordered,
      skus: rebuildSkus(reordered, sellingMethods, doorWidths, skus),
    })
    setColorDragIdx(null)
  }

  // ========== 售卖方式（多行下拉，去重） ==========
  const handleAddSellingMethod = () => {
    // 占位空值（用 '' 表示尚未选择）
    if (sellingMethods.length >= SELLING_METHOD_OPTIONS.length) {
      toast.warning('已添加全部可用的售卖方式')
      return
    }
    onChange({
      ...value,
      sellingMethods: [...sellingMethods, '' as unknown as SellingMethod],
    })
  }

  const handleChangeSellingMethod = (idx: number, v: string) => {
    if (!v) {
      // 选择为空，移除占位行
      const next = sellingMethods.filter((_, i) => i !== idx)
      onChange({
        ...value,
        sellingMethods: next,
        skus: rebuildSkus(colors, next, doorWidths, skus),
      })
      return
    }
    if (sellingMethods.some((m, i) => i !== idx && m === v)) {
      toast.warning('当前售卖方式已经添加过了哦')
      return
    }
    const next = [...sellingMethods]
    next[idx] = v as SellingMethod
    onChange({
      ...value,
      sellingMethods: next,
      skus: rebuildSkus(colors, next, doorWidths, skus),
    })
  }

  const handleRemoveSellingMethod = (idx: number) => {
    const next = sellingMethods.filter((_, i) => i !== idx)
    onChange({
      ...value,
      sellingMethods: next,
      skus: rebuildSkus(colors, next, doorWidths, skus),
    })
  }

  // ========== 规格尺寸（多行下拉，去重） ==========
  const handleAddDoorWidth = () => {
    if (doorWidths.length >= DOOR_WIDTH_OPTIONS.length) {
      toast.warning('已添加全部可用的规格尺寸')
      return
    }
    onChange({ ...value, doorWidths: [...doorWidths, ''] })
  }

  const handleChangeDoorWidth = (idx: number, v: string) => {
    if (!v) {
      const next = doorWidths.filter((_, i) => i !== idx)
      onChange({
        ...value,
        doorWidths: next,
        skus: rebuildSkus(colors, sellingMethods, next, skus),
      })
      return
    }
    if (doorWidths.some((w, i) => i !== idx && w === v)) {
      toast.warning('当前规格尺寸已经添加过了哦')
      return
    }
    const next = [...doorWidths]
    next[idx] = v
    onChange({
      ...value,
      doorWidths: next,
      skus: rebuildSkus(colors, sellingMethods, next, skus),
    })
  }

  const handleRemoveDoorWidth = (idx: number) => {
    const next = doorWidths.filter((_, i) => i !== idx)
    onChange({
      ...value,
      doorWidths: next,
      skus: rebuildSkus(colors, sellingMethods, next, skus),
    })
  }

  // ========== SKU 单元格 ==========
  const validSellingMethods = useMemo(
    () => sellingMethods.filter((m) => !!m),
    [sellingMethods]
  )
  const validDoorWidths = useMemo(
    () => doorWidths.filter((w) => !!w),
    [doorWidths]
  )

  const handleSkuChange = (
    colorId: number,
    method: SellingMethod,
    width: string,
    field: 'price' | 'stock',
    val: number
  ) => {
    const nextSkus = skus.map((s) =>
      s.colorId === colorId &&
      s.sellingMethod === method &&
      s.doorWidth === width
        ? { ...s, [field]: val }
        : s
    )
    onChange({ ...value, skus: nextSkus })
  }

  // ========== 批量填写 ==========
  const [batchScope, setBatchScope] = useState<BatchScope>('all')
  const [batchTarget, setBatchTarget] = useState<string>('')
  const [batchPrice, setBatchPrice] = useState('')
  const [batchStock, setBatchStock] = useState('')

  const handleBatchFill = () => {
    if (skus.length === 0) {
      toast.warning('请先完善颜色 / 售卖方式 / 规格尺寸')
      return
    }
    const priceNum = batchPrice === '' ? null : parseFloat(batchPrice)
    const stockNum = batchStock === '' ? null : parseInt(batchStock, 10)
    if (priceNum === null && stockNum === null) {
      toast.warning('请填写价格或数量')
      return
    }
    const isMatch = (s: ProductSku): boolean => {
      if (batchScope === 'all') return true
      if (batchScope === 'color') return String(s.colorId) === batchTarget
      if (batchScope === 'method') return s.sellingMethod === batchTarget
      if (batchScope === 'width') return s.doorWidth === batchTarget
      return false
    }
    if (batchScope !== 'all' && !batchTarget) {
      toast.warning('请选择批量填写目标')
      return
    }
    let touched = 0
    const nextSkus = skus.map((s) => {
      if (!isMatch(s)) return s
      touched++
      return {
        ...s,
        price: priceNum !== null && !isNaN(priceNum) ? priceNum : s.price,
        stock: stockNum !== null && !isNaN(stockNum) ? stockNum : s.stock,
      }
    })
    onChange({ ...value, skus: nextSkus })
    toast.success(`已批量填写 ${touched} 条`)
  }

  const batchTargetOptions = useMemo(() => {
    if (batchScope === 'color')
      return colors.map((c) => ({
        value: String(c.id),
        label: c.colorName || '未命名颜色',
      }))
    if (batchScope === 'method')
      return validSellingMethods.map((m) => ({
        value: m,
        label: SellingMethodLabels[m],
      }))
    if (batchScope === 'width')
      return validDoorWidths.map((w) => ({ value: w, label: w }))
    return []
  }, [batchScope, colors, validSellingMethods, validDoorWidths])

  const totalSkus = colors.length * validSellingMethods.length * validDoorWidths.length

  // ========== 颜色校验 - 单行错误 ==========
  const colorRowError = (c: ProductColor): string | null => {
    if (!c.colorName || !c.colorName.trim()) return '所填的值不能为空，请修改'
    return null
  }

  // ========== 渲染 ==========
  return (
    <div className="space-y-7">
      {/* ===== 销售属性标题 ===== */}
      <div className="text-sm font-medium text-gray-800">
        销售属性<span className="text-red-500 ml-1">*</span>
      </div>

      {/* ===== 颜色分类 ===== */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-700">
              颜色分类
              <span className="ml-1 text-gray-400">({colors.length})</span>
            </span>
            <span className="text-xs text-gray-400">
              最多新增 {MAX_COLORS} 个颜色分类，每种颜色分类最多可输入 {COLOR_NAME_MAX} 字符。
            </span>
          </div>
          <button
            type="button"
            onClick={() => setColorSortMode((v) => !v)}
            className={`text-sm px-2 py-0.5 rounded transition-colors ${
              colorSortMode ? 'text-primary-600 bg-primary-50' : 'text-primary-500 hover:bg-gray-50'
            }`}
          >
            {colorSortMode ? '完成排序' : '排序'}
          </button>
        </div>

        {/* 预设颜色面板 */}
        <PresetColorPalette onPick={(name, hex) => handleAddColorWithPreset(name, hex)} />

        {/* 批量输入颜色 */}
        <BatchColorInput onAdd={(names) => names.forEach((name) => handleAddColorWithPreset(name, ''))} />

        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">
          {colors.map((color, idx) => {
            const err = colorRowError(color)
            return (
              <div
                key={color.id}
                draggable={colorSortMode}
                onDragStart={() => setColorDragIdx(idx)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => handleColorDrop(idx)}
                className={`flex items-center gap-2 ${
                  colorSortMode ? 'cursor-grab active:cursor-grabbing' : ''
                }`}
              >
                {colorSortMode && (
                  <GripVertical className="w-4 h-4 text-gray-400 shrink-0" />
                )}
                {/* 图片 */}
                <ColorImage
                  url={color.colorImageUrl}
                  onChange={(u) => handleUpdateColor(idx, { colorImageUrl: u })}
                />
                {/* 名称 + 主色选择器 */}
                <div className="flex-1 min-w-0">
                  <ColorPicker
                    colorName={color.colorName}
                    mainColorHex={color.mainColorHex}
                    hasError={!!err}
                    onChange={(name, hex) =>
                      handleUpdateColor(idx, { colorName: name, mainColorHex: hex })
                    }
                    onNameChange={(name) =>
                      handleUpdateColor(idx, { colorName: name })
                    }
                  />
                </div>
                {/* 备注 */}
                <div className="flex-1 min-w-0">
                  <input
                    type="text"
                    value={color.remark || ''}
                    maxLength={COLOR_NAME_MAX}
                    placeholder="备注(可选)"
                    onChange={(e) => handleUpdateColor(idx, { remark: e.target.value })}
                    className="w-full h-9 px-2.5 text-sm rounded border border-gray-300 bg-white focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                </div>
                {/* 删除 */}
                <button
                  type="button"
                  onClick={() => handleRemoveColor(idx)}
                  className="shrink-0 w-9 h-9 inline-flex items-center justify-center rounded text-gray-400 hover:text-red-500 hover:bg-red-50"
                  title="删除"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
                {/* 行内错误 */}
                {err && (
                  <p className="basis-full pl-11 text-xs text-red-500 -mt-0.5">{err}</p>
                )}
              </div>
            )
          })}

          {/* 添加按钮 */}
          {colors.length < MAX_COLORS && (
            <button
              type="button"
              onClick={handleAddColor}
              className="h-9 inline-flex items-center justify-center gap-1 rounded border border-dashed border-gray-300 text-sm text-gray-500 hover:border-primary-400 hover:text-primary-600 hover:bg-primary-50/30 transition-colors"
            >
              <Plus className="w-4 h-4" />
              添加颜色分类
            </button>
          )}
        </div>
        {errors?.colors && (
          <p className="text-sm text-red-600 mt-2">{errors.colors}</p>
        )}
      </div>

      {/* ===== 售卖方式 ===== */}
      <RowSelectorSection
        title="售卖方式"
        count={validSellingMethods.length}
        sortableHidden
        onAdd={handleAddSellingMethod}
        canAdd={sellingMethods.length < SELLING_METHOD_OPTIONS.length}
        error={errors?.sellingMethods}
      >
        {sellingMethods.map((m, idx) => (
          <div key={`sm-${idx}`} className="flex items-center gap-2">
            <div className="w-44">
              <Select
                options={[
                  { value: '', label: '请选择' },
                  ...SELLING_METHOD_OPTIONS.map((o) => ({
                    value: o.value,
                    label: o.label,
                  })),
                ]}
                value={m || ''}
                onChange={(e) => handleChangeSellingMethod(idx, e.target.value)}
              />
            </div>
            <button
              type="button"
              onClick={() => handleRemoveSellingMethod(idx)}
              className="w-9 h-9 inline-flex items-center justify-center rounded text-gray-400 hover:text-red-500 hover:bg-red-50"
              title="删除"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ))}
      </RowSelectorSection>

      {/* ===== 规格尺寸 ===== */}
      <RowSelectorSection
        title="规格尺寸"
        count={validDoorWidths.length}
        sortableHidden
        onAdd={handleAddDoorWidth}
        canAdd={doorWidths.length < DOOR_WIDTH_OPTIONS.length}
        error={errors?.doorWidths}
      >
        {doorWidths.map((w, idx) => (
          <div key={`dw-${idx}`} className="flex items-center gap-2">
            <div className="w-44">
              <Select
                options={[
                  { value: '', label: '请选择' },
                  ...DOOR_WIDTH_OPTIONS.map((o) => ({ value: o, label: o })),
                ]}
                value={w || ''}
                onChange={(e) => handleChangeDoorWidth(idx, e.target.value)}
              />
            </div>
            <button
              type="button"
              onClick={() => handleRemoveDoorWidth(idx)}
              className="w-9 h-9 inline-flex items-center justify-center rounded text-gray-400 hover:text-red-500 hover:bg-red-50"
              title="删除"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ))}
      </RowSelectorSection>

      {/* ===== 销售规格表 ===== */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-800">
            销售规格<span className="text-red-500 ml-1">*</span>
          </span>
          <span className="text-xs text-gray-400 tabular-nums">
            总数: {totalSkus}/{MAX_SKUS}
          </span>
        </div>

        {/* 批量填写工具栏 */}
        <div className="flex flex-wrap items-center gap-2 mb-2 p-2 rounded bg-gray-50/60 border border-gray-200/70">
          <div className="w-28">
            <Select
              options={[
                { value: 'all', label: '全部' },
                { value: 'color', label: '按颜色分类' },
                { value: 'method', label: '按售卖方式' },
                { value: 'width', label: '按规格尺寸' },
              ]}
              value={batchScope}
              onChange={(e) => {
                setBatchScope(e.target.value as BatchScope)
                setBatchTarget('')
              }}
            />
          </div>
          {batchScope !== 'all' && (
            <div className="w-44">
              <Select
                options={[
                  { value: '', label: '请选择' },
                  ...batchTargetOptions,
                ]}
                value={batchTarget}
                onChange={(e) => setBatchTarget(e.target.value)}
              />
            </div>
          )}
          <div className="relative">
            <input
              type="number"
              placeholder="价格"
              min="0"
              step="0.01"
              value={batchPrice}
              onChange={(e) => setBatchPrice(e.target.value)}
              className="h-9 w-28 pl-2 pr-8 text-sm rounded border border-gray-300 bg-white focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
            />
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-400">
              元
            </span>
          </div>
          <div className="relative">
            <input
              type="number"
              placeholder="数量"
              min="0"
              step="1"
              value={batchStock}
              onChange={(e) => setBatchStock(e.target.value)}
              className="h-9 w-28 pl-2 pr-8 text-sm rounded border border-gray-300 bg-white focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
            />
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-400">
              件
            </span>
          </div>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={handleBatchFill}
          >
            批量填写
          </Button>
        </div>

        {/* 批量填写提示 */}
        <p className="text-xs text-gray-400 mb-2">
          提示：选择目标范围并填入价格/库存，点击&ldquo;批量填写&rdquo;即可统一设置。多个规格请分批次填写。
        </p>

        {totalSkus === 0 ? (
          <div className="text-sm text-gray-400 text-center py-6 border border-dashed border-gray-200 rounded">
            请先完善颜色分类、售卖方式、规格尺寸
          </div>
        ) : (
          <div className="overflow-x-auto border border-gray-200 rounded-md">
            <table className="w-full text-sm border-collapse">
              <thead className="bg-gray-50/80">
                <tr className="text-gray-600">
                  <th className="px-3 py-2.5 text-left font-medium border-b border-gray-200 w-[26%]">
                    颜色分类
                  </th>
                  <th className="px-3 py-2.5 text-left font-medium border-b border-gray-200 w-[14%]">
                    售卖方式
                  </th>
                  <th className="px-3 py-2.5 text-left font-medium border-b border-gray-200 w-[14%]">
                    规格尺寸
                  </th>
                  <th className="px-3 py-2.5 text-left font-medium border-b border-gray-200 w-[23%]">
                    <span className="text-red-500 mr-0.5">*</span>价格（元）
                  </th>
                  <th className="px-3 py-2.5 text-left font-medium border-b border-gray-200 w-[23%]">
                    <span className="text-red-500 mr-0.5">*</span>库存（米）
                  </th>
                </tr>
              </thead>
              <tbody>
                {colors.map((color) => {
                  const colorRowSpan =
                    validSellingMethods.length * validDoorWidths.length || 1
                  return validSellingMethods.map((method, mIdx) =>
                    validDoorWidths.map((width, wIdx) => {
                      const sku = skus.find(
                        (s) =>
                          s.colorId === color.id &&
                          s.sellingMethod === method &&
                          s.doorWidth === width
                      )
                      const isFirstRowOfColor = mIdx === 0 && wIdx === 0
                      const isFirstRowOfMethod = wIdx === 0
                      return (
                        <tr
                          key={`${color.id}-${method}-${width}`}
                          className="border-b border-gray-100 last:border-b-0 hover:bg-gray-50/40"
                        >
                          {isFirstRowOfColor && (
                            <td
                              rowSpan={colorRowSpan}
                              className="px-3 py-2 align-middle border-r border-gray-100 bg-white"
                            >
                              <div className="flex items-center gap-2">
                                <div className="w-10 h-10 shrink-0 rounded overflow-hidden border border-gray-200 bg-gray-50">
                                  {color.colorImageUrl && color.colorImageUrl.trim() !== '' ? (
                                    <Image
                                      src={resolveImageUrl(color.colorImageUrl)}
                                      alt={color.colorName || ''}
                                      width={40}
                                      height={40}
                                      className="w-full h-full object-cover"
                                      unoptimized
                                    />
                                  ) : (
                                    <div className="w-full h-full flex items-center justify-center text-gray-300">
                                      <ImagePlus className="w-4 h-4" />
                                    </div>
                                  )}
                                </div>
                                <div className="text-sm text-gray-700 truncate">
                                  {color.colorName || '未命名'}
                                  {color.remark && (
                                    <span className="text-gray-400">
                                      （{color.remark}）
                                    </span>
                                  )}
                                </div>
                              </div>
                            </td>
                          )}
                          {isFirstRowOfMethod && (
                            <td
                              rowSpan={validDoorWidths.length}
                              className="px-3 py-2 align-middle border-r border-gray-100 text-gray-700"
                            >
                              {SellingMethodLabels[method]}
                            </td>
                          )}
                          <td className="px-3 py-2 border-r border-gray-100 text-gray-700">
                            {width}
                          </td>
                          <td className="px-3 py-2 border-r border-gray-100">
                            <input
                              type="number"
                              min="0"
                              step="0.01"
                              placeholder="0.00"
                              value={sku?.price || ''}
                              onChange={(e) =>
                                handleSkuChange(
                                  color.id,
                                  method,
                                  width,
                                  'price',
                                  parseFloat(e.target.value) || 0
                                )
                              }
                              className="w-full h-8 px-2 text-sm rounded border border-gray-300 bg-white focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                            />
                          </td>
                          <td className="px-3 py-2">
                            <input
                              type="number"
                              min="0"
                              step="1"
                              placeholder="0"
                              value={sku?.stock || ''}
                              onChange={(e) =>
                                handleSkuChange(
                                  color.id,
                                  method,
                                  width,
                                  'stock',
                                  parseInt(e.target.value, 10) || 0
                                )
                              }
                              className="w-full h-8 px-2 text-sm rounded border border-gray-300 bg-white focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                            />
                          </td>
                        </tr>
                      )
                    })
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {errors?.skus && <p className="text-sm text-red-600 mt-2">{errors.skus}</p>}
      </div>
    </div>
  )
}

// ========== 子组件：售卖方式 / 规格尺寸 区块 ==========

interface RowSelectorSectionProps {
  title: string
  count: number
  onAdd: () => void
  canAdd: boolean
  error?: string
  children: React.ReactNode
  /** 排序按钮虽出现在 PRD 但 MVP 可暂时占位（保持视觉一致） */
  sortableHidden?: boolean
}

function RowSelectorSection({
  title,
  count,
  onAdd,
  canAdd,
  error,
  children,
}: RowSelectorSectionProps) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-gray-700">
          {title}
          <span className="ml-1 text-gray-400">({count})</span>
        </span>
        <span className="text-sm text-primary-500 cursor-default select-none">排序</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {children}
        <button
          type="button"
          onClick={onAdd}
          disabled={!canAdd}
          className={`w-9 h-9 inline-flex items-center justify-center rounded border border-dashed transition-colors ${
            canAdd
              ? 'border-gray-300 text-gray-500 hover:border-primary-400 hover:text-primary-600'
              : 'border-gray-200 text-gray-300 cursor-not-allowed'
          }`}
          title="添加"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>
      {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
    </div>
  )
}

// ========== 子组件：颜色行内的小图上传（36x36 微缩） ==========

function ColorImage({
  url,
  onChange,
}: {
  url?: string
  onChange: (u: string) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const uploadingRef = useRef(false)

  const handleFiles = async (files: FileList | null) => {
    if (!files || !files.length || uploadingRef.current) return
    const file = files[0]
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) {
      toast.error('仅支持 JPG / PNG / WEBP 图片')
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      toast.error('图片不能超过 5MB')
      return
    }
    uploadingRef.current = true
    try {
      const res = await fileApi.uploadFile(file, 'product-color')
      onChange(res.data.data.url)
    } catch {
      // 错误由 API 层提示
    } finally {
      uploadingRef.current = false
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <div
      className={`relative w-9 h-9 rounded border bg-gray-50 cursor-pointer overflow-hidden flex items-center justify-center transition-colors ${
        url ? 'border-gray-200' : 'border-dashed border-gray-300 hover:border-primary-400 hover:bg-primary-50/30'
      }`}
      title={url ? '点击替换图片' : '点击上传图片'}
    >
      {url && url.trim() !== '' ? (
        <Image src={resolveImageUrl(url)} alt="color" width={36} height={36} className="w-full h-full object-cover" unoptimized />
      ) : (
        <ImagePlus className="w-4 h-4 text-gray-400" />
      )}
      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
        onChange={(e) => handleFiles(e.target.files)}
      />
    </div>
  )
}

// ========== 预设颜色面板（使用上方 PRESET_COLORS 常量） ==========

function PresetColorPalette({
  onPick,
}: {
  onPick: (name: string, hex: string) => void
}) {
  const [collapsed, setCollapsed] = useState(true)

  return (
    <div className="mb-3">
      <button
        type="button"
        onClick={() => setCollapsed(!collapsed)}
        className="text-xs text-primary-500 hover:text-primary-700 flex items-center gap-1"
      >
        {collapsed ? '▸ 展开预设颜色' : '▾ 收起预设颜色'}
      </button>
      {!collapsed && (
        <div className="flex flex-wrap gap-1.5 mt-2">
          {PRESET_COLORS.map((c) => (
            <button
              key={c.name}
              type="button"
              onClick={() => onPick(c.name, c.hex)}
              className="inline-flex items-center gap-1 px-2 py-1 rounded border border-gray-200 hover:border-primary-400 hover:bg-primary-50 text-xs transition-colors"
              title={c.name}
            >
              <span
                className="w-3.5 h-3.5 rounded-full border border-gray-300 flex-shrink-0"
                style={{ backgroundColor: c.hex }}
              />
              {c.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ========== 批量输入颜色 ==========

function BatchColorInput({ onAdd }: { onAdd: (names: string[]) => void }) {
  const [collapsed, setCollapsed] = useState(true)
  const [text, setText] = useState('')

  const handleApply = () => {
    const names = text
      .split(/[\n,，、]+/)
      .map((s) => s.trim())
      .filter(Boolean)
    if (names.length === 0) return
    onAdd(names)
    setText('')
    setCollapsed(true)
  }

  return (
    <div className="mb-3">
      <button
        type="button"
        onClick={() => setCollapsed(!collapsed)}
        className="text-xs text-primary-500 hover:text-primary-700 flex items-center gap-1"
      >
        {collapsed ? '▸ 批量输入颜色' : '▾ 收起批量输入'}
      </button>
      {!collapsed && (
        <div className="mt-2 space-y-2">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="每行一个颜色名称，或用逗号、顿号分隔&#10;例如：红色, 蓝色, 米色"
            rows={3}
            className="w-full px-3 py-2 text-sm rounded border border-gray-300 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
          />
          <div className="flex items-center gap-2">
            <Button type="button" size="sm" onClick={handleApply} disabled={!text.trim()}>
              添加颜色
            </Button>
            <span className="text-xs text-gray-400">
              支持换行、逗号、顿号分隔
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

// ========== 子组件：主色选择器（名称输入框 + 预设颜色 popover） ==========

function ColorPicker({
  colorName,
  mainColorHex,
  hasError,
  onChange,
  onNameChange,
}: {
  colorName: string
  mainColorHex?: string
  hasError?: boolean
  onChange: (name: string, hex: string) => void
  onNameChange: (name: string) => void
}) {
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)

  // 点击外部 / ESC 关闭
  useEffect(() => {
    if (!open) return
    const onClickOutside = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClickOutside)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const handlePick = (hex: string, name: string) => {
    onChange(name, hex)
    setOpen(false)
  }

  return (
    <div ref={wrapperRef} className="relative">
      <div
        className={`flex items-stretch h-9 rounded border bg-white focus-within:ring-2 focus-within:ring-primary-500/15 ${
          hasError
            ? 'border-red-400 focus-within:border-red-500'
            : 'border-gray-300 focus-within:border-primary-500'
        }`}
      >
        {/* 色块触发 popover */}
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="shrink-0 w-9 h-full inline-flex items-center justify-center border-r border-gray-200 hover:bg-gray-50 transition-colors"
          title="选择主色"
        >
          {mainColorHex ? (
            <span
              className="w-5 h-5 rounded-sm border border-gray-200 shadow-inner"
              style={{ backgroundColor: mainColorHex }}
            />
          ) : (
            <span
              className="w-5 h-5 rounded-sm border border-dashed border-gray-300 bg-[conic-gradient(from_45deg,#f87171,#fbbf24,#34d399,#60a5fa,#a78bfa,#f87171)]"
              aria-hidden
            />
          )}
        </button>
        {/* 名称输入（可编辑） */}
        <input
          type="text"
          value={colorName}
          maxLength={COLOR_NAME_MAX}
          placeholder="主色(必选)"
          onChange={(e) => onNameChange(e.target.value)}
          className="flex-1 min-w-0 px-2.5 text-sm bg-transparent focus:outline-none"
        />
      </div>

      {/* 预设颜色面板 */}
      {open && (
        <div
          className="absolute z-30 mt-1 left-0 w-[280px] rounded-lg border border-gray-200 bg-white shadow-lg p-3"
          role="dialog"
          aria-label="选择主色"
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-500">选择主色（选择后可编辑名称）</span>
          </div>
          <div className="grid grid-cols-5 gap-2">
            {PRESET_COLORS.map((c) => {
              const selected =
                mainColorHex && mainColorHex.toUpperCase() === c.hex.toUpperCase()
              return (
                <button
                  key={c.hex}
                  type="button"
                  onClick={() => handlePick(c.hex, c.name)}
                  className="flex flex-col items-center gap-1 p-1 rounded hover:bg-gray-50 transition-colors"
                  title={`${c.name} ${c.hex}`}
                >
                  <span
                    className={`relative w-8 h-8 rounded border ${
                      c.hex.toUpperCase() === '#FFFFFF'
                        ? 'border-gray-300'
                        : 'border-gray-200'
                    } shadow-inner`}
                    style={{ backgroundColor: c.hex }}
                  >
                    {selected && (
                      <Check
                        className={`absolute inset-0 m-auto w-4 h-4 ${
                          ['#FFFFFF', '#FFFDD0', '#FFFF00', '#FFC0CB', '#00FFFF', '#C0C0C0', '#C3B091'].includes(
                            c.hex.toUpperCase()
                          )
                            ? 'text-gray-700'
                            : 'text-white'
                        }`}
                      />
                    )}
                  </span>
                  <span className="text-[11px] text-gray-600 leading-none">{c.name}</span>
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
