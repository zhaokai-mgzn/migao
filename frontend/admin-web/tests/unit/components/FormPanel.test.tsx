// case_ids: UI-122
/**
 * `FormPanel` / `FormGrid` / `Field` / `FIELD_CONTROL` —— 配置面字段的**唯一版式原语**（issue #7176）。
 *
 * 判据 = 形态本身：区块是浅底面板 + `text-sm font-semibold` 标题 + `text-xs` 说明；
 * 字段是**标签在上**（`text-xs`、且 `htmlFor` 真关联）、控件满列、单位做**框内后缀**；
 * 栅格有列定义与统一间距。
 * 类级守卫（**谁能用哪套写法**：业务面自拼控件铬 / 标签顺排控件 ⇒ 红）在
 * `frontend/admin-web/tests/unit/design-system-form-fields.test.tsx`。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import FormPanel, { FIELD_CONTROL, Field, FormGrid, fieldControl } from '../../../src/components/ui/FormPanel'

describe('FormPanel / FormGrid / Field（issue #7176）', () => {
  it('原语形态：面板 = 浅底 + 标题；字段 = 标签在上 + 单位做框内后缀；栅格 = 统一间距', () => {
    const { container } = render(
      <FormPanel title="阈值试算" hint="一句说明" testid="ds-panel">
        <FormGrid cols={4} testid="ds-grid">
          <Field label="试算窗宽" unit="米" htmlFor="ds-a">
            <input id="ds-a" data-testid="ds-input" />
          </Field>
        </FormGrid>
      </FormPanel>,
    )
    const panel = screen.getByTestId('ds-panel')
    expect(panel.tagName).toBe('SECTION')
    expect(panel.className, '浅底面板').toContain('bg-neutral-50/50')
    expect(panel.className, '圆角 + 边框').toContain('rounded-lg')
    expect(panel.className, '内边距与「阈值试算」一致').toContain('p-4')
    const heading = container.querySelector('h4') as HTMLElement
    expect(heading.textContent).toBe('阈值试算')
    expect(heading.className, '区块标题 = text-sm font-semibold').toContain('text-sm font-semibold')
    expect(panel.textContent).toContain('一句说明')

    const grid = screen.getByTestId('ds-grid')
    expect(grid.className, '栅格').toContain('grid')
    expect(grid.className, '四列').toContain('sm:grid-cols-4')
    expect(grid.className, '统一间距').toContain('gap-3')

    const field = screen.getByTestId('ds-input').closest('div.min-w-0') as HTMLElement
    const label = field.querySelector('label') as HTMLElement
    expect(label.textContent, '标签在上').toBe('试算窗宽')
    expect(label.className).toContain('text-xs')
    expect(label.getAttribute('for'), '标签与控件**真关联**').toBe('ds-a')
    expect(field.textContent, '单位做框内后缀').toContain('米')
    expect(screen.getByTestId('ds-input')).toHaveAttribute('id', 'ds-a')
    expect(fieldControl('米'), '带单位时留出单位位').toContain('pr-9')
  })
})
