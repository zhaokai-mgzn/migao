// case_ids: RPT-005
import { describe, expect, it } from 'vitest'
import { toCsv } from '@/lib/csv'

/**
 * CSV 导出（issue #7376 段 5）。
 *
 * 为什么单独测：页面用例走 `Blob.text()`，而 jsdom 的 Blob **会吃掉 UTF-8 BOM** ——
 * 把 BOM 断言塞进页面用例只能靠 mock 自证，那是假绿。这里直接对 `toCsv()` 的字符串断言。
 */
describe('toCsv', () => {
  it('带 UTF-8 BOM（不带 BOM 时 Excel 把中文读成乱码）+ CRLF 行尾', () => {
    const csv = toCsv(['客户', '应收'], [['张记布艺', 1200]])
    expect(csv.charCodeAt(0)).toBe(0xfeff)
    expect(csv).toContain('客户,应收\r\n张记布艺,1200\r\n')
  })

  it('缺值留空（不是 0）：null / undefined ⇒ 空单元格', () => {
    const csv = toCsv(['应收', '逾期'], [[1200, null], [undefined, 0]])
    expect(csv).toContain('1200,\r\n')
    // 🔴 真 0 照实写 0（「缺值」与「零」两个结论，不许混）
    expect(csv).toContain(',0\r\n')
  })

  it('含逗号 / 引号 / 换行的字段加引号，内部引号翻倍（RFC 4180）', () => {
    const csv = toCsv(['备注'], [['客户说"下周付"，先记账'], ['第一行\n第二行']])
    expect(csv).toContain('"客户说""下周付""，先记账"')
    expect(csv).toContain('"第一行\n第二行"')
  })
})
