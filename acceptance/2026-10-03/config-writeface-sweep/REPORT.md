# 配置写面「写后等价性」横切扫描（线③）

- **轮次**：2026-10-03 · 下一轮功能测试 · 线③（横切扫描）
- **产物根**：`acceptance/2026-10-03/config-writeface-sweep/`
- **探针脚本**：`harness/*.mjs`（复用上一轮 `dispatch-routing-sweep/harness/lib.mjs` 的 `api()/psql()/psqlWrite()/one()/Recorder`）
- **读数**：`out/*.json`（逐条记录 + 证据引用）、`out/raw-*.log`（原始 stdout）、`out/run-all-summary.json`
- **本包零业务代码改动**（只新增验收脚本与读数）

---

## 0. 核心判据（本线的灵魂）

> 一次「只改一个字段」的保存，**允许变化的字段集必须恰好等于你发出的 payload 的键**
> （外加显式声明的审计 / 版本 / 时间戳字段）。**多一处即红。**

实现口径（`harness/sweep.mjs`）：

| 步骤 | 动作 | 说明 |
|---|---|---|
| 1 | **字段级快照（before）** | 租户 20 的配置表全集（11 张主面 + 6 张审计/版本面）逐行逐字段；**一次 SQL 往返**（`union all` + `row_to_json`）；含软删行 |
| 2 | 发**一个**写请求 | payload 键数记入证据；UI 天然多键的动作**显式声明**（如 `positions` 的语义就是建矩阵行） |
| 3 | **字段级快照（after）+ diff** | 差异按 `表.行.字段: before → after` 逐条列出 |
| 4 | **判定** | `changed_keys ⊆ payload_keys ∪ 审计列`；越界项 = **发现** |
| 5 | **还原** | 「拉到 before 态」两趟（字段写回 + 新行软删）；**只碰我自己探针的对象** |
| 6 | **还原自证** | 逐字段比对（我的行主面残留 = 0）+ 每个还原动作 `affected` 行数 > 0 + 零存活残留 |
| 7 | **时间戳** | 全部 +08 口径（原始 JSON 同时存 UTC，标注换算） |

**补充判据（本轮新增）**：越界之后还要问一句 **「这次越界伤不伤钱？」** ——
`priceEffect()` 比对**有效价（读面口径）**与**存活价目行集合**：
有效价变了 = **P1 涉钱**；只有行集合变了 = **P3 等价性越界但不伤钱**。两条必须分开记，
否则会把「已修的」与「新发现的」混成一条。

### 0.1 与并行包的隔离（纪律）

同租户另有并行包 **`acceptance/2026-10-03/piecework-wage-sweep/`** 在自建自清工资探针并**读写**同一批表。
实测它在我的一次写窗口内改了 `复烫-布帘` 的价（`0.35 → 1.11`），并在 `打包` 上新建了 `布帘` 价目行
（`fd9f565…`，`created_at 2026-10-03 08:36:19 +08`）。

⇒ 三条纪律（缺一条归因就会错）：

1. **探针对象尽量自建**（前缀 `写面横切`）；必须改的既有行逐条还原；
2. **短写窗口 + 逐条立即还原**；快照与写请求紧邻；
3. **越界项按「行内容」归因**：命中我自己探针对象标识的 = **本写面副作用**（发现）；
   落在**不是我探针对象**行上的 = **外来行** ⇒ 记 `skip`（疑似并发干扰）**并先还原再重跑**
   （且**只在同一写请求内没有我自己的后果时**才重跑 —— 否则重跑会被第一次的副作用
   「布帘行已存在 ⇒ 幂等跳过」**掩盖**，这是我踩过并修掉的假绿）。
   还原也**只碰我自己的行** —— 否则会把并行包的写入「还原」掉（实测踩过）。

---

## 1. 环境与构建点（含 🔴 **部署点在测量期间移动**的完整披露）

### 1.1 部署点在同一轮测量中前进（**本报告最重要的环境事实**）

| 时段（+08） | 运行中的构建点 | 含 #6102 修复？ | F8 形态的实测结果 |
|---|---|---|---|
| 08:29 – ~08:47 | **`402be478b`**（main-live 当时 HEAD；类文件 mtime `01:57:09`） | **否**（`merge-base --is-ancestor 1d1fe5e55 HEAD` ⇒ NO） | **复现**：保存一次工序设置 ⇒ 价目表多出 `布帘` 行（**涉钱**形态，见 §3.1a） |
| ~08:47 起 | **`a4aaa3c24`**（含 `1d1fe5e55 #6106`；类文件 mtime `08:47:36`；Java 进程 **08:49:17** 重启） | **是** | **不再复现涉钱形态**：新 `布帘` 行**继承有效价** ⇒ 有效价不变（见 §3.1b） |

