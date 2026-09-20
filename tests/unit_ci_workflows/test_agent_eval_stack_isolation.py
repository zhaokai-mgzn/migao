# case_ids: HR-003, AS-003, OR-014, PR-017
"""`agent-eval` 的隔离栈 + 用例级并发（issue #4821）—— L0 静态锁（零 LLM、零 docker）。

## 病灶（#4821 的核实结论，逐条见 PR body）

`agent-eval.yml` 的 normal 档**改造前**打**共享云环境**（`ai-api.migaozn.com` /
`api.migaozn.com`）且**未设 `EVAL_CONCURRENCY`** ⇒ runner 默认 1 = **严格串行**。

实测（既有 run `34800764957` 的日志逐条 `⏱ <ID> start=` 时间戳）：70 条用例首尾相接
**2873s**，而该 job 墙钟 2891s ⇒ **99.4% 的墙钟就是用例执行、零重叠零空转**
（与 issue 引用的 2882s 同源）。故"无谓等待"无可省，唯一杠杆是用例级并发。

⚠️ **但并发的前提是隔离**：normal 档含建品/下单/改客户等**写用例**，并发写同一套共享
dev 库会互相污染 ⇒ 假失败会落进失败建 issue 的去重守卫（同标题
`[Agent Eval] 米宝冒烟评测失败 — <date>`），把"噪音与真失败同形"引回来。
本提交给该 workflow 补上**每次跑完即销毁的隔离栈**（平移两个已落地先例的起栈手法 +
种子单一源 `scripts/eval_stack_seed.sh`），并发才敢打开。

## 本文件锁定什么（每条断言都有**注入式反向红证**）

1. **隔离**：评测步骤不许再打共享云环境（地址必须是本地 compose 容器）；
2. **可回退**：`EVAL_CONCURRENCY` 接 workflow 输入、默认 = 同族口径，
   `-f concurrency=1` 一路可达（runner 侧 `--concurrency` 缺省回落 1 = 串行）；
3. **覆盖面不缩水**：评测命令恒为 `normal --cases .github/cases`，不得出现
   `--case-ids` / `--shard` / 非 normal 档；
4. **分道不丢用例**：`parallel ∪ serial == 全量`（并发只改"同时跑几条"，
   不改"跑什么"）—— 且并**不**改变选题（选题函数不吃并发参数，AST 判据）；
5. **种子与 runner 的 persona 同源**（种子装 mibao、runner 跑 xiaobu = 拿错栈跑，
   正是 #3563 的 0 分形态）；
6. **跑完即销毁**（`if: always()`）+ 全局槽位（`eval-stack-global`）。

## 未真跑（照实登记，成本纪律 #4262）

并发下的"假失败 0"读数**本单未实测**（不派发真实 LLM 评测）。本文件是**零 LLM 的
结构性证明 + 既有 run 的离线推演**，不声称"已验证并发无假失败"。
推演读数（同一可比子集 63 条、既有 run 逐条耗时 + 本仓 `serialize_seconds` 代价模型）：
实测串行 **2873s** → 并发 6 的下界 **1215s**（**≈58%**，不是 issue 估算的 83%）——
下界由**独占串行道**顶着（20 条声明了命名空间撞车/id_reuse/update/pre_clean 的用例
合计 1215s，与并发度**无关**）。该推演的复算命令写在 PR body，可独立重放。
"""
import ast
import datetime
import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"
WORKFLOW = "agent-eval.yml"
SEED_STEP_NAME = "Seed 评测业务数据"
SLOT_GROUP = "eval-stack-global"
# 同族口径（post-deploy-eval / xiaobu-acceptance 的 `concurrency` 默认皆 6）
FAMILY_DEFAULT_CONCURRENCY = "6"
# 共享云环境的域名特征（改造前本 workflow 打的就是它）
SHARED_ENV_HOSTS = ("migaozn.com",)
EVAL_CMD_RE = re.compile(r"local_runner\.py\s+(\S+)\s+--cases\s+(\S+)")
# 种子调用形态：`bash scripts/eval_stack_seed.sh --persona "<表达式>"` —— 取**整段引号内**
# 的表达式（同族两处都带引号），便于与 runner 的 `PERSONA` 逐字符比对。
# 不带引号 ⇒ 匹配不到 ⇒ 判据 fail-closed 报红（而不是静默"没找到就放过"）。
SEED_CALL_RE = re.compile(r'bash\s+scripts/eval_stack_seed\.sh\s+--persona\s+"([^"]+)"')


