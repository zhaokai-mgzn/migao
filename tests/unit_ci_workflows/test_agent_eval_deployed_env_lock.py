# case_ids: HR-003, AS-003, OR-014, PR-017
"""`agent-eval` 的**已部署环境覆盖面锁**（issue #4821 的收口口径）—— L0（零 LLM、零 docker）。

## 本文件锁的是 #4821 核清后的**结论**，不是一次实现

#4821 的原始假设是「耗时严格串行 ⇒ 唯一杠杆是并发 ⇒ 前置 = 每次跑完即销毁的隔离栈」。
核清后**假设被两处修正**（逐条见 `docs/testing/eval-environments.md` §3.9）：

1. **「并发 6 省 83%」不成立**：那个 LPT 估算没把**隔离串行**算进去。用本 workflow 既有 run
   `34800764957` 的逐条 `⏱ <ID> start=` 耗时代入 `tests/agent_eval/local_runner.py` 的
   `serialize_seconds`（含隔离语义），可比子集（**62 条**）的下界是 **2873s → 1230s（≈57%）**，且下界由
   **独占串行道**顶着（≈43% 墙钟，与并发度无关）。**未真跑**（#4262 不派发真实 LLM 评测）。
   （订正记录：该 run 的 `⏱ start=` 集 ≡ `✅/❌` 集 = **69 条**，旧读数的「70 条 ⇒ 63 条可比子集」
   记高一，派生量随之订正为 62 条 / 1230s；复算命令见 `docs/testing/eval-environments.md` §3.9 ②。）
2. 🔴 **本 workflow 的耗时是一层覆盖面的价格**：它的 `AI_API_URL` / `ADMIN_API_URL` 指向
   **已部署**的云测试环境；同族的 `post-deploy-eval.yml` / `xiaobu-acceptance.yml` 跑的
   **都是本地临时栈**（`http://localhost:8001` + `Start local stack`）⇒
   「**部署出去的那一份**」的 normal 全量**只有本入口在跑**。把它改成隔离栈 =
   既丢掉这一层、又变成 post-deploy-eval mibao 腿的同构副本（净减覆盖 + 重复付费）。
   ⇒ 维护者裁定（2026-09-21）：**不改环境语义**；覆盖面变更（要不要砍/搬这一层）留给业务
   裁定（见 issue #4824）。
3. 但**共享环境不可安全并发**（normal 档含建品/下单/改客户等写用例；假失败会经失败步骤落进
   issue 台账，且 `flaky-triage.yml` 的 `workflow_run` 白名单**不含**本 workflow ⇒
   不会被自动重跑兜住）⇒ 本入口**保持严格串行**，`EVAL_CONCURRENCY` 有意**不设**。

## 为什么这些判据必须有（否则「静默丢一层覆盖面」没有任何东西会红）

「把评测换成临时栈」在**其它任何检查里都长得像一次正常重构**：用例数不变、命令不变、
`schema_integrity` 不红、`test_eval_stack_seed_parity` 也不红（它只管**起栈的那些** workflow）。
唯一能看见"已部署那一份没人测了"的地方，就是本文件的第 ① ② 条。

## 每条断言都有**注入式反向红证**（判据本体是纯函数，注入坏形态后必须变红）

| # | 不变式 | 注入的坏形态（⇒ 必红） |
|---|---|---|
| ① | 打**已部署**环境（不是本地栈） | `AI_API_URL: http://localhost:8001` |
| ② | 覆盖面不收窄（同一条 `normal --cases .github/cases`） | 加 `--case-ids` / 加 `--shard` / `normal`→`smoke` |
| ③ | 共享环境**不开并发** | 评测步骤注入 `EVAL_CONCURRENCY: "6"` |
| ④ | 栈机件 ⇔ 家族登记（不许"半改造"藏身处） | 注入 `docker compose` 起栈步骤而不登记 |
| ⑤ | 非内置 secrets 引用**只增不免审** | 注入 `secrets.DEEPSEEK_API_KEY` |
| ⑥ | 仍**仅手动**触发（#4262） | 注入 `schedule:` |
| ⑦ | #4821 结论**留痕**不许被静默删除 | 删掉 `#4821` 结论块 |
| ⑧ | 分道不丢用例（若将来启用隔离模式） | 把撞车用例从两条道里"优化"掉 |
| ⑨ | 缺省并发仍回落 1（"配置丢失 = 变慢"） | 把 runner 缺省 `"1"` 抬成 `"6"` |

⚠️ 未真跑登记：本文件**不**声称并发下的"假失败 0"已验证，也不声称 §3.9 的推演是实测。
"""
import ast
import re
import sys
import types
import importlib.util
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"
PARITY_PATH = Path(__file__).resolve().parent / "test_eval_stack_seed_parity.py"
WORKFLOW = "agent-eval.yml"

