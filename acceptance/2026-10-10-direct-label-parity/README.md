# 「直连打印的水洗唛 = 打印预览那张」证据（issue #6656）

用户 2026-10-10 逐字：**「直连打印机打印的样式和水洗唛预览打印的样式完全不一样，能不能做成一样的」**
（附两张截图：生产明细页的「直连打印机打印」入口 / 「水洗唛 · 打印预览」纸面）。

本目录是**改后那条通道真正会送给打印机的位图**（不是单测读数 —— 单测只能证明「版式函数算了什么」，
证明不了「出图长什么样」）。

## 怎么采的（可复跑）

| 项 | 值 |
|---|---|
| 被测面 | 本 worktree 的**生产源码**：`lib/wash-label-content.ts`（内容真值）→ `lib/label-print/wash-label.ts`（版式）→ `lib/label-print/render.ts` 的 `canvasTextMeasure` |
| 渲染 | esbuild 把真模块打成 IIFE → Chromium（Playwright，从主仓 `tests/package.json` 解析）跑**真 canvas** |
| 二维码 | 页面用的同一个 `qrcode.react` `QRCodeCanvas size={256} level="M"`，取法同 `DirectLabelPrint.collectQrSources`（从容器里取 canvas） |
| 样例 | 与用户截图**同一条真单**：加工单 `JG-20261006-5289` / 订单 `20261006239740146` / 客户 `SD07演示客814127-123` / 部位 纱帘 / `SD07演示布814127 墨绿` / 用料 5.8 米 / 宽高 2.5×1.5 米 / 加工方式 打孔 · 定高买宽 / 交期 — / 备注 加铅块 / 短码 `HV4C6EKK` |
| 为什么不用 `toWashLabelInputs` | 它要一份完整 `ProductionPosition` + 快照行；本证据只取 `washLabelRows`（**同一份内容真值**），其余走同一套版式与绘制 |

```bash
cd frontend/admin-web
cp ../../acceptance/2026-10-10-direct-label-parity/render-bitmap.tsx .wl-accept-entry.tsx
npx esbuild .wl-accept-entry.tsx --bundle --outfile=/tmp/wl-accept/bundle.js --jsx=automatic \
  --format=iife --platform=browser \
  --define:process.env.NODE_ENV='"production"' --define:process.env='"{}"'
node ../../acceptance/2026-10-10-direct-label-parity/run.mjs
rm .wl-accept-entry.tsx
```

## 读数（两个独立来源，逐字一致）

- **几何**（`out/rows.json` 的 `geometry`）：**384 × 480 点** = 打印头有效打印宽 **48mm** × 纸长 **60mm**
  （= 介质矩阵 `label-50x60` 的 `effectiveWidthPx` × `pageBoxMm.heightMm` —— 改动前是 384 × 320 = **40mm**）。
- **纸面行**（`out/rows.json` 的 `rows`，与 `out/01-direct-print-bitmap.png` 图上逐字一致）：

  ```
  客户 SD07演示客814127-123 / 第 1 套 / 共 1 套 / 部位 纱帘 / SD07演示布814127 墨绿 /
  用料 5.8米 / 宽高 2.5×1.5米 / 加工方式 打孔 · 定高买宽 / 订单 20261006239740146 /
  交期 — / 备注 加铅块
  ```

- **读图判定**（我自己读 `out/01-direct-print-bitmap.png`；写「看到了什么」，不写「应该是什么」）：
  表头 `JG-20261006-5289`（7pt 粗体）在上；其下逐行 = 客户 / 套序 / 部位 / 件名（含色号，**不重复印色号行**）/
  用料 / 宽高 / 加工方式 / 订单 / 交期 / 备注；底部为**二维码 + 「扫码报工」+ 大字短码 `HV4C6EKK`**。
  与用户截图那张「水洗唛 · 打印预览」**字段与顺序逐条相同**（预览多出的只有页面外框与纸型说明文字）。
  `pageerrors = []`（`out/rows.json`）。

## 边界（照实登记，不粉饰）

1. **本目录不覆盖真机打印**：位图按 `PrintJob` 1:1 送点阵，但「边距 / 走纸 / 6pt 在 203dpi 下够不够清楚」
   仍**需要人在打印机旁核对**（Playwright 无人值守弹不出设备选择框）。
   **必须用 60mm 长的水洗唛纸卷**（40mm 卷装不下这些字段）。**重启条件**：现场实测 6pt 不可读 ⇒
   抬字号并重算 60mm 预算（预算账在 `frontend/admin-web/src/components/production/TaskCardPrint.tsx` 文件头）。
2. **不可统一的一处**：预览印在 50mm 纸上，而标签机打印头只有 **384 点 = 48mm**
   （`lib/print-media.json` 的 `dotGeometry` 已登记「右侧约 2mm 打不到」）⇒ 出图最宽 48mm，
   字段一致、整体窄 2mm。**这是物理上限，不是漏做。**
3. **本目录不是 §15.7 的「页面多模态验收」**：本次**屏幕上没有任何可见面变化**
   （改的是喂给位图的数据与版式；页面上的按钮 / 提示 / 预览层一字未动）⇒ 采的是**纸面产物**这一面。
   页面接线由 `frontend/admin-web/tests/unit/pages/processing-orders-production.test.tsx` 覆盖。