🔴 **这条时间线是实测的，不是推断**：09:00 与 09:01 两次读到 `main-live` HEAD 从 `402be478b` 变为 `a4aaa3c24`
（`git -C …/main-live rev-parse HEAD`），且 Java 进程 `lstart` 从 `2:50 上午` 变为 `08:49:17`。
现在 `run-all` 的**每一次**运行都会记录（`W0-00`）：
`HEAD / 编译产物 mtime / Java 进程启动时刻 / 是否含 1d1fe5e55`，避免再次出现「读数与部署点对不上」。

**本报告的最终整套读数**（§2.1）全部取自**同一个构建点 `a4aaa3c24`**（测量前 09:01:41 / 测量后 09:03:28 两侧自证一致）。

### 1.2 环境明细

| 项 | 读数 | 取证 |
|---|---|---|
| 被测租户 | **20** | `TENANT_ID=20` |
| 运行中的 admin-api | `http://localhost:8080`，`GET /actuator/health` = **200** | `curl` |
| 运行方式 | `mvn spring-boot:run`（worktree `/Users/guangzhen.zk/migao-wt/main-live`） | `ps -eo pid,command` 逐字 |
| **最终构建点** | **`a4aaa3c24`**「fix(admin-api): #6115 路线「适用帘种」写面加值域护栏…(#6116)」，提交时刻 `2026-10-03 08:28:00 +08` | `git -C …/main-live log -1` |
| 类文件构建时刻 | `2026-10-03 08:47:36 +08`（`ProductionOperationCommandService.class`） | `stat` |
| Java 进程启动 | `2026-10-03 08:49:17 +08` | `ps -eo lstart` |
| 数据库 | 云 dev RDS（库 `ai_customer_service`） | `backend/admin-api/.env` |

### 1.3 环境维护动作披露（不影响被测对象，但必须写出来）

1. **登录**：admin-api 的短信登录走 Redis 验证码（`sms:code:<phone>`，TTL 5 分钟、一次性）。
   横切扫描反复登录会耗尽**短信日限（10 条）** ⇒ 中途出现 `401 AUTH_FAILED / 今日发送次数已达上限`。
   处置（**仅 dev**）：清 `sms:daily:<phone>` 计数 → 重新 `/sms/send` → **从 Redis 读回真实验证码**登录。
   该兜底已落进 `harness/lib.mjs` 的 `loginApi()`（无 Redis 凭据的环境自动不可用）。
   ⚠️ **不改任何产品配置**（只清开发环境限流计数）。
2. **不改被测服务**：全程未重启 admin-api、未重新构建、未改任何业务代码
   （08:49 的重启是**外部部署动作**，不是本包做的 —— 见 §1.1）。

---

## 2. 写面 × 允许变化键矩阵

判据：`changed_keys ⊆ payload_keys ∪ 审计列`。**两套账分开**：主面（11 张配置表）= 判据主体；
审计/版本面（`production_operation_price_versions` / `production_operation_position_price_versions` /
`production_routing_versions` / `processing_fee_combination_versions` / `tenant_param_audit` / `audit_logs`）
= **显式声明的副账**（变化单列，不计越界，但不许静默）。

