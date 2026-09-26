# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012。）
r"""CI 成本台账的常驻判据（issue #3507 ②）。

## 台账是什么 / 判据锁什么

台账 = `tests/unit_ci_workflows/ci_cost_ledger.json`（机器可读，**每条 PR 触发的腿**一行）：
**实测**近期时长（`measured`）+ **显式上限**（`hard_kill_seconds`）+ required 口径 +
需要 owner 裁定的项（`policy_decisions`）+ 外部阻塞（`external_blockers`）。
生成/复算 = `python3 scripts/ci_cost_ledger.py --measure`。

本文件**只锁"台账不许自说自话"**，不锁时长本身（时长是读数，会随负载漂移）：

| # | 判据 | 语义 / 红证 |
|---|---|---|
| 1 | 台账**非空 + 形态合规** | `legs` 为空 / 缺 schema ⇒ 红（防"空跑成绿"） |
| 2 | **上限与现取 YAML 逐条相等** | `hard_kill_seconds` 必须 == 该 workflow 该 job 的 `timeout-minutes × 60`；改 workflow 抬上限而不改台账 ⇒ 红（反之亦然）。**这是把"上限"钉在仓库自有值上、而不是让台账手抄一个会腐烂的数** |
| 3 | **实测读数自洽** | `n ≥ 3` 且 `0 < median ≤ p90 ≤ max`；样本不足必须显式写 `measured: null` + `measure_status`（**不许**用一个好看的数填空） |
| 4 | **不许发明策略数字** | `budget_seconds` 要么是整数**且**带 `budget_status == "已裁定"`，要么必须 `budget_status == "待裁定"` + 非空 `budget_question`。**"看起来合理"的数是本判据要拦的形态**（owner 未拍板 ⇒ 只能挂待裁定） |
| 5 | **③ 外部阻塞必须登记在案** | `external_blockers` 里 GHCR 那条必须带 `owner_action`（含**可复制的命令**）/ `restart_condition` / `carrier`，且 `grant_verified` 是布尔（未验证就写 `false`，**不许含混过去**） |

## 边界（照实登记，别把"登记了"读成"治住了"）

- 判据**不**校验 `measured` 的数值与真实 CI 一致（判据在 CI 里读不到 Actions API 的历史时长）；
  它只保证"数来自 `--measure` 的结构"与自洽性 ⇒ **读数陈旧不会被本判据发现**，
  靠 `measured.at` / `measured.recompute` 让人能自己复算。
- 判据**不**拦 `timeout-minutes` 本身被抬高（那是"值班判据"，见 `pr-check.yml` 里
  `ci workflow tests` job 上方那段口径）—— 它只保证台账跟着现取走，**不留下过期上限**。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO / ".github" / "workflows"
LEDGER_PATH = REPO / "tests" / "unit_ci_workflows" / "ci_cost_ledger.json"
SELF_REL = "tests/unit_ci_workflows/test_ci_cost_ledger.py"
SCHEMA = "ci-cost-ledger/v1"


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
    """判据 1：schema / 测量来源 / 非空读数。"""
    data = _ledger()
    assert data.get("schema") == SCHEMA, f"台账 schema 不是 {SCHEMA}（形态漂移 ⇒ 红）：{data.get('schema')!r}"
    measured = data.get("measured") or {}
    assert measured.get("recompute"), "台账缺 `measured.recompute` ⇒ 读数无法复算（数字变成不可验证的断言）"
    assert measured.get("at"), "台账缺 `measured.at` ⇒ 无法判断读数有多旧"
    assert measured.get("source"), "台账缺 `measured.source` ⇒ 读数来源不可追溯"
    legs = _legs()
    with_readings = [leg for leg in legs if leg.get("measured")]
    print(f"台账腿数={len(legs)}（有实测读数 {len(with_readings)} 条）/ "
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
        "台账的「显式上限」与现取 workflow 不一致：\n" + "\n".join("  " + p for p in problems)
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


def test_policy_numbers_are_decided_or_explicitly_pending() -> None:
    """判据 4：**不许发明策略数字** —— 目标预算要么已裁定（带裁定人），要么显式待裁定（带问题）。"""
    problems: list[str] = []
    rows = 0
    for leg in _legs():
        rows += 1
        budget = leg.get("budget_seconds")
        status = str(leg.get("budget_status") or "")
        if isinstance(budget, int):
            if status != "已裁定":
                problems.append(f"{leg.get('id')}：`budget_seconds={budget}` 但 `budget_status={status!r}`"
                                "（写了数字就必须标明它已被裁定）")
            if not leg.get("decided_by"):
                problems.append(f"{leg.get('id')}：写了预算数字却没有 `decided_by` ⇒ 来源不明的策略数字")
        elif budget is None:
            if status != "待裁定":
                problems.append(f"{leg.get('id')}：无预算数字，`budget_status` 却是 {status!r}"
                                "（未裁定必须显式写 `待裁定`，否则会被读成'已定'）")
            if len(str(leg.get("budget_question") or "")) < 12:
                problems.append(f"{leg.get('id')}：待裁定项缺可回答的 `budget_question`（谁来答都不知道）")
        else:
            problems.append(f"{leg.get('id')}：`budget_seconds` 形态非法 {budget!r}（整数或 null）")
    for decision in _ledger().get("policy_decisions") or []:
        rows += 1
        if str(decision.get("status")) == "待裁定":
            if decision.get("decided_by"):
                problems.append(f"policy_decisions::{decision.get('id')}：标了待裁定却又有 decided_by")
            if len(str(decision.get("question") or "")) < 12:
                problems.append(f"policy_decisions::{decision.get('id')}：缺可回答的 `question`")
            if len(str(decision.get("why_not_derivable") or "")) < 20:
                problems.append(f"policy_decisions::{decision.get('id')}：缺 `why_not_derivable`"
                                "（必须说清'为什么这不是能算出来的读数'）")
        elif not decision.get("decided_by"):
            problems.append(f"policy_decisions::{decision.get('id')}：非待裁定 ⇒ 必须写 `decided_by`")
    print(f"预算/策略口径核对：{rows} 条 / 问题 {len(problems)} 条")
    assert rows > 0, "一条预算/策略登记都没有 ⇒ 本判据在空集上恒真"
    assert not problems, "台账里出现「来源不明的策略数字」或含混的待裁定项：\n" + "\n".join("  " + p for p in problems)


def test_external_blockers_are_registered_with_command_and_restart_condition() -> None:
    """判据 5：③ GHCR 外部阻塞必须在册（带可复制命令 + 重启条件 + 载体），且验证状态是布尔。"""
    blockers = _ledger().get("external_blockers")
    assert isinstance(blockers, list) and len(blockers) > 0, (
        "台账没有 `external_blockers` ⇒ ③「GHCR 需 packages:write」这条外部依赖没有落点"
        "（关单后就会蒸发 —— 正是「'有意不做'被读成'已解决'」的形态）"
    )
    problems: list[str] = []
    for blocker in blockers:
        where = f"external_blockers::{blocker.get('id')}"
        if len(str(blocker.get("owner_action") or "")) < 40:
            problems.append(f"{where}：`owner_action` 太短 ⇒ 缺少 owner 可执行的**命令**")
        if "gh " not in str(blocker.get("owner_action") or "") and "ghcr.io" not in str(blocker.get("owner_action") or ""):
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
