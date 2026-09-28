# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012。）
r"""CI 成本台账的常驻判据（issue #3507 ②）。

## 台账是什么 / 判据锁什么

台账 = `tests/unit_ci_workflows/ci_cost_ledger.json`（机器可读，**每条 PR 触发的腿**一行）：
**实测**近期时长（`measured`）+ **硬杀上限**（`hard_kill_seconds`）+ **目标预算**（`budget_seconds`）
+ required 口径 + 超预算的归因口径（`attribution_policy`）+ 已裁定的策略项 + 外部阻塞。
生成/复算 = `python3 scripts/ci_cost_ledger.py --measure`。

**预算口径（owner 裁定 2026-09-26）**：预算 = 该腿**实测 p90 向上取整**（读数的函数，不是人手填的数）；
取不到读数（n < 3）的腿**保持留白**、不编数。⇐ 这条裁定由判据 4 钉住：手改任何一个预算数字都会红。

本文件**只锁"台账不许自说自话"**，不锁时长本身（时长是读数，会随负载漂移）：

| # | 判据 | 语义 / 红证 |
|---|---|---|
| 1 | 台账**非空 + 形态合规** | `legs` 为空 / 缺 schema / 缺复算命令 / 缺 `attribution_policy` 四项 ⇒ 红（防"空跑成绿"） |
| 2 | **硬杀上限与现取 YAML 逐条相等** | `hard_kill_seconds` 必须 == 该 workflow 该 job 的 `timeout-minutes × 60`；改 workflow 抬上限而不改台账 ⇒ 红（反之亦然）。**这是把"上限"钉在仓库自有值上、而不是让台账手抄一个会腐烂的数** |
| 3 | **实测读数自洽** | `n ≥ 3` 且 `0 < median ≤ p90 ≤ max`；样本不足必须显式写 `measured: null` + `measure_status`（**不许**用一个好看的数填空） |
| 4 | **预算 == ceil(实测 p90)**（文件不变式） | 手改任一 `budget_seconds`（或填一个人手凑的整数）⇒ 红；无读数的腿必须 `null` + `budget_status` 逐字等于留白口径 |
| 5 | **超预算会红 + 归因口径在案** | 见 `TestBudgetBreachRedProof`：预算 100s / 新实测 p90 150s ⇒ **必须命中**；上取整 == 预算 ⇒ 必须不命中（边界）；读数下降 ⇒ 不命中。政策文本必须同时含「新增开销」与「`timeout-minutes`」（把"先查新增开销、不许抬 timeout"钉进数据） |
| 6 | **策略项已裁定就要带裁定人与重开条件** | 非「待裁定」⇒ 必须有 `decided_by` 与 `reopen_condition`；频率上限那条的裁定内容还必须写出依据（两者都只有 `workflow_dispatch`） |
| 7 | **③ 外部阻塞必须登记在案** | `external_blockers` 里 GHCR 那条必须带 `owner_action`（含**可复制的命令**）/ `restart_condition` / `carrier`，且 `grant_verified` 是布尔（未验证就写 `false`，**不许含混过去**） |

## 边界（照实登记，别把"登记了"读成"治住了"）

- 判据**不**在 CI 里比对"实测数值与真实 CI 是否一致"（判据在 CI 里读不到 Actions API 的历史时长）⇒
  它锁的是**结构 + 自洽 + 预算与读数的函数关系**，外加**超预算判定逻辑本身**（判据 5，纯函数）。
  **超预算判红真正生效的地方** = `python3 scripts/ci_cost_ledger.py --measure`（能读该 API 的环境）；
  这条边界逐字写在台账的 `attribution_policy.enforced_where` 里，判据 5 会核它非空。
- 判据**不**拦 `timeout-minutes` 本身被抬高（那是"值班判据"，见 `pr-check.yml` 里
  `ci workflow tests` job 上方那段口径）—— 它只保证台账跟着现取走，**不留下过期上限**。
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO / ".github" / "workflows"
LEDGER_PATH = REPO / "tests" / "unit_ci_workflows" / "ci_cost_ledger.json"
SCRIPT_PATH = REPO / "scripts" / "ci_cost_ledger.py"
SELF_REL = "tests/unit_ci_workflows/test_ci_cost_ledger.py"
SCHEMA = "ci-cost-ledger/v1"


def _script():
    """按路径加载被测脚本（`scripts/` 不是包）—— 判据 5 直接调它的纯函数。"""
    spec = importlib.util.spec_from_file_location("ci_cost_ledger_under_test", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ledger() -> dict:
    assert LEDGER_PATH.exists(), f"缺成本台账 {LEDGER_PATH.relative_to(REPO)}（issue #3507 ②）"
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def _legs() -> list[dict]:
    legs = _ledger().get("legs")
    assert isinstance(legs, list) and len(legs) > 0, (
        "台账 `legs` 为空 ⇒ 本判据会在空集上恒真（空跑成绿）。复算：python3 scripts/ci_cost_ledger.py --measure"
    )
    return legs


def _live_timeouts() -> dict[str, int | None]:
    """现取每个 `<workflow>::<job>` 的 `timeout-minutes`（**不读台账**，两边独立取值才判得出漂移）。"""
    out: dict[str, int | None] = {}
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for jid, job in (doc.get("jobs") or {}).items():
            if isinstance(job, dict) and "runs-on" in job:
                timeout = job.get("timeout-minutes")
                out[f"{path.name}::{jid}"] = int(timeout) if timeout else None
    return out


def test_ledger_is_wellformed_and_non_empty() -> None:
    """判据 1：schema / 测量来源 / 复算命令 / 归因口径齐全，且确有实测读数。"""
    data = _ledger()
    assert data.get("schema") == SCHEMA, f"台账 schema 不是 {SCHEMA}（形态漂移 ⇒ 红）：{data.get('schema')!r}"
    measured = data.get("measured") or {}
    assert measured.get("recompute"), "台账缺 `measured.recompute` ⇒ 读数无法复算（数字变成不可验证的断言）"
    assert measured.get("at"), "台账缺 `measured.at` ⇒ 无法判断读数有多旧"
    assert measured.get("source"), "台账缺 `measured.source` ⇒ 读数来源不可追溯"
    policy = data.get("attribution_policy") or {}
    missing_policy = [k for k in ("rule", "what_to_check_first", "how_to_raise", "enforced_where")
                      if len(str(policy.get(k) or "")) < 20]
    assert missing_policy == [], f"台账 `attribution_policy` 缺项或过短：{missing_policy}（超预算时无口径可依）"
    legs = _legs()
    with_readings = [leg for leg in legs if leg.get("measured")]
    print(f"台账腿数={len(legs)}（有实测读数 {len(with_readings)} 条 / 有预算 "
          f"{sum(1 for leg in legs if leg.get('budget_seconds'))} 条）/ "
          f"required={sum(1 for leg in legs if leg.get('required'))} 条 / measured.at={measured.get('at')}")
    assert len(with_readings) > 0, "一条实测读数都没有 ⇒ 台账没有承担'实测'这件事"


def test_hard_kill_ceiling_matches_workflow_verbatim() -> None:
    """判据 2：`hard_kill_seconds` 必须等于现取 YAML 的 `timeout-minutes × 60`（手抄腐烂即红）。"""
    live = _live_timeouts()
    problems: list[str] = []
    checked = 0
    for leg in _legs():
        key = f"{leg.get('workflow')}::{leg.get('job')}"
        if key not in live:
            problems.append(f"{key}：台账里的腿**在现取 workflow 里不存在**（job 被改名/删除）⇒ 台账陈旧")
            continue
        want = live[key]
        expected = want * 60 if want else None
        got = leg.get("hard_kill_seconds")
        if got != expected:
            problems.append(f"{key}：上限不符 —— 台账 {got} / 现取 YAML {expected}（timeout-minutes={want}）")
            continue
        source = str(leg.get("hard_kill_source") or "")
        if expected is None and "未声明" not in source:
            problems.append(f"{key}：现取未声明 timeout-minutes，但 `hard_kill_source`={source!r} 没说清楚")
        if expected is not None and not source:
            problems.append(f"{key}：有上限却缺 `hard_kill_source`（读者无法知道上限从哪来）")
        checked += 1
    print(f"上限逐条复比：已核对 {checked} 条腿 / 问题 {len(problems)} 条")
    assert checked > 0, "一条腿都没核对上 ⇒ 复比口径失效（判据会静默空跑成绿）"
    assert not problems, (
        "台账的「硬杀上限」与现取 workflow 不一致：\n" + "\n".join("  " + p for p in problems)
        + "\n修法：`python3 scripts/ci_cost_ledger.py --measure` 重算台账（上限取自 workflow 自身，不手抄）。"
    )


def test_measured_readings_are_self_consistent() -> None:
    """判据 3：读数自洽（n ≥ 3 / 0 < median ≤ p90 ≤ max）；无样本必须显式留白。"""
    problems: list[str] = []
    for leg in _legs():
        reading = leg.get("measured")
        if not reading:
            if not str(leg.get("measure_status") or "").strip():
                problems.append(f"{leg.get('id')}：没有实测读数，却也没有 `measure_status` ⇒ 「没测」被读成「没问题」")
            continue
        n = reading.get("n")
        median, p90, maxv = reading.get("median_seconds"), reading.get("p90_seconds"), reading.get("max_seconds")
        if not isinstance(n, int) or n < 3:
            problems.append(f"{leg.get('id')}：n={n} < 3 ⇒ 单次读数不足以下结论（不许拿一次当分布）")
            continue
        if not all(isinstance(v, (int, float)) for v in (median, p90, maxv)):
            problems.append(f"{leg.get('id')}：median/p90/max 不是数字 ⇒ 形态漂移")
            continue
        if not (0 < median <= p90 <= maxv):
            problems.append(f"{leg.get('id')}：读数不自洽 —— median={median} p90={p90} max={maxv}"
                            "（必须 0 < median ≤ p90 ≤ max）")
    print(f"读数自洽核对：腿 {len(_legs())} 条 / 问题 {len(problems)} 条")
    assert not problems, "台账读数不自洽：\n" + "\n".join("  " + p for p in problems)


def test_budget_equals_measured_p90_ceil_or_is_explicitly_blank() -> None:
    """判据 4：预算 == ceil(实测 p90)（**文件不变式**）；无读数的腿保持留白、不编数。

    这条就是「不许发明策略数字」在**新口径**下的形态：预算是**读数的函数** ⇒ 想改预算只有两条路 ——
    真跑一次 `--measure` 改读数，或显式改口径（脚本与判据同改、在 diff 里留痕）。手填一个整数 ⇒ 红。
    """
    mod = _script()
    problems: list[str] = []
    rows = 0
    for leg in _legs():
        rows += 1
        reading, budget = leg.get("measured") or {}, leg.get("budget_seconds")
        status = str(leg.get("budget_status") or "")
        basis = str(leg.get("budget_basis") or "")
        if reading:
            expected = int(math.ceil(reading["p90_seconds"]))
            if budget != expected:
                problems.append(f"{leg.get('id')}：预算 {budget} != ceil(实测 p90 {reading['p90_seconds']}) = {expected}"
                                "（预算是读数的函数，手填的整数一律红）")
            if status != mod.BUDGET_STATUS_MEASURED:
                problems.append(f"{leg.get('id')}：有读数但 `budget_status`={status!r}"
                                f"，应为 {mod.BUDGET_STATUS_MEASURED!r}")
            if "p90" not in basis:
                problems.append(f"{leg.get('id')}：`budget_basis` 没说清预算从哪来（{basis!r}）")
        else:
            if budget is not None:
                problems.append(f"{leg.get('id')}：**没有实测读数却写了预算 {budget}** ⇒ 正是「编一个数」的形态")
            if status != mod.BUDGET_STATUS_NO_READING:
                problems.append(f"{leg.get('id')}：无读数时 `budget_status` 应为 {mod.BUDGET_STATUS_NO_READING!r}"
                                f"，现为 {status!r}（留白必须显式，否则会被读成'已定'）")
    print(f"预算口径核对：{rows} 条腿 / 问题 {len(problems)} 条")
    assert rows > 0, "一条腿都没有 ⇒ 本判据在空集上恒真"
    assert not problems, (
        "台账的「目标预算」与裁定口径不符（口径 = 实测 p90 向上取整；无读数则留白）：\n"
        + "\n".join("  " + p for p in problems)
        + "\n修法：`python3 scripts/ci_cost_ledger.py --measure` 重算（预算由读数派生，不要手填）。"
    )


class TestBudgetBreachRedProof:
    """判据 5：**超预算会红** + 归因口径在案（用合成数据直接证明判定逻辑，不必等真实 CI 变慢）。"""

    def test_breach_is_detected_when_new_p90_exceeds_frozen_budget(self) -> None:
        """🔴 红证（判据本体）：已冻结预算 100s / 新实测 p90 150s ⇒ **必须命中**且给出可归因读数。"""
        mod = _script()
        got = mod.budget_breaches({"wf::job": 100}, {"wf::job": 150.0, "other::job": 150.0})
        assert got == [{
            "id": "wf::job",
            "budget_seconds": 100,
            "new_p90_seconds": 150.0,
            "new_p90_ceil": 150,
        }], (
            "超预算未被判出（或形态漂移）⇒ 「超了红」这条裁定在实现里不成立。\n"
            f"现取：{got!r}\n"
            "注意 `other::job`（没有冻结预算 ⇒ 无读数腿）**不得**被判 —— 它没有预算可比。"
        )

    def test_breach_boundary_and_direction(self) -> None:
        """边界：p90 上取整 == 预算 ⇒ 不命中；超出 1s ⇒ 命中；**下降** ⇒ 不命中（预算只许收紧）。"""
        mod = _script()
        assert mod.budget_breaches({"a": 100}, {"a": 99.5}) == [], "99.5 上取整 = 100 == 预算 ⇒ 不应命中"
        assert len(mod.budget_breaches({"a": 100}, {"a": 100.0001})) == 1, "上取整 101 > 100 ⇒ 必须命中"
        assert mod.budget_breaches({"a": 100}, {"a": 10.0}) == [], "读数下降不得被判成超预算"
        assert mod.ceil_budget(0.1) == 1 and mod.ceil_budget(120.0) == 120, "上取整口径漂移"

    def test_attribution_policy_pins_check_new_overhead_not_raising_timeout(self) -> None:
        """归因口径必须**逐字**钉住「先查新增开销」与「不许抬 timeout」（#5365 同源）。"""
        policy = _ledger().get("attribution_policy") or {}
        first = str(policy.get("what_to_check_first") or "")
        assert "新增" in first and "开销" in first, (
            "`attribution_policy.what_to_check_first` 没写「先查**新增**开销」⇒ 超预算时的归因要求丢失（#5365 同源口径）"
        )
        assert "timeout-minutes" in first, (
            "`attribution_policy.what_to_check_first` 没写「**不要**抬 `timeout-minutes` 交差」⇒ 治症状的路子没被堵"
        )
        assert "accept-raise" in str(policy.get("how_to_raise") or ""), (
            "`how_to_raise` 必须给出**显式**抬预算的逃生口（改动要能在 diff 里看见），否则人们会直接改 JSON"
        )
        assert "Actions API" in str(policy.get("enforced_where") or ""), (
            "`enforced_where` 必须说清超预算判红**只在能读 Actions API 的环境**生效（否则会被读成 CI 也拦）"
        )


