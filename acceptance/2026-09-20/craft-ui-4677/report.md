# 验收报告 — issue #4677 · 工艺项界面两层改造（PR #4710）

| | |
|---|---|
| **验收类型** | 独立验收（**非实施者**；不复用实施包自述作为结论依据） |
| **被测对象** | issue **#4677**（CLOSED）· PR **#4710**（MERGED @2026-09-20T02:45:42Z）· merge commit **`efa59d98a29034ca8f5d2455c6e03ea1dde3aef6`** |
| **设计依据** | `docs/design/public-operations-and-craft-ui.md`（#4675）§4 界面改造 / §4.5 方案 A / 附录 B 16 条判据 |
| **后端依赖** | `GET /operation-layers`（#4676 已合并） |
| **验收工作区** | `/Users/guangzhen.zk/ai native/migao-wt/acceptance-craft-ui-4677`（分支 `acceptance/craft-ui-4677` → 报告分支 `acceptance-report/craft-ui-4677`） |
| **交付源码锚（不可变）** | `page.tsx` = `0176604778…a003e9` · `api.ts` = `84b172c8…a5a206f` · `types/index.ts` = `45fcf825…dbc9f8`（均 `git show efa59d98a:<path> \| shasum -a 256`） |
| **报告日期** | 2026-09-20 |
| **transcript** | 同目录 `transcript.md`（任何一轮原文未省略） |

---

## 0. 结论

> **代码层：判定"基本达成"（带 1 条 P1 端到端缺口）。用户可见结果：判定"未达成"（缺部署，非本次代码缺陷）。**

一句话展开：**本次交付在代码/测试层把 #4677 的 A~E 全部要求做成了可执行、带红证的行为**（两层分区、车间分组折叠、列收窄、打包发货一列价逐字用服务端 4 态、🔴【布料单】小区真的能读写 `裁剪 × 布料`/`打包 × 布料` 两格且不依赖「布料」列、#4674 死路四条约束、就绪度②点名、补套入口缺失即显示、#4692 删除路径不回退），**`GET /operation-layers` 从"零前端调用点"变成"有发射点 + 默认 tab 首屏可达 + 有测试钉住"（v1.11 三问齐备）**；
> **但有一条 P1 端到端缺口：D6①「第二层的行不依赖矩阵格」只在「服务端已给出该行」时成立** —— 后端 `delivery` 段本身仍按**矩阵行**分区（`ProductionRoutingReadService.operationLayers` 遍历 `operationPositions()`，只读矩阵表），实测 `scope='set'` 且**零矩阵格**的工序在 delivery 段**一行都没有**（§3.3 `PROBE delivery operations = [打包]`）⇒ 该形态下【打包发货】层无行、无 `管理▸`、抽屉打不开（见 **P1-2**）；前端 `B6-①` 之所以绿，是因为它**手造**了服务端行。**另：交付件（`efa59d98a`）尚未部署到任何活环境**（三条部署腿最后部署的都是其父提交 `b364a7eb5`）⇒ **商家今天打开界面看不到这套改造**；叠加 #4707（OPEN，租户 20/21 的 `production_operations` 0 行）与 V88/V89/V90 迁移的应用状态不可得 ⇒ **"用户可见地解决了"这一条，本次判为「未达成」，缺口是"部署 + 依赖单"而不是本次代码**。

---

## 1. 验收矩阵（验收点 × L1/L2/UA × 判定）

> L1 = 机器可判断言（本会话前台直接执行，退出码可查）；L2 = 需活环境/浏览器/活库的证据；UA = AI 用户代理判定。
> **无"待人工"**；**非全 UA**（24 条 L1 + 1 条 UA + 4 条 L2 = 29 条）。

| # | 验收点 | 层 | 判定 | 证据引用 |
|---|---|---|---|---|
| P1 | 页面**真的调** `GET /operation-layers`（改前零调用点 = 上轮 P0-1） | L1 | ✅ 成立 | `frontend/admin-web/tests/unit/pages/production-routings.test.tsx:4105`；红证 R3-INJ1（`Tests 2 failed`） |
| P2 | 入口可达：默认 tab「工艺项」首屏即触发（无二次跳转） | L1 | ✅ 成立 | `:4111`（`toHaveBeenCalledTimes(1)`）；红证 R3-INJ1 |
| P3 | 【工序】层按**车间分组可折叠**（裁剪（裁床）/ 车位（缝制）/ 后整（烫工及后整）/ 质检） | L1 | ✅ 成立 | `:3822` B2；红证 R3-INJ5 |
| P4 | 列**收窄**到 布帘/纱帘/帘头（**不含** 布料） | L1 | ✅ 成立 | `:3874` B4（列头逐字 `['工序','布帘','纱帘','帘头','元数据 / 操作']`）；红证 R3-INJ2 |
| P5 | 界面**不出现**「槽位」这类发明词 | L1 | ✅ 成立 | `:3849`（`expect(getByTestId('craft-operations-panel')).not.toHaveTextContent('槽位')`） |
| P6 | 【打包发货】层 = `scope='set'` 成员**一列价**（一行一价，非 4 格） | L1 | ✅ 成立 | `:3851` B3（`getAllByRole('columnheader')` 恰三列；`getAllByTestId(/^matrix-cell-/)` = 0） |
| P7 | `price_state` **逐字用服务端聚合**（4 态），前端**不重算** | L1 | ✅ 成立（**交付测试不可证伪，验收补红证**） | `frontend/admin-web/src/app/(dashboard)/production/routings/frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:2961-2983`（`data-price-state={row.price_state}` + 4 分支只读该键）；红证 §3-INJ8/9/10 + **§3.2 补口红证**；缺口见 P2-8 |
| P8 | `unpriced` **≠ ¥0.00** | L1 | ✅ 成立 | `:3914` B7-①（`not.toHaveTextContent('¥')`）；红证 R3-INJ8 |
| P9 | `multiple_prices` **不静默取第一个** + 计数 | L1 | ✅ 成立 | `:3925` B7-②（`各部位不同价（2 处）`，两个价都不显示）；红证 R3-INJ9 |
| P10 | `no_applicable_position` 如实报出（不假装成 0 元/未定价） | L1 | ✅ 成立 | `:3938` B7-③；红证 R3-INJ10 |
| P11 | 🔴 **【布料单】小区存在**，`裁剪`+`打包` 各一行一列价 | L1 | ✅ 成立 | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:3020` `data-testid="fabric-sheet-section"`；`:3044` `fabric-sheet-row-{裁剪,打包}`；红证 R3-INJ3 |
| P12 | 🔴 能**读写** `裁剪 × 布料`（`PUT /operation-positions/lc-8`，body **恰为** `{unit_price}`） | L1 | ✅ 成立 | `:4002`（`:4032` `expect(Object.keys(call[1])).toEqual(['unit_price'])`） |
| P12b | 🔴 能**读写** `打包 × 布料`（`PUT /operation-positions/lc-12`） | L1 | ✅ 成立（**交付测试未覆盖，验收探针实测**） | **验收探针**（§3.1）：`toHaveBeenCalledWith('lc-12', { unit_price: 2.25 })` → `Tests 1 passed`；交付测试里 `lc-12` 零命中（见 P2-7） |
| P13 | 🔴 **不依赖矩阵里有「布料」列**（列收窄后仍可定价） | L1 | ✅ 成立 | `:4005`（`within(workshop).queryByTestId('matrix-cell-裁剪-布料')` **为 null** 的前提下，`within(fabric)` 里该格 `priced` ¥7.00） |
| P14 | 格缺失时**空态给出路**（两个**可点**动作，无页面里没有的指引） | L1 | ✅ 成立 | `:4035`（`fabric-sheet-attach-*` 真开 `orphan-attach-list`；`fabric-sheet-seed-*` 真到 `seed-template-apply-curtain`；`not.toHaveTextContent('请核对各部位的适用性配置')`） |
| P15 | #4674-① 第二层的行**不依赖矩阵格**（一格都没有 ⇒ 仍有行 + `管理▸`） | L1 | ⚠️ **仅前端渲染层成立；端到端不成立** | `:3950` B6-①（但**手造**服务端行）；后端实测 `PROBE delivery operations = [打包]`（§3.3）⇒ 见 **P1-2** |
| P16 | #4674-② `管理▸` **在行上** | L1 | ✅ 成立 | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:591-607` `ManageButton`，`:2894`（工序层行尾）/ `:2999`（打包发货层行尾）/ `:3107`（布料单行尾） |
| P17 | #4674-③ 停用/删除渲染在 `manageVariants.map(...)` **循环体外** | L1 | ✅ 成立 | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:3913-3990`（`manageVariants.length === 0 ? 空态 : <div>…map…</div>`，`:3967` 是 `manageVariants.map(...)`），`footer` 在 `:3857-3891`（`operations-manage-disable` `:3872` / `-delete` `:3881` / `-close` `:3890`，**循环体之外**）；红证 R3-INJ11 |
| P18 | #4674-④ 空态**给出路**且**可点**（enabled，非只渲染） | L1 | ✅ 成立 | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:3916-3947`（两个 `Button` + 解释「为什么空」）；**验收探针** `not.toBeDisabled()` → `Tests 1 passed`（R4.1） |
| P19 | 就绪度② 改成「**两条基础路线是否齐**」并**点名** | L1 | ✅ 成立 | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1661-1670`（`BASE_ROUTE_NAMES` + `missingBaseRoutes` + `routingsReady`）；`:2575-2584`（`基础路线 1/2 条 · 缺 布料工序路线`）；红证 R3-INJ6 |
| P20 | 补套入口改成「**缺失即显示**」（幂等） | L1 | ✅ 成立 | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:2617`（`(!operationsReady \|\| missingBaseRoutes.length > 0) &&`）；反向护栏 `:4072`；红证 R3-INJ7 |
| P21 | #4692 删除路径**不回退**（判据按名字 + `detachPositions: true`） | L1 | ✅ 成立 | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1520-1522`（`opDeleteBlockerCells` 按行键）+ `:2366-2372`；测试 `:1742 #4692-A` … `:1830/#4692-E`；红证 R3-INJ12（`Tests 4 failed \| 2 passed`） |
| P22 | #4665 / #4671 / #4650 阶段 1 / #4614 **原样保留** | L1 | ✅ 成立（**注**：#4614 的「读面那一格仍在」无断言，见 P2-3） | 全量 `npx vitest run` = **2395 passed / 1 skipped**（含这四单的既有断言，**未放宽**）；`check-ui-regression.sh` exit 0 |
| P23 | 否决方案①（工序库行价）的理由成立 | L1 | ✅ 成立 | `V49__create_production_operations_and_work_logs.sql:15` 逐字 `unit_price NUMERIC(10,2) NOT NULL DEFAULT 0` |
| P24 | 界面在**真实浏览器**里渲染正确（HTML 合法 / 布局） | L2 | ❌ **未达成** | 唯一产出 `<td>` 嵌 `<td>` 的非法嵌套（见 §5-P2-1）；PR 门禁的 Playwright quality specs（`pr-check.yml:187`）**不含** routings 页（`grep -rln "routings\|工艺项" tests/e2e/` 零命中） |
| P25 | 加工单「第 N 套」：布料单实例化 = `裁剪`+`打包` **2 道** | L2 | ⚠️ **证据不足** | 静态侧成立（`ProductionSeedTemplateService.java:112` `List.of("裁剪","打包")`；`test_fabric_route_seed.py:45` `FABRIC_MAINLINE_EFFECTIVE = ("裁剪","打包")`）；**活库未采集**（无活库/无浏览器）⇒ 见 §5-P2-5 |
| P26 | 真实环境用户看到【布料单】入口 | L2 | ❌ **未达成** | 交付 SHA `efa59d98a` **无任何 deploy-* run**；三条部署腿最后部署 `b364a7eb5`（R6） |
| P27 | 「布料」相关入口在**缺布料种子的租户**上可见 | L2 | ❌ **未达成** | #4685 CLOSED（PR #4706 MERGED，V89）但**未部署**；#4707 **OPEN**（租户 20/21 `production_operations` 0 行）；活环境 SHA/迁移版本**不可得**（R6.1） |
| P28 | UA：界面文案可懂度（商家视角） | UA | ✅ 通过 | persona = **低学历窗帘厂老板**（不做技术、只看中文）；基准对照见 §1.1 |

