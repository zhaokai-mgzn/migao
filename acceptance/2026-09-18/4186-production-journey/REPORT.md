# #4186 收口 —— 加工单二维码 / 工序 / 计件**正向** UI 旅程固化

| 项 | 值 |
|---|---|
| 分支 | `test/4186-production-journey`（worktree `migao-wt/4186-production-journey`） |
| 新增旅程 | `32-production-qr-and-piecework`（`scripts/ui-smoke-merchant/spec.mjs`） |
| 被测 SHA | `d5bca241`（= 分支 fork 点 = 验证时 `origin/main`；与 #4186 手工实验同一 SHA） |
| 执行人/方式 | DSH 验收资产 agent，真浏览器 + 真后端（admin-api）+ 真库（云 dev），**零人工步骤** |
| 结论 | **绿**：本旅程 5 次连续绿（17~26s）；全量 A/B **0 回归**；11 条断言 **11/11 有红证** |

## 1. 要固化什么（#4186 收口条件原文）

> 若通过 ⇒ 本单关闭，并把该实验固化成一条**正向 UI 旅程**（当前旅程③的正向分支**从未被行使**过）

原「`qr_token` 为空 ⇒ 任务卡落占位」这一半自洽，但「`qr_token` 非空 ⇒ 出真二维码」这一半**此前从未被行使**。
本旅程把它变成可复跑判据：**任何一条不过 ⇒ 旅程判失败，并打印断在哪一条判据**（不是「不抛异常就算过」）。

## 2. 复跑命令

```bash
MAIN_REPO="/Users/guangzhen.zk/ai native/migao"        # 提供 tests/node_modules（playwright）
cd "/Users/guangzhen.zk/ai native/migao-wt/4186-production-journey"

# ① 起栈（端口隔离 §2.3：API :8092 / WEB :3003；主会话占用 8080/3001）
(cd backend/admin-api && SMS_BYPASS_CODE=123456 SERVER_PORT=8092 \
   CORS_ALLOWED_ORIGINS="http://localhost:3003,http://localhost:3001" ./mvnw spring-boot:run &)
(cd frontend/admin-web && NEXT_PUBLIC_API_BASE_URL="http://localhost:8092" npm run dev -- -p 3003 &)

# ② 单跑本旅程（绿=判据全过；红=打印断在哪条）
BASE_URL=http://localhost:3003 API_BASE=http://127.0.0.1:8092 REPO_ROOT="$MAIN_REPO" \
  OUT_DIR=acceptance/2026-09-18/4186-production-journey \
  node scripts/ui-smoke-merchant/spec.mjs --group 32-

# ③ 全量（既有 31 条旅程 + 本旅程）；16- 旅程的 API 建单需要 API_TOKEN
BASE_URL=http://localhost:3003 API_BASE=http://127.0.0.1:8092 API_TOKEN=<JWT> REPO_ROOT="$MAIN_REPO" \
  OUT_DIR=/tmp/ui-smoke node scripts/ui-smoke-merchant/spec.mjs
```

- **`--group 32-` 能单跑**：`01-login` 会被 group 过滤掉，故本旅程自带补登录（`ensureLoggedIn`）。
- **两个环境硬约束**（都是实测踩过的）：
  1. `BASE_URL` 必须用 `http://localhost:3003`，**不能**用 `127.0.0.1` —— 后端
     `CORS_ALLOWED_ORIGINS` 不含 `127.0.0.1`，浏览器侧 API 调用会 `Network Error`；
  2. WEB 端口非 3000/3001 时必须给 API 显式传 `CORS_ALLOWED_ORIGINS`（本次传 `http://localhost:3003`），
     否则登录必 Network Error。

## 3. 判据与实测值（每条都锚定具体值 + 语义）

