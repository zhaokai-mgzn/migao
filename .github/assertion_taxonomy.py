#!/usr/bin/env python3
"""断言可信度判据 —— **单一判据源**（假红/假绿结构性护栏 A 层，#3483 T1 扩展格）。

## 为什么需要这个模块

PR Check 的用例侧门禁原本只有 `Case Contract (truths_ref)`（引用可解析 + 生成物新鲜）、
`Case Coverage Gate`（覆盖映射）、`QA Growth Gate`（改代码要有测试）—— **没有任何一条
校验断言本身是否可信**。于是「写了断言」与「断言真能判红」之间没有任何结构性约束，
以下缺陷全部被门禁放行进来（均有实证，见 `RULES` 的 `why` 字段）：

| 形态 | 实证 |
|---|---|
| 用例**物理不可满足** | `CU-003` 让 agent 挂种子目录里不存在的标签 `VIP2活跃`（种子只有 `VIP2`/`活跃`）→ #3832 |
| 散文禁令**独自承载**关键判据 | `PG-013` 首跑功能正确，却因 `forbidden_text`（**全程**语义、无轮次作用域）命中 R1 良性措辞而判红 → #3833 |
| 写类用例**无效果层断言** | 31 条写用例「调用了 ≠ 成了」→ #3778 |
| 机器计分关键词**缺失** = 不计分 | `data_checks` 里「sku_update 成功（价格落库）」**没有 `success=true`** ⇒ 该项**不计分** = 假绿 → #3559（`PR-021`） |
| 写类用例**无自清理** ⇒ 重试前置不等价 | #3800 / #3797 |
| **写案例无自清理/准备失败路径未纳入折叠** | #3797 |

**为什么必须是单一判据源**（本模块存在的核心理由）：
静态门禁（`.github/case_trust_gate.py`）与后续的动态分类器（runner 侧归因）**必须共用一处口径**。
两处各写一份「写工具集合 / 效果层断言集合」，就一定会漂移 —— 届时静态放行、动态判红
（或反之），门禁的可信度直接归零（形态同 `migao-acceptance`「注释漂移 = 假绿来源」）。

**依赖纪律**：纯函数、零第三方依赖、无副作用（不读文件、不联网、不 import 后端 app 包），
因此可被 L0 单测（`tests/unit_ci_workflows/`）与 CI job 直接调用 —— CI 的
`ci workflow helper unit tests` job 只 `pip install pytest pyyaml`（见 pr-check.yml）。
**唯一例外**（#4244）：`backend_contract_scoring_channel(case, repo_root)` 在调用方
**显式传入 `repo_root`** 时做一次 `traces.tests` 存在性校验（`Path.is_file()`，stdlib）——
不传即不做（按未成立处理，fail-closed）；`judge_case` 默认路径仍不读文件。

## 与 #3483 的关系

本模块 = **#3483「评测体系根本解」T1「L0 静态不变式层」的扩展格：断言可信度**。
T1 已有的「case 库静态校验（expectation 引用工具 ∈ persona 工具集）」在
`tests/unit_ci_workflows/test_assertion_specs_wellformed.py` / `test_xiaobu_case_set.py`；
本模块补的是**同一层里缺的那一格**（可失败性 / 效果层断言 / 自清理与前置等价 / 散文禁令不得单独承载）。

## 未实装项

见 `.github/case-trust-unimplemented.json`（**如实登记**，不写成恒真判断凑数）。
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
# 一、写工具集合 / 写 action（**精确枚举，禁用宽正则**）
# ══════════════════════════════════════════════════════════════════════════════
#
# 口径来源（真值锚点，不是拍的）：`backend/ai-agent-service/app/tools/base.py` 的
# `read_only: bool = True`（第 83 行，@82d20090）+ 各工具类里 `read_only = False`
# 的覆写；`registry.py` 用 `is_write = not tool.read_only` 判写操作审计
# （按 `is_write = not tool.read_only` 文本检索）。
#
# **为什么不用宽正则**：`customer_manage` 既有 `add_tag`（写）又有 `list`/`detail`
# （读）；`inventory_manage` 既有 `adjust`（写）又有 `query`（读）。一条
# `.*manage.*` 或 `.*create|update|delete.*` 正则会把 `customer_manage(action=query)`
# 这种**纯读**误判成写用例 —— 误伤的代价是给正确用例加无谓的断言要求（假红）。
# 故：**工具级显式枚举 + action 级显式枚举**，二者都写死在下方常量里。
#
# `WRITE_TOOLS`：整工具即为写（该类没有 read_only action，任何调用都是写）。
# ⚠️ 只列**当前可达**的工具 —— 工具下线/改名后必须从本表移除，否则出现**幽灵写工具**
# （判据从「工具真实可达」悄悄变成「曾经可达」，且不会让任何用例变红）。不变式测试：
# tests/unit_ci_workflows/test_case_trust_gate.py::TestDegenerateGuardRails
#   ::test_write_tool_sets_only_name_reachable_tools（真值 = eval_case_filter 的两端工具集并集）。
WRITE_TOOLS: frozenset[str] = frozenset({
    # read_only = False 且**未**声明 read_only_actions 的工具
    # ⚠️ `human_handoff` 已于 2026-09-19 按用户裁定退场（模型不可达：不在默认注册表、
    #    不在任何 skill 工具集）⇒ **从本表移除**（本表只列当前可达的工具，见上方幽灵
    #    写工具口径）。工具类文件仍在 `app/tools/human_handoff.py`，但它只能被直测类
    #    单测实例化，用例断言它会永远失败 ⇒ 留在表里只会让"写用例"分类产生假红。
    #    工具文件删除（阶段二）时无本表改动。
    "aftersale_create",            # WRITE|NON_IDEMPOTENT
    "order_create",                # WRITE
    "order_manage",                # WRITE|DESTRUCTIVE
    "product_manage",              # WRITE|DESTRUCTIVE
    "product_processing_item_manage",  # WRITE|IDEMPOTENT
    "product_update",              # WRITE|IDEMPOTENT
    "sku_update",                  # WRITE|IDEMPOTENT
    # 加工单写工具（issue #4196 恢复接入 ⇒ 重新落回「当前可达」面，必须在此表态；
    # #3917 下线期它们**不在**本表 —— 正是「已注册写工具必须显式表态」这条摩擦的实例）。
    # 两者**整工具即写**：`processing_order_generate` 只有 `generate`（批量建单 + 订单
    # confirmed→producing）；`processing_order_update` 的 `VALID_ACTIONS` 四个
    # （issue/start/complete/cancel）**全是状态迁移**，类里没有 `read_only_actions`
    # ⇒ 不存在只读 action ⇒ 进 `WRITE_TOOLS` 而非 `WRITE_TOOL_ACTIONS`。
    "processing_order_generate",   # WRITE|NON_IDEMPOTENT
    "processing_order_update",     # WRITE|DESTRUCTIVE|NON_IDEMPOTENT
})

# `WRITE_TOOL_ACTIONS`：工具级 read_only=False，但**只有部分 action 是写**
# （值 = 该工具的写 action 集合；`read_only_actions` 里的 action 是读，**不算写**）。
# 真值锚点 = 各工具类的 `read_only_actions`（按该文本检索）
#   · customer_manage      read_only_actions = {"list","detail","list_tags"}
#   · after_sales_manage   read_only_actions = {"list","detail"}
#   · employee_manage      read_only_actions = {"list","detail"}
#   · finance_api          read_only_actions = frozenset({"get_summary","get_transactions","get_reconciliation"})
#   · inventory_manage     read_only_actions = {"query","low_stock_alert"}
#   · notification_manage  read_only_actions = {"list","unread_count"}
#   · processing_item_manage read_only_actions = {"list_categories","calculate_price"}
#   · role_manage          read_only_actions = {"list","all","detail","list_permissions"}
#   · session_manage       read_only_actions = {"list","monitor","detail"}
#   · settings_manage      read_only_actions = {"get_settings","get_ai_config","login_logs"}
#   · category_manage      read_only_actions = {"tree"}
WRITE_TOOL_ACTIONS: dict[str, frozenset[str]] = {
    "customer_manage": frozenset({
        "update", "add_tag", "remove_tag", "create_tag", "update_tag", "delete_tag",
    }),
    "after_sales_manage": frozenset({"update_status"}),
    "employee_manage": frozenset({
        "create", "update", "delete", "reset_password", "toggle_status",
    }),
    "finance_api": frozenset({"create_transaction"}),
    "inventory_manage": frozenset({"adjust"}),
    "notification_manage": frozenset({
        "mark_read", "create", "delete", "mark_all_read",
    }),
    "processing_item_manage": frozenset({"create", "update", "delete"}),
    "role_manage": frozenset({"create", "update", "delete", "assign_permissions"}),
    "session_manage": frozenset({"assign", "end"}),
    "settings_manage": frozenset({
        "update_settings", "update_ai_config", "change_password",
    }),
    "category_manage": frozenset({"create", "update", "delete"}),
}

# 安全护栏：集合不得为空（空集合 = 所有写用例都判成读用例 = 门禁静默变空壳）。
assert WRITE_TOOLS, "WRITE_TOOLS 不得为空 —— 空集会让写用例全部漏判（门禁空壳）"
assert WRITE_TOOL_ACTIONS, "WRITE_TOOL_ACTIONS 不得为空 —— 同上"

_ALL_WRITE_TOOLS: frozenset[str] = WRITE_TOOLS | frozenset(WRITE_TOOL_ACTIONS)


# ══════════════════════════════════════════════════════════════════════════════
# 二、效果层断言集合 / 非效果层（「调用了 ≠ 成了」）
# ══════════════════════════════════════════════════════════════════════════════

# 「效果层」= 断言的是**系统状态真的变了**（落库 / 产出 payload / 工具返回 success），
# 而不是「工具被调用过」。判定来源：`tests/agent_eval/local_runner.py` 里每个断言
# 检查器的语义（按 `check_must_succeed` / `check_db_verify` / `check_output_verify`
# / `check_amount_verify` / `check_post_session` 等函数名检索）。
#
# ⚠️ 为什么 `required_args` **不属**效果层：它只证明「调用时参数给对了」，
# 工具返回 `success=false` 照样通过 ⇒ 「调用了 ≠ 成了」（#3778 的原话）。
EFFECT_FIELDS: tuple[str, ...] = (
    "must_succeed",     # 写工具必须有**至少一次 success=true**（issue #3361）
    "db_verify",        # 创建后查 admin-api 断言落库值（issue #3056）
    "output_verify",    # 工具计算产出 payload 对不对（issue #3367）
    "amount_verify",    # 金额正确性（单价接地/小计/总额，issue #3365）
    "post_session",     # 会话关闭后落库断言（user_memories，issue #3357）
)

EFFECT_FIELD_WHY: dict[str, str] = {
    "must_succeed": "『调了≠成了』：证明写操作真的 success=true（#3361/#3778）",
    "db_verify": "落库层真值核对（#3056）：只有它能证伪『工具说成了、库里没有』",
    "output_verify": "产出侧核对（#3367）：算出来的数对不对",
    "amount_verify": "金额核对（#3365）：写成功 ≠ 钱算对",
    "post_session": "会话关闭后的落库事实（#3357）",
}

# 非效果层（只证明「调用了」或纯散文，**不构成**效果层证据）
NON_EFFECT_FIELDS: tuple[str, ...] = (
    "expectations",       # 工具名 / tool(args) 命中 —— 「调用了」
    "required_args",      # 参数给对了 —— 仍是「调用了」
    "forbidden_args",     # 越权下限（反向断言）
    "order_before",       # 时序
    "forbidden_text",     # 回复文本反模式词（且是**全程**语义，无轮次作用域 —— 见下）
    "want_text",          # 回复文本正向关键词
    "forbidden_card_text",  # 卡片文本反模式
    "form_prefill",       # 卡片预填值
    "data_checks",        # 见下：机器计分型才算证据，纯散文不算
)

assert EFFECT_FIELDS, "EFFECT_FIELDS 不得为空 —— 空集会让效果层断言要求恒不满足（门禁空壳）"

# ── 机器计分型 data_checks（**精确复刻 runner 的计分口径**）──
# 真值锚点：`local_runner.py` 把 data_checks 收进 `scoring_checks` 的判据
# （按 `scoring_checks = list(case.expectations or [])` 文本检索）：
#
#     for dc in (case.data_checks or []):
#         dcs = str(dc).strip().lower()
#         if "success=true" in dcs or "error.code=" in dcs or "未被调用" in dc or "not called" in dcs:
#             scoring_checks.append(str(dc))
#
# ⇒ **纯散文 data_checks 不计分**。这正是 `#3559` / `PR-021` 的形态：
# 「sku_update 成功（价格落库）」**没有 `success=true` 关键词** ⇒ 该条**不计分** ⇒ 假绿。
# 用例作者以为写了「落库」断言，runner 一个数都没核。
MACHINE_DATA_CHECK_MARKERS: tuple[str, ...] = (
    "success=true",
    "error.code=",
    "未被调用",
    "not called",
)


def is_machine_scored_data_check(check: object) -> bool:
    """该 data_checks 条目是否**计入评分**（runner 口径的精确复刻）。

    ⚠️ 与 runner 的一致性由 `test_case_trust_gate.py` 的
    `test_machine_scored_marker_matches_runner_source` 锁定 —— 它直接读
    `local_runner.py` 源码里的同一段判据，任一侧改动而另一侧没跟上即红。
    """
    s = str(check)
    low = s.strip().lower()
    return (
        "success=true" in low
        or "error.code=" in low
        or "未被调用" in s
        or "not called" in low
    )


def machine_scored_data_checks(case: dict) -> list[str]:
    """用例里**计入评分**的 data_checks 条目。"""
    return [str(dc) for dc in (case.get("data_checks") or [])
            if is_machine_scored_data_check(dc)]


# ══════════════════════════════════════════════════════════════════════════════
# 三、可失败性（「不会红的断言 = 空断言」）
# ══════════════════════════════════════════════════════════════════════════════

# ── 三之零、计分通道分流：`[backend-contract]` 用例的判据在 `traces.tests`（#4244）──
#
# 病灶（#4244）：规则 a1（`EMPTY-ASSERTION`）/ a2（`NO-EFFECT-ASSERTION`）的**前提**是
# 「该用例由 runner 计分」—— `total_exp == 0 ⇒ score = 1.0` ⇒ 恒绿。但 `[backend-contract]`
# 类用例**根本不进 agent-eval**（runner 侧按 `skip_reason` 过滤 ⇒ 既不会绿也不会红，而是
# **未运行**），它们的真实计分通道是 `traces.tests`（Java / pytest，由 CI 的
# `ci workflow helper unit tests` 等 job 跑）。对它们提「补计分断言」只有两条路，都是
# 仓库最忌讳的形态：**纸面修复**（把散文 `data_checks` 改写成含 `error.code=` 的形态 ——
# 静态门禁绿、运行期零变化）或凭空编造断言。两者都 = `migao-acceptance` 的「绿了但没跑」。
#
# 故 a1/a2 做**计分通道分流**：豁免必须**同时**满足两个条件（缺一即照旧报，防豁免被当万金油）
#   ① **入口条件**：`skip_reason` 以 `[backend-contract]` 开头（声明「不进 agent-eval」）；
#   ② **结构性条件**：`traces.tests` **非空** 且引用**全部**真实存在。
# ② 的口径**复用**既有先例、不另造第二套：`tests/unit_ci_workflows/test_eval_evidence_chain.py`
# 的 `trace_ghosts()`（路径相对仓库根 `is_file()`）+ `Case Contract` 的「引用必须可解析」。
# ⚠️ 其余规则（自清理 / 前置自断言 / 单端 persona / 定位键 …）对这类用例**一字不放宽**：
# 分流的是「谁给它计分」，不是「它免检」。
BACKEND_CONTRACT_MARKER = "[backend-contract]"


def is_backend_contract_case(case: dict) -> bool:
    """该用例是否声明为 `[backend-contract]`（不进 agent-eval 冒烟、非 LLM 行为）。"""
    return str(case.get("skip_reason") or "").strip().startswith(BACKEND_CONTRACT_MARKER)


def backend_contract_scoring_channel(case: dict, repo_root=None) -> bool:
    """该用例的计分通道是否**在 `traces.tests`**（⇒ a1/a2 不适用，见上节说明）。

    `repo_root is None` ⇒ 存在性**无法校验** ⇒ **按未成立**处理（fail-closed：宁可多报一条
    「补计分断言」，也不静默放行）。传 `repo_root` 是本模块**唯一**的文件系统接触点，
    且必须由调用方显式传入（默认路径仍是纯函数）—— 门禁侧传仓库根。
    """
    if not is_backend_contract_case(case):
        return False
    refs = [str(r) for r in ((case.get("traces") or {}).get("tests") or [])]
    if not refs or repo_root is None:
        return False
    return all((Path(repo_root) / r).is_file() for r in refs)


def scoring_assertion_count(case: dict) -> int:
    """**计分**断言条数 —— 精确复刻 runner 的 `total_exp`。

    = len(expectations) + len(机器计分型 data_checks)。
    为 0 ⇒ 该用例**没有任何断言参与计分**：
      · `score = passed_expectations / total_exp if total_exp > 0 else 1.0` ⇒ **满分 1.0**；
      · 唯一还能判红的只有 case 级检查器（最后轮报错守卫 / 跨轮文本断言 / 写工具护栏）。
    ⇒ 这是「**恒绿**」形态（`migao-acceptance`「空断言（双向）」的恒绿一支）。
    """
    return len(case.get("expectations") or []) + len(machine_scored_data_checks(case))


def has_effect_assertion(case: dict) -> bool:
    """是否含**效果层**断言（落库/产出/success —— 而非「调用了」）。"""
    if any(case.get(f) for f in EFFECT_FIELDS):
        return True
    # 机器计分型 data_checks 若是 `success=true` 形态，本身就是效果层证据
    # （它断言的是工具返回的 success，不是「调用过」）。
    return any("success=true" in s.lower() for s in machine_scored_data_checks(case))


def has_behavior_assertion(case: dict) -> bool:
    """是否含**行为层**断言（工具调用/时序/效果 —— 与「纯散文禁令」相对）。

    规则 c 用：`forbidden_text` **不得单独承载**关键判据。
    为什么：`forbidden_text` 是**全程语义**（扫所有轮的 final_text，无轮次作用域），
    首跑功能正确却可能因**某一轮**的良性措辞命中而判红（#3833 / `PG-013` 实证）。
    ⇒ 用例必须有**另一条**行为/效果层断言，才不至于「禁令一响、整条用例就等于什么都没测」。

    ⚠️ **`required_args` / `forbidden_args` 不算行为层证据**（这是有意的收紧，说明清楚）：
    · `required_args` 的失败路径是**条件式**的 —— runner 里「未调用该工具」就直接
      `continue`（按 `required_args:` 的 `未调用` 文本检索），即**工具从未被调用时它全绿**；
    · 它断言的也只是「调用时某个字段给对了」，不回答「行为发生了 / 成功了」。
    ⇒ `PG-013`（有 `required_args` + 8 条 `forbidden_text`）正是「散文禁令 + 条件式参数断言」
    的组合，**没有**任何断言能证明加工单真的生成了。若把 `required_args` 当行为层证据，
    就会把这条**已知缺陷形态**判成合规（门禁空壳）。故排除。

    `order_before`（时序）算行为层：它要求 A 在 B 之前**真的发生**，与措辞无关。

    ⚠️ **裸工具名期望也不算行为层证据**：`expectations: [order_query]`（无 args）只证明
    「该工具被调用过」（runner 里是纯工具名子串匹配）—— 这正是 `PG-013` 的形态
    （`[order_query, processing_order_generate]` + `forbidden_text` 若干条），
    功能对了却因 R1 良性措辞判红时，整条用例**没有任何断言**在证明「加工单真生成了」。
    带 args 的期望（`sku_update(price=150)` / `{tool:…, args:…}`）算行为层：它断言参数。
    """
    if has_effect_assertion(case):
        return True
    if case.get("order_before"):
        return True
    if machine_scored_data_checks(case):
        return True
    # 带 args 的期望才承载「行为」；裸工具名只是「调用过」
    for exp in case.get("expectations") or []:
        if isinstance(exp, dict):
            if exp.get("args"):
                return True
            continue
        if "(" in str(exp):
            return True
    return False


def uses_forbidden_text(case: dict, raw_text: str | None = None) -> bool:
    """是否使用 `forbidden_text`（**全程**语义）。"""
    return bool(case.get("forbidden_text"))


# `forbidden_text` 的**轮次作用域**标注（能力由并发包在 runner 侧新增，字段名未定）。
# 规则 c 必须**允许**「已轮次作用域 + 有行为断言」的形态（否则把正确用法也堵死）。
# 判定：该用例的原始 YAML 文本里，`forbidden_text` 附近出现轮次作用域标注词。
_ROUND_SCOPE_MARKERS: tuple[str, ...] = (
    "rounds=",          # 形如 forbidden_text_rounds / forbidden_text: [{text:..., rounds:[1]}]
    "round",            # 英文 round 键
    "轮次",              # 「轮次作用域」
    "作用域",
    "仅第",
    "只在第",
)
_FORBIDDEN_TEXT_KEY_RE = re.compile(r"forbidden_text")


def forbidden_text_is_round_scoped(raw_text: str | None) -> bool:
    """该用例的 `forbidden_text` 是否**已声明轮次作用域**（有作用域能力才算）。

    ⚠️ 能力现状：**轮次作用域尚未落地**（并发包在 runner 侧新增）。故本函数返回 False
    时，规则 c 按「全程语义」处理 —— 此时 `forbidden_text` 必须有行为/效果层断言陪跑。
    """
    if not raw_text:
        return False
    if not _FORBIDDEN_TEXT_KEY_RE.search(raw_text):
        return False
    # 取该用例文本里 forbidden_text 起的一段（到下一个顶层字段或文末）
    m = _FORBIDDEN_TEXT_KEY_RE.search(raw_text)
    tail = raw_text[m.start():]
    stop = re.search(r"\n    [a-z_]+:", tail)
    seg = tail[: stop.start()] if stop else tail
    # 作用域标注可能在紧接着的注释块里 —— 一并纳入（字段后 400 字符窗口）
    window = raw_text[m.start(): m.start() + len(seg) + 400]
    low = window.lower()
    return any(mk.lower() in low for mk in _ROUND_SCOPE_MARKERS)


# ── 规则 c 的**显式豁免标记**（逃生口；见 `has_forbidden_text_intent` 的为什么）──
# 为什么需要逃生口：`forbidden_text` 有一类**合法**用法 —— 「禁令本身就是被测行为」，
# 如 AS-009「C 端售后进度查询：回复不得出现『没有权限/无权限』」（#3477 类**能力自我
# 否定**）。此时禁令是**主判据且是机制本身**，要求它再配一条效果层断言是**假红风险**的
# 无谓负担（`migao-acceptance` v1.5：换个判据写法不构成修复；此处正相反 —— **不是**
# 判据写错，而是这类用例的判据**本就该是禁令**）。
# 故：作者若**显式声明**「禁令即主判据」，规则 c 降级为**不阻塞**（记入报告）。
# 声明形态 = 该用例块里的一行注释（不改 schema、不碰 YAML 键，避免与生成物/装载器打架）：
#     # forbidden-text-intent: <≥10 字的理由>
_FORBIDDEN_INTENT_RE = re.compile(
    r"#\s*forbidden-text-intent\s*[:：]\s*(\S.{9,})", re.IGNORECASE)


def has_forbidden_text_intent(raw_text: str | None) -> bool:
    """该用例是否**显式声明**「`forbidden_text` 即主判据」（带 ≥10 字理由）。

    命中 ⇒ 规则 c 不阻塞；**理由仍必须写出来**（写不出理由 = 还没想清楚这条用例在测什么）。
    用途示例：AS-009 那种「禁令就是被测行为」的守护型用例。
    """
    if not raw_text:
        return False
    return bool(_FORBIDDEN_INTENT_RE.search(raw_text))


# ══════════════════════════════════════════════════════════════════════════════
# 四、写用例的识别（工具名 + action 精确判定）
# ══════════════════════════════════════════════════════════════════════════════

_EXP_TOOL_RE = re.compile(r"^\s*([a-z][a-z0-9_]*)\s*(?:\(|\s|$)")


def expectation_tools(case: dict) -> list[tuple[str, dict]]:
    """从 `expectations` 提取 [(工具名, args)]。

    支持两种形态：
      · dict：`{tool: sku_update, args: {action: add_tag}}`
      · 字符串（旧形态 / 生成物）：`customer_manage(action=add_tag) or direct_reply`

    字符串形态下按 ` or ` 拆分支（与 runner 的 `check_expectation` 同语义）。
    """
    out: list[tuple[str, dict]] = []
    for exp in case.get("expectations") or []:
        if isinstance(exp, dict):
            tool = str(exp.get("tool") or "").strip()
            args = exp.get("args") if isinstance(exp.get("args"), dict) else {}
            if tool:
                out.append((tool, args))
            continue
        for part in str(exp).split(" or "):
            part = part.strip()
            if not part:
                continue
            m = _EXP_TOOL_RE.match(part)
            if not m:
                continue
            tool = m.group(1)
            args = {}
            inner = re.search(r"\(([^)]*)\)", part)
            if inner:
                for kv in inner.group(1).split(","):
                    if "=" in kv:
                        k, _, v = kv.partition("=")
                        args[k.strip()] = v.strip()
            out.append((tool, args))
    return out


def is_write_expectation(tool: str, args: dict | None = None) -> bool:
    """该 (工具, args) 期望是否**写**操作。

    · 工具在 `WRITE_TOOLS` ⇒ 写；
    · 工具在 `WRITE_TOOL_ACTIONS` ⇒ 看 `args.action`：
        - action ∈ 写集合 ⇒ 写；
        - action ∈ read_only_actions（即不在写集合）⇒ **读**（`customer_manage(action=query)` 这类）；
        - action 缺失 ⇒ **保守判写**（缺 action 时该工具默认走写路径的可能性更高；
          宁可多要求一条效果层断言，也不放过一个真的写用例）。
    · 其余工具 ⇒ 读。
    """
    tool = str(tool or "").strip()
    args = args or {}
    if tool in WRITE_TOOLS:
        return True
    write_actions = WRITE_TOOL_ACTIONS.get(tool)
    if write_actions is not None:
        action = str(args.get("action") or "").strip()
        if not action:
            return True  # 保守判写（见 docstring）
        return action in write_actions
    return False


def write_expectations(case: dict) -> list[tuple[str, dict]]:
    """用例里所有**写**期望。"""
    return [(t, a) for t, a in expectation_tools(case) if is_write_expectation(t, a)]


def is_write_case(case: dict) -> bool:
    """用例是否**写类用例**（含 ≥1 条写期望）。"""
    return bool(write_expectations(case))


# ══════════════════════════════════════════════════════════════════════════════
# 五、前置等价性（自清理 / 命名空间）
# ══════════════════════════════════════════════════════════════════════════════

# 自清理字段（评测前把上一次跑留下的状态复位，保证重试前置等价）。
SELF_CLEAN_FIELDS: tuple[str, ...] = ("pre_clean", "namespaces")

# ⚠️ **能力现状（照实登记，勿当有硬保证）**：
#   · `pre_clean` —— **已落地**（`local_runner._run_pre_clean`，按该函数名检索）。
#     支持 product_remove / product_dedupe / employee_reactivate /
#     aftersales_ticket_prepare / customer_tag_remove；**未知类型只打印「（跳过）」**，
#     即写错 type 名**不会报错**（静默不清理 = 潜在假绿，见 #3797，登记为未实装项）。
#   · `namespaces` —— **本仓库当前不存在这个 schema 字段**（在 `.github/cases/**` 与
#     `tests/agent_eval/**` 全库 grep 均为 0 命中）。它由**另一并发包**规划用于
#     **并行互斥**；`SELF_CLEAN_FIELDS` 预留它以支持「先落地者不互相误伤」。
#
# **`namespaces` 与 `pre_clean` 不是一回事**（判据必须区分）：
#   `namespaces` 只保证**并行互斥**（两条用例不会同时跑），**不解决重试前置**
#   —— 上一跑留下的数据仍在，重试时前置状态与首跑**不等价**（#3800 的形态）。
#   故：声明 `namespaces` 时**降级为「命名空间（弱证据）」**，不视为前置等价性成立。
NAMESPACE_FIELDS: tuple[str, ...] = ("namespaces",)


def self_clean_evidence(case: dict) -> str:
    """返回该用例的自清理证据等级。

    · `"pre_clean"`  —— 强：评测前真的复位（`_run_pre_clean`）。
    · `"namespaces"` —— **弱**：只保证并行互斥，**不解决重试前置**（见上）。
    · `""`           —— 无。
    """
    if case.get("pre_clean"):
        return "pre_clean"
    if case.get("namespaces"):
        return "namespaces"
    return ""


# ── 「可解析性」规则的**适用域**（issue #3835 实证修正）──────────────────────────
# 命题「`pre_clean` 的点名目标必须在**种子**里可解析」只在**准备型**前置上成立
# （"我需要种子里那个对象在位"）。**清理型**前置的语义**相反**：它要删的常常是
# **用例自己在运行期造出来的对象**，而那个对象**按设计就不在种子里**
# （`local_runner._PRECLEAN_CLEANUP_TYPES` 明确把"目标不存在"判为**良性 no-op**）。
# 两类混进同一个判据 ⇒ **正确形态被永远判红**（`migao-dev-flow` §19.1
# 「基于错误的真相模型写出的护栏 = 永远红」）。
# 实证：把「与种子同名的建品用例」改成**用例自有名**（#3835 的根治修法）后，
# `pre_clean: product_remove{自有名}` 必然"不在种子真值里" ⇒ 正确修法反被门禁判红。
#
# 豁免**只认"用例自己的声明"**（`namespaces` 的 `<kind>:<值>` 的 `<值>`），不靠猜：
# 没声明的目标**照样**判红（`CU-003` 的 `VIP2活跃` 不受影响 —— 它声明的是手机号）。
# 且豁免**只对清理族**生效：准备型（如 `employee_reactivate{employee_name:王五}`）
# 即便声明了该值也**必须**继续核对种子 —— 否则就是把 HR-003 这类正确用例的护栏拆掉。
# 与 runner 的一致性由 `tests/unit_ci_workflows/test_eval_product_name_pollution.py`
# 的 `test_cleanup_type_set_matches_runner_source` 锁定（任一侧改动而另一侧没跟上即红）。
CLEANUP_PRECLEAN_TYPES: frozenset = frozenset({
    "product_remove",       # = local_runner._PRECLEAN_CLEANUP_TYPES
    "customer_tag_remove",
    "employee_remove",
})


def case_declared_resource_values(case: dict) -> set:
    """用例**自己声明**的全局资源值（`namespaces` 形态 `<kind>:<值>` 里的 `<值>`）。

    用途见 `CLEANUP_PRECLEAN_TYPES` 的注释：它是"点名目标不在种子里"的**唯一正当豁免源**。
    """
    out = set()
    for k in (case or {}).get("namespaces") or []:
        s = str(k)
        if ":" in s:
            v = s.split(":", 1)[1].strip()
            if v:
                out.add(v)
    return out


def is_case_owned_cleanup_target(case: dict, ptype: str, value: str) -> bool:
    """该 `pre_clean` 目标是否 = **用例自建对象**（清理族 + 目标就在自己的声明里）。

    两个条件都必需：① 类型属**清理族**（准备型不接受本豁免）；② 目标值是**本用例**
    在 `namespaces` 里声明的资源 ⇒ 那个对象是本用例运行期自己造的，不在种子里是设计。
    """
    return str(ptype) in CLEANUP_PRECLEAN_TYPES and str(value) in case_declared_resource_values(case)


# `_run_pre_clean` 已实现的类型与各自的**点名目标字段**（真值锚点 = local_runner
# 的分支；变更时同步此处）。`None` = 该类型没有「点名目标」（无需种子真值解析）。
KNOWN_PRECLEAN_TARGET_FIELDS: dict[str, str | None] = {
    "customer_tag_remove": "tag_name",         # 精确匹配种子 customer_tags.name
    "product_remove": "product_keyword",       # 子串匹配商品名
    "product_dedupe": "product_keyword",       # 子串匹配商品名
    "employee_reactivate": "employee_name",    # 精确匹配员工名
    "aftersales_ticket_prepare": None,         # 只需存在 pending 工单，不点名
    "processing_order_reset": None,            # 按 order_no 复位订单/加工单（#3833 修复新增）
}
# 声明了 `pre_clean` 但类型不在上表 ⇒ 静态**无法**判定其点名目标 ⇒ 不登记（**不是**缺陷的
# 借口：真值锚点 = `runner._PRECLEAN_TYPES`，两边**必须同步**）。
# ⚠️ **已发现的漂移**：`employee_remove`（runner 已实装、目标字段 `employee_name`）与
# `user_memories_clear` 不在上表 ⇒ HR-002 / HR-009 / HR-010 的 pre_clean 目标**未被**
# `CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE` 核对（= 一条没登记的豁免面）。
# 本模块的文件所有权不含该表（本次只同步 `UNIMPLEMENTED`）⇒ 不在本次改，登记见 #4161。
# 历史备注：这里曾指向 `UNIMPLEMENTED` 的 `CASE-TRUST-PRECLEAN-UNKNOWN-TYPE`，
# 该登记**已撤**（runner 侧早已 fail-closed，见 `UNIMPLEMENTED` 上方的「已撤登记」）。


def pre_clean_targets(case_or_spec: dict) -> list[tuple[str, str, str]]:
    """从 `pre_clean` 提取「需在种子真值里可解析的目标」=[(类型, 字段, 值)]。

    真值锚点 = `local_runner._run_pre_clean` 的分支（按该函数名检索），
    类型↔字段的映射见 `KNOWN_PRECLEAN_TARGET_FIELDS`：
      · `customer_tag_remove`       → `tag_name`（精确匹配种子 `customer_tags.name`）
      · `product_remove`            → `product_keyword`（子串匹配商品名）
      · `product_dedupe`            → `product_keyword`（子串匹配商品名）
      · `employee_reactivate`       → `employee_name`（精确匹配员工名）
      · `aftersales_ticket_prepare` → **无点名目标**（只需存在 pending 工单，不登记）
      · `processing_order_reset`    → **无点名目标**（按订单号复位，不依赖种子名字）
      · 未知类型                     → 不登记（真值 = `runner._PRECLEAN_TYPES`；表未同步的
                                       `employee_remove` 漂移见上方 ⚠️ 与 #4161）
    """
    specs = case_or_spec.get("pre_clean") if isinstance(case_or_spec, dict) else None
    out: list[tuple[str, str, str]] = []
    for spec in specs or []:
        if not isinstance(spec, dict):
            continue
        t = str(spec.get("type") or "")
        field = KNOWN_PRECLEAN_TARGET_FIELDS.get(t, "UNKNOWN")
        if field is None:
            continue  # 该类型无点名目标（aftersales_ticket_prepare / processing_order_reset）
        if field == "UNKNOWN":
            continue  # 未知类型：不登记（真值 = runner._PRECLEAN_TYPES，同步漂移见 #4161）
        v = str(spec.get(field) or "")
        if v:
            out.append((t, field, v))
    return out


# ── 种子真值解析（从 tests/agent_eval/fixtures/*.sql 提取）────────────────────
# **为什么从 SQL 提取而不是硬编码标签名**：硬编码的清单会与种子漂移，而
# `CU-003`（#3832）的形态正是「种子改了名、用例没跟上」—— 唯一能结构性地发现它的
# 办法就是**每次从种子现算真值集**。

_INSERT_HEAD_RE = re.compile(r"INSERT\s+INTO\s+([a-z_][a-z0-9_]*)\s*\(", re.IGNORECASE)
_NAME_COLUMNS = frozenset({
    "name", "color_name", "tag_name", "product_name", "employee_name", "title",
    "nickname",
})
_STR_LIT_RE = re.compile(r"'((?:[^']|'')*)'")


def _scan_paren_group(text: str, i: int) -> tuple[str, int]:
    """从 `text[i] == '('` 起，返回 (组内文本, 右括号后一位)。

    **必须按括号配平扫描**，不能用 `\\(([^)]*)\\)`：真实列名列表里有
    `stock_warning_threshold` 这类长名 + 跨行，用非配平正则会**提前截断**列名列表
    ⇒ 列位错位 ⇒ 「name 列」指到 color 列 ⇒ 真值集合变成颜色十六进制 ⇒ 门禁静默失效。
    （实证：本模块初版即踩此坑，`customer_tags` 只解析出 `#faad14`。）
    """
    assert text[i] == "(", f"_scan_paren_group 需从 '(' 开始，实际 {text[i]!r}"
    depth = 0
    j = i
    n = len(text)
    while j < n:
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return text[i + 1: j], j + 1
        j += 1
    raise ValueError("括号不配平（种子 SQL 损坏或被截断）")


def _split_values_tuples(body: str) -> list[list[tuple[int, str]]]:
    """从 VALUES 体里切出每个元组的 `[(列序号, 字符串值)]`。

    ⚠️ **列序号必须在扫描时算出来**：本函数只收字符串字面量（数字/布尔/`NULL` 不入表），
    所以「第 k 个字符串」**不等于**「第 k 列」。实证：`customer_tags` 的值
    `('tag_eval_vip2', 1, 'VIP2', '#faad14', 'manual', …)` 的字符串序列是
    `['tag_eval_vip2','VIP2','#faad14','manual',…]` —— 若按字符串位序取 `name`
    （列序号 2）就会拿到 `#faad14`，真值集合变成颜色十六进制 ⇒ 判据静默失效
    （本模块初版即踩此坑）。故每个 `(...)` 里按**逗号分隔的字段位**计列序号，
    只把该位是字符串的记下来。

    只收**顶层** `(...)`（`depth == 1`）里的字符串 —— 嵌套函数/`ROW()` 里的字面量不算一列。
    """
    tuples: list[list[tuple[int, str]]] = []
    depth = 0
    col_idx = 0
    cur: list[tuple[int, str]] = []
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch == "'":
            j = i + 1
            buf = []
            while j < n:
                if body[j] == "'":
                    if j + 1 < n and body[j + 1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    break
                buf.append(body[j])
                j += 1
            if depth == 1:
                cur.append((col_idx, "".join(buf)))
            i = j + 1
            continue
        if ch == "(":
            depth += 1
            if depth == 1:
                cur = []
                col_idx = 0
        elif ch == ")":
            if depth == 1:
                tuples.append(cur)
                cur = []
            depth -= 1
        elif ch == "," and depth == 1:
            col_idx += 1
        i += 1
    return tuples


def extract_seed_catalog(sql_text: str) -> dict[str, set[str]]:
    """从种子 SQL 提取 {表名: {列名类真值}}。

    口径（刻意**保守**，宁可少收也不误收）：
      · 只收 `INSERT INTO <表>(<列...>)` 里**列名**属 `_NAME_COLUMNS` 的位置上的字符串；
      · 列名列表按**括号配平**扫描（见 `_scan_paren_group` 的实证注释）；
      · 取值按**逗号分隔的字段位**对齐列名（见 `_split_values_tuples` 的实证注释）；
      · 两种写法都覆盖：纯 `VALUES (...)` 与 `SELECT ... FROM (VALUES ...) AS v(...)`；
      · 名列出现多次（如 `product_skus.color_name`）时其值也收 —— 属同族真值，
        多收无害（判据只查「能否解析到」，不查来源表）。

    **为什么不收所有字符串**：描述文本里出现 `张三` 会让「标签/商品名解析」误判为可解析，
    门禁直接变成恒真（空壳）。见本模块 header 的「不许放宽成空壳」红线。
    """
    catalog: dict[str, set[str]] = {}
    for m in _INSERT_HEAD_RE.finditer(sql_text):
        table = m.group(1).lower()
        try:
            cols_text, after = _scan_paren_group(sql_text, m.end() - 1)
        except ValueError:
            continue
        # 语句体：到下一个分号（分号不会出现在本仓库种子的字符串字面量里；此处保守）
        semi = sql_text.find(";", after)
        body = sql_text[after: semi if semi != -1 else len(sql_text)]
        cols = [c.strip().split(".")[-1].strip().lower() for c in cols_text.split(",")]
        name_idx = {i for i, c in enumerate(cols) if c in _NAME_COLUMNS}
        if not name_idx:
            continue
        for tup in _split_values_tuples(body):
            for idx, value in tup:
                if idx in name_idx and value.strip():
                    catalog.setdefault(table, set()).add(value)
    return catalog


def resolve_pre_clean_target(spec_type: str, field: str, value: str,
                             catalog: dict[str, set[str]]) -> bool:
    """`pre_clean` 的点名目标能否在种子真值里解析到。

    匹配语义与 runner 对齐：
      · `tag_name` / `employee_name` → **精确匹配**（runner 按 name 精确查）
      · `product_keyword`            → **子串匹配**（runner 用 `kw in p.name`）
    """
    value = str(value or "")
    if field == "tag_name":
        return value in catalog.get("customer_tags", set())
    if field == "employee_name":
        return value in catalog.get("sys_users", set()) or value in catalog.get("users", set())
    if field == "product_keyword":
        return any(value in name for name in catalog.get("products", set()))
    return True  # 未知字段：不判（登记为未实装，不写成恒真阻塞）


# ══════════════════════════════════════════════════════════════════════════════
# 五之二、不可变对象引用（治「按可变键定位被测对象」）
# ══════════════════════════════════════════════════════════════════════════════
#
# **为什么单列**（主会话新发现）：反复修反复测的**主机制**不是断言写法本身，而是
# 「**读的是快照 / 按可变键定位被测对象**」。写用例自清理解决的是「**世界**被谁改了」，
# 本规则解决的是「**我改的是哪个对象**」—— 两者互补，缺任一条都不够。
#
# **判据范围的口径（必须写清，否则大面积误伤）**：
#   名字 / 序号出现在 `user_inputs` 里是**合理的**（那是被测行为的一部分 —— 用户就是会说
#   「第一个」「遮光窗帘」）。**只允许**在「**定位被测对象**」的位置上判违规，即：
#   `pre_clean[].*`、`db_verify[].*`、`output_verify[].*`、`expectations[].args.*`。
#   ⇒ 扫 `user_inputs` 的判据是**错的**，本模块不这么做。
#
# 严重度分层（`migao-acceptance`：fail-closed 只用在**能确定判错**的判据上）：
#   · **位置/序号选择器**（`_index` / `_position` 之类）⇒ **阻塞**：它按**列表位置**定位，
#     而列表顺序是运行时排序（如客户列表 `created_at DESC`）⇒ 别人中途造一条同名记录，
#     定位就漂到**别的对象**上。不可能有正当用法。
#   · **名字子串 / 自然键**（`*_keyword` / `*_name` / `tag_name` …）⇒ **警告**：
#     多数是**种子里的名字**（可解析、当前唯一），属「有风险但当下正确」；
#     降级为警告并按清单跟踪，避免把 20 条存量用例一次全判红（那会挡住所有人的 PR）。
INDEX_SELECTOR_RE = re.compile(r"(^|_)(index|position|idx|ordinal)($|_)", re.IGNORECASE)
NAME_KEY_SELECTOR_RE = re.compile(r"(keyword|_name$|^name$|_no$)", re.IGNORECASE)

# 允许/豁免：`type` 是**选择器类型本身**，不是定位键
LOCATOR_EXEMPT_KEYS: frozenset[str] = frozenset({"type", "fetch", "source", "expect",
                                                 "expect_present", "fields", "checks"})

# 「定位被测对象」的位置（用例 dict 形态）
def locator_positions(case: dict) -> list[tuple[str, str]]:
    """返回 [(位置, 键名)] —— 只覆盖**定位被测对象**的位置（不含 `user_inputs`）。"""
    out: list[tuple[str, str]] = []
    for i, spec in enumerate(case.get("pre_clean") or []):
        if isinstance(spec, dict):
            out += [(f"pre_clean[{i}]", k) for k in spec]
    for field in ("db_verify", "output_verify"):
        for i, spec in enumerate(case.get(field) or []):
            if isinstance(spec, dict):
                out += [(f"{field}[{i}]", k) for k in spec]
    for i, exp in enumerate(case.get("expectations") or []):
        if isinstance(exp, dict):
            for k in (exp.get("args") or {}):
                out.append((f"expectations[{i}].args", k))
    return out


def index_selector_positions(case: dict) -> list[tuple[str, str]]:
    """用例里用**列表位置/序号**定位被测对象的位置 ⇒ 阻塞项。"""
    bad = []
    for where, key in locator_positions(case):
        if key in LOCATOR_EXEMPT_KEYS:
            continue
        if INDEX_SELECTOR_RE.search(key):
            bad.append((where, key))
    return bad


def name_key_positions(case: dict) -> list[tuple[str, str]]:
    """用例里用**名字子串 / 自然键**定位被测对象的位置 ⇒ 警告项（当下正确、有风险）。"""
    out = []
    for where, key in locator_positions(case):
        if key in LOCATOR_EXEMPT_KEYS:
            continue
        if INDEX_SELECTOR_RE.search(key):
            continue  # 已由阻塞项覆盖
        if NAME_KEY_SELECTOR_RE.search(key):
            out.append((where, key))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 五之三、前置自断言（治「前置悄悄不成立」）
# ══════════════════════════════════════════════════════════════════════════════
#
# **问题**：用例的前置（「库里恰有一个已确认且含加工项的订单」）若不成立，红的表现是
# `unmatched expectation` —— 看起来像「**agent 不干活**」，于是归因全错、反复修反复测。
# 实证：`PG-013` 首跑生成加工单后订单转 `producing`，重试时前置已不成立，但红的表现是
# `unmatched expectation`；`CU-003` 的「客户数 = 2」同理。
#
# **红线**：**不得**为了让用例变绿而删这类断言 —— 它只会让「前置坏了」更早、更准地暴露。
#
# 静态侧的口径（必须是**可判定**的，否则写成恒真就是空壳）：
#   · 写/多轮用例（≥2 轮 user_inputs 或含写期望）必须在**首轮**有前置断言；
#   · 可判定的声明形态（任一）：
#       ① `precondition` / `preconditions` 字段（**声明层**，推荐）—— 值为非空字符串/映射；
#       ② `data_checks` 里含前置关键词（`前置` / `precondition` / `precondition_not_applied`），
#          **且**该条是**机器计分型**（含 `success=true`/`error.code=`/… 之一）——
#          纯散文的「前置：…」不计分 ⇒ 前置不成立时**不会红**，等于没断言（#3559 同族）；
#       ③ `must_succeed` / `db_verify` 至少一条 —— 它们是**效果层**，前置不成立必然失败，
#          即天然把前置失败暴露出来（弱形式，仅当用例只有一轮时接受）。
PRECONDITION_KEYWORDS: tuple[str, ...] = (
    "前置", "precondition", "precondition_not_applied", "前提",
)
# runner 侧已有的 fail-closed 路径名（真值锚点：`local_runner` 的
# `_PRECONDITION_NOT_APPLIED` / `PRECONDITION_NOT_APPLIED`，按该文本检索）
PRECONDITION_FAILCLOSED_ANCHOR = "PRECONDITION_NOT_APPLIED"


def declares_precondition(case: dict) -> tuple[bool, str]:
    """该用例是否**声明了可判定的前置断言**。返回 (是否声明, 证据说明)。

    **严格口径（只有两种算数）**：
      ① `precondition` / `preconditions` 声明层字段（推荐，语义最直白）；
      ② `data_checks` 里含前置关键词**且是机器计分型**（前置不成立时会红）。

    ⚠️ **「有 `must_succeed` / `db_verify`」不满足本规则**（本模块初版曾把它当弱形式接受，
    实测把「已声明」从 1 条虚增到 37 条 —— 那 36 条只是「工具没成功」，**根本没说前置是
    什么**，前置悄悄不成立时它同样不会红）。虚增 = 判据失去判别力（空壳），故移除。
    效果层断言仍是有价值的（由规则 b 管），但**不能替前置自断言**。
    """
    for key in ("precondition", "preconditions"):
        v = case.get(key)
        if v:
            return True, f"声明层字段 `{key}`"
    for dc in (case.get("data_checks") or []):
        s = str(dc)
        low = s.lower()
        if any(k in s or k in low for k in PRECONDITION_KEYWORDS):
            if is_machine_scored_data_check(dc):
                return True, "机器计分型 data_checks 里的前置断言"
    return False, ""


def has_weak_precondition_signal(case: dict) -> bool:
    """仅有**弱前置信号**（效果层断言 / 纯散文前置）：不算声明，但可供分诊参考。"""
    ok, _ = declares_precondition(case)
    if ok:
        return False
    if case.get("must_succeed") or case.get("db_verify"):
        return True
    for dc in (case.get("data_checks") or []):
        s = str(dc)
        if any(k in s or k in s.lower() for k in PRECONDITION_KEYWORDS):
            return True
    return False


def needs_precondition_assertion(case: dict) -> bool:
    """该用例是否**必须有**前置自断言。

    口径：**多轮**（≥2 轮 user_inputs）**或**含写期望 —— 这两种形态才会「跑一次就改变
    自己的前置」（写用例污染、多轮用例消耗存量）。单轮只读用例不强制（读不改变世界）。
    """
    n_rounds = len(case.get("user_inputs") or [])
    return n_rounds >= 2 or is_write_case(case)


# ── 前置的**运行期漂移**容差（`max_growth`，issue #4200）───────────────────────
# 真值锚点 = `local_runner` 的 `_PRECONDITION_NO_DRIFT`（按该文本检索）与它的漂移判据
# `after - before > max_growth`：缺省 0 = 「运行期间**不得**新增」。本模块只对齐这一个
# 缺省值（不复制 runner 的整段判定），供静态判据回答「缺 max_growth 时运行期会容忍多少」。
PRECONDITION_NO_DRIFT = 0

#: 与「自建商品名」配对的前置类型（真值 = `local_runner._PRECONDITION_TYPES` 的
#: `product_count_for_keyword`）。一致性由 `tests/unit_ci_workflows/test_case_trust_gate.py`
#: 的 `test_self_target_type_matches_runner_source` 直接读 runner 源码锁定（防双源漂移）。
SELF_TARGET_PRECONDITION_TYPE = "product_count_for_keyword"


def case_declared_product_names(case: dict) -> set:
    """`namespaces` 里声明的 `product_name:<值>` = 本用例**自建**的商品名。

    与 `case_declared_resource_values` 同一份 `<kind>:<值>` 约定，只按 **kind** 收窄到商品：
    判「自建目标」必须知道是**哪一类**资源，只看值会把 `customer_phone:<值>` 也算进来。
    """
    out = set()
    for k in (case or {}).get("namespaces") or []:
        kind, _, value = str(k).partition(":")
        if kind == "product_name" and value.strip():
            out.add(value.strip())
    return out


def self_target_missing_max_growth(case: dict) -> list[str]:
    """自建商品名 + `expect: 0` 的前置**却没给** `max_growth` ⇒ 返回这些关键词（#4200）。

    判据（**只用现成声明**，不新造字段）：
      `namespaces` 声明了 `product_name:<KW>`（= 本用例自己会创建这个名字的商品）
      ∧ 存在 `precondition[type=product_count_for_keyword, source=<KW>, expect=0]`
      ∧ `max_growth` 缺失或 < 1。

    为什么这是**结构性恒红**（不是偶发红）：runner 的漂移判据 `after - before > max_growth`
    缺省 0，而用例**自己就要创建同名商品** ⇒ 正常行为下 `0 → 1 > 0` **恒判漂移**、`score`
    归零 —— 哪怕逐条计分断言全 passed（实证判定跑 `35295494688`：`PR-008` / `PR-016`
    `score=0.0` 而逐条计分断言全 ✅；同族潜伏例 `CH-005`）。先例 = `HR-002` 的
    `max_growth: 1`，以及用例库既有的「自建目标的用例必须给 max_growth」口径。

    判别力不丢：`max_growth: 1` 只容忍**自建的那一个**，并行用例再造同名（`0 → 2`）仍判漂移
    （运行期红证见 `test_eval_debug_permissions_precondition.py` 的 `max_growth: 1` 用例）。
    """
    names = case_declared_product_names(case)
    if not names:
        return []
    out: list[str] = []
    for spec in case.get("precondition") or []:
        if not isinstance(spec, dict):
            continue
        if str(spec.get("type") or "") != SELF_TARGET_PRECONDITION_TYPE:
            continue
        kw = str(spec.get("source") or "")
        if kw not in names:
            continue
        # `expect` 缺失 ⇒ 不判（本规则的形态是「声明了必须不存在、却又不容忍自建的那一个」；
        # 口径与 runner 的 `int(expect)` 强制转换同源，`"0"` 也算 0）。
        try:
            expect_i = int(spec.get("expect"))
        except (TypeError, ValueError):
            continue
        if expect_i != 0:
            continue
        try:
            growth = int(spec.get("max_growth", PRECONDITION_NO_DRIFT))
        except (TypeError, ValueError):
            growth = PRECONDITION_NO_DRIFT
        if growth < 1:
            out.append(kw)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 五之四、引用新鲜度（`path:NNN` 行号引用）
# ══════════════════════════════════════════════════════════════════════════════
#
# 仓库已有「**不写裸行号**」的纪律（`migao-dev-flow` §16.7 引用纪律：活跃编辑文件的裸行号
# 会在几分钟内失效），但**没有机器检查** —— `#3787` 记着 5 处过期指引。
# 本规则把纪律变成可判定：`path:NNN` 里的行号必须对 `origin/main` 的该文件**存在**；
# 若旁边还写了符号（反引号包裹），则符号应能在该行附近找到（近旁）或**至少在该文件里存在**。
#
# 严重度分层：
#   · 文件不存在 / 行号越界 ⇒ **阻塞**（可确定是错的：该行**不存在**）；
#   · 行号存在但符号既不在该行附近、也**不在该文件里** ⇒ **阻塞**（引用指向不存在的东西）；
#   · 行号存在但符号在文件别处（行号漂移）⇒ **警告**（可行动：「换成符号锚点」）。
PATH_LINE_REF_RE = re.compile(
    r"(?<![-\w./])((?:[\w.-]+/)*[\w.-]+\.(?:py|yml|yaml|sh|md|java|ts|tsx|js|json|sql|sql))"
    r":(\d+)")
BACKTICK_SYMBOL_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]{3,})`")


def find_path_line_refs(text: str) -> list[dict]:
    """扫文本里的 `path:NNN` 引用 → [{"path", "line", "pos", "symbols"}]。

    `symbols` = 该引用**紧随其后**（同一行或下 120 字符内）出现的反引号符号，
    用于「行号漂移」判定（符号在文件别处 = 行号过期）。
    """
    out = []
    for m in PATH_LINE_REF_RE.finditer(text or ""):
        tail = (text or "")[m.end(): m.end() + 160]
        symbols = [s for s in BACKTICK_SYMBOL_RE.findall(tail)
                   if "." not in s.split("(")[0][:1]]
        out.append({
            "path": m.group(1),
            "line": int(m.group(2)),
            "pos": m.start(),
            "symbols": symbols[:3],
            "raw": m.group(0),
        })
    return out


def check_reference_freshness(refs: list[dict], read_lines) -> dict:
    """校验引用新鲜度。

    `read_lines(path)` → 该文件在 `origin/main` 上的**全部行**（list[str]）；
    文件不存在返回 None（由调用方注入，保持本模块纯函数）。
    返回 `{"blocking": [...], "warnings": [...]}`。
    """
    blocking, warnings = [], []
    for r in refs:
        lines = read_lines(r["path"])
        if lines is None:
            blocking.append({**r, "reason": f"`{r['path']}` 在 origin/main 上不存在"})
            continue
        n = len(lines)
        if r["line"] < 1 or r["line"] > n:
            blocking.append({**r, "reason": (
                f"行号越界：`{r['path']}` 在 origin/main 上只有 {n} 行，引用第 {r['line']} 行"
            )})
            continue
        if not r["symbols"]:
            continue
        window = "\n".join(lines[max(0, r["line"] - 4): r["line"] + 3])
        if any(s in window for s in r["symbols"]):
            continue
        whole = "\n".join(lines)
        if not any(s in whole for s in r["symbols"]):
            blocking.append({**r, "reason": (
                f"引用指向的符号 {r['symbols']} 在 `{r['path']}` 里**完全找不到**"
            )})
            continue
        warnings.append({**r, "reason": (
            f"行号漂移：符号 {r['symbols']} 不在第 {r['line']} 行附近（该文件里能找到）"
            f" —— 建议改用符号/文本锚点（dev-flow §16.7 引用纪律）"
        )})
    return {"blocking": blocking, "warnings": warnings}


# ══════════════════════════════════════════════════════════════════════════════
# 六、persona 规则（单端用例的标注与跨腿窄跑）
# ══════════════════════════════════════════════════════════════════════════════

# C 端（小布）工具集真值 —— **单一源** = `tests/agent_eval/eval_case_filter.XIAOBU_TOOLS`
# （该模块零第三方依赖，自身的一致性由 `test_xiaobu_case_set.py::TestXiaobuToolsetTruth`
#  与后端 `CUSTOMER_*_TOOLS` 锁定）。本模块只做转发，**不复制**一份平行清单
# （复制 = 双源漂移，正是本模块 header 反对的）。
try:  # pragma: no cover - 导入失败时降级为「未实装」，不静默恒真
    import os as _os
    import sys as _sys

    _EVAL_DIR = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
        "tests", "agent_eval")
    if _EVAL_DIR not in _sys.path:
        _sys.path.insert(0, _EVAL_DIR)
    from eval_case_filter import XIAOBU_TOOLS as _XIAOBU_TOOLS  # noqa: E402
    XIAOBU_TOOLSET_SOURCE = "eval_case_filter.XIAOBU_TOOLS"
except Exception:  # pragma: no cover
    _XIAOBU_TOOLS = None
    XIAOBU_TOOLSET_SOURCE = ""

PERSONA_VALUES: tuple[str, ...] = ("mibao", "xiaobu", "both")

# 禁止静默少跑守卫的**文本锚点**（行号会漂移，引用一律按文本检索）：
# `tests/agent_eval/local_runner.py` 的「禁止静默少跑」守卫 —— 单端用例若被当
# `case_ids` 窄跑，另一条腿会 `sys.exit(1)`；**配对不豁免**（#3822，run 34907040543：
# `OR-013` 只在 mibao 腿 ⇒ xiaobu 腿红）。静态门禁只能要求**标注存在**，
# 真正的跨腿判定属 T2（runner 归因），见 unimplemented 清单。
SILENT_SKIP_GUARD_ANCHOR = "禁止静默少跑"


def case_persona(case: dict) -> str:
    """读用例 persona（`""` = 缺省双端）。"""
    return str(case.get("persona") or "").strip().lower()


def is_single_leg_by_toolset(case: dict) -> bool:
    """**纯静态**判定：该用例是否只能跑单端（期望工具全是小布工具集）。

    ⚠️ 这是**下界**（保守判定）：
      · expectations 非空 且 工具集 ⊆ XIAOBU_TOOLS ⇒ 只可能是小布用例
        （米宝工具集与之不相交）；
      · expectations 为空 ⇒ **无法静态判定**（返回 False，登记为未实装）；
      · 工具集不 ⊆ XIAOBU_TOOLS ⇒ 双端或米宝端，无法静态判定（返回 False）。
    """
    if _XIAOBU_TOOLS is None:
        return False
    tools = {t for t, _ in expectation_tools(case) if t}
    tools = {t for t in tools if t != "direct_reply"}
    if not tools:
        return False
    return tools <= _XIAOBU_TOOLS


def missing_persona_annotation(case: dict) -> bool:
    """单端（按工具集可判定的）用例是否**缺** persona 标注。

    规则 d 的静态部分：要求**标注存在**。跨腿窄跑的禁止（#3822）属 T2，见未实装清单。
    """
    if not is_single_leg_by_toolset(case):
        return False
    return case_persona(case) not in ("mibao", "xiaobu")


# ══════════════════════════════════════════════════════════════════════════════
# 七、规则表（**门禁与分类器共用的唯一规则源**）
# ══════════════════════════════════════════════════════════════════════════════

# 每条规则含：code / title / why（形态名 + issue）/ counterexample（现存用例）/
# implemented（False = **未实装**，绝不写成恒真判断）/ fix（给人和 agent 的修复指引）。
RULES: tuple[dict, ...] = (
    {
        "code": "CASE-TRUST-EMPTY-ASSERTION",
        "title": "计分断言不得为空（可失败性）",
        "why": (
            "空断言（恒绿）：`total_exp == 0` ⇒ `score = 1.0`，用例永远绿。"
            "见 `migao-acceptance`「假绿 / 假红：断言自身会双向骗人」的空断言（恒绿）支；"
            "实证 #3559 / PR-021。"
            "⚠️ 适用范围（#4244）：本规则的前提是**该用例由 runner 计分** —— `[backend-contract]` "
            "用例不进 agent-eval（runner 侧按 `skip_reason` 过滤 ⇒ 未运行，既不会绿也不会红），"
            "其计分通道是 `traces.tests`（非空且引用真实存在）⇒ 由 "
            "`backend_contract_scoring_channel` 分流豁免；对它们提「补计分断言」只会逼出"
            "纸面修复（改散文形态、运行期零变化）。"
        ),
        "counterexample": "PR-021（只有纯散文 data_checks，无 expectations、无 success=true）",
        "implemented": True,
        "fix": (
            "补 ≥1 条**计分**断言：`expectations`（工具名/args），"
            "或在 data_checks 里写机器可判定形态（必须含 `success=true` / `error.code=` / "
            "`未被调用` / `not called` —— 纯散文不计分）。"
        ),
    },
    {
        "code": "CASE-TRUST-NO-EFFECT-ASSERTION",
        "title": "写类用例必须 ≥1 条效果层断言",
        "why": (
            "「调用了 ≠ 成了」（#3778）：`expectations`/`required_args` 只证明调用发生、"
            "参数给对，工具返回 `success=false` 也照样通过。"
            "⚠️ 适用范围（#4244）：与 a1 同一条分流 —— `[backend-contract]` 用例不进 "
            "agent-eval，其效果层证据在 `traces.tests`（真实存在的后端契约测试）里，"
            "不适用本规则。"
        ),
        "counterexample": "PR-021（`sku_update` 只有工具名期望 + 散文 data_checks）",
        "implemented": True,
        "fix": (
            "加 `must_succeed: [{tool: <写工具>}]`（断言至少一次 success=true），"
            "或 `db_verify`（查落库值）、`output_verify`（核产出 payload）、"
            "`amount_verify`（核金额）、`post_session`（核会话关闭后落库）。"
            "**不要**只写散文 data_checks 充当落库断言（那条不计分）。"
        ),
    },
    {
        "code": "CASE-TRUST-NO-SELF-CLEAN",
        "title": "写类用例必须声明自清理（前置等价性）",
        "why": (
            "写用例不自清理 ⇒ 第二次跑的前置状态与首跑**不等价**（幂等拒绝/重名澄清/"
            "存量消耗）。实证 #3800（PG-013 重试前置不等价）、#3797（准备型 pre_clean "
            "未复位路径未纳入折叠）。"
        ),
        "counterexample": ("PG-013（#3800 实证：重试前置不等价 —— 首跑已生成加工单、重试前置已变；"
                           "#3833 后已补 `pre_clean[processing_order_reset]`，工具亦按 #3917 下线 ⇒ "
                           "本条为**历史实例**，判据不变）"),
        "implemented": True,
        "fix": (
            "声明 `pre_clean`（`customer_tag_remove` / `product_remove` / `product_dedupe` / "
            "`employee_reactivate` / `aftersales_ticket_prepare`）把目标状态复位；"
            "或声明 `namespaces`（**弱证据**：只保证并行互斥，不解决重试前置）。"
        ),
    },
    {
        "code": "CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE",
        "title": "`pre_clean` 的点名目标必须在种子真值里可解析",
        "why": (
            "点名一个种子里不存在的对象 ⇒ 用例**物理不可满足**（agent 无论如何都做不到），"
            "且 pre_clean 静默「无 X 需清理」⇒ 前置状态从未复位。实证 #3832 / #3794："
            "`CU-003` 让 agent 挂 `VIP2活跃`，而种子只有 `VIP2` / `活跃`。"
        ),
        "counterexample": "CU-003（`pre_clean[].tag_name: \"VIP2活跃\"` ∉ 种子 customer_tags）",
        "implemented": True,
        "fix": (
            "改成本用例 persona 对应种子文件里**真实存在**的名字"
            "（`tests/agent_eval/fixtures/mibao_eval_seed.sql` / `xiaobu_eval_seed.sql`），"
            "或在种子里补上该对象（补数据层，而不是让用例悬空）。"
        ),
    },
    {
        "code": "CASE-TRUST-FORBIDDEN-TEXT-SOLE",
        "title": "`forbidden_text` 不得单独承载关键判据",
        "why": (
            "`forbidden_text` 是**全程**语义（扫所有轮的 final_text，**无轮次作用域**）⇒ "
            "首跑功能正确却可能因**某一轮**的良性措辞而判红（假红）。实证 #3833 / PG-013："
            "R1 良性措辞命中禁令 → 整条用例红，而业务流程实际走通了。"
        ),
        "counterexample": "PG-013（8 条 forbidden_text + 无 must_succeed/expectations 层面的行为断言）",
        "implemented": True,
        "fix": (
            "该用例**同时**要有 ≥1 条行为/效果层断言（`expectations` / `must_succeed` / "
            "`db_verify` / `output_verify` / 机器计分型 data_checks）；"
            "或把禁令改成**轮次作用域**形态（轮次作用域能力落地后本规则自动放行）。"
        ),
    },
    {
        "code": "CASE-TRUST-VOLATILE-LOCATOR",
        "title": "定位被测对象必须用不可变标识（不得用列表位置/序号）",
        "why": (
            "写用例自清理治「**世界**被谁改了」，本规则治「**我改的是哪个对象**」——"
            "反复修反复测的**主机制**是「读的是快照 / 按可变键定位被测对象」。"
            "位置选择器按**列表位置**定位，而列表顺序是运行时排序（如客户列表 "
            "`created_at DESC`）⇒ 别人中途造一条同名记录，定位就漂到**别的对象**上。"
            "取证：`CU-003` 的 `customer_index: 0` + `created_at DESC`。"
        ),
        "counterexample": "CU-003（`pre_clean[].customer_index: 0`，按位置定位客户）",
        "implemented": True,
        "fix": (
            "把定位键换成**不可变标识**：手机号 / `order_no` / `id` / 用例自建对象的唯一名。"
            "例：`pre_clean: [{type: customer_tag_remove, customer_keyword: \"13800138000\"}]`"
            "（手机号唯一且不可变）而不是 `customer_index: 0`。"
            "⚠️ 注意：名字/序号出现在 `user_inputs` 里是**合理的**（那是被测行为的一部分），"
            "本规则只看**定位被测对象**的位置（`pre_clean` / `db_verify` / `output_verify` / "
            "`expectations[].args`）。"
        ),
    },
    {
        "code": "CASE-TRUST-NO-PRECONDITION-ASSERTION",
        "title": "多轮/写类用例必须对**自己的前置**给出可判定断言",
        "why": (
            "前置悄悄不成立时，红的表现是 `unmatched expectation` —— 看起来像"
            "「**agent 不干活**」，于是归因全错、反复修反复测。实证：`PG-013` 首跑生成"
            "加工单后订单转 `producing`，重试时前置已不成立；`CU-003` 的「客户数 = 2」同理。"
        ),
        "counterexample": "PG-013（首跑后订单转 producing，重试前置不成立 ⇒ 表现像 agent 不干活）",
        "implemented": True,
        "fix": (
            "声明 `precondition` / `preconditions`（声明层，推荐）；或把前置写成"
            "**机器计分型** `data_checks`（必须含 `success=true` / `error.code=` 之一 —— "
            "纯散文的「前置：…」不计分 ⇒ 前置不成立时不会红，等于没断言）；"
            "⚠️ 只加 `must_succeed` / `db_verify` **不满足本规则** —— 它们只说明「工具没成功」，"
            "**没说前置是什么**（实测这种弱形式会把「已声明」从 1 条虚增到 37 条）。"
            f"前置不成立时应走 runner 已有的失败关闭路径"
            f"（`{PRECONDITION_FAILCLOSED_ANCHOR}`）。"
            "**红线：不得为了让用例变绿而删这类断言。**"
        ),
    },
    {
        "code": "CASE-TRUST-SELF-TARGET-NO-MAX-GROWTH",
        "title": "自建目标的 `expect: 0` 前置必须给 `max_growth`",
        "why": (
            "runner 的漂移判据是 `after - before > max_growth`（缺省 0），而用例**自己就会创建**"
            "同名商品 ⇒ 正常行为下 `0 → 1 > 0` **恒判漂移**、`score` 归零 —— 即使逐条计分断言"
            "全 passed（实证判定跑 `35295494688` @`d5bca241`：`PR-008` / `PR-016` `score=0.0` 而"
            "逐条计分断言全 ✅；同族潜伏例 `CH-005`）。"
            "先例 = `HR-002` 的 `max_growth: 1`（自建目标的用例必须给 max_growth）。"
        ),
        "counterexample": ("PR-008（自建名 `测试窗帘A` + `expect: 0` 无 `max_growth`）；"
                           "PR-016（`E2E建品流程样品帘`）同形；C 端 CH-005（`星夜`）同形"),
        "implemented": True,
        "fix": (
            "给该前置加 `max_growth: 1` —— 只容忍**本用例自己造的那一个**；并行用例再造同名"
            "（`0 → 2`）仍判漂移，判别力不丢。**不得**改 `expect` / 删断言来绕过："
            "那会连「基线本就不成立」这一格一起丢掉。"
        ),
    },
    {
        "code": "CASE-TRUST-STALE-LINE-REF",
        "title": "`path:NNN` 行号引用必须对 `origin/main` 命中",
        "why": (
            "仓库已有「**不写裸行号**」的纪律（`migao-dev-flow` §16.7 引用纪律：活跃编辑"
            "文件的裸行号会在几分钟内失效），但**没有机器检查** —— `#3787` 记着 5 处过期指引。"
        ),
        "counterexample": "（`#3787` 的 5 处过期指引：`§16.5` / 「全库跑」/ 写死条数 / 存量裸行号）",
        "implemented": True,
        "fix": (
            "改用**符号 / 文本锚点**（如「按 `_first_successful_ticket_payload` 函数名检索」），"
            "或写成 `@<sha>` 限定的行号形式；确实要留行号时，先核 `origin/main` 上该行是否命中所引符号。"
        ),
    },
    {
        "code": "CASE-TRUST-SINGLE-LEG-NO-PERSONA",
        "title": "单端用例必须显式标注 persona",
        "why": (
            "单端用例缺标注 ⇒ 被另一条腿选中 ⇒ 该腿必挂（假红）；且 `case_ids` 窄跑时"
            "另一腿「禁止静默少跑」守卫会红，**配对不豁免**（#3822，run 34907040543）。"
        ),
        "counterexample": "（存量：按工具集可判定的纯小布用例中，缺 `persona` 标注者见基线清单）",
        "implemented": True,
        "fix": "在该用例上加 `persona: xiaobu`（或 `mibao`）。",
    },
)

RULES_BY_CODE: dict[str, dict] = {r["code"]: r for r in RULES}

# ── 未实装项（**如实登记**；绝不写成恒真判断凑数）─────────────────────────────
# 🔒 **可执行约束**（本次收紧）：每条登记**必须**带 `issue`（正整数追踪号）/ `expires`
# （YYYY-MM-DD）/ `how_to_verify`（**怎么算已实装**的可执行判据）/ `hit_probe`（僵尸判据）。
# 四条判据都可红（判据本体 = `judge_unimplemented()`；红证 = `tests/unit_ci_workflows/
# test_case_trust_gate.py`）：① 缺字段（指名缺哪个）② `expires` 已过 ③ `issue` 已 CLOSED
# （网络格，由门禁判）④ **僵尸**（登记所述口径已不成立）。为什么必须有：只有
# `why_not` + `needs` 时，「未实装」可以**永久**当借口 —— 没有任何东西会因此变红。
# 🗑️ **已撤登记（已实装，不许再登记回来）**：
#   · `CASE-TRUST-PRECLEAN-UNKNOWN-TYPE` / `CASE-TRUST-PRECLEAN-FAILURE-FOLD`
#     —— 两条的 `why_not` 都声称「runner 静默跳过 / 返回值不参与用例判定」，而 runner 侧
#     早已 fail-closed：`_PRECLEAN_TYPES` 是单一真值（未知 type ⇒ `_PRECLEAN_CONFIG_ERR`），
#     `check_preclean_not_applied` 按**稳定前缀**把它折进用例结论（#3781），清理型的
#     「目标不存在」按 #3791 走良性 no-op（可见、不进结论）；L0 五条判据 + 逐条红证锁在
#     `tests/unit_ci_workflows/test_eval_preclean_registry.py`。
#     留着 = 与实现相反的**假真值**（`migao-acceptance`：注释漂移是假绿来源）。
#   · `DRIFT-AUDIT-STALE-DIFF-SCOPED` —— `scripts/drift_audit.py` 的 `compare_baseline`
#     已改为**全量对账**并 **import 复用** `.github/case_trust_gate.py` 的
#     `reconcile_baseline` / `burn_down_verdict`（#4045：陈旧条目**不限 diff 命中**一律阻塞 +
#     反向对账「仍违规却被删」+ burn-down 预算），源码注释里那句「沿用 `stale_baseline_entries`
#     口径」的**假真值**已一并删掉 ⇒ 该登记所述口径**已不成立**。
#     ⚠️ 僵尸判据 `_probe_drift_audit_diff_scoped_stale` 与其注册项**保留**（它现在探不到证据 =
#     正是「已实装」的读数，按探针名检索即可复核），因此本项**不在**下方 `UNIMPLEMENTED` 里
#     —— 留着就是「实装了还挂着未实装」的假真值。
UNIMPLEMENTED: tuple[dict, ...] = (
    {
        "code": "CASE-TRUST-CROSS-LEG-NARROW-RUN",
        "title": "单端用例在与其他腿共用 `case_ids` 时被选中",
        "why_not": (
            "静态只能看到**本 PR 的 diff**，看不到「本次运行会不会用 `case_ids` 窄跑」"
            "—— 那是**运行期**信息。静态侧只能要求 persona 标注存在"
            "（`CASE-TRUST-SINGLE-LEG-NO-PERSONA` 已实装）。"
        ),
        "needs": (
            "runner 侧按 persona 校验 `case_ids` 的跨腿完整性（#3822；"
            "`local_runner.py` 的「禁止静默少跑」守卫按该文本检索）。属 T2。"
        ),
        # ── 收紧后的必填四字段（见本元组上方的「可执行约束」）──
        "issue": 3822,
        "expires": "2027-01-31",
        "how_to_verify": (
            "runner 的「禁止静默少跑」守卫**按 persona 校验 `case_ids` 的跨腿完整性**"
            "（单端用例被另一腿选中时不再产生误导性红/自动评论）⇒ 撤登记。"
            "核验：单腿派发（`xiaobu-acceptance.yml` 的 `persona` 输入）+ `case_ids` 含一条"
            "单端用例 ID，另一腿**不再**判红；或该守卫源码里出现按 persona 过滤 `case_ids` 的分支"
            "（按「禁止静默少跑」文本检索）。"
        ),
        "hit_probe": "single_leg_persona",
    },
    {
        "code": "CASE-TRUST-BURN-DOWN-SCOPE-CASE-TOUCHING-ONLY",
        "title": "burn-down 预算的「每 PR 最低消减」**默认只对改用例的 PR 生效**",
        "why_not": (
            "#4031 已实装全量对账（陈旧条目阻塞）+ 到期清零（全局生效），但**每-PR 最低消减**"
            "的口径默认 `scope=case_touching_prs`：字面口径（**每个** PR，含不改用例的）"
            "会让全仓每个 PR 都必须改 `.github/cases/**` + 清单才能合并 —— 与「先把清单清干净"
            "再翻 required，避免阻塞所有人」的顺序铁律自相矛盾，且会把 Java 单测 PR 也卡在"
            "用例库上（= 假红）。口径是**数据**（`burn_down.scope`），改为 `all_prs` 即字面口径。"
        ),
        "needs": (
            "要先让「清单条目可被多条 PR 各自删除的小文件化 / 自动重生成」落地，"
            "每-PR 口径才有可安全阻塞的目标（drift_audit 侧的同族改造已于 **#4045** 落地："
            "那边同样是 `scope=case_touching_prs` 的数据口径）。"
        ),
        # ── 收紧后的必填四字段（见本元组上方的「可执行约束」）──
        # 本项属**口径型**登记（不是代码缺口）：追踪单 #4155 同时承载它与
        # `CASE-TRUST-ALL-CASES-PERSONA-ANNOTATED` 的复核触发器。
        "issue": 4155,
        "expires": "2027-03-31",
        "how_to_verify": (
            "前置（豁免清单小文件化 / 可自动重生成）落地 ⇒ 把 `.github/case-trust-baseline.json`"
            "的 `burn_down.scope` 改成 `all_prs` 并撤本登记。"
            "核验命令：`python3 -c \"import json;print(json.load(open("
            "'.github/case-trust-baseline.json'))['burn_down']['scope'])\"` 输出 `all_prs` = 已实装。"
        ),
        "hit_probe": "burn_down_scope_case_touching",
    },
    {
        "code": "CASE-TRUST-ALL-CASES-PERSONA-ANNOTATED",
        "title": "**全库**用例都必须标注 persona",
        "why_not": (
            "口径过宽会让全部双端用例（存量 200+ 条）立刻违规 —— 但双端用例**本就不该**"
            "被强制标注（`persona: \"\"` 是合法的「双端」语义）。故只对**按工具集可判定为"
            "单端**的用例子集实装。"
        ),
        "needs": "无需落地（这是**有意不做**的口径，登记以免被误当遗漏）。",
        # ── 收紧后的必填四字段（见本元组上方的「可执行约束」）──
        # **口径型**登记：不是「要做没做」，而是「**有意更窄**」——但「有意」不等于
        # 「永久」：到期/追踪单 CLOSED 都必须重新裁定一次（不许静默续期）。
        "issue": 4155,
        "expires": "2027-06-30",
        "how_to_verify": (
            "persona 语义变更（例如引入显式 `persona: both` 双端标注）⇒ 全库标注成为"
            "**可判定且不产生假红**的口径，撤本登记并按新口径实装；或双端用例归零"
            "⇒ 子集口径 == 全库口径，本登记自动成僵尸。"
            "核验命令：`python3 -c \"import sys;sys.path.insert(0,'.github');"
            "from render_cases import load_case_dicts;"
            "print(sum(1 for c in load_case_dicts('.github/cases') "
            "if not str(c.get('persona') or '').strip()))\"`（当前 246 > 0 = 口径仍成立）。"
        ),
        "hit_probe": "dual_leg_no_persona",
    },
    {
        "code": "CASE-TRUST-PROSE-DATA-CHECK-QUALITY",
        "title": "纯散文 `data_checks` 的**语义**质量（是否真在测它声称的东西）",
        "why_not": (
            "「这条散文断言是不是真的覆盖了业务价值」是**语义**判断，静态无法判定"
            "（`migao-acceptance`：LLM 只覆盖语义残留）。静态侧只能判定「它**不计分**」"
            "（`is_machine_scored_data_check`）并据此要求效果层断言。"
        ),
        "needs": "LLM 用例语义审计（#3483 的 LLM 复核格），不属静态门禁。",
        # ── 收紧后的必填四字段（见本元组上方的「可执行约束」）──
        "issue": 3483,
        "expires": "2027-03-31",
        "how_to_verify": (
            "出现**可执行**的用例语义复核（`#3483` 的 LLM 复核格：逐条判定散文 `data_checks`"
            "是否真在测它声称的东西，且结论落盘可复查）⇒ 静态侧不再是「无法判定」"
            "⇒ 撤本登记。核验：存在按用例 ID 产出语义复核结论的脚本/用例，"
            "且 `python3 .github/case_trust_gate.py` 的未实装清单里不再需要这一条。"
        ),
        "hit_probe": "prose_data_check",
    },
)


# ══════════════════════════════════════════════════════════════════════════════
# 七之二、未实装登记的**可执行约束**（本次收紧）：字段 / 到期 / 僵尸
# ══════════════════════════════════════════════════════════════════════════════
#
# 为什么单开这一节（病灶）：`UNIMPLEMENTED` 原来只有 `why_not` + `needs` 两个自由文本字段
# ⇒「未实装」可以**永久**当借口：没有任何追踪号、没有到期日、没有「怎么算已实装」，
# 于是**没有任何东西会因此变红**（`migao-acceptance`：不会红的判据 = 空断言）。
# 现在四条都可红，且**判据只有这一处**（门禁只做「取数 → 调用 → 报错」）：
#
#   ① `MISSING_FIELD`：缺任一必填字段（**指名**缺哪个；`issue` 非正整数也算）⇒ 红
#   ② `EXPIRED`     ：`expires` 已过（非法/缺失的日期按**已到期**处理 = fail-closed）⇒ 红
#   ③ `ZOMBIE`      ：登记所述口径已不成立（`hit_probe` 探不到存活证据）⇒ 红
#      —— 僵尸判据为什么必须有：口径被修好/被绕开后，登记会**永久**留在清单里，
#      读者会以为「这条还没做」（与实现相反的假真值）。
#   ④ `ISSUE_CLOSED`：网络格（`issue` 指向的追踪单已 CLOSED）⇒ 红；由门禁判，
#      文案与修法仍在本节单点（判据文本与实现同源，避免两处漂移）。
#
# **依赖纪律**：本节全部为纯函数（不读文件、不联网）—— 门禁把 IO（读用例库、
# 读 `scripts/drift_audit.py` 源码、查 issue 状态）取好后**注入**给这里。

UNIMPLEMENTED_REQUIRED_FIELDS: tuple[str, ...] = (
    "code", "title", "why_not", "needs", "issue", "expires", "how_to_verify", "hit_probe",
)

# ⚠️ 这组码**不放进 `RULES`**：那是「逐用例」判据表（基线清单按 `case_id` 记账、
# `rule_counts` 逐码计数），而本组判据的对象是**登记条目**本身（没有 case_id）。
# 混进去会让基线出现无法解释的条目 ⇒ 两处口径都失真。
UNIMPLEMENTED_VIOLATION_CODES: dict[str, dict[str, str]] = {
    "MISSING_FIELD": {
        "code": "CASE-TRUST-UNIMPL-MISSING-FIELD",
        "title": "未实装登记缺必填字段（issue / expires / how_to_verify / hit_probe …）",
        "fix": (
            "补齐报告里点名的那一项：`issue`（正整数追踪号 —— 该单 CLOSED 即红）、"
            "`expires`（`YYYY-MM-DD`；过期即红，**不许静默续期**）、"
            "`how_to_verify`（**怎么算已实装**的可执行判据/命令，不是散文感想）、"
            "`hit_probe`（僵尸判据，取自 `UNIMPLEMENTED_HIT_PROBES` 的键）。"
        ),
    },
    "EXPIRED": {
        "code": "CASE-TRUST-UNIMPL-EXPIRED",
        "title": "未实装登记已到期（`expires` ≤ 今天）",
        "fix": (
            "到期不是自动失效、也不是自动续期：**要么撤登记**（已实装 —— 这是首选，"
            "并说明在哪落地），**要么**在追踪单上给出新的事实（为什么还不能做）后"
            "把 `expires` 往后挪，让这次推迟**在 PR diff 里可见**。"
            "日期写成非法/缺失同样按已到期处理（fail-closed）。"
        ),
    },
    "ZOMBIE": {
        "code": "CASE-TRUST-UNIMPL-ZOMBIE",
        "title": "僵尸登记：登记所述口径已不成立（hit_probe 探不到存活证据）",
        "fix": (
            "先核 `hit_probe` 的读数（门禁会打印存活证据）：口径**已不成立** ⇒ **撤登记**"
            "（信息别丢：把「已由谁在哪落地」写进本次 PR 说明）；口径仍在、但探针写错了 ⇒ "
            "改 `hit_probe` 指向真正能表达该口径的探针（不许写成恒真探针 —— 那就是复活"
            "「永久借口」）。"
        ),
    },
    "ISSUE_CLOSED": {
        "code": "CASE-TRUST-UNIMPL-ISSUE-CLOSED",
        "title": "`issue` 指向的追踪单已 CLOSED（借口不能过期不销）",
        "fix": (
            "追踪单 CLOSED 有两个出口：**实装了 ⇒ 撤登记**（首选）；**没实装 ⇒ 开新单**"
            "并把 `issue` 指向它（并把 `expires` 重新设成合理未来日期）。"
            "**不许**让一条已关闭的单继续当永久借口。"
        ),
    },
}

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def iso_date_or_expired(v) -> str:
    """规范化 `expires`：非法/缺失 ⇒ `0000-00-00`（**按已到期处理**，fail-closed）。

    与 `case_trust_gate._date` 同口径、**同样 fail-closed**：任何一侧放宽，
    「写个乱码当到期日」就能变成永久续期。
    """
    s = str(v or "").strip()
    if not _ISO_DATE_RE.match(s):
        return "0000-00-00"
    try:
        date.fromisoformat(s)
    except ValueError:
        return "0000-00-00"
    return s


# ── 僵尸判据（`hit_probe`）：探针 = 「这条登记所述的口径**还在不在**」──────────────
# 统一形状：`probe(probe_context) -> list[str]`，**返回存活证据**（空列表 = 僵尸）。
# ⚠️ 探针必须能真的变空（否则它自己就是一条不会红的判据）—— 每条都有对应红证，
# 见 `tests/unit_ci_workflows/test_case_trust_gate.py::TestUnimplementedRegistrations`。
# 探针是**纯函数**：所需的一切（用例库、生效清单、`drift_audit` 源码文本）由门禁注入
# `probe_context`，本模块不读文件、不联网。

def _ctx_cases(ctx: dict) -> list[dict]:
    return list(ctx.get("cases") or [])


def _probe_single_leg_persona(ctx: dict) -> list[str]:
    """口径 =「单端用例被另一腿选中」：只要还有**显式标注了 persona 的单端用例**，就还成立。"""
    return sorted({str(c.get("id") or "?") for c in _ctx_cases(ctx)
                   if str(c.get("persona") or "").strip()})


def _probe_burn_down_scope_case_touching(ctx: dict) -> list[str]:
    """口径 = `burn_down.scope == case_touching_prs`（生效清单那一份，数据即判据）。"""
    scope = str(((ctx.get("baseline") or {}).get("burn_down") or {}).get("scope") or "")
    return [f"burn_down.scope={scope}"] if scope == "case_touching_prs" else []


def _probe_drift_audit_diff_scoped_stale(ctx: dict) -> list[str]:
    """口径 = `scripts/drift_audit.py` **自实现** diff 命中口径的陈旧判据（未复用统一对账）。

    源码文本由门禁注入（本模块不读文件）。复用统一对账后探针为空 ⇒ 该登记成僵尸
    ⇒ 强制撤登记（**实装了就不许再挂着「未实装」**）。
    """
    src = ctx.get("drift_audit_source")
    if src is None:
        return ["scripts/drift_audit.py（源码未取到 —— 按存活处理，避免把读不到文件误判成已实装）"]
    return [] if "reconcile_baseline" in str(src) else [
        "scripts/drift_audit.py: compare_baseline 仍自实现 diff 命中口径的陈旧判据"]


def _probe_dual_leg_no_persona(ctx: dict) -> list[str]:
    """口径 =「双端用例不该被强制标注」：只要还有 `persona` 为空的用例，该口径就有对象。"""
    return sorted({str(c.get("id") or "?") for c in _ctx_cases(ctx)
                   if not str(c.get("persona") or "").strip()})


def _probe_prose_data_check(ctx: dict) -> list[str]:
    """口径 =「散文 `data_checks` 的语义质量静态判不了」：只要还有**不计分**的散文断言就成立。"""
    out: set[str] = set()
    for c in _ctx_cases(ctx):
        for d in (c.get("data_checks") or []):
            if not is_machine_scored_data_check(d):
                out.add(str(c.get("id") or "?"))
    return sorted(out)


UNIMPLEMENTED_HIT_PROBES: dict[str, object] = {
    "single_leg_persona": _probe_single_leg_persona,
    "burn_down_scope_case_touching": _probe_burn_down_scope_case_touching,
    "drift_audit_diff_scoped_stale": _probe_drift_audit_diff_scoped_stale,
    "dual_leg_no_persona": _probe_dual_leg_no_persona,
    "prose_data_check": _probe_prose_data_check,
}


def unimplemented_evidence(entries, probe_context: dict | None = None) -> dict[str, list[str]]:
    """每条登记的**存活证据**（= 僵尸判据的正面读数）→ `{code: [证据…]}`。

    空列表 = 僵尸。**未注册的探针名 ⇒ 空**（无判据的登记按僵尸处理，fail-closed）。
    报告必须把它打印出来（否则「为什么说它活着」没有可复查的读数）。
    """
    ctx = probe_context or {}
    out: dict[str, list[str]] = {}
    for item in entries or []:
        name = str((item or {}).get("hit_probe") or "")
        probe = UNIMPLEMENTED_HIT_PROBES.get(name)
        if probe is None:
            out[str(item.get("code") or "?")] = []
            continue
        try:
            out[str(item.get("code") or "?")] = list(probe(ctx))  # type: ignore[operator]
        except Exception:
            # 探针自身炸了 = 判据不可用 ⇒ 按**僵尸**处理（fail-closed，绝不静默成活）
            out[str(item.get("code") or "?")] = []
    return out


def _field_missing(v) -> bool:
    """字段是否**等于没写**（`None` / 空容器 / 空白串都算 —— 不许用空值凑数）。"""
    if v is None or v == [] or v == {}:
        return True
    return isinstance(v, str) and not v.strip()


def judge_unimplemented(entries, *, today: str,
                        probe_context: dict | None = None) -> list[dict]:
    """未实装登记的**可执行约束**裁决（纯函数）→ `[{"code","entry","detail","fix"}]`。

    三条可静态判定的判据（第 ④ 条 `ISSUE_CLOSED` 需网络，由门禁单独判）：
      ① 缺必填字段（`UNIMPLEMENTED_REQUIRED_FIELDS`，**指名**缺哪个）；
      ② `expires` 已过（非法/缺失按已到期处理）；
      ③ 僵尸（`hit_probe` 未注册，或探不到存活证据）。

    `today` 必须由调用方注入（可确定性红证），**不得**在判据里取系统时间。
    """
    evidence = unimplemented_evidence(entries, probe_context)
    out: list[dict] = []
    for item in entries or []:
        item = item or {}
        code = str(item.get("code") or "?")
        entry_name = code

        def add(kind: str, detail: str) -> None:
            spec = UNIMPLEMENTED_VIOLATION_CODES[kind]
            out.append({"code": spec["code"], "entry": entry_name,
                        "detail": detail, "fix": spec["fix"]})

        missing = [f for f in UNIMPLEMENTED_REQUIRED_FIELDS
                   if _field_missing(item.get(f))]
        if missing:
            add("MISSING_FIELD",
                f"登记 {code} 缺必填字段：{('、'.join(missing))} —— "
                f"（`why_not`/`needs` 只是理由与缺口，**不是**约束；"
                f"没有追踪号/到期日/实装判据 = 可以永久当借口）")
        issue = item.get("issue")
        if not missing or "issue" not in missing:
            # `True` 是 `int` 的子类 ⇒ 显式排除布尔（`issue: true` 不是追踪号）
            if isinstance(issue, bool) or not isinstance(issue, int) or issue <= 0:
                add("MISSING_FIELD",
                    f"登记 {code} 的 `issue` 必须是**正整数追踪号**（实际 {issue!r}）——"
                    f"否则「已 CLOSED 即红」这条判据失去目标（指向不存在的单 = 假借口）")
        exp = iso_date_or_expired(item.get("expires"))
        if exp <= str(today):
            add("EXPIRED",
                f"登记 {code} 已到期：`expires`={item.get('expires')!r}（规范化后 {exp}）"
                f" ≤ 今天 {today} —— 到期未实装**不许静默续期**：撤登记，或改追踪单后"
                f"把 `expires` 挪到合理未来日期（推迟要在 diff 里可见）")
        probe_name = str(item.get("hit_probe") or "")
        if probe_name not in UNIMPLEMENTED_HIT_PROBES:
            add("ZOMBIE",
                f"登记 {code} 的 `hit_probe`={probe_name!r} 未注册（可用："
                f"{sorted(UNIMPLEMENTED_HIT_PROBES)}）—— **无判据的登记 = 僵尸登记**，"
                f"不许用「探针永远为真」凑数")
        elif not evidence.get(code):
            add("ZOMBIE",
                f"登记 {code} 所述口径**已不成立**（`hit_probe`={probe_name!r} 探不到任何"
                f"存活证据）—— 口径被修好/被绕开后，登记会永久留在清单里被读成「还没做」")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 八、裁决入口（**门禁与动态分类器共用的唯一入口**）
# ══════════════════════════════════════════════════════════════════════════════

def judge_case(case: dict, *, catalog: dict[str, set[str]] | None = None,
               raw_text: str | None = None, repo_root=None) -> list[dict]:
    """对**单条**用例给出违规列表（纯函数，无副作用）。

    返回 `[{"code", "case_id", "detail", "fix"}]`，空列表 = 无违规。
    `catalog` 为 None 时跳过「种子可解析」规则（**不**当成通过 —— 由调用方决定是否加载种子；
    门禁脚本**必须**传 catalog，否则会静默少判一条规则，故门禁里断言 catalog 非空）。
    `repo_root` 只用于「计分通道分流」的 `traces.tests` 存在性校验（#4244）：
    传仓库根即启用；不传 ⇒ 按未成立处理（fail-closed，见 `backend_contract_scoring_channel`）。
    """
    out: list[dict] = []
    cid = str(case.get("id") or "?")

    def add(code: str, detail: str) -> None:
        out.append({
            "code": code,
            "case_id": cid,
            "detail": detail,
            "fix": RULES_BY_CODE[code]["fix"],
        })

    # ── 计分通道分流（#4244）：`[backend-contract]` 用例由 `traces.tests` 计分，
    #    不适用下面 a1/a2 两条**runner 计分口径**的规则（其余规则一字不放宽）──
    traces_scored = backend_contract_scoring_channel(case, repo_root)

    # ── 规则 a1：可失败性（计分断言非空）──
    n_scoring = scoring_assertion_count(case)
    if n_scoring == 0 and not traces_scored:
        add("CASE-TRUST-EMPTY-ASSERTION",
            f"计分断言数 = 0（expectations={len(case.get('expectations') or [])}，"
            f"机器计分型 data_checks={len(machine_scored_data_checks(case))}）"
            f"⇒ 恒绿：score 公式 `total_exp > 0 else 1.0` 会给满分")

    # ── 规则 a2：写类用例 ≥1 效果层断言 ──
    write_exps = write_expectations(case)
    if write_exps:
        names = ", ".join(sorted({t for t, _ in write_exps}))
        if not has_effect_assertion(case) and not traces_scored:
            add("CASE-TRUST-NO-EFFECT-ASSERTION",
                f"含写期望 [{names}] 但无任何效果层断言"
                f"（效果层字段：{'/'.join(EFFECT_FIELDS)}；"
                f"机器计分型 data_checks 也认，但必须含 "
                f"{'/'.join(MACHINE_DATA_CHECK_MARKERS)} 之一）"
                f"⇒「调用了 ≠ 成了」（#3778）")

        # ── 规则 b：前置等价性（写用例必须声明自清理）──
        if not self_clean_evidence(case):
            add("CASE-TRUST-NO-SELF-CLEAN",
                f"含写期望 [{names}] 但未声明自清理"
                f"（`pre_clean` 或 `namespaces`）⇒ 重试前置与首跑不等价（#3800）")

        # ── 规则 b2：pre_clean 目标必须在种子真值里可解析 ──
        if catalog is not None:
            for ptype, field, value in pre_clean_targets(case):
                # 清理族 + 目标 = 本用例自己声明的资源 ⇒ 该对象是**用例运行期自建的**，
                # "不在种子里"是设计而非缺陷（详见 `CLEANUP_PRECLEAN_TYPES` 的注释）。
                if is_case_owned_cleanup_target(case, ptype, value):
                    continue
                if not resolve_pre_clean_target(ptype, field, value, catalog):
                    add("CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE",
                        f"pre_clean[{ptype}].{field} = {value!r} 在种子真值里解析不到"
                        f"（已收表：{sorted(k for k in catalog if catalog[k])}）"
                        f"⇒ 用例物理不可满足（#3832/#3794）")

    # ── 规则 c：forbidden_text 不得单独承载 ──
    if uses_forbidden_text(case) and not forbidden_text_is_round_scoped(raw_text):
        if not has_behavior_assertion(case) and not has_forbidden_text_intent(raw_text):
            add("CASE-TRUST-FORBIDDEN-TEXT-SOLE",
                f"使用了 forbidden_text（{len(case.get('forbidden_text') or [])} 条，"
                f"**全程**语义、无轮次作用域）但无任何行为/效果层断言陪跑"
                f"⇒ 单轮良性措辞即可判红（假红，#3833/#3800）")

    # ── 规则 e：定位被测对象必须用不可变标识（位置/序号选择器 ⇒ 阻塞）──
    idx_pos = index_selector_positions(case)
    if idx_pos:
        detail = "、".join(f"{w}.{k}" for w, k in idx_pos)
        add("CASE-TRUST-VOLATILE-LOCATOR",
            f"用**列表位置/序号**定位被测对象：{detail} ⇒ 列表顺序是运行时排序，"
            f"别人中途造一条同名/同序记录就会定位到**别的对象**上"
            f"（取证：CU-003 的 customer_index: 0 + 列表 created_at DESC）")

    # ── 规则 f：多轮/写类用例必须对自己的前置给出可判定断言 ──
    if needs_precondition_assertion(case):
        ok, how = declares_precondition(case)
        if not ok:
            n_rounds = len(case.get("user_inputs") or [])
            add("CASE-TRUST-NO-PRECONDITION-ASSERTION",
                f"多轮/写类用例（{n_rounds} 轮"
                f"{'、含写期望' if is_write_case(case) else ''}）没有任何**可判定**的前置断言"
                f"⇒ 前置不成立时红的表现像「agent 不干活」"
                f"（PG-013 重试前置不成立 / CU-003 客户数=2 的形态）")

    # ── 规则 h：自建目标的 `expect: 0` 前置必须给 `max_growth`（issue #4200）──
    for kw in self_target_missing_max_growth(case):
        add("CASE-TRUST-SELF-TARGET-NO-MAX-GROWTH",
            f"`namespaces` 声明了自建名 {kw!r}（本用例自己会创建它），"
            f"而 `precondition[{SELF_TARGET_PRECONDITION_TYPE}]` 对同一名字声明 `expect: 0` "
            f"却不给 `max_growth`（缺省 {PRECONDITION_NO_DRIFT}）⇒ 正常行为下 "
            f"`0 → 1 > 0` **恒判漂移**、score 归零（实证判定跑 35295494688："
            f"PR-008 / PR-016 逐条计分断言全 passed 而 score=0.0）"
            f"⇒ 加 `max_growth: 1` 容忍自建的那一个（并行再造同名仍判漂移）")

    # ── 规则 d：单端用例必须标注 persona ──
    if missing_persona_annotation(case):
        tools = sorted({t for t, _ in expectation_tools(case) if t})
        add("CASE-TRUST-SINGLE-LEG-NO-PERSONA",
            f"期望工具 {tools} ⊆ 小布工具集（米宝工具集与之不相交）"
            f"⇒ 只能跑单端，但 persona 未标注"
            f"（缺 persona 的另一条腿必挂；`case_ids` 窄跑还会触发"
            f"「{SILENT_SKIP_GUARD_ANCHOR}」守卫，#3822）")

    return out
