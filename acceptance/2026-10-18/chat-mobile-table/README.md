# 手机端黄金策表格渲染 · 静态复现件读数（issue #7235 / 用例 UI-126）

## 这是什么

手机端（390 竖屏比例、750 设计宽）聊天气泡里 **GFM 表格**的**几何读数 + 截图**。
用的是产品同一份 `frontend/bmini-app/src/components/chat/MessageBubble.scss`（编译产物内嵌进
`table-probe.html`）与同一套 DOM 结构（`.message-bubble__table*`）。

## 为什么是静态复现件（边界，如实登记）

本机此刻没有起 bmini H5 运行栈（Taro 构建 + 商家登录 + 真会话），而本单只改**渲染形态**
（DOM 结构 + SCSS）⇒ 用复现件在**真实 Chromium** 里量几何。与仓库既有先例同范式：
`acceptance/2026-10-18/design-system-7176/probe.mjs`。

⚠️ **复现件 ≠ 真机 H5**。差异与登记：

1. **横向滚动由 Taro 的 `<ScrollView scrollX>` 提供**（H5 = `taro-scroll-view-core`，小程序 = 原生
   `scroll-view`）。复现件没有这层运行时 ⇒ `table-probe.html` 里补了一条
   `.message-bubble__table-scroll { overflow-x: auto }` **等价语义**（注释里写明是运行时补的，不是产品 SCSS）。
2. 未覆盖：Taro 的 `px → rpx/rem` 换算后的**绝对字号**（复现件按 750 设计宽直接渲染，比例一致）、
   微信小程序的 `scroll-view` 真机滚动惯性。
3. **真栈截图仍待补**：下一次 `bmini-h5-publish` 部署后，用真机打开黄金策会话里任意带表格的回复补一轮
   §15.7 读图（本 README 与 PR body 双向登记；未补不算已验收）。

## 读数（`node probe.mjs`，2026-10-18）

```json
{
  "viewport": 750,
  "pageScrollWidth": 750,
  "tableCount": 2,
  "sixCol": {
    "rows": 4,
    "cells": 24,
    "clientWidth": 622,
    "scrollWidth": 823,
    "scrollable": true
  },
  "threeCol": {
    "rows": 3,
    "cells": 9,
    "clientWidth": 555,
    "scrollWidth": 557,
    "scrollable": true
  },
  "wideBubbleWidth": 660,
  "plainBubbleWidth": 548,
  "literalPipes": 0
}
```

判据（脚本自带，非全绿即 exit 1）：

- DOM 文本**零字面 `|`**（不再是裸 markdown）；
- 页面**无横向溢出**（`750 == 750`）；
- 6 列表格**可横滑**（`scrollWidth 823 > clientWidth 622`）
  —— 宁滑不挤，不把 6 列压成 6 个竖排字；
- 表格行 / 单元格数量逐值（6 列 = 表头 1 + 数据 3 行 = 24 格；3 列 = 9 格）；
- 有表格的气泡（94%，660）确实比纯文本气泡（78%，548）更宽。

## 读图判定（§15.7，逐条引证据）

`screenshot-750.png`（1500×3000 @2x）：

1. ① 6 列表示意：表头浅底 + 单元格细线，**前 4 列完整可见**、第 5/6 列被右缘裁掉（= 可横滑的形态，
   不是被压成竖排）；
2. ② 3 列表格：三列完整落在气泡内，无截断；
3. ③ 对照纯文本气泡明显更窄（78% vs 94%），证明「只有表格气泡放宽」不是全局放宽。

## 复算

```bash
cd acceptance/2026-10-18/chat-mobile-table
node probe.mjs        # 打印读数 JSON + 判据 + 截图
```