| # | 写面（端点） | 探针 | payload 键 | changed_keys | 判定 |
|---|---|---|---|---|---|
| **A** | **工序库** `PUT /production/operations/{id}` | W2-01 scope | `[scope]` | `scope, updated_at` | ✅ |
| A | 同上 | W2-02 `group_name` | `[group_name]` | `group_name, updated_at` | ✅ |
| A | 同上 | W2-03 `unit` | `[unit]` | `unit, updated_at` | ✅ |
| A | 同上 | W2-04 `is_start_marker`（标记生产开始） | `[is_start_marker]` | `is_start_marker, updated_at` | ✅ |
| A | 同上 | W2-05 `sort_order` | `[sort_order]` | `sort_order, updated_at` | ✅ |
| A | 同上 | W2-06 `status=disabled` | `[status]` | `status, updated_at` | ✅ |
| A | 同上 | W2-07 `status=inactive`（**UI 实发词**） | `[status]` | **（无）** HTTP 422 | ✅（拒收） |
| A | 同上 | W2-08 `unit_price` | `[unit_price]` | `unit_price` + 版本账行（副账） | ✅ |
| A | 同上 | W2-09 `positions=[布帘]` | `[positions]` | `updated_at`（已存在 ⇒ 幂等跳过） | ✅ |
| A | **同一次保存的副作用** | **W1-01 只改 `scope`** | `[scope]` | **`production_operation_positions.*(row-added)`** | 🔴 **F1（见 §4）** |
| A | **空 payload** | **W0-03 `{}`（键数 0）** | `[]` | **`production_operation_positions.*(row-added)`** | 🔴 **F1 同族** |
| A | 新建 `POST /production/operations` | W2-10 | — | 新工序行 + 1 价目行 | ✅（自建自清） |
| A | **软删** `DELETE /production/operations/{id}`（有挂格） | W2-11 | 语义=`deleted` | **HTTP 422（护栏③）** | ✅（护栏生效，**不是**静默成功） |
| A | 设为不做并删除 `…/detach-and-delete` | **W2-12**（受控复核） | — | 工序软删 ✅ **且** 该工序矩阵行全清（`deleted_positions=1`） | ✅ |
| **B** | **价目矩阵** `PUT /production/operation-positions/{id}` | W3-01 `unit_price=0.77` | `[unit_price]` | `unit_price` + 位置价版本账行 | ✅（读面 0.66→0.77） |
| B | 同上 | W3-02 `unit_price=0` | `[unit_price]` | `unit_price` + 版本账 | ✅（读面 →`0`） |
| B | 同上 | W3-03 `unit_price=null`（清空） | `[unit_price]` | `unit_price` + 版本账 | ✅（读面 →`NULL(未定价)`，**≠ 0 元**，W3-03b ✅） |
| B | 同上 | W3-04 负对照（同值重发） | `[unit_price]` | `updated_at` only | ✅ |
| B | 同上 | W3-05 `applicable`（已退场字段） | `[applicable]` | **（无）** HTTP 422 | ✅（拒收） |
| B | 同上 | W3-06 **未知字段 `position`** | `[position]` | `updated_at` only（**静默忽略**） | ⚠️ **F2（见 §4）** |
| B | 同上 | W3-07 空 payload `{}` | `[]` | `updated_at` only | ✅ |
| **C** | **工艺路线** `POST /routings` | W4-01 | — | 新路线行（自建自清） | ✅ |
| C | `PUT /routings/{id}` | W4-02 改名 | `[name]` | `name, updated_at` | ✅ |
| C | 同上 | W4-03 调序 | `[mainline]` | `mainline` + 路线版本账行（副账） | ✅ |
| C | 同上 | W4-04 删一道 | `[mainline]` | `mainline` + 版本账 | ✅ |
| C | 同上 | W4-05 加回 | `[mainline]` | `updated_at` only | ✅ |
| C | 同上 | W4-06 适用帘种 `positions` | `[positions]` | `positions, updated_at` | ✅ |
| C | 同上 | W4-07 停用 / W4-08 启用 | `[status]` | `status, updated_at` / `updated_at` | ✅ |
| C | 同上 | W4-09 `is_default=false` | `[is_default]` | **（无）** HTTP 422（契约一致） | ✅ |
| C | `DELETE /routings/{id}` | W4-11 | 语义=`deleted` | `deleted, updated_at` | ✅ |
| **D** | **适用条件规则** `POST /route-rules` | W5-01 | — | 新规则行（自建自清） | ✅ |
| D | `PUT /route-rules/{id}/customer-unit-price` | W5-02 `12.5` | `[customer_unit_price]` | `customer_unit_price, updated_at` | ✅ |
| D | 同上 | W5-03 `null` | `[customer_unit_price]` | `updated_at` only | ✅ |
| D | `DELETE /route-rules/{id}` | W5-04 | 语义=`deleted` | `deleted, updated_at` | ✅ |
| D | 改触发维/动作/部位 | W5-05 | — | **仓内无该写面** | ⏭️ 未覆盖（登记） |
| **E** | **加工费组合** `POST /processing-fee-combinations` | W6-01 | — | 新组合行（自建自清） | ✅ |
| E | `PUT /processing-fee-combinations/{id}` | W6-02 `unit_price` / W6-03 `sort_order` | 各 1 键 | 对应列 + 版本账行 | ✅ |
| E | `DELETE /processing-fee-combinations/{id}` | W6-04 | 语义=`status` | `status` + 版本账行 | ✅（软删=disabled，`deleted` 仍 0 —— 已按此口径判残留） |
| **F** | 算料公式配置 `PUT /production/craft-calc-config` | W6-05 `margin_multi+0.01` | `[margin_multi]` | 对应列 + `updated_at`；HTTP 200 | ✅ |
| F | 裁高配置 `PUT /production/cutting-height-config` | W6-06 `rounding.digits` | `[rounding.digits]` | `rounding` 列 + `updated_at`；**首建配置行**（该租户原本无行） | ✅（首建属该写面固有语义，显式声明放行） |
| F | 工人端页面开关 `PUT /admin/worker-page-config` | W6-07 `pages`（倒序） | `[pages]` | `pages`；HTTP 200 | ✅ |
| F | 小件用料尺寸表 `PUT /production/remnants/small-item-specs` | W6-08 `items=[]` | `[items]` | **（无）**（清空 = 已未配置）；HTTP 200 | ✅ |
| F | 加工项 `POST/PUT/DELETE /processing-items` | W6-09/10/11/12 | `[name]` / `[unit]` / 语义 | 对应列 / 软删 | ✅ |
| F | 店铺设置 `PUT /admin/settings` | W6-13 `companyName`（同原值） | `[companyName]` | **（无）** | ✅ |
| F | 租户 AI 配置 `PUT /admin/tenant/ai-config` | W6-14（同原值） | `[id]` | **（无）** | ✅ |