# 本 workflow **已被审查过**的 secrets 引用集合（= Danger Scan 的 L0 等价物）。
# 新增任何非内置 secrets 引用都必须显式改这里 ⇒ 逼出"有意识的动作 + 有人看"
# （`.github/danger_scan.py` 对「改已有 workflow 且新增 secrets 引用」是**硬 BLOCK**，
#  且 secrets 没有 ack 通道 —— 只有删 workflow 才有 `/danger-ack delete-workflow`）。
ALLOWED_SECRETS = frozenset({"SMOKE_SERVICE_TOKEN"})
EVAL_CMD_RE = re.compile(r"local_runner\.py\s+(\S+)\s+--cases\s+(\S+)")
SECRET_REF_RE = re.compile(r"secrets\.([A-Za-z0-9_]+)")
# 已部署环境的判定：本地栈一律是 localhost/127.0.0.1
LOCAL_HOST_RE = re.compile(r"(localhost|127\.0\.0\.1)")
# 起栈机件的形态判据（与 test_eval_stack_seed_parity.py 的白名单语义同源：谁起栈谁登记）
STACK_MARKERS = ("docker compose", "docker-compose", "Start local stack")
# 家族登记锚（都在 test_eval_stack_seed_parity.py 里定义 —— 本文件只**读**它的真值，不复制规则）
FAMILY_CONSTANTS = ("EVAL_WORKFLOWS", "EVAL_JOB", "PERSONA_SOURCE")


# ── 载入 ────────────────────────────────────────────────────────────────────

def _load_workflow() -> dict:
    return yaml.safe_load((WORKFLOWS_DIR / WORKFLOW).read_text(encoding="utf-8")) or {}


def _steps(wf: dict) -> list:
    out = []
    for job in (wf.get("jobs") or {}).values():
        out.extend(job.get("steps") or [])
    return out


def _eval_step(wf: dict) -> dict:
    steps = [s for s in _steps(wf)
             if "local_runner" in ((s.get("name") or "") + (s.get("run") or ""))]
    assert len(steps) == 1, f"{WORKFLOW} 的评测步骤应唯一，实测 {len(steps)} 个"
    return steps[0]


def _triggers(wf: dict) -> dict:
    return wf.get("on") or wf.get(True) or {}


