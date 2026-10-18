# 页面与按钮的统一规范（观星台 · PC + 移动端）

> **真值源**：本文（业务仓）。
> **研发模式侧的硬约束摘要**：预设仓 `zhaokai-mgzn/migao-agent-presets` 的 `migao-dev-flow` §32
> （v1.113.0 起）—— 那边只放摘要与边界，**表格与判据以本文为准**。改动时两边同批改。
> **实现**：`frontend/admin-web/src/components/ui/Button.tsx`（按钮：`variant` / `size` / **`icon`** / `loading` / `aria-busy`）、`.../ui/FormPanel.tsx`（字段与区块）。
> **守卫**：`frontend/admin-web/tests/unit/design-system-form-fields.test.tsx`（字段/区块）+ 按钮守卫（issue #7184 落地）。

## 0. 这份规范怎么来的（用户逐字，2026-10-18）

> 「还是老问题，按钮样式未统一，你检查下 PC 端的按钮，然后制定一个统一规范并执行落地，后续新增功能都要按页面&按钮的统一规范来落地，咱们的产品已经可以形成统一规范了」
> ｜「这个规范包含观星台所有功能，PC&手机端」
> ｜「规范应该写进米高研发模式？」

同一屏并存的反例（用户截图）：`刷新`（描边 + 图标）、`新增工序`（描边）、`新建路线`（主色实心 + 图标）、
`加工分类 (2)`（描边 + 图标 + 计数）、`新增加工项`（主色实心 + 图标）、`新建组合`（主色实心 + 图标）
—— **同一动作层级三种形态**（高度 / 圆角 / 配色 / 图标间距各不相同）。

## 1. 审计读数（2026-10-18 现取）

| 面 | 读数 |
|---|---|
| `frontend/admin-web/src` 里的 `<Button>` | **297** 处 |
| 同上，裸 `<button>` | **296** 处（≈ 一半没走共享件） |
| 共享件已有能力 | `variant`（primary / secondary / danger / ghost）+ `size`（sm / md / lg）+ `loading` |
| 缺的能力 | ① 裸 button 各写各的 class；② 图标靠手写 `mr-*`（没有 slot）；③ `loading` 时 spinner 与页面自带图标**并排**（双图标，issue #7180 那类观感的来源之一） |

> 读数口径：`grep -rc "<Button" src --include=*.tsx`（按行计）与 `grep -rho "<button" src --include=*.tsx | wc -l`。
> **这不是「有 296 个 bug」**——是「有 296 处还没收口」；收口顺序见 §6。

## 2. 按钮：层级（一屏至多一个 primary）

| 层级 | 用途 | 形态（PC） |
|---|---|---|
| `primary` | 这一屏**最主要的那个动作**（新建路线 / 保存 / 查询） | 实心主色 `bg-primary-600 text-white`，hover `primary-700` |
| `secondary` | 刷新 / 新建 / 取消 / 次级动作 | 白底描边 `bg-white border border-neutral-300` |
| `ghost` | 行内、表格行、弱动作 | 透明底 + hover `bg-neutral-100` |
| `danger` | 破坏性（删除 / 作废） | 白底红描边 `text-red-600 border-red-600`（**不实心**） |

**硬约束**：一屏**至多一个** `primary`；同一动作层级**不许**两种形态并存（截图里「刷新」和「新增工序」
同为 secondary 却一个带图标一个不带 —— 允许，但高度 / 圆角 / 描边色必须一致）。

## 3. 按钮：尺寸与图标

| 维度 | 规范 | 说明 |
|---|---|---|
| 尺寸 | `sm` = `h-8 px-3 text-sm`；`md` = `h-9 px-4 text-sm`（**默认**）；`lg` = `h-10 px-6 text-base` | 表格行内用 sm；页面头 / 对话框用 md；落地页 / 引导用 lg |
| 圆角 | `rounded-lg` | 与 `Field` 的控件同圆角 |
| 图标 | `icon` slot：16px、`shrink-0`、与文字 `gap-1.5` | **不许**手写 `mr-*` 把图标塞进 children |
| loading | spinner **顶替** `icon`（不并排）+ `disabled` + `aria-busy` | 两者并排 = 双图标（2026-10-18 真机被读成「图标重叠」） |
| 纯图标 | 必须 `aria-label` | 无障碍与测试都以名称定位 |
| 文案 | 动词开头（刷新 / 新建路线 / 保存）；不加「！」 | 与 `docs/design/user-facing-copy-standard.md` 同源 |

## 4. 页面与区块（同族的另一半）

配置面字段一律 `Field`（**标签在上** + 控件满列 + 单位入框），区块一律 `FormPanel`
（浅底面板 `rounded-lg border bg-neutral-50/50 p-4` + `text-sm font-semibold` 标题 + 一句 `text-xs` 说明）。

**改版式的唯一合法路径 = 改共享原语**（改一处全站跟着变），**不是**在页面里覆盖 class ——
后者正是「一个产品长出多种写法」的源头（issue #7176 的实测病灶）。

## 5. 移动端（H5 / 小程序）

- **同一套语义与 token**：四个层级、`rounded-lg`、主色同一变量、`36~40px` 高度（触屏最小可点 40px）；
- 实现**各自原语**（`frontend/mini-app` 与 H5 各自），但**不许**按端另发明一套层级；
- 移动端一屏**同样**至多一个 primary；列表行内动作用 ghost / 文本动作，不用实心主色。

## 6. 判据与落地顺序

**顺序**：规范（本文）→ 共享件（`Button` 增 `icon` / `aria-busy`）→ 用户点名的面（工艺配置 / 加工项 / 加工费组合 / 通知中心）→
存量台账收敛。**不做**「一次迁完 296 处」的大爆炸迁移。

| 判据 | 会红的形态 | 状态 |
|---|---|---|
| 字段 / 区块 | 业务面自拼控件铬、标签顺排控件 | ✅ 已落：`design-system-form-fields.test.tsx` |
| 按钮 chrome | 裸 `<button>` 自带**主色** chrome（`bg-primary-600`） | ✅ 已落：`design-system-buttons.test.tsx`（存量 10 处冻结台账，只许缩短） |
| loading 双图标 / icon slot | `loading` 时页面自带图标仍渲染；图标手写 `mr-*` | ✅ 已落：`design-system-buttons.test.tsx`（`icon` prop + spinner 顶替 + `aria-busy`） |
| 图标字形 | ≤16px 用叠置字形（`check-check` 一类）读成「图标重叠」 | ✅ 已落：`notifications.test.tsx` / `NotificationBell.test.tsx`（#7180） |

## 7. 边界（如实登记）

- 本规范**不新增 required check**（落地前是判据标准；落地后才成为 CI 的一部分）；
- 「好不好看」仍由 `migao-dev-flow` §15.7 读图 + 人裁定（§31.4：界面是「智能专业的优雅绅士」），
  本节只保证**同一个产品长得像同一个产品**；
- 本文与预设仓 §32 **双向同步**：改表格回来改那边的一句话摘要（不抄第二份表）。