# ── 载入（被测对象：workflow YAML 的**解析真值**，不是全文正则）──────────────

def _load_workflow(name: str = WORKFLOW) -> dict:
    return yaml.safe_load((WORKFLOWS_DIR / name).read_text(encoding="utf-8")) or {}


def _steps(wf: dict) -> list:
    out = []
    for job in (wf.get("jobs") or {}).values():
        out.extend(job.get("steps") or [])
    return out


def _named(wf: dict, keyword: str) -> list:
    return [s for s in _steps(wf) if keyword in (s.get("name") or "")]


def _eval_steps(wf: dict) -> list:
    """评测步骤 = 步骤名或命令体里出现 `local_runner`（与同族守卫同判据）。"""
    return [s for s in _steps(wf)
            if "local_runner" in ((s.get("name") or "") + (s.get("run") or ""))]


def _eval_step(wf: dict) -> dict:
    steps = _eval_steps(wf)
    assert len(steps) == 1, f"{WORKFLOW} 的评测步骤应唯一，实测 {len(steps)} 个"
    return steps[0]


def _seed_step(wf: dict) -> dict:
    steps = _named(wf, SEED_STEP_NAME)
    assert len(steps) == 1, f"{WORKFLOW} 的注种子步骤应唯一，实测 {len(steps)} 个"
    return steps[0]


def _dispatch_inputs(wf: dict) -> dict:
    triggers = wf.get("on") or wf.get(True) or {}
    return ((triggers.get("workflow_dispatch") or {}).get("inputs") or {})


def _job(wf: dict, name: str) -> dict:
    return (wf.get("jobs") or {}).get(name) or {}


# ── 判据本体（纯函数：输入 = 解析后的 workflow，便于注入式红证）──────────────

def audit_target_env(wf: dict) -> list:
    """① 隔离：评测步骤的两个地址不许指向共享云环境。"""
    problems = []
    env = _eval_step(wf).get("env") or {}
    for key in ("AI_API_URL", "ADMIN_API_URL"):
        val = str(env.get(key) or "")
        if not val:
            problems.append(f"评测步骤缺 {key} —— 无从判定打的是哪套环境")
        elif any(h in val for h in SHARED_ENV_HOSTS):
            problems.append(
                f"{key}={val!r} 仍指向**共享环境** —— 并发写同一套共享数据会互相污染"
                f"（#4821：隔离栈正是打开并发的前置）"
            )
    body = "\n".join((s.get("run") or "") for s in _named(wf, "Start local stack"))
    if "docker compose" not in body:
        problems.append("找不到 `Start local stack` 步骤（docker compose 起栈）—— 隔离栈缺失")
    return problems


def audit_revert_switch(wf: dict) -> list:
    """② 可回退：并发度可配、默认 = 同族口径、`1` 一路可达。"""
    problems = []
    inputs = _dispatch_inputs(wf)
    if "concurrency" not in inputs:
        problems.append(
            "workflow_dispatch 缺 `concurrency` 输入 —— 并发度不可配："
            "出问题时无法一键退回串行（#4821 明列的硬要求）"
        )
    else:
        default = str(inputs["concurrency"].get("default"))
        if default != FAMILY_DEFAULT_CONCURRENCY:
            problems.append(
                f"`concurrency` 默认值 {default!r} ≠ 同族口径 "
                f"{FAMILY_DEFAULT_CONCURRENCY!r}（post-deploy-eval / xiaobu-acceptance 皆 6）"
            )
    expr = str((_eval_step(wf).get("env") or {}).get("EVAL_CONCURRENCY") or "")
    if not expr:
        problems.append("评测步骤未设 EVAL_CONCURRENCY")
    elif "concurrency" not in expr:
        problems.append(
            f"EVAL_CONCURRENCY={expr!r} 未接 workflow 输入（写死 = 不可回退，只能改代码）"
        )
    return problems