### 1.1 UA 判定（persona 声明 + 基准对照 + 原文引用）

- **persona**：低学历窗帘厂老板（车间出身，会看中文，不认「槽位 / 作用域 / 变体 / 锚点」这类词）。
- **可懂度基准**（`migao-acceptance` 通过线：信息准确 + 给出口 + 不编造）：逐条给分。

| 界面文案（逐字引用） | 信息准确 | 给出口 | 不编造 | 判定 |
|---|---|---|---|---|
| `【打包发货】` / `这几道活不按部位分（一樘窗只做一次）⇒ 一个价`（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:2914/2919`） | ✅ | — | ✅ | 通过 |
| `未定价` + `title="有部位还没定价（≠ ¥0.00）"`（`:2961/2964`） | ✅ | — | ✅ | 通过（**不把未定价说成 0 元**） |
| `各部位不同价（{N} 处）` + `title="各部位不同价 —— 到「管理▸」里逐个部位看"`（`:2979/2966`） | ✅ | ✅ 指名「管理▸」 | ✅ | 通过（**不静默取第一个**） |
| `未设置（没有部位设为「做」）`（`:2982`） | ✅ | — | ✅ | 通过 |
| `卖布按米、不走窗帘那三个部位 ⇒「布料」不出现在上面的列里，但布料单一样要算这两道活的计件钱。**这里就是给它定价的地方**`（`:3025-3029`） | ✅ | ✅ 指名「这里」 | ✅ | 通过（**正面回答了用户的原始困惑**） |
| `没有「裁剪 × 布料」这一格 ⇒ 现在没法定价` + `接入部位…` / `补套行业模板`（`:3074-3090`） | ✅ | ✅ 两个可点动作 | ✅ | 通过（**不是**「请核对各部位的适用性配置」这类页面里没有的指引） |
| `基础路线 1/2 条 · 缺 布料工序路线`（`:2582`） | ✅ | — | ✅ | 通过（**点名**，不是只数条数） |
| 观察项（不阻塞）：`每樘窗一次的交付活`、`作用域：套级 = 每樘窗只做一次`（`:2916` / `:3900`） | ✅ | — | ✅ | 通过（密度/术语属观察项，按 `migao-acceptance` 不为"短句"字面判红） |

**UA 结论：通过。** 界面**一律不出现「槽位」**（L1 已钉住，`B2` 末尾断言），且「布料单」小区的文案**直接回答**了 issue 里用户的原始困惑（「我到现在仍然不知道如何在系统上完成配置」）。

---

## 2. 待核主张 A~E 的逐条判定

### A. 两层结构

**A1【工序】层：按车间分组可折叠 + 列收窄到 布帘/纱帘/帘头（不含布料）** —— ✅ **成立**

- 分组取值：`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1295-1312` `workshopGroups`（`key = distinctMeta(row, c => c.group).join(' / ') || ''`，认不出的组照原样追加）；
  折叠：`:2796-2810`（`aria-expanded={openWorkshops[...] !== false}` + `▸/▾`），渲染门在 `:2813`。
- 列收窄：`:179-182` `matrixColumnsOf` = `POSITION_DOMAIN.filter(p => present.has(p))`，`POSITION_DOMAIN = ['布帘','纱帘','帘头']`（`:136`）。
- **红证**：INJ5（折叠条件恒真）⇒ `B2` 红；INJ2（`return [...present]`）⇒ `B4` 红。
- 行业正名：`WORKSHOP_LABEL`（`:149-157`）`裁剪→裁剪（裁床）`/`车位→车位（缝制）`/`后道→后整（烫工及后整）`/`质检`；**注意** DB 里 `group_name` 实测值是 `后道`（`V49:13` 注释逐字「裁剪/车位/后道/其他」），故映射表**同时**收录 `后整` 与 `后道` 两个前缀（`:153-154`）—— 照实登记为口径细节。

**A2【打包发货】层：`scope='set'` 成员一列价，逐字用服务端 4 态（前端不重算）** —— ✅ **成立**

- 分区判据：`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1265-1268` `operationsRows = matrixRows.filter(r => !deliveryOps.has(r.operation))`；`deliveryRows`（`:1317-1349`）= 服务端 `delivery` 段 ∪ 矩阵里 `scope==='set'` 的格。
- **逐字用服务端**：`:2961-2983` 渲染分支**只读** `row.price_state`；`data-price-state={row.price_state}` 逐字透出。
- **前端不重算（代码层成立，但交付测试**无红证**）**：全仓 grep `price_state` 只有 3 处（`frontend/admin-web/src/types/index.ts:1022` 类型、`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:2961/2964/2966/2979/2982` 读、`:1337` 的**兜底行**构造）—— 代码里**没有**按格价自行聚合的逻辑。
  ⚠️ **但交付测试证伪不了这条**：测试的 `buildLayers(夹具)`（`:423-459`）从**同一份夹具格**推导服务端 `delivery` 段 ⇒ 服务端值与前端重算值**构造性相等**。复核 agent 注入「前端忽略 `price_state` 自行重算」⇒ **`B7-①/②/③` 全绿**（3 passed）。
  ⇒ 本次验收**独立补了一条可证伪的红证**（§3.2）：让服务端 `price_state='priced'/price=9.99` 与矩阵格 `unpriced` **故意不一致** ⇒ 页面必须显示 `¥9.99`；注入「前端重算」后该断言**必红**（实测）。⇒ **"逐字取自服务端"成立**（值级证据），但**交付测试未钉住**（P2-8）。
- ⚠️ **登记一处非"逐字"路径**：`:1330-1345`（`:1337` 是固定值），服务端**没有**给这一行时，前端从格上重建一行并**固定** `price_state: 'no_applicable_position'`（不猜价）。真实后端 `operationLayers` 对每个有 `scope='set'` 格的工序**必然**给行（`ProductionRoutingReadService.java:178-188`）⇒ 该分支**只在服务端漏行时**可达；`B6-①` 的夹具正是这种"服务端给了行"的形态。⇒ 归因强度：**存在性级**（代码存在该分支），**不构成"前端重算价态"**，但**未逐字**，如实登记。

### B. 🔴 硬要求

**B1 该小区真的存在** —— ✅ **成立**：`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:3020` `<section … data-testid="fabric-sheet-section">`，标题逐字 `【布料单】`（`:3023`）、副标题 `裁剪 + 打包 · 一列价（布料单按此价）`（`:3024`）。

**B2 能读写 `裁剪 × 布料` / `打包 × 布料` 两格** —— ✅ **成立**

- 行来源：`:190` `FABRIC_SHEET_OPERATIONS = ['裁剪','打包']`、`:193` `FABRIC_SHEET_POSITION = '布料'`；`:1360-1369` `fabricSheetRows` 取 `matrixRows.find(r => r.operation === operation)?.cells.get('布料')`。
- 读：`:3056-3071` 复用**主表同一个** `PositionCell`（同一三态口径）。
- 写：`onSave={() => r.cell && saveCellPrice(r.cell)}` → 既有 `PUT /operation-positions/{id}`（`api.ts:543`）。
- **测试逐字**：`:4002-4033`，`within(fabric).getByTestId('matrix-cell-裁剪-布料')` → `data-state="priced"` + `¥7.00`；改价后 `expect(mockUpdateOperationPosition).toHaveBeenCalledWith('lc-8', { unit_price: 8.5 })`，且 `expect(Object.keys(call[1])).toEqual(['unit_price'])`。

**B3 不依赖矩阵里有「布料」列** —— ✅ **成立**

- 该小区**不经** `matrixColumns`：它直接用 `FABRIC_SHEET_POSITION` 常量取格（`:1364`），与列渲染路径（`:2775` `matrixColumns.map`）**无交集**。
- **测试逐字**（同一用例内先证否、再证有）：`:4005-4006` `expect(within(workshop).queryByTestId('matrix-cell-裁剪-布料')).toBeNull()`（列里**没有**）→ `:4012` `within(fabric).getByTestId('matrix-cell-裁剪-布料')`（小区里**有**）。

**B4 否决方案①（工序库行价）的理由是否成立** —— ✅ **理由成立**（独立核验）

- 理由（实施方）：`production_operations.unit_price` 是 `NOT NULL DEFAULT 0` ⇒ 用它当"布料单按此价"会把**未定价**显示成**真 ¥0.00**。
- 独立取证：`V49__create_production_operations_and_work_logs.sql:15` 逐字 `unit_price NUMERIC(10,2) NOT NULL DEFAULT 0,     -- 计件单价（元/单位）`。**值级证据**（DDL 原文）⇒ 成立。
- 补充（实施方另一条理由）：`buildRoute` 的回落条件是「格存在 + `applicable=TRUE` + 价 `NULL`」—— 独立核验：`ProcessingOrderService.java:1259-1269`，`if (applicable == null) { … continue; }`（格不存在 ⇒ 滤掉，**不回落**），价 `NULL` 才回落。⇒ 「格不存在时方案①根本不参与实例化」**成立**（存在性 + 值级证据）。
- **归因强度声明**：以上证明「方案①**会**把未定价变成 ¥0.00」这一**机制**；**未**证明「方案②是唯一可行方案」（例如"先给工序库行价补未定价语义再走①"也是设计 §8 U6 登记过的前置单路线）⇒ 只判「否决①的理由成立」，**不判**「选②是唯一正确解」。

### C. 交付物可达性（v1.11 三问） —— ✅ **成立（P0-1 已闭合）**

| 三问 | 答案 | 锚点 |
|---|---|---|
| **谁发射** | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:989` `productionApi.getOperationLayers(),`（在 `load()` 的 `Promise.allSettled` 内） | `:986-992` |
| **哪个入口可达** | 「工艺项」tab = **默认 tab**（`:2668` `{ key: 'operations', label: '工艺项' }`），面板 `:2700` `craft-operations-panel` 在 `tab === 'operations'` 分支 ⇒ **首屏即触发** | `:2668` / `:2700` |
| **有无测试钉住** | 有，2 条：`:4105`（`toHaveBeenCalled()`）+ `:4111`（`toHaveBeenCalledTimes(1)`） | `:4105-4116` |

