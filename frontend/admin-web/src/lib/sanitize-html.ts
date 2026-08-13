import DOMPurify from 'dompurify'

/**
 * 富文本 HTML 消毒（防 XSS）
 *
 * 商品描述由 RichTextEditor 产出，再经 dangerouslySetInnerHTML 渲染。
 * 此前用正则清洗（移除 script/iframe/on*），可被未加引号的事件处理器、
 * 实体编码的 javascript:、<svg onload> 等绕过，构成存储型 XSS。
 *
 * 现改为 DOMPurify 白名单消毒：仅放行编辑器实际会产出的标签/属性，
 * script/iframe/style/事件处理器/javascript: 等一律被剔除。
 */
const ALLOWED_TAGS = [
  'p', 'br', 'div', 'span',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'strong', 'b', 'em', 'i', 'u', 's',
  'ul', 'ol', 'li',
  'a', 'img',
  'blockquote', 'code', 'pre',
]

const ALLOWED_ATTR = [
  'href', 'src', 'alt', 'title', 'target', 'rel',
  'style', 'width', 'height',
]

export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
  })
}
