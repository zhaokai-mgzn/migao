'use client'

/**
 * 把**单据 DOM** 截成 PNG（issue #5914 的功能④：点「复制截图」⇒ 单据落到剪贴板）。
 *
 * ## 为什么自己写（而不是引一个截图库）
 *
 * 走的是**浏览器原生**那条路，零依赖：
 * 计算样式内联 → `SVG foreignObject` → `<img>` → `canvas` → PNG blob。
 * 单据的样式面很窄（边框 / 文字 / 内联 SVG 二维码 / 圆角），不值得为它引一个通用库
 * （`docs/wiki/Code-Minimalism.md` 的最少代码阶梯：原生特性优先于新增依赖）。
 *
 * ## 三个必须显式处理的坑（都踩过，写在判据里）
 *
 * 1. **外链 CSS 在 `foreignObject` 里不生效** ⇒ 逐元素把 `getComputedStyle` 内联进 `style`；
 * 2. **跨域 `<img>`（如 OSS 上的收款码）在 SVG 图片里不加载** ⇒ 先 fetch 成 dataURL 再塞进去；
 *    取不到就**如实计数并上屏提示**，不静默丢图（`skippedImages`）；
 * 3. **被 `transform: scale()` 缩放的预览里，`getBoundingClientRect()` 是缩放后的值** ⇒
 *    尺寸一律取 `offsetWidth/offsetHeight`（布局尺寸，不受祖先 transform 影响）。
 */

/** 截图结果：`skippedImages > 0` ⇒ 有图没进截图（调用方**必须**把它说出来） */
export interface CaptureResult {
  blob: Blob
  /** 取不到的图片数（跨域 / 加载失败）—— 不静默：调用方要提示 */
  skippedImages: number
}

export interface CaptureOptions {
  /** 放大倍数（默认 3 ≈ 288dpi，够打印/微信看清小字） */
  scale?: number
  /** 底色（默认白；单据是纯边框无底色，白底才对） */
  background?: string
}

/** 不该被内联的属性（对静态截图没有意义，且会把体积撑大） */
const SKIP_PROPERTIES = new Set(['cursor', 'pointer-events', 'transition', 'animation', 'will-change'])

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error('图片转 dataURL 失败'))
    reader.readAsDataURL(blob)
  })
}

/** 递归把**计算样式**写进克隆体的 `style`（`foreignObject` 里外链 CSS 不生效） */
function inlineComputedStyles(source: Element, clone: Element): void {
  if (!(clone instanceof HTMLElement) || !(source instanceof Element)) return
  const computed = window.getComputedStyle(source)
  let css = ''
  for (let i = 0; i < computed.length; i += 1) {
    const name = computed[i]
    if (SKIP_PROPERTIES.has(name)) continue
    const value = computed.getPropertyValue(name)
    if (!value) continue
    css += `${name}:${value};`
  }
  clone.style.cssText = css
  const sourceChildren = source.children
  const cloneChildren = clone.children
  for (let i = 0; i < sourceChildren.length && i < cloneChildren.length; i += 1) {
    inlineComputedStyles(sourceChildren[i], cloneChildren[i])
  }
}

/** 把跨域图片换成 dataURL；取不到就计数返回（不抛错 —— 少一张图不该拦掉整张截图） */
async function inlineImages(source: Element, clone: Element): Promise<number> {
  const sourceImages = Array.from(source.querySelectorAll('img'))
  const cloneImages = Array.from(clone.querySelectorAll('img'))
  let skipped = 0
  await Promise.all(
    sourceImages.map(async (image, index) => {
      const target = cloneImages[index]
      if (!target) return
      const src = image.getAttribute('src') || ''
      if (src === '' || src.startsWith('data:')) return
      try {
        const response = await fetch(src, { credentials: 'include' })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        target.setAttribute('src', await blobToDataUrl(await response.blob()))
      } catch {
        skipped += 1
      }
    })
  )
  return skipped
}

/**
 * 把一个 DOM 节点截成 PNG。节点必须**已经在版面上**（有布局尺寸）——
 * `display: none` 的节点量不出尺寸，那是调用方的责任（预览层保证它是可见的）。
 */
export async function captureNodeToPngBlob(node: HTMLElement, options: CaptureOptions = {}): Promise<CaptureResult> {
  const scale = options.scale ?? 3
  const background = options.background ?? '#ffffff'
  // 🔴 尺寸取 offsetWidth/Height：预览里节点被 scale 包着，rect 是缩放后的值
  const width = node.offsetWidth
  const height = node.offsetHeight
  if (width === 0 || height === 0) {
    throw new Error('单据尺寸为 0 —— 截图前必须先把单据渲染出来（预览层可见时才截）')
  }

  const clone = node.cloneNode(true) as HTMLElement
  inlineComputedStyles(node, clone)
  const skippedImages = await inlineImages(node, clone)

  // 字体没就绪就截图 ⇒ 截图里会用回退字体（纸面与截图不一致）
  if (document.fonts?.ready) await document.fonts.ready

  const serialized = new XMLSerializer().serializeToString(clone)
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" ` +
    `viewBox="0 0 ${width} ${height}">` +
    `<foreignObject x="0" y="0" width="${width}" height="${height}">` +
    `<div xmlns="http://www.w3.org/1999/xhtml">${serialized}</div>` +
    `</foreignObject></svg>`

  const image = new Image()
  image.decoding = 'sync'
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve()
    image.onerror = () => reject(new Error('单据渲染成图片失败（SVG foreignObject）'))
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  })

  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(width * scale))
  canvas.height = Math.max(1, Math.round(height * scale))
  const context = canvas.getContext('2d')
  if (!context) throw new Error('浏览器不支持 canvas（无法导出截图）')
  context.fillStyle = background
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(image, 0, 0, canvas.width, canvas.height)

  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'))
  if (!blob) throw new Error('导出 PNG 失败')
  return { blob, skippedImages }
}

/**
 * 把 PNG 写进剪贴板。**返回 `false` = 这条路走不通**（非安全上下文 / 无权限 / 浏览器不支持），
 * 调用方必须给降级出口（下载），不许静默失败。
 */
export async function copyPngToClipboard(blob: Blob): Promise<boolean> {
  if (typeof ClipboardItem === 'undefined') return false
  if (!navigator.clipboard || typeof navigator.clipboard.write !== 'function') return false
  try {
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
    return true
  } catch {
    return false
  }
}

/** 降级出口：下载 PNG（剪贴板不可用时用） */
export function downloadPng(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  // 立刻 revoke 会让部分浏览器来不及取流 ⇒ 下一轮事件循环再释放
  setTimeout(() => URL.revokeObjectURL(url), 0)
}
