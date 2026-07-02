/**
 * 商品表单工具函数
 *
 * 从 ProductForm.tsx 提取的纯业务逻辑，不依赖 React/组件。
 */

import type { ProductFormData, ProductSku, ProductStatus } from '@/types'

const TITLE_MAX = 60

/**
 * 校验商品表单数据。
 *
 * @param form         - 表单数据
 * @param targetStatus - 目标提交状态（draft 只校验 title）
 * @returns 字段→错误消息的 map，空对象表示全部通过
 */
export function validateProductForm(
  form: ProductFormData,
  targetStatus: ProductStatus,
): Record<string, string> {
  const errs: Record<string, string> = {}
  const isDraft = targetStatus === 'draft'

  // ─── 所有状态都校验 title ───
  if (!form.name.trim()) {
    errs.name = '请输入商品标题'
  } else if (form.name.length > TITLE_MAX) {
    errs.name = `标题不超过 ${TITLE_MAX} 字`
  }

  if (!isDraft) {
    // ─── 货号 ───
    if (!form.skuCode || !form.skuCode.trim()) {
      errs.skuCode = '请输入货号'
    } else if (form.skuCode.length > 30) {
      errs.skuCode = '货号不超过 30 字'
    }

    // ─── 必填项 ───
    if (!form.unit) errs.unit = '请选择计价单位'
    if (!form.categoryId) errs.categoryId = '请选择商品分类'
    if (!form.images || form.images.length === 0) {
      errs.images = '请至少上传 1 张商品主图'
    }

    // ─── 颜色 ───
    if (!form.colors || form.colors.length === 0) {
      errs.colors = '请至少添加 1 种颜色'
    } else {
      const incomplete = form.colors.find(
        (c) => !c.colorName || !c.colorName.trim(),
      )
      if (incomplete) errs.colors = '颜色必须填写名称'
    }

    // ─── 售卖方式 / 门幅 ───
    if (
      !form.sellingMethods ||
      form.sellingMethods.filter(Boolean).length === 0
    ) {
      errs.sellingMethods = '请至少添加 1 种售卖方式'
    }
    if (
      !form.doorWidths ||
      form.doorWidths.filter(Boolean).length === 0
    ) {
      errs.doorWidths = '请至少添加 1 种规格尺寸'
    }

    // ─── SKU 完整性 ───
    if (
      form.colors &&
      form.colors.length > 0 &&
      form.sellingMethods &&
      form.sellingMethods.filter(Boolean).length > 0 &&
      form.doorWidths &&
      form.doorWidths.filter(Boolean).length > 0
    ) {
      const totalCells =
        form.colors.length *
        form.sellingMethods.filter(Boolean).length *
        form.doorWidths.filter(Boolean).length
      const list = form.skus || []
      const filled = list.filter(
        (s) => Number(s.price) > 0 && Number(s.stock) >= 0,
      )
      const allValid =
        list.length >= totalCells &&
        list.every((s) => Number(s.price) > 0 && Number(s.stock) >= 0)
      if (!allValid || filled.length < totalCells) {
        errs.skus = '请完整填写所有 SKU 的价格与库存'
      }
    }

    // ─── 加工项 ───
    if (form.supportsProcessing) {
      const cfg = form.processingItemConfigs || []
      if (
        cfg.length === 0 ||
        cfg.some((c) => !c.processingItemId || c.customPrice < 0)
      ) {
        errs.processingItemConfigs = '请至少配置 1 项加工项并填写价格'
      }
    }
  }

  return errs
}

/**
 * 从 SKU 列表中推导商品最低售价。
 *
 * @param skus        - SKU 列表
 * @param fallbackPrice - 无可计算 SKU 时的兜底价格
 * @returns 最低正价格
 */
export function derivePrice(skus: ProductSku[], fallbackPrice: number): number {
  if (skus.length === 0) return fallbackPrice
  const positive = skus.map((s) => Number(s.price)).filter((p) => p > 0)
  if (positive.length === 0) return fallbackPrice
  return Math.min(...positive)
}