- **红证**：R3-INJ1（把调用换成 `Promise.resolve({operations:[],delivery:[]})`）⇒ 这 2 条**同时红**（`Tests 2 failed | 168 skipped`）⇒ **不是空断言**。

### D. 其它

**D5 未定价不得显示成 ¥0.00（三态语义）** —— ✅ **成立**：工序层 `cellState`（`:1270-1275`）三态 `na/unpriced/priced`；`PositionCell`（`:640-730`）三态**不同形**；交付层 `B7-①`（`:3914`）+ 红证 INJ8。工序层反向护栏 `B5`（`:3893`）逐字断言 `data-state="unpriced"` 且 `not.toHaveTextContent('¥')`。

**D6 #4674 那个死路从根上避免（四条约束）** —— ✅ **四条全部成立**

| 约束 | 判定 | 锚点 | 红证 |
|---|---|---|---|
| ① 第二层的行不依赖矩阵格 | ⚠️ **仅前端渲染层成立；端到端不成立** | `:1317-1349`（服务端 `delivery` 段 ∪ 格）——**但服务端那段本身也按矩阵行分区**：`ProductionRoutingReadService.operationLayers`（`:174-185`）遍历的是 `operationPositions(tenantId)`（`:138-154`，**只读矩阵表** `productionOperationPositionMapper.selectList`）⇒ **`scope='set'` 且零矩阵格的工序，服务端 `delivery` 段根本不给行**；前端兜底分支（`:1330-1345`）同样只能从格造行。**实测红证**：§3.3 后端探针 `PROBE delivery operations = [打包]`（期望含 `外帘装袋`/`外帘打卷`，实测缺） | INJ4 ⇒ `B6-①` 红（但 `B6-①` 是**手造** delivery 行，见 P1-2） |
| ② `管理▸` 移到行上 | ✅ | `ManageButton`（`:591-607`）用在 `:2894`（工序层行尾）/ `:2999`（打包发货行尾）/ `:3107`（布料单行尾） | —（读码；`B6-②` 点 `delivery-manage-外帘装袋` 真开抽屉） |
| ③ 停用/删除在 `manageVariants.map(...)` 循环体外 | ✅ | `:3913` 是 `{manageVariants.length === 0 ? (`，`:3967` 是 `{manageVariants.map((v) => (`；`footer`（`:3857-3891`，含 `operations-manage-disable` `:3872` / `-delete` `:3881`）在**整个**条件式**之外** | INJ11（空态隐藏两者）⇒ `B6-②` 红 |
| ④ 空态给出路 | ✅ | `:3916-3947`：说清**为什么**空（`有 N 个格，而这些格都没有关联到它` / `还没有任何格`）+ 两个**可点**动作（`接入部位…` / `删除这道工序`） | 探针 `not.toBeDisabled()` 通过（R4.1） |

**D7 就绪度②：从"数条数"改成"两条基础路线是否齐"并点名** —— ✅ **成立**：`:1663-1670`（`BASE_ROUTE_NAMES = ['窗帘工序路线（默认）','布料工序路线']` 与后端常量逐字同名；`routingsReady = missingBaseRoutes.length === 0 && emptyShells.length === 0`）；UI `:2575-2584`；红证 INJ6（回退成数条数 ⇒ `§6-②` 红）。