def _family_registrations() -> dict:
    """读同目录守卫文件里的**三处登记真值**（**不复制规则**）。

    `EVAL_WORKFLOWS` 在模块级；`EVAL_JOB` / `PERSONA_SOURCE` 是测试类的属性
    （分别是"槽位持有者"与"种子 persona 来源"两张按 workflow 索引的表）。
    """
    spec = importlib.util.spec_from_file_location("_mg_eval_parity", PARITY_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {
        "EVAL_WORKFLOWS": tuple(getattr(mod, "EVAL_WORKFLOWS")),
        "EVAL_JOB": tuple(getattr(getattr(mod, "TestEvalConcurrencySlot"), "EVAL_JOB")),
        "PERSONA_SOURCE": tuple(getattr(getattr(mod, "TestNoMixedPersonaStack"), "PERSONA_SOURCE")),
    }


# ── 判据本体（纯函数：输入 = 解析后的 workflow，便于注入式红证）──────────────

def audit_deployed_env(wf: dict) -> list:
    """① 评测打的是**已部署**环境（不是本地临时栈）。"""
    problems = []
    env = _eval_step(wf).get("env") or {}
    for key in ("AI_API_URL", "ADMIN_API_URL"):
        val = str(env.get(key) or "")
        if not val:
            problems.append(f"评测步骤缺 {key} —— 无从判定打的是哪套环境")
            continue
        if LOCAL_HOST_RE.search(val):
            problems.append(
                f"{key}={val!r} 指向**本地栈** —— 本入口的独一无二价值是"
                "「**部署出去的那一份**」的 normal 全量（同族另两处都跑本地临时栈）；"
                "改成本地栈 = 净减一层覆盖面 + 变成 post-deploy-eval mibao 腿的同构副本"
                "（#4821 裁定：不改环境语义）"
            )
        elif not val.startswith("https://"):
            problems.append(f"{key}={val!r} 不是 https 云地址 —— 无法认定它打的是已部署环境")
    return problems


def _strip_comments(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def audit_coverage_not_narrowed(wf: dict) -> list:
    """② 覆盖面不收窄：命令恒为 `normal --cases .github/cases`。"""
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
                f"评测命令出现 {banned} —— 「不许减少评测轮数/用例」："
                "任何改造只许改变「同时跑几条/何时跑」，不许改变「跑什么、判什么」"
            )
    return problems


def audit_no_concurrency_on_shared_env(wf: dict) -> list:
    """③ 共享环境**不得**开用例级并发（并发写同一套共享 dev 库会互相污染）。"""
    problems = []
    env = _eval_step(wf).get("env") or {}
    if "EVAL_CONCURRENCY" in env:
        problems.append(
            f"评测步骤设了 EVAL_CONCURRENCY={env['EVAL_CONCURRENCY']!r} —— 本入口打的是"
            "**共享环境**（写用例会互相污染且加速污染 dev 库；假失败还会落进失败建 issue 的"
            "台账，而 flaky-triage 的白名单不含本 workflow ⇒ 不会被重跑兜住）"
            "⇒ 必须保持严格串行（有意不设该变量 = runner 缺省 1）"
        )
    return problems


def audit_stack_machinery_matches_registration(wf: dict, regs: dict) -> list:
    """④ 栈机件 ⇔ 家族登记：**不许"半改造"**（起了栈却不进白名单 = 判据盲区）。"""
    body = "\n".join((s.get("run") or "") + (s.get("name") or "") for s in _steps(wf))
    has_stack = any(m in body for m in STACK_MARKERS)
    problems = []
    for name, members in sorted(regs.items()):
        registered = WORKFLOW in tuple(members)
        if has_stack and not registered:
            problems.append(
                f"{WORKFLOW} 有起栈机件却**不在** `{name}` 里 —— "
                "白名单的语义是「谁起栈谁登记」：不登记 ⇒ 种子/旋钮/单 persona/种子先于评测"
                "四条判据全部不覆盖它（= 拿白名单当藏身处）"
            )
        if registered and not has_stack:
            problems.append(
                f"{WORKFLOW} 在 `{name}` 里却**没有**起栈机件 —— "
                "登记与实际不符（要么把机件补回、要么把它移出该表）"
            )
    return problems


def audit_no_new_secret_refs(source: str) -> list:
    """⑤ 非内置 secrets 引用必须落在**已审查集合**里（Danger Scan 的 L0 等价物）。"""
    problems = []
    found = set(SECRET_REF_RE.findall(source)) - {"GITHUB_TOKEN"}
    extra = sorted(found - ALLOWED_SECRETS)
    if extra:
        problems.append(
            f"{WORKFLOW} 新增/存在未审查的非内置 secrets 引用 {extra} —— "
            "`.github/danger_scan.py` 对「改已有 workflow 且新增 secrets 引用」是**硬 BLOCK**"
            "（secrets 无 ack 通道）；确实需要时请显式改本文件的 ALLOWED_SECRETS 并走人工审查"
        )
    return problems


def audit_manual_only(wf: dict) -> list:
    """⑥ 仍**仅手动**（#4262：全仓自动真实 LLM 触发只允许 1 条）。"""
    keys = sorted(_triggers(wf))
    if keys != ["workflow_dispatch"]:
        return [f"{WORKFLOW} 的触发面 = {keys} —— 必须仍为仅手动（#4262）"]
    return []


def audit_closeout_record_present(source: str) -> list:
    """⑦ #4821 的结论必须**留痕**（否则下一个人会把同一份核清重做一遍）。"""
    problems = []
    for marker, why in (
        ("#4821", "#4821 的结论锚（谁核清的、结论是什么）"),
        ("EVAL_CONCURRENCY", "「并发有意不设」的说明"),
    ):
        if marker not in source:
            problems.append(f"{WORKFLOW} 缺 {why}（marker={marker!r}）—— 结论被静默删除")
    return problems


# ── runner 侧判据（读源/AST，便于注入式红证）────────────────────────────────

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


def audit_runner_default_is_serial(source: str) -> list:
    """runner 的缺省并发必须仍回落 1（"配置丢失 = 变慢"，不是"静默开并发"）。"""
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
    """⑧ 分道不丢用例：`parallel ∪ serial == 全量`（将来若启用隔离模式，覆盖面不变）。"""
    problems = []
    ns = runner.namespace_conflict_groups(cases)
    conflicted = {i for g in ns.values() for i in g}
    parallel = [c for c in cases if not runner.needs_serial_lane(c, conflicted)]
    serial = [c for c in cases if runner.needs_serial_lane(c, conflicted)]
    lane_ids = sorted([c.id for c in parallel] + [c.id for c in serial])
    all_ids = sorted(c.id for c in cases)
    if lane_ids != all_ids:
        lost = sorted(set(all_ids) - set(lane_ids))
        problems.append(
            f"分道丢/重用例：缺 {lost[:8]}（共 {len(lost)} 条）—— "
            "并发分道必须恰好覆盖全量（覆盖面无条件不缩水）"
        )
    return problems


# ── 测试：workflow 侧 ───────────────────────────────────────────────────────

def test_eval_targets_the_deployed_environment():
    assert audit_deployed_env(_load_workflow()) == []


def test_red_proof_switching_to_local_stack_reds():
    """反向红证 ①：把它改成打本地栈 ⇒ 必须变红（这正是"静默丢一层覆盖面"的形态）。"""
    wf = _load_workflow()
    _eval_step(wf)["env"]["AI_API_URL"] = "http://localhost:8001"
    problems = audit_deployed_env(wf)
    assert problems and "本地栈" in problems[0], problems


def test_coverage_is_not_narrowed():
    assert audit_coverage_not_narrowed(_load_workflow()) == []


@pytest.mark.parametrize("banned", ["--case-ids OR-001", "--shard 0/2"])
def test_red_proof_narrowing_command_reds(banned):
    """反向红证 ②：收窄/分片 ⇒ 必须变红。"""
    wf = _load_workflow()
    _eval_step(wf)["run"] = _eval_step(wf)["run"] + f" {banned}"
    assert audit_coverage_not_narrowed(wf), f"加了 {banned} 后判据仍绿 —— 覆盖面缩水无人拦"


def test_red_proof_tier_change_reds():
    """反向红证 ②：改档 = 改跑什么 ⇒ 必须变红。"""
    wf = _load_workflow()
    _eval_step(wf)["run"] = _eval_step(wf)["run"].replace(" normal --cases", " smoke --cases")
    problems = audit_coverage_not_narrowed(wf)
    assert problems and "档位" in problems[0], problems


def test_no_concurrency_on_the_shared_environment():
    assert audit_no_concurrency_on_shared_env(_load_workflow()) == []


def test_red_proof_concurrency_on_shared_env_reds():
    """反向红证 ③：在共享环境入口上开并发 ⇒ 必须变红。"""
    wf = _load_workflow()
    _eval_step(wf)["env"]["EVAL_CONCURRENCY"] = "6"
    problems = audit_no_concurrency_on_shared_env(wf)
    assert problems and "共享环境" in problems[0], problems


def test_stack_machinery_matches_family_registration():
    wf = _load_workflow()
    assert audit_stack_machinery_matches_registration(wf, _family_registrations()) == []


def test_red_proof_half_conversion_reds():
    """反向红证 ④：起了栈却不登记（"半改造"= 判据盲区）⇒ 必须变红。"""
    wf = _load_workflow()
    _eval_step(wf)["run"] = (
        "docker compose -f deploy/docker-compose.yml up -d --wait\n"
        + (_eval_step(wf).get("run") or "")
    )
    problems = audit_stack_machinery_matches_registration(wf, _family_registrations())
    assert problems and "谁起栈谁登记" in problems[0], problems


def test_red_proof_registered_without_machinery_reds():
    """反向红证 ④的镜像：登记了却没有栈机件（登记与实际不符）⇒ 必须变红。"""
    wf = _load_workflow()
    regs = _family_registrations()
    regs["EVAL_WORKFLOWS"] = tuple(regs["EVAL_WORKFLOWS"]) + (WORKFLOW,)
    problems = audit_stack_machinery_matches_registration(wf, regs)
    assert problems and "登记与实际不符" in problems[0], problems


def test_no_unreviewed_secret_references():
    assert audit_no_new_secret_refs(
        (WORKFLOWS_DIR / WORKFLOW).read_text(encoding="utf-8")
    ) == []


def test_red_proof_new_secret_reference_reds():
    """反向红证 ⑤：新增非内置 secrets 引用 ⇒ 必须变红（= Danger Scan 会 BLOCK 的形态）。"""
    src = (WORKFLOWS_DIR / WORKFLOW).read_text(encoding="utf-8")
    # 注入形态 = **真实引用行**（与 Danger Scan 的判据同形：它只看"含 secrets. 的新增行"）
    injected = src + "\n          PRIMARY_API_KEY: ${{ secrets.DEEPSEEK_API_KEY || 'ci-dummy' }}\n"
    problems = audit_no_new_secret_refs(injected)
    assert problems and "DEEPSEEK_API_KEY" in problems[0], problems


def test_red_proof_schedule_injection_reds():
    """反向红证 ⑥：加自动触发 ⇒ 必须变红（#4262）。"""
    wf = _load_workflow()
    wf[True] = dict(_triggers(wf))
    wf[True]["schedule"] = [{"cron": "0 3 * * 1"}]
    problems = audit_manual_only(wf)
    assert problems and "仅手动" in problems[0], problems


def test_closeout_record_present():
    assert audit_closeout_record_present(
        (WORKFLOWS_DIR / WORKFLOW).read_text(encoding="utf-8")
    ) == []


def test_red_proof_stripping_closeout_record_reds():
    """反向红证 ⑦：删掉 #4821 结论块 ⇒ 必须变红。"""
    src = (WORKFLOWS_DIR / WORKFLOW).read_text(encoding="utf-8")
    stripped = "\n".join(l for l in src.splitlines() if "#4821" not in l)
    problems = audit_closeout_record_present(stripped)
    assert problems and "#4821" in problems[0], problems


# ── 测试：runner 侧（零 LLM，读源 + 真实用例库）────────────────────────────

def test_selection_functions_do_not_take_concurrency():
    assert audit_selection_ignores_concurrency(RUNNER_PATH.read_text(encoding="utf-8")) == []


def test_red_proof_selection_taking_concurrency_reds():
    """反向红证：让选题函数吃并发参数 ⇒ AST 判据必须变红。"""
    problems = audit_selection_ignores_concurrency(
        "x = select_cases_for_persona(cases, PERSONA, concurrency)\n"
    )
    assert problems and "参与了选题" in problems[0], problems


def test_runner_keeps_serial_default():
    assert audit_runner_default_is_serial(RUNNER_PATH.read_text(encoding="utf-8")) == []


def test_red_proof_default_concurrency_raised_reds():
    """反向红证 ⑨：把 runner 缺省并发从 1 抬到 6 ⇒ 必须变红。"""
    src = RUNNER_PATH.read_text(encoding="utf-8").replace(
        'os.environ.get("EVAL_CONCURRENCY", "1")', 'os.environ.get("EVAL_CONCURRENCY", "6")'
    )
    problems = audit_runner_default_is_serial(src)
    assert problems and "回落" in problems[0], problems


@pytest.mark.parametrize("persona", ["mibao", "xiaobu"])
def test_lane_split_covers_every_case(persona):
    """⑧ 分道不丢用例（真实用例库 + 真实分道判据，两条 persona 腿各判一次）。"""
    runner = _load_runner()
    cases = runner.load_cases_from_yaml(str(REPO_ROOT / ".github" / "cases"))
    sel = runner.select_cases_for_persona(cases, persona)
    normal = [c for c in sel if c.difficulty == runner.Difficulty.NORMAL and not c.skip_reason]
    assert normal, f"persona={persona} 的 normal 档用例集为空（守卫前提失效）"
    assert audit_lane_union(runner, normal) == []


def test_red_proof_dropped_lane_case_reds():
    """反向红证 ⑧：串行道"只挑不撞车的" = 丢掉争用用例 ⇒ 分道判据必须变红。

    判据按**全量**比对（不是"分道自洽"），故先证：变异确实少了用例。
    """
    runner = _load_runner()
    cases = runner.load_cases_from_yaml(str(REPO_ROOT / ".github" / "cases"))
    normal = [c for c in runner.select_cases_for_persona(cases, "mibao")
              if c.difficulty == runner.Difficulty.NORMAL and not c.skip_reason]
    ns = runner.namespace_conflict_groups(normal)
    conflicted = {i for g in ns.values() for i in g}
    assert conflicted, "前提：真实用例库里确实存在命名空间争用用例"
    pruned = [c for c in normal if c.id not in conflicted]
    assert {c.id for c in normal} - {c.id for c in pruned}, "变异必须真的少了用例（否则红证是空的）"
    # 变异后的分道自身自洽（这正是"看起来没问题"的形态）⇒ 判据的价值在于按全量比对
    assert audit_lane_union(runner, pruned) == []
    assert audit_lane_union(runner, normal) == []


def test_plan_case_count_is_invariant_to_concurrency():
    """若将来启用隔离模式：`serialize_seconds` 的 `cases` 不随并发度变化 = 并发不改"跑什么"。

    （⚠️ 该模型的 `wall_s` 在 k=1 时**不代表**真实串行墙钟 —— 它假设并行道与串行道可重叠；
    真实串行墙钟 = 各条耗时之和，见 `docs/testing/eval-environments.md` §3.9 的推演。
    故这里只断言**条数不变**，且**不**据此声称任何提速已实测。）
    """
    runner = _load_runner()
    cases = runner.load_cases_from_yaml(str(REPO_ROOT / ".github" / "cases"))
    normal = [c for c in runner.select_cases_for_persona(cases, "mibao")
              if c.difficulty == runner.Difficulty.NORMAL and not c.skip_reason]
    durations = {c.id: 25.0 for c in normal}          # 合成耗时：只判条数不变量
    counts = {runner.serialize_seconds(normal, durations, k)["cases"] for k in (1, 2, 3, 6, 8, 12)}
    assert counts == {len(normal)}, (
        f"并发度改变了计划里的用例条数：{counts} vs {len(normal)} —— 并发动了覆盖面"
    )