> 说明：`W6-13/W6-14/W3-04/W3-07/W4-05/W4-08/W5-03` 的 changed 集合本来就可能为空（同值或幂等），
> 因此**每条另加一条断言「写面真的被接受（HTTP 2xx）」**（`*-http` 记录）—— 否则「允许集合为空」
> 可能是「请求根本没被接受」的**假绿**。**这条自查实测抓到 2 条假绿**（见 §5-③）。

### 2.1 最终汇总读数（可复算：`out/run-all-summary.json`）

**构建点 = `a4aaa3c24`**（测量前 09:01:41 / 测量后 09:03:28，两侧 `rev-parse` 一致）

| 探针 | pass | fail | skip | total |
|---|---|---|---|---|
| `p1-selftest-f8`（构建点自证 + 红证 + 正/负对照） | 13 | **4** | 0 | 17 |
| `p2-operations`（工序库写面） | 28 | 0 | 0 | 28 |
| `p3-positions`（价目矩阵写面） | 19 | 0 | 0 | 19 |
| `p4-routes`（路线写面） | 24 | 0 | 1 | 25 |
| `p5-rules`（规则写面） | 11 | 0 | 1 | 12 |
| `p6-other-config`（其余 8 个配置写面） | 33 | 0 | 0 | 33 |
| **合计** | **128** | **4** | **2** | **134** |

- **4 条 fail 全部是同一形态**：`W1-01`/`W1-02`（正对照）与 `W0-03`/`W0-03b`（空 payload 负对照）；
  这 4 条**判据命中是真命中**（价目表确实被多写了一行），但 `W1-03` 判定 **当前构建点上它已不涉钱**（§3.1b）；
- **2 条 skip 都是「有意的未覆盖 / 不可达」**（`W4-10` 设默认路线、`W5-05` 规则无 update 写面），**不是**并发干扰跳过；
- 其余 **6 个写面族 / 128 条断言全绿**（含 6 条还原自证、4 条 HTTP 2xx 前置、构建点自证）。

---

## 3. 红证（逐字读数）

### 3.1 正对照 —— **两个构建点，两种结果**

**(a) 构建点 `402be478b`（不含 #6102 修复）—— 涉钱形态复现**

```
[build] 写面横切正对照232831 HTTP 200 id=403483d653581d18161df17a671fe97b scope=position 库价=0.55
        价目行=[{"applicable":true,"id":"a5d833…","p":"0.55","position":"通用"}]
❌ W1-01 越界 1 处（本写面副作用）：["production_operation_positions.*(row-added)"]（payload 键=[scope]）
✅ W1-01-restore 我的行主面残留=0；还原动作=2（no-op=0）；软删回收=1 行；非我的行=0
❌ W1-02 正对照判定：F8 形态**当场红** ⇒ 本线判据有效（不是空断言）
```

**(b) 构建点 `a4aaa3c24`（**含** #6102 修复）—— 涉钱形态**不再复现**，判据仍红（性质降级）**

