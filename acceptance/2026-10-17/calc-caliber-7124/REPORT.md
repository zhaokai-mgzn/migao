# 验收报告 —— 「算料口径」改分组表单（issue #7124）

> 按 `docs/testing/acceptance-protocol.md` 的产出物形态写；逐条证据可复算。
> 本报告只覆盖**商家可见面**（`/settings?domain=calc`），不改任何算料口径 / 金额 / 保存语义。

## 0. 被测对象与环境

| 项 | 值 |
|---|---|
| 被测版本 | 分支 `ui/7124-calc-caliber-form`（base = `origin/main` @ 合并后 `c9cecfe3a`；收口提交 `079ecdc26`） |
| 环境 | 本地真栈：admin-web `:3001`（Next dev，工作树 = 被测分支）+ admin-api `:8080` |
| Persona | 商家 `13800138000` / 万能码 `123456`（同 `scripts/ui_smoke_merchant.sh`） |
| 视口 | 1440×980（§15.7 读图口径） |
| 机器判据 | `acceptance/2026-10-17/calc-caliber-7124/verify.mjs`（自写，exit 0 = 三条判据全过） |
| 独立复核 | 另一个 AI（未参与实现、**自己写脚本**、不看本 PR 的 spec），共 3 轮：首轮 / 修复重放 / 收口 |
| 时间 | 2026-10-17 14:44–15:12 +08 |

## 1. 结论

**通过（P0/P1 = 0）。** 用户原始诉求（「算料口径这里的样式还是太丑陋了」）由形态改版回应；两轮独立复核的 6 条 P2 +
1 条观察项**全部关闭**，第二轮重放新抓到的「吸底条遮挡」也已修并复核关闭。

## 2. 验收矩阵

| # | 验收点 | 层级 | 断言（可执行） | 结果 | 证据 |
|---|---|---|---|---|---|
| 1 | 字段**标签在上、控件在下、提示收尾** | L1 | 6/6 `label.bottom <= input.top` | ✅ | `geometry.json`；复核 `04-group-materials.png` |
| 2 | 同组输入框**左边界对齐**（两列栅格） | L1 | 标量输入 x ∈ {562, 956}，宽一律 144（`w-36`） | ✅ | `RESULT {"distinctScalarX":[562,956]}` |
| 3 | 无**裁切 / 溢出 / 重叠 / 竖排折行** | L1 | `contentHits=0`；复核 `overPanel=[] overflowers=[]`；表右沿 953/1199 在卡内 | ✅ | `档位与拼色.png`；复核读数 |
| 4 | 区块标题把参数分组 | L1 | 3 个 h3：用布与余量 / 档位与拼色 / 超高 / 超宽阈值；无「其余参数」兜底组 | ✅ | `geometry.json.sectionTitles` |
| 5 | **研发过程产物不上屏**（§31 P3） | L1 | body 文本 snake_case / `issue #` / `NaN` / `undefined` 命中 **0** | ✅ | 复核 `body-text.txt` 全文扫描 |
| 6 | 无大块告警占屏、首屏看见要做的事 | L1 | 三个告警位均不渲染；首屏即见 4 个可编辑字段 + 档位表 | ✅ | `算料口径-首屏.png` |
| 7 | 列头对比度过 AA | L1 | 12px 列头 `rgb(126,111,87)` = **4.89:1**（白底）/ 4.68（卡底） | ✅ | 复核 `report4-after.json` |
| 8 | 「保存」始终够得着且**不盖内容** | L1 | 小条 208×53；静止首屏 `contentHits=0/728`；滚到档位与拼色时按钮 `buttonBottom 946 < 980` | ✅ | `verify.mjs` 两条读数 |
| 9 | 同屏不再有两处**同名**可编辑框 | L2 | 试算侧标签为「试算用超宽 / 超高阈值」，高度统一 `h-9` | ✅ | 复核 `07-threshold-preview.png` |
| 10 | 术语表首列不折行 | L1 | 首列 139px、行高 33.5（改前 126.7px / 54.5） | ✅ | 复核 `09-glossary-values-table.png` |

## 3. 问题清单（逐条带证据与处置）