**D8 补套入口：从"只在工序库为空时显示"改成"缺失即显示"（幂等）** —— ✅ **成立**：`:2617` `{(!operationsReady || missingBaseRoutes.length > 0) && (`；反向护栏 `:4072`（两条齐 ⇒ **不显示**，不是常驻噪音）；红证 INJ7。
- ⚠️ 登记：`routingsReady` 含 `emptyShells.length === 0`，但**入口条件不含**空壳（`:2607-2616` 注释已说明「空壳路线不是种子能补的」）⇒ 空壳态下就绪度② 为 `todo` 而补套入口**不显示**，此时靠 `routing-empty-shell-{id}` 的就地入口（`:3201`）。**照实登记为口径细节**，非缺陷。

**D9 #4692 删除路径不得回退；#4665/#4671/#4650 阶段 1/#4614 原样保留** —— ✅ **成立**

- #4692：判据 = `opDeleteBlockerCells`（`:1520-1522`，**按行键/名字**，不看 `variant_operation_id`）；路径 `:2366-2372`（有"做"的格 ⇒ `deleteOperation(id, { detachPositions: true })`；否则普通软删）。测试 `:1742 #4692-A` / `:1768 #4692-B`（注入"FE 按 id 判"⇒ 必红）/ `:1790 #4692-C` / `:1812 #4692-D` / `:1830 #4692-E`。**红证** INJ12（`if (false)` 回退）⇒ `Tests 4 failed | 2 passed`。
- 原样保留：全量 **2395 passed / 1 skipped**（0 failed），含这四单既有断言；`#4614` 的列收窄回归见 `:3091`（`判据③ 改判（#4677）：工序层列收窄到三部位（90 格）；布料 不再当列，但读面一格未丢`）。

### E. 用户可见结果 —— ❌ **未达成**（缺口 = 部署 + 依赖单，非本次代码）

用户的原始诉求（issue #4677 评论逐字）：「**布料的工序&计价问题，我到现在仍然不知道如何在系统上完成配置**」+「**建不出纯布料路线**」。

| 诉求 | 代码层 | 用户可见层 | 缺口 |
|---|---|---|---|
| 给布料单的 `裁剪`/`打包` 定价 | ✅ 已做（【布料单】小区，P11~P14） | ❌ **看不到** | 交付 SHA `efa59d98a` **未部署**（R6） |
| 建出纯布料路线 | ✅ 既有能力（`新建路线`勾「布料」，`:3074` describe） | ❌ **看不到** | ① 未部署；② 缺布料种子的租户（#4685 的 V89）**未部署**；③ 租户 20/21 `production_operations` 0 行（**#4707 OPEN**） |
| 「工序项要有公共工序分区」 | ✅ 已做（两层 + 车间分组） | ❌ **看不到** | 未部署 |

**还缺哪几步**（可执行清单）：
1. **部署** `efa59d98a`（或其后继）到云测试环境：`deploy-frontend.yml` + `deploy-admin-api.yml`（三条腿当前都停在 `b364a7eb5`）；
2. **确认迁移应用**：`V88`（配料退场 / 布料主线改 `裁剪,打包` / 保命格）、`V89`（#4685 补种布料种子）、`V90`（#4696 未定价≠0）在活库上真的跑过 —— 本次**无法从外部判定**（活环境鉴权 401 / 前端域名不可达，R6）；
3. **等 #4707 收口**（租户 20/21 的 `production_operations` 0 行 ⇒ 窗帘单本来就 fail-closed 422）；
4. 部署后**在真实浏览器**走一遍 J1~J19 旅程（尤其 J10 就地改价、J11 空态两个动作、J14 抽屉空态删除）。

---

## 3. 红证（关键断言的负向夹具与实测输出）

**方法与卫生**（协议 v1.12 / #4260 / #4313）：基线 `sha256` 内容指纹 → 逐字节内联锚点注入（`count==1` 否则失败）→ **自证注入生效**（指纹变化）→ **清缓存**（`node_modules/.vite` / `.next/cache`）→ 跑目标测试 → 还原 → **自证还原 = 基线指纹**。
**锚点出处 = `@efa59d98a` 的交付源码**（不读 `origin/main` 移动靶）。

| # | 注入（把被测行为改坏） | 目标用例 | 实测 |
|---|---|---|---|
| INJ1 | `getOperationLayers()` → `Promise.resolve({operations:[],delivery:[]})` | `v1.11` ×2 | **RED_OK** `Tests 2 failed \| 168 skipped` |
| INJ2 | `matrixColumnsOf` → `return [...present]`（列不收窄） | `B4` | **RED_OK** `1 failed` |
| INJ3 | `FABRIC_SHEET_OPERATIONS` → `[]`（隐藏布料单小区） | `硬要求：商家能…` | **RED_OK** `1 failed` |
| INJ4 | 删 `deliveryAgg.forEach(...)`（第二层依赖矩阵格） | `B6-①` | **RED_OK** `1 failed` |
| INJ5 | 折叠条件 → `{true &&` | `B2` | **RED_OK** `1 failed` |
| INJ6 | `routingsReady` → `routeList.length > 0 && …`（数条数） | `§6-②` | **RED_OK** `1 failed` |
| INJ7 | 入口条件 → `{!operationsReady && (` | `§6-①` | **RED_OK** `1 failed` |
| INJ8 | `unpriced` → `{money(0)}`（未定价显示成 ¥0.00） | `B7-①` | **RED_OK** `1 failed` |
| INJ9 | `multiple_prices` → `{money(row.price ?? 0)}`（静默取第一个） | `B7-②` | **RED_OK** `1 failed` |
| INJ10 | `no_applicable_position` → `未定价`（谎报） | `B7-③` | **RED_OK** `1 failed` |
| INJ11 | 空态隐藏停用/删除（#4674 死路本体） | `B6-②` | **RED_OK** `1 failed` |
| INJ12 | `if (opDeleteBlockerCells.length > 0)` → `if (false)`（#4692 回退） | `4692` | **RED_OK** `Tests 4 failed \| 2 passed` |
| INJ13/14 | 列只留 `布料` / 列返回 `[]`（方向性对照，定位 B4 红在哪条断言） | `B4` | **RED_OK** ×2 |
| **对照** | **锚点不改（old == new）** | `B6-②` | **INJECT_NOOP**（harness 明确报"注入未生效"）⇒ **证明 harness 不会假报红** |

每条跑完 `shasum -a 256 page.tsx` 恒 = `0176604778…a003e9`，`git status --porcelain` 为空。

**验收探针（补强 B6-②）**：注入式红证之外，独立加一条 `expect(getByTestId('operations-manage-delete')).not.toBeDisabled()` → `Tests 1 passed`（证明"出路"是**可点**的，不只是渲染出来）；探针跑完已还原测试文件。

---

## 4. 复核抽验（双 AI 交叉验证）

- **主验收**：DeepSeek（本会话，DSH）。
- **复核验收**：GLM-5.3-Flash（provider `scnet-token-plan`），**独立视角**：自己读码 + 自己挑 2~3 条断言做注入式红证，**不看**主验收的结论。

| 项 | 主验收 | 复核验收 | 差异处置 |
|---|---|---|---|
| A1 工序层分组折叠 + 列收窄 | 成立 | 见 §4.1 | — |
| A2 一列价逐字用服务端 4 态 | 成立（登记一处"服务端漏行"兜底分支） | 见 §4.1 | — |
| B 硬要求（布料单小区可读写、不依赖布料列） | 成立 | 见 §4.1 | — |
| C v1.11 三问 | 成立 | 见 §4.1 | — |
| D6 四条约束 | 成立 | 见 §4.1 | — |
| 抽样红证 | 14 条注入 | 见 §4.1 | — |
| 主验收可能漏判的一条 | — | 见 §4.1 | — |

### 4.1 复核结论

**复核裁判**：GLM-5.3-Flash（provider `scnet-token-plan`，与主验收**不同模型族**），**不看**主验收结论、独立读码 + 独立抽样 6 条注入式红证。
**完整性自证**：`page.tsx` BASE `0176604778…a003e9`，6 次注入**逐次还原后都 == BASE**；基线全量 `170 passed`（注入前后各一次）。

