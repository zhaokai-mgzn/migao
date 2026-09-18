# 03-5 线上会话取证 + 研发模式评分卡（2026-09-17）

> **来源**：issue [#4041](https://github.com/zhaokai-mgzn/migao/issues/4041) 第三节（线上会话取证）、
> 第四节（研发模式质量评分卡）、第五节（方法论教训）。
> **锚定 SHA**：`origin/main` @ `46c91d3c`（审计基线）
> **采集时间**：2026-09-18 03:00 (+0800)
> **性质**：**冻结快照，且本文件绝大多数内容「不可复算」** ——
> 线上 DB 读数、历史会话 ID、当时的工作区状态都**无法从仓库重建**。
> 本文件的核心价值是 **§4「不可复算资产登记」**：把「哪些数字以后不要再引用」写死。

---

## 0. 本文件为什么长这样

issue 第三节的取证来自**云 dev RDS**（与生产共用）—— 78 条消息的 `metadata`、
5 个会话的完整链路、当日订单的唯一性判定。这些**不是仓库里的东西**：
没有 fixture、没有 artifact、没有可回放的 transcript。

按本仓 `migao-acceptance`「证据等级」的要求，**引用不到证据的结论不得写成已核事实**。
因此本文件采取如下写法：

- 结论照录（它们是审计的产出，翻译成本仓语言仍然成立）；
- **每个数字都标 `历史读数（不可复算）`**；
- 凡**能**在仓库里找到落点的（如 `metadata` 的键集、`createOrderForAgent` 不设 `discountAmount`），
  给出命令与实测；
- 未能取证的结论在 §5 汇总。

## 1. 线上会话取证（2026-09-17，B 端 5 个会话）

**取证渠道**（issue 原文）：云 dev RDS（与生产共用）18,473 会话 / 68,582 消息；
本机 IP 按 `migao-dev-flow` §10 追加到白名单 `dev_local`（**只追加、原 IP 全保留**）。全部只读。

| 结论 | 类型 | 仓库内可否复算 |
|---|---|---|
| S1 `sess_202d55d49a254a10`（#3976 的线上实证会话）：完整链「录单 → 选商品卡 → 核对 SKU+加工项 → `validate_input(target_tool=order_create)` → 点确认卡 → `order_create` **被请求** → 助手说「已转到订单流程…请稍候」→ **DB 无任何订单**」 | 历史观察 | ❌ 不可复算（无 transcript artifact） |
| S2 `sess_d35caf31a7ce4197`：点卡确认 **¥498** → 助手「抱歉，刚才调用出错了，我重新提交订单」→ 3 次承诺 → 用户追问「没提交成功？」 | 历史观察 | ❌ 不可复算 |
| S2 附：DB 当日**唯一**订单为 **¥133.80**，且 `discount_amount=5.00` 而 `createOrderForAgent` **从不设置该字段** ⇒ 该单不可能来自 agent 路径 | **可查代码侧锚点** | ⚠️ **代码侧可查**（见 §2.1），**DB 侧不可复算** |
| 卡片对照：**真发卡的 7 个回合 → `interactive_answered` 全为 True**；**自称已发卡但无卡的 3 个回合 → 全部无卡** | 历史观察 | ❌ 不可复算 |
| 可观测性：78 条消息的 `metadata` **只有 4 个键**（`tool_calls`/`interactive`/`interactive_answered`/`images`），**无任何执行结果字段**；今日消息零失败标记；`audit_logs` **0 行** | **部分可查**（键集在代码里） | ⚠️ **键集可查**（§2.2），DB 行数不可复算 |

## 2. 仓库侧可查锚点（真正站得住的那一半）

### 2.1 `createOrderForAgent` 不设置 `discount_amount`

```bash
$ S=backend/admin-api/src/main/java/com/migao/admin/service/OrderService.java
# ① createOrderForAgent 方法体（第 1549 行起，到下一个方法前的 BFF 段）内**没有任何 discount 赋值**
$ git show 46c91d3c:$S | sed -n '1549,1604p' | grep -n "discount\|Discount"
（无输出 —— 零命中）
# ② 全文件的 discountAmount 赋值点都在**另一个方法**里（手工下单路径）
$ git show 46c91d3c:$S | grep -n "discountAmount\|setDiscountAmount"
455:        BigDecimal discountAmount = request.getDiscountAmount() != null ? request.getDiscountAmount() : BigDecimal.ZERO;
456:        if (discountAmount.compareTo(BigDecimal.ZERO) < 0) {
460:            BigDecimal expected = totalAmount.subtract(discountAmount);
464:                                totalAmount, discountAmount, expected, request.getActualAmount()));
484:        order.setDiscountAmount(discountAmount);
# ③ 列默认值 = 0 ⇒ agent 路径落库的订单 discount_amount 只可能是 0（或列默认值）
$ grep -n "discount_amount" docs/sql/schema.sql
1461:ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_amount DECIMAL(12,2) DEFAULT 0;
```

> **本批实测结论（强于 issue 原文的表述）**：
> `createOrderForAgent` 方法体（第 1549~1604 行）内**零 `discount` 出现**，
> 而 `orders.discount_amount` 的列默认值是 **0** ⇒ **经 agent 路径创建的订单，
> 该列在 DB 里只可能是 0**。因此「当日唯一订单 `discount_amount=5.00` 不可能来自 agent 路径」
> 这条推理**在代码侧是站得住的**。
> **但 DB 侧前提（当日到底有几单、那一单确实是 5.00）不可复算** ——
> ⇒ 引用时只能说「**代码面支持**这个结论」，不能说「已证」。

### 2.2 `metadata` 的键集（M13 的线上形态）

```bash
$ git show 46c91d3c:backend/ai-agent-service/app/api/chat.py \
    | grep -n '"images"\|"tool_calls"\|"interactive"\|"interactive_answered"'
2135:            "images": msg_images if msg_images else None,
2136:            "tool_calls": msg.get("tool_calls"),
2137:            "interactive": _mask_card_for_customer(interactive_data, current_user),
2139:            "interactive_answered": interactive_answered,
```

⇒ **「会话记录里『调了』与『成了』不可区分」这个结论在代码侧成立**：
`metadata` 的构造点只有这 4 个键，无任何执行结果字段。
（DB 侧「78 条消息只有 4 个键」是它的线上实例 —— 两者一致，互相印证。）

## 3. 研发模式质量评分卡（issue 第四节，7 维度）

issue 原表 + **本批判定**（凡能落到仓库命令的都补了命令）：

| 维度 | issue 现状 | 本批判定 |
|---|---|---|
| 静态门禁 | 9 条 required（+P11 的 3 条静态）✅ | ⚠️ **已过期**：本批实测 **12 条** required（§4.1 命令）；「9 条」按历史读数 |
| L0 守卫族 | 5 个已落 main ✅ | ✅ **取证**：`test_case_trust_gate.py` / `test_l0_reachability_guards.py` / `test_behavior_gate_reachability.py` / `test_tool_input_contract_guards.py` / `test_workflow_issue_permissions.py` 均在 `origin/main` |
| 交付物搁浅检测 | 内容判据 + R8 `headRefOid` ✅（R8 本次实测 4 次） | ⚠️ **未取证**：`headRefOid` 在 `scripts/` 与 `.github/` 下**搜不到**（§4.2）；「实测 4 次」无仓库内来源 |
| 集成检查器 | 落库，5/7 纪律已落码 ⚠️ **未接 CI** | ✅ **取证**：`scripts/batch-integrate-check.sh` 存在，头部自述「未覆盖项：R1 / R3」；`grep -rn batch-integrate-check .github/workflows/` **零命中** ⇒ 确实未接 CI |
| 活锚新鲜度 | **已修**（独立镜像，与 main 逐字节一致）✅ | ✅ **取证**：`./scripts/preset-anchor-check.sh` 退出 0，输出「内容与 origin/main 逐字节一致（6 个文件）」（§4.3）；⚠️ **但见 §5 的「活锚 sha ≠ 基线 sha」观测** |
| 验收协议 | L1/L2/UA + 可达性判据 ✅ | ✅ **取证**：`docs/testing/acceptance-protocol.md` 有 `### 1.2 L1/L2/UA 断言降级阶梯` 等节（§4.4） |
| **行为层拦截力** | ❌ **零**（行为评测非 required 且恒 `exit 0`）—— 最关键缺口 | ✅ **取证（基线时点）**：`exit 0` × 4 处（[03-3](03-3-eval-system-audit.md) §3 R5）+ 不在 required（§4.1）。⚠️ **现已改判**：`origin/main` 已**删除** `agent-behavior-eval.yml` 的 `behavior-eval` job（PR 阶段零真实 LLM，`migao-dev-flow` v1.31 / #4034） |
| 纪律落码率 | §20 **5/7**（R1 修机制、R3 失败集收敛**未落码**） | ✅ **取证**：`scripts/batch-integrate-check.sh` 头部自述未覆盖 R1/R3 ⇒ **5/7 一致** |

### 3.1 评分卡里「行为层拦截力」的现状变化（本批实测）

```bash
$ git show origin/main:.github/workflows/agent-behavior-eval.yml | grep -nE '^  [a-z-]+:$'
129:jobs:
131:  map:
# ⇒ origin/main 上只剩 map job；baseline 上的 behavior-eval job（原第 406 行）已删除
```

## 4. 实跑输出（逐字）

```bash
# ── 4.1 required checks（活环境读数，采集时 2026-09-18）──
$ gh api repos/zhaokai-mgzn/migao/branches/main/protection/required_status_checks --jq '.contexts | length, .[]'
12
Block .env files (except .env.example)
admin-api unit tests
ai-agent-service unit tests
admin-web typecheck + unit tests
mini-app typecheck + unit tests
QA Growth Gate
ci workflow helper unit tests
Secret Scan (gitleaks)
Danger Scan (破坏性变更检测)
Case Trust Gate (断言可信度)
Case Coverage Gate
Case Contract (truths_ref)
```

```bash
# ── 4.2 交付物搁浅检测：headRefOid 搜不到 ──
$ grep -rln "headRefOid" scripts/ .github/
（无输出 —— 零命中）
```

```bash
# ── 4.3 活锚新鲜度自检（退出码 0 = 新鲜）──
$ ./scripts/preset-anchor-check.sh; echo "exit=$?"
🔎 活锚新鲜度（DSH 真正加载的那份内容；地雷 B / issue #4026）
   活锚：/Users/guangzhen.zk/.dsh/.agent-presets/migao
   判定依据：显式 `--anchor` ⇒ 一律判定
   活锚检出：/Users/guangzhen.zk/migao-preset-anchor @da9d66e85200（与基线同一提交）
   基线：origin/main @da9d66e8（仓库 …/migao-wt/4041-archive；只读**本地** ref —— 要连远端一起核请先 fetch/刷新）
   migao-acceptance   活锚=1.11.0 基线=1.11.0
   migao-dev-flow     活锚=1.31.0 基线=1.31.0
   ✅ 活锚新鲜：内容与 origin/main 逐字节一致（6 个文件），且 sha 为同一提交
exit=0
```

```bash
# ── 4.4 验收协议：L1/L2/UA + 可达性判据 ──
$ grep -n "^### 1.2\|L1/L2/UA" docs/testing/acceptance-protocol.md | head -3
89:### 1.2 L1/L2/UA 断言降级阶梯
```

```bash
# ── 4.5 集成检查器落码 / 未接 CI ──
$ head -30 scripts/batch-integrate-check.sh | grep -n "R1\|R3"
25:# 未覆盖项（**照实登记，不把"写进技能"写成"有门禁"**；同 §19 表口径）：R1 修机制不修事故点 / R3 失败集只许收敛
$ grep -rn "batch-integrate-check" .github/workflows/
（无输出 —— 零命中 ⇒ 未接 CI）
```

```bash
# ── 4.6 L0 守卫族在 main 上 ──
$ for f in test_case_trust_gate.py test_l0_reachability_guards.py test_behavior_gate_reachability.py \
           test_tool_input_contract_guards.py test_workflow_issue_permissions.py; do
    printf "%-45s %s\n" $f "$(git cat-file -e origin/main:tests/unit_ci_workflows/$f 2>/dev/null && echo 已落main || echo 缺失)"
  done
test_case_trust_gate.py                       已落main
test_l0_reachability_guards.py                已落main
test_behavior_gate_reachability.py            已落main
test_tool_input_contract_guards.py            已落main
test_workflow_issue_permissions.py            已落main
```

## 5. 不可复算资产登记（**引用黑名单**）

以下内容**不要**在后续文档/结论里当点值引用 —— 它们既不在仓库里，也没有可重放的 artifact：

| # | 不可复算的内容 | 为什么 |
|---|---|---|
| N1 | 云 dev RDS 的 **18,473 会话 / 68,582 消息** | 活库快照；无导出的 fixture/artifact |
| N2 | 5 个线上会话的**完整链路**（`sess_202d55d49a254a10` / `sess_d35caf31a7ce4197` …） | 会话内容未落盘；RDS 数据会滚动 |
| N3 | 「当日唯一订单 ¥133.80 / `discount_amount=5.00` / `created_at` 与 `updated_at` 相差 0.2ms」 | DB 读数 |
| N4 | 「78 条消息 metadata 只有 4 个键」「今日消息零失败标记」「`audit_logs` 0 行」 | DB 读数（**键集本身**在代码侧可查，见 §2.2） |
| N5 | 「近 7 天 723 条『自称发卡』中 708 条（97.9%）前 2 轮也无卡」 | DB 读数 |
| N6 | 「真的发了卡的 7 个回合 / 声称已发卡但无卡的 3 个回合」 | DB 读数 |
| N7 | 审计时的 **required checks = 9 条** | 活环境读数（现已 12 条，见 §4.1） |
| N8 | 「R8 `headRefOid` 本次实测 4 次」 | 仓库内搜不到 `headRefOid`（§4.2）⇒ 无来源 |
| N9 | 方法论第 1~5 条里的具体实证（`P5` 三点 diff 误报「移除=4」、`grep` 假红/假绿的具体条数） | PR 级过程记录，未落 artifact |
| N10 | **原始审计报告原文**（`/tmp/migao_audit/TOOL_LAYER_AUDIT.md`、`/tmp/migao-b-order-eval-audit.md`） | `/tmp` 已清理，**不可检索** |

> **N10 是这份归档存在的理由本身**：issue 说的就是「`/tmp` 会被清掉」—— 现在已经清了。

## 6. 方法论教训（issue 第五节，照录 + 证据等级）

| # | 教训 | 仓库内落点 | 等级 |
|---|---|---|---|
| 1 | **frontmatter 结构性损坏**：把新节插进 YAML 注释块内部 ⇒ `description` 被静默切掉、技能静默降级 | `migao-dev-flow` v1.21 已把沿革迁入正文；`tests/unit_ci_workflows/test_agent_presets_guard.py` 是判据 | **取证（已落码）** |
| 2 | **三点 diff 假绿**：`base...branch` 是相对 merge-base；集成检查要的是**两点** | `scripts/batch-integrate-check.sh` 头部已写明「必须用两点 `base..branch`，不是三点」；`migao-dev-flow` v1.30 同步登记 | **取证（已落码）** |
| 3 | **检查器两个真 bug**（`--all` 退出码丢失 ⇒ 批量模式永远 exit 0；macOS bash 3.2 变量后紧跟中文） | `tests/unit_ci_workflows/test_step_exit_code_propagation.py` 等 L0 判据 | **部分取证**（具体两处修复未逐行回溯） |
| 4 | **粗字符串匹配双向骗人**（`grep` 假红：意图描述键报 0 → 改 AST 后 ✅；`grep` 假红：已下线工具报 2，实为注释散文） | `.github/assertion_taxonomy.py` 头部自述「**精确枚举，禁用宽正则**」+ 本批的 AST 口径即是这条的实践 | **取证（范式已落码）** |
| 5 | **local `origin/main` 落后**导致误判「交付物搁浅」 | `scripts/preset-anchor-check.sh` / `agent-presets-guard.py anchor`（#4026）+ `migao-dev-flow` §18.2 | **取证（已落码）** |

> ⇒ **五条方法论教训里有四条已经在仓库里落成了判据/工具**。这是本次审计「团队在收敛」的
> 最硬证据 —— 比 §3 的任何一条 ✅ 都更有说服力（口头的 ✅ 会过期，落码的判据不会）。

## 7. 未取证 / 不可复算汇总

- **§1 全部线上会话结论**：无 transcript artifact ⇒ 结论可引、**数字不可引**（§5 N1~N6）。
- **§3「R8 `headRefOid` ✅（本次实测 4 次）」**：仓库内零命中 ⇒ **未取证**（§5 N8）。
- **§3「静态门禁 9 条」**：已过期（现 12 条）⇒ 历史读数。
- **§3「活锚新鲜度已修」**：本批自检通过（§4.3），**但输出里「活锚检出 sha `da9d66e8`」与
  「基线 `origin/main`」的 sha 在当天晚些时候已推进到 `8e03e5b3`** —— 脚本自己用
  `（与基线同一提交）` 作了判定并给出 ✅。**本批不追加判定**：这是一个**活环境读数的时效问题**
  （`migao-dev-flow` §18.7），只登记「脚本退出 0、内容逐字节一致」这一条可复算事实。
- **§3「纪律落码率 5/7」**：与脚本头部自述一致（§4.5），但**7 条纪律各自的落码判据本批未逐条核**。