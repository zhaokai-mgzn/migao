/**
 * RichTextEditor 组件测试
 * 覆盖：#563 — 工具栏渲染、编辑区渲染、placeholder
 */
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import RichTextEditor from '@/components/products/RichTextEditor'

// Mock @/lib/utils
vi.mock('@/lib/utils', () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(' '),
  resolveImageUrl: (url: string) => url,
}))

// Mock @/lib/api
vi.mock('@/lib/api', () => ({
  fileApi: {
    uploadFile: vi.fn(),
  },
}))

describe('RichTextEditor (#563)', () => {
  it('渲染编辑区域', () => {
    render(<RichTextEditor value="" onChange={vi.fn()} />)
    const editor = document.querySelector('[contentEditable]')
    expect(editor).toBeTruthy()
  })

  it('渲染默认 placeholder', () => {
    render(<RichTextEditor value="" onChange={vi.fn()} />)
    const editor = document.querySelector('[contenteditable]')
    expect(editor?.getAttribute('data-placeholder')).toBe('请输入内容...')
  })

  it('支持自定义 placeholder', () => {
    render(
      <RichTextEditor
        value=""
        onChange={vi.fn()}
        placeholder="请输入商品描述"
      />
    )
    const editor = document.querySelector('[contenteditable]')
    expect(editor?.getAttribute('data-placeholder')).toBe('请输入商品描述')
  })

  it('显示工具栏按钮（加粗/斜体/下划线）', () => {
    render(<RichTextEditor value="" onChange={vi.fn()} />)
    // toolbar buttons should render (mocked lucide icons as spans)
    const toolbar = document.querySelector('.rich-text-editor')
    expect(toolbar).toBeTruthy()
    // Check that toolbar exists and contains buttons
    const buttons = toolbar?.querySelectorAll('button')
    expect(buttons).toBeTruthy()
    expect(buttons!.length).toBeGreaterThan(0)
  })

  it('显示初始 HTML 内容', () => {
    render(
      <RichTextEditor
        value="<p>Hello World</p>"
        onChange={vi.fn()}
      />
    )
    const editor = document.querySelector('[contenteditable]')
    expect(editor?.innerHTML).toBe('<p>Hello World</p>')
  })

  it('支持自定义 minHeight', () => {
    render(
      <RichTextEditor
        value=""
        onChange={vi.fn()}
        minHeight={400}
      />
    )
    const editor = document.querySelector('[contenteditable]')
    expect(editor?.getAttribute('style')).toContain('min-height: 400px')
  })
})
