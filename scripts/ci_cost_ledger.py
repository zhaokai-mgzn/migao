#!/usr/bin/env python3
"""ci_cost_ledger.py — 生成/复算 CI 成本台账（issue #3507 ②）。

## 这个脚本做什么（以及**不**做什么）

它**只测量与搬运读数**，不发明策略数字：

- **测量**：按 workflow 采样最近 `--runs-per-workflow`（默认 8）次 **completed `pull_request`**
  run 的每个 job，算 `n` / `median` / `p90` / `max`（秒）——来源
  `gh api repos/<owner>/<repo>/actions/runs?event=pull_request&status=completed` +
  `…/runs/<id>/jobs`（**逐次现取**，不引二手数字）。
- **硬杀上限（`hard_kill_seconds`）**：取自 **workflow 自身**的 `timeout-minutes × 60`
  （仓库里**已有**的、可评审的值）——**不是**本脚本发明的。判据会拿现取 YAML 复比，手抄腐烂即红。
- **目标预算（`budget_seconds`）**：**owner 裁定（2026-09-26）= 该腿实测 p90 向上取整**。
  ⇒ 预算是**读数的函数**，不是人手填的数；取不到读数（n < 3）的腿**保持 `null` + 显式留白**，不编数。
- **超预算判红**：新一次实测的 p90 上取整 **>** 台账里**已冻结**的预算 ⇒ 本命令**非零退出且不写台账**
  （不许静默抬预算），并要求**先查「新增」开销**（钉与负载无关的计数），
  **不得**靠抬 `timeout-minutes` 交差（与 #5365 同源口径）；
  确有必要抬 ⇒ 显式 `--accept-raise`（重冻结为现取 p90，改动在 diff 里可见）。
- **required 口径**：取 `required_status_snapshot.json`（分支保护快照），**不猜**。

    python3 scripts/ci_cost_ledger.py --measure                  # 现取 → 重写台账（超预算则退出 1 且不写）
    python3 scripts/ci_cost_ledger.py --measure --accept-raise   # 显式同意把超预算的腿重冻结为现取 p90
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO / ".github" / "workflows"
LEDGER_PATH = REPO / "tests" / "unit_ci_workflows" / "ci_cost_ledger.json"
SNAPSHOT_PATH = REPO / "tests" / "unit_ci_workflows" / "required_status_snapshot.json"
REPO_SLUG = "zhaokai-mgzn/migao"

#: 评测型流水线（**非 PR 触发**，workflow_dispatch）—— 月度频率读数用于 ② 的「频率上限」议题。
EVAL_WORKFLOWS = ("agent-eval.yml", "agent-eval-adversarial.yml", "xiaobu-acceptance.yml")

#: 预算口径的两个取值（owner 裁定 2026-09-26；判据按**逐字相等**核对，改动必须两边同改）。
BUDGET_STATUS_MEASURED = "已裁定：预算 = 实测 p90（向上取整）"
BUDGET_STATUS_NO_READING = "无读数：不编预算（显式留白）"


def gh_json(args: list[str]):
    proc = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"gh api 失败（{' '.join(args)}）：{(proc.stderr or '').strip()[:300]}")
    return json.loads(proc.stdout or "null")


def _pr_config(doc: dict) -> dict | None:
    on = doc.get("on") if isinstance(doc.get("on"), dict) else doc.get(True)
    if not isinstance(on, dict) or on.get("pull_request") is None:
        return None
    pr = on["pull_request"]
    return pr if isinstance(pr, dict) else {}


def _required_names() -> set[str]:
    return set(json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))["contexts"])


def _legs_skeleton() -> dict[str, dict]:
    """从**现取 YAML** 取每一条 PR 触发腿：job 名 / 硬杀上限 / 是否被路径门控。"""
    legs: dict[str, dict] = {}
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if _pr_config(doc) is None:
            continue
        for jid, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict) or "runs-on" not in job:
                continue
            timeout = job.get("timeout-minutes")
            legs[f"{path.name}::{jid}"] = {
                "workflow": path.name,
                "job": str(jid),
                "check_name": str(job.get("name") or jid),
                "hard_kill_seconds": (int(timeout) * 60) if timeout else None,
                "hard_kill_source": (f"workflow `timeout-minutes: {int(timeout)}`" if timeout
                                     else "workflow 未声明 `timeout-minutes`（GitHub 默认 360min）"),
            }
    return legs


def _sample_legs(runs_per_workflow: int) -> tuple[dict[tuple[str, str], list[float]], dict[str, list[float]]]:
    """按 `(workflow 文件名, **检查名**)` 采样 —— Actions 的 `/jobs` 只给显示名（= check name），
    不给人 YAML 里的 job id ⇒ 归属靠后面用现取 YAML 的 `name:` 反查（两边同源，不猜）。"""
    runs = []
    for page in (1, 2, 3):
        batch = gh_json([f"repos/{REPO_SLUG}/actions/runs?event=pull_request&status=completed&per_page=100&page={page}"])
        runs.extend(batch.get("workflow_runs") or [])
        if len(batch.get("workflow_runs") or []) < 100:
            break
    seen: dict[str, list[dict]] = {}
    for run in sorted(runs, key=lambda r: r["created_at"], reverse=True):
        bucket = seen.setdefault(run["path"], [])
        if len(bucket) < runs_per_workflow:
            bucket.append(run)
    per_leg: dict[tuple[str, str], list[float]] = {}
    per_flow: dict[str, list[float]] = {}
    for path, bucket in seen.items():
        for run in bucket:
            payload = gh_json([f"repos/{REPO_SLUG}/actions/runs/{run['id']}/jobs?per_page=100"])
            total = 0.0
            for job in payload.get("jobs") or []:
                started, done, conclusion = job.get("started_at"), job.get("completed_at"), job.get("conclusion")
                if not started or not done or conclusion == "skipped":
                    continue
                seconds = (datetime.strptime(done, "%Y-%m-%dT%H:%M:%SZ")
                           - datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ")).total_seconds()
                total += seconds
                per_leg.setdefault((Path(path).name, str(job["name"])), []).append(seconds)
            if total > 0:
                per_flow.setdefault(Path(path).name, []).append(total)
    return per_leg, per_flow


def _stats(values: list[float]) -> dict:
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "median_seconds": round(statistics.median(ordered), 1),
        "p90_seconds": round(ordered[min(len(ordered) - 1, int(0.9 * (len(ordered) - 1)))], 1),
        "max_seconds": round(ordered[-1], 1),
    }


def ceil_budget(p90_seconds: float) -> int:
    """预算 = 实测 p90 **向上取整**（owner 裁定 2026-09-26）。"""
    return int(math.ceil(p90_seconds))


def budget_breaches(frozen_budgets: dict, fresh_p90: dict) -> list[dict]:
    """**纯函数**：哪些腿的新实测 p90 上取整 > 台账里已冻结的预算。

    `frozen_budgets` = `{leg_id: 已冻结预算秒}`（非整数/缺项的腿不判 —— 那是「无读数、不编预算」）。
    `fresh_p90` = `{leg_id: 本次实测 p90 秒}`。
    抽成纯函数是为了让判据能用**合成数据**直接证明「超预算会红」（不必等真实 CI 变慢）。
    """
    breaches: list[dict] = []
    for leg_id, p90 in sorted(fresh_p90.items()):
        budget = frozen_budgets.get(leg_id)
        if not isinstance(budget, int):
            continue
        if ceil_budget(p90) > budget:
            breaches.append({
                "id": leg_id,
                "budget_seconds": budget,
                "new_p90_seconds": p90,
                "new_p90_ceil": ceil_budget(p90),
            })
    return breaches


def _eval_cadence() -> dict:
    """评测型流水线的**实测**月度触发次数（`workflow_dispatch` 为主 ⇒ 读数=人跑的频率）。"""
    out: dict[str, dict[str, int]] = {}
    for name in EVAL_WORKFLOWS:
        try:
            payload = gh_json([f"repos/{REPO_SLUG}/actions/workflows/{name}/runs?per_page=100"])
        except SystemExit:
            continue
        counts: dict[str, int] = {}
        for run in payload.get("workflow_runs") or []:
            counts[run["created_at"][:7]] = counts.get(run["created_at"][:7], 0) + 1
        out[name] = dict(sorted(counts.items()))
    return out


def _previous_legs() -> dict[str, dict]:
    """上一版台账的腿（用于取**已冻结预算**做超预算判定）。"""
    if not LEDGER_PATH.exists():
        return {}
    old = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    return {leg["id"]: leg for leg in old.get("legs") or []}


ATTRIBUTION_POLICY = {
    "rule": ("某腿**超出预算**（新实测 p90 上取整 > 台账里已冻结的预算）⇒ `--measure` **非零退出且不写台账**"
             "（不许静默抬预算；预算是读数的函数，不是人手填的数）"),
    "what_to_check_first": ("先查**新增**开销 —— 钉与负载无关的计数：新判据文件数 / 真库 `initdb` 次数 / "
                            "语料真解析次数 / 新增依赖安装；**不要**用抬 `timeout-minutes` 交差"
                            "（与 #5365 同源口径：上限是值班判据，不是成本成绩单）"),
    "how_to_raise": ("确有必要抬预算 ⇒ 显式 `python3 scripts/ci_cost_ledger.py --measure --accept-raise`"
                     "（把该腿预算重冻结为现取 p90，改动在 diff 里可见），并在 PR / 追踪单上写明为什么"),
    "enforced_where": ("超预算判红在**能读 Actions API 的环境**（本机 / attended）生效；CI 的 "
                       "`ci workflow helper unit tests` 读不到历史时长 ⇒ 它只锁「预算 == 实测 p90 上取整」"
                       "这条**文件不变式**（判据 = tests/unit_ci_workflows/test_ci_cost_ledger.py）"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--measure", action="store_true", help="现取 gh API 并重写台账")
    parser.add_argument("--runs-per-workflow", type=int, default=8)
    parser.add_argument("--accept-raise", action="store_true",
                        help="超预算时**显式**同意把预算重冻结为现取 p90（默认拒绝并退出 1）")
    args = parser.parse_args()
    if not args.measure:
        parser.print_help()
        return 2

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    required = _required_names()
    skeleton = _legs_skeleton()
    per_leg, per_flow = _sample_legs(args.runs_per_workflow)
    previous = _previous_legs()

    fresh: dict[str, dict] = {}
    for leg_id, base in skeleton.items():
        samples = per_leg.get((base["workflow"], base["check_name"])) or []
        if len(samples) >= 3:
            fresh[leg_id] = _stats(samples)

    frozen_budgets = {lid: leg["budget_seconds"] for lid, leg in previous.items()
                      if isinstance(leg.get("budget_seconds"), int)}
    breaches = budget_breaches(frozen_budgets, {lid: st["p90_seconds"] for lid, st in fresh.items()})
    if breaches and not args.accept_raise:
        print("❌ 超预算（预算 = 台账里已冻结的实测 p90 上取整）—— 本命令**不写台账**：", file=sys.stderr)
        for row in breaches:
            print(f"   · {row['id']}：预算 {row['budget_seconds']}s / 现取 p90 {row['new_p90_seconds']}s"
                  f"（上取整 {row['new_p90_ceil']}s）⇒ 超 {row['new_p90_ceil'] - row['budget_seconds']}s",
                  file=sys.stderr)
        print(f"\n{ATTRIBUTION_POLICY['what_to_check_first']}\n{ATTRIBUTION_POLICY['how_to_raise']}",
              file=sys.stderr)
        return 1

    legs = []
    for leg_id, base in sorted(skeleton.items()):
        samples = per_leg.get((base["workflow"], base["check_name"])) or []
        stats = fresh.get(leg_id)
        if stats:
            budget, status = ceil_budget(stats["p90_seconds"]), BUDGET_STATUS_MEASURED
            basis = f"budget = ceil(measured.p90_seconds={stats['p90_seconds']}) @ {now}"
        else:
            budget, status = None, BUDGET_STATUS_NO_READING
            basis = (f"现取 n={len(samples)} < 3（本腿多为 skipped/未触发）⇒ **不编预算**，"
                     "保持显式留白")
        legs.append({
            "id": leg_id,
            **base,
            "required": base["check_name"] in required,
            "measured": stats,
            "measure_status": "ok" if stats else f"样本不足（现取 n={len(samples)}）",
            "budget_seconds": budget,
            "budget_status": status,
            "budget_basis": basis,
        })

    ledger = {
        "schema": "ci-cost-ledger/v1",
        "issue": "#3507",
        "what": (
            "每条 PR 触发的 CI 腿：**实测**近期时长 + 显式上限 + 目标预算 + required 口径。"
            "上限 = 该腿自己声明的 `timeout-minutes`（硬杀开关，见 `hard_kill_source`）；"
            "预算 = 该腿**实测 p90 向上取整**（owner 裁定 2026-09-26）；"
            "两者都由 tests/unit_ci_workflows/test_ci_cost_ledger.py 与现取 YAML / 读数复比。"
        ),
        "judged_by": "tests/unit_ci_workflows/test_ci_cost_ledger.py",
        "measured": {
            "at": now,
            "source": f"gh api repos/{REPO_SLUG}/actions/runs?event=pull_request&status=completed",
            "event": "pull_request",
            "runs_per_workflow": args.runs_per_workflow,
            "recompute": "python3 scripts/ci_cost_ledger.py --measure",
        },
        "attribution_policy": ATTRIBUTION_POLICY,
        "workflow_totals": {
            name: {"n": len(vals), **_stats(vals)} for name, vals in sorted(per_flow.items())
        },
        "legs": legs,
        "eval_cadence": {
            "what": "评测型流水线（**非 PR 触发**）每月**实测**触发次数 —— 频率议题的读数基线",
            "source": f"gh api repos/{REPO_SLUG}/actions/workflows/<wf>/runs?per_page=100",
            "runs_per_month": _eval_cadence(),
        },
        "policy_decisions": [
            {
                "id": "eval-monthly-frequency-cap",
                "status": "已裁定：有意不设上限（只登记手动触发现状）",
                "question": "normal / adversarial 评测的**月度频率上限**定为多少？",
                "decision": (
                    "**不设硬上限**，只登记现状：`agent-eval.yml` 与 `agent-eval-adversarial.yml` 现取"
                    "**都只有 `workflow_dispatch`**（无 schedule / 无自动触发面）⇒ 频率 = 人跑的频率，"
                    "**上限本来就撞不到**，设一个数只会是空转的管理数字。"
                ),
                "reopen_condition": (
                    "任一评测 workflow 恢复/新增**自动触发**（`schedule` / `push` / `pull_request` / "
                    "`workflow_call` 被自动面调用）⇒ **重开本裁定**，届时上限才有可撞的对象"
                ),
                "evidence": "见 `eval_cadence.runs_per_month`（实测月度次数）与各 workflow 的 `on:`（现取）",
                "decided_by": "用户裁定 2026-09-26（经集成侧转达）",
            },
            {
                "id": "per-leg-target-budget",
                "status": "已裁定：预算 = 实测 p90（向上取整），超了红",
                "question": "各腿的**目标预算**（低于硬杀上限的期望值）如何取？",
                "decision": (
                    "预算 = 该腿**实测 p90 向上取整**（读数的函数，不是人手填的数）；取不到读数（n < 3）的腿"
                    "**保持留白**、不编数。新实测 p90 上取整 **>** 已冻结预算 ⇒ `--measure` **非零退出且不写台账**，"
                    "并要求**先查「新增」开销**、**不得**靠抬 `timeout-minutes` 交差（见 `attribution_policy`）。"
                ),
                "reopen_condition": "预算口径本身变更（例如改用 p95 或引入分位数以外的口径）时重开",
                "decided_by": "用户裁定 2026-09-26（经集成侧转达）",
            },
        ],
        "external_blockers": [
            {
                "id": "ghcr-prebuilt-images",
                "what": "评测栈 GHCR 预构建镜像（admin-api 与分支无关 ⇒ 可复用；栈步骤实测约 210s，其中构建占大头）",
                "why_external": "需要 `packages: write` —— 本仓 CI token 不具备该权限（前序调查结论「需新权限」）",
                "owner_action": (
                    "授予 packages 写权限后重启本项。**命令（CLI 身份的 token）**："
                    "`gh auth refresh -h github.com -s write:packages`（随后 `gh auth status` 应显示该 scope）；"
                    "**仓库侧设置**（需 admin）：Settings → Actions → General → Workflow permissions 允许 "
                    "write，或在容器 job 里显式声明 `permissions: packages: write`。"
                    "⚠️ 上述两条哪一条是必需，取决于落地时用哪个身份发镜像 —— **未验证**"
                    "（本包按用户裁定**不尝试**该操作，故没有实证）。"
                ),
                "grant_verified": False,
                "restart_condition": (
                    "① `gh auth status` 显示 `write:packages`（或仓库允许 `permissions: packages: write`）"
                    "② 一次真实 `docker push ghcr.io/<owner>/…` 成功 ③ 再按 "
                    "docs/testing/eval-pipeline-performance.md「GHCR 拆分建议」只做 admin-api 一档，"
                    "并保留现有回落路径 + 用其判定行做前后对照（不满足前置就不上镜像化）"
                ),
                "carrier": "docs/testing/eval-pipeline-performance.md（§2.7「GHCR 预构建镜像」行的 ⏸ 登记）",
                "issue": "#3507（第 ③ 项）",
            }
        ],
    }
    LEDGER_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with_measure = sum(1 for leg in legs if leg["measured"])
    print(f"✅ 已重写 {LEDGER_PATH.relative_to(REPO)}：腿 {len(legs)} 条"
          f"（其中有实测读数 {with_measure} 条 / 有预算 {sum(1 for x in legs if x['budget_seconds'])} 条）"
          f"/ required {sum(1 for leg in legs if leg['required'])} 条 @ {now}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