| 项 | 主验收（初判） | 复核验收 | 处置 |
|---|---|---|---|
| a) 分组折叠 + 列收窄 | 成立 | **成立** | 一致 |
| b) 一列价 4 态逐字取自服务端 | 成立（已登记兜底分支） | **渲染成立，但「不重算」无红证** | **复核更严 ⇒ 采纳**：主验收补 §3.2 可证伪红证；新增 P2-8 |
| c) 布料单读写两格、不依赖布料列 | 成立（已补 `打包` 写面探针） | **成立**（`打包` 写无独立用例） | 一致（主验收 P2-7 + 复核，同一结论） |
| d)②③④ | 成立 | **成立** | 一致 |
| **d)① 第二层行不依赖矩阵格** | 成立（据前端代码） | **前端渲染成立、端到端不成立** | **🔴 复核推翻主验收初判** ⇒ 主验收复现（§3.3 `PROBE delivery operations = [打包]`）后**采纳**，改判 + 新增 **P1-2** |
| `B4` 内恒真空断言 | 已发现（P2-3） | 独立复现（注入 5：B4 绿） | 一致（复核另指出它由 `硬要求` 那条覆盖 ⇒ 建议删除） |
| DOM `<td>` 嵌 `<td>` | 已发现（P2-1） | 独立复现 + **补充影响边界**（`'use client'` + `!loading` 门控 ⇒ SSR 不含该 HTML，故不触发解析器多出一列；影响限于客户端渲染的内边距/列宽/对齐） | **复核更精确 ⇒ 采纳**（P2-1 已补该边界） |
| `deliveryOps` 注释漂移 | 未发现 | **发现** | **采纳** ⇒ 新增 P2-9 |
| `operation-layers` 失败无错误面 | 未发现 | **发现** | **采纳** ⇒ 新增 P2-10 |
| 假红陷阱 `-t "#4677"` | 未遇到（本次用 `-t "B6-②"` 等精确片段） | **发现**：`-t "#4677"` 会匹配 describe 外的 `判据③ 改判（#4677）`（`:3091`）⇒ `Test timed out in 5000ms`（**假红**；全量跑是绿的） | **采纳**：登记为测试写法陷阱（§7 假红行） |

**不一致处置**：1 处实质性不一致（d①），**以证据引用充分者为准 = 复核验收**（主验收已独立复现其判据并改正记录，非静默改口径）。
**复核未覆盖**：未重跑主验收的注入矩阵；未跑 `verify-all.sh` / `check-ui-regression.sh` / `contract-check.sh`；未派发真实 LLM 评测；`<td>` 嵌套的**真实视觉后果**（需真浏览器）与生产库是否真有"零格 set 工序"数据**未判定**（照实）。

---

### 3.1 验收探针：硬要求写的是**两格**，交付测试只覆盖了其中一格

issue 硬要求逐字是「给布料单的 `裁剪` **与** `打包` 定价」。交付测试 `:4002-4033` 只对 `裁剪 × 布料`（`lc-8`）做了**写**断言，`打包 × 布料`（`lc-12`）只做了**读**断言（`:4020` `toHaveTextContent('¥1.50')`）；`grep -n "'lc-12'" production-routings.test.tsx` → **仅命中夹具定义**（`:3755`），**无写面断言**。

独立探针（加在 describe 末尾，跑完已还原测试文件，`git status` 无改动）：

```ts
  it('【验收探针】硬要求写的是两格：`打包 × 布料` 是否也能就地写（lc-12）', async () => {
    await renderOperations()
    const fabric = screen.getByTestId('fabric-sheet-section')
    expect(within(fabric).getAllByTestId('matrix-cell-打包-布料')).toHaveLength(1)
    await userEvent.click(within(fabric).getAllByTestId('matrix-price-edit-打包-布料')[0])
    const input = within(fabric).getAllByTestId('matrix-price-input-打包-布料')[0]
    await userEvent.clear(input); await userEvent.type(input, '2.25')
    await userEvent.click(within(fabric).getAllByTestId('matrix-price-save-打包-布料')[0])
    await waitFor(() => expect(mockUpdateOperationPosition).toHaveBeenCalledWith('lc-12', { unit_price: 2.25 }))
    expect(Object.keys(mockUpdateOperationPosition.mock.calls[0][1] as object)).toEqual(['unit_price'])
  })
```

```
 ✓ tests/unit/pages/production-routings.test.tsx (171 tests | 170 skipped) 237ms
      Tests  1 passed | 170 skipped (171)
```

⇒ **`打包 × 布料` 写面实测可写**（`lc-12` + body 恰为 `{unit_price}`）；但**交付测试没钉住它** ⇒ 单列 P2-7（断言缺口，**非功能缺陷**）。
> ⚠️ 归因强度：**值级**（该夹具下真的发出了 `lc-12` 的写请求）。**不**等于"任何形态都可写"（例如 `lc-12` 缺失时走 `fabric-sheet-missing-打包` 空态分支 —— 该分支**有**代码，但测试只覆盖了 `裁剪` 的空态，`:4035`）。

### 3.2 红证补口：「逐字取自服务端（前端不重算）」原本**不可证伪**

复核 agent 注入「`deliveryRows` 忽略服务端 `price_state`、由矩阵格自行重算 4 态」⇒ **`B7-①/②/③` 3 passed 全绿** ⇒ 交付测试**抓不住**这条口径（因 `buildLayers(夹具)` 从同一份格推导 ⇒ 两值构造性相等）。

本次验收**独立补一条可证伪的红证**（探针：服务端与矩阵格故意不一致）：

```ts
  it('【验收探针】「逐字取自服务端」可证伪：服务端说 priced，矩阵格说未定价 ⇒ 必须显示 ¥9.99', async () => {
    mockGetOperationLayers.mockResolvedValue(ok({
      operations: LAYER_CELLS,
      delivery: [{ operation: '外帘装袋', scope: 'set', unit: '套', group: '后道', is_must_finish: true,
                   price: 9.99, price_state: 'priced', different_price_count: 0, applicable_positions: ['布帘'] }],
    }))
    await renderOperations()
    const cell = screen.getByTestId('delivery-price-外帘装袋')
    expect(cell).toHaveAttribute('data-price-state', 'priced')
    expect(cell).toHaveTextContent('¥9.99')
    expect(cell).not.toHaveTextContent('未定价')   // 矩阵格里该工序是 unpriced ⇒ 自行重算必红
  })
```

| 状态 | 实测 |
|---|---|
| ① 交付源码（未注入） | `✓ 171 tests \| 170 skipped` → **`Tests 1 passed`** ⇒ 页面**逐字用服务端值** |
| ② 注入「前端重算」（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1317` 起 `recompute(...)`） | `× 【验收探针】…` → **`Tests 1 failed`**（`toHaveTextContent('¥9.99')` 失败）⇒ **该断言会红** |
| ③ 还原 | `shasum page.tsx` 回到 `0176604778…a003e9`；`git status` 干净 |

⇒ **A2「前端不重算」成立**（代码层 + 值级红证），**但交付测试未钉住** ⇒ 单列 **P2-8**。

### 3.3 后端红证：「第二层的行不依赖矩阵格」**端到端不成立**

D6① 的判据要在**后端读面**上验。独立探针（加在 `ProductionOperationLayersTest` 内，跑完已还原、指纹逐字相同 `e0eccfbe…d8d66`）：

```java
    @Test
    @DisplayName("【验收探针】真形态：`scope='set'` 且**零矩阵格**的工序 —— delivery 段有行吗？")
    void acceptanceProbe_zeroCellSetOperationStillHasDeliveryRow() {
        stubPackingCatalog();                       // 工序库：打包 / 外帘打卷 / 外帘装袋 三行均 scope='set'
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("打包", "布帘", "1.50", true)));   // 矩阵里**只有 `打包` 一格**
        Map<String, Object> layers = service().operationLayers(TENANT);
        List<Map<String, Object>> delivery = (List<Map<String, Object>>) layers.get("delivery");
        System.out.println("PROBE delivery operations = " + delivery.stream().map(r -> r.get("operation")).toList());
        assertThat(delivery).extracting(r -> r.get("operation"))
                .as("零矩阵格的 scope='set' 工序也应有一行（#4674 从根上避免的第①条约束）")
                .containsExactly("打包", "外帘装袋", "外帘打卷");
    }
