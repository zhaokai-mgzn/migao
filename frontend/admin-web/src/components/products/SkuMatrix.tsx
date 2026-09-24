/* eslint-disable react/no-unescaped-entities */
'use client'

import { useMemo, useRef, useState, useEffect } from 'react'
import { Plus, Trash2, GripVertical, Check, AlertCircle } from 'lucide-react'
import { toast } from 'sonner'
import { Button, NumberInput, Select } from '@/components/ui'
import type { ProductColor, ProductSku } from '@/types'
import { RecognizedBadge } from '@/components/image-recognize/ImageRecognizeButton'
import { rebuildSkus, nextTempId, DOOR_WIDTH_OPTIONS, doorWidthSelectOptions, normalizeDoorWidth, formatDoorWidth, sameDoorWidth } from '@/lib/sku-utils'

interface SkuMatrixProps {
  value: {
    colors: ProductColor[]
    doorWidths: string[]
    skus: ProductSku[]
  }
  onChange: (v: {
    colors: ProductColor[]
    doorWidths: string[]
    skus: ProductSku[]
  }) => void
  errors?: {
    colors?: string
    doorWidths?: string
    skus?: string
  }
  /**
   * 已被**图片识别**预填的字段键（issue #5321 包 1）—— **可选**，只影响渲染：
   * 在「颜色分类」/「规格尺寸」两处标题旁显示 `[图片识别]` 徽标提醒商家复核。
   * 颜色与门幅都是**列表字段**（没有单一输入框可挂），故徽标挂在区块标题上 ——
   * 商家据此知道这两列是识别来的、要逐行核对（价格 / 库存不预填，仍由商家填）。
   */
  recognizedFields?: string[]
}

// 门幅选项（值 canonical 裸数值 / 显示带单位）见 @/lib/sku-utils 的 DOOR_WIDTH_OPTIONS
// （issue #3621：值/显示分离，避免选项值 '2.8米' 与库内 '2.8' 口径不一致）

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

type BatchScope = 'all' | 'color' | 'width'

/**
 * 销售属性矩阵：**颜色 × 门幅**。
 *
 * ⚠️ 「售卖方式（整卷 / 散剪）」**不在这里** —— 它是商品级基础属性
 * （`ProductForm` 的基础属性区，请求体顶层 `sellingMethods`），不是 SKU 的组合项。
 */
