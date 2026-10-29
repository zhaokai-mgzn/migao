# 专属水洗唛再收短 · 50mm × 80mm + 留白 8/8（issue #8163，承接 #8107）

## 1. 用户逐字

issue #8163（2026-10-30，回答「纸长还能再短吗」）：

> 「1，那就再缩小到80mm」

前序口径（#8107，2026-10-29，本次未改）：专属唛只印 **5 行**（货号 / 门幅 / 宽高 / 工艺 / 特殊选项）+ 二维码；
副标题 16pt 加粗、**只印语义名**（`余料带回` / `绑带`）。

## 2. 结论（做了什么，边界在哪）

| 面 | 改前 | 改后 |
|---|---|---|
| 专属唛纸型 | 50mm × 100mm（介质 `label-50x100`，点阵 800） | **50mm × 80mm**（介质 `label-50x80-option`，点阵 **640**）；旧 id 退场 |
| 专属唛上下留白 | 15mm / 15mm（= 常规唛 140mm 纸的口径） | **8mm / 8mm**（`WASH_LABEL_OPTION_TOP_BLANK_MM` / `WASH_LABEL_OPTION_BOTTOM_CLEARANCE_MM`） |
| 同一次出纸 | 文档级 `@page`（50×140）+ 命名页 `@page wash-label-option`（50×100） | 同上，命名页纸型变成 `50mm 80mm` |
| 常规唛 | 50mm × 140mm / 15 行 / `padding: 15mm 1.2mm 15mm` | **一字未改**（负控） |
| 行集合 / 副标题 / 二维码 | 5 行 / `余料带回` 16pt / 80 CSS px | **一字未改** |

**为什么留白必须一起收（物理约束，不是口味）**：上下各 15mm 是 **140mm 纸**的口径（2026-10-28
「多的30要添加到顶部和底部虚线下处各15」）。纸长砍到 80mm 后若仍按 15/15，纵向只剩 80 − 15 − 15 = **50mm**，
而 5 行内容要 **58.15mm** ⇒ **纸面必然少几行且两条通道都不报错**（静默裁行）。所以专属唛单独取 8/8：
可用 **64mm**，内容 **58.15mm ≤ 64mm**（余 5.85mm ≈ 1.25 行），整张 ≈ **74.15mm ≤ 80mm**。
红证见 §5 的注入 B。

**物理边界（照实登记）**：两种纸长 = **两种标签纸**（同一台 DP235S、同一条 50mm 卷，只有纸长不同）。
打印时驱动里**两张自定义纸型都要各登记一次**，纸卷也要**真的换** —— 本目录量的是「浏览器接受混合页高」，
**不是**「打印机出纸正确」。

**证据强度边界（issue #8145 收口）**：样张是**手写 HTML 复刻**（不是真组件、不读组件常量）⇒
它**只**证「Chromium 在同一次出纸里接受两种页高」，**证不到** 5 行内容 / 16pt 副标题 / 留白 8/8 的实际排版 ——
那几件事由 `frontend/admin-web/tests/unit/lib/label-print/wash-label.test.ts`（位图通道 640 点、留白 8/8 vs 常规 15/15、
5 行不裁）与 `frontend/admin-web/tests/unit/components/TaskCardPrint.test.tsx`（DOM 子节点 + `.task-card-label--option`
的 `height: 80mm; padding: 8mm 1.2mm 8mm`）钉住。

## 3. 读数（实测原文，本机）

```bash
node acceptance/2026-10-30-8163-option-label/verify.mjs
```

```
playwright: /Users/guangzhen.zk/ai native/migao/tests/node_modules/playwright
pages: 2 | 50.1x140mm | 50.1x80.1mm
pdf: …/acceptance/2026-10-30-8163-option-label-80/out/wash-label-two-papers-80.pdf
✅ 两页纸型 = 50×140 与 50×80（±0.5mm），命名页混排被 Chromium 接受
```

- **`pages: 2`**：一次出纸两页。
- **`50.1x140mm`**：常规唛那张 = `label-50x140`（**没被本次改到**）。
- **`50.1x80.1mm`**：专属唛那张 = `label-50x80-option`。80mm = 226.77pt，PDF MediaBox 取整成 227pt
  ⇒ 227 × 0.3528 ≈ **80.09mm**（+0.1mm 是 pt 取整，不是排版误差）；断言容差 ±0.5mm。