def test_policy_decisions_carry_decider_and_reopen_condition() -> None:
    """判据 6：已裁定的策略项必须带裁定人 + 重开条件；频率那条还要写出依据。"""
    decisions = _ledger().get("policy_decisions") or []
    assert len(decisions) >= 2, f"策略项只有 {len(decisions)} 条 ⇒ 本判据在空集上恒真"
    problems: list[str] = []
    by_id = {str(d.get("id")): d for d in decisions}
    for decision in decisions:
        where = f"policy_decisions::{decision.get('id')}"
        if len(str(decision.get("decision") or "")) < 20:
            problems.append(f"{where}：缺 `decision`（只说状态不说裁定内容）")
        if str(decision.get("status") or "").startswith("待裁定"):
            if decision.get("decided_by"):
                problems.append(f"{where}：标了待裁定却又有 decided_by")
            continue
        if len(str(decision.get("decided_by") or "")) < 6:
            problems.append(f"{where}：已裁定却没有 `decided_by` ⇒ 来源不明的裁定")
        if len(str(decision.get("reopen_condition") or "")) < 12:
            problems.append(f"{where}：缺 `reopen_condition` ⇒ 将来条件变了没人知道要重开")
    freq = by_id.get("eval-monthly-frequency-cap") or {}
    if "workflow_dispatch" not in str(freq.get("decision") or ""):
        problems.append("policy_decisions::eval-monthly-frequency-cap：裁定内容没写「两者都只有 workflow_dispatch」这一依据"
                        "（依据丢了，后来者会以为当时只是没空定）")
    print(f"策略项核对：{len(decisions)} 条 / 问题 {len(problems)} 条 / 现取 id={sorted(by_id)}")
    assert not problems, "策略裁定登记不合规：\n" + "\n".join("  " + p for p in problems)


