// case_ids: UI-148
//
// WebView 83 兜底：Chrome 83 **没有** flex `gap`（Chromium 84 才给 flexbox 加）。
//
// 真机读数（2026-11-01）—— 商米 V2s / `Chrome 83.0.4103.120`：
//   `裁剪 应做 1.00 米0.25 元/米待报工`  ← `gap: 4px 12px` 被静默忽略 ⇒ 三列挤成一串
//   （同一份 CSS 在 PC / 手机 Chrome ≥84 上正常 ⇒ 单测与截图回归都绿，只有手持机现形）。
//
// 做法：**先量一次真布局**，量到「gap 没生效」才给 `<html>` 加 `.no-flex-gap`，
// 样式表里同名作用域下的 margin 兜底才生效；现代浏览器不加类 ⇒ 视觉零变化、不叠两层间距。
//
// 🔴 为什么不用 `@supports (gap: 1px)`：Chrome 83 认得 `gap` 这个**属性**（grid 用），
//    所以 `@supports` 判为「支持」，但 flex 容器上照样不生效 —— 判据会假绿。
// 🔴 grid 的 `gap` 自 Chrome 57 就支持，**不需要**兜底（本文件也不碰 grid 规则）。

/** `<html>` 上的兜底开关类名（与 `styles.css` 里的作用域逐字一致）。 */
export const NO_FLEX_GAP = 'no-flex-gap'

/**
 * 当前文档**真的**用上了 flex `gap` 吗？
 *
 * 用「两个 10px 子项 + 10px 间距，容器宽度应 ≈ 30px」量一次：
 * 量到 ≈20px ⇒ gap 被忽略（Chrome 83）；量到 ≈30px ⇒ 支持。
 *
 * @returns {boolean} `true` = 支持（**不做任何兜底**）。测不出来时也返回 `true`：
 *   宁可在不支持的浏览器上保持原样，也不在正常浏览器上叠加两层间距（那会让 PC 端回退）。
 */
export function detectsFlexGap(doc, { probeSize = 10, gap = 10 } = {}) {
  if (!doc || typeof doc.createElement !== 'function' || !doc.body) return true
  let probe = null
  try {
    probe = doc.createElement('div')
    probe.style.display = 'flex'
    probe.style.gap = `${gap}px`
    probe.style.position = 'absolute'
    probe.style.left = '-9999px'
    probe.style.top = '0'
    probe.style.visibility = 'hidden'
    for (let i = 0; i < 2; i += 1) {
      const cell = doc.createElement('div')
      cell.style.width = `${probeSize}px`
      cell.style.height = '1px'
      cell.style.flex = '0 0 auto'
      probe.appendChild(cell)
    }
    doc.body.appendChild(probe)
    const width = typeof probe.getBoundingClientRect === 'function'
      ? probe.getBoundingClientRect().width
      : NaN
    if (!Number.isFinite(width)) return true
    return width >= probeSize * 2 + gap - 0.5
  } catch (e) {
    return true
  } finally {
    try {
      if (probe && probe.parentNode) probe.parentNode.removeChild(probe)
    } catch (e) {
      /* 探测节点清不掉也不影响页面（绝对定位、视口外、不可见） */
    }
  }
}

/**
 * 装兜底：不支持 flex `gap` ⇒ 给 `<html>` 加 {@link NO_FLEX_GAP}。
 *
 * @returns {boolean} 同 {@link detectsFlexGap}（`true` = 支持，未加类）
 */
export function installFlexGapFallback(doc) {
  if (!doc || !doc.documentElement) return true
  const supported = detectsFlexGap(doc)
  if (!supported) {
    try {
      doc.documentElement.classList.add(NO_FLEX_GAP)
    } catch (e) {
      /* classList 不可用（极端旧内核）⇒ 保持原样，页面仍可读 */
    }
  }
  return supported
}