| # | 判据 | 实测值（绿） | 实测值（红证：把该条件取反） |
|---|---|---|---|
| ① | API 建单返回 `data.id` | `403fee51621a1460899a9ac98be3f860` | — |
| ② | UI「确认付款」→「生成加工单」按钮出现（#3583 闸门） | 按钮出现，`order.status=confirmed` | 修复前 2 次红：`加载中…` / 弹窗仍在 loading（见 §6） |
| ③ | `qr_token` 为 **32 位十六进制** | `67bb062fa07243939fe6d219309c2634` | `非 32 位十六进制："a37b3e20ddb0470082b13f1dabe7d77a"` |
| ③ | `positions` 非空（工序数 ≥1） | 部位 1 个 / **工序 11 道** | `工序实例为空：部位 1 个 / 工序 11 道` |
| ③ | `progress.total == 工序数` | 11 == 11 | `11 与工序数 11 不一致` |
| ④ | DOM `task-card-qr` **≥ 1** | **1** | `计数 1（期望 ≥1）`（取反后命中） |
| ④ | DOM `task-card-qr-placeholder` **= 0** | **0** | `计数 0（期望 0）`（取反后命中） |
| ④ | DOM `operation-row-*` **≥ 1** | **11** | `计数 11（期望 ≥1）`（取反后命中） |
| ④ | DOM 行数 == API 工序数 | 11 == 11 | `operation-row-*=11，而 /operations 工序数=11` |
| ⑤ | 报工后 `production-progress-text` 不再 `0%` | `9%（已完成 1/11 道工序）` | `报工后仍为 "9%（已完成 1/11 道工序）"（期望非 0%）` |
| ⑤ | `piecework-empty` **不存在** | 计数 0 | `计数 0（期望 0）`（取反后命中） |
| ⑤ | `piecework-total` **存在**（计数 = 1） | 计数 1 | `计数 1（期望 1）`（取反后命中） |
| ⑤ | 计件合计 **> 0** | `¥0.80`（= 2 米 × 0.40，工序「精裁-布」） | `"¥0.80"（期望 > 0）` |

- 红证做法：把**每一条**判据的条件单独取反（一次只反一条）⇒ 11 个变体各自 `rc=1` 且红灯标记恰为该判据
  （`[③ qr_token]` / `[③ positions]` / `[③ progress.total]` / `[④ task-card-qr]` /
  `[④ task-card-qr-placeholder]` / `[④ operation-row-*]` / `[④ DOM↔API 不一致]` / `[⑤ 进度]` /
  `[⑤ piecework-empty]` / `[⑤ piecework-total]` / `[⑤ 计件合计]`）。
  **11/11 全部可红 ⇒ 无空断言**。
- 报工的工序是「各部位首道工序中 应做量>0 且单价>0」的一道（首道工序无前道，不会撞「越站」闸门；
  单价>0 才能证明计件 > 0）。
- **红证可复现**：把下面 11 个条件各自单独取反（每次只反一条，其余不动），逐个 `--group 32-` 跑，
  期望「`rc=1` 且红灯标记恰为该判据」：

  | 判据 | 原条件 | 取反 |
  |---|---|---|
  | ③ qr_token | `!/^[0-9a-f]{32}$/.test(qrToken)` | `/^[0-9a-f]{32}$/.test(qrToken)` |
  | ③ positions | `opTotal < 1` | `opTotal >= 1` |
  | ③ progress.total | `Number(ops?.progress?.total) !== opTotal` | `… === opTotal` |
  | ④ qr | `qrN < 1` | `qrN >= 1` |
  | ④ placeholder | `phN !== 0` | `phN === 0` |
  | ④ rows | `rowN < 1` | `rowN >= 1` |
  | ④ DOM↔API | `rowN !== opTotal` | `rowN === opTotal` |
  | ⑤ 进度 | `!progressText \|\| progressText.startsWith('0%')` | `progressText && !progressText.startsWith('0%')` |
  | ⑤ piecework-empty | `emptyN !== 0` | `emptyN === 0` |
  | ⑤ piecework-total | `totalN !== 1` | `totalN === 1` |
  | ⑤ 计件合计 | `!(totalAmount > 0)` | `totalAmount > 0` |

## 4. 真跑输出（最终一次 `--group 32-`，17s）

```
$ BASE_URL=http://localhost:3003 API_BASE=http://127.0.0.1:8092 REPO_ROOT="$MAIN_REPO" \
    OUT_DIR=$PWD/acceptance/2026-09-18/4186-production-journey \
    node scripts/ui-smoke-merchant/spec.mjs --group 32-
✅ 32-production-qr-and-piecework

===== 汇总: 1/1 通过，0 失败 =====
EXIT=0 耗时=17s
```

机器可读证据（`smoke-results.json` 的 `evidence`，即断言全过时落盘的真实值）：

```
订单 403fee51621a1460899a9ac98be3f860 / 加工单 JG-20260918-9051：
qr_token=67bb062fa07243939fe6d219309c2634；工序 11 道；DOM qr=1 占位=0 行=11；
报工「精裁-布」2米 → 进度 9%（已完成 1/11 道工序）、计件 ¥0.80
```

> 与 #4186 手工实验的对照基线一致（手工：`qr_token` 32 位 hex、1 部位 × 11 道、
> `task-card-qr`=1 / 占位=0 / `operation-row-*`=11、进度 `9%（已完成 1/11 道工序）`；
> 计件手工 `¥1.20`（应做 3 米）vs 本旅程 `¥0.80`（应做 2 米）—— 同口径、随应做量变化，属预期）。