```
✅ W0-00  构建点自证 main-live HEAD=a4aaa3c24；编译产物 mtime=2026-10-03 08:47:36；Java 进程启动=六 10月/3 08:49:17 2026
✅ W0-00b merge-base --is-ancestor 1d1fe5e55 HEAD ⇒ YES（构建点含 #6102 修复）
❌ W1-01  越界 1 处：["production_operation_positions.*(row-added)"]（payload 键=[scope]）
❌ W1-02  payload 键=[scope] ⇒ 越界命中价目表；有效价（读面）0.55 → 0.55（**未变**）
✅ W1-03  有效价 0.55 → 0.55；存活价目行集合变化=false ⇒ **—**
          （= #6102 修复**已生效**：新行继承有效价 ⇒ 不再静默改价）
```

**定点独立复核**（同一构建点，三种形态各跑一次；每态自建自清）：

| 形态 | 工序库价 | 「通用」行价（人为构造，模拟商家改价/未定价） | PUT 后新建「布帘」行的价 | 读面有效价 | 结论 |
|---|---|---|---|---|---|
| A 商家改过价 | 0.55 | **0.77** | **0.77**（继承有效价） | 0.77 → 0.77 | ✅ **未被回退** |
| B 未定价 | 0.99 | **NULL** | **NULL** | NULL → NULL | ✅ **未被顶成 0/0.99** |
| C `打包` 真实形态 | 0.00 | **NULL** | **NULL** | NULL → NULL | ✅ **未变成 0 元** |

⇒ **#6102 的修复在本构建点上确实生效**（`attachPositions` 的 5 参签名 + `priceSourceRows` 逻辑逐字可复核）。
**F8 的「静默改价」症状已消除**；但**「多写一行」这个写后等价性越界依然存在**。

### 3.2 负对照

| 形态 | 读数 | 判定 |
|---|---|---|
| **同值重发**（价目矩阵） | `changed = ["…updated_at"]`；越界 **0** | ✅ 允许集合为空 |
| **空 payload `{}`**（价目矩阵） | `updated_at` only；越界 **0** | ✅ |
| **空 payload `{}`**（**工序库**，键数 0） | 越界 **1**：`production_operation_positions.*(row-added)` | 🔴 **F1**（一个键都不带也能多写一行） |
| **同值重发**（工序库 `scope`） | 同上 | 🔴 同上 |

### 3.3 注入式红证（判据能区分「写面副作用」与「外部改动」）✅

```
手工 update production_operations set unit_price=0.1234 where id='op-v91-20-32'（logo条-布）
⇒ 字段级 diff 命中 production_operations.unit_price: "0.6" → "0.12"；判据越界=["production_operations.unit_price"]
⇒ 还原（拉到注入前）：还原动作=1（affected=1）；主面残留=0 ✅
```

---

## 4. 发现清单

> 级别：P1 = 涉钱/静默；P2 = 用户可见功能不可用；P3 = 一致性/登记。
> 每条给：级别 + 复现 + 影响面 + 一句话判据。

### 🟠 F1（**P3** · 写后等价性越界；**修复前是 P1 涉钱**）工序设置写面**凭空新建价目行**（连空 payload 也会）

- **当前级别：P3**（原为 P1）。**理由（本构建点 `a4aaa3c24` 实测）**：新建的 `布帘` 行**继承有效价**
  ⇒ 有效价不变 ⇒ **暂不伤钱**（§3.1b + 三形态定点复核）。但**写后等价性判据仍然越界**。
- **复现（自建对象，最短路径）**：
  1. `POST /api/admin/production/operations` body `{name:"写面横切正对照<N>", group_name:"写面探针组", unit:"米", unit_price:0.55, scope:"position", positions:["通用"]}`
     ⇒ 工序建成时矩阵里**只有 `通用` 一行**（HTTP 200）。
  2. 发**一个**写请求 `PUT /operations/{id}` body `{"scope":"set"}`（payload 键数 = **1**）
     —— 或更短：body **`{}`（键数 0）**。
  3. 字段级 diff ⇒ **越界 1 处**：`production_operation_positions` 多出一行 `position=布帘`。
- **触发前置（必须显式构造，否则假绿）**：该工序的矩阵里**没有「布帘」行**
  （`attachPositions` 只补**不存在**的那一列；已有 ⇒ 幂等跳过）。
- **影响面（既有生产数据上的活体读数）**：租户 20 上只有 `通用` 一行的工序有 8 道；
  `打包` 上累计的软删 `布帘` 孤儿行在本会话内从 **6 条 → 9 条 → 13 条**（两次独立快照分别读到 9 与 13）
  ⇒ **每次保存都往价目表里塞一行，且只增不减**。
