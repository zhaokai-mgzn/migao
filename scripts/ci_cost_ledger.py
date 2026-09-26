#!/usr/bin/env python3
"""ci_cost_ledger.py — 生成/复算 CI 成本台账（issue #3507 ②）。

## 这个脚本做什么（以及**不**做什么）

它**只测量与搬运读数**，不发明策略数字：

- **测量**：按 workflow 采样最近 `--runs-per-workflow`（默认 8）次 **completed `pull_request`**
  run 的每个 job，算 `n` / `median` / `p90` / `max`（秒）——来源
  `gh api repos/<owner>/<repo>/actions/runs?event=pull_request&status=completed` +
  `…/runs/<id>/jobs`（**逐次现取**，不引二手数字）。
- **上限（ceiling）**：取自 **workflow 自身**的 `timeout-minutes × 60`（= 那条腿的硬杀开关，
  仓库里**已有**的、可评审的值）——**不是**本脚本发明的预算。判据会拿现取 YAML 复比，
  手抄腐烂即红（见 `tests/unit_ci_workflows/test_ci_cost_ledger.py`）。
- **required 口径**：取 `required_status_snapshot.json`（分支保护快照），**不猜**。
- **不发明**：目标预算 / 评测月度频率上限这类**需要 owner 裁定**的值一律写
  `null` + `budget_status: "待裁定"` + 一条可回答的 `question`。已有台账里的裁定值会被
  **原样保留**（重算读数不会覆盖人的裁定）。

    python3 scripts/ci_cost_ledger.py --measure     # 现取 → 重写 tests/unit_ci_workflows/ci_cost_ledger.json
"""

from __future__ import annotations

import argparse
import json
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


def _questions_from_existing() -> dict[str, dict]:
    """保留上一版台账里**人的裁定**（重算读数绝不覆盖 owner 决定）。"""
    if not LEDGER_PATH.exists():
        return {}
    old = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    return {leg["id"]: leg for leg in old.get("legs") or []}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--measure", action="store_true", help="现取 gh API 并重写台账")
    parser.add_argument("--runs-per-workflow", type=int, default=8)
    args = parser.parse_args()
    if not args.measure:
        parser.print_help()
        return 2

    required = _required_names()
    skeleton = _legs_skeleton()
    per_leg, per_flow = _sample_legs(args.runs_per_workflow)
    previous = _questions_from_existing()

    legs = []
    for leg_id, base in sorted(skeleton.items()):
        samples = per_leg.get((base["workflow"], base["check_name"])) or []
        old = previous.get(leg_id) or {}
        row = {
            "id": leg_id,
            **base,
            "required": base["check_name"] in required,
            "measured": _stats(samples) if len(samples) >= 3 else None,
            "measure_status": ("ok" if len(samples) >= 3
                               else f"样本不足（现取 n={len(samples)}；本腿多为 skipped/未触发）"),
            # ⚠️ owner 裁定字段：一律 `null`（除非上一版已裁定）—— **不发明数字**。
            "budget_seconds": old.get("budget_seconds"),
            "budget_status": ("已裁定" if isinstance(old.get("budget_seconds"), int) else "待裁定"),
            "budget_question": old.get("budget_question") or (
                "这条腿的目标预算（不是硬杀上限）应定为多少？—— 需要 owner 决定；"
                "现取读数见 `measured`，硬杀上限见 `hard_kill_seconds`"
            ),
        }
        legs.append(row)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger = {
        "schema": "ci-cost-ledger/v1",
        "issue": "#3507",
        "what": (
            "每条 PR 触发的 CI 腿：**实测**近期时长 + 显式上限 + required 口径。"
            "上限 = 该腿自己声明的 `timeout-minutes`（硬杀开关，见 `hard_kill_source`），"
            "由 tests/unit_ci_workflows/test_ci_cost_ledger.py 与现取 YAML 逐条复比（手抄腐烂即红）。"
        ),
        "judged_by": "tests/unit_ci_workflows/test_ci_cost_ledger.py",
        "measured": {
            "at": now,
            "source": f"gh api repos/{REPO_SLUG}/actions/runs?event=pull_request&status=completed",
            "event": "pull_request",
            "runs_per_workflow": args.runs_per_workflow,
            "recompute": "python3 scripts/ci_cost_ledger.py --measure",
        },
        "workflow_totals": {
            name: {"n": len(vals), **_stats(vals)} for name, vals in sorted(per_flow.items())
        },
        "legs": legs,
        "eval_cadence": {
            "what": "评测型流水线（**非 PR 触发**）每月**实测**触发次数 —— ② 的「月度频率上限」议题的读数基线",
            "source": f"gh api repos/{REPO_SLUG}/actions/workflows/<wf>/runs?per_page=100",
            "runs_per_month": _eval_cadence(),
        },
        "policy_decisions": [
            {
                "id": "eval-monthly-frequency-cap",
                "status": "待裁定",
                "question": "normal / adversarial 评测的**月度频率上限**定为多少？",
                "why_not_derivable": (
                    "「上限」是策略数字，不是读数：现取只给出**历史频率**（见 `eval_cadence.runs_per_month`）。"
                    "按本仓纪律「不许编一个看起来合理的数」⇒ 记为待裁定，由 owner 拍板后写入本字段。"
                ),
                "decided_by": None,
            },
            {
                "id": "per-leg-target-budget",
                "status": "待裁定",
                "question": "各腿的**目标预算**（低于硬杀上限的期望值）如何取？",
                "why_not_derivable": (
                    "硬杀上限已由 workflow 的 `timeout-minutes` 给出（可复算）；"
                    "「我们希望它多快」属成本-风险取舍（压太紧会把慢 runner 变成假红）⇒ 需 owner 裁定。"
                ),
                "decided_by": None,
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
          f"（其中有实测读数 {with_measure} 条）/ required {sum(1 for leg in legs if leg['required'])} 条 @ {now}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