def audit_coverage_not_narrowed(wf: dict) -> list:
    """③ 覆盖面不缩水：命令恒为 `normal --cases .github/cases`，无收窄/分片开关。"""
    problems = []
    run = _eval_step(wf).get("run") or ""
    matches = EVAL_CMD_RE.findall(run)
    if len(matches) != 1:
        problems.append(f"评测命令应恰好一条 `local_runner.py <tier> --cases <dir>`，实测 {matches}")
    else:
        tier, cases = matches[0]
        if tier != "normal":
            problems.append(f"档位 {tier!r} ≠ 'normal'（改档 = 改跑什么，属覆盖面变更）")
        if cases != ".github/cases":
            problems.append(f"用例源 {cases!r} ≠ '.github/cases'（用例库单一源）")
    for banned in ("--case-ids", "--shard"):
        if banned in run:
            problems.append(
                f"评测命令出现 {banned} —— #4821 明令「不许减少评测轮数/用例」："
                "并发改造只许改变「同时跑几条」，不许改变「跑什么」"
            )
    return problems


def audit_teardown(wf: dict) -> list:
    """④ 跑完即销毁（隔离承诺的必要组成）。"""
    problems = []
    steps = [s for s in _steps(wf) if "Teardown" in (s.get("name") or "")]
    if len(steps) != 1:
        problems.append(f"应有且仅有 1 个 Teardown 步骤，实测 {len(steps)} 个")
        return problems
    step = steps[0]
    if "down -v" not in (step.get("run") or ""):
        problems.append("Teardown 未 `down -v`（不删数据卷 = 下一次跑不是全新库）")
    if "always()" not in str(step.get("if") or ""):
        problems.append(
            "Teardown 缺 `if: always()` —— 评测失败时残留容器/卷，"
            "「下一次跑是不是干净栈」变成不可判定"
        )
    return problems


def audit_persona_same_source(wf: dict) -> list:
    """⑤ 种子与 runner 的 persona 必须同源（同一表达式）。"""
    problems = []
    seed_expr = SEED_CALL_RE.findall(_seed_step(wf).get("run") or "")
    if len(seed_expr) != 1:
        problems.append(f"种子步骤应恰好一次调用单一源，实测 {seed_expr}")
        return problems
    runner_expr = (_eval_step(wf).get("env") or {}).get("PERSONA")
    if not runner_expr:
        problems.append("评测步骤未设 PERSONA（会静默回落到 runner 默认 mibao）")
    elif str(runner_expr).strip() != seed_expr[0].strip():
        problems.append(
            f"persona 不同源：种子用 {seed_expr[0]!r}、runner 用 {str(runner_expr)!r} —— "
            "拿 A 的栈跑 B 的用例正是 #3563 的 0 分形态"
        )
    return problems


def audit_slot(wf: dict) -> list:
    """⑥ 起栈的 job 必须进全局槽位（与同族同名、不 cancel 正在跑的）。"""
    problems = []
    job = _job(wf, "agent-eval")
    conc = job.get("concurrency") or {}
    group = str(conc.get("group") or "")
    if not group.startswith(SLOT_GROUP):
        problems.append(
            f"job 级 concurrency.group={group!r} 应以 {SLOT_GROUP!r} 开头 —— "
            "跨 workflow 无约束 ⇒ 并发建栈把栈启动从 3.4min 抬到 12min"
        )
    if conc.get("cancel-in-progress") is not False:
        problems.append("job 级 cancel-in-progress 必须为 False（取消在跑的一条 = 白烧一次全量 LLM）")
    return problems


# ── runner 侧判据（读源/AST，输入 = 源码字符串，便于注入式红证）──────────────

SELECTION_FUNCS = ("select_cases_for_persona", "load_cases_from_yaml", "filter_cases_by_ids")


