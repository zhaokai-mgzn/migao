// case_ids: PR-008
/**
 * RichTextEditor 组件测试
 * 覆盖：#563 — 工具栏渲染、编辑区渲染、placeholder
 */
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
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

describe('RichTextEditor 工具栏（#5105 真缺陷回归锁）', () => {
  // jsdom 不实现 execCommand / queryCommandState（组件依赖浏览器 legacy API），补最小 stub。
  const execCommand = vi.fn(() => true)
  beforeEach(() => {
    execCommand.mockClear()
    Object.defineProperty(document, 'execCommand', { value: execCommand, configurable: true, writable: true })
    Object.defineProperty(document, 'queryCommandState', { value: () => false, configurable: true, writable: true })
    Object.defineProperty(document, 'queryCommandValue', { value: () => 'p', configurable: true, writable: true })
  })

  // 缺陷形态：`buttons` 数组里塞了会读 editorRef 的闭包（插入链接/插入图片），
  // 数组因此在渲染期带上「可能读 ref」的类型 ⇒ `react-hooks/refs` 判 `buttons.map(...)`
  // 为「渲染期读 ref」。修法：数组只存纯数据，需要 ref 的两个动作在 onClick 里按 key 分发。
  // 这两条钉住修完后的对外行为：按钮齐全 + 点击确实作用到 contentEditable 编辑区。
  it('工具栏按钮齐全（含插入链接/插入图片两个自定义动作）', () => {
    render(<RichTextEditor value="" onChange={vi.fn()} />)
    for (const title of ['插入链接', '插入图片', '加粗', '斜体', '下划线', '撤销', '重做']) {
      expect(screen.getByTitle(title)).toBeInTheDocument()
    }
  })

  it('点击「插入链接」非法 URL → 不执行 execCommand（负向：校验挡住）', () => {
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('ftp://nope')
    try {
      render(<RichTextEditor value="" onChange={vi.fn()} />)
      fireEvent.click(screen.getByTitle('插入链接'))
      expect(promptSpy).toHaveBeenCalled()
      expect(execCommand).not.toHaveBeenCalled()
    } finally {
      promptSpy.mockRestore()
    }
  })

  it('点击「插入链接」合法 URL → 插入 <a>（正向：动作确实被分发到编辑器）', () => {
    // jsdom 无选区 ⇒ selectedText 为空 ⇒ 组件走 insertHTML 分支
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('https://example.com')
    try {
      render(<RichTextEditor value="" onChange={vi.fn()} />)
      fireEvent.click(screen.getByTitle('插入链接'))
      expect(execCommand).toHaveBeenCalledWith(
        'insertHTML',
        false,
        '<a href="https://example.com" target="_blank" rel="noopener noreferrer">https://example.com</a>',
      )
    } finally {
      promptSpy.mockRestore()
    }
  })

  it('点击工具栏命令按钮（加粗）→ 走 exec（命令分发未被自定义动作改写破坏）', () => {
    render(<RichTextEditor value="" onChange={vi.fn()} />)
    fireEvent.click(screen.getByTitle('加粗'))
    expect(execCommand).toHaveBeenCalledWith('bold', false, undefined)
  })
})