def test_external_blockers_are_registered_with_command_and_restart_condition() -> None:
    """判据 7：③ GHCR 外部阻塞必须在册（带可复制命令 + 重启条件 + 载体），且验证状态是布尔。"""
    blockers = _ledger().get("external_blockers")
    assert isinstance(blockers, list) and len(blockers) > 0, (
        "台账没有 `external_blockers` ⇒ ③「GHCR 需 packages:write」这条外部依赖没有落点"
        "（关单后就会蒸发 —— 正是「'有意不做'被读成'已解决'」的形态）"
    )
    problems: list[str] = []
    for blocker in blockers:
        where = f"external_blockers::{blocker.get('id')}"
        action = str(blocker.get("owner_action") or "")
        if len(action) < 40:
            problems.append(f"{where}：`owner_action` 太短 ⇒ 缺少 owner 可执行的**命令**")
        if "gh " not in action and "ghcr.io" not in action:
            problems.append(f"{where}：`owner_action` 里没有可复制的命令（`gh …` / `ghcr.io…`）")
        if len(str(blocker.get("restart_condition") or "")) < 20:
            problems.append(f"{where}：缺 `restart_condition` ⇒ 将来没人知道满足什么条件才能重启这项")
        if len(str(blocker.get("carrier") or "")) < 8:
            problems.append(f"{where}：缺 `carrier`（这条登记落在哪份活文档上）")
        if not isinstance(blocker.get("grant_verified"), bool):
            problems.append(f"{where}：`grant_verified` 必须是布尔 —— 未验证就要如实写 false，不许含混")
    ids = {str(b.get("id")) for b in blockers}
    assert "ghcr-prebuilt-images" in ids, f"③ 的 GHCR 阻塞不在册（现取 id：{sorted(ids)}）"
    print(f"外部阻塞在册：{sorted(ids)}")
    assert not problems, "外部阻塞登记不完整：\n" + "\n".join("  " + p for p in problems)
