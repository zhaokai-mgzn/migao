import { describe, it, expect } from 'vitest'
import { sanitizeHtml } from '@/lib/sanitize-html'

describe('sanitizeHtml（DOMPurify 白名单消毒）', () => {
  it('移除 <script> 标签', () => {
    const out = sanitizeHtml('<p>hi</p><script>alert(1)</script>')
    expect(out).not.toContain('<script')
    expect(out).not.toContain('alert(1)')
  })

  it('移除 <iframe> 标签', () => {
    const out = sanitizeHtml('<p>hi</p><iframe src="https://evil.com"></iframe>')
    expect(out).not.toContain('<iframe')
  })

  it('移除事件处理器（含未加引号变体）', () => {
    const quoted = sanitizeHtml('<img src="x" onerror="alert(1)">')
    const unquoted = sanitizeHtml('<img src=x onerror=alert(1)>')
    expect(quoted).not.toContain('onerror')
    expect(unquoted).not.toContain('onerror')
  })

  it('移除 javascript: 伪协议链接', () => {
    const out = sanitizeHtml('<a href="javascript:alert(1)">click</a>')
    expect(out).not.toContain('javascript:')
  })

  it('移除 <svg onload> 向量', () => {
    const out = sanitizeHtml('<svg onload="alert(1)"></svg>')
    expect(out).not.toContain('<svg')
    expect(out).not.toContain('onload')
  })

  it('保留编辑器会产出的合法富文本', () => {
    const out = sanitizeHtml(
      '<h2>标题</h2><p><strong>加粗</strong> 正文 <a href="https://migaozn.com" target="_blank" rel="noopener noreferrer">链接</a></p><img src="https://oss.example.com/a.jpg" alt="图" style="max-width:100%;" />',
    )
    expect(out).toContain('<h2>标题</h2>')
    expect(out).toContain('<strong>加粗</strong>')
    expect(out).toContain('href="https://migaozn.com"')
    expect(out).toContain('src="https://oss.example.com/a.jpg"')
  })
})