- 两页**高度不同**本身就是断言（`boxes[0] ≠ boxes[1]`，见脚本末段反向对照）。

## 4. 复算 / 重跑

```bash
# 纸型真值（两页应为 50×140 与 50×80）
node acceptance/2026-10-30-8163-option-label/verify.mjs

# 纸型 / 留白 / 行集合的单一真值
cd frontend/admin-web && npx vitest run \
  tests/unit/lib/wash-label-content.test.ts \
  tests/unit/lib/label-print/wash-label.test.ts \
  tests/unit/lib/label-print/wash-label-metrics.test.ts \
  tests/unit/lib/print-media.test.ts \
  tests/unit/components/TaskCardPrint.test.tsx

# 几何/预算的类级守卫（G8~G13）
cd ../.. && python3 -m pytest tests/unit_ci_workflows/test_wash_label_geometry_guard.py \
  tests/unit_ci_workflows/test_print_media_matrix_guard.py \
  tests/unit_ci_workflows/test_wash_label_single_source.py -q
```

## 5. 红证（注入式，逐条可复制）

**A. 纸高别只改一处**（脚本内联 CSS）：

```bash
sed 's/height: 80mm; padding: 8mm 1.2mm 8mm; page: wash-label-option;/height: 100mm; page: wash-label-option;/' \
  acceptance/2026-10-30-8163-option-label-80/verify.mjs > /tmp/inject-a.mjs
node /tmp/inject-a.mjs
# 实测输出（本机）：
#   pages: 3 | 50.1x140mm | 50.1x80.1mm | 50.1x80.1mm
#   ❌ 页数 3 ≠ 期望 2（两种纸型必须各自成页）
# 为什么是 3 页而不是 2 页：容器被改回 100mm 却仍挂在 80mm 的命名页上 ⇒ 溢出部分被浏览器
# 另起一页（100mm 盒子塞进 80mm 纸）—— 这正是「容器高必须与命名页纸型一致」的形态。
```

**B. 留白退回 15/15**（= 「静默裁行」的形态，由单测抓 —— 这一层量不到裁行，所以才必须另有断言）：

```bash
cd frontend/admin-web
# 把位图通道的按张取留白退回常量（模拟「只改纸高没改留白」）
sed -i '' 's/media === WASH_LABEL_OPTION_MEDIA/false \&\& media === WASH_LABEL_OPTION_MEDIA/' \
  src/lib/label-print/wash-label.ts
npx vitest run tests/unit/lib/label-print/wash-label.test.ts   # ⇒ 2 failed（5 行被裁：实际只画到第 3 行）
git checkout src/lib/label-print/wash-label.ts
```

**C. 类级守卫（常驻，随判据跑）**：`test_wash_label_geometry_guard.py` 的
- G8：容器高 != 矩阵纸高 ⇒ 红（注入：`height: 140mm` ⇒ 实测 4 failed）
- G9：命名 `@page` 缺 / 与矩阵不同源 ⇒ 红
- G10：预算恒等式（版心宽 / 可用 / 每行）与现取几何不符 ⇒ 红
- **G12**：专属唛没写自己的 `padding`、或与 `wash-label-metrics.ts` 的 8/8 不同源、或等于常规唛的 15/15 ⇒ 红
- **G13**：注释里的「满字段 5 行 = 58.15mm ≤ 可用」/「折 1 行 = 62.81mm ≤ 可用」不成立（= 内容装不下）⇒ 红
- G11：以上四条各自的注入式红证（带 sha256 内容指纹，禁 mtime/size）

## 6. 本目录**不**覆盖什么（照实写）

1. **真机**：没有打印机，量不到实际走纸、切纸位置、热敏浓度；`label-50x80-option` 的
   `measurement = measured` 指的是**纸宽侧**沿用 `label-50x140` 的实测口径，不是本机量了 80mm 那张纸。
2. **视觉**：不判「16pt `余料带回` 在 50mm 宽纸上是否好看」；只判预算（22.6mm < 47.6mm 版心）。
3. **裁行**：本层的 PDF 只证页高；「50mm 纸上 5 行不裁」由位图单测 + 预算复算覆盖。

## 7. 文件

- `verify.mjs` —— 出两张样张 PDF、逐页读 MediaBox、断言 50×140 与 50×80（±0.5mm）+ 两页高度必须不同。
- `out/wash-label-two-papers-80.pdf` —— 本机实测产物（证据原件）。
- `README.md` —— 本文件。
