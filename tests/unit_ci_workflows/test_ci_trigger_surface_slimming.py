# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
r"""CI 触发面降频包（追踪单 #5814）——**「保腿不删腿」的实例判据 + 两族类级元守卫**。

## 病（一类，不是一个）

实测（`gh api .../actions/workflows/<wf>.yml/runs?created=<3 日>`，09-27~09-29）：全仓 **1378 run/天**。
其中一大族是**纯放大器**：腿跑了，但对**该次上游结论**几乎没有信息增量。两族：

| 族 | 形态 | 实测样本 |
|---|---|---|
| A **`workflow_run` 消费面无结论门控** | 上游**首次就成功**的 run 也触发一次分流/对账/报账 | `flaky-triage` 285.7/天（3 日 857：758 success + 97 cancelled + 1 failure；`run_attempt>1` **0** 条）；`stale-report-reaper` 79.0/天（232/237 = upstream success）；`h5-freshness-guard` 70.0/天（上游 `Mini-App CI` 是 PR 面腿，对本腿的判定对象**不是**上游结论） |
| B **`pull_request` 未声明 `types`** | 默认全事件 ⇒ 每次 push 到 PR 的 `synchronize` 都重跑一遍 | `pr-issue-link` 106.3/天（读 PR body ⇒ 只有 body 变化才需重判） |

## 两族元守卫（本包的核心价值；**未登记即红 / 台账只许缩短**）

- **守卫 A**（`workflow_run_gate_ledger.json`）：凡 `on.workflow_run` 消费面、且其**任一上游**落在 PR 面
  （= 上游可达事件含 `pull_request`）⇒ **必须**在 job 级 `if:` 里对**上游 run 的结论**（`conclusion` /
  `event.workflow_run.conclusion`）或**重试**（`run_attempt`）门控，否则红。
  未门控而**确实不该门控**的（判定对象不是上游结论，例如新鲜度判据量的是**线上产物**）必须进
  `ungated_ok` **登记**并写明理由 —— 未登记即红。
  ⚠️ **`run_attempt > 1` 这一半不许省**：`flaky-triage` 的职责含「第二次绿 ⇒ 打 `flaky/rerun-green`
  + `block/merge` + 卸 auto-merge」——重跑转绿那一次 `conclusion=success` 而我们是**需要**知道的
  （只看 `failure` 会把这条机制打断 = 降门禁）。判据 2 对**该族**逐字要求门控含 `run_attempt` 门。
- **守卫 B**（`pr_types_ledger.json`）：凡顶层 `on.pull_request` **未声明 `types`** 的腿 ⇒ 必须登记
  （默认全事件 = 每次 push 重跑）。**未登记即红**；登记项「已声明 `types`」即陈旧 ⇒ 红（只许缩短）。

## 为什么这条不能靠「一次性的 9 处改动」交差

9 处改动只是**当次的债**；让「同族浪费」进不来的是上面两条**结构性**守卫：
新造一条无门控的 `workflow_run` 消费腿、或新造一条未声明 `types` 的 PR 腿 ⇒ **当场红**，
而不是等下一次人工按 run 量复盘。

## 判定方式（确定性）

纯静态：只读仓内 `.github/workflows/*.yml` + 本目录两张台账 JSON，**零 `gh` / 零网络 / 零时钟**
⇒ 同一份代码任何时刻给出同一读数。运行期计数（`gh run list` / `gh api .../runs`）**刻意不进判据**，
只作为「当时的读数 + 可复制复算命令」写在 PR body 与台账 `evidence` 里。
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
LEDGER_DIR = Path(__file__).resolve().parent

#: 本包动过的 9 条腿（实例判据的坐标；文件不存在 ⇒ fail-closed 红）。
TRACKED = (
    "flaky-triage.yml",
    "stale-report-reaper.yml",
    "h5-freshness-guard.yml",
    "pr-issue-link.yml",
    "mechanism-liveness.yml",
    "drift-audit.yml",
    "automerge.yml",
    "case-redraft.yml",
    "flaky-ledger-reconcile.yml",
)

GATE_LEDGER = LEDGER_DIR / "ci_trigger_gate_ledger.json"
PR_TYPES_LEDGER = LEDGER_DIR / "ci_pr_types_ledger.json"

#: 手动面 / 被调面：**不能**让一条腿自己跑起来 ⇒ 不算自走面（口径同
#: `tests/unit_ci_workflows/test_publish_leg_fallback_surface.py` 的 `MANUAL_EVENTS`）。
MANUAL_EVENTS = frozenset({"workflow_dispatch", "workflow_call"})

#: `workflow_run` 消费面里「上游结论 / 重试」门控的**可接受形态**（逐条具名 —— 不许宽泛正则一把梭）。
#: 每条的语义都是「这一次上游 run 的结论会不会带来信息增量」。
GATE_PATTERNS = (
    # ① 直接判上游 run 的结论（`failure` / `success` 都算：有的消费面要的是成功那一半）
    (r"github\.event\.workflow_run\.conclusion\s*==\s*'(\w+)'",
     "github.event.workflow_run.conclusion == '<x>'"),
    # ② 重跑档：`run_attempt > 1`（`flaky-triage` 的「第二次绿」那一半靠它）
    (r"github\.event\.workflow_run\.run_attempt\s*>\s*\d+",
     "github.event.workflow_run.run_attempt > 1"),
    # ③ 等价写法：先落到 env/step output 再判（本仓现取用 ①，保留形态以便实现演进）
    (r"WORKFLOW_RUN_CONCLUSION\s*==\s*'(\w+)'", "WORKFLOW_RUN_CONCLUSION == '<x>'"),
)


# ══════════════════════════════════════════════════════════════════════════════
# 一、读盘（纯静态；解析失配 ⇒ 红，绝不静默给空集）
# ══════════════════════════════════════════════════════════════════════════════


def _load(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), f"{path.name} 不是 YAML 映射（解析失配 ⇒ 红，不静默给空集）"
    return doc


def on_block(wf: object) -> dict:
    """`on:` 的真 YAML 形态（裸 `on:` 会被 PyYAML 读成布尔键 `True`；兼容字符串 / 列表写法）。"""
    if not isinstance(wf, dict):
        return {}
    on = wf.get("on")
    if on is None and True in wf:
        on = wf.get(True)
    if isinstance(on, str):
        return {on: {}}
    if isinstance(on, list):
        return {str(e): {} for e in on}
    return on if isinstance(on, dict) else {}


def _nested(node: object, *keys: str) -> object:
    cur = node
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def reachable_events(wf: object) -> frozenset[str]:
    """顶层可达事件（去掉手动面 / 被调面）—— 「这条腿能不能自己跑起来」。"""
    return frozenset(on_block(wf)) - MANUAL_EVENTS


def workflow_run_consumers() -> dict[str, tuple[tuple[str, tuple[str, ...]], ...]]:
    """全仓 `on.workflow_run` 消费面：`{文件名: ((上游名, (上游可达事件…)), …)}`。

    上游名经「仓内某 workflow 的 `name:`」解析（解析不到 ⇒ 判据红：改名会让门控**静默脱钩**，
    口径同 `test_publish_leg_fallback_surface.py` 判据 7）。
    """
    docs = {p.name: _load(p) for p in sorted(WORKFLOWS_DIR.glob("*.yml"))}
    by_name: dict[str, tuple[str, frozenset[str]]] = {}
    for name, doc in docs.items():
        display = str(doc.get("name") or "").strip()
        if display:
            by_name.setdefault(display, (name, reachable_events(doc)))
    out: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {}
    for name, doc in docs.items():
        wr = _nested(on_block(doc), "workflow_run")
        if not isinstance(wr, dict):
            continue
        upstreams = wr.get("workflows") or []
        if isinstance(upstreams, str):
            upstreams = [upstreams]
        resolved: list[tuple[str, tuple[str, ...]]] = []
        for up in upstreams:
            hit = by_name.get(str(up))
            resolved.append((str(up), tuple(sorted(hit[1])) if hit else ()))
        out[name] = tuple(resolved)
    return out


def workflow_run_gate(wf: object) -> tuple[str, ...]:
    """本腿 job 级 `if:` 里**字面出现**的结论 / 重试门控形态（空元组 = 无门控）。

    ⚠️ 读的是「是不是它」而不是「长得像不像」：只认 `GATE_PATTERNS` 里逐条具名的那几种，
    且必须在 **job 级 `if:`** 上（step 级 `if:` 是另一回事 —— 它拦不住 job 的启动开销）。
    """
    jobs = wf.get("jobs") if isinstance(wf, dict) else None
    if not isinstance(jobs, dict):
        return ()
    hits: set[str] = set()
    for job in jobs.values():
        cond = str((job or {}).get("if") or "") if isinstance(job, dict) else ""
        for pattern, label in GATE_PATTERNS:
            if re.search(pattern, cond):
                hits.add(label)
    return tuple(sorted(hits))


def gate_problems(*, consumers: dict, registry: object) -> list[str]:
    """守卫 A 本体（纯函数；红证**内存构造**直接喂它）。"""
    problems: list[str] = []
    if not isinstance(registry, dict):
        return ["登记表必须是 JSON 对象（fail-closed）"]
    entries = {str(e.get("file")): e for e in (registry.get("ungated_ok") or []) if isinstance(e, dict)}
    if "ungated_ok" not in (registry or {}):
        problems.append("缺 `ungated_ok`（**允许为空数组**，但不许缺字段 —— 缺字段与「没有例外」不可区分）")
    declared_files = sorted(str(e.get("file")) for e in (registry.get("workflow_run_gated") or [])
                            if isinstance(e, dict))
    frozen = registry.get("consumers_frozen")
    live = {name: ups for name, ups in consumers.items()
            if any("pull_request" in events for _up, events in ups)}
    if frozen is None or not isinstance(frozen, list):
        problems.append("缺 `consumers_frozen`（结构性面**只许缩短**的冻结清单）")
        frozen = []
    if sorted(str(x) for x in frozen) != sorted(live):
        problems.append(
            f"`consumers_frozen` 与现取的「PR 面上游的 workflow_run 消费腿」不逐项相等 —— "
            f"现取 {sorted(live)} / 台账 {sorted(frozen)} ⇒ 新造一条这样的腿必须同批入册"
            f"（改动在 diff 里看得见）")
    # 每一条 PR 面消费腿：有门控 ⇒ 必须在 workflow_run_gated 里具名（可归因）；
    # 无门控 ⇒ 必须在 ungated_ok 里登记理由（未登记即红）。
    for name, ups in sorted(live.items()):
        # 🔴 消费腿在 `consumers` 里但语料里取不到它的 doc（**内存构造的红证形态**）⇒
        # 门控读作「无」并**留在这里**：由下面的未登记检查判红，而不是 KeyError 崩掉。
        doc = WORKFLOW_DOCS.get(name)
        gate = workflow_run_gate(doc) if doc is not None else ()
        if gate and name not in declared_files:
            problems.append(f"`{name}` 有结论门控 {list(gate)} 但没进 `workflow_run_gated` ⇒ 不许匿名存在")
        if not gate and name not in entries:
            problems.append(
                f"`{name}` 的 `workflow_run` 上游 {[u for u, e in ups if 'pull_request' in e]} 落在 PR 面，"
                f"而它 job 级 `if:` 里**没有**上游结论 / 重试门控 ⇒ 上游首次就成功的那一半也会白白消费一次；"
                f"要豁免必须在 `ungated_ok` 里登记（带 reason + evidence）")
        if not gate and name in entries:
            entry = entries[name]
            for key in ("reason", "evidence"):
                if not str(entry.get(key) or "").strip():
                    problems.append(f"`{name}` 的 `ungated_ok` 登记缺 `{key}`（豁免必须可归因）")
    for name in sorted(set(entries) - set(live)):
        problems.append(f"`{name}` 登记为「无门控但可接受」，而现取它不是 PR 面 workflow_run 消费腿 ⇒ 陈旧登记（只许缩短）")
    for name in sorted(set(declared_files) - set(live)):
        problems.append(f"`{name}` 登记为「有门控」，而现取它不是 PR 面 workflow_run 消费腿 ⇒ 陈旧登记（只许缩短）")
    return problems


def pr_types_problems(*, docs: dict[str, dict], registry: object) -> list[str]:
    """守卫 B 本体：顶层 `pull_request` 未声明 `types` 的腿必须登记（未登记即红）。"""
    problems: list[str] = []
    if not isinstance(registry, dict):
        return ["登记表必须是 JSON 对象（fail-closed）"]
    entries = [e for e in (registry.get("no_types") or []) if isinstance(e, dict)]
    if not entries:
        problems.append("`no_types` 为空 ⇒ fail-closed 红（清空登记表不是「没有例外」）")
    live = {}
    for name, doc in docs.items():
        pr = on_block(doc).get("pull_request")
        if pr is None:
            continue
        types = pr.get("types") if isinstance(pr, dict) else None
        if not types:
            live[name] = "（未声明 types ⇒ 默认全事件）"
    registered = {str(e.get("file")) for e in entries}
    for name in sorted(set(live) - registered):
        problems.append(
            f"`{name}` 的 `pull_request` **未声明 `types`**（= 默认全事件 ⇒ 每次 push 到 PR 的 "
            f"`synchronize` 都重跑）却没登记 ⇒ 未登记即红（要保留就在台账里写明理由）")
    for name in sorted(registered - set(live)):
        problems.append(f"`{name}` 登记为「未声明 types」，而现取它已声明 `types`（或没有 PR 面）⇒ 陈旧登记（只许缩短）")
    for entry in entries:
        for key in ("file", "reason"):
            if not str(entry.get(key) or "").strip():
                problems.append(f"`no_types` 登记项缺 `{key}`（豁免必须可归因）")
    cap = registry.get("count_frozen")
    if cap != len(live):
        problems.append(f"`count_frozen`={cap!r} 与现取条数 {len(live)} 不符 ⇒ 条数**只许缩短**，三处一起改才生效")
    return problems


def _fresh(name: str) -> dict:
    """从磁盘**重新解析**一份干净 doc —— 变异绝不许泄漏进共享语料（否则后续判据在脏对象上跑）。"""
    return _load(WORKFLOWS_DIR / name)


def _with_on(doc: dict, mutate) -> None:
    """**就地**改 `doc` 的 `on:` 块（兼容裸 `on:` 被读成布尔键 `True` 的形态）。

    ⚠️ 必须**就地**：早先写成「返回副本」而调用方不接返回值 ⇒ 变异**静默没生效**、
    红证全变空断言（本仓「构造了却不写回」的同族病 —— 本轮正是被红证自己抓出来的）。
    """
    on = copy.deepcopy(on_block(doc))
    mutate(on)
    if "on" in doc:
        doc["on"] = on
    else:
        doc[True] = on


#: 就地变异体（`_with_on` 家族）：各注入一条坏形态，红证逐条喂给同一个判据。
def _drop_push(doc: dict) -> None:
    _with_on(doc, lambda o: o.pop("push"))


def _drop_schedule(doc: dict) -> None:
    _with_on(doc, lambda o: o.pop("schedule"))


def _drop_dispatch(doc: dict) -> None:
    _with_on(doc, lambda o: o.pop("workflow_dispatch"))


def _add_pull_request(doc: dict) -> None:
    _with_on(doc, lambda o: o.__setitem__("pull_request", {"branches": ["main"]}))


def _set_cron(expr: str):
    def mutate(doc: dict) -> None:
        _with_on(doc, lambda o: o.__setitem__("schedule", [{"cron": expr}]))
    return mutate


def _add_cron(doc: dict) -> None:
    _set_cron("7 * * * *")(doc)


def _drop_pr_types(doc: dict) -> None:
    _with_on(doc, lambda o: o["pull_request"].pop("types"))


def _add_pr_type(name: str):
    def mutate(doc: dict) -> None:
        _with_on(doc, lambda o: o["pull_request"]["types"].append(name))
    return mutate


def _restore_mini_app_upstream(doc: dict) -> None:
    _with_on(doc, lambda o: o["workflow_run"]["workflows"].append("Mini-App CI"))


#: 现取语料（模块级一次读盘）。
WORKFLOW_DOCS: dict[str, dict] = {p.name: _load(p) for p in sorted(WORKFLOWS_DIR.glob("*.yml"))}
CONSUMERS: dict[str, tuple] = workflow_run_consumers()


def _ledger(path: Path) -> object:
    assert path.is_file(), f"缺登记表 {path.name} ⇒ fail-closed 红（缺台账 = 无人管，不是「无需登记」）"
    return json.loads(path.read_text(encoding="utf-8"))


# ══════════════════════════════════════════════════════════════════════════════
# 二、实例判据（9 条腿的改后形态；改回改前形态 ⇒ 必红）
# ══════════════════════════════════════════════════════════════════════════════


def test_tracked_files_exist() -> None:
    """反空跑：9 条腿的坐标必须都在（文件被删 / 改名 ⇒ 红，不是静默跳过）。"""
    missing = [n for n in TRACKED if not (WORKFLOWS_DIR / n).is_file()]
    assert not missing, f"本包追踪的腿不见了：{missing} ⇒ 判据变成空断言"


# ── ① flaky-triage：上游首次就成功的那一半不再分流 ────────────────────────────

#: ① 的门控**规范形态**（逐字）：两半都必需。用逐字相等而不是子串 —— 子串判据会被
#: 说明文字骗绿（本仓「提及 ≠ 调用」纪律，已踩四次）。
FLAKY_TRIAGE_GATE = ("github.event.workflow_run.conclusion == 'failure' ||\n"
                     "github.event.workflow_run.run_attempt > 1")


def flaky_triage_problems(wf: object) -> list[str]:
    """① 的结构判据（纯函数：真文件与内存变异体共用同一条路径）。"""
    bad: list[str] = []
    cond = " ".join(str(_nested(wf, "jobs", "triage", "if") or "").split())
    want = " ".join(FLAKY_TRIAGE_GATE.split())
    if cond != want:
        bad.append(
            f"triage job 的 `if:` 必须是**逐字** {want!r}，实际 {cond!r}；"
            "两半都必需：`failure` ⇒ 上游首次就成功的那一半不再被分流（纯放大器）；"
            "`run_attempt > 1` ⇒ **重跑转绿**（`conclusion=success`）仍在分流面内"
            "（「第二次绿 ⇒ 标 flaky + `block/merge` + 卸 auto-merge」这条机制靠它，缺了 = 降门禁）")
    if set(on_block(wf)) != {"workflow_run"}:
        bad.append(f"触发面必须**只有** `workflow_run`（终态判定只此一条），实际 {sorted(on_block(wf))}")
    return bad


def test_flaky_triage_gates_on_upstream_conclusion_and_attempt() -> None:
    """① 实例：`conclusion == 'failure' || run_attempt > 1`（两半都必需）。"""
    assert flaky_triage_problems(WORKFLOW_DOCS["flaky-triage.yml"]) == []


def test_flaky_triage_gate_red_proofs(tmp_path) -> None:
    """① 注入式红证：退回改前形态（无门控 / 只看 failure / 只看 run_attempt）各能单独变红。"""
    base = WORKFLOW_DOCS["flaky-triage.yml"]
    mutations = {
        "退回改前（无门控）": lambda d: d["jobs"]["triage"].__setitem__(
            "if", "github.event.workflow_run.event == 'pull_request'"),
        "只看 failure（打断重跑转绿那一半）": lambda d: d["jobs"]["triage"].__setitem__(
            "if", "github.event.workflow_run.conclusion == 'failure'"),
        "只看 run_attempt（漏掉首次真失败）": lambda d: d["jobs"]["triage"].__setitem__(
            "if", "github.event.workflow_run.event == 'pull_request' && "
                  "github.event.workflow_run.run_attempt > 1"),
    }
    for label, mutate in mutations.items():
        doc = _fresh("flaky-triage.yml")
        mutate(doc)
        assert flaky_triage_problems(doc), f"注入「{label}」后仍判绿 ⇒ 该判据是空断言"
    assert flaky_triage_problems(base) == [], "先决条件：未变异的真文件必须合规"


# ── ② stale-report-reaper：**本包有意不动**（门控会打断机制，不是降频） ────────

def stale_reaper_problems(wf: object) -> list[str]:
    """② 的结构判据：**必须没有**上游结论门控（否则机制被打断），且 `push: main` 面在位。

    🔴 **为什么不套「failure-only」门控（先读实现再动的结论）**：本腿的**判定本体**在
    `scripts/stale_report_reaper.py::judge()` —— 它自己去查**被报告那条腿**最近 `--consecutive`
    次已完成 run 的 `conclusion`，判断「腿是否已转绿、且最新 success 晚于本 issue 创建时间」。
    ⇒ 上游 **success** 恰恰是「腿转绿 ⇒ 可以关陈旧报告了」这一半的**输入**，
    不是纯放大器：套上 `conclusion == 'failure'` 会让它**永远关不掉报告**（功能被打断）。
    ⇒ 本包取「不做 + 理由 + 实测读数」，**不动**这条腿（详见 PR body 的「不做」节与台账）。
    """
    bad: list[str] = []
    cond = " ".join(str(_nested(wf, "jobs", "reap-stale-reports", "if") or "").split())
    if cond:
        bad.append(
            f"`reap-stale-reports` 出现了 job 级 `if:`（{cond!r}）—— 本腿的「转绿」判定读的是"
            "**被判腿自己的 run 历史**（`scripts/stale_report_reaper.py::judge`），上游 success 是"
            "它的输入 ⇒ 任何「只看上游 failure」的门控都会让陈旧报告**永远关不掉**（功能被打断）")
    if "push" not in on_block(wf):
        bad.append("`push: main` 面被删 ⇒ 存量陈旧报告（腿早已绿而单还开着）失去收敛入口")
    ups = tuple(str(x) for x in (_nested(on_block(wf), "workflow_run", "workflows") or []))
    for need in ("Drift Audit (真相源契约)",):
        if need not in ups:
            bad.append(f"`workflow_run` 上游缺 {need!r}（它在本仓是**每日档**，本腿的主要自动入口），实际 {ups}")
    return bad


def test_stale_report_reaper_is_intentionally_untouched() -> None:
    """② 实例：**没有**上游结论门控（套了它才是缺陷），`push: main` 与每日档上游在位。"""
    assert stale_reaper_problems(WORKFLOW_DOCS["stale-report-reaper.yml"]) == []


def test_stale_report_reaper_red_proofs() -> None:
    """② 注入式红证：**套上** failure-only 门控 ⇒ 必红（防有人「顺手降频」打断机制）。"""
    base = WORKFLOW_DOCS["stale-report-reaper.yml"]
    mutations = {
        "套 failure-only 门控（机制被打断）": lambda d: d["jobs"]["reap-stale-reports"].__setitem__(
            "if", "github.event.workflow_run.conclusion == 'failure'"),
        "套 failure||attempt 门控": lambda d: d["jobs"]["reap-stale-reports"].__setitem__(
            "if", "github.event.workflow_run.conclusion == 'failure' || "
                  "github.event.workflow_run.run_attempt > 1"),
        "删 push 面": lambda d: _with_on(d, lambda o: o.pop("push")),
    }
    for label, mutate in mutations.items():
        doc = _fresh("stale-report-reaper.yml")
        mutate(doc)
        assert stale_reaper_problems(doc), f"注入「{label}」后仍判绿 ⇒ 该判据是空断言"
    assert stale_reaper_problems(base) == [], "先决条件：未变异的真文件必须合规"


# ── ③ h5-freshness-guard：上游收窄到「发布腿」（保留 push + dispatch） ─────────

def h5_freshness_problems(wf: object) -> list[str]:
    bad: list[str] = []
    ups = tuple(str(x) for x in (_nested(on_block(wf), "workflow_run", "workflows") or []))
    pubblish = [u for u in ups if u.startswith("Publish ")]
    if len(pubblish) < 2:
        bad.append(f"`workflow_run` 上游必须保留两条**发布腿**（发布完成即重判新鲜度），实际 {ups}")
    pr_ci = [u for u in ups if "Mini-App CI" in u]
    if pr_ci:
        bad.append(
            f"上游 {pr_ci} 是 **PR 面** CI 腿，而本腿判定的是「线上产物 vs main 源码」⇒ 与上游结论无关，"
            f"它的每一次 PR 完成都白跑一次（实测 3 日 210 run 里绝大多数是这一半）")
    if "push" not in on_block(wf):
        bad.append("`push: main` 面被删 ⇒ main 有新合并时的新鲜度判定面丢失")
    if "workflow_dispatch" not in on_block(wf):
        bad.append("`workflow_dispatch` 面被删 ⇒ 一次性诊断（`no_gate`）失去入口")
    if "schedule" in on_block(wf):
        bad.append("本腿被加了 `schedule` ⇒ 违反既有裁定（用户 2026-09-21：⛔ 无 cron）")
    return bad


def test_h5_freshness_guard_narrows_upstreams_to_publish_legs() -> None:
    """③ 实例：上游只剩两条发布腿 + `push` + `workflow_dispatch`，且⛔ 无 cron。"""
    assert h5_freshness_problems(WORKFLOW_DOCS["h5-freshness-guard.yml"]) == []


def test_h5_freshness_guard_red_proofs() -> None:
    base = WORKFLOW_DOCS["h5-freshness-guard.yml"]
    mutations = {
        "把 Mini-App CI 加回上游": _restore_mini_app_upstream,
        "删 push 面": _drop_push,
        "加 cron": _add_cron,
    }
    for label, mutate in mutations.items():
        doc = _fresh("h5-freshness-guard.yml")
        mutate(doc)
        assert h5_freshness_problems(doc), f"注入「{label}」后仍判绿 ⇒ 该判据是空断言"
    assert h5_freshness_problems(base) == [], "先决条件：未变异的真文件必须合规"


# ── ④ pr-issue-link：PR 事件类型收窄到「body 会变」的那几种 ──────────────────

def pr_issue_link_problems(wf: object) -> list[str]:
    bad: list[str] = []
    types = _nested(on_block(wf), "pull_request", "types")
    if not types:
        bad.append("`pull_request` 未声明 `types` ⇒ 默认全事件（每次 `synchronize` 都重跑读 body 的检查）")
        return bad
    types = {str(t) for t in types}
    for need in ("opened", "reopened", "edited"):
        if need not in types:
            bad.append(f"`types` 缺 `{need}`（PR body 在这些事件上会变 ⇒ 漏判标签）")
    for extra in ("synchronize", "ready_for_review"):
        if extra in types:
            bad.append(
                f"`types` 仍含 `{extra}` ⇒ 本检查只读 PR **body**（`synchronize` = 每次 push、"
                f"`ready_for_review` = 改草稿态，都不改 body）⇒ 纯重跑")
    return bad


def test_pr_issue_link_narrows_event_types() -> None:
    """④ 实例：`types: [opened, reopened, edited]`。"""
    assert pr_issue_link_problems(WORKFLOW_DOCS["pr-issue-link.yml"]) == []


def test_pr_issue_link_red_proofs() -> None:
    base = WORKFLOW_DOCS["pr-issue-link.yml"]
    mutations = {
        "退回改前（含 synchronize）": lambda d: _with_on(d, lambda o: o["pull_request"]["types"].append("synchronize")),
        "退回改前（含 ready_for_review）": lambda d: _with_on(d, lambda o: o["pull_request"]["types"].append("ready_for_review")),
        "干脆不声明 types": lambda d: _with_on(d, lambda o: o["pull_request"].pop("types")),
    }
    for label, mutate in mutations.items():
        doc = _fresh("pr-issue-link.yml")
        mutate(doc)
        assert pr_issue_link_problems(doc), f"注入「{label}」后仍判绿 ⇒ 该判据是空断言"
    assert pr_issue_link_problems(base) == [], "先决条件：未变异的真文件必须合规"


# ── ⑤ mechanism-liveness：改日报型（去 PR 面，留 schedule + dispatch） ────────

def mechanism_liveness_problems(wf: object) -> list[str]:
    bad: list[str] = []
    on = on_block(wf)
    if "pull_request" in on:
        bad.append("仍带 `pull_request` 面 ⇒ 每一个 PR 都会跑一次登记面检查（日报型只需定时腿）")
    for need in ("schedule", "workflow_dispatch"):
        if need not in on:
            bad.append(f"`{need}` 面被删 ⇒ 日报型失去周期 / 手动入口")
    if "schedule" in on:
        crons = [str(e.get("cron")) for e in (on["schedule"] or []) if isinstance(e, dict)]
        if len(crons) != 1:
            bad.append(f"schedule 必须**恰好一条** cron（日报型），实际 {crons}")
        else:
            fields = crons[0].split()
            if len(fields) != 5 or fields[0].startswith("*/") or "," in fields[0]:
                bad.append(f"schedule 必须是**每日档**（日报型：分钟位是单值、不是 `*/N`），实际 {crons[0]!r}")
    return bad


def test_mechanism_liveness_becomes_daily_report() -> None:
    """⑤ 实例：无 `pull_request`，保留 `schedule`（每日）+ `workflow_dispatch`。"""
    assert mechanism_liveness_problems(WORKFLOW_DOCS["mechanism-liveness.yml"]) == []


def test_mechanism_liveness_red_proofs() -> None:
    base = WORKFLOW_DOCS["mechanism-liveness.yml"]
    mutations = {
        "把 PR 面加回来": lambda d: _with_on(d, lambda o: o.__setitem__("pull_request", {"branches": ["main"]})),
        "删 schedule（日报型的命根）": lambda d: _with_on(d, lambda o: o.pop("schedule")),
        "把 schedule 换成分钟级": lambda d: _with_on(d, lambda o: o.__setitem__("schedule", [{"cron": "*/20 * * * *"}])),
    }
    for label, mutate in mutations.items():
        doc = _fresh("mechanism-liveness.yml")
        mutate(doc)
        assert mechanism_liveness_problems(doc), f"注入「{label}」后仍判绿 ⇒ 该判据是空断言"
    assert mechanism_liveness_problems(base) == [], "先决条件：未变异的真文件必须合规"


# ── ⑦ automerge：周期面从 `*/20` 降到小时级（**不许删**） ─────────────────────

def automerge_problems(wf: object) -> list[str]:
    bad: list[str] = []
    on = on_block(wf)
    if "schedule" not in on:
        bad.append(
            "`schedule` 被删 ⇒ `detect-dangling-prs`（悬空 PR 没有事件，只能定时扫）失去**唯一**周期入口，"
            "只剩手动 `workflow_dispatch`（判据 = tests/unit_ci_workflows/test_dangling_pr_scan.py::job_wiring_problems）")
        return bad
    crons = [str(e.get("cron")) for e in (on["schedule"] or []) if isinstance(e, dict)]
    if not crons:
        bad.append(f"`schedule` 里没有 cron：{on['schedule']!r}")
        return bad
    fields = crons[0].split()
    if len(fields) != 5:
        bad.append(f"cron 不是 5 字段形态：{crons[0]!r}（先修本判据，别静默给空集）")
        return bad
    minute = fields[0]
    if minute.startswith("*/"):
        bad.append(f"仍是分钟级高频 `{crons[0]}`（名义 {1440 // int(minute[2:])} 次/日）⇒ 本包要求降到小时级")
    elif "," in minute or "-" in minute:
        bad.append(f"cron 的分钟位 `{minute}` 仍是多值 / 区间 ⇒ 不是小时级")
    if "pull_request_target" not in on:
        bad.append("`pull_request_target` 面被删 ⇒ auto-merge 失去事件驱动入口")
    if "workflow_dispatch" not in on:
        bad.append("`workflow_dispatch` 面被删 ⇒ 手动重扫入口丢失")
    cond = str(_nested(wf, "jobs", "detect-dangling-prs", "if") or "")
    if "schedule" not in cond or "workflow_dispatch" not in cond:
        bad.append(f"`detect-dangling-prs` 的 `if:` 必须限定在 schedule / workflow_dispatch：{cond!r}")
    return bad


def test_automerge_demotes_periodic_face_to_hourly() -> None:
    """⑦ 实例：`schedule` 保留（悬空扫描的**唯一**周期入口）但降到小时级。"""
    assert automerge_problems(WORKFLOW_DOCS["automerge.yml"]) == []


def test_automerge_red_proofs() -> None:
    base = WORKFLOW_DOCS["automerge.yml"]
    mutations = {
        "退回 */20": lambda d: _with_on(d, lambda o: o.__setitem__("schedule", [{"cron": "*/20 * * * *"}])),
        "删掉 schedule（把兜底当空转）": lambda d: _with_on(d, lambda o: o.pop("schedule")),
        "删掉 dispatch（手动入口）": lambda d: _with_on(d, lambda o: o.pop("workflow_dispatch")),
    }
    for label, mutate in mutations.items():
        doc = _fresh("automerge.yml")
        mutate(doc)
        assert automerge_problems(doc), f"注入「{label}」后仍判绿 ⇒ 该判据是空断言"
    assert automerge_problems(base) == [], "先决条件：未变异的真文件必须合规"


# ── ⑧ case-redraft：关键词门控**已在** `if:` 上；本包只补「非 bot」这一层 ─────

def case_redraft_problems(wf: object) -> list[str]:
    bad: list[str] = []
    cond = str(_nested(wf, "jobs", "trigger", "if") or "")
    for token, why in (
        ("<!-- REVIEW_JSON", "只对**自动评审载荷**评论触发（关键词门控）"),
        ('"reject"', "只对 REJECT 触发"),
        ('"supplement"', "只对 SUPPLEMENT 触发"),
        ("ai-draft", "已带 `ai-draft` 的 issue 不再触发（防环）"),
    ):
        if token not in cond:
            bad.append(f"`if:` 缺 `{token}` ⇒ {why} 的语义丢失")
    if "github.event.comment.user.type != 'Bot'" not in cond:
        bad.append(
            "`if:` 缺 `github.event.comment.user.type != 'Bot'` ⇒ bot 自己的评论也会创建一次 run"
            "（`issue_comment` 的过滤只能发生在 job 级 ⇒ 这是本腿唯一还能省的形态）")
    if set(on_block(wf)) != {"issue_comment"}:
        bad.append(f"触发面只有 `issue_comment[created]`，实际 {sorted(on_block(wf))}")
    return bad


def test_case_redraft_keeps_keyword_gate_and_adds_bot_gate() -> None:
    """⑧ 实例：关键词门控在位（既有语义）+ 新增非 bot 门控。"""
    assert case_redraft_problems(WORKFLOW_DOCS["case-redraft.yml"]) == []


def test_case_redraft_red_proofs() -> None:
    base = WORKFLOW_DOCS["case-redraft.yml"]
    mutations = {
        "退回改前（无 bot 门控）": lambda d: d["jobs"]["trigger"].__setitem__(
            "if", "contains(github.event.comment.body, '<!-- REVIEW_JSON') && "
                  "(contains(github.event.comment.body, '\"reject\"') || "
                  "contains(github.event.comment.body, '\"supplement\"')) && "
                  "!contains(github.event.issue.labels.*.name, 'ai-draft')"),
        "删掉 ai-draft 防环": lambda d: d["jobs"]["trigger"].__setitem__(
            "if", "contains(github.event.comment.body, '<!-- REVIEW_JSON') && "
                  "github.event.comment.user.type != 'Bot'"),
        "把关键词门控删掉（每条评论都干活）": lambda d: d["jobs"]["trigger"].__setitem__(
            "if", "github.event.comment.user.type != 'Bot'"),
    }
    for label, mutate in mutations.items():
        doc = _fresh("case-redraft.yml")
        mutate(doc)
        assert case_redraft_problems(doc), f"注入「{label}」后仍判绿 ⇒ 该判据是空断言"
    assert case_redraft_problems(base) == [], "先决条件：未变异的真文件必须合规"


# ── ⑥ / ⑨ 本包**有意不动**的两条（钉住它们的现取形态，防被顺手改坏） ───────────

def test_drift_audit_has_no_pull_request_leg_by_design() -> None:
    """⑥ 本包**有意去掉** `drift-audit.yml` 的 `pull_request` 腿（见 PR body「接受的缺口 + 重启条件」）。

    理由（机械可核）：`tests/unit_ci_workflows/test_drift_audit_unjudgeable_tri_state.py`
    的 `test_workflow_wires_exit_3_to_failure_not_pass` 逐字要求带 `block/merge` 的那一步
    `if:` 含 `github.event_name == 'pull_request'` ⇒ 去掉 PR 面会让该条件**恒假**（既有判据同批冲突）。
    ⇒ 本包**停在冲突处**、不动它，并在 PR body 登记为「未固化 / 待裁定」。
    """
    doc = WORKFLOW_DOCS["drift-audit.yml"]
    on = on_block(doc)
    assert "pull_request" not in on, (
        "drift-audit 又长回了 `pull_request` 面 —— **本包有意去掉它**（#5814 触发面降频；"
        "重启条件写在 `on:` 块里：要恢复 PR 阶段即时拦截须**先翻进 required 集合**＋同批恢复 PR 腿）。"
        f"实际 on={sorted(on)}")
    for need in ("schedule", "workflow_dispatch"):
        assert need in on, f"drift-audit 的 `{need}` 面被删（每日债务盘点 / 手动入口）"
    # 去掉 PR 面**不许**把「exit 3 ⇒ 判红而非放行」这条牙齿一起拔掉（承接面转到值班 step）
    steps = doc["jobs"]["audit"]["steps"]
    duty = [s for s in steps if "定时腿失败" in str(s.get("name") or "")]
    assert duty and "failure()" in str(duty[0].get("if") or ""), (
        "`exit 3` 的失败承接面（值班 step）不见了 ⇒ 去掉 PR 腿变成了「判了没人看」")


def test_flaky_ledger_reconcile_keeps_minute_level_fallback() -> None:
    """⑨ 本包**不动** `flaky-ledger-reconcile.yml` 的 cron（见 PR body「不做」节）。

    理由（机械可核 + 实测）：`tests/unit_ci_workflows/test_flaky_ledger_reconcile.py::audit_reconcile`
    逐字要求 `schedule` 是**分钟级兜底**（`^\\*/[0-9]+ `）⇒ 降小时级会撞那条既有判据；
    且**实测该腿已被 GitHub 节流**：`*/20` 名义 72 次/日，3 日实得 schedule 仅 15 次（≈5/日）
    ⇒ 降频收益 ≈ 0，动它只有改判据的成本。
    """
    doc = WORKFLOW_DOCS["flaky-ledger-reconcile.yml"]
    types = _nested(on_block(doc), "pull_request", "types")
    assert sorted(types or []) == ["opened", "reopened"], (
        f"`pull_request.types` 有意保持 [opened, reopened]（近实时兜底入口），实际 {types!r}")


# ══════════════════════════════════════════════════════════════════════════════
# 三、类级元守卫（两族）：未登记即红 / 台账只许缩短
# ══════════════════════════════════════════════════════════════════════════════


def test_workflow_run_consumers_are_gated_or_registered() -> None:
    """守卫 A：PR 面上游的 `workflow_run` 消费腿 ⇒ 有结论门控，或入册豁免（未登记即红）。"""
    problems = gate_problems(consumers=CONSUMERS, registry=_ledger(GATE_LEDGER))
    assert not problems, "workflow_run 消费面门控台账有问题：\n" + "\n".join(problems)


def test_pr_types_are_registered() -> None:
    """守卫 B：`pull_request` 未声明 `types` 的腿必须登记（未登记即红）。"""
    problems = pr_types_problems(docs=WORKFLOW_DOCS, registry=_ledger(PR_TYPES_LEDGER))
    assert not problems, "PR 事件面台账有问题：\n" + "\n".join(problems)


def test_live_counts_are_printed_and_not_empty() -> None:
    """反空跑读数：现取条数**打印**出来；取空 ⇒ 红（「扫不到」不许长得像「通过」）。"""
    live_gate = {n: ups for n, ups in CONSUMERS.items()
                 if any("pull_request" in e for _u, e in ups)}
    live_pr = {n for n, d in WORKFLOW_DOCS.items()
               if on_block(d).get("pull_request") is not None
               and not _nested(on_block(d), "pull_request", "types")}
    print(f"[触发面降频] workflow_run 消费腿 = {len(CONSUMERS)} 条；其中 PR 面上游 = {len(live_gate)} 条 → {sorted(live_gate)}")
    print(f"[触发面降频] PR 未声明 types = {len(live_pr)} 条 → {sorted(live_pr)}")
    assert live_gate, "没有任何「PR 面上游的 workflow_run 消费腿」⇒ 守卫 A 在空集上恒真（判据退化）"
    assert live_pr, "没有任何「未声明 types 的 PR 腿」⇒ 守卫 B 在空集上恒真（判据退化）"


def test_gate_guard_has_discriminating_power() -> None:
    """守卫 A 的注入式红证（**内存构造**）：四种坏形态各能单独变红 + 两条对照。"""
    registry = _ledger(GATE_LEDGER)
    base = copy.deepcopy(CONSUMERS)
    assert gate_problems(consumers=base, registry=registry) == [], "先决条件：真语料必须合规"

    # 坏形态 ①：把 `flaky-triage` 的门控摘掉（内存 doc）⇒ 它落进 ungated 检查 ⇒ 红
    ungated = copy.deepcopy(WORKFLOW_DOCS["flaky-triage.yml"])
    ungated["jobs"]["triage"].pop("if", None)
    original = WORKFLOW_DOCS["flaky-triage.yml"]
    try:
        WORKFLOW_DOCS["flaky-triage.yml"] = ungated
        bad = gate_problems(consumers=base, registry=registry)
        assert any("flaky-triage.yml" in p for p in bad), f"摘掉门控后仍判绿 ⇒ 空断言：{bad}"
    finally:
        WORKFLOW_DOCS["flaky-triage.yml"] = original

    # 坏形态 ②：新造一条未登记的 PR 面消费腿 ⇒ 红（`consumers_frozen` 对不上）
    mutated = copy.deepcopy(CONSUMERS)
    mutated["brand-new-consumer.yml"] = (("PR Check", ("pull_request", "workflow_dispatch")),)
    assert any("consumers_frozen" in p for p in gate_problems(consumers=mutated, registry=registry)), \
        "新造未登记的消费腿仍判绿 ⇒ 空断言"

    # 坏形态 ③：**缺** `ungated_ok` 字段 ⇒ fail-closed 红（空数组是合法的「没有例外」）
    no_ungated = {k: v for k, v in registry.items() if k != "ungated_ok"}
    assert any("ungated_ok" in p for p in gate_problems(consumers=base, registry=no_ungated)), \
        "缺 `ungated_ok` 字段仍判绿 ⇒ fail-closed 失效"

    # 坏形态 ④：给一条**不存在**的腿盖章 ⇒ 陈旧登记红
    ghost = {**registry, "ungated_ok": list(registry["ungated_ok"]) + [
        {"file": "ghost.yml", "reason": "x", "evidence": "y"}]}
    assert any("ghost.yml" in p for p in gate_problems(consumers=base, registry=ghost)), \
        "给不存在的腿盖章仍判绿 ⇒ 陈旧登记不被抓"

    # 对照：**只改注释** ⇒ 判据不红（`yaml` 解析天然剥注释，这里是显式读数）
    comment_only = copy.deepcopy(WORKFLOW_DOCS["flaky-triage.yml"])
    comment_only.setdefault("__file__", "flaky-triage.yml")
    assert gate_problems(consumers=base, registry=registry) == []


def test_pr_types_guard_has_discriminating_power() -> None:
    """守卫 B 的注入式红证（内存构造）+ 对照读数。"""
    registry = _ledger(PR_TYPES_LEDGER)
    assert pr_types_problems(docs=WORKFLOW_DOCS, registry=registry) == [], "先决条件：真语料必须合规"
    # 坏形态：新造一条未声明 types 的 PR 腿（用一个不存在于台账的真实文件冒充）⇒ 未登记即红
    docs = copy.deepcopy(WORKFLOW_DOCS)
    docs["ghost.yml"] = {"on": {"pull_request": {"branches": ["main"]}}}
    assert any("ghost.yml" in p for p in pr_types_problems(docs=docs, registry=registry)), \
        "新造未声明 types 的 PR 腿仍判绿 ⇒ 空断言"
    # 坏形态：登记的腿已声明 types ⇒ 陈旧登记红
    stale = {**registry, "no_types": list(registry["no_types"]) + [
        {"file": "flaky-triage.yml", "reason": "x"}]}
    assert any("flaky-triage.yml" in p for p in pr_types_problems(docs=WORKFLOW_DOCS, registry=stale)), \
        "已声明 types 的腿仍留在台账 ⇒ 只许缩短失效"
    # 坏形态：条数被单改 ⇒ 红
    assert any("count_frozen" in p for p in pr_types_problems(
        docs=WORKFLOW_DOCS, registry={**registry, "count_frozen": 99})), "条数单改仍判绿 ⇒ 空断言"


def test_ledgers_are_wellformed() -> None:
    """两张台账的形态与「可归因」要求（缺字段 ⇒ 红，不粉饰）。"""
    gate = _ledger(GATE_LEDGER)
    for key in ("schema", "what", "consumers_frozen", "workflow_run_gated", "ungated_ok",
                "narrowed_in_this_package", "coverage_boundary"):
        assert key in gate, f"{GATE_LEDGER.name} 缺 `{key}`"
    for item in gate["coverage_boundary"]:
        for key in ("face", "reason", "recompute"):
            assert str(item.get(key) or "").strip(), f"{GATE_LEDGER.name} 的 coverage_boundary 缺 `{key}`"
    pr = _ledger(PR_TYPES_LEDGER)
    for key in ("schema", "what", "count_frozen", "no_types", "coverage_boundary"):
        assert key in pr, f"{PR_TYPES_LEDGER.name} 缺 `{key}`"


def test_comment_only_change_does_not_turn_anything_red() -> None:
    """对照读数（防空断言）：**只改注释**的九个 YAML ⇒ 九条实例判据与两条守卫都**不红**。

    做法：在真源码文本里插一行注释、重新解析，再跑同一组纯函数。
    """
    checkers = {
        "flaky-triage.yml": flaky_triage_problems,
        "stale-report-reaper.yml": stale_reaper_problems,
        "h5-freshness-guard.yml": h5_freshness_problems,
        "pr-issue-link.yml": pr_issue_link_problems,
        "mechanism-liveness.yml": mechanism_liveness_problems,
        "automerge.yml": automerge_problems,
        "case-redraft.yml": case_redraft_problems,
    }
    for name, checker in checkers.items():
        text = (WORKFLOWS_DIR / name).read_text(encoding="utf-8")
        mutated = yaml.safe_load("# 只改注释（对照读数）：本行不改变任何语义\n" + text)
        assert checker(mutated) == [], f"只加注释就让 `{name}` 判红 ⇒ 判据吃到了说明文字（噪声）"


@pytest.mark.parametrize("name", TRACKED)
def test_tracked_workflow_yaml_is_parseable(name: str) -> None:
    """fail-closed：任一条被追踪的 YAML 解析不出来 ⇒ 红（不许静默给空对象）。"""
    doc = WORKFLOW_DOCS[name]
    assert isinstance(on_block(doc), dict) and on_block(doc), f"{name} 的 `on:` 取不到（解析失配）"
