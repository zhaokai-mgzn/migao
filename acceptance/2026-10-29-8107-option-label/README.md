# 专属水洗唛瘦身 · 两种纸长并存（issue #8107）

## 1. 用户逐字（2026-10-29）

> 「余料带回和绑带的水洗唛打印功能中，用户反馈打印的信息太多了，可以适当删减，
> 保留货号，门幅，宽高，工艺和特殊选项 + 二维码即可」
> 「把长度再缩减一些，能放下以上信息即可」

## 2. 结论（做了什么，边界在哪）

| 面 | 改前 | 改后 |
|---|---|---|
| 专属唛行集合 | 与常规唛同一份 15 行 | **只印 5 行**：货号 / 门幅 / 宽高 / 工艺 / 特殊选项（+ 底部二维码、抬头标记） |
| 专属唛纸型 | 50mm × 140mm（与常规唛同纸） | **50mm × 100mm**（介质 `label-50x100`，点阵 800） |
| 同一次出纸 | 只有一条文档级 `@page` | 文档级 `@page`（常规唛 50×140）+ **命名页** `@page wash-label-option`（专属唛 50×100）并存 |
| 常规唛 | 50mm × 140mm / 15 行 | **一字未改**（负控：改动 ⇒ `wash-label-content.test.ts` / `TaskCardPrint.test.tsx` 必红） |
| 专属唛抬头副标题 | `成品定制 · 余料带回`（12pt 加粗） | **只印语义名** `余料带回` / `绑带`、**16pt 加粗**（同日追加口径，用户逐字「副标题 成品定制.余料带回 改成余料带回，移除前面的成品定制，余料带回 /绑带字体再加大加粗」） |

**物理边界（照实登记）**：两种纸长 = **两种标签纸**（同一台 DP235S、同一条 50mm 卷，只有纸长不同）。
打印时驱动里**两张自定义纸型都要各登记一次**，纸卷也要**真的换** —— 本目录量的是「浏览器接受混合页高」，
不是「打印机出纸正确」。

**证据强度边界（issue #8145 收口）**：样张是**手写 HTML 复刻**（不是真组件、不读组件常量）⇒
它**只**证「Chromium 在同一次出纸里接受两种页高」，**证不到** 5 行内容 / 16pt 副标题 —— 那两件事由
`frontend/admin-web/tests/unit/lib/wash-label-content.test.ts`（行集合逐字）与
`frontend/admin-web/tests/unit/components/TaskCardPrint.test.tsx`（DOM 子节点 + `style.fontSize`）钉住。
样张上的「特殊选项」行按**展示名**印（`余料带回、绑带`），与真组件同口径（改回 join key ⇒ 单测必红）。

## 3. 读数（实测原文）

命令：

```bash
node acceptance/2026-10-29-8107-option-label/verify.mjs
```

输出（本机实跑，2026-10-29）：

```
playwright: /Users/guangzhen.zk/ai native/migao/tests/node_modules/playwright
pages: 2 | 50.1x140mm | 50.1x99.8mm
pdf: acceptance/2026-10-29-8107-option-label/out/wash-label-two-papers.pdf
✅ 两页纸型 = 50×140 与 50×100（±0.5mm），命名页混排被 Chromium 接受
```

- **2 页**：第 1 页 = 常规唛 50.1mm × 140mm，第 2 页 = 专属唛 50.1mm × **99.8mm**。
  宽度 +0.1mm 是 Chromium 出 PDF 的取整口径（两张纸同宽、同一条卷 ⇒ 逐页一致）；
  99.8mm 相对 100mm 的 −0.2mm 同样落在 MediaBox 取整误差内（阈值 ±0.5mm 见脚本）。
- 样张上那张专属唛的副标题**按新口径印**（`余料带回`，16pt 加粗、无 `成品定制` 前缀），常规唛仍是
  `成品定制` 10pt —— 与 `washLabelSubtitle` / `WASH_LABEL_OPTION_SUBTITLE_FONT_PT` 同值。
  注意：**页尺寸由纸型决定，不由内容决定**，副标题的字号/文案变化**不改**上面的 MediaBox 读数
  （复跑逐字仍是 `pages: 2 | 50.1x140mm | 50.1x99.8mm`）—— 这正是「纸长固定」应有的行为。
- 这条读数的**意义**：`page: wash-label-option` 与 `@page wash-label-option { size: 50mm 100mm }`
  真的让「同一次出纸」出了**两种纸高** —— 若两者任一失效，第二页会退回 140mm（脚本的反向对照会当场判红）。

## 4. 红证（注入式，证明这不是一份恒绿的读数）

把专属唛那一行 CSS 改回 140mm（= 命名页没生效的形态）后再跑：

```bash
sed 's/\.task-card-label--option { height: 100mm; page: wash-label-option; }/.task-card-label--option { height: 140mm; }/' \
  acceptance/2026-10-29-8107-option-label/verify.mjs > /tmp/verify-8107-injected.mjs
node /tmp/verify-8107-injected.mjs
```

实测输出（2026-10-29）：

```
pages: 2 | 50.1x140mm | 50.1x140mm
❌ 第 2 页（专属唛）高 140mm ≠ 100mm（±0.5）
❌ 两页纸高相同 ⇒ 命名页 `@page wash-label-option` 没生效（专属唛退化回 140mm）
```

⇒ 本读数**会红**（不是空断言）；同时它把「命中判据」与「反向对照（两页纸高必须不同）」各钉一条。

## 5. 这份证据**不覆盖**什么（照实登记）

- **不是真机热敏打印读数**：驱动侧两张自定义纸型的登记、走纸精度、撕纸位置，本脚本量不到；
  真机仍需人核对（重启条件 = 客户现场换纸/换驱动时）。
- **不复刻组件同值项**（宽度 / padding / 字号 / 行高 / 二维码边长）：那部分由
  `frontend/admin-web/tests/unit/lib/label-print/wash-label-metrics.test.ts` 逐值解析组件源码钉住，
  本脚本用的是与组件**同值**的一份 CSS（值取自 `wash-label-metrics.ts` 现值），只判纸型分页。
- **不进 CI 门禁**：本目录是**验收证据**，不是判据（判据见 PR body 的「固化声明」）。
- 依赖解析：本 worktree 未装 `tests/node_modules` ⇒ 脚本按候选列表回落到**同一仓库主工作区**的
  `tests/node_modules/playwright`（同 `tests/package-lock.json`、同版本 1.64.1）。取不到就直接报错，
  **不硬编任何读数**（脚本里没有兜底数字）。

## 6. 文件

- `verify.mjs` —— 可重跑的测量脚本（Chromium `page.pdf({preferCSSPageSize:true})` + 逐页读 MediaBox）。
- `out/wash-label-two-papers.pdf` —— 上面那次实测的 PDF 原件（2 页：50.1×140mm、50.1×99.8mm）。