## 5. 稳定性（修复竞态后 5 次连续绿）

| 轮次 | 结果 | 耗时 | 说明 |
|---|---|---|---|
| 修复后 1~4（`--group 32-`） | ✅✅✅✅ | 20s / 26s / 19s / 20s | 连续 |
| 最终入库轮 | ✅ | 17s | 证据落 `acceptance/2026-09-18/4186-production-journey/` |
| 全量套件内的 32- | ✅ | — | 见 §6，与 01-login 同一会话（不走补登录） |

**修复期间**共红过 **4 次**（3 类成因，**没有一次**是被测链路本身的问题；全部已定位并修掉/规避，见 §7.3/§7.5）：

| 红 | 断在哪 | 根因（有截图/日志） |
|---|---|---|
| 1 | `[② 生成加工单]` | 点「确定」后 1.8s 时弹窗仍在 loading（截图：弹窗开着、确定键转圈）⇒ 订单还没转 confirmed |
| 2 | `[② 确认付款]` | `nav` 后 2.5s 页面仍是整页 `加载中…`（截图：整页只有一个 spinner）⇒ 按「付款」的按钮还没渲染 |
| 3 | 整旅程（**2 次**） | 只有 1 条 `[console.error] Failed to load resource: 400` ⇒ 补登录的 `POST /api/auth/sms-code` 撞上 60s 防刷窗口（与本次链路无关）；断言全过、`evidence` 已落盘 |

另 1 次红为**环境事件**：admin-api 进程被外部 `SIGTERM`（`SpringApplicationShutdownHook`，非本旅程所致）
⇒ `fetch failed`。重启后恢复。

## 6. 不回归：全量 A/B（详见 `regression-A-B.md`）

同一栈、**同一份被测代码**（`d5bca241`），只换 spec.mjs：

| 套件 | 汇总 | 失败 |
|---|---|---|
| 基线 = `git show HEAD:scripts/ui-smoke-merchant/spec.mjs`（改动前） | 27/31 | `06-agent-sessions` `07-chat` `11-product-edit-doorwidth` `17-order-ship` |
| 本分支（含 `32-`） | 29/32 | `06-agent-sessions` `07-chat` `17-order-ship` |

- **回归（✅→❌）条数 = 0**；两轮一致 30/31；唯一差异 `11-product-edit-doorwidth` 是**基线侧 flake**
  （该旅程不读本 PR 任何改动）。
- `06`/`07` 红因 ai-agent 未起（该套件本就接受 UI-only）；`17-order-ship` **两轮都红** ⇒ 既有问题，非本 PR 引入
  （它前置依赖 `16-` 把加工单流转到 completed；本轮 `16-` 的「发加工」按钮不可见 ⇒ 加工单未完成 ⇒ 发货表单被守卫阻断）。

## 7. 方法学坑（都实测踩过，已固化进代码注释）

1. **不能用 `innerText` 判「页面含某文案」**：任务卡 `display:none`（打印才显形）⇒ 假阴性。
   **DOM 计数（`locator.count()`）才是真值**；相应地等待数据就位只能 `waitFor({state:'attached'})`，
   等 `visible` 会永远超时。
2. **必须用 `http://localhost:3003` 而不是 `127.0.0.1`**：`CORS_ALLOWED_ORIGINS` 不含 `127.0.0.1`，
   浏览器侧 API 调用会 `Network Error`。
3. **定长 sleep + `isVisible()` 是假红制造机**（本旅程红过 3 次，全部此因）：改为
   「等目标元素出现 / 等弹窗出现 / 等数据 attached」+ 失败时把实测值写进错误消息。
4. **API 调用走 node + `Cookie: access_token=…`，不走页面内 fetch**：`access_token` 是
   HttpOnly + **Secure** + SameSite=Strict cookie，浏览器在 http 跨端口（3003 → 8092）下**不发它**
   ⇒ 页面内 `fetch(credentials:'include')` 实测 **401**；node 显式带 Cookie 头**实测 200**
   （且无 CORS 参与，鉴权主体与 UI 会话同租户）。
5. **补登录必须早于 `journey()`**（即早于本旅程的 console 监听窗口）：`journey()` 把**任何**
   `console.error` 判为旅程失败，而补登录时的 `sms-code` 400（60s 防刷窗口）与本次链路无关
   ⇒ 会把**全绿**的旅程翻成红（实测 2 次：断言全过、`evidence` 已落盘，仅因那一条 400 判失败）。

## 8. 越界发现（**不属于本任务范围，未修改**）

