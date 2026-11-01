// case_ids: UI-148
//
// WebView 83（Chrome 83）没有 flex `gap` ⇒ 工人端间距全塌（issue #8336）。
//
// 真机读数（2026-11-01 / 商米 V2s / Chrome 83.0.4103.120）：
//   `裁剪 应做 1.00 米0.25 元/米待报工` —— 三列挤成一串；页头按钮贴字。
// 本文件只钉**探测与开关**这一段（样式兜底本身在真机截图里验）：
//   ① 量到 20px（两个 10px 子项、没有 10px 间距）⇒ 判为不支持 ⇒ 给 <html> 加 `no-flex-gap`；
//   ② 量到 30px ⇒ 判为支持 ⇒ **不加类**（现代浏览器不许叠两层间距）；
//   ③ 探测节点必须**拆掉**（不留垃圾节点在 body 里）；
//   ④ 量不出宽度（NaN / 没有 getBoundingClientRect）⇒ 当作支持（宁可不兜底，也不误伤 PC）；
//   ⑤ 极端旧内核（没有 body）⇒ 不抛、返回 true。
import test from 'node:test'
import assert from 'node:assert/strict'

import { detectsFlexGap, installFlexGapFallback, NO_FLEX_GAP } from '../src/flex-gap.mjs'

/** 最小假文档：只实现探测用到的那几个 API（宽度由用例注入）。 */
function fakeDoc({ width = Number.NaN, body = true } = {}) {
  const classList = {
    values: new Set(),
    add(c) { this.values.add(c) },
    contains(c) { return this.values.has(c) },
  }
  const makeEl = () => {
    const el = {
      style: {},
      children: [],
      parentNode: null,
      appendChild(child) { this.children.push(child); child.parentNode = this },
      getBoundingClientRect() { return { width } },
    }
    return el
  }
  const bodyEl = {
    children: [],
    appendChild(child) { this.children.push(child); child.parentNode = this },
    removeChild(child) { this.children = this.children.filter((x) => x !== child); child.parentNode = null },
  }
  return {
    documentElement: { classList },
    body: body ? bodyEl : null,
    createElement: makeEl,
  }
}

test('① Chrome 83：gap 没生效（宽 20px）⇒ 判不支持、<html> 加 no-flex-gap', () => {
  const doc = fakeDoc({ width: 20 })
  assert.equal(detectsFlexGap(doc), false)
  assert.equal(installFlexGapFallback(doc), false)
  assert.equal(doc.documentElement.classList.contains(NO_FLEX_GAP), true)
})

test('② 现代浏览器：gap 生效（宽 30px）⇒ 判支持、不加类（不许叠两层间距）', () => {
  const doc = fakeDoc({ width: 30 })
  assert.equal(detectsFlexGap(doc), true)
  assert.equal(installFlexGapFallback(doc), true)
  assert.equal(doc.documentElement.classList.contains(NO_FLEX_GAP), false)
})

test('③ 探测节点必须拆掉（页面里不留垃圾）', () => {
  const doc = fakeDoc({ width: 20 })
  detectsFlexGap(doc)
  assert.equal(doc.body.children.length, 0, 'body 里不得留下探测节点')
})

test('④ 量不出宽度 ⇒ 当作支持（不兜底，避免误伤）', () => {
  const doc = fakeDoc({ width: Number.NaN })
  assert.equal(detectsFlexGap(doc), true)
  const noRect = fakeDoc({ width: 30 })
  noRect.createElement = () => ({ style: {}, children: [], appendChild(c) { this.children.push(c) } })
  assert.equal(detectsFlexGap(noRect), true)
})

test('⑤ 没有 body / 没有 document ⇒ 不抛、判支持', () => {
  assert.equal(detectsFlexGap(fakeDoc({ body: false })), true)
  assert.equal(detectsFlexGap(null), true)
  assert.equal(installFlexGapFallback(null), true)
})
