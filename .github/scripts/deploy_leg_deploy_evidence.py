#!/usr/bin/env python3
r"""「**这一次真的发生了部署**」的自证（issue #9056）。

## 病（逐字现场，不要转述）

run `45010592767`（`schedule`）的 job 结论是 **success**，而部署步根本没跑：

    Skip if already built (schedule reconcile)   success
    Deploy to SWAS (测试环境)                      skipped

日志逐字：「⛔ 镜像缺失，但 0dced39 最近一次部署是**不可恢复的终态**（结论=failure）——跳过本轮构建部署」。

`[deploy-leg]` 值守单（#9051 / #9040 / #9029）的**清零判据**是「该腿下一次 `conclusion=success`」
⇒ **一次没部署的空转 run 就能把值守单关掉**，而线上仍是旧镜像（实证误导过一次归因）。

## 判据面 = **部署步**结论，不是 job / run 结论

`scripts/deploy_leg_failure_reaction.sh` 的 `clear_leg()` 在关单前调本模块。它读 run 的
`jobs[].steps[]`，只看**部署类步**（名字以 `Deploy ` / `Publish ` 开头；三条镜像腿是
`Deploy to SWAS (测试环境)`，两条发布腿是 `Publish … to SWAS (…)`）：

| 部署类步的结论 | 判定 | 退出码 | 读数 |
|---|---|---|---|
| 全部 `success` | **已部署** | `0` | `DEPLOY_EXECUTED=1` |
| 任一 `skipped` | **未部署**（skip 非 deployed） | `1` | `DEPLOY_EXECUTED=0` |
| 其余（失败/取消/空） | **未部署** | `1` | `DEPLOY_EXECUTED=0` |
| 读不到 jobs / 没有部署类步 | **判不了** | `3` | `DEPLOY_EXECUTED=unknown` |

`3` **不得当 0 读**（会把「没查」读成「确认未部署」），**也不得当 1 读**（会把「判不了」读成
「已部署」）—— 调用方的口径是：**只有 0 才关单**。

## 两个入口（调用方决定用哪个）

* `--run-id <id>`：事件面（`workflow_run` 带着 run id）⇒ 读**那一条** run；
* `--workflow <wf> --sha <7>`：状态面（对账步只落「无漂移：自 <sha>（上次成功部署）」）⇒
  先用 `gh run list` 找到「该腿在该 commit 上的那次部署」，再读它的部署步。

## 离线驱动（守卫测试 / 白天复算都用同一条路）

`ATTEST_JOBS_FILE=<json>` ⇒ **只读该文件、一次 `gh` 都不调**（`--run-id` / `--workflow --sha` 都可配）。
`ATTEST_RUNS_FILE=<json>` 同理给 `gh run list` 的离线替身。

判据 = `tests/unit_ci_workflows/test_deploy_leg_failure_reaction.py` 的
`test_attestation_reads_the_deploy_step_not_the_run_conclusion` 等；
类级元守卫 = `scripts/deploy_leg_close_claim_audit.py check-skip-close`（本模块是它的**行为夹具**对象）。

## 边界（照实登记）

* **不判线上状态**：部署步 success ≠ 线上跑的是它（那两条判据在各腿的
  `Assert running tag == target` / `Assert served sha == deployed sha` 步里，本模块不重复判）。
* **部署类步的识别 = 名字前缀**（`Deploy ` / `Publish `）：新腿若把部署步改成别的名字 ⇒ 判 `3`
  （判不了 ⇒ 不关单），**不会**静默放行 —— 这是有意的 fail-closed 方向。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

#: 部署类步的**名字前缀**（三条镜像腿 `Deploy to SWAS (测试环境)`；两条发布腿 `Publish … to SWAS (…)`）。
DEPLOY_STEP_PREFIXES = ("Deploy ", "Publish ")
#: 「这一轮没部署」的结论 —— 就是 issue #9056 现场的形态。
SKIP_CONCLUSION = "skipped"
#: 「这一次部署成功执行」的结论。
EXECUTED_CONCLUSION = "success"
#: 判不了时的具名读数（**不许**写成 0/1）。
UNKNOWN = "unknown"


def deploy_steps(jobs: object) -> list[tuple[str, str]]:
    """从 `gh run view --json jobs` 的响应里取**部署类步**：`[(名字, 结论), …]`（保序）。"""
    out: list[tuple[str, str]] = []
    if not isinstance(jobs, dict):
        return out
    for job in jobs.get("jobs") or []:
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            name = str(step.get("name") or "")
            if not name.startswith(DEPLOY_STEP_PREFIXES):
                continue
            out.append((name, str(step.get("conclusion") or "")))
    return out


def judge(steps: list[tuple[str, str]]) -> tuple[int, str, str]:
    """→ `(退出码, DEPLOY_EXECUTED 取值, 具名理由)`。三态：0 已部署 / 1 未部署 / 3 判不了。"""
    if not steps:
        return 3, UNKNOWN, (
            "读不到**部署类步**（名字以 `Deploy ` / `Publish ` 开头）⇒ 判不了："
            "「没查到」不等于「没部署」，也不等于「已部署」"
        )
    skipped = [f"{n}={c or '（空）'}" for n, c in steps if c == SKIP_CONCLUSION]
    if skipped:
        return 1, "0", (
            f"部署类步被 **skipped**（{', '.join(skipped)}）⇒ **skip 非 deployed**："
            "本轮一次都没有部署（`Skip if already built` 命中的形态，issue #9056）"
        )
    failed = [f"{n}={c or '（空）'}" for n, c in steps if c != EXECUTED_CONCLUSION]
    if failed:
        return 1, "0", f"部署类步没有全部成功（{', '.join(failed)}）⇒ 本轮没有发生成功的部署"
    return 0, "1", f"部署类步全部 success（{', '.join(n for n, _ in steps)}）⇒ 本次**真的发生了部署**"


def _gh_json(args: list[str], gh: str = "gh") -> object | None:
    exe = shutil.which(gh) or ""
    if not exe:
        return None
    try:
        proc = subprocess.run([exe, *args], capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError:
        return None


def _read_json_file(path: str) -> object | None:
    try:
        return json.loads(open(path, encoding="utf-8").read() or "null")
    except (OSError, json.JSONDecodeError):
        return None


def resolve_run_id(workflow: str, sha: str, limit: int) -> str:
    """状态面：在该腿的 run 列表里找**该 commit** 最近的一条（离线替身 = `ATTEST_RUNS_FILE`）。"""
    fixture = (os.environ.get("ATTEST_RUNS_FILE") or "").strip()
    runs = _read_json_file(fixture) if fixture else _gh_json(
        ["run", "list", "--workflow", workflow, "--branch", "main", "--limit", str(limit),
         "--json", "databaseId,headSha,conclusion"])
    if not isinstance(runs, list):
        return ""
    for run in runs:
        if not isinstance(run, dict):
            continue
        head = str(run.get("headSha") or "")
        if head.startswith(sha):
            return str(run.get("databaseId") or "")
    return ""


def read_jobs(run_id: str) -> object | None:
    """读一条 run 的 jobs（离线替身 = `ATTEST_JOBS_FILE`；给了它 ⇒ **一次 gh 都不调**）。"""
    fixture = (os.environ.get("ATTEST_JOBS_FILE") or "").strip()
    if fixture:
        return _read_json_file(fixture)
    if not run_id:
        return None
    return _gh_json(["run", "view", run_id, "--json", "jobs"])


def recipe(run_id: str, workflow: str = "", sha: str = "") -> str:
    """白天可复算的命令（**逐字**能跑；`gh` 的 jq 只要 `Deploy|Publish` 前缀的步）。"""
    jq = (r'.jobs[].steps[] | select(.name|test("^(Deploy|Publish) ")) '
          r'| "\(.name)\t\(.conclusion)"')
    if run_id:
        return f'gh run view {run_id} --json jobs --jq \'{jq}\''
    return (f'gh run list --workflow {workflow or "<wf>"} --branch main --limit 30 '
            f'--json databaseId,headSha,conclusion  # 取 headSha 以 {sha or "<sha>"} 开头那条，再 '
            f'gh run view <id> --json jobs')


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="「这一次真的发生了部署」的自证（issue #9056，只读）")
    ap.add_argument("--run-id", default="", help="事件面：那一条 run 的 id")
    ap.add_argument("--workflow", default="", help="状态面：该腿的 workflow 文件名")
    ap.add_argument("--sha", default="", help="状态面：对账基准的短 sha（7 位）")
    ap.add_argument("--limit", type=int, default=int(os.environ.get("ATTEST_LIMIT", "100")))
    ns = ap.parse_args(argv)
    run_id = ns.run_id.strip()
    if not run_id and ns.workflow and ns.sha:
        run_id = resolve_run_id(ns.workflow.strip(), ns.sha.strip(), ns.limit)
        if not run_id and not (os.environ.get("ATTEST_JOBS_FILE") or "").strip():
            print("DEPLOY_EXECUTED=" + UNKNOWN)
            print(f"判不了：该腿（{ns.workflow}）在 main 上找不到 headSha 以 `{ns.sha}` 开头的 run "
                  f"⇒ 「没查到」不等于「没部署」，也不等于「已部署」")
            print(f"DEPLOY_ATTEST_RECIPE={recipe('', ns.workflow, ns.sha)}")
            return 3
    jobs = read_jobs(run_id)
    steps = deploy_steps(jobs)
    code, executed, why = judge(steps)
    print(f"DEPLOY_EXECUTED={executed}")
    for name, conclusion in steps:
        print(f"DEPLOY_STEP={name}={conclusion or '（空）'}")
    if code == 1:
        print(f"⛔ skip 非 deployed：{why}")
    elif code == 3:
        print(f"⚠️ 判不了：{why}")
    else:
        print(f"✅ {why}")
    print(f"DEPLOY_ATTEST_RECIPE={recipe(run_id, ns.workflow, ns.sha)}")
    return code


if __name__ == "__main__":
    sys.exit(main())