| 分级 | 问题 | 证据 | 处置 |
|---|---|---|---|
| P2 | 表格列头 12px `text-neutral-400` 对比度 **2.28:1** | 复核 `report2.json.contrast` | → `text-neutral-600`（4.89:1） |
| P2 | 「档位与拼色」两卡撑满整行，右侧空 **357/535px** | 复核 `report2.json.cards` | → `w-fit` + `flex-wrap`（408/230，rightGap 17px） |
| P2 | h3 区块标题与 h4 卡标题同为 14px | 复核 `report2.json.h3/h4` | → h3 `text-base`（16px） |
| P2 | 阈值同屏两处同名可编辑框、高度 36 vs 32 | 复核 `07-threshold-preview.png` | → 「试算用」前缀 + `h-9` |
| P2 | 保存条距首屏 1.8 屏（静止不可见） | 复核 `report2.json saveDistanceFromTop` | → 右下角常驻小条（吸底） |
| P2（重放新发现） | **吸底条在静止首屏盖住内容**（标签 15708px² / 下拉框 5632px²） | 复核重放读数 | → shrink 到 208×53 + 说明移 title；复核收口 `文本命中 0` |
| 观察项 | 术语「参数当前值」首列 126.7px ⇒ 折两行 | 复核 `09-glossary-values-table.png` | → `whitespace-nowrap`（139px 单行） |
| 观察项（非缺陷） | 整页图左侧空白 / 右下蓝钮 / 左下「N」 | 复核说明 | Next dev 固定元素与开发指示器；登记为截图假象 |

## 4. 复核抽验（独立视角）

- 复核 AI **自写** Playwright 脚本（`/tmp/review-7124/`，不读本目录脚本），逐项给 DOM 读数与截图位置；
- **反向自证**：用四条与旧版相反的硬特征确认「看到的是新版」（label 在上 / 3 个 h3 / 两表上下排 / 输入框 144px vs 112px）；
- 三轮结论：首轮「通过 + 5 P2」→ 重放「5 P2 全关 + 1 新 P2」→ 收口「**通过**，新 P2 关闭，P0/P1 无新增」。

## 5. 沉淀（判据与边界）

**新增/改写的实例判据**

- `frontend/admin-web/tests/unit/components/CalcCaliberPanel.test.tsx`：分组表单形态（label 在上 / 无行底细线）、
  区块标题、**常用键 ≡ 分组 ∪**（漏键 ⇒ 参数在写面隐身）、定宽 `w-36`；
- `frontend/admin-web/tests/unit/lib/craft-calc-glossary.test.ts`：`CALC_FIELD_GROUPS` 结构性守卫（键必须是标量键、
  同键不重复、标题非空）+ 判别力自证；
- `frontend/admin-web/tests/unit/lib/domain-write-surface.test.tsx`：定宽 token 放行集改为 `{36,40,64}`（类级）。

**验收侧新增的机器判据**（`verify.mjs`）

- 同组输入框左边界「恰好两类」（参差回归即红）；
- **静止首屏遮挡采样**（4px 栅格 + 文本矩形命中，排除吸底条自身族与 hidden 文本）。

**未覆盖（照实登记）**

- 只拍桌面 1440×980；窄屏（<640）单列形态**没有真机截图**（由 `sm:grid-cols-2` / `flex-wrap` 承担）；
- 「好不好看」的最终判定仍属人裁定（§31.4）；本报告只给可断言形态；
- 422 逐条理由块在**真触发**时的高度表现未截图（已加 `max-h-40 overflow-y-auto`，结构核对过）。

---

## 6. 二轮改版（2026-10-17 16:00 起）—— 用户读图判「劣质」后的收口

**触发**：用户看首轮成品后逐字「这就是你改造后的结果吗？看起来就很劣质」。

**结论**：二轮通过（`verify.mjs` exit 0，四条判据合取；见 `README.md` 二轮读数节）。方向与处置逐条见 README 表。

**二轮新增/加强的判据**

| # | 断言 | 读数 |
|---|---|---|
| 11 | 标签里**不再有**「（」；有单位的 7 个键**框内有单位后缀** | `labelHasUnitParen=false` ×8、`unitInBox=true` ×7（`min_fullness` 无单位，豁免） |
| 12 | 数值**左对齐** | `text-left` 断言（`CalcCaliberPanel.test.tsx` 判据 8） |
| 13 | 三组字段落在**同一组 x** 上（浅底面板统一 `p-5`） | `distinctScalarX=[583,956]`（对称：583+333+40=956） |
| 14 | 保存出口**静止不吸底 / 滚过首屏才吸底且在视口内** | `restPinned=false`、`deepPinned=true`、`deepSaveInViewport=true`（单测另有滚前滚后滚回三段断言） |

**二轮被咬到的一次**（记录在案）：给「高级（2）」单独套 `p-5` 面板 ⇒ 它比别的组右移 21px，
`distinctScalarX` 立刻多出一个 x（判据当场红）⇒ 抽成共用的 `FieldGrid`，**面板内边距只有一处**。
