// 报表导出（issue #7376 段 5）：CSV 是本仓 SQL 视图可得的**最小**导出形态（Excel 双向迁移按 P2 另做）。
//
// 三条口径：
// 1. **数值原样**：金额/数量不在这里加千分位或货币符号 —— CSV 进 Excel 后要能直接求和；
// 2. **缺值留空**（不是 0）：`null`/`undefined` 一律空单元格，与页面「—」同义；
// 3. **含逗号/引号/换行的字段必须加引号**（双引号自转义），否则 Excel 打开就错列。

export type CsvCell = string | number | null | undefined

/** 转义单个单元格（RFC 4180：含 `,` `"` `\n` `\r` 才加引号，内部 `"` 翻倍）。 */
function cell(value: CsvCell): string {
  if (value === null || value === undefined) return ''
  const text = String(value)
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

/**
 * 生成 CSV 文本（含 UTF-8 BOM —— 不带 BOM 时 Excel 会把中文读成乱码）。
 *
 * @param headers 表头（逐字上屏，走中文，不摆内部字段名）
 * @param rows    数据行；`null` 值留空
 */
export function toCsv(headers: string[], rows: CsvCell[][]): string {
  const lines = [headers.map(cell).join(','), ...rows.map((row) => row.map(cell).join(','))]
  return `\uFEFF${lines.join('\r\n')}\r\n`
}

/** 触发浏览器下载（测试里把 `URL.createObjectURL` mock 掉即可断言内容）。 */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
