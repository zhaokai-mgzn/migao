# 03-3 报告③｜评测体系审计（M1 ~ M16，2026-09-17）

> **来源**：issue [#4041](https://github.com/zhaokai-mgzn/migao/issues/4041) 第一节 ③；
> 审计原文曾位于 `/tmp/migao-b-order-eval-audit.md`（**已被清理，不可检索**）。
> 本文件**按 issue 正文 + 仓库内可复现事实重建**，不是原件复制。
> **锚定 SHA**：`origin/main` @ `46c91d3c`（审计基线）
> **采集时间**：2026-09-18 03:00 (+0800)
> **性质**：**冻结快照** —— 用例库增长 / runner 判据变更后立刻过期。
> 效果层断言的**口径来源是仓内单一判据源** `.github/assertion_taxonomy.py`（本批不新造口径）。

---

## 1. 裁决（issue 原文照录）

> **测试设计与架构互为因果，上游是「可观测性架构缺失」。**

## 2. 可复算断言

### 2.1 用例库规模

| # | 断言 | 复算命令 | 实测 @46c91d3c |
|---|---|---|---|
| E1 | 用例总数（**按单一源渲染后的条数**，不是 yml 行数） | §3 R1 | **310** |
| E2 | 用例 yml 文件数 | `ls .github/cases/*.yml \| wc -l` | **25** |

> **差异说明（E1 vs issue「297 条（main 312）」）**：
> 本批在基线 `46c91d3c` 上**实跑渲染器**得 **310 条**（渲染器自己打印 `ALL_CASES=310`）。
> issue 的 297 / 312 是另一次读数，**既不含其口径也不含其时点** → 按「历史读数，不可复算」对待。
> 复算命令在 §3 R1，谁都可以在自己关心的 SHA 上重跑。

### 2.2 效果层断言（issue 的「13%」）

| # | 断言 | 复算命令 | 实测 @46c91d3c |
|---|---|---|---|
| E3 | 有 ≥1 条**效果层**断言的用例占比 | §3 R2（用 `.github/assertion_taxonomy.EFFECT_FIELDS`） | **52 / 310 = 16.8%** |
| E4 | `expectations` **全部是纯工具名**（无 `args`/`component` 限定）的用例数 | §3 R2 | **175** |
| E5 | 含 `must_succeed` 的用例数 | §3 R2 | **40**（与 issue「09-17 312 条 / `must_succeed` 40」的 40 **一致**） |

> **差异说明（E3 vs issue「41 条（13%）」）**：
> 本批用仓内 `EFFECT_FIELDS = (must_succeed, db_verify, output_verify, amount_verify, post_session)`
> 判定得 **52 条（16.8%）**。issue 的 41 条（13%）**未声明口径** ——
> 若按「仅 `must_succeed` + `db_verify`」子集算本批是 40 + 13 = 53 条（去重后仍 52），
> 也对不上 41。⇒ issue 的 13% 按**历史读数，不可复算**对待。
> **注意 E3 是「下界宽松」的**：`has_effect_assertion` 还接受机器计分型 `data_checks` 里的
> `success=true`（见 §2.4），所以「效果层覆盖率」比直觉高不了 —— 真实覆盖仍只有 ~1/6。

### 2.3 时序断言（issue 的 M2）

| # | 断言 | 复算命令 | 实测 |
|---|---|---|---|
| E6 | `order_before` 的**后件**只看成功调用（`require_success=True`） | §3 R3 | `check_order_before` → `_first_qualified_round(..., require_success=True)`；docstring 原文：「有状态信息但**从未成功** → 返回 None，即不在这里造时序违规（"没写成"由 `must_succeed` / `db_verify` 判，避免同一件事重复计错）」 |
| E7 | 后件从未成功 ⇒ **不报违规**（判据弃权） | §3 R3 最小复现 | **复现成功**（3 条轨迹对照，见下） |
| E8 | 影响面：**有 `order_before`、无 `must_succeed`** 的用例 | §3 R2 | **4 条**：`OR-015` / `OR-016` / `PG-013` / `PR-025` |

```text
E7 最小复现输出（判据本体从 local_runner.py 抽出，不改语义）：
A 真反序：后件 R1 成功、前件 R2 ⇒ 应违规
    => ['order_before[validate_input before order_create]: validate_input(R2) 晚于 order_create(R1)——应 validate_input 先于 order_create']
B 正常序：前件 R1、后件 R2 成功 ⇒ 无违规
    => []
C 后件**从未成功**（线上形态）⇒ 判据弃权
    => []
```

> **因果链**：判据弃权的理由是「『没写成』由 `must_succeed` / `db_verify` 判」——
> 而 E8 的 4 条用例**恰好没有** `must_succeed`。
> ⇒ 对它们而言，「订单没落库」被**设计性地移交给了不存在的断言**（issue 原话）。
> **这是 issue M2 的定义本身，本批用可执行复现把它钉住了。**

### 2.4 `data_checks` 的计分面（issue 的 M3）

| # | 断言 | 复算命令 | 实测 @46c91d3c |
|---|---|---|---|
| E9 | `data_checks` 总条数 / 机器可计分条数 | §3 R4 | **845 条 / 15 条机器可计分（1.8%）** |
| E10 | 机器可计分条数落在多少条用例上 | §3 R4 | **15 条用例** |

「机器可计分」的判据由 `local_runner` 决定并在 `assertion_taxonomy.MACHINE_DATA_CHECK_MARKERS` 里复刻
（`success=true` / `error.code=` / `未被调用` / `not called`）。

> **差异说明（E9 vs issue「791 条里仅 14 条」）**：本批实测 **845 / 15**，issue 写 **791 / 14**。
> 两个数都随用例库增长变动；issue 未给出口径命令。⇒ 本批只用**自己的可复算值**，
> issue 的 791/14 按**历史读数，不可复算**对待。

### 2.5 落库通道的 B/C 不对称（issue 的 M4）

| # | 断言 | 复算命令 | 实测 @46c91d3c |
|---|---|---|---|
| E11 | 带 `db_verify` 的用例按 persona 分布 | §3 R4 | **`mibao`（B 端）= 1 条**；`xiaobu` + 默认（C 端）= 12 条 |

> issue 写「`db_verify[order_phone]` 7 条全 C 端、**B 端 0 条**」——
> 本批的**粗口径**（不看 `db_verify` 的具体字段）得 B 端 **1** 条，与「B 端 ≈ 0」同向。
> 精确到 `order_phone` 字段的计数本批**未复算**（需按 `db_verify` 内的字段名过滤）→ 该点 `未取证`。

### 2.6 门禁与可观测面（issue 的 M5 / M8 / M13）

| # | 断言 | 复算命令 | 实测 |
|---|---|---|---|
| E12 | `e2e-real` 的 `schedule` **已停跑** | §3 R5 | **注释掉**，且注释自带原因：`# 2026-09-06 暂停定时调度（issue #2957）` |
| E13 | 行为门禁**恒 `exit 0`** | §3 R5 | `agent-behavior-eval.yml` 含 **4 处 `exit 0`**，其中一处注释明写「★ 恒 exit 0：规则命中失败降级为报告」 |
| E14 | 行为门禁**不在 required checks** | §3 R6 | 当时读数 **9 条**；本批实测（2026-09-18）**12 条**，**仍无** `Agent Behavior Eval` —— 但**已有** `Case Trust Gate (断言可信度)` / `Case Coverage Gate` / `Case Contract` ⇒ issue B1 的「断言/覆盖类 0 条」**已不成立** |
| E15 | `metadata` 只有 4 个键，无执行结果字段 | §3 R7 | `chat.py` 只构造 `images` / `tool_calls` / `interactive` / `interactive_answered` |
| E16 | SSE `tool_call` 对 `tool_not_found` 照发 | §3 R7 | 基线 `chat.py` 已有注释「#3976（P4）：未执行的调用（tool_not_found）不得…」⇒ **该点已在基线前修** |

> ⚠️ **E14/E16 是「issue 结论已过期」的两例**，照实登记而不是照抄 issue。
> 这正是 `migao-dev-flow` §19.2③「不写死易变数字」的现场教材：**门禁集合是活的**。

## 3. 实跑输出（逐字）

```bash
# ── R1：渲染基线用例库并计数（渲染器自己会打印条数）──
$ rm -rf /tmp/cases_base && mkdir -p /tmp/cases_base
$ git archive 46c91d3c .github/cases | tar -x -C /tmp/cases_base
$ python3.11 .github/render_cases.py --cases /tmp/cases_base/.github/cases \
    --out-eval /tmp/ec_base.py --out-md /tmp/cb_base.md
✓ eval_cases.py → /tmp/ec_base.py（310 条）
✓ casebook → /tmp/cb_base.md（310 条）
✓ 生成物自检通过（ALL_CASES=310）
```

```bash
# ── R2：效果层断言（口径 = 仓内单一判据源 .github/assertion_taxonomy.py）──
# 分析脚本 /tmp/analyze_cases.py 的要点（逐条断言见 §2）：
#   sys.path.insert(0, '.github'); import assertion_taxonomy as T
#   T.has_effect_assertion(case) / T.machine_scored_data_checks(case)
$ cd /tmp/base_tax && python3.11 analyze_cases.py ec_base.py     # ec_base.py = R1 的产物
用例总数（渲染后）： 310
含 ≥1 条效果层断言（EFFECT_FIELDS=('must_succeed', 'db_verify', 'output_verify', 'amount_verify', 'post_session')）的用例：52 / 310 = 16.8%
expectations 全部为纯工具名（无 args/component 限定）的用例： 175
data_checks 总条数：845；机器可计分：15（1.8%）；落在 15 条用例上
db_verify 命中用例总数： 13
    xiaobu: 10  (该端用例总数 44)
    xiaobu(默认): 2  (该端用例总数 246)
    mibao: 1  (该端用例总数 20)
含 must_succeed 的用例数： 40
只有 order_before 没有 must_succeed 的用例数： 4 ['OR_015', 'OR_016', 'PG_013', 'PR_025']
```

```bash
# ── R3：M2 最小复现（判据抽出，不改语义）──
$ python3.11 /tmp/m2_repro.py
轨迹：validate_input(R1,ok) → order_create(R2,fail) → order_create(R3,fail)
A 真反序：后件 R1 成功、前件 R2 ⇒ 应违规
    => ['order_before[validate_input before order_create]: validate_input(R2) 晚于 order_create(R1)——应 validate_input 先于 order_create']
B 正常序：前件 R1、后件 R2 成功 ⇒ 无违规
    => []
C 后件**从未成功**（线上形态）⇒ 判据弃权
    => []
```

```bash
# ── R4：M3/M4 见 R2 的输出（data_checks / db_verify 两段）──
# 口径锚点（assertion_taxonomy 的 MACHINE_DATA_CHECK_MARKERS，复刻 runner 计分口径）：
$ grep -n "MACHINE_DATA_CHECK_MARKERS" -A 5 .github/assertion_taxonomy.py
174:MACHINE_DATA_CHECK_MARKERS: tuple[str, ...] = (
175-    "success=true",
176-    "error.code=",
177-    "未被调用",
178-    "not called",
179-)
```

```bash
# ── R5：M5（e2e-real schedule 停跑）+ M8（行为门禁恒 exit 0）──
$ git show 46c91d3c:.github/workflows/e2e-real.yml | sed -n '8,13p'
  # 2026-09-06 暂停定时调度（issue #2957）：连续 5+ 日 daily failure 且自动开 issue 制造噪音，
  # 待失败根因排查 + 本地验证提速落地后再恢复；期间保留 workflow_dispatch 手动触发。
  # schedule:
  #   # 每天 00:00 CST（UTC+8）= UTC 16:00，低峰期跑真实 LLM 能力回归
  #   - cron: '0 16 * * *'
$ git show 46c91d3c:.github/workflows/agent-behavior-eval.yml | grep -c 'exit 0'
4
$ git show 46c91d3c:.github/workflows/agent-behavior-eval.yml | sed -n '667,670p'
          # ★ 恒 exit 0：规则命中失败降级为报告（脚本本身出错另有其退出码，
          #   由 set -e/pipefail 兜住 —— 不要用 `|| true` 掩盖 infra 故障）。
          exit 0
```

```bash
# ── R6：M8/E14 required checks（**活环境读数，采集时 2026-09-18**）──
$ gh api repos/zhaokai-mgzn/migao/branches/main/protection --jq '.required_status_checks.contexts'
["Block .env files (except .env.example)","admin-api unit tests","ai-agent-service unit tests",
 "admin-web typecheck + unit tests","mini-app typecheck + unit tests","QA Growth Gate",
 "ci workflow helper unit tests","Secret Scan (gitleaks)","Danger Scan (破坏性变更检测)",
 "Case Trust Gate (断言可信度)","Case Coverage Gate","Case Contract (truths_ref)"]
$ gh api repos/zhaokai-mgzn/migao/branches/main/protection/required_status_checks --jq '.contexts | length'
12
```

```bash
# ── R7：M13/E15/E16 metadata 与 tool_not_found ──
$ git show 46c91d3c:$A/api/chat.py | grep -n '"images"\|"tool_calls"\|"interactive"\|"interactive_answered"'
2135:            "images": msg_images if msg_images else None,
2136:            "tool_calls": msg.get("tool_calls"),
2137:            "interactive": _mask_card_for_customer(interactive_data, current_user),
2139:            "interactive_answered": interactive_answered,
$ git show 46c91d3c:$A/api/chat.py | grep -n "tool_not_found"
1076:                                # issue #3976（P4）：未执行的调用（tool_not_found）不得
1082:                                if _res_error == "tool_not_found":
```

## 4. M1~M16 的覆盖情况（如实登记哪些进了本归档）

| 机制 | 本归档状态 |
|---|---|
| M1 存在性断言冒充效果断言 | **取证**（§3 R2：175 条纯工具名 + `check_expectation` 的纯工具名分支不看 `success`） |
| M2 时序断言主动弃权 | **取证 + 最小复现**（§2.3/§3 R3） |
| M3 散文 `data_checks` 零权重 | **取证**（§2.4） |
| M4 落库通道 B/C 不对称 | **部分取证**（粗口径 B 端 1 条；字段级未复算） |
| M5 唯一零 Mock 真落库层停跑 | **取证**（§3 R5） |
| M6~M7 | **未取证**（issue 未在 #4041 正文展开，本批无来源） |
| M8 行为门禁恒绿 + 非 required | **取证**（§3 R5/R6；「非 required」部分已因门禁集合变化而过期） |
| M9~M12 | **未取证**（同上） |
| M13 可观测面不区分「请求了/执行了」 | **取证**（metadata 4 键；`tool_not_found` 侧已在基线前修） |
| M14~M16 | **未取证**（同上） |

> issue #4041 正文只点名了 M1/M2/M3/M4/M5/M8/M13 七条（「16 条机制（M1~M16），核心：…」），
> 其余九条**没有内容进本 issue 正文**，而原报告已在 `/tmp` 被清理 ⇒ **无法重建，不编造**。

## 5. 未取证 / 不可复算

- **M6/M7/M9~M12/M14~M16**：正文未展开 + 原文不可检索 ⇒ 不重建。
- **`db_verify[order_phone]` 字段级 7 条全 C 端**：需按字段名过滤，本批未做。
- **用例总数 297 / 312、效果层 41 条（13%）、`data_checks` 791/14**：issue 未给口径命令 ⇒ 历史读数。
- **「同期自动开 42 条失败 issue，其中 4 条点名 OR-016/OR-028 —— 对应 4 个 PR 全部 MERGED」**：
  需查历史 issue/PR 状态，本批未做 ⇒ `未取证`。
- **「79 条 B 端用例 62 条（78%）零效果层断言」**：本批口径下 B 端用例总数 **20**（`persona: mibao`）
  + 默认 persona 里可能还有 B 端用例 ⇒ **分母口径不明，未复算**。