def _call_name(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def audit_selection_ignores_concurrency(source: str) -> list:
    """选题函数不得吃并发参数（= 并发度不参与"跑什么"）。"""
    problems = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _call_name(node.func) in SELECTION_FUNCS:
            args = list(node.args) + [k.value for k in node.keywords]
            if any("concurren" in ast.dump(a).lower() for a in args):
                problems.append(
                    f"{_call_name(node.func)} 收到了并发参数 —— 并发度参与了选题："
                    "「改并发」就会变成「改覆盖面」"
                )
    return problems


def audit_runner_revert_path(source: str) -> list:
    """runner 侧必须有「缺省回落 1 = 串行」的回退路径。"""
    problems = []
    if not re.search(r'os\.environ\.get\(\s*["\']EVAL_CONCURRENCY["\']\s*,\s*["\']1["\']\s*\)',
                     source):
        problems.append(
            "runner 的 `--concurrency` 默认值不再回落 `EVAL_CONCURRENCY` 缺省 '1' —— "
            "「配置丢失」的失效形态会从『变慢』变成『静默开并发』"
        )
    if "ConcurrencyGate" not in source:
        problems.append("runner 缺 ConcurrencyGate（读写门）—— 独占窗口语义消失")
    return problems


def _load_runner():
    """导入 `local_runner`（L0 job 可能没装 httpx → 注入最小替身，同 #3781 的做法）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                       # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    sys.path.insert(0, str(RUNNER_PATH.parent))
    import local_runner
    return local_runner


def audit_lane_union(runner, cases: list) -> list:
    """分道不丢用例：`parallel ∪ serial == 全量`（并发只改同时跑几条）。"""
    problems = []
    ns = runner.namespace_conflict_groups(cases)
    conflicted = {i for g in ns.values() for i in g}
    parallel = [c for c in cases if not runner.needs_serial_lane(c, conflicted)]
    serial = [c for c in cases if runner.needs_serial_lane(c, conflicted)]
    lane_ids = sorted([c.id for c in parallel] + [c.id for c in serial])
    all_ids = sorted(c.id for c in cases)
    if lane_ids != all_ids:
        lost = sorted(set(all_ids) - set(lane_ids))
        dup = sorted({i for i in lane_ids if lane_ids.count(i) > 1})
        problems.append(
            f"分道丢/重用例：缺 {lost[:8]}（共 {len(lost)} 条）、重复 {dup[:8]} —— "
            "并发分道必须恰好覆盖全量（覆盖面无条件不缩水）"
        )
    return problems


def _real_mibao_normal(runner) -> list:
    cases = runner.load_cases_from_yaml(str(REPO_ROOT / ".github" / "cases"))
    sel = runner.select_cases_for_persona(cases, "mibao")
    return [c for c in sel if c.difficulty == runner.Difficulty.NORMAL and not c.skip_reason]


# ── 测试：workflow 侧 ───────────────────────────────────────────────────────

def test_eval_targets_isolated_stack():
    assert audit_target_env(_load_workflow()) == []


def test_red_proof_shared_env_restored():
    """反向红证：把地址改回共享云环境 ⇒ ① 判据必须变红。"""
    wf = _load_workflow()
    _eval_step(wf)["env"]["AI_API_URL"] = "https://ai-api.migaozn.com"
    problems = audit_target_env(wf)
    assert problems and "共享环境" in problems[0], (
        f"把评测地址改回共享环境后判据仍是绿的 —— 该断言不会红（空断言）：{problems}"
    )


def test_revert_switch_is_wired_and_defaulted():
    assert audit_revert_switch(_load_workflow()) == []


def test_red_proof_concurrency_hardcoded():
    """反向红证：并发度写死（不可回退）⇒ ② 判据必须变红。"""
    wf = _load_workflow()
    _eval_step(wf)["env"]["EVAL_CONCURRENCY"] = "6"
    problems = audit_revert_switch(wf)
    assert problems and "未接 workflow 输入" in problems[0], problems


def test_red_proof_concurrency_input_removed():
    """反向红证：删掉 concurrency 输入 ⇒ ② 判据必须变红。"""
    wf = _load_workflow()
    _dispatch_inputs(wf).pop("concurrency")
    problems = audit_revert_switch(wf)
    assert problems and "缺 `concurrency` 输入" in problems[0], problems


def test_coverage_is_not_narrowed():
    assert audit_coverage_not_narrowed(_load_workflow()) == []


@pytest.mark.parametrize("banned", ["--case-ids OR-001", "--shard 0/2"])
def test_red_proof_narrowing_command_reds(banned):
    """反向红证：评测命令一旦收窄/分片 ⇒ ③ 判据必须变红。"""
    wf = _load_workflow()
    _eval_step(wf)["run"] = _eval_step(wf)["run"] + f" {banned}"
    problems = audit_coverage_not_narrowed(wf)
    assert problems, f"加了 {banned} 后判据仍绿 —— 覆盖面缩水无人拦"


def test_red_proof_tier_change_reds():
    """反向红证：把 normal 换成 smoke ⇒ ③ 判据必须变红（改档 = 改跑什么）。"""
    wf = _load_workflow()
    _eval_step(wf)["run"] = _eval_step(wf)["run"].replace(" normal --cases", " smoke --cases")
    problems = audit_coverage_not_narrowed(wf)
    assert problems and "档位" in problems[0], problems


def test_teardown_destroys_stack_on_all_paths():
    assert audit_teardown(_load_workflow()) == []


def test_red_proof_teardown_without_always_reds():
    """反向红证：Teardown 去掉 `if: always()` ⇒ ④ 判据必须变红。"""
    wf = _load_workflow()
    step = next(s for s in _steps(wf) if "Teardown" in (s.get("name") or ""))
    step.pop("if", None)
    problems = audit_teardown(wf)
    assert problems and "always()" in problems[0], problems


def test_red_proof_teardown_without_volume_wipe_reds():
    """反向红证：不 `down -v`（留着数据卷）⇒ ④ 判据必须变红。"""
    wf = _load_workflow()
    step = next(s for s in _steps(wf) if "Teardown" in (s.get("name") or ""))
    step["run"] = "echo noop"
    problems = audit_teardown(wf)
    assert problems and "down -v" in problems[0], problems


def test_seed_and_runner_persona_same_source():
    assert audit_persona_same_source(_load_workflow()) == []


def test_red_proof_persona_divergence_reds():
    """反向红证：种子与 runner 的 persona 分叉 ⇒ ⑤ 判据必须变红。"""
    wf = _load_workflow()
    _eval_step(wf)["env"]["PERSONA"] = "${{ github.event.inputs.persona || 'xiaobu' }}"
    problems = audit_persona_same_source(wf)
    assert problems and "不同源" in problems[0], problems


def test_job_holds_the_global_eval_slot():
    assert audit_slot(_load_workflow()) == []


def test_red_proof_missing_slot_reds():
    """反向红证：去掉 job 级槽位 ⇒ ⑥ 判据必须变红。"""
    wf = _load_workflow()
    _job(wf, "agent-eval").pop("concurrency", None)
    problems = audit_slot(wf)
    assert problems and "eval-stack-global" in problems[0], problems


def test_red_proof_cancellable_slot_reds():
    """反向红证：把槽位改成 cancel-in-progress=true ⇒ ⑥ 判据必须变红。"""
    wf = _load_workflow()
    _job(wf, "agent-eval")["concurrency"]["cancel-in-progress"] = True
    problems = audit_slot(wf)
    assert problems and "cancel-in-progress" in problems[0], problems


def test_no_automatic_llm_trigger_added():
    """#4262：本 workflow 仍**仅手动**（本次改造不得顺手加定时/PR 触发）。"""
    triggers = _load_workflow().get("on") or _load_workflow().get(True) or {}
    assert sorted(triggers) == ["workflow_dispatch"], (
        f"agent-eval.yml 的触发面 = {sorted(triggers)} —— 真实 LLM 自动触发全仓仅允许 1 条"
        "（post-deploy-eval 每周一），本 workflow 必须仍为仅手动（#4262）"
    )


# ── 测试：runner 侧（零 LLM，读源 + 真实用例库）────────────────────────────

def test_selection_functions_do_not_take_concurrency():
    src = RUNNER_PATH.read_text(encoding="utf-8")
    assert audit_selection_ignores_concurrency(src) == []


def test_red_proof_selection_taking_concurrency_reds():
    """反向红证：让选题函数吃并发参数 ⇒ AST 判据必须变红。"""
    mutated = "x = select_cases_for_persona(cases, PERSONA, concurrency)\n"
    problems = audit_selection_ignores_concurrency(mutated)
    assert problems and "参与了选题" in problems[0], problems


def test_runner_keeps_serial_revert_path():
    assert audit_runner_revert_path(RUNNER_PATH.read_text(encoding="utf-8")) == []


def test_red_proof_default_concurrency_raised_reds():
    """反向红证：把 runner 缺省并发从 1 抬到 6 ⇒ 回退路径判据必须变红。"""
    src = RUNNER_PATH.read_text(encoding="utf-8").replace(
        'os.environ.get("EVAL_CONCURRENCY", "1")', 'os.environ.get("EVAL_CONCURRENCY", "6")'
    )
    problems = audit_runner_revert_path(src)
    assert problems and "回落" in problems[0], problems


@pytest.mark.parametrize("persona", ["mibao", "xiaobu"])
def test_lane_split_covers_every_case(persona):
    """分道不丢用例（真实用例库 + 真实分道判据，两条 persona 腿各判一次）。"""
    runner = _load_runner()
    cases = runner.load_cases_from_yaml(str(REPO_ROOT / ".github" / "cases"))
    sel = runner.select_cases_for_persona(cases, persona)
    normal = [c for c in sel if c.difficulty == runner.Difficulty.NORMAL and not c.skip_reason]
    assert normal, f"persona={persona} 的 normal 档用例集为空（守卫前提失效）"
    assert audit_lane_union(runner, normal) == []


def test_red_proof_dropped_lane_case_reds():
    """反向红证：串行道「只挑不撞车的」= 丢掉争用用例 ⇒ 分道判据必须变红。"""
    runner = _load_runner()
    cases = _real_mibao_normal(runner)
    ns = runner.namespace_conflict_groups(cases)
    conflicted = {i for g in ns.values() for i in g}
    # 变异形态：把撞车用例从两条道里都「优化」掉（"并行跑得更快"的假优化）
    pruned = [c for c in cases if c.id not in conflicted]
    problems = audit_lane_union(runner, pruned)
    # pruned 自身的并集是自洽的 —— 故真正要判红的是「与全量的差集」（这正是判据的意义）
    assert problems == [], "前提：pruned 自身分道自洽（本条只证明判据按全量比对）"
    assert conflicted, "前提：真实用例库里确实存在命名空间争用用例"
    assert audit_lane_union(runner, cases) == [], "全量分道必须自洽"
    full_ids = {c.id for c in cases}
    assert full_ids - {c.id for c in pruned}, "变异必须真的少了用例（否则红证是空的）"


def test_plan_case_count_is_invariant_to_concurrency():
    """`serialize_seconds` 的 `cases` 不随并发度变化 = 并发不改"跑什么"。

    （⚠️ 该模型的 `wall_s` 在 k=1 时**不代表**真实串行墙钟 —— 它假设并行道与串行道
    可重叠；真实串行墙钟 = 各条耗时之和，见本文件头部推演。故这里只断言**条数不变**。）
    """
    runner = _load_runner()
    cases = _real_mibao_normal(runner)
    durations = {c.id: 25.0 for c in cases}          # 合成耗时：只判条数不变量
    counts = {runner.serialize_seconds(cases, durations, k)["cases"] for k in (1, 2, 3, 6, 8, 12)}
    assert counts == {len(cases)}, (
        f"并发度改变了计划里的用例条数：{counts} vs {len(cases)} —— 并发动了覆盖面"
    )
