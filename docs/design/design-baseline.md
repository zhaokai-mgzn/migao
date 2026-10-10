# 设计基线（单一真值源）

> **本页是「设计基线」的入口，不是真值本身。** 真值在代码里 —— 本页只**指出**它在哪、
> 以及「照它做」要自检什么。任何与代码不一致的文字（包括本页）**以代码为准**。
>
> - 定源日期：**2026-10-10**（issue [#6668](https://github.com/zhaokai-mgzn/migao/issues/6668)）
> - 目标（用户 2026-10-10 逐字）：「**我们的目标是按顶尖的互联网网站设计规范去做基线，
>   我们的产品需要给客户商务感且专业**」
> - 判据（这段基线**会红**的承载体）：
>   `frontend/admin-web/tests/unit/design-baseline-token-contract.test.ts`（token 与文档一致）、
>   `frontend/admin-web/tests/unit/design-baseline-expression-fallback.test.ts`（盲区①）、
>   `frontend/admin-web/tests/unit/design-baseline-server-strings.test.ts`（盲区②）、
>   `frontend/admin-web/tests/unit/design-baseline-geometry.test.ts`（盲区③）、
>   `frontend/admin-web/tests/unit/design-baseline-page-state-contract.test.ts`（盲区④）

---

## 1. 真值源在哪（**不要复制，要指向**）

| 面 | 真值源（唯一） | 怎么被消费 |
|---|---|---|
| **颜色**（primary / accent / neutral / gold / chart） | `frontend/admin-web/tailwind.config.ts` 的 `theme.extend.colors` | 页面只写类名（`bg-primary-500` / `text-neutral-700` / `border-accent-200`） |
| 织金数值本体 | `frontend/admin-web/src/lib/brand-palette.ts`（SVG 属性也读它） | `tailwind.config.ts` 把它接成 `gold` 调色板 |
| **字号阶梯** | `frontend/admin-web/src/lib/design-tokens.ts` 的 `TYPE_SCALE` | `tailwind.config.ts` 的 `theme.extend.fontSize` ⇒ 页面写 `text-sm` / `text-2xl` |
| **圆角（基数）** | Tailwind 默认阶（未覆盖）：`rounded-sm=2px` / `rounded-md=6px` / `rounded-lg=8px` / `rounded-xl=12px` | 页面只用这四个类名；**不写任意值** `rounded-[10px]` |
| **阴影** | `frontend/admin-web/tailwind.config.ts` 的 `theme.extend.boxShadow` | `shadow-card` / `shadow-card-hover` / `shadow-modal` / `shadow-float` |
| **间距** | Tailwind 默认阶（未扩展）；容器内边距统一 `p-4`/`px-4 py-3`、表头 `px-4 py-3` | 页面只用默认阶 |
| **金额** | `frontend/admin-web/src/lib/money.ts`（`money` / `moneyOrDash`） | 「未定价 ≠ ¥0.00」：缺失值**不得**印成 0 |
| **日期时间** | `frontend/admin-web/src/lib/utils.ts` 的 `formatChatTime`（相对/时分）/ `formatFullDateTime`（`YYYY年M月D日 HH:mm`） | 页面不自己拼日期串 |
| **状态展示** | 各域 `*StatusLabels` + `frontend/admin-web/src/lib/status-chip.ts`（语义色 tone） | 见 §5 四态契约 |
| **枚举显示名** | `frontend/admin-web/src/lib/enum-display.ts` 的 `displayEnum` | 未知枚举值 ⇒ 人话兜底（见 §4 盲区①） |

> **一处例外（如实登记）**：`gold` 是**唯一**把数值本体放在 `src/lib/`（而非 config）的调色板，
> 理由是 SVG 的属性位也要读同一份；这是 issue #6665 的有意设计，不是漂移。

---

## 2. 颜色（现行 token；**这些值是判据钉住的**）

| token | 值 | 用途 |
|---|---|---|
| `primary-500` | `#48618f` | **主色**：主按钮、链接、选中态（靛蓝 —— **不是** AntD 时代的默认蓝，历史值见 `docs/design/ui-design-spec.md`） |
| `primary-600` | `#3a4e75` | 主按钮 hover |
| `primary-700` | `#2e3d5c` | 主按钮 active |
| `accent-500` | `#c06a3e` | 点缀（陶土）：次要强调、图表销售额 |
| `neutral-50` | `#faf7f2` | **页面底色**（暖亚麻 —— **不是** `#FAFAFA` 平灰） |
| `neutral-700` | `#625545` | 正文 |
| `neutral-900` | `#312c26` | 标题 / 深色区块底 |
| `gold-600` | 见 `frontend/admin-web/src/lib/brand-palette.ts` | 织金点缀（官网 hero 渐变、深色区块图标） |
| 语义色 | emerald / amber / red / primary 四族（`status-chip.ts`） | 成败/警示/中性/信息 |

**适用范围（重要）**：本仓的 `docs/design/ui-design-spec.md` **从未覆盖官网**
（`frontend/admin-web/src/app/(corporate)/**`）—— 官网是 2026-10-04 才落地的
（见 `docs/design/corporate-site-redesign.md`），此前那份规范是 **C 端对话页 / 员工工作台 /
管理后台**三者的规范。官网的视觉口径**不在**本页射程内（它有自己的暖织物底 + 深色 hero + 金点缀），
但**共用**本节的颜色 token（`primary` / `neutral` / `gold`）。

---

## 3. 字号阶梯（真值 = `TYPE_SCALE`；下限 12px）

| 类名 | 字号 | 行高 | 字重 | 用途 |
|---|---|---|---|---|
| `text-2xl` | 24px | 36px | 600 | 页面标题（h1） |
| `text-xl` | 20px | 30px | 600 | 区块标题（h2） |
| `text-lg` | 18px | 27px | 600 | 卡片 / 弹层标题（h3） |
| `text-base` | 16px | 24px | 400 | 强调正文（不常用） |
| `text-sm` | 14px | 21px | 400 | **默认正文**、表格内容、表单文字 |
| `text-xs` | 12px | 18px | 400 | 辅助说明、时间戳、角标 |

- **下限 12px**：低于它的字号不进本阶梯（写 `text-[11px]` 即越界）；行高比固定 **1.5**；
- **触屏门面另有下限**：`worker-h5` / 两个 Taro app 用**设计尺度**（`1px = 1/40 rem`），
  下限 **24 设计 px**（= 12.8 CSS px @390）—— 承载体 =
  `tests/unit_ci_workflows/test_bmini_mobile_typography_floor.py`（**那条不许松**，本页不合并它：两套坐标系）；
- 关键数字用 `tabular-nums`（金额 / 库存 / 销量），避免跳动。

## 4. 圆角 / 阴影 / 间距

| 面 | 口径 |
|---|---|
| 圆角 | `rounded-sm` 2px（Badge/小标签）· `rounded-md` 6px（下拉）· **`rounded-lg` 8px（按钮 / 输入框 / 卡片，最常用）** · `rounded-xl` 12px（Modal / 大卡） |
| 阴影 | `shadow-card`（卡片默认）· `shadow-card-hover`（悬浮）· `shadow-modal`（弹层）· `shadow-float`（浮窗）；色相取自暖中性 `rgba(36,31,24,…)`，**不用**纯黑 |
| 间距 | 页面容器 `p-4`/`gap-4`；表头/单元格 `px-4 py-3`；区块间 `space-y-5`；**不写任意值** |
| 边框 | `border-neutral-200`（分隔）/ `border-neutral-100`（极浅分隔）；**软分层**优先于重边框 |

### 几何（浏览器读数才判得了，见盲区③）

| 读数 | 基线 | 谁守 |
|---|---|---|
| 桌面后台**主控件**高度 | **≥ 36**（= `h-9`，与 `Button`/`Input` 逐字一致） | `acceptance/2026-10-10-admin-web-6668/admin-web-geometry-probe.mjs` + `frontend/admin-web/tests/unit/design-baseline-geometry.test.ts` |
| 触屏门面触达区 | **≥ 40**（Apple HIG 44 / Material 48 的下沿；射程 = `worker-h5` / Taro，另有 `bmini-geometry-probe.mjs`） | 同上（备查，不在 admin 探针射程） |
| 单条常驻面高度 | **≤ 96**（超过即「横幅式告警」，违反常驻面克制） | 同上 |
| 首屏被常驻面占掉 | **≤ 0.4**（1440×980） | 同上 |
| 内容被常驻面遮挡 | 叶子文本底边 − 常驻面顶边 **≤ 0.5**（只判 `fixed`/`sticky` 的面） | 同上 |

> ⚠️ **本包没有真跑浏览器**（本机没起 `:3001`）⇒ 上表是**口径 + 可复算入口**，
> **不是**「几何已验过」。真读数由验收会话跑探针取得（命令见该目录 README）。

---

## 5. 四态契约（**失败 ≠ 空**）

每个读面页面必须能渲染四种**可区分**的态：

| 态 | 说什么 | 反例（会红） |
|---|---|---|
| ① 加载中 | 骨架 / 「加载中…」 | 白屏或先印「暂无数据」 |
| ② 空 | **「暂无数据」+ 为什么空 + 去哪建** | 只说「暂无数据」（用户不知道下一步） |
| ③ **失败** | **「加载失败 + 是哪几块 + 重试出口」**，且**不清零**已有读数 | 只 `toast.error`（一会儿就没了）而页面照旧印「暂无数据」；把故障画成 0 |
| ④ 成功 | 真数据 | —— |

**判据链**（两条互补，别只读一条）：
- `frontend/admin-web/tests/unit/read-failure-empty-state-guard.test.ts`（UI-057/058）——
  治「**catch 只清空读数**」（扫 catch 块的 setter）；
- `frontend/admin-web/tests/unit/design-baseline-page-state-contract.test.ts`（盲区④）——
  治「**渲染出来的态**」：凡有空态字面量的页面必须有失败态锚点；
  当前**已知缺口 3 条**写在 `frontend/admin-web/tests/unit/page-state-contract-ledger.json`
  （`finance/page.tsx` / `customers/page.tsx` / `customers/[id]/CustomerDetail.tsx`），**只许缩短**。
- 范式（抄它）= `frontend/admin-web/src/app/(dashboard)/dashboard/page.tsx` 的
  `dashboard-load-failed` + `dashboard-retry-block`：「加载失败 + 是哪几块 + 上次成功值仍在」。

---

## 6. 文案语调

- 口径与词表：`docs/design/user-facing-copy-standard.md` +
  `frontend/admin-web/tests/unit/user-copy-jargon-guard.test.ts`（UI-093，机械面）；
- 三条硬口径：**只陈述事实 + 该做什么**；禁责备 / 催促式口语与惊叹号堆叠；
  **内部标识不上屏**（哈希 / 内部键 / 字段名 / 权限码 —— 见盲区②）；
- 承诺与边界照旧保留（**未定价 ≠ ¥0.00**、**「读取失败」≠「暂无」**）。

---

## 7. 四条盲区与它们的判据（今天之前完全没有网）

| # | 盲区 | 今天之前的缺口 | 判据（会红） | 判别力自证 |
|---|---|---|---|---|
| ① | **表达式兜底** | `LABELS[x] \|\| x` 既不是字面量（UI-093 扫不到）也不是纯成员链（UI-094 扫不到） | `frontend/admin-web/tests/unit/design-baseline-expression-fallback.test.ts` + 扫描器 `frontend/admin-web/scripts/enum-fallback-scan.mjs` + 台账 `frontend/admin-web/tests/unit/enum-fallback-ledger.json` | 5 个历史坏形态各自命中；5 个好形态（人话兜底 / 字面量 / 破折号 / 同表缺省 / 数组）不命中 |
| ② | **服务端下发字符串** | 前端自切服务端复合串；`error.details[{"field":"requiredPermission","message":"<权限码>"}]` 的 `message` 里装的是**机读权限码**；服务端只下发机器键 | `frontend/admin-web/tests/unit/design-baseline-server-strings.test.ts` + 台账 `frontend/admin-web/tests/unit/server-string-display-ledger.json` + **「只改展示」负控**（`materialKey` 仍承载 React key；`materialLabel` 仍是展示名；DTO 两字段都在） | 切串 / 权限码进提示语 / 进 JSX 三种坏形态判红；展示名与判定式不红 |
| ③ | **几何** | 条高 / 被常驻面遮住 / 触达区 / 首屏被常驻面占掉 —— **0 条常驻判据** | `frontend/admin-web/tests/unit/design-baseline-geometry.test.ts`（守读数入口与判别力）+ 探针 `acceptance/2026-10-10-admin-web-6668/admin-web-geometry-probe.mjs`（真读数） | 四条判据各自有坏/好对照；`judge` 综合判据逐条具名 |
| ④ | **状态机** | 失败态与空态在页面间各写一套（有的页面显示「暂无」） | `frontend/admin-web/tests/unit/design-baseline-page-state-contract.test.ts` + 台账 `frontend/admin-web/tests/unit/page-state-contract-ledger.json`（**未登记即红、只许缩短**） | 只有空态判红；空态+失败态放行；「计算不可用」的描述不判红 |

---

## 8. 设计基线自检五问（**新页面 / 新组件动手前逐条问**）

1. **它会随数据增长吗？** —— 会（列表 / 告警 / 明细）就默认**折叠 + 封顶**：
   常驻面 = 一行摘要（条数 + 最强读数 + 动作入口），逐条明细按需展开且 `max-h + overflow-y-auto`；
   **折叠态下逐条 DOM 不渲染**（`queryByTestId` 为 `null` 才是机器读数）。
2. **它有没有重复同屏已有的信息？** —— 单号 / 时长 / 金额 / 状态**至多一处**承载
   （表格列与文案只能有一处说它）。
3. **有没有内部标识上屏？** —— 哈希 / 内部键（`materialKey` / `orderRef`）/ 字段名 / 权限码
   **一律不得出现在商家可见面**；展示名与标识分家（服务端新增展示字段，**前端不切串**）。
4. **语气像给商家的正式提示吗？** —— 只陈述**事实 + 该做什么**；禁责备 / 催促 / 惊叹号堆叠。
5. **首屏第一眼能看到要做的事吗？** —— 常驻面（告警 / 提示 / 明细）不得占掉首屏主体
   （读数口径 = 几何探针的 `firstScreenShare`）。

> 前四问与 `migao-dev-flow` §31（产品设计原则）同源，本页是它在**基线**里的落点；
> 第五问在这条基线上第一次有了**几何读数**（`firstScreenShare ≤ 0.4`）。

---

## 9. 有意接受的取舍（**登记，不是缺陷**）

| # | 取舍 | 理由 | 重启条件 |
|---|---|---|---|
| 1 | **同一个琥珀色承载两种语义**：`frontend/admin-web/src/components/orders/OrderFeeBreakdown.tsx` 的 `text-amber-*` = 「**未定价**」；`frontend/admin-web/src/components/orders/OrderCraftFields.tsx` 的 `cutting-mode-auto` = 「**系统自动选中**」 | 两处都在**同一张下单表单**上，且都在提示「这里不是你手填的值」——共用警示色**降低了**表单的颜色数量（颜色语义一对一很好，但为它新增第五个语义色会更花） | 若将来「未定价」需要更强的**行动**含义（如必须补价才能提交），两者必须分色 |
| 2 | `ui-design-spec.md` 的色彩章**降级**而非删除 | 它是历史（AntD 时代）的**唯一**记录，删掉会让「为什么不是蓝色」无从追溯 | 若该文档的其余章节（组件 / 布局）也整体退场，本页接管后即可归档 |
| 3 | 桌面后台主控件下限 **36** 而非触屏 40 | 与 `Button`/`Input` 的 `h-9` 逐字一致；写 40 会把整站既有主控件判红（假红） | 触屏门面（worker-h5 / Taro）另有 40 的判据，两者不互相覆盖 |

---

## 10. 未固化项（照实登记，§19.1）

1. **`kind: risk` 的 22 条表达式兜底尚未逐条改成 `displayEnum`** ——
   清单在 `frontend/admin-web/tests/unit/enum-fallback-ledger.json`（只许缩短）。
   它们分布在**已合并包的文件族**（订单 / 财务 / 生产 / 打印纸面），本包**不改业务组件实现**
   ⇒ 修复另单承接；
2. **服务端展示名与标识的分离只固化了前端这一半** —— `error.details[{"field":"requiredPermission",
   "message":"<权限码>"}]` 的 `message` 装的是**机读权限码**（服务端契约面），
   `backend/admin-api` 的 `PermissionDeniedResponse` 目前没有展示名字段 ⇒ 需要后端包新增
   `displayName`（或前端接住 `permissionLabel`）；本页只保证**前端不切串、不把机器值当人话**；
3. **几何真读数未跑**（本机没起 `:3001`）—— 探针与阈值都在，但**没有实测读数**；
4. **加载态（第三态）没有机械判据** —— `loading` 变量名五花八门，判它只会造假红；
5. **审美本身判不了** ——「优雅」的最终判定仍是真机截图 + 读图 + 人裁定
   （`migao-dev-flow` §15.7）。**别把「基线达标」读成「设计已评审」**。
