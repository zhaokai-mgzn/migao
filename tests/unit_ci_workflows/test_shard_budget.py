# case_ids: MC-354
"""分片预算台账的常驻判据（issue #9102：`ci workflow helper unit tests` 分片吃顶被 cancel）。

## 病（2026-11-24 连续两次，不是估算）

required job `ci workflow helper unit tests` 的后半片**跑满 20 分钟被 cancel**
（run `45291734491` / job `138117410585`，GitHub 注释逐字
`The job has exceeded the maximum execution time of 20m0s`）⇒ 分支保护在等它 ⇒ **所有 PR 卡死**。
而 `timeout-minutes` 是**值班判据**、不是成本成绩单（#5203 / #5365 既有口径：
**不许拿抬上限交差**）⇒ 只能把「每片到底跑了多少工时」变成**会红的读数**。

## 台账是什么（`tests/unit_ci_workflows/shard_budget_ledger.json`）

每片**测得的秒数** + **预算上限**，外加**拆片前最重片**的同一口径读数（60% 目标的比较基准）。

读数口径 = **逐用例自耗秒数之和**（`-n 4 --durations=0` 按文件聚合）—— 它是**工作量读数**，
与机器负载无关（§23 G6：降成本的固化**禁挂钟时长**）。墙钟（CI job 秒数）只作证据登记在
`ci_readings` 里，**不参与判定**（runner 噪声会让它假红/假绿；本仓实测过同一片两轮差 40%）。

## 判据（任一不成立 ⇒ 红）

| # | 判据 | 回归时会怎么红 |
|---|---|---|
| 1 | 台账形态齐备（schema / issue / judged_by / unit / policy 四项 / `shards` 非空 / 预算与读数都是正数） | 台账被删空 / 字段被清成空 ⇒ fail-closed 红（空跑成绿是这里最坏的结果） |
| 2 | **片名三方一致**：台账 `shards` 的键 == 现取 `pr-check.yml` matrix 的 `shard` 取值 | 改了 matrix 没改台账（或反之）⇒ 红（新片没有预算 = 那条腿没有牙齿） |
| 3 | **`timeout-minutes` 只许缩短**：现取 `timeout-minutes × 60` **逐值等于** `hard_kill_seconds`，且 `hard_kill_seconds ≤ HARD_KILL_FROZEN_SECONDS` | 抬 timeout 交差 ⇒ 红；抬了没同步台账 ⇒ 也红（两处任一被抬都会红） |
| 4 | **每片预算只许缩短**（`budget_seconds ≤ BUDGET_FROZEN_SECONDS`）**且最重片的预测墙钟 ≤ 拆片前最重片的 60%**（issue #9102 的目标本身：`max(predicted) ≤ 0.6 × pre_split.heaviest_seconds`） | 手抬预算 ⇒ 红；重切没切够（最重片仍 > 60%）⇒ 也红 |
| 5 | **实测与预测都不得越过预算的 80%**：`max(measured_seconds, predicted_seconds) > red_at_ratio × budget_seconds` ⇒ 红（预测 = 现取语料按冻结的 `file_seconds` 聚合；报错里点名该片最重的 3 个文件） | 把重判据挪回最重片 / 新增一份重判据却没重切 ⇒ 红；真读数 ⇒ 绿 |
| 6 | 判据 2~5 的**注入式红证**（各自能单独变红）+ 对照读数（真读数不报） | 谓词恒真/恒假（空断言）⇒ 红 |

## 边界（照实登记，别把"登记了"读成"治住了"）

- 预算的**绝对值**是本机工作量读数（`unit` 字段写明），**不是** CI 墙钟；两者只通过「哪一片更重」的
  **排序**相关 —— 本仓实测过「本机 −20% 没迁移到 CI」（#6164 的第一件读数）⇒ CI 侧读数只登记证据；
- 台账只锁分片的**成本面**，不判任何一条断言的覆盖面（那是 `test_helper_leg_execution_shape.py` 的面）；
- `predicted_seconds` 用**冻结的逐文件读数**：新增判据文件若比 `default_file_seconds` 重得多而台账没登记，
  预测会偏低 —— **照实登记的缺口**，由 `measured_seconds` 那条臂（下一次实测）兜住；
- 判据**不联网**、不读 `origin/main`（CI 的 `fetch-depth` 形态与本判据无关）。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

from unit_ci_workflows import conftest

REPO = Path(__file__).resolve().parents[2]
LEDGER_REL = "tests/unit_ci_workflows/shard_budget_ledger.json"
CI_REL = ".github/workflows/pr-check.yml"
JOB_ID = "ci-workflow-tests"
SCHEMA = "ci-helper-shard-budget/v1"

#: 判红线（实测/预测 > 预算 × 该比值 ⇒ 红）。与台账 `policy.red_at_ratio` 必须逐值相等。
RED_AT_RATIO = 0.8

#: `hard_kill_seconds` 的上限（**只许缩短**）。改大它 = 抬 timeout 交差，必须被评审看到。
#: 现取 = `pr-check.yml` 该 job 的 `timeout-minutes: 20` × 60。
HARD_KILL_FROZEN_SECONDS = 1200

#: 每片预算的上限（**只许缩短**，单位 = 本机 `-n 4` 墙钟秒，见台账 `unit`）。
#: 现取 = 该片实测墙钟的 1.5×（四片 326/342/322/299s ⇒ 预算 490/520/490/450；§23 G6：预算是**冻结登记值**、不是随手现测的挂钟；
#: 判据只在「实测/预测 > 预算 × 0.8」时红，所以 1.5× 给的是 ~20% 的增长余量）。
BUDGET_FROZEN_SECONDS = 520

#: 预算相对拆片前最重片的上界（issue #9102 的要求本身，写成判据 ⇒ 重切"没切够"也红）。
PRE_SPLIT_RATIO = 0.6


def _ledger() -> dict:
    assert (REPO / LEDGER_REL).exists(), (
        f"缺分片预算台账 {LEDGER_REL}（issue #9102）—— 没有它「每片跑了多少工时」没有任何读数"
    )
    return json.loads((REPO / LEDGER_REL).read_text(encoding="utf-8"))


def live_timeout_seconds() -> int | None:
    """现取 `pr-check.yml` 该 job 的 `timeout-minutes × 60`（**不读台账**，两边独立取值才判得出漂移）。"""
    doc = yaml.safe_load((REPO / CI_REL).read_text(encoding="utf-8")) or {}
    job = ((doc.get("jobs") or {}).get(JOB_ID) or {})
    timeout = job.get("timeout-minutes")
    return int(timeout) * 60 if timeout else None


def live_shard_names() -> list[str]:
    """现取 CI matrix 的分片取值（`jobs.<JOB_ID>.strategy.matrix.include[].shard`）。"""
    doc = yaml.safe_load((REPO / CI_REL).read_text(encoding="utf-8")) or {}
    job = ((doc.get("jobs") or {}).get(JOB_ID) or {})
    matrix = ((job.get("strategy") or {}).get("matrix") or {})
    return [str(entry["shard"]) for entry in (matrix.get("include") or [])
            if isinstance(entry, dict) and entry.get("shard")]


def predicted_seconds(ledger: dict, shard_names=None, census=None, weights: dict | None = None) -> dict:
    """每片的**预测工作量**（秒）= 该片判据文件按冻结逐文件读数求和（未登记的文件取默认值）。

    `weights` 是红证注入孔（覆盖 `file_seconds`）：用来证明「一个重文件落进这一片 ⇒ 这一片红」，
    而同一份重量落进**更轻**的片 ⇒ 不红（单变量差分，证明是**分配**在触发判据，不是"重就红"）。
    """
    file_seconds = dict(ledger.get("file_seconds") or {})
    if weights:
        file_seconds.update(weights)
    default = float(ledger.get("default_file_seconds") or 0.0)
    files = conftest._current_test_files() if census is None else set(census)
    names = list(shard_names if shard_names is not None else (ledger.get("shards") or {}).keys())
    works: dict[str, float] = {}
    for name in names:
        try:
            index, count = (int(part) for part in str(name).split("/"))
        except ValueError:
            works[str(name)] = 0.0
            continue
        bucket = [f for f in files if conftest.shard_of(f, count) == index]
        works[str(name)] = sum(float(file_seconds.get(f, default)) for f in bucket)
    # 预测的**单位 = 本机墙钟秒**（与 `measured_seconds` 同单位）= 该片工作量 × `work_to_wall_ratio`。
    # 🔴 **刻意不做份额归一化**：归一化会让「把重文件塞进最重片」把总量一起抬高 ⇒ 该片的预测只涨一点点
    #    （实测过：注入半片预算只让预测从 301 → 358，刚好压在红线下 ⇒ 那是**假牙**）。
    #    绝对工作量 × 固定系数 ⇒ 同一份工作量落进哪一片，只有那一片的预测升高（红证的单变量差分就在这里）。
    ratio = float(ledger.get("work_to_wall_ratio") or 0.0)
    if ratio <= 0:
        return {}
    return {name: round(work * ratio, 1) for name, work in works.items()}


def _heaviest_in_shard(ledger: dict, shard: str, census=None) -> tuple[str, float] | None:
    """该片里**最重**的判据文件（红证与报错文案用）。"""
    file_seconds = ledger.get("file_seconds") or {}
    files = conftest._current_test_files() if census is None else set(census)
    try:
        index, count = (int(part) for part in str(shard).split("/"))
    except ValueError:
        return None
    bucket = [(f, float(file_seconds.get(f, 0.0))) for f in files
              if conftest.shard_of(f, count) == index]
    if not bucket:
        return None
    return max(bucket, key=lambda item: item[1])


def shard_budget_problems(ledger: dict, *, timeout_seconds: int | None, shard_names=None,
                          census=None, weights: dict | None = None,
                          red_at_ratio: float = RED_AT_RATIO,
                          budget_frozen: float = BUDGET_FROZEN_SECONDS,
                          hard_kill_frozen: int = HARD_KILL_FROZEN_SECONDS,
                          pre_split_ratio: float = PRE_SPLIT_RATIO) -> list[str]:
    """判据 1~5 的**谓词本体**（真台账 / 内存构造的坏台账共用同一份；红证可在内存里跑）。"""
    bad: list[str] = []
    if ledger.get("schema") != SCHEMA:
        bad.append(f"台账 schema = {ledger.get('schema')!r}，期望 {SCHEMA!r}（形态漂移 ⇒ 红）")
    for key in ("issue", "judged_by", "unit"):
        if not str(ledger.get(key) or "").strip():
            bad.append(f"台账缺 `{key}`（空串 ⇒ 读者无从复算/归因）")
    policy = ledger.get("policy") or {}
    missing_policy = [k for k in ("red_at_ratio", "hard_kill_rule", "budget_rule", "on_breach")
                      if policy.get(k) in (None, "", {})]
    if missing_policy:
        bad.append(f"台账 `policy` 缺项：{missing_policy}（超预算时无口径可依）")
    if float(policy.get("red_at_ratio") or 0) != float(red_at_ratio):
        bad.append(f"台账 `policy.red_at_ratio` = {policy.get('red_at_ratio')!r} != 判定本体 "
                   f"{red_at_ratio}（两边必须逐值相等，否则红线的位置会静默漂移）")

    shards = ledger.get("shards") or {}
    if not isinstance(shards, dict) or not shards:
        return bad + ["台账 `shards` 为空 ⇒ 每片预算无对象可判（fail-closed 判红）"]

    # ② 片名三方一致：台账 ⇄ 现取 CI matrix
    live = list(shard_names if shard_names is not None else live_shard_names())
    if not live:
        bad.append(f"现取不到 `{CI_REL}::{JOB_ID}` 的 matrix 分片 ⇒ 片名无从核对（fail-closed）")
    elif sorted(shards) != sorted(live):
        bad.append(f"台账片名 {sorted(shards)} != CI matrix {sorted(live)} ⇒ 只改了一边"
                   "（新片没有预算 = 那条腿的成本面没有牙齿）")

    # ③ timeout 只许缩短（两条锁：与现取逐值相等 + 不超过冻结值）
    hard_kill = int(ledger.get("hard_kill_seconds") or 0)
    if hard_kill <= 0:
        bad.append("台账 `hard_kill_seconds` 缺失或非正 ⇒ 「timeout 不得调大」无对象可判")
    if timeout_seconds is None:
        bad.append(f"现取不到 `{CI_REL}::{JOB_ID}` 的 `timeout-minutes` ⇒ 上限无从核对（fail-closed）")
    elif hard_kill and int(timeout_seconds) != hard_kill:
        direction = "调大" if int(timeout_seconds) > hard_kill else "调小"
        bad.append(
            f"`{CI_REL}::{JOB_ID}` 的 `timeout-minutes×60` = {int(timeout_seconds)}s ≠ 台账 "
            f"`hard_kill_seconds` = {hard_kill}s（{direction}了没同步）—— "
            "**不许拿抬 timeout 交差**（#5203 / #5365 口径）：先查新增开销，再谈重切"
        )
    if hard_kill > hard_kill_frozen:
        bad.append(
            f"台账 `hard_kill_seconds` = {hard_kill}s > 冻结上限 {hard_kill_frozen}s ⇒ "
            "**上限只许缩短**（抬它 = 把「被 cancel」推后，问题照旧；改它必须是一个被评审的动作）"
        )

    # ④ 每片预算只许缩短 + ≤ 拆片前最重片的 60%
    pre_split = ledger.get("pre_split") or {}
    heaviest = float(pre_split.get("heaviest_seconds") or 0)
    if heaviest <= 0:
        bad.append("台账缺 `pre_split.heaviest_seconds`（拆片前最重片的实测量）⇒ 60% 目标无对象可判")
    for name in sorted(shards):
        entry = shards.get(name) or {}
        budget = float(entry.get("budget_seconds") or 0)
        measured = float(entry.get("measured_seconds") or 0)
        if budget <= 0:
            bad.append(f"分片 {name} 的 `budget_seconds` 缺失或非正 ⇒ 该片没有预算（成本面空跑）")
            continue
        if budget > budget_frozen:
            bad.append(
                f"分片 {name} 预算 {budget}s > 冻结上限 {budget_frozen}s ⇒ **预算只许缩短**"
                "（抬预算等于把「吃顶」合法化；要抬必须同时改冻结值，一次被评审的动作）"
            )
        if measured <= 0:
            bad.append(f"分片 {name} 缺 `measured_seconds`（实测读数）⇒ 判据 5 只剩预测一条臂")

    # ④b **没切够 ⇒ 红**：最重片的**预测墙钟**必须 ≤ 拆片前最重片的 60%（issue #9102 的要求本身）。
    #    为什么用预测而不是预算：预算是"这一片的上限"（只许缩短），60% 是"重切够不够"的**成绩**；
    #    两者混用会让「切得刚好」立刻 redness（预算 = 实测 × 1.5 时，实测 = 0.67 × 预算 ⇒ 与 80% 线打架）。
    if float(ledger.get("work_to_wall_ratio") or 0) <= 0:
        bad.append("台账缺 `work_to_wall_ratio`（工作量 → 墙钟 的换算系数）⇒ 预测那条臂无对象可判"
                   "（份额归一化会被「往最重片塞重文件」稀释 —— 那是假牙，见 `predicted_seconds` 的注释）")
    predicted = predicted_seconds(ledger, shard_names=list(shards), census=census, weights=weights)
    if heaviest > 0 and predicted:
        top_name = max(predicted, key=predicted.get)
        top_value = float(predicted[top_name])
        bound = round(pre_split_ratio * heaviest, 1)
        if top_value > bound:
            bad.append(
                f"最重片 {top_name} 的预测墙钟 {top_value}s > {pre_split_ratio} × 拆片前最重片 "
                f"{heaviest}s = {bound}s ⇒ **没达到 issue #9102 的「最重片 ≤ 现在 60%」目标**"
                "（重切了但切得不够，不许静默过；夹带进重片的重判据要挪走或再切一片）"
            )

    # ⑤ 实测与预测都不得越过预算的 80%
    for name in sorted(shards):
        entry = shards.get(name) or {}
        budget = float(entry.get("budget_seconds") or 0)
        if budget <= 0:
            continue
        line = red_at_ratio * budget
        measured = float(entry.get("measured_seconds") or 0)
        guess = float(predicted.get(name) or 0)
        for label, value in (("实测", measured), ("预测", guess)):
            if value > line:
                top = _heaviest_in_shard(ledger, name, census=census)
                top_text = (f"；该片最重的判据文件 = {top[0]}（{top[1]}s）" if top else "")
                bad.append(
                    f"分片 {name} 的{label}工作量 {value}s > 预算 {budget}s × {red_at_ratio} = {round(line, 1)}s"
                    f"（片名集合 {sorted(shards)}）{top_text} ⇒ 这一片已到红线的 "
                    f"{round(100 * value / budget, 1)}%：先查**新增**开销（新判据文件 / 真库 initdb 次数 / "
                    "语料真解析次数），再按实测权重重切；**不许**抬 timeout-minutes（#5365 口径）"
                )
    return bad


# ══════════════════════════════════════════════════════════════════════════════════════
# 真读数臂
# ══════════════════════════════════════════════════════════════════════════════════════

def test_ledger_shape_is_complete_and_non_vacuous() -> None:
    """判据 1：台账形态齐备，且每片都有正数的实测与预算（空跑成绿是这里最坏的结果）。"""
    data = _ledger()
    assert shard_budget_problems(data, timeout_seconds=live_timeout_seconds()) == [], (
        "分片预算台账判红：\n  - "
        + "\n  - ".join(shard_budget_problems(data, timeout_seconds=live_timeout_seconds()))
    )
    for name, entry in (data.get("shards") or {}).items():
        assert float(entry.get("measured_seconds") or 0) > 0, f"分片 {name} 没有实测读数 ⇒ 判据退化成空断言"
        assert float(entry.get("budget_seconds") or 0) > 0, f"分片 {name} 没有预算 ⇒ 成本面无对象可判"
    assert len(data.get("file_seconds") or {}) >= 20, (
        "台账的逐文件读数太少（<20 个文件）⇒ 预测那条臂基本等于用默认值 —— "
        "复算命令见台账 `measure.recompute`"
    )


def test_shard_names_are_the_live_matrix() -> None:
    """判据 2：台账片名 == 现取 CI matrix（重切/回切都必须同批改台账）。"""
    data = _ledger()
    live = live_shard_names()
    assert live, "现取不到 CI matrix 分片 ⇒ 本判据会空跑"
    assert sorted((data.get("shards") or {}).keys()) == sorted(live), (
        f"台账片名 {sorted((data.get('shards') or {}).keys())} != CI matrix {sorted(live)}"
        " ⇒ 只改了一边：新片没有预算、旧片预算成了死数据"
    )


def test_timeout_may_only_shrink() -> None:
    """判据 3：`timeout-minutes` 与台账逐值相等，且台账值不超过冻结上限（抬 timeout ⇒ 红）。"""
    data = _ledger()
    problems = shard_budget_problems(data, timeout_seconds=live_timeout_seconds())
    timeout_problems = [p for p in problems if "timeout-minutes" in p or "hard_kill_seconds" in p]
    assert timeout_problems == [], "timeout 判据报红：\n  - " + "\n  - ".join(timeout_problems)


# ══════════════════════════════════════════════════════════════════════════════════════
# 判别力自证（注入式红证 + 对照读数）
# ══════════════════════════════════════════════════════════════════════════════════════

def _live_kwargs() -> dict:
    return {"timeout_seconds": live_timeout_seconds(), "shard_names": live_shard_names()}


def test_red_proof_raising_the_timeout_turns_red() -> None:
    """红证①（issue #9102 要求「把 timeout 调大 ⇒ 有判据能红」）：两条路各自能单独变红。

    ① 只抬 workflow（`timeout-minutes` 10 → 30）⇒ 台账没同步 ⇒ 红；
    ② 连台账一起抬（`hard_kill_seconds` 1200 → 1800）⇒ 撞冻结上限 ⇒ **照样红**。
    """
    data = _ledger()
    kwargs = _live_kwargs()
    assert shard_budget_problems(data, **kwargs) == [], "真读数被判红 ⇒ 谓词恒真，不是判据"

    raised_workflow = dict(kwargs, timeout_seconds=int(kwargs["timeout_seconds"]) + 600)
    problems = shard_budget_problems(data, **raised_workflow)
    assert any("timeout-minutes" in p for p in problems), (
        f"只抬 workflow 的 timeout ⇒ 不报 ⇒ 「不许调大超时」没有判据：{problems}"
    )

    raised_both = copy.deepcopy(data)
    raised_both["hard_kill_seconds"] = int(data["hard_kill_seconds"]) + 600
    problems = shard_budget_problems(raised_both, **dict(kwargs, timeout_seconds=raised_both["hard_kill_seconds"]))
    assert any("只许缩短" in p for p in problems), (
        f"把台账和 workflow 一起抬到 30 分钟 ⇒ 不报 ⇒ 上限可以被静默续期：{problems}"
    )


def test_red_proof_a_heavy_file_landing_in_the_heaviest_shard_turns_red() -> None:
    """红证②：**同一个重文件**落进最重片 ⇒ 红；落进最轻片 ⇒ 不红（单变量差分）。

    这是 issue #9102 的真实回归形态：新判据文件（或把重判据挪回来）落在**已经最重**的那一片。
    """
    data = _ledger()
    kwargs = _live_kwargs()
    predicted = predicted_seconds(data)
    heaviest = max(predicted, key=predicted.get)
    lightest = min(predicted, key=predicted.get)
    assert heaviest != lightest, f"预测读数里最重片与最轻片相同（{predicted}）⇒ 本红证无处落脚"

    budget = float(((data.get("shards") or {}).get(heaviest) or {}).get("budget_seconds") or 0)
    assert budget > 0, "最重片没有预算 ⇒ 红证会退化成空跑"
    heavy_added = round(0.5 * budget, 1)      # 一份"重文件"的量级 = 半片预算

    in_heaviest = _heaviest_in_shard(data, heaviest)
    in_lightest = _heaviest_in_shard(data, lightest)
    assert in_heaviest and in_lightest, "取不到两片里最重的文件 ⇒ 注入点无处落"
    problems = shard_budget_problems(
        data, **kwargs, weights={in_heaviest[0]: in_heaviest[1] + heavy_added})
    assert any(f"分片 {heaviest}" in p and "预测" in p for p in problems), (
        f"重文件落进最重片 {heaviest}（+{heavy_added}s）⇒ 不报 ⇒ 这条判据没有牙齿：{problems}"
    )

    control = shard_budget_problems(
        data, **kwargs, weights={in_lightest[0]: in_lightest[1] + heavy_added})
    assert not any(f"分片 {heaviest}" in p for p in control), (
        f"同一份重量落进**最轻**片 {lightest}，最重片却被判红 ⇒ 判据不是在判「哪一片重」：{control}"
    )


def test_red_proof_raising_a_budget_past_the_frozen_ceiling_turns_red() -> None:
    """红证③：预算只许缩短（抬预算 / 没达到 60% 目标各能单独变红）。"""
    data = _ledger()
    kwargs = _live_kwargs()

    raised = copy.deepcopy(data)
    for entry in raised["shards"].values():
        entry["budget_seconds"] = float(entry["budget_seconds"]) + 120
    problems = shard_budget_problems(raised, **kwargs)
    assert any("只许缩短" in p for p in problems), f"抬预算 ⇒ 不报 ⇒ 只许缩短没有被钉住：{problems}"

    # ③b 「**重切没切够**」⇒ 红：把拆片前最重片的读数读小 10%（等价于这次重切其实没到 60% 目标）
    tight = copy.deepcopy(data)
    pred = predicted_seconds(data)
    tight["pre_split"]["heaviest_seconds"] = round(max(pred.values()) / PRE_SPLIT_RATIO * 0.9, 1)
    problems = shard_budget_problems(tight, **dict(kwargs, budget_frozen=10**6))
    assert any("没达到 issue #9102" in p for p in problems), (
        f"最重片的预测墙钟超过拆片前最重片的 60% ⇒ 不报 ⇒ 「重切没切够」会静默溜过去：{problems}"
    )


def test_red_proof_a_stale_matrix_or_a_vacuous_ledger_turns_red() -> None:
    """红证④：matrix 与台账分片对不上 / 台账被删空 / 缺读数，各能单独变红（fail-closed）。"""
    data = _ledger()
    kwargs = _live_kwargs()
    assert shard_budget_problems({"schema": SCHEMA, "shards": {}}, **kwargs), (
        "台账没有 `shards` ⇒ 不报 ⇒ 分片成本面无对象可判"
    )
    stale = dict(kwargs, shard_names=list(kwargs["shard_names"]) + ["4/4"])
    assert any("!= CI matrix" in p for p in shard_budget_problems(data, **stale)), (
        "matrix 多出一片 ⇒ 不报 ⇒ 新片没有预算也会溜过去"
    )
    no_reading = copy.deepcopy(data)
    for entry in no_reading["shards"].values():
        entry["measured_seconds"] = 0
    assert any("measured_seconds" in p for p in shard_budget_problems(no_reading, **kwargs)), (
        "某片缺实测读数 ⇒ 不报 ⇒ 判据 5 只剩一条臂（且没人知道）"
    )
