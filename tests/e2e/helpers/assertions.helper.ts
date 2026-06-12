/**
 * 反占位符断言 — 检测数据列不应该全是占位符（如 '-'）
 *
 * 用途: 发现前后端字段不同步导致的数据未渲染问题。
 *       例如后端 DTO 缺字段 → 前端读不到 → 所有行显示 '-'
 *       这个断言会在 E2E 中主动暴露这类 bug。
 */

import { type Page } from '@playwright/test'

export interface AntiPlaceholderOptions {
  /** 表格/列表的行选择器 */
  rowSelector?: string
  /** 需要检查的列：列标题 → 列内选择器 */
  columns: Record<string, string>
  /** 占位符值（默认 '-'） */
  fallbackValue?: string
  /** 最小行数，少于这个数跳过检查（空列表不报警） */
  minRows?: number
}

/**
 * 断言指定列的所有行都不全是占位符。
 *
 * 检查逻辑: 如果列中 ALL 可见行都显示 fallbackValue → 断言失败。
 *          如果至少有一行显示了非 fallbackValue → 通过。
 */
export async function assertNoPlaceholderFallback(
  page: Page,
  options: AntiPlaceholderOptions,
): Promise<void> {
  const {
    rowSelector = 'tbody tr',
    columns,
    fallbackValue = '-',
    minRows = 1,
  } = options

  const rows = page.locator(rowSelector)
  const rowCount = await rows.count()

  if (rowCount < minRows) {
    console.log(`[assertNoPlaceholderFallback] 仅 ${rowCount} 行，跳过检查（minRows=${minRows}）`)
    return
  }

  for (const [colName, cellSelector] of Object.entries(columns)) {
    const cells = page.locator(`${rowSelector} ${cellSelector}`)
    const cellCount = await cells.count()

    if (cellCount === 0) {
      console.warn(`[assertNoPlaceholderFallback] 列 "${colName}" 无匹配元素 (${cellSelector})`)
      continue
    }

    // 收集所有可见文本
    const texts: string[] = []
    for (let i = 0; i < cellCount; i++) {
      const text = (await cells.nth(i).textContent())?.trim() || ''
      texts.push(text)
    }

    // 检查是否所有非空文本都等于 fallbackValue
    const nonEmptyTexts = texts.filter((t) => t.length > 0)
    const allPlaceholder = nonEmptyTexts.length > 0 &&
      nonEmptyTexts.every((t) => t === fallbackValue)

    if (allPlaceholder) {
      throw new Error(
        `[反占位符检查] 列 "${colName}" 的 ${nonEmptyTexts.length} 行全部显示占位符 "${fallbackValue}"。` +
        `这通常意味着后端未返回该字段，或前端未正确渲染。` +
        `\n  选择器: ${rowSelector} ${cellSelector}`
      )
    }

    console.log(
      `[assertNoPlaceholderFallback] ✅ 列 "${colName}": ` +
      `${cellCount} 行, ${nonEmptyTexts.length} 非空, ` +
      `占位符 ${fallbackValue}: ${nonEmptyTexts.filter((t) => t === fallbackValue).length} 行`
    )
  }
}
