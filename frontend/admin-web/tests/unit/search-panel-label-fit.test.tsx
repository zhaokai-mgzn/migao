// case_ids: UI-122
/**
 * 列表页筛选卡片（共享原语 `SearchPanel`）：**标签不许压到控件上**（issue #7238）。
 *
 * ## 病灶（2026-10-18 用户截图 + 逐字「PC端的小问题一起修复掉，这里太紧凑了」）
 *
 * 截图里的红框 = 「姓名/手机号」标签与它的输入框几乎贴在一起。归因（读 `SearchPanel.tsx`）：
 * 标签是**定宽** `w-[4.5em]`（4.5 个字号 = 4 个中文字；注释里写明是为「下单时间」这类 4 字标签对齐用的），
 * 而「姓名/手机号」是 **5 个字符** + `whitespace-nowrap` + `shrink-0` ⇒ 文字**溢出**定宽盒，
 * 把控件左边那 8px 间隙吃掉 ⇒ 看上去标签贴着输入框（页面上不止员工页：任何 5 字标签都这样）。
 *
 * ## 修法（改原语，不改页面 —— `docs/design/ui-button-standard.md` §4）
 *
 * 定宽只作**下限**：`w-[4.5em] min-w-fit` ⇒ 常见 4 字标签照旧对齐，长标签**把控件推出去**而不是压上去；
 * 标签与控件之间的间隙同时提到 12px（`gap-3`）。
 *
 * ## 判据形态（会红）与边界
 *
 * jsdom **没有布局引擎** ⇒ 这里钉的是**机制**（决定「定宽能不能溢出」的那几个类），不是几何读数：
 *   ① 标签必须同时有 `w-[4.5em]`（对齐基线）与 `min-w-fit`（可增长）；
 *   ② 标签必须 `whitespace-nowrap` + `shrink-0`（长标签只许把控件推远，不许折行 / 被压扁）；
 *   ③ 标签与控件的间隙 ≥ 12px。
 * 真几何读数在 `frontend/admin-web/scripts/design-baseline-geometry-probe.mjs`（真浏览器/CDP），
 * 本条**不冒充**它 —— 「标签与输入框到底差几个像素」仍由那支探针 + 人读图裁定。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import SearchPanel from '../../src/components/ui/SearchPanel'

const renderPanel = () =>
  render(
    <SearchPanel
      fields={[
        { key: 'keyword', label: '姓名/手机号', control: <input aria-label='关键字' /> },
        { key: 'status', label: '状态', control: <select aria-label='状态' /> },
      ]}
      onSearch={() => {}}
    />,
  )

const labelOf = (text: string) => {
  const el = screen.getByText(text)
  return el as HTMLElement
}

describe('SearchPanel 标签可增长（issue #7238）', () => {
  it('① 长标签（5 字）不会溢出定宽盒：`w-[4.5em]` 只是下限，`min-w-fit` 让它增长', () => {
    renderPanel()
    const long = labelOf('姓名/手机号')
    expect(long.className).toContain('min-w-fit')
    expect(long.className).toContain('w-[4.5em]')
  })

  it('② 标签不折行、不被压缩（只许把控件推远）', () => {
    renderPanel()
    for (const text of ['姓名/手机号', '状态']) {
      const label = labelOf(text)
      expect(label.className).toContain('whitespace-nowrap')
      expect(label.className).toContain('shrink-0')
    }
  })

  it('③ 标签与控件之间留出 ≥12px 空隙（`gap-3`；改前 8px 被 5 字标签吃掉）', () => {
    renderPanel()
    const row = labelOf('姓名/手机号').parentElement as HTMLElement
    expect(row.className).toContain('gap-3')
    expect(row.className).not.toContain('gap-2 ')
  })
})