- **一句话判据**：**任何工序设置写面调用后，该工序的价目行集合与有效价都必须逐字不变，
  除非该写面显式带 `unit_price` / `positions`。**
- **与 #6102 的关系（关键）**：#6102 修的是「**新行的价取错**」（⇒ 有效价被改写），
  **没有**修「**新行本就不该被创建**」。⇒ 正确修法方向是让 `attachPositions` 在 **`update` 路径**上
  不再兜底建行（或建行后不进读面的取价集合），而不是仅让新行的价正确。

### ⚠️ F2（P3 · 一致性/静默）价目矩阵写面**静默忽略**未知键 `position`

- **复现**：`PUT /production/operation-positions/{id}` body `{"position":"纱帘"}` ⇒ **HTTP 200**，只有 `updated_at` 变。
- **同一系统内的对照（两套口径）**：同端点对已退场字段 `applicable` 是**收到即 422**（W3-05 实测 422）；
  而 `worker-page-config` 的读面注释逐字写着「拼错的键会被静默忽略 ⇒ 商家以为改了却没改」。
- **影响面**：商家/集成方发 `{"position":"纱帘"}` 会以为改了部位归属，实际什么都没发生（**静默 no-op**）。
  本包实测**未发现它连带改别的列**（越界 0），故只记 P3。
- **一句话判据**：**写面收到不属于契约的键时，必须 422 逐条报理由，不得静默忽略。**

### ℹ️ F3（P3 · 登记）UI「停用工序」词表不一致仍未修（上一轮 F1 的形态）

- `PUT /operations/{id}` body `{"status":"inactive"}`（**UI 逐字实发的词**）⇒ **HTTP 422**、库中 `status` 不变；
  `{"status":"disabled"}` ⇒ 200。⇒ UI 侧「停用」按钮 100% 失效（**如实登记为未修**）。
- ⚠️ **注意**：`main-live` 工作树里已有 `dc10e5d2e fix(production): #6103「停用工序」按钮真正生效`，
  但**其是否已进入运行中的编译产物，本包未验证**（本包只验证了 `#6102` 对应的类）⇒ 记「未验证」，不写成「已修」。

### ✅ F2′（**已撤回** —— 上一版记为「`detach-and-delete` 不级联清矩阵行」，经**受控复核推翻**）

- **上一版结论**：该端点返回 200 但不级联软删矩阵行（残留累积）。**已撤回。**
- **它是怎么来的（我的工装缺陷，如实登记）**：我用「**全前缀**存活矩阵行数」当判据 ——
  那个计数的对象是「所有 `写面横切*` 的行」，会被**后续步骤 / 我自己的清场**扫掉 ⇒ 读数被污染；
  我又把同一步里**普通 `DELETE` 的 422**（护栏③）误读成「级联没生效」。
- **受控复核（只数**该工序自己**的存活矩阵行，先读后在）**：
  ```
  build HTTP 200 created_positions=1
  before: aliveRows=[{"p":"0.44","position":"通用"}]
  detach-and-delete HTTP 200 resp={"deleted":true,"detached_positions":1,"deleted_positions":1}
  after : aliveRows=[]     op.deleted = 1     VERDICT: PASS（级联清干净）
  ```
- **现结论**：**级联软删矩阵行确实生效**。该写面**不会**静默留残留 —— 与 F1 的「静默多写一行」形成**反向对照**。
- **工装修正（已落码，防下次再犯）**：`harness/setup.mjs` 的 `removeOp()` 现在返回
  「**该工序自己**的存活矩阵行数」（先读后在），并在普通 `DELETE` 非 2xx 时改走 `detach-and-delete`。

---

## 5. 假绿 / 假红自查（**尤其**：我的期望是否取自被测系统自己的读面？）