export default function SkuMatrix({ value, onChange, errors, recognizedFields }: SkuMatrixProps) {
  const { colors, doorWidths, skus } = value
  // 图片识别预填的响应字段键（issue #5321）——只驱动 `[图片识别]` 徽标，不参与提交
  const recognized = recognizedFields || []

  // ========== 颜色管理 ==========
  const handleAddColor = () => {
    if (colors.length >= MAX_COLORS) {
      toast.warning(`最多只能添加 ${MAX_COLORS} 种颜色分类`)
      return
    }
    const newColor: ProductColor = {
      id: nextTempId(),
      colorName: '',
      remark: '',
      sortOrder: colors.length,
    }
    const nextColors = [...colors, newColor]
    onChange({
      ...value,
      colors: nextColors,
      skus: rebuildSkus(nextColors, doorWidths, skus),
    })
  }

  const handleAddColorWithPreset = (name: string, hex: string) => {
    if (colors.length >= MAX_COLORS) {
      toast.warning(`最多只能添加 ${MAX_COLORS} 种颜色分类`)
      return
    }
    const newColor: ProductColor = {
      id: nextTempId(),
      colorName: name,
      mainColorHex: hex || undefined,
      remark: '',
      sortOrder: colors.length,
    }
    const nextColors = [...colors, newColor]
    onChange({
      ...value,
      colors: nextColors,
      skus: rebuildSkus(nextColors, doorWidths, skus),
    })
  }

  // 批量添加颜色：一次 state update 中添加所有颜色，避免 forEach 中的闭包陷阱
  const handleBatchAddColors = (names: string[]) => {
    if (colors.length >= MAX_COLORS) {
      toast.warning(`最多只能添加 ${MAX_COLORS} 种颜色分类`)
      return
    }
    const available = MAX_COLORS - colors.length
    const toAdd = names.slice(0, available).map((name, i) => ({
      id: nextTempId(),
      colorName: name,
      mainColorHex: undefined as string | undefined,
      remark: '',
      sortOrder: colors.length + i,
    } satisfies ProductColor))
    if (names.length > available) {
      toast.warning(`最多只能添加 ${MAX_COLORS} 种颜色，已截取前 ${available} 个`)
    }
    const nextColors = [...colors, ...toAdd]
    onChange({
      ...value,
      colors: nextColors,
      skus: rebuildSkus(nextColors, doorWidths, skus),
    })
  }

  const handleUpdateColor = (idx: number, patch: Partial<ProductColor>) => {
    const nextColors = [...colors]
    nextColors[idx] = { ...nextColors[idx], ...patch }
    // 同步 sku.colorName（兼容 colorId 和 colorName 匹配）
    const nextSkus =
      patch.colorName !== undefined
        ? skus.map((s) => {
            const idMatch = s.colorId != null && s.colorId === nextColors[idx].id
            const nameMatch = s.colorName === nextColors[idx].colorName
            if (idMatch || (s.colorId == null && nameMatch)) {
              return { ...s, colorName: patch.colorName! }
            }
            return s
          })
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
      skus: rebuildSkus(reordered, doorWidths, skus),
    })
    setColorDragIdx(null)
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
        skus: rebuildSkus(colors, next, skus),
      })
      return
    }
    // issue #3621：同一物理门幅只允许一个组合 —— 已存在 '2.8' 时不得再加 '2.8米'
    if (doorWidths.some((w, i) => i !== idx && sameDoorWidth(w, v))) {
      toast.warning('当前规格尺寸已经添加过了哦')
      return
    }
    const next = [...doorWidths]
    // 写入侧口径统一：落表单的是 canonical 裸数值（与库内 product_skus.door_width 一致）
    next[idx] = normalizeDoorWidth(v) || v
    onChange({
      ...value,
      doorWidths: next,
      skus: rebuildSkus(colors, next, skus),
    })
  }

  const handleRemoveDoorWidth = (idx: number) => {
    const next = doorWidths.filter((_, i) => i !== idx)
    onChange({
      ...value,
      doorWidths: next,
      skus: rebuildSkus(colors, next, skus),
    })
  }

  // ========== SKU 单元格 ==========
  const validDoorWidths = useMemo(
    () => doorWidths.filter((w) => !!w),
    [doorWidths]
  )

  // 规格尺寸下拉选项：值 canonical（与库内一致）+ 显示带单位；同一物理门幅只一个 entry
  // （含历史写法 '2.8米'/'门幅2.8米' 的回显兜底，issue #3621）
  const widthSelectOptions = useMemo(
    () => doorWidthSelectOptions(doorWidths),
    [doorWidths]
  )

  // 与表格渲染共用同一匹配逻辑（优先 colorId，兜底 colorName + 门幅双侧归一化）
  const findSku = (
    color: ProductColor,
    width: string
  ): ProductSku | undefined =>
    skus.find((s) => {
      const idMatch = s.colorId != null && s.colorId === color.id
      const nameMatch = s.colorName === color.colorName
      return (
        (idMatch || (s.colorId == null && nameMatch)) &&
        sameDoorWidth(s.doorWidth, width)
      )
    })

  // 未填写的价格/库存单元格计数（与 validateProductForm 规则一致：价格>0、库存>=0）
  const invalidCounts = useMemo(() => {
    let price = 0
    let stock = 0
    for (const color of colors) {
      for (const width of validDoorWidths) {
        const sku = findSku(color, width)
        if (!sku || Number(sku.price) <= 0) price++
        if (!sku || Number(sku.stock) < 0) stock++
      }
    }
    return { price, stock, total: price + stock }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [colors, validDoorWidths, skus])

  const handleSkuChange = (
    colorId: string,
    colorName: string,
    width: string,
    field: 'price' | 'stock',
    val: number
  ) => {
    const nextSkus = skus.map((s) => {
      const idMatch = s.colorId != null && s.colorId === colorId
      const nameMatch = s.colorName === colorName
      if ((idMatch || (s.colorId == null && nameMatch)) &&
        sameDoorWidth(s.doorWidth, width)) {
        return { ...s, [field]: val }
      }
      return s
    })
    onChange({ ...value, skus: nextSkus })
  }

  // ========== 批量填写 ==========
  const [batchScope, setBatchScope] = useState<BatchScope>('all')
  const [batchTarget, setBatchTarget] = useState<string>('')
  const [batchPrice, setBatchPrice] = useState('')
  // issue #5237：库存草稿由共享 NumberInput 直接给 `number | null`（价格那条仍是 `string` +
  // parseFloat，本单**不动**它 —— 它的精度本来就是对的，见测试「价格框逐值不变」）。
  const [batchStock, setBatchStock] = useState<number | null>(null)

  const handleBatchFill = () => {
    if (skus.length === 0) {
      toast.warning('请先完善颜色 / 规格尺寸')
      return
    }
    const priceNum = batchPrice === '' ? null : parseFloat(batchPrice)
    // issue #5237：旧形态 `parseInt(batchStock, 10)` 把 `60.5` **静默截成 `60`** —— 丢 0.5 米，
    // 无报错、无提示、无痕迹（截断发生在提交之前 ⇒ 后端收到的就是 `60`，无从察觉）。
    // 库存值现在由共享 `NumberInput` 给：`decimals={1}` ⇒ 失焦按 1 位小数归一，
    // 与列口径 `NUMERIC(12,1)`（V115 / #5063）同源。此处**不再自行解析**。
    const stockNum = batchStock
    if (priceNum === null && stockNum === null) {
      toast.warning('请填写价格或数量')
      return
    }
    const isMatch = (s: ProductSku): boolean => {
      if (batchScope === 'all') return true
      if (batchScope === 'color') return String(s.colorId) === batchTarget
      if (batchScope === 'width') return sameDoorWidth(s.doorWidth, batchTarget)
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
    if (batchScope === 'width')
      return validDoorWidths.map((w) => ({
        value: normalizeDoorWidth(w) || w,
        label: formatDoorWidth(w),
      }))
    return []
  }, [batchScope, colors, validDoorWidths])

  const totalSkus = colors.length * validDoorWidths.length

  // ========== 颜色校验 - 单行错误 ==========
  const colorRowError = (c: ProductColor): string | null => {
    if (!c.colorName || !c.colorName.trim()) return '所填的值不能为空，请修改'
    return null
  }

  // ========== 渲染 ==========
  return (
    <div className="space-y-7">
      {/* ===== 销售属性标题 ===== */}
      <div className="text-sm font-medium text-neutral-800">
        销售属性<span className="text-red-500 ml-1">*</span>
      </div>

      {/* ===== 颜色分类 ===== */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-sm text-neutral-700">
              颜色分类
              <span className="ml-1 text-neutral-400">({colors.length})</span>
              {recognized.includes('color') && <RecognizedBadge fieldKey="color" />}
            </span>
            <span className="text-xs text-neutral-400">
              最多新增 {MAX_COLORS} 个颜色分类，每种颜色分类最多可输入 {COLOR_NAME_MAX} 字符。
            </span>
          </div>
          <button
            type="button"
            onClick={() => setColorSortMode((v) => !v)}
            className={`text-sm px-2 py-0.5 rounded transition-colors ${
              colorSortMode ? 'text-primary-600 bg-primary-50' : 'text-primary-500 hover:bg-neutral-50'
            }`}
          >
            {colorSortMode ? '完成排序' : '排序'}
          </button>
        </div>

        {/* 预设颜色面板 */}
        <PresetColorPalette onPick={(name, hex) => handleAddColorWithPreset(name, hex)} />

        {/* 批量输入颜色 */}
        <BatchColorInput onAdd={handleBatchAddColors} />

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
                  <GripVertical className="w-4 h-4 text-neutral-400 shrink-0" />
                )}
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
                    className="w-full h-9 px-2.5 text-sm rounded border border-neutral-300 bg-white focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                </div>
                {/* 删除 */}
                <button
                  type="button"
                  onClick={() => handleRemoveColor(idx)}
                  className="relative z-40 shrink-0 w-9 h-9 inline-flex items-center justify-center rounded text-neutral-400 hover:text-red-500 hover:bg-red-50"
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
              className="h-9 inline-flex items-center justify-center gap-1 rounded border border-dashed border-neutral-300 text-sm text-neutral-500 hover:border-primary-400 hover:text-primary-600 hover:bg-primary-50/30 transition-colors"
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

      {/* ===== 规格尺寸 ===== */}
      <RowSelectorSection
        title="规格尺寸"
        count={validDoorWidths.length}
        sortableHidden
        onAdd={handleAddDoorWidth}
        canAdd={doorWidths.length < DOOR_WIDTH_OPTIONS.length}
        error={errors?.doorWidths}
        badge={recognized.includes('door_width') ? <RecognizedBadge fieldKey="door_width" /> : undefined}
      >
        {doorWidths.map((w, idx) => (
          <div key={`dw-${idx}`} className="flex items-center gap-2">
            <div className="w-44">
              <Select
                aria-label="规格尺寸"
                options={[
                  { value: '', label: '请选择' },
                  ...widthSelectOptions,
                ]}
                // 值 = canonical 裸数值（与库内一致）；显示文案由 label 带单位 →
                // 同一 Select 不会出现「2.8」与「2.8米」两种写法（issue #3621）
                value={normalizeDoorWidth(w)}
                onChange={(e) => handleChangeDoorWidth(idx, e.target.value)}
              />
            </div>
            <button
              type="button"
              onClick={() => handleRemoveDoorWidth(idx)}
              className="relative z-40 w-9 h-9 inline-flex items-center justify-center rounded text-neutral-400 hover:text-red-500 hover:bg-red-50"
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
          <span className="text-sm font-medium text-neutral-800">
            销售规格<span className="text-red-500 ml-1">*</span>
          </span>
          <span className="text-xs text-neutral-400 tabular-nums">
            总数: {totalSkus}/{MAX_SKUS}
          </span>
        </div>

        {/* 批量填写工具栏 */}
        <div className="flex flex-wrap items-center gap-2 mb-2 p-2 rounded bg-neutral-50/60 border border-neutral-200/70">
          <div className="w-28">
            <Select
              options={[
                { value: 'all', label: '全部' },
                { value: 'color', label: '按颜色分类' },
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
              className="h-9 w-28 pl-2 pr-8 text-sm rounded border border-neutral-300 bg-white focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
            />
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-neutral-400">
              元
            </span>
          </div>
          <div className="relative">
            {/* issue #5237：旧形态是裸 `<input type="number" step="1">` + `parseInt` ⇒ 输入
                `60.5` 静默变 `60`。改用共享 NumberInput（`type="text"` + 字符串草稿，与 #5218
                的订正段口径一致），`decimals={1}` 对齐列口径 `NUMERIC(12,1)` = 0.1 米粒度。
                ⚠️ 单位文案仍是「件」：#5237 已把「库存到底按米还是按件」登记为**待用户裁定**项
                （`backend/admin-api/src/main/resources/db/init/schema.sql` 的列注释口径写的是「米」）⇒ 本单**只落数值精度、不擅改文案**。 */}
            <NumberInput
              min={0}
              decimals={1}
              placeholder="数量"
              value={batchStock}
              onChange={setBatchStock}
              className="h-9 w-28 pl-2 pr-8 text-sm rounded border border-neutral-300 bg-white focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
            />
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-neutral-400">
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
        <p className="text-xs text-neutral-400 mb-2">
          提示：选择目标范围并填入价格/库存，点击&ldquo;批量填写&rdquo;即可统一设置。多个规格请分批次填写。
        </p>

        {/* #2908: SKU 校验失败醒目提示（带计数 + 锚点供滚动定位） */}
        {errors?.skus && totalSkus > 0 && (
          <div
            id="pf-skus-error"
            role="alert"
            className="flex items-start gap-2 px-3 py-2.5 mb-3 rounded-md border border-red-300 bg-red-50"
          >
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-600" />
            <p className="text-sm text-red-700 leading-relaxed">
              <span className="font-medium">{errors.skus}</span>
              {invalidCounts.total > 0 && (
                <>
                  ，还有 <span className="font-semibold">{invalidCounts.total}</span> 处价格/库存未填写
                </>
              )}
            </p>
          </div>
        )}

        {totalSkus === 0 ? (
          <div className="text-sm text-neutral-400 text-center py-6 border border-dashed border-neutral-200 rounded">
            请先完善颜色分类、规格尺寸
          </div>
        ) : (
          <div className="overflow-x-auto border border-neutral-200 rounded-md">
            <table className="w-full text-sm border-collapse">
              <thead className="bg-neutral-50/80">
                <tr className="text-neutral-600">
                  <th className="px-3 py-2.5 text-left font-medium border-b border-neutral-200 w-[30%]">
                    颜色分类
                  </th>
                  <th className="px-3 py-2.5 text-left font-medium border-b border-neutral-200 w-[20%]">
                    规格尺寸
                  </th>
                  <th className="px-3 py-2.5 text-left font-medium border-b border-neutral-200 w-[25%]">
                    <span className="text-red-500 mr-0.5">*</span>价格（元）
                  </th>
                  <th className="px-3 py-2.5 text-left font-medium border-b border-neutral-200 w-[25%]">
                    <span className="text-red-500 mr-0.5">*</span>库存（米）
                  </th>
                </tr>
              </thead>
              <tbody>
                {colors.map((color) => {
                  const colorRowSpan = validDoorWidths.length || 1
                  return validDoorWidths.map((width, wIdx) => {
                    const sku = findSku(color, width)
                    // 与 validateProductForm 规则一致：价格必须 >0，库存必须 >=0
                    const priceInvalid = !sku || Number(sku.price) <= 0
                    const stockInvalid = !sku || Number(sku.stock) < 0
                    const validationOn = !!errors?.skus
                    const cellCls =
                      'w-full h-8 px-2 text-sm rounded border focus:outline-none focus:ring-2'
                    const cellClsNormal =
                      'bg-white border-neutral-300 focus:border-primary-500 focus:ring-primary-500/15'
                    const cellClsError =
                      'bg-red-50/60 border-red-400 focus:border-red-500 focus:ring-red-500/15'
                    const isFirstRowOfColor = wIdx === 0
                    return (
                      <tr
                        key={`${color.id}-${width}`}
                        className="border-b border-neutral-100 last:border-b-0 hover:bg-neutral-50/40"
                      >
                        {isFirstRowOfColor && (
                          <td
                            rowSpan={colorRowSpan}
                            className="px-3 py-2 align-middle border-r border-neutral-100 bg-white"
                          >
                            <div className="text-sm text-neutral-700 truncate">
                              {color.colorName || '未命名'}
                              {color.remark && (
                                <span className="text-neutral-400">
                                  （{color.remark}）
                                </span>
                              )}
                            </div>
                          </td>
                        )}
                        <td className="px-3 py-2 border-r border-neutral-100 text-neutral-700">
                          {formatDoorWidth(width)}
                        </td>
                        <td className="px-3 py-2 border-r border-neutral-100">
                          {/* issue #5198：旧形态 `value={sku?.price || ''}` + `parseFloat(raw) || 0`
                              会把合法的 0 与空值混为一谈 ⇒ 用户敲下 "0" 的当刻输入框被清空。
                              issue #5218 #1：`sku?.price ? sku.price : null` 是**同一个 bug 的新形态**
                              （0 是 falsy ⇒ 外部值 12.5 → null ⇒ 外部同步把正在输入的草稿洗掉）——
                              改成「只有真缺值（undefined/NaN）才映射成空」，0 原样喂给输入框。
                              ⚠️ 可见面后果：未填的行（`rebuildSkus` 落 `price: 0`）现在显示 `0`
                              而不是占位符 `0.00` —— 「0 = 未填写」由既有校验（`price > 0` + 标红 +
                              计数横幅）表达，输入框不再替商家把它藏起来。 */}
                          <NumberInput
                            min={0}
                            decimals={2}
                            placeholder="0.00"
                            value={
                              typeof sku?.price === 'number' && Number.isFinite(sku.price) ? sku.price : null
                            }
                            onChange={(v) =>
                              handleSkuChange(
                                color.id,
                                color.colorName,
                                width,
                                'price',
                                v ?? 0
                              )
                            }
                            aria-invalid={validationOn && priceInvalid ? true : undefined}
                            className={`${cellCls} ${
                              validationOn && priceInvalid ? cellClsError : cellClsNormal
                            }`}
                          />
                        </td>
                        <td className="px-3 py-2">
                          {/* issue #5198：同族形态（`sku?.stock || ''` + `parseInt(raw) || 0`）——
                              库存 0（无库存）是合法值，改前敲 "0" 会被清空。
                              issue #5218 #2：`sku?.stock ? sku.stock : null` 同为新形态（0 falsy）⇒ 拆掉。
                              issue #5237：缺 `decimals` ⇒ 取默认 2 位，而库存列口径是
                              `stock NUMERIC(12,1)`（1 位 = 0.1 米粒度）⇒ 输入框邀请了一个后端
                              `StockQuantity.requireOneDecimalOrNull` **必拒**（422）的值 ⇒ 补
                              `decimals={1}`。同排价格格是 `decimals={2}`（对齐 `price DECIMAL(10,2)`）
                              —— 两格**各按自己的列精度**，不互相「顺手统一」。 */}
                          <NumberInput
                            min={0}
                            decimals={1}
                            placeholder="0"
                            value={
                              typeof sku?.stock === 'number' && Number.isFinite(sku.stock) ? sku.stock : null
                            }
                            onChange={(v) =>
                              handleSkuChange(
                                color.id,
                                color.colorName,
                                width,
                                'stock',
                                v ?? 0
                              )
                            }
                            aria-invalid={validationOn && stockInvalid ? true : undefined}
                            className={`${cellCls} ${
                              validationOn && stockInvalid ? cellClsError : cellClsNormal
                            }`}
                          />
                        </td>
                      </tr>
                    )
                  })
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
  /** 标题旁的来源徽标（如 `[图片识别]`，issue #5321） */
  badge?: React.ReactNode
}

function RowSelectorSection({
  title,
  count,
  onAdd,
  canAdd,
  error,
  children,
  badge,
}: RowSelectorSectionProps) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-neutral-700">
          {title}
          <span className="ml-1 text-neutral-400">({count})</span>
          {badge}
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
              ? 'border-neutral-300 text-neutral-500 hover:border-primary-400 hover:text-primary-600'
              : 'border-neutral-200 text-neutral-300 cursor-not-allowed'
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
              className="inline-flex items-center gap-1 px-2 py-1 rounded border border-neutral-200 hover:border-primary-400 hover:bg-primary-50 text-xs transition-colors"
              title={c.name}
            >
              <span
                className="w-3.5 h-3.5 rounded-full border border-neutral-300 flex-shrink-0"
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
            className="w-full px-3 py-2 text-sm rounded border border-neutral-300 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
          />
          <div className="flex items-center gap-2">
            <Button type="button" size="sm" onClick={handleApply} disabled={!text.trim()}>
              添加颜色
            </Button>
            <span className="text-xs text-neutral-400">
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
            : 'border-neutral-300 focus-within:border-primary-500'
        }`}
      >
        {/* 色块触发 popover */}
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="shrink-0 w-9 h-full inline-flex items-center justify-center border-r border-neutral-200 hover:bg-neutral-50 transition-colors"
          title="选择主色"
        >
          {mainColorHex ? (
            <span
              className="w-5 h-5 rounded-sm border border-neutral-200 shadow-inner"
              style={{ backgroundColor: mainColorHex }}
            />
          ) : (
            <span
              className="w-5 h-5 rounded-sm border border-dashed border-neutral-300 bg-[conic-gradient(from_45deg,#f87171,#fbbf24,#34d399,#60a5fa,#a78bfa,#f87171)]"
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
          className="absolute z-30 mt-1 left-0 w-[280px] rounded-lg border border-neutral-200 bg-white shadow-lg p-3"
          role="dialog"
          aria-label="选择主色"
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-neutral-500">选择主色（选择后可编辑名称）</span>
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
                  className="flex flex-col items-center gap-1 p-1 rounded hover:bg-neutral-50 transition-colors"
                  title={`${c.name} ${c.hex}`}
                >
                  <span
                    className={`relative w-8 h-8 rounded border ${
                      c.hex.toUpperCase() === '#FFFFFF'
                        ? 'border-neutral-300'
                        : 'border-neutral-200'
                    } shadow-inner`}
                    style={{ backgroundColor: c.hex }}
                  >
                    {selected && (
                      <Check
                        className={`absolute inset-0 m-auto w-4 h-4 ${
                          ['#FFFFFF', '#FFFDD0', '#FFFF00', '#FFC0CB', '#00FFFF', '#C0C0C0', '#C3B091'].includes(
                            c.hex.toUpperCase()
                          )
                            ? 'text-neutral-700'
                            : 'text-white'
                        }`}
                      />
                    )}
                  </span>
                  <span className="text-[11px] text-neutral-600 leading-none">{c.name}</span>
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
