/**
 * SKU 矩阵工具函数
 *
 * 从 SkuMatrix.tsx 提取的纯业务逻辑，不依赖 React/组件。
 */

import type { ProductColor, ProductSku, SellingMethod } from '@/types'

/**
 * 根据颜色 × 售卖方式 × 门幅 三维矩阵重建 SKU 列表。
 *
 * 规则：
 * 1. 过滤空字符串（sellingMethods / doorWidths 中的占位值）
 * 2. 对每个 color × method × width 组合，尝试匹配已有 SKU
 * 3. 匹配成功 → 保留已有数据（price/stock/skuCode 等），更新 colorName
 * 4. 匹配失败 → 创建新 SKU（price=0, stock=0）
 * 5. 匹配逻辑：优先 colorId，兜底 colorName（兼容旧数据 colorId=null）
 * 6. 门幅兼容旧格式 "门幅2.8米" ↔ "2.8米"
 *
 * @param colors      - 当前颜色列表
 * @param methods     - 当前售卖方式列表（可能含空占位）
 * @param widths      - 当前门幅列表（可能含空占位）
 * @param existing    - 已有 SKU 列表
 * @returns 重建后的 SKU 列表
 */
export function rebuildSkus(
  colors: ProductColor[],
  methods: SellingMethod[],
  widths: string[],
  existing: ProductSku[],
): ProductSku[] {
  // 过滤空占位值，避免生成无效 SKU
  const validMethods = methods.filter((m) => !!m)
  const validWidths = widths.filter((w) => !!w)

  const result: ProductSku[] = []
  for (const color of colors) {
    for (const method of validMethods) {
      for (const width of validWidths) {
        // 兼容旧格式'门幅2.8米'和新格式'2.8米'
        const matchWidth = (db: string, opt: string) =>
          db === opt || db.replace(/^门幅/, '') === opt

        const found = existing.find((s) => {
          // 优先 colorId 匹配（旧数据），兜底 colorName 匹配（新数据 colorId 可能为 null）
          const idMatch = s.colorId != null && s.colorId === color.id
          const nameMatch = s.colorName === color.colorName
          return (
            (idMatch || (s.colorId == null && nameMatch)) &&
            s.sellingMethod === method &&
            matchWidth(s.doorWidth || '', width)
          )
        })

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
