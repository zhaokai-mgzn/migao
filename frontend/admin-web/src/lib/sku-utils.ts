/**
 * SKU 矩阵工具函数
 *
 * 从 SkuMatrix.tsx 提取的纯业务逻辑，不依赖 React/组件。
 */

import type { ProductColor, ProductSku, SellingMethod } from '@/types'

/**
 * 门幅选项（issue #3621：「值 / 显示」分离）。
 *
 * - `value` 用 canonical 裸数值（与库内 `product_skus.door_width` 一致：种子是 `2.8`）
 *   → 写入侧与库内同口径，匹配不需要容错；
 * - `label` 带单位，商家看到的文案保持「2.8米」不变（业务术语）。
 *
 * 历史数据里同时存在 `2.8米` 与更老的 `门幅2.8米` 写法，回显/匹配一律走
 * {@link normalizeDoorWidth} 双侧归一化，不再出现「同一 Select 两种写法」。
 */
export const DOOR_WIDTH_OPTIONS: { value: string; label: string }[] = [
  { value: '2.8', label: '2.8米' },
  { value: '3.2', label: '3.2米' },
  { value: '3.4', label: '3.4米' },
]

/**
 * 门幅归一化：`'门幅2.8米'` / `'2.8m'` / `' 2.8 '` → `'2.8'`。
 *
 * 只去 legacy「门幅」前缀与「米/m」后缀（含空白），不做数值换算（`2.80` 仍是 `2.80`）。
 * 与后端同一套口径（#3546 `ProductService.normalizeDoorWidth`、
 * #3621 `SkuNotation.normalizeDoorWidth`）。
 */
export function normalizeDoorWidth(raw: string | null | undefined): string {
  if (!raw) return ''
  return raw.trim().replace(/^门幅/, '').replace(/[米mM]$/, '').trim()
}

/**
 * 是否为同一物理门幅（双侧归一化比较，issue #3621）。
 *
 * 两侧写法都归一化后再比 —— 库内 `2.8` 与选项 `2.8米` 等价；
 * 真正不同的门幅（`2.8` vs `3.2`）仍然不等（防归一化过宽把不同 SKU 合并）。
 */
export function sameDoorWidth(a: string | null | undefined, b: string | null | undefined): boolean {
  const na = normalizeDoorWidth(a)
  return na !== '' && na === normalizeDoorWidth(b)
}

/** 门幅展示文案：`'2.8'` → `'2.8米'`（已带单位/门幅前缀的写法原样返回） */
export function formatDoorWidth(value: string | null | undefined): string {
  const v = (value ?? '').trim()
  if (!v) return ''
  return /[米mM]$/.test(v) ? v : `${v}米`
}

/**
 * 规格尺寸下拉选项：canonical 预设选项 + 表单里出现的非预设门幅（历史数据）兜底，
 * 同一物理门幅只产出一个 entry（值 canonical、显示带单位）——保证同一 Select 里
 * 不会同时出现「2.8」与「2.8米」两种写法。
 */
export function doorWidthSelectOptions(
  current: (string | null | undefined)[],
): { value: string; label: string }[] {
  const options = DOOR_WIDTH_OPTIONS.map((o) => ({ ...o }))
  for (const raw of current) {
    const canonical = normalizeDoorWidth(raw)
    if (canonical && !options.some((o) => o.value === canonical)) {
      options.push({ value: canonical, label: formatDoorWidth(raw) })
    }
  }
  return options
}

/**
 * 生成前端临时 ID（颜色 / SKU 行）。
 *
 * P0-1 契约修复：此前用 `String(-(Date.now() + Math.random()))` 产出
 * "-1788388811825.4893" 这类【浮点】字符串，而后端
 * `ProductColorInput.id` / `ProductSkuInput.id` 均为 `Long`，
 * Jackson 反序列化失败 → POST /api/admin/products 恒 400
 * 「请求体格式错误或缺失」，商家 UI 无法新建任何商品。
 *
 * 现改为模块级【单调递减整数】计数器：
 * - 始终为纯整数字符串（可被 Long 解析）
 * - 会话内唯一（不复用、不撞色），后端颜色→DB id 映射依赖该唯一性
 * - 保持负数语义（后端以负数判定"待落库的新增行"，见 ProductColorInput 注释）
 */
let tempIdCounter = 0

/** @returns 单调递减的纯整数字符串临时 id（如 "-1"、"-2"、…） */
export function nextTempId(): string {
  tempIdCounter -= 1
  return String(tempIdCounter)
}

/**
 * 根据颜色 × 售卖方式 × 门幅 三维矩阵重建 SKU 列表。
 *
 * 规则：
 * 1. 过滤空字符串（sellingMethods / doorWidths 中的占位值）
 * 2. 对每个 color × method × width 组合，尝试匹配已有 SKU
 * 3. 匹配成功 → 保留已有数据（price/stock/skuCode 等），更新 colorName
 * 4. 匹配失败 → 创建新 SKU（price=0, stock=0）
 * 5. 匹配逻辑：优先 colorId，兜底 colorName（兼容旧数据 colorId=null）
 * 6. 门幅匹配走 {@link sameDoorWidth} 双侧归一化（issue #3621）：
 *    `2.8` / `2.8米` / `门幅2.8米` 视为同一物理门幅（不再因写法差异生成第二个组合行），
 *    真正不同的门幅（`2.8` vs `3.2`）仍不匹配
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
        const found = existing.find((s) => {
          // 优先 colorId 匹配（旧数据），兜底 colorName 匹配（新数据 colorId 可能为 null）
          const idMatch = s.colorId != null && s.colorId === color.id
          const nameMatch = s.colorName === color.colorName
          return (
            (idMatch || (s.colorId == null && nameMatch)) &&
            s.sellingMethod === method &&
            sameDoorWidth(s.doorWidth, width)
          )
        })

        if (found) {
          result.push({ ...found, colorName: color.colorName })
        } else {
          result.push({
            id: nextTempId(),
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