| # | 形态 | 本包自查动作 | 读数 |
|---|---|---|---|
| ① | **判据是空断言**（永远不会红） | **正对照**在**当前构建点**上跑，要求当场红 | ✅ 当场红（§3.1b）；红的原因是「多写一行」，可复核。**若它不红我会先修判据再继续** |
| ② | **恒红** | 负对照（同值重发 / 空 payload / 幂等写）要求允许集合为空 | ✅ 价目矩阵侧四条全绿；工序库侧两个「应为空」的形态红了 = **真发现**（已归因 F1，非判据问题） |
| ③ | **「允许集合为空」可能是「请求根本没被接受」** | 给每条「changed 为空」的探针**另加** `*-http`（HTTP 2xx）断言 | ✅ **实测抓到 2 条真值主张被推翻**：`W6-06 裁高配置`、`W6-07 工人端页面开关` 首版发了**读面全量 body**（含 `source`/`labels`）⇒ **HTTP 422**，而「越界 0」是**假绿**；改正 payload 后重跑。**本次自查最有价值的一处** |
| ④ | **我的期望取自被测系统自己的读面？** | 全部「有效价」判定都读**被测系统自己的读面** `GET /admin/production/operation-positions`（`unit_price == null ⇒ 「未定价」`），**不自己推算**；「读面 null ⇒ 未定价 ≠ 0 元」用 `W3-02 → W3-03` 的**对照**钉住 | ✅ `W3-03b`：改前读面 `0`（显式 0 元）⇒ 清空后读面 `NULL(未定价)` ⇒ 两态可区分 |
| ⑤ | **未复现缺陷的前置条件**（跑了也绿，但前置不在） | 正对照显式**构造** F8 前置：`W1-00` 断言「矩阵里**没有**布帘行」；`W0-03-pre` 在负对照前再自证一次 | ✅ 两次前置自证 pass。**这正是我第一版判据假绿（正对照不红）的真因**——前置被我上一步的写入破坏了 |
| ⑥ | **并发改动被当成我的残留** | 还原与还原自证**只比我自己探针的行**；外来行单列不计 | ✅ `W2-01-restore` 等显示「非我的行 = 2」而**我的行残留 = 0** |
| ⑦ | **陈旧产物 / 空跑** | 每条记录带 +08 时间戳 + `affected` 行数 + 存活残留读数；**每次运行自证构建点**（`W0-00`） | ✅ **抓到一次真问题**：部署点在测量期间移动（`402be478b` → `a4aaa3c24`），已据此把正对照改写成双构建点（§3.1） |
| ⑧ | **计数口径与被断言对象不同域**（本轮最贵的一课） | 用「**全前缀**存活行数」当判据 ⇒ 后续清场扫掉它 ⇒ 读数与人眼不符 | 🔴 实测**误导过一次归因**（F2′ 假发现）。已改为「**只数该探针对象自己的行**」+ 先读后在 + 返回 `affected`。**教训：计数口径必须与被断言对象同域** |
| ⑨ | **重跑掩盖副作用** | 并发干扰重跑前必须先还原到 before；且**只在「本次写请求内没有我自己的后果」时才重跑** | ✅ 已修：否则「布帘行已存在 ⇒ 幂等跳过」会让第二次跑**假绿**（实测踩过） |
| ⑩ | **「已合并 ≠ 已部署」** | 不假设构建点；每次运行用 `merge-base --is-ancestor` 自证是否含目标修复 | ✅ 抓到部署点移动，并据此把「涉钱 P1」改判为「不涉钱 P3」 |

---

## 6. 零残留读数

**报告时点（09:06 +08，构建点 `a4aaa3c24`）直接查库**：

```
ops=0        （production_operations          name          like '写面横切%' and deleted=0）
pos=0        （production_operation_positions logical_name like '写面横切%' and deleted=0）
routes=0     （production_route_templates     name          like '写面横切%' and deleted=0）
rules=0      （production_route_rules         trigger_value like '写面横切%' and deleted=0）
items=0      （processing_items               name          like '写面横切%' and deleted=0）
fees_notdisabled=0 （processing_fee_combinations … status<>'disabled'）
```

- **对既有行的改动全部还原**：注入式探针（`logo条-布` 的 `unit_price`）还原动作 `affected=1`、主面残留 = 0；
  所有探针的 `*-restore` 记录「**我的行**主面残留 = 0；no-op = 0」。
- **未触碰商家的生产配置**：既有两条路线（`布料工序路线` / `窗帘工序路线（默认）`，后者 `is_default=true`）
  在 P4 前后**逐字未变**（`W4-99` 只读比对）；`is_default=true` 的写法**本轮有意不测**（见 §7）。
- **探针对象总数**（含历史软删行，全部 `deleted=1` 或 `status=disabled`）：工序 60 条 / 矩阵行 82 条
  —— 都是**探针自己的**累积，且都不存活。
- **审计/版本面**（显式声明的副账）：改价 / 改主线会追加版本行，逐条列在证据里，不计越界。

---

## 7. 未覆盖面（如实登记，不粉饰）

1. **`is_default=true`（设默认路线）**：会把商家**现有默认路线**（`rt-v72-20`）降级 —— 属「改动既有生产配置、非自建对象」，
   按本包纪律**不碰** ⇒ 该写面**未被本轮覆盖**（只读了当前默认是谁）。