```

```
$ ./mvnw -q -o -Dtest=ProductionOperationLayersTest test
PROBE delivery operations = [打包]
[ERROR] Tests run: 8, Failures: 1, Errors: 0, Skipped: 0
[ERROR]   ProductionOperationLayersTest.acceptanceProbe_zeroCellSetOperationStillHasDeliveryRow:260
          [零矩阵格的 scope='set' 工序也应有一行（#4674 从根上避免的第①条约束）]
          but could not find the following elements:
```

⇒ **服务端 `delivery` 段只给出 `[打包]`**，零格的 `外帘装袋` / `外帘打卷` **一行都没有** ⇒ **D6①「第二层的行不依赖矩阵格」在端到端上不成立**（只在前端渲染层成立，且只在服务端已给行时）。

**为什么交付测试没抓到**（复核 agent 独立发现 + 本次核实）：
- 前端 `B6-①`（`:3950-3974`）用 `mockGetOperationLayers.mockResolvedValue(ok({… delivery:[…, {operation:'外帘装袋', price_state:'no_applicable_position', …}]}))` **手造**了服务端行；其注释（`:3952-3953`）声称「真后端的**分区读面**仍会给出这一行（它按 `production_operations` 的行分区，**不看格**）」—— **与实现不符**（`operationLayers` 按 `operationPositions()` 即矩阵行分区）。
- 后端 `backend/admin-api/src/test/java/com/migao/admin/service/ProductionOperationLayersTest.java:228-246` 的 `@DisplayName` 写「只剩一格（**甚至零格**）时仍有 delivery 行」，但 stub 是 `position("外帘装袋", "布帘", null, false)` = **有格、只是 `applicable=false`** ⇒ **零格从未被构造**。

---

## 5. 问题清单（P0/P1/P2 + 证据引用 + 归因）

### P0-1 · 交付件未部署 ⇒ 用户可见结果未达成

- **证据**：`gh run list --limit 60 … select(.headSha|startswith("efa59d98"))` → 仅 `case-redraft :: completed/skipped`（**无 deploy-* run**）；`deploy-frontend.yml` / `deploy-admin-api.yml` / `deploy-ai-agent-service.yml` 的**最新一条** headSha 均为 **`b364a7eb5`**（`efa59d98a` 的父提交）。
- **归因（机制级）**：`Deploy Reconcile` 的 cron 是 `*/20`，本次验收时点尚未对 `efa59d98a` 触发部署；**不是**代码缺陷。
- **影响**：商家今天打开界面看不到两层改造 / 【布料单】小区 / 就绪度点名。
- **修复方向**：部署 `efa59d98a`（或后继）到云测试环境后，在真实浏览器重走 J1~J19。

### P1-1 · 新行为未进用例库（`migao-dev-flow` §14）

- **证据**：`grep -rn "4677\|4676" .github/cases/` **零命中**（`grep -rln "4677" .github/cases/ | wc -l` = 0）。测试文件头部 `// case_ids: PG-020, PG-034, PG-053, PP-014, OR-041, UI-048`（`frontend/admin-web/tests/unit/pages/production-routings.test.tsx:1`）**全部是既有 case**，`QA Growth Gate` 因此通过。
- **归因**：**流程/资产缺口**（非产品缺陷）。用例库是"被迭代喂养的活资产"，缺触发时机就会与现实脱节。
- **修复方向**：为本次行为补 `.github/cases/**`（如 `PG-0xx`）—— 断言必须可执行（`order_before` / `forbidden_text` / `required_args` / `db_verify`），并跑 `render_cases.py` 提交生成物。

### P1-2 · 「第二层的行不依赖矩阵格」端到端不成立（后端 `delivery` 段仍按矩阵行分区）

- **证据**：`ProductionRoutingReadService.operationLayers`（`:174-185`）分区遍历的是 `operationPositions(tenantId)`（`:138-154`，**只读矩阵表**）；**实测**（§3.3）`PROBE delivery operations = [打包]` —— 零矩阵格的 `scope='set'` 工序（`外帘装袋`/`外帘打卷`）**一行都没有**。
- **归因（机制级）**：`delivery` 段的数据源是 `production_operation_positions`，不是 `production_operations` ⇒ 「零格仍有行」在**生产形态**下不成立。前端 `B6-①` 靠**手造**服务端行才绿（`:3958-3967`），后端同类用例的 DisplayName 写「甚至零格」但 stub 是「有格 + `applicable=false`」（`:232-234`）⇒ **两处都是"看起来覆盖了其实没测到"**（复核 agent 独立发现，本次复现）。
- **影响（存在性级，不夸大）**：该形态下【打包发货】层**无行** ⇒ 该工序**没有 `管理▸`** ⇒ 抽屉（及其中已正确实现的循环体外停用/删除）**打不开**。可用路径退化为「工序层顶部孤儿提示 → 接入部位（先建格）→ 才出现行/抽屉」。**不是**"无处可删"，但**不是** issue #4677 第 ① 条约束所声称的形态。
- **修复方向**：`delivery` 段改按 `production_operations` 的 `scope='set'` 行分区（或与之并集），并让前端 `B6-①` **不再手造**服务端行（改为让替身反映真实分区）；后端用例补**真零格**夹具。
- ⚠️ **归属**：`delivery` 段的实现属 **#4676**（后端读面，已合并）；#4677 的**前端**把「服务端会给行」当作既定前提（`:1317-1349` 注释 + `B6-①` 注释）。⇒ 记为**跨单缺口**，建议跟随 issue 同时收口。

### P2-8 · 「逐字取自服务端」交付测试不可证伪

- **证据**：复核 agent 注入「前端忽略 `price_state` 自行重算 4 态」⇒ `B7-①/②/③` **3 passed 全绿**；根因 = 测试 `buildLayers(夹具)`（`:423-459`）从同一份夹具格推导服务端段 ⇒ 两值构造性相等。
- **归因（值级）**：**断言缺口**（代码正确 —— §3.2 探针实测页面逐字用服务端值）。
- **修复方向**：把 §3.2 的探针（服务端与格故意不一致）落进 `B7` 组。

### P2-9 · `deliveryOps` 注释与实现不符（注释漂移）

- **证据**：`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1152-1158` 注释逐字「取自服务端的分区读面（`delivery` 段），**不是**「有没有矩阵格」」「`scope='set'` 的工序**恒有**一行 + `管理▸`」；而实现 `:1159-1162` 是 `new Set(matrix.filter(c => c.scope === 'set').map(c => c.operation))` —— **就是**按矩阵格取。且「恒有一行」在零格形态下为假（P1-2）。
- **归因（机制级）**：`migao-acceptance`「注释漂移 = 假绿来源」形态 —— 读注释的人会据此认为 ① 已达成。
- **修复方向**：改注释与实现同源；`deliveryOps` 若可改为消费服务端 `delivery` 段则一并改（并配红证）。

### P2-10 · `GET /operation-layers` 失败**无错误面** ⇒ 用假话代替报错

- **证据**：`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1018` `setDeliveryAgg(layersRes.status === 'fulfilled' ? … : [])` —— 失败时静默置空；对比矩阵失败有 `matrixError` + `operation-price-matrix-error`（`:2764`）。此时前端兜底（`:1330-1345`）把**有价**的 `scope='set'` 工序渲染成 `no_applicable_position` ⇒ 界面显示「**未设置（没有部位设为「做」）**」= **假话**。测试无覆盖。
- **归因（存在性级）**：**错误面缺口**（与 #4696「未定价 ≠ 0」同一族：界面不许把"读不到"说成"没配置"）。参照同页既有纪律：`catalogError` 显示「工序库 **读取失败**（≠ 没配）」（`:2565` 附近）—— 本端点**没有**对应处置。
- **修复方向**：加 `layersError` 状态 + 就地报错（不拿 `no_applicable_position` 顶替），并补红证。

### P2-1 · 【布料单】小区渲染出 `<td>` 嵌 `<td>` 的非法 DOM 嵌套

- **证据**：`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:3056-3071` —— `<td className="py-2.5 pr-4 align-top">` 内直接放 `PositionCell`；而 `PositionCell` 的根节点就是 `<td data-testid={\`matrix-cell-${key}\`}>`（`:640-642`）。实测 React 警告（stderr 逐字，**每个渲染该小区的用例都打一次**）：

  ```
  Warning: validateDOMNesting(...): <td> cannot appear as a child of <td>.
      at td
      at PositionCell (…/routings/page.tsx:421:3)
      at td
      at tr
  ```

  `grep -c validateDOMNesting`（单跑 `production-routings.test.tsx`）= 1。
- **归因（存在性级）**：**结构性缺陷**，归属本次交付（`fabric-sheet-section` 是 #4677 新增，`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:3020` 起）。`jsdom` 不做 HTML 纠错 ⇒ 单测绿；**真实浏览器**会按 HTML 解析规则隐式闭合/重排表格（**布局后果未采集** ⇒ 不夸大）。
- **修复方向**：把小区那格的 `PositionCell` 包进合法容器（如让 `PositionCell` 支持 `as="div"`，或该格改用一个非 `<td>` 的包装），并补一条**可执行**断言钉住 HTML 合法性（例：`expect(within(fabric).getByTestId('matrix-cell-裁剪-布料').closest('td')?.parentElement?.tagName).toBe('TR')`，或加 `console.error` 监听断言"无 validateDOMNesting 警告"）。**该断言需自带红证**。

### P2-2 · 抽屉空态「停用/删除」只有"存在"断言，无"可点"断言

- **证据**：`frontend/admin-web/tests/unit/pages/production-routings.test.tsx:3995-3997` 只断言 `toBeInTheDocument()`；而按钮带 `disabled={variantBusy || !manageOpEntry}`（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:3873/3882`）。若工序库读面查不到该逻辑名 ⇒ `manageOpEntry` 为 null ⇒ 按钮 disabled，只报一句理由（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:2337-2342`，该分支**有**就地理由、**无**测试钉住）。
- **归因（值级）**：**断言强度不足**（存在性 ≠ 可点）。本次验收用探针**实测该夹具下 enabled**（R4.1，`Tests 1 passed`）⇒ 当前夹具**不构成**产品缺陷；但"任何数据形态下都可删"**未证**。
- **修复方向**：把探针（`not.toBeDisabled()`）正式落进 `B6-②`；并为 `!manageOpEntry` 分支补一条断言（就地理由可见、不静默）。

### P2-3 · `B4` 内一条**恒真空断言** + 一处真实风险无断言

- **证据**：`frontend/admin-web/tests/unit/pages/production-routings.test.tsx:3888` `expect(LAYER_CELLS.some((c) => c.position === '布料' && c.operation === '裁剪')).toBe(true)` —— 真值取自**测试自己的夹具常量**，与被测行为无关 ⇒ 按 `migao-acceptance`「空断言（恒绿）」，**页面怎么改都恒真**。
- **定位实测**：INJ13/INJ14（列只留 `布料` / 列返回 `[]`）都让 `B4` 红，但红的是**前面**的渲染断言（`getAllByRole('columnheader')` / `queryByTestId(...).toBeNull()`）⇒ `B4` 整体有效，**仅最后一条是空的**。
- **同时登记缺口**：设计 §4.3 要求「**不得**把 `布料` 从**读面响应**里删掉」（它是 `variant_operation_id` 的载体 + V88 保命格），而**没有任何断言**钉住"页面消费的读面数据里 `布料` 那格仍在"（现有断言只自证夹具）。
- **修复方向**：删掉该恒真断言，换成对**页面数据/渲染**的断言（例：断言 `matrixColumns` 不含 `布料` 的同时，断言页面仍把该格的 `id` 用于写面 —— 即 `fabric-sheet-row-裁剪` 里的 `PositionCell` 存在，或断言 `orphanOps` 判据未把 `裁剪` 误判为孤儿）。

### P2-4 · 渲染层证据从未在真实浏览器产出（`routings` 页不在 E2E quality specs 内）

- **证据**：PR 门禁的 `E2E quality gate` 跑的是 `pr-check.yml:187-194` 的 6 个 spec（`api-contract` / `anti-placeholder` / `cross-page-consistency` / `business-judge` / `search-alignment` / `dashboard`）；`grep -rln "routings\|工艺项\|delivery-section\|fabric-sheet" tests/e2e/` **零命中**。
- **归因**：**测试面缺口**（不是本次 PR 引入的回归）⇒ `data-testid` / 文案 / 结构在 `jsdom` 里成立，**渲染 HTML 合法性 / CSS 布局 / 折叠交互**未在任何浏览器验证（与 P2-1 叠加）。
- **修复方向**：给工艺项页补一条 Playwright spec（fixture 模式即可），覆盖 J1/J3/J9/J14。

### P2-5 · 加工单「第 N 套」端到端未采集（L2 未采集）

- **证据**：静态侧成立 —— `ProductionSeedTemplateService.java:112` `FABRIC_MAINLINE_STEPS = List.of("裁剪", "打包")`；`tests/unit_ci_workflows/test_fabric_route_seed.py:45` `FABRIC_MAINLINE_EFFECTIVE = ("裁剪", "打包")`。**活库未采集**（本会话无活库/无浏览器/活环境鉴权 401）。
- **归因**：**证据不足**。缺的是：活库上对某租户的布料单跑一次实例化，读 `processing_position_operations` 逐行 diff（附录 B8/B9/B10 的判据）。
- **附带登记（跨服务口径不一致，**不归属本次交付**）**：`backend/ai-agent-service/app/production/routing.py:465` 仍是 `FABRIC_MAINLINE_STEPS: List[str] = ["配料", "打包"]`，且 `backend/ai-agent-service/tests/test_production/test_fabric_route.py:98` 断言 `== ["配料","打包"]`；而 Java/迁移链终态已是 `["裁剪","打包"]`。
  **影响面判定（存在性级）**：`backend/ai-agent-service/app/production/routing.py:448` 逐字注释「**`build_route_v2` 今天是零消费者**：Java 实例化仍读旧 `production_routings`（P2 才切）」⇒ **今天不产生用户可见影响**；`routing.py` **不在本 PR 的改动面**（`git show --name-only efa59d98a` 无该文件）⇒ 归属 **#4676 的迁移面**，登记为**待观察项**（P2 切换时必须同步，否则 Python 会算出 `配料`）。

### P2-7 · 硬要求的「两格」只有一格有写面断言

- **证据**：`:4002-4033` 对 `裁剪 × 布料` 有完整读+写断言；`打包 × 布料` **只有读断言**（`:4020`）。`grep -n "'lc-12'" production-routings.test.tsx` → 只命中夹具 `:3755`（**无写面**）。
- **归因（值级）**：**断言缺口**（不是功能缺陷）—— 验收探针实测 `打包 × 布料` **可写**（§3.1，`Tests 1 passed`）。
- **修复方向**：把 §3.1 的探针落进 `硬要求` 用例（覆盖两格）；并补 `fabric-sheet-missing-打包` 的空态分支断言（`:4035` 目前只覆盖 `裁剪`）。

### P2-6 · 活环境判定不可得（协议 v1.9）

- **证据**：`curl https://api.migaozn.com/api/admin/production/operation-layers` → **401**（服务在、鉴权拦下）；`curl https://admin.migaozn.com/` → **000**（exit 6，不可达）。
- **归因**：本会话无活环境凭据/浏览器 ⇒ **不满足「断言无部署在飞 + 记录被测 SHA」两条前置** ⇒ **本次不对活环境下任何判定**（P26/P27 的"未达成"依据是**部署事实**，不是活环境测量）。

---

## 6. 未达成 / 未交付清单（照实）

| 项 | 状态 | 原因 |
|---|---|---|
| **D6① 端到端（P15）** | ⚠️ **仅前端渲染层达成** | 后端 `delivery` 段按矩阵行分区 ⇒ 零格 `scope='set'` 工序无行（§3.3 实测）；跨单缺口（#4676 实现 / #4677 前端前提），见 P1-2 |
| 用户可见结果（P26） | ❌ **未达成** | 交付 SHA `efa59d98a` **无任何 deploy-* run**；三条部署腿停在 `b364a7eb5` |
| 「布料」入口在缺种子租户可见（P27） | ❌ **未达成** | V89（#4685 补种）**未部署**；**#4707 OPEN**（租户 20/21 `production_operations` 0 行）；迁移应用状态**不可得** |
| 加工单「第 N 套」= 2 道（P25） | ⚠️ **证据不足** | 静态成立；**无活库** ⇒ 附录 B8/B9/B10 未采集 |
| 真实浏览器渲染正确性（P24） | ❌ **未达成** | **无浏览器**（本会话）+ routings 页**不在** E2E quality specs 内；已知 `<td>` 嵌 `<td>` 非法嵌套（P2-1） |
| 活环境任何判定 | ⛔ **未采集** | 无凭据（API 401）/ 前端域名不可达（exit 6）⇒ 协议 v1.9 两条前置不满足 |
| 用例库沉淀（P1-1） | ❌ **未交付** | `.github/cases/**` 零命中 `4677` |
| 迁移（V88/V89/V90）应用状态 | ⛔ **不可得** | 外部不可判定（无活库/无凭据） |

> **"无浏览器 ⇒ 哪些点未采集"**：P24（浏览器渲染/HTML 合法性/布局/折叠交互）、P25（加工单实例化端到端）、P26/P27（活环境可见性）—— 共 4 条 L2；**其余 25 条全部 L1/UA 已采集**（无"待人工"）。

---

## 7. 假绿 / 假红自查（逐条对照协议形态）

| 形态 | 本次处置 |
|---|---|
| **空跑（v1.3）** | **不引用任何 CI run 作为判定证据**。R1.2 已核：PR rollup 的 run `35484666211` head_sha = `9d8d65439`（**非**交付 SHA）⇒ 引用它就是把"PR 上的绿"当成"交付件已验"。全部机器判定取自本会话**前台直接执行**（退出码可查）。另核：`Case Coverage Gate` / `QA Growth Gate` / `E2E quality gate` 的**干活步骤均 `success`（非 `skipped`）**。 |
| **陈旧产物（v1.4）** | 每轮注入前后 `rm -rf node_modules/.vite .next/cache`；被测源码 `sha256` 跑前跑后逐字核；被测源码与 `@efa59d98a` **逐字节相同**（4 个文件 SAME）。 |
| **红证自身骗人（v1.12 / #4260）** | 内容指纹 `sha256`（**禁 mtime/size**）+ 注入自证（未生效 ⇒ `INJECT_NOOP` 非零退出）+ 还原自证（`RESTORE_FAIL`）+ 锚点唯一命中（`count==1`，否则 `INJECT_ANCHOR_FAIL`）+ **空跑对照**（old==new ⇒ 实测 `INJECT_NOOP`）。 |
| **红证锚点读可变引用（v1.13 / #4313）** | 全部锚点 = **逐字节内联片段**，出处 `@efa59d98a`；**不读 `origin/main`**。 |
| **基线快照晚于被测事件（v1.5）** | R4.1 探针是"当前状态"型（`not.toBeDisabled()`），无"等新增/等变化"比较 ⇒ 无基线取晚问题。 |
| **重放未复现缺陷前置条件（v1.7）** | R4.1 探针**显式复现** #4674 的前置（`manageVariants.length === 0`）并给观测值（按钮 enabled）；**未复现前置的 J18/P25 不写结论**（写"证据不足"）。 |
| **测试自建产物路径（v1.8）** | 未使用任何"按名拼产物路径"断言；`vitest`/`shasum` 的路径全部直接取自被测文件真实路径；未依赖 locale/`TMPDIR`/`TZ` 影响命名的量。 |
| **证据过渡帧/滞后帧（v1.4）** | 未引用任何截图/快照/导出物作为证据。 |
| **注释漂移（v1.4）** | 关键注释（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:136-196` 常量区、`:1310-1396` 聚合区、`:2318-2372` 删除路径）逐条与实现同源核对；发现 1 处**跨文件口径不一致**（`backend/ai-agent-service/app/production/routing.py:465` 的 `["配料","打包"]` vs Java 的 `["裁剪","打包"]`），已登记为 P2-5 待观察项（该文件**不在**本 PR 改动面）。 |
| **真值主张（自毁式断言）** | 本次**未**产出任何"断言仓库当下恰有该缺陷"的判据。 |
| **覆盖了但其实没测到（假绿）** | ① **后端「零格仍有 delivery 行」从未被构造**：`backend/admin-api/src/test/java/com/migao/admin/service/ProductionOperationLayersTest.java:232-234` 的 DisplayName 写「甚至零格」，stub 却是「有格 + `applicable=false`」；② **前端 `B6-①` 手造服务端行**（`:3958-3967`），其注释声称的后端分区口径与实现不符。两条合起来让 D6① 看起来有覆盖 —— 本次用**后端探针**（§3.3）把它测出来了，改判 P15 + 新增 P1-2 |
| **断言不可证伪** | `B7` 组「逐字取自服务端」因 `buildLayers(夹具)` 与页面同源而构造性相等 ⇒ 复核 agent 注入「前端重算」后 **3 passed 全绿**。本次补 §3.2 可证伪红证（服务端与格故意不一致）⇒ 成立，缺口登记 P2-8 |
| **假红（测试写法陷阱）** | 复核 agent 发现：`-t "#4677"` 会额外匹配 describe 外的 `判据③ 改判（#4677）`（`:3091`），该用例只在自己的 describe 里 `setDefault` 矩阵、依赖其它 describe 留下的 mock 状态 ⇒ 被过滤时必然 `Test timed out in 5000ms`（**假红**；全量跑绿）。本次验收全程用 `-t "B6-②"` / `-t "v1.11"` 这类**精确片段**规避 |
| **断言覆盖窄于声明** | issue 硬要求是「`裁剪` **与** `打包`」，交付测试只对 `裁剪` 做了写断言 ⇒ 单列 P2-7，并用**验收探针**独立补测 `打包 × 布料`（实测可写）——没有把「测试绿」读成「两格都测过」 |
| **恒真空断言** | **实测定位到 1 条**（`frontend/admin-web/tests/unit/pages/production-routings.test.tsx:3888`）并单列 P2-3；用 INJ13/INJ14 的方向性对照确认它**不是** `B4` 变红的来源。 |
| **假红** | 每条"期望红"的注入都同时满足"注入生效（指纹变化）∧ 目标用例真的失败"；`check-ui-regression.sh` / `tsc --noEmit` / 全量 vitest 在**未注入**状态下均绿 ⇒ 无"环境噪声被当红"。 |
| **活环境测量窗口（v1.9）** | **完全回避**：本次不对活环境下任何判定（R6 已核部署事实，未测活环境）。 |

---

## 8. 沉淀记录

| 问题 | 沉淀动作 | 关联 issue | case 有效性验证 |
|---|---|---|---|
| P0-1 未部署 | **跟随 issue**（部署 + 真实浏览器重走 J1~J19） | 新建（"#4677 界面改造未部署 ⇒ 用户不可见"） | 不适用（非断言） |
| P1-1 用例库 | 补 `.github/cases/**` + `render_cases.py` 生成物 | 关联 #4677（`migao-dev-flow` §14） | 需：旧失败会话重放该 case 必 fail / 修复后必 pass |
| P1-2 第二层行端到端 | `delivery` 段改按 `production_operations` 的 `scope='set'` 行分区（或并集）；前端 `B6-①` 不再手造服务端行；后端补**真零格**夹具 | 关联 #4676（后端）/ #4677 | 红证：§3.3 后端探针即为该红证（真零格 ⇒ 现红；修好后应绿） |
| P2-8 「不重算」不可证伪 | 把 §3.2 探针（服务端与格故意不一致）落进 `B7` 组 | 新建 | 红证：注入「前端重算」⇒ 必红（§3.2 已实测） |
| P2-9 `deliveryOps` 注释漂移 | 注释与实现同源；可改为消费服务端 `delivery` 段 | 新建 | 红证：注入「`deliveryOps` 改按格取」⇒ 若注释所声称的行为有断言则应红 |
| P2-10 读面失败无错误面 | 加 `layersError` + 就地报错（不拿 `no_applicable_position` 顶替） | 新建（同族 #4696 口径） | 红证：注入「`operation-layers` 失败」⇒ 断言「显示读取失败而非未设置」必红 |
| P2-1 `<td>` 嵌 `<td>` | 修 DOM 结构 + **可执行**断言（无 `validateDOMNesting` 警告 / `closest('td').parentElement.tagName === 'TR'`） | 新建 | 红证：把 `PositionCell` 换回 `<td>` 包装 ⇒ 该断言必红（**须实测**） |
| P2-2 空态按钮"可点" | 把验收探针 `not.toBeDisabled()` 落进 `B6-②`；补 `!manageOpEntry` 分支断言 | 新建 | 红证：注入 `disabled={true}` ⇒ 必红 |
| P2-3 恒真断言 | 删 `:3888` 的夹具自证，换成页面数据/渲染断言；补"读面 `布料` 格仍在"的断言 | 新建 | 红证：注入"从读面删掉 `布料` 格" ⇒ 新断言必红 |
| P2-4 浏览器证据缺口 | 给工艺项页补 Playwright spec（fixture 模式）覆盖 J1/J3/J9/J14 | 新建 | 红证：把 `delivery-section` 改回 4 列 ⇒ 必红 |
| P2-5 加工单 2 道未采集 + 跨服务口径 | 活库采集 `processing_position_operations` 逐行 diff；登记 `routing.py` 待观察 | 关联 #4707 / #4676 | 不适用（采集动作） |
| P2-7 两格只测一格 | 把 §3.1 探针落进 `硬要求` 用例 + 补 `fabric-sheet-missing-打包` 空态断言 | 新建 | 红证：注入「`打包` 行不渲染 `PositionCell`」⇒ 新断言必红 |
| P2-6 活环境判定不可得 | 部署后按协议 v1.9 重测（先断言无部署在飞 + 记录 SHA） | 关联 P0-1 跟随 issue | 不适用 |

> ⚠️ **沉淀动作本身尚未执行**（本验收单只产出报告，**不改生产代码/测试**）；上表是**待办清单 + 各自的 case 有效性验证方案**，按 `migao-dev-flow` §17 冻结后并行修复（验收者不参与实现）。