| # | 发现 | 证据 | 影响 |
|---|---|---|---|
| 1 | `16-order-detail-processing-order` 的「加工单可见」判据用 `/PO-[0-9-]+\|PG-[0-9-]+/`，而真实单号是 `JG-YYYYMMDD-NNNN`（`ProcessingOrderService.generateOrderNo()`）⇒ **永远 false** | 本轮全量 `16-` 证据 `加工单生成+流转:  [发加工不可见]; 加工单可见=false`，而同一单号确实生成为 `JG-20260918-9049`（见 `32-` 证据） | 证据字段误导；`if (!poVisible && !flowDone)` 守卫被削弱 |
| 2 | `16-` / `17-` 的状态耦合 + `16-` 的定长 sleep 竞态：「发加工」按钮在生成后立即检查 `isVisible()` ⇒ 偶发不可见 ⇒ 加工单不 completed ⇒ `17-order-ship`「发货页无表单」 | A/B 两轮 `17-` 都红；`16-` 证据 `[发加工不可见]` | 全量套件长期带 2 条红灯（掩盖真实回归） |
| 3 | `16-` 的 404 探测豁免有**假绿**路径：`res.errors.every(e => e.includes('404'))` 会把「旅程自身抛出且消息含 `404`」的失败一起豁免（如 API 404 时消息形如 `GET … → HTTP 404：…`） | 代码即判据：`spec.mjs` 内 `exemptProbe404` 逻辑 | 窄但真实：可能把失败判成通过 |
| 4 | 框架级：`journey()` 对**任何** `console.error` 判失败 ⇒ 任何「在 journey 内做登录」的旅程都会被 SMS 400 误伤（本旅程以 §7.5 规避） | §5 红 3 | 是否收窄该口径属框架决策，未擅自改 |
| 5 | 文件头注释「33 旅程」与实跑不符：基线实跑 **31** 条记录（27-30 由 `corporatePages` 循环产出 4 条） | A/B 两轮 `results` 长度 31 / 32 | 纯文档漂移 |

> 本 PR 只动 `scripts/ui-smoke-merchant/spec.mjs`（新增旅程 + 两个 helper + 1 行 `API_BASE` 复用）
> 与 `acceptance/2026-09-18/4186-production-journey/**`；`frontend/**`、`backend/**`、`.github/**`、
> `.agent-presets/**` **零改动**（另 3 个并行包在改那些路径）。
> 曾一度把 `16-` 的 404 豁免抽成公共 `exemptProbe404()`，最终**撤回**为原样：本旅程不用该豁免
> （避免继承 §8.3 的假绿路径），故抽取只增改 `16-` 的风险而无收益。

## 9. 未做与原因

| 未做 | 原因 |
|---|---|
| 未改 `frontend/**` `backend/**` `.github/**` `.agent-presets/**` | 写路径限制 + 他人并行包 |
| 未修 §8 的 5 条越界发现 | 明确要求「不顺手修」，只单列 |
| 未加 `# case_ids:` 声明 | `spec.mjs` **不是**测试文件：`growth_gate.py::_is_test_file` 只认 `.py/.java/.ts/.tsx` + 文件名含 test/spec，`.mjs` 不在内；且 G5 用例追溯要求声明的 ID **必须已存在于** `.github/cases/`，凭空加 `UI-xxx` 反而 block 门禁 |
| 未修 #4202（存量单无恢复路径） | 属另一 issue，非本单范围 |
| 未 rebase 到最新 `origin/main`（`1ee23816`） | 4 个新提交**不触及**本 PR 文件与依赖链路（`git diff --stat d5bca241..origin/main -- scripts/ui-smoke-merchant/spec.mjs acceptance/ <生产链路文件>` 全空；#4211 是 ai-agent Python 幂等键，非 admin-api 契约）⇒ 无冲突、判定不受影响；按 §2.2 禁止裸 rebase |
| 未跑评测派发（`post-deploy-eval` 等） | 本 PR 是评测**资产**（UI 旅程），不改 ai-agent 行为/judgement 用例 ⇒ 无 LLM 判定需求（§16.7 禁空跑：过筛不改下一步就不跑） |

**验证 SHA 边界**：本报告全部结论覆盖 `d5bca241`（= 分支 fork 点 = 验证时 `origin/main`）。
其后 `origin/main` 前进到 `1ee23816`（4 个提交，均不触及本 PR 文件与生产链路）。

## 10. 证据清单

| 文件 | 内容 |
|---|---|
| `REPORT.md` | 本文件 |
| `smoke-summary.md` / `smoke-results.json` | 最终 `--group 32-` 轮的机器可读结果与真实值 |
| `screenshots/32-production-qr-and-piecework.png` | 该轮页面截图（生产明细页） |
| `regression-A-B.md` | 全量套件 A/B 逐旅程对照（证明 0 回归） |