2. **规则写面的「改触发维与取值 / 改动作 / 改部位限定」**：仓内**无该写面**
   （`ProductionController` 只有 `POST /route-rules`、`PUT /route-rules/{id}/customer-unit-price`、`DELETE /route-rules/{id}`；
   `lib/api.ts` 同）⇒ **不可达**，不是「已覆盖」。
3. **模板 / 种子类写面**：`lib/api.ts` 逐字注明「行业模板的**商家面入口已整体退场**（issue #5874）；
   本客户端不再有 `getSeedTemplates` / `applySeedTemplate`，后端两个端点同批删除」，只剩**开租时自动套用**
   （`RegistrationService.applyTemplate`）⇒ **无商家可达的模板写面**（本轮未触发开租流程）。
4. **`PUT /admin/settings` / `tenant/ai-config`**：只做了「同值重发（允许集合为空）」这一形态，
   **未**逐字段穷举（字段多，且部分字段可能影响 AI/通知行为，超出本包「不改既有配置」的纪律）。
5. **`production_crafts` / `processing_categories` 写面**：未发现商家可达的写端点（表在枚举里，控制器无对应写面）。
6. **`/admin/knowledge/templates/{id}/apply`**：会创建**知识内容**（非纯配置），可能对新会话可见，
   与并行验证（真实会话）相互影响 ⇒ **有意不测**。
7. **工序「启用（disabled → active）」**：只作为复原写出现，未单列为独立探针（与 `status=disabled` 同端点同键）。
8. **`#6103`（停用工序按钮）的部署验证**：`main-live` 工作树含该提交，但**本包未验证其是否已进入运行中的编译产物**
   （只验证了 `#6102` 对应的类）⇒ 记「未验证」。

---

## 8. 下一步建议

1. **F1（P3，原 P1）—— 本线真正要找的「兄弟形态」**：
   #6102 修了「新行的**价**取错」，**没修「新行本就不该被创建」**。建议
   ① 在 `update` 路径上**不再兜底建行**（或建行后**不进读面的取价集合**）；
   ② 加**类级判据**：**任何工序设置写面调用后，该工序的价目行集合与有效价逐字不变**，
   除非该写面显式带 `unit_price`/`positions` —— `harness/sweep.mjs` 就是这条判据的可复用实现；
   ③ 回归夹具**必须显式构造**「矩阵里没有 `布帘` 列」这个前置（否则假绿，见 §5-⑤）。
2. **F2（P3）**：统一「未知键」口径 —— 与 `applicable` / `worker-page-config` 同措辞：**422 + 逐条理由**，别静默。
3. **把「写后等价性」做成常驻判据**：`snapshot → 单键写 → diff → changed ⊆ payload ∪ 审计列`，
   每个写面配一张「主面表集合 + 审计面表集合」台账。建议**先修 F1 再冻结**（否则一上来就恒红）。
4. **部署点纪律（本会话的实操教训）**：横切扫描这类**长测量**必须
   ① **每次运行自证构建点**（HEAD + 编译产物 mtime + 进程启动时刻 + 是否含目标修复）；
   ② 部署点移动时**把正对照的两种形态都写进报告**，并把结论按**当前**构建点重判级别。
5. **并行包纪律补充**：本包实测并行包会写同一批表（`复烫` 的价、`打包` 的 `布帘` 行）⇒
   此类横切包要么**只用自建对象**，要么在报告里**逐条标注外来行**，不要靠「跑得够快」。

---

## 9. 复算入口（零人工）

```bash
cd "/Users/guangzhen.zk/ai native/migao"
export REPO_ROOT="$PWD" OUT_DIR="$PWD/acceptance/2026-10-03/config-writeface-sweep/out"
node acceptance/2026-10-03/config-writeface-sweep/harness/run-all.mjs     # P1..P6 串行 + 汇总
# 单条：node acceptance/2026-10-03/config-writeface-sweep/harness/p1-selftest-f8.mjs
```

> ⚠️ 重跑会**新建并软删**自己的探针对象（前缀 `写面横切`），并在既有行上做短窗口写 + 立即还原；
> 若同租户有其它并行包在写同一批表，请按 §0.1 的归因纪律读「越界项」——
> 落在**不是我探针对象**行上的变化应记为「疑似并发干扰」，**不得**记成本写面缺陷。
> 🔴 **重跑前先看 `W0-00`**：若构建点已前进（尤其含 `1d1fe5e55` 之后的新修复），
> 正对照的形态与 F1 的级别都**需要按当前构建点重判**。
