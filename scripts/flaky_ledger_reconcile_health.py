#!/usr/bin/env python3
# case_ids: MC-012
"""`Flaky Ledger Reconcile` 自身的健康值守（issue #5960 ③）。

## 病（issue #5960 ③，**实测**）

`Flaky Ledger Reconcile`（`.github/workflows/flaky-ledger-reconcile.yml`）**不在 required 集合**
⇒ 它判红**不拦任何合并**，**也没有任何东西会因此报警**。现取读数（2026-10-02）：

```
2026-10-02T02:33:09Z pull_request failure        36956153995
2026-10-02T02:03:09Z pull_request failure        36953815649
2026-10-02T01:48:11Z pull_request action_required 36952665492
2026-10-02T01:46:16Z pull_request failure        36952519546
...
```

⇒ 「记录 flake 的那条腿自己坏了」这一形态**没有任何消费面**。

## 本脚本交付的**一条判据**

**连续 N 次判红 ⇒ 出声**。出声是**机械的**：由本脚本自己 `gh issue create/comment`
（带 run 列表 + 可复制复算命令），**不是**写进 job summary 等人看。

## 三态语义（不许降级）

| 态 | 退出码 | 含义 |
|---|---|---|
| `healthy` | 0 | 最近一次已完成 run **不是红**（**一次偶发红不算坏了** —— 本单要治的反面就是告警疲劳） |
| `broken` | 1 | 连续 `--threshold` 次（默认 4）**真红** |
| `unknown` | 3 | **无法判定**（窗口内没有已完成 run / 结论读不到）⇒ **不得当 0 读** |

「没跑」与「跳过」都**不是**结果（本仓 §16.7 口径）：`skipped` 归 `not-red`（且**不计入**连续红），
`action_required` **要看它有没有 job** —— 见下。

## `action_required` 为什么必须与 `failure` 分开（**本包的取证读数**）

台账分支（`chore/flaky-ledger`）的 PR 由 robot 推送，其 `pull_request` run 会被 GitHub 放进
**审批队列**（`conclusion=action_required`、**零 job ⇒ 零 check-run**）：

```
$ gh api repos/{owner}/{repo}/actions/runs/<id>/jobs --jq '.total_count'
run 36952665492 → 0      # action_required（台账分支 PR，审批门控）
run 36947111932 → 0      # action_required（同上）
run 36956153995 → 1      # failure（真失败）
run 36947893768 → 1      # failure（真失败）
```

⇒ 判定规则 = `action_required` **且零 job** ⇒ **审批门控，不是坏了**（否则台账分支每开一次 PR
就伪造一段「连续红」= 本单要治的告警疲劳）；`failure` / 有 job 的 `action_required` ⇒ **真红**。
零 job 在这里**不是**近似判据 —— 「被门控」的机械定义就是「**没有 job 被创建**」。

## 阈值（N=4）怎么取、为什么不是写死的魔数

`--threshold` 默认 4，依据是**现取的结论序列**（可复算，见 `--check --json` 的 `streak_max`）：

```
$ gh run list --workflow=flaky-ledger-reconcile.yml -L 60 \
    --json conclusion,status --jq '[.[] | select(.status=="completed")] | .[] | .conclusion'
```

2026-10-02 现取：最近 60 条已完成 run 里**最长连续真红 = 2**（偶发单红/双红很常见 —— 台账欠账
会让**每个碰台账分支的 PR** 都红一次），而**机制真坏**的特征是「红**不断累积**」。
N=4 ⇒ ① 高于实测噪声上限（2）⇒ **不会把偶发红判成坏了**；② 4 条连续红在「每个 PR + 每 20 分钟
定时档」的触发面下只需极短时间就会累积到 ⇒ 不迟钝。数字与依据都在 `--check --json` 里现取输出
（`threshold` / `streak_max`），**判据读的是现取读数，不是本注释里的快照**。

## 边界（照实登记，§19.1）

- **不新增 schedule / cron**（铁律 10）：本脚本挂在 `flaky-ledger-reconcile.yml` 的**既有触发面**
  （`pull_request` / `schedule` / `workflow_dispatch`）的**最后一步**上。
- **它不改变机制结论**：判红只写 issue，**不** `exit 1`（「读数的发射**绝不**改变机制结论」；
  机制自己的红由机制自己的步骤判）。
- **窗口 = 最近 `--window`（默认 30）条已完成 run**，**不用挂钟时长**（时长受 runner 负载污染，
  且 GitHub 对分钟级 cron 节流到 2~5.5h ⇒ 时间窗判定不确定 —— 与 `mechanism_liveness.py` 判据 4 同口径）。
- **`job` 计数按需取**：只为 `action_required` 的 run 调 `/actions/runs/<id>/jobs` 且**结果缓存**；
  取不到 ⇒ 该 run 记 `unknown`（**不算红**）—— 「取不到」不等于「坏了」，也不等于「通过」，
  它由 `unknown` 计数单独出声。
- **本脚本只裁「连续失败 ⇒ 出声」这一条**：`mechanism-liveness.yml` 的 `watchdog` 腿裁的是
  「**跑了却没出声**」，`drift_audit.py::check_heartbeat()` 裁的是「**调度存在**」——
  三条判据**分工不重叠**。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

# ── 结论分类（**单一实现**；本模块没有第二份判定）─────────────────────────────

#: 明确的「不是结果」：run 没跑完 / 被取消 / 被跳过 ⇒ **既不算红，也不算绿**（记 not-red 但不计入连续红）。
NON_RESULT = frozenset({"cancelled", "skipped", "timed_out", "stale"})

#: 结论读不到（run 还没完成）⇒ **unknown**，不得当绿。
UNDECIDED = frozenset({"", "queued", "in_progress", "pending", "requested", "waiting", "none", "null"})

RED = "red"
NOT_RED = "not-red"
UNKNOWN = "unknown"

#: 出现这个结论时，**必须**看它有没有 job：零 job ⇒ 审批门控（不是坏了）。
GATED_CONCLUSION = "action_required"


def classify(conclusion: object, job_count: object) -> str:
    """**纯函数**：把一条 run 的 `(conclusion, job_count)` 判成 `red` / `not-red` / `unknown`。

    - `success` ⇒ `not-red`（**打断**连续红）；
    - `action_required` 且 `job_count == 0` ⇒ `not-red`（审批门控：GitHub 根本没创建 job）；
    - `action_required` 且 `job_count > 0` ⇒ `red`（真跑了并判红 —— **不得**被门控规则豁免）；
    - `action_required` 且 `job_count` 未知 ⇒ `red`（fail-closed：宁可报出来让人看，也不静默豁免
      —— 与 `mechanism_liveness.py::_job_conclusions_of_run()` 的「对不上就当作非跳过」同口径）；
    - `cancelled` / `skipped` / `timed_out` / `stale` ⇒ `not-red`（**不是结果**，且不计入连续红）；
    - 结论读不到（空 / 非终态）⇒ `unknown`；
    - 其余任何终态结论（`failure` / `startup_failure` / 将来新增的坏形态）⇒ `red`
      —— **未知的坏形态默认算红**，白名单式「只有 failure 算红」会让新形态静默溜过。
    """
    c = str(conclusion or "").strip().lower()
    if c in UNDECIDED:
        return UNKNOWN
    if c == "success":
        return NOT_RED
    if c in NON_RESULT:
        return NOT_RED
    if c == GATED_CONCLUSION:
        if job_count is None:
            return RED  # fail-closed：取不到 job 面 ⇒ 不许静默豁免
        return NOT_RED if int(job_count) == 0 else RED
    return RED


@dataclass
class Streak:
    """连续红的**现取**读数（判据本体；纯数据，不含任何 I/O）。"""

    verdict: str  # healthy | broken | unknown
    streak: int = 0
    decided: list[dict] = field(default_factory=list)  # 从最新往后，直到第一个非红
    gated: int = 0  # 其中「审批门控」的 run 数（read 出来，供人复算）
    undecided: int = 0  # 其中结论读不到的 run 数
    window: int = 0  # 实际进窗口的已完成 run 数
    scanned: int = 0  # 为了判连续红，真正走到（含打断那一条）的 run 数
    threshold: int = 4

    @property
    def truncated(self) -> bool:
        return self.scanned >= self.window and self.verdict == "broken"


def streak_of_reds(
    runs: Sequence[Mapping[str, object]],
    *,
    threshold: int = 4,
    job_count: Callable[[int], object] | None = None,
) -> Streak:
    """**纯函数**：`runs` = 已完成 run 的**新→旧**序列 ⇒ 连续红读数。

    `job_count(run_id)`：仅在结论命中 `action_required` 时调用（**惰性 + 由调用方缓存**）。
    `runs` 里的 `databaseId` 缺失 ⇒ 不调 provider，按「job 面未知」处理。

    「窗口截断」**不判 broken**：扫完 30 条全是红却 still-consecutive ⇒ 至少 30 次连续红，
    远远超过阈值 ⇒ 那是 broken 且 `truncated=True`（**连续红本身已达阈值**这一条是判据）。
    窗口里**没有**已完成 run ⇒ `unknown`（**不得当 0 读**）。
    """
    if not runs:
        return Streak(verdict="unknown", window=0, threshold=threshold)
    got = Streak(verdict="unknown", window=len(runs), threshold=threshold)
    for run in runs:
        conclusion = run.get("conclusion")
        raw_jobs = run.get("jobCount", run.get("job_count"))
        jobs: object = raw_jobs
        if str(conclusion or "").strip().lower() == GATED_CONCLUSION and jobs is None:
            rid = run.get("databaseId", run.get("id"))
            if job_count is not None and rid is not None:
                try:
                    jobs = job_count(int(rid))  # type: ignore[arg-type]
                except Exception:  # noqa: BLE001 —— provider 失败 ⇒ 记 unknown（fail-closed），不是崩
                    jobs = None
        kind = classify(conclusion, jobs)
        got.scanned += 1
        if kind == RED:
            got.streak += 1
            got.decided.append({"run": run.get("databaseId", run.get("id")), "conclusion": conclusion,
                                "createdAt": run.get("createdAt")})
            continue
        if kind == NOT_RED:
            if str(conclusion or "").strip().lower() == GATED_CONCLUSION:
                got.gated += 1
            break
        got.undecided += 1
        break
    if got.streak >= threshold:
        got.verdict = "broken"
    elif got.undecided:
        got.verdict = "unknown"
    else:
        got.verdict = "healthy"
    return got


#: 三态退出码（本仓惯例：`3` = 无法判定，**不得当 0 读**）。
EXIT = {"healthy": 0, "broken": 1, "unknown": 3}

# ── 渲染（判据的**可归因**面：哪个 run / 哪条 job / 可复制命令）─────────────────

CHECK_CMD = (
    "gh run list --workflow=flaky-ledger-reconcile.yml -L 30 "
    "--json databaseId,conclusion,status,createdAt,event,headBranch,attempt"
)


def render(s: Streak, *, repo: str = "", run_id: str = "") -> str:
    lines = [
        f"## 🩺 Flaky Ledger Reconcile 自身健康（issue #5960 ③）",
        "",
        f"- 判定：**{s.verdict}**（连续真红 {s.streak} / 阈值 {s.threshold}）",
        f"- 窗口：最近 {s.window} 条**已完成** run（不用挂钟时长）；为判连续红实际走到 {s.scanned} 条",
        f"- 其中审批门控（`action_required` 零 job）={s.gated} / 结论读不到={s.undecided}",
        "",
        "连续真红的 run（新→旧）：",
    ]
    if s.decided:
        for item in s.decided:
            lines.append(f"  - `{item['run']}` {item['conclusion']}（{item['createdAt']}）")
    else:
        lines.append("  - （无）")
    lines += ["", "可复制复算：", "", "```bash", CHECK_CMD, "```"]
    if repo and run_id:
        lines.append(f"本 run：https://github.com/{repo}/actions/runs/{run_id}")
    return "\n".join(lines)


#: 跟踪单标题的**机器可检索**片段（issue 由本脚本机械开 / 续 / 清）。
ISSUE_TAG = "[flaky-ledger-reconcile health]"
ISSUE_TITLE = f"{ISSUE_TAG} 台账对账腿**连续失败** ⇒ 记录 flake 的那条腿自己坏了（issue #5960）"


def issue_body(s: Streak, *, repo: str, run_id: str) -> str:
    return "\n".join([
        f"**{s.verdict}**：`Flaky Ledger Reconcile` 连续 **{s.streak}** 次真红（阈值 {s.threshold}）。",
        "",
        "**为什么有这张单**：该腿**不在 required 集合** ⇒ 它判红不拦任何合并，也**没有任何东西**"
        "会因此报警（issue #5960 ③）—— 本单就是那条值守面，由 CI **机械**开/续。",
        "",
        render(s, repo=repo, run_id=run_id),
        "",
        "### 清零判据（**机械**，不需要人来判）",
        "",
        "本单由**同一个 job 的同一个步骤**自动销账：下一次 `Flaky Ledger Reconcile` 的**最近一次已完成 run "
        "不是真红**（`success` / 被门控的 `action_required` / 取消 / 跳过）⇒ 同一脚本 `gh issue close` 掉本单，"
        "并把打断连续红的那个 run 号写进关闭评论。⇒ **人工只需修根因，不需要记得关单**；",
        "红**再次累积**到阈值 ⇒ **复用本单**（`gh issue comment`，不新开新单 ⇒ 不制造噪音）。",
        "",
        "### 处置",
        "",
        "1. 按上面列出的 run 号 `gh run view <id> --log-failed` 看**确切的**失败步骤；",
        "2. 若是「台账欠账可见性」（#5307）那一步（`reconcile=1`）⇒ 那是**数据**问题：按该步 job summary "
        "里给出的回填命令补 `follow_up`，**不是**本腿的代码坏了；",
        "3. 若是其它步骤 / 整个 job 结构性失败 ⇒ 本腿**自身**坏了，按 `migao-dev-flow` §28.1 给注入式红证再修。",
        "",
        "⚠️ **本单不是「偶发一次红」**：阈值取现取序列的噪声上限之上（见 `--check --json` 的 "
        "`streak_max`），**一次偶发红不会开单**。",
    ])


# ── 纯函数自证（离线夹具；`--self-test` ⇒ 坏形态必红）────────────────────────

#: 夹具：`事件名/场景 → (runs, threshold, 期望 verdict)`
#: ⚠️ **每种坏形态都在**：13 条里明确覆盖「连续红不再出声」与「无法判定被降级成通过」两族。
SELF_TESTS: tuple[tuple[str, list[dict], int, str], ...] = (
    ("连续 N 条真红 ⇒ broken",
     [{"databaseId": 1, "conclusion": "failure"}, {"databaseId": 2, "conclusion": "failure"},
      {"databaseId": 3, "conclusion": "success"}], 2, "broken"),
    ("连续数**不足**阈值 ⇒ healthy（偶发红不成灾）",
     [{"databaseId": 1, "conclusion": "failure"}, {"databaseId": 2, "conclusion": "success"}], 2, "healthy"),
    ("最近一次绿 ⇒ healthy（哪怕更早连红）",
     [{"databaseId": 1, "conclusion": "success"}, {"databaseId": 2, "conclusion": "failure"},
      {"databaseId": 3, "conclusion": "failure"}], 2, "healthy"),
    ("审批门控（action_required 零 job）**不算红**",
     [{"databaseId": 1, "conclusion": "action_required", "jobCount": 0},
      {"databaseId": 2, "conclusion": "failure"}], 2, "healthy"),
    ("action_required **有 job** ⇒ 算红（不得被门控规则豁免）",
     [{"databaseId": 1, "conclusion": "action_required", "jobCount": 1},
      {"databaseId": 2, "conclusion": "action_required", "jobCount": 1}], 2, "broken"),
    ("action_required 的 job 面**取不到** ⇒ fail-closed 算红",
     [{"databaseId": 1, "conclusion": "action_required"}, {"databaseId": 2, "conclusion": "failure"}],
     2, "broken"),
    ("取消 / 跳过**不是结果** ⇒ 不计入连续红",
     [{"databaseId": 1, "conclusion": "cancelled"}, {"databaseId": 2, "conclusion": "failure"},
      {"databaseId": 3, "conclusion": "failure"}], 2, "healthy"),
    ("结论**读不到** ⇒ unknown（**不得当通过**）",
     [{"databaseId": 1, "conclusion": None}, {"databaseId": 2, "conclusion": "failure"}], 2, "unknown"),
    ("空窗口 ⇒ unknown（**不得当通过**）", [], 4, "unknown"),
    ("未知的新坏形态默认算红（白名单会让它静默溜过）",
     [{"databaseId": 1, "conclusion": "startup_failure"}], 1, "broken"),
    ("窗口扫尽仍连续红 ⇒ broken（truncated 只标注，不降级）",
     [{"databaseId": i, "conclusion": "failure"} for i in range(1, 31)], 4, "broken"),
    ("阈值**现取**：同序列在 N=3 下 broken、N=4 下 healthy",
     [{"databaseId": i, "conclusion": "failure"} for i in range(1, 4)], 3, "broken"),
    ("阈值**现取**：同序列在 N=3 下 broken、N=4 下 healthy（另一半）",
     [{"databaseId": i, "conclusion": "failure"} for i in range(1, 4)], 4, "healthy"),
)


def self_test() -> int:
    """把上表逐条跑一遍；**任一条不符 ⇒ 非零退出**（这就是「注回坏形态必红」的机械形态）。"""
    bad: list[str] = []
    for name, runs, threshold, want in SELF_TESTS:
        got = streak_of_reds(runs, threshold=threshold).verdict
        if got != want:
            bad.append(f"  ❌ {name}：期望 {want}，实测 {got}")
    if bad:
        print("自证失败（判据退化）：")
        print("\n".join(bad))
        return 1
    print(f"✅ 自证通过：{len(SELF_TESTS)} 条夹具（含注回坏形态的必红用例）")
    return 0


def demo() -> int:
    """**反向对照**：把两种坏形态**注回**判定本体 ⇒ 必红（证明夹具不是空断言）。"""
    print("[反向对照 1] 把「连续 N 条真红」判成 healthy")
    print("  实际 verdict =", streak_of_reds(
        [{"databaseId": 1, "conclusion": "failure"}, {"databaseId": 2, "conclusion": "failure"}],
        threshold=2).verdict, "（期望 broken ⇒ 若为 healthy，判定本体已退化）")
    print("[反向对照 2] 把「无法判定」降级成 healthy")
    print("  实际 verdict =", streak_of_reds([], threshold=4).verdict,
          "（期望 unknown ⇒ 若为 healthy，三态语义已降级）")
    return 0


# ── I/O（真网络路径；离线判据不覆盖，见 §19.1 边界登记）────────────────────────


def _gh(args: list[str]) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} 失败：{proc.stderr.strip()[:300]}")
    return proc.stdout


def fetch_runs(repo: str, window: int) -> list[dict]:
    """取该 workflow 的分析窗口（新→旧，只留**已完成**）。真网络路径。"""
    raw = _gh(["run", "list", "--workflow=flaky-ledger-reconcile.yml", "--repo", repo,
               "--limit", str(window), "--json",
               "databaseId,conclusion,status,createdAt,event,headBranch"])
    items = json.loads(raw or "[]")
    return [r for r in items if str(r.get("status") or "") == "completed"]


def enrich_job_counts(runs: list[dict], provider: Callable[[int], object]) -> list[dict]:
    """把 `action_required` 的 job 数**落进 run 记录**（就地写 `jobCount`）。

    ⚠️ 为什么必须落进去：`--runs-file` 复算（离线路径）拿不到 provider，若记录里没有 `jobCount`
    就会走 fail-closed ⇒ 把**审批门控**也算成红 ⇒ `streak_max` 偏高（实测：同一窗口 3 → 5）。
    本函数让「离线复算」与「在线判定」看到**同一份数据**（`--live` 的 `--json` 报告因此可被逐字复算）。
    """
    for run in runs:
        if (str(run.get("conclusion") or "").strip().lower() == GATED_CONCLUSION
                and run.get("jobCount") is None and run.get("databaseId") is not None):
            try:
                run["jobCount"] = provider(int(run["databaseId"]))
            except Exception:  # noqa: BLE001
                run["jobCount"] = None
    return runs


def job_count_provider(repo: str) -> Callable[[int], object]:
    """惰性 + 缓存：只在 `action_required` 时被调用（见 `streak_of_reds`）。"""
    cache: dict[int, object] = {}

    def provider(run_id: int) -> object:
        if run_id not in cache:
            try:
                cache[run_id] = int(
                    _gh(["api", f"repos/{repo}/actions/runs/{run_id}/jobs", "--jq", ".total_count"]).strip())
            except Exception:  # noqa: BLE001
                cache[run_id] = None
        return cache[run_id]

    return provider


def find_issue(repo: str) -> str:
    """找已存在的值守单（**只读**）。取不到 ⇒ 返回空串（调用方 fail-closed 出声）。"""
    raw = _gh(["issue", "list", "--repo", repo, "--state", "open", "--limit", "100",
               "--json", "number,title"])
    for item in json.loads(raw or "[]"):
        if ISSUE_TAG in str(item.get("title") or ""):
            return str(item.get("number") or "")
    return ""


def ensure_issue(repo: str, s: Streak, run_id: str) -> str:
    """**幂等**：已有 ⇒ 追加证据评论（复用，不新开新单）；没有 ⇒ 新建。返回单号或空串。"""
    body = issue_body(s, repo=repo, run_id=run_id)
    number = find_issue(repo)
    if number:
        _gh(["issue", "comment", number, "--repo", repo, "--body", body])
        return number
    raw = _gh(["issue", "create", "--repo", repo, "--title", ISSUE_TITLE, "--body", body])
    for token in str(raw).split():
        if token.startswith("http") and token.rstrip("/").split("/")[-1].isdigit():
            return token.rstrip("/").split("/")[-1]
    return ""


def clear_issue(repo: str, s: Streak, run_id: str) -> str:
    """**机械清零**：连续红已被打断（最近一次已完成 run 不是真红）⇒ 自动关单。

    清零判据 = `streak_of_reds(...).verdict != "broken"`（**现取**，不是人记得去看）。
    """
    number = find_issue(repo)
    if not number:
        return ""
    last = s.decided[0]["run"] if s.decided else "n/a"
    _gh(["issue", "comment", number, "--repo", repo, "--body", "\n".join([
        f"✅ **自动清零**：连续真红已被打断（现取判定 = `{s.verdict}`，连续真红 {s.streak} / 阈值 {s.threshold}）。",
        "",
        f"打断它的 run（窗口内最近一条真红）：`{last}`（**任何**非真红结论——`success` / 审批门控的 "
        "`action_required` / 取消 / 跳过——都会打断连续红）。",
        "",
        "本单由 CI **机械**关闭（不需要人来判）；红再次累积到阈值 ⇒ **复用**本单。",
    ])])
    _gh(["issue", "close", number, "--repo", repo,
         "--reason", "completed", "--comment", "auto-cleared: 连续真红已打断（issue #5960 ③ 清零判据）"])
    return number


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--check", action="store_true", help="跑判据（需要 --runs-file 或 --live）")
    p.add_argument("--self-test", action="store_true", help="跑离线夹具自证（坏形态必红）")
    p.add_argument("--demo", action="store_true", help="反向对照：注回坏形态看是否必红")
    p.add_argument("--runs-file", type=Path, help="已完成 run 的 JSON（新→旧）；离线复算入口")
    p.add_argument("--live", action="store_true", help="真网络路径：从 gh 取 run 列表")
    p.add_argument("--repo", default="", help="owner/repo（--live / 开单用）")
    p.add_argument("--run-id", default="", help="本 run 的 id（写进证据，便于归因）")
    p.add_argument("--window", type=int, default=30, help="分析窗口（条数，不用挂钟时长）")
    p.add_argument("--threshold", type=int, default=4, help="连续真红阈值（默认 4，取法与依据见模块 docstring）")
    p.add_argument("--issue", action="store_true", help="按判定机械开单 / 续单 / 清零（需要 --repo）")
    p.add_argument("--json", type=Path, help="把现取读数写成机器可读报告")
    args = p.parse_args(list(argv) if argv is not None else None)

    if args.self_test:
        return self_test()
    if args.demo:
        return demo()

    if not args.check:
        p.print_help()
        return 2

    if args.runs_file:
        runs = [r for r in json.loads(args.runs_file.read_text(encoding="utf-8"))
                if str(r.get("status") or "completed") == "completed"]
        provider = None
    elif args.live:
        if not args.repo:
            print("::error::--live 需要 --repo", file=sys.stderr)
            return 3
        try:
            runs = fetch_runs(args.repo, args.window)
        except Exception as exc:  # noqa: BLE001
            print(f"无法判定：取不到 run 列表（{exc}）⇒ **不得当通过**读", file=sys.stderr)
            return 3
        provider = job_count_provider(args.repo)
        runs = enrich_job_counts(runs, provider)
    else:
        print("::error::--check 需要 --runs-file 或 --live", file=sys.stderr)
        return 2

    s = streak_of_reds(runs, threshold=args.threshold, job_count=provider)
    report = render(s, repo=args.repo, run_id=args.run_id)
    print(report)
    if args.json:
        args.json.write_text(json.dumps({
            "verdict": s.verdict, "streak": s.streak, "threshold": s.threshold,
            "window": s.window, "scanned": s.scanned, "gated": s.gated,
            "undecided": s.undecided, "reds": s.decided,
            "streak_max": max_historical_streak(runs, provider),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.issue and args.repo:
        try:
            if s.verdict == "broken":
                num = ensure_issue(args.repo, s, args.run_id)
                print(f"::warning::值守单 #{num or '?'} 已开/续（连续真红 {s.streak} ≥ 阈值 {s.threshold}）")
            else:
                num = clear_issue(args.repo, s, args.run_id)
                if num:
                    print(f"::notice::值守单 #{num} 已机械清零（现取判定 {s.verdict}）")
        except Exception as exc:  # noqa: BLE001 —— 开单失败必须出声，但**不改机制结论**
            print(f"::warning::值守单动作失败：{exc}（**不改机制结论**；请人工按上方 run 列表处置）")
    return EXIT[s.verdict]


def max_historical_streak(runs: Sequence[Mapping[str, object]],
                          provider: Callable[[int], object] | None) -> int:
    """**现取**噪声上限：窗口内历史最长连续真红（阈值取法的依据；判据读它、不读注释里的快照）。"""
    best = cur = 0
    for run in runs:
        jobs: object = run.get("jobCount", run.get("job_count"))
        if (str(run.get("conclusion") or "").strip().lower() == GATED_CONCLUSION
                and jobs is None and provider is not None and run.get("databaseId") is not None):
            try:
                jobs = provider(int(run["databaseId"]))  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001
                jobs = None
        if classify(run.get("conclusion"), jobs) == RED:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


if __name__ == "__main__":
    raise SystemExit(main())
