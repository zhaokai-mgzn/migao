#!/usr/bin/env python3
"""CI failed-job **重跑分流** + **flaky 台账**（issue #4717）。

背景（本会话真实发生两次，别再重新猜）
--------------------------------------
- **#4713**：`new Date()` 造期望值 vs 消息时间戳 ⇒ **跨分钟边界必红**（~10~15% 随机红），
  且落在 **required** 的 `mini-app typecheck + unit tests` 里 ⇒ 随机卡住**任何** PR
  （实证 #4712：一个与 mini-app 毫无关系的 drift-audit 改动被卡）。
- **#4717**：`task-card-qr`「等 A 后**同步**断言 B」的 **commit 竞态**（晚一次 commit）。
两者同形：**随机红 ⇒ 告警疲劳 ⇒ 归因层失效**（`migao-acceptance` 点名形态）。

本模块只做 **CI 层两件事**（测试层的机械守卫 (C) 项由另一单承担）：
  ① failed job **重跑分流**：首次失败 ⇒ 自动重跑 **1 次（上限，绝不无限重跑）**；
     第二次绿 ⇒ 标 flaky（可见标注 + 记账）；第二次仍红 ⇒ **照常失败**。
  ② flaky **台账**（`.github/flaky-ledger.json`）：**只追加**、幂等、可被后续单消费；
     **推前先与 main 对齐**（并集 + 最新 main 之上重放 + `--force-with-lease` 推送，见 #5100）。

三条不变量（判据的骨头；每条都有反向红证，见
`tests/unit_ci_workflows/test_flaky_triage.py`）
------------------------------------------------
  **A. 绝不静默放行** —— 「第二次绿」**不等于**「通过」：分流只产出「标注 + 记账」，
     并由 workflow 侧**卸下 auto-merge**（`gh pr merge --disable-auto` + `block/merge`）。
     判据形态：`mark_flaky` 只可能来自 `rerun_result == "success"`（纯函数可证）。
  **B. 绝不误判 infra** —— `cancelled` / `timed_out` / `startup_failure` / `stale` /
     `action_required` 的运行，以及**从未真正跑起来的 job**（无 steps）、
     只在「取代码 · 装依赖」步骤失败的 job ⇒ **既不算 flaky、也不重跑**。
  **C. 绝不重复记账** —— 幂等键 = `(workflow, run_id, job)`：同一次失败被重跑/重判多次
     只留 **一条**（`append_entries` 对批内 + 存量都去重）。

⚠️ **判据方向一律 fail-safe**：分类不确定时倾向 **infra_suspect**（= 不打 flaky 标、
不卸 auto-merge、但**仍然记账**）—— 宁可漏标一条 flaky（可见、可补），
不可把 infra 抖动记成 flaky（那会把台账本身变成噪音源）。

退出码（三态，照本仓库 `merge_gate.py` / `llm_sink_check.py` 口径）
------------------------------------------------------------------
`0` = 正常；`1` = 违规（台账不自洽 / 参数非法）；`3` = **无法判定**（取不到事实）。
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── 常量（单一事实源；workflow 侧只引用，不复制） ───────────────────────────────

LEDGER_PATH = Path(__file__).resolve().parents[1] / "flaky-ledger.json"
LEDGER_BRANCH = "chore/flaky-ledger"
FLAKY_LABEL = "flaky/rerun-green"
BLOCK_LABEL = "block/merge"

#: 参与分流的 workflow **白名单**（按 workflow `name` 匹配，不是文件名）。
#: 只收「PR 上跑测试、且重跑无副作用」的 CI：
#:   · 故意**不收** `Drift Audit` / `Agent Behavior Eval` / `Demo Evidence Gate`（报告型，不阻塞）；
#:   · 故意**不收** `Deploy Reconcile` / `deploy-*`（**重跑有副作用**：会真的部署）；
#:   · 故意**不收** `Post-Deploy Eval` 等真实 LLM workflow（重跑 = 重复烧 token，见 #4262）。
TRIAGED_WORKFLOWS = (
    "PR Check",
    "Mini-App CI",
    "AI Agent Service Unit Tests",
    "Bmini-App CI",
)

#: **上限**：首次 + 最多 1 次重跑。改大这个数 = 允许无限重跑 ⇒ 守卫测试会红。
MAX_ATTEMPTS = 2

#: 这些 conclusion **不是测试失败**：取消 / 超时 / 基础设施 / 启动失败 / 过期。
#: 命中 ⇒ 不重跑、不记账、不打标（「不许把 infra 抖动记成 flaky」）。
NOT_TEST_FAILURE_CONCLUSIONS = frozenset({
    "cancelled",
    "timed_out",
    "startup_failure",
    "stale",
    "action_required",
    "skipped",
    "neutral",
})

#: 「基础设施步骤」的名字形态：这些步骤失败 = 环境/依赖问题，**不是被测对象的问题**。
#: 方向是 fail-safe（多认 ⇒ 少打 flaky 标），故含较宽的 `^install `。
INFRA_STEP_PATTERNS = tuple(re.compile(p) for p in (
    r"^set up job$",
    r"^complete job$",
    r"^initialize containers$",
    r"^start container",
    r"^stop container",
    r"^run actions/",              # uses: actions/checkout@v7 → 步骤名 "Run actions/checkout@v7"
    r"^set ?up (node|python|java|jdk|go|ruby|php|dotnet)",
    r"^setup (node|python|java|jdk|go|ruby|php|dotnet)",
    r"^(npm|yarn|pnpm) (ci|install)",
    r"^install ",                  # Install dependencies / Install test deps / Install Playwright deps …
    r"^pip install",
    r"^(restore|save) cache",
    r"^cache ",
))

LEDGER_TOP_KEYS = ("version", "note", "_schema", "entries")
ENTRY_REQUIRED = {
    "workflow": str,
    "job": str,
    "run_id": int,
    "rerun_result": str,
    "kind": str,
    "observed_at": str,
    # 「每条带**可行动**信息」（照 #4757 `time_flaky_baseline.json` 的形态）：
    # 只有 kind 的条目是**不可行动**的 —— 读的人不知道下一步该干什么。
    "reason": str,
    "remedy": str,
    "status": str,
}
ENTRY_KINDS = ("flaky", "confirmed_failure", "infra_suspect")
ENTRY_STATUSES = ("open", "fixed")
RERUN_RESULTS = ("success", "failure", "not_rerun")
#: 台账里**禁止**出现的顶层键：硬编码计数会随追加而腐烂（#4701/#4714/#4742 纪律）。
FORBIDDEN_LEDGER_KEYS = ("count", "total", "entries_count", "n_entries", "num_entries")

#: 每个 kind 的**可行动**说明（生成时即写入，读的人不必回查脚本）。
KIND_REASON = {
    "flaky": "首次失败、**重跑后通过**（随机波动）——**不是**本次改动修好了它",
    "confirmed_failure": "同一 commit **两次都失败** ⇒ 确定性失败（已用「第二次真实结果」排除 flaky）",
    "infra_suspect": "失败落在「取代码 · 装依赖 · 配环境」步骤（或 job 从未跑起来）⇒ 环境/基础设施问题",
}
KIND_REMEDY = {
    "flaky": ("按 `migao-acceptance`「随机红 = 归因层失效」**定位机制**（不许只加 waitFor/sleep）："
              "时间相关 ⇒ 冻结时钟（`jest.setSystemTime` / 注入时钟）；并行或共享状态 ⇒ 显式隔离或独立 fixture；"
              "修后**必须给红证**（把机制注回 ⇒ 必红）"),
    "confirmed_failure": "按真实失败排查（本机制已用「同 commit 第二次结果」排除 flaky 可能）",
    "infra_suspect": ("排查 runner 容量 / 依赖源 / 网络：偶发一次属环境抖动；"
                      "反复出现 ⇒ 查依赖锁定与 runner 超时配置"),
}


# ── 纯函数：事实 → 分流决定（无 IO、无网络，故可离线红证） ─────────────────────


def _conclusion(obj) -> str:
    return str((obj or {}).get("conclusion") or "").strip().lower()


def is_failed(job) -> bool:
    return _conclusion(job) == "failure"


def failed_step_name(job) -> str:
    """该 job **第一个失败步骤**的名字（空串 = 没有任何步骤失败 ⇒ runner 级失败）。"""
    for step in (job or {}).get("steps") or []:
        if _conclusion(step) == "failure":
            return str(step.get("name") or "").strip()
    return ""


def job_is_infra(job) -> bool:
    """该失败 job 是否属**基础设施/环境**失败（⇒ 不算 flaky、不重跑）。

    四个判据，任一命中即 infra（全部 fail-safe 方向）：
      ① job conclusion ∈ {timed_out, cancelled, startup_failure}；
      ② job **没有任何 steps** ⇒ 它从未真正跑起来（runner 分配/启动失败）；
      ③ 失败了但**没有任何步骤**被判失败 ⇒ runner 级失败（非测试断言）；
      ④ 唯一失败的步骤名命中「取代码 · 装依赖 · 配环境」形态。
    """
    if _conclusion(job) in {"timed_out", "cancelled", "startup_failure"}:
        return True
    steps = (job or {}).get("steps") or []
    if not steps:
        return True
    step = failed_step_name(job)
    if not step:
        return True
    low = step.lower()
    return any(p.search(low) for p in INFRA_STEP_PATTERNS)


def pr_number(run) -> int | None:
    for pr in (run or {}).get("pull_requests") or []:
        if isinstance(pr, dict) and isinstance(pr.get("number"), int):
            return pr["number"]
    return None


def entry_key(entry) -> tuple:
    """幂等键：**同一次失败**（同 run 的同一个 job）无论被判多少次，都只算一条。"""
    return (entry.get("workflow"), entry.get("run_id"), entry.get("job"))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_entries(run, failed_jobs, rerun_result: str) -> list:
    """把「失败 job 列表 + 重跑结果」变成台账条目（**只追加**，不修改既有条目）。"""
    out = []
    for job in failed_jobs:
        if job_is_infra(job):
            kind = "infra_suspect"
        elif rerun_result == "success":
            kind = "flaky"
        else:
            kind = "confirmed_failure"
        out.append({
            "workflow": run.get("name"),
            "job": job.get("name"),
            "run_id": run.get("id"),
            "run_attempt": run.get("run_attempt"),
            "run_url": run.get("html_url"),
            "pr": pr_number(run),
            "head_sha": run.get("head_sha"),
            "head_branch": run.get("head_branch"),
            "first_failure_step": failed_step_name(job),
            "rerun_result": rerun_result,
            "kind": kind,
            "observed_at": run.get("updated_at") or run.get("created_at") or _now(),
            # 可行动信息：生成时即写入（读的人不必回查脚本 / 不必翻日志）
            "reason": KIND_REASON[kind],
            "remedy": KIND_REMEDY[kind],
            "status": "open",
            # 跟踪单号由**分诊方**回填（CI 生成时不知道单号）——
            # `reconcile` 会把「kind=flaky 且 status=open 但没 follow_up」判成欠账（红）。
            "follow_up": None,
        })
    return out


def decide(bundle, max_attempts: int = MAX_ATTEMPTS) -> dict:
    """**唯一**的分流判据（纯函数）。返回 `{action, reason, kind, entries, pr, attempt}`。

    `bundle` = `{"run": {...}, "jobs": [...], "prior_jobs": [...] | None}`
    （形状与 GitHub REST `/actions/runs/{id}` 与 `/attempts/{n}/jobs` 同源）。

    action 四态：
      · `skip`                   —— 不动作（含 infra/取消/超时/非 PR/不在白名单）
      · `rerun`                  —— 首次失败 ⇒ 重跑失败 job **1 次**
      · `mark_flaky`             —— 第二次绿 ⇒ 标 flaky（**并卸 auto-merge**）
      · `record_infra`           —— 第二次绿但全是 infra ⇒ 只记账（不打 flaky 标、不卸）
      · `record_confirmed_failure` —— 第二次仍红 ⇒ **照常失败**（不再重跑第三次）
    """
    run = (bundle or {}).get("run") or {}
    jobs = (bundle or {}).get("jobs") or []
    prior_jobs = (bundle or {}).get("prior_jobs") or []

    def skip(reason: str) -> dict:
        return {"action": "skip", "reason": reason, "kind": None,
                "entries": [], "pr": pr_number(run), "attempt": _attempt(run)}

    name = str(run.get("name") or "")
    if name not in TRIAGED_WORKFLOWS:
        return skip(f"workflow `{name}` 不在分流白名单（重跑无副作用才收）")
    if str(run.get("event") or "") != "pull_request":
        return skip(f"非 PR 运行（event={run.get('event')!r}）—— 部署/定时/手动不参与分流")
    branch = str(run.get("head_branch") or "")
    if branch == LEDGER_BRANCH:
        return skip("台账分支自身的 CI 不参与分流（防自指递归：台账 PR 又被分流）")

    attempt = _attempt(run)
    conclusion = _conclusion(run)
    if conclusion in NOT_TEST_FAILURE_CONCLUSIONS:
        return skip(f"conclusion={conclusion} 属取消/超时/基础设施失败 —— 不算 flaky、也不重跑")
    if conclusion == "success":
        if attempt < 2:
            return skip("首次尝试即绿 —— 无需分流")
        first_failed = [j for j in prior_jobs if is_failed(j)]
        if not first_failed:
            return skip("重跑绿，但**首次尝试没有失败 job**（可能被取消后重跑）⇒ 无 flaky 证据")
        return _terminal(run, first_failed, "success", attempt)
    if conclusion != "failure":
        return skip(f"conclusion={conclusion} 不是测试失败")

    failed = [j for j in jobs if is_failed(j)]
    if not failed:
        return skip("conclusion=failure 但没有任何失败 job（workflow 级失败）—— 无 job 可重跑")
    if attempt >= max_attempts:
        return _terminal(run, failed, "failure", attempt)
    return {
        "action": "rerun",
        "reason": (f"首次失败（attempt={attempt}）⇒ 自动重跑失败 job "
                   f"（上限 {max_attempts - 1} 次，绝不无限重跑）"),
        "kind": None,
        "failed_jobs": [j.get("name") for j in failed],
        "entries": [],
        "pr": pr_number(run),
        "attempt": attempt,
    }


def _attempt(run) -> int:
    try:
        return int(run.get("run_attempt") or 1)
    except (TypeError, ValueError):
        return 1


def _terminal(run, failed_jobs, rerun_result: str, attempt: int) -> dict:
    entries = build_entries(run, failed_jobs, rerun_result)
    kinds = {e["kind"] for e in entries}
    if rerun_result == "success" and "flaky" in kinds:
        action, kind = "mark_flaky", "flaky"
        reason = "第二次绿 ⇒ **flaky**（标注 + 记账 + 卸 auto-merge；第二次绿 ≠ 通过）"
    elif rerun_result == "success":
        action, kind = "record_infra", "infra_suspect"
        reason = "第二次绿，但失败 job 全属 infra/环境 ⇒ 只记账（**不**记成 flaky）"
    else:
        action, kind = "record_confirmed_failure", "confirmed_failure"
        reason = (f"第 {attempt} 次仍失败 ⇒ **照常失败**（不再重跑第 {attempt + 1} 次）"
                  f"；确定性失败，绝不放行")
    return {"action": action, "reason": reason, "kind": kind,
            "entries": entries, "pr": pr_number(run), "attempt": attempt}


# ── 台账：只追加 + 幂等 ───────────────────────────────────────────────────────


def append_entries(ledger: dict, entries: list) -> tuple:
    """**只追加**、**幂等**。返回 `(added, skipped_keys)`。

    幂等判据 = `entry_key` 在「存量 ∪ 本批已收」里出现过 ⇒ 跳过。
    故「同一次失败被重跑多次 / 重判多次」只留一条；重复追加是**无副作用**的空操作。
    """
    existing = {entry_key(e) for e in (ledger.get("entries") or [])}
    added, skipped = [], []
    for entry in entries:
        key = entry_key(entry)
        if key in existing:
            skipped.append(key)
            continue
        existing.add(key)
        added.append(entry)
    ledger.setdefault("entries", []).extend(added)
    return added, skipped


def union_ledgers(main_ledger, branch_ledger) -> dict:
    """**并集**（幂等、不丢条目）：以 main 台账为基线，幂等并入分支侧条目。

    **复用** `append_entries`（幂等键 `entry_key` 的去重逻辑只有一份，不新写第二套并集）。

    #5100 为什么需要它：台账分支的追加路径**不自愈** —— 旧实现在**分支自己的 HEAD**（旧基线）
    上追加，而台账 PR 走 **squash 合并** ⇒ 分支历史**永不含** main 上那个 squash 提交
    ⇒ **只追加**的分支**每轮都会再冲突**（实测 `diverged, ahead_by 34, behind_by 16`）。
    根治 = 推前先与 main 对齐：**先并集，再在最新 main 之上重放**（见 `align_with_main`）。

    三条不变量（判据：`tests/unit_ci_workflows/test_flaky_ledger_append_selfheal.py`）：
      · **幂等** —— 同一 key 只留一条（重复并集是无副作用的空操作）；
      · **不丢条目** —— 结果 ⊇ main ∪ 分支 ⇒ 条目数 ≥ `max(main, 分支)`；
      · **同 key 内容不同时以 main 为准**（main 是**已合并的权威态**；只追加写者不产生这种差异）。
    """
    merged = copy.deepcopy(main_ledger or {})
    append_entries(merged, list((branch_ledger or {}).get("entries") or []))
    return merged


def load_ledger(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_ledger(path: Path, ledger: dict) -> None:
    Path(path).write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _show_json(rev_path: str, what: str):
    """读 `git show <rev>:<path>` 并解析 JSON。**fail-closed**：读不到/不是 JSON ⇒ 抛错。

    绝不许把「读不到」当「空台账」继续 —— 那会**丢**掉那一侧的条目（并集的全部意义）。
    """
    out = _git("show", rev_path)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"读不到{what}（{rev_path}）：{(out.stderr or '空内容').strip()[:200]}")
    try:
        return json.loads(out.stdout)
    except ValueError as exc:
        raise RuntimeError(f"{what}（{rev_path}）不是合法 JSON：{exc}")


def align_with_main(ledger_path, branch: str = LEDGER_BRANCH) -> dict:
    """**推前先与 main 对齐**（#5100 根治）：并集 + 在**最新 main 之上**重放（并写回台账文件）。

    步骤（**全 fail-closed**：任一步取不到事实 ⇒ 抛 `RuntimeError`，绝不「当作空台账」继续）：
      ① `git fetch origin main` → 读 `origin/main:<台账相对路径>`（main 侧 = **权威态**）；
      ② 分支存在 ⇒ 读 `FETCH_HEAD:<台账相对路径>`，并记下它的 HEAD（= 推送要用的 **lease 期望值**）；
      ③ `union_ledgers(main, 分支)`（幂等 + 不丢条目）；
      ④ `git checkout -B <branch> origin/main` ⇒ 把并集**写回** `ledger_path`
         —— 此后调用方的 `git diff` 基线是 **main**（不再是旧分支），提交落在**最新 main 之上**。

    返回 `{"lease": "<branch>:<sha>" | "", "branch_head": …, "main_total": n,
    "branch_total": n, "merged_total": n}`；`lease` 供调用方做 `--force-with-lease`
    （lease 失败 = 别人刚推 ⇒ **重取重算，绝不强推**）。

    ⚠️ `ledger_path` 必须是**仓库相对**路径：本函数要对 git 说 `origin/main:<该路径>`。
    """
    rel = Path(ledger_path).as_posix()
    if Path(rel).is_absolute():
        raise RuntimeError(f"`--ledger` 必须是**仓库相对**路径（要用于 `origin/main:<路径>`），"
                           f"实际 {str(ledger_path)!r}")

    fetch = _git("fetch", "--quiet", "origin", "main")
    if fetch.returncode != 0:
        raise RuntimeError(f"git fetch origin main 失败：{(fetch.stderr or '').strip()[:200]}")
    main_ledger = _show_json(f"origin/main:{rel}", "main 侧台账")

    branch_head, branch_ledger = None, None
    ls = _git("ls-remote", "--heads", "origin", branch)
    if ls.returncode != 0:
        raise RuntimeError(
            f"git ls-remote 失败（无法判定分支是否存在）：{(ls.stderr or '').strip()[:200]}")
    if ls.stdout.strip():
        got = _git("fetch", "--quiet", "origin", branch)
        if got.returncode != 0:
            raise RuntimeError(f"git fetch origin {branch} 失败：{(got.stderr or '').strip()[:200]}")
        branch_head = _git("rev-parse", "FETCH_HEAD").stdout.strip() or None
        branch_ledger = _show_json(f"FETCH_HEAD:{rel}", "分支侧台账")

    merged = union_ledgers(main_ledger, branch_ledger)
    co = _git("checkout", "-B", branch, "origin/main")
    if co.returncode != 0:
        raise RuntimeError(
            f"git checkout -B {branch} origin/main 失败：{(co.stderr or '').strip()[:200]}")
    save_ledger(ledger_path, merged)
    return {
        "lease": f"{branch}:{branch_head}" if branch_head else "",
        "branch_head": branch_head,
        "main_total": len(ledger_keys(main_ledger)),
        "branch_total": len(ledger_keys(branch_ledger or {})),
        "merged_total": len(ledger_keys(merged)),
    }


def ledger_violations(ledger: dict) -> list:
    """台账自洽性判据（空 = 合规）。`selftest` 与 CI 守卫共用同一实现。"""
    bad = []
    for key in LEDGER_TOP_KEYS:
        if key not in ledger:
            bad.append(f"台账缺顶层键 `{key}`")
    for key in FORBIDDEN_LEDGER_KEYS:
        if key in ledger:
            bad.append(f"台账出现硬编码计数键 `{key}`（会随追加而腐烂 ⇒ 条数一律现取）")
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        return bad + ["`entries` 必须是列表"]
    seen = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            bad.append(f"entries[{i}] 不是对象")
            continue
        for key, typ in ENTRY_REQUIRED.items():
            if key not in entry:
                bad.append(f"entries[{i}] 缺字段 `{key}`")
            elif not isinstance(entry[key], typ):
                bad.append(f"entries[{i}].{key} 类型应为 {typ.__name__}")
        if entry.get("kind") not in ENTRY_KINDS:
            bad.append(f"entries[{i}].kind={entry.get('kind')!r} 不在 {ENTRY_KINDS}")
        if entry.get("status") not in ENTRY_STATUSES:
            bad.append(f"entries[{i}].status={entry.get('status')!r} 不在 {ENTRY_STATUSES}")
        if entry.get("rerun_result") not in RERUN_RESULTS:
            bad.append(f"entries[{i}].rerun_result={entry.get('rerun_result')!r} 不在 {RERUN_RESULTS}")
        # 「可行动信息」不许是空壳（空字符串 = 有字段但不可行动，等于没有）
        for key in ("reason", "remedy"):
            if isinstance(entry.get(key), str) and not entry[key].strip():
                bad.append(f"entries[{i}].{key} 是空串 ⇒ 条目不可行动（照 #4757 形态：每条带 reason+remedy）")
        fu = entry.get("follow_up", None)
        if fu is not None and not isinstance(fu, int):
            bad.append(f"entries[{i}].follow_up 必须是整数跟踪单号或 null，实际 {fu!r}")
        # 「第二次绿 ⇒ flaky」的**方向**也必须自洽：重跑没绿就不许标 flaky
        if entry.get("kind") == "flaky" and entry.get("rerun_result") != "success":
            bad.append(f"entries[{i}] kind=flaky 但 rerun_result≠success —— 放行了未复现的失败")
        key = entry_key(entry)
        if key in seen:
            bad.append(f"entries[{i}] 幂等键重复 {key}（同一次失败记了多条）")
        seen.add(key)
    return bad


def reconcile(ledger: dict) -> dict:
    """**三态对账**（照 #4757 存量账本的口径，适配「事件追加日志」语义）。返回三个清单。

    | 态 | 判据 | 为什么必须能红 |
    |---|---|---|
    | `new_events` | `kind=flaky` 且 `status=open` 却**没有 `follow_up` 跟踪单** | 新 flaky 事件没登记修复路径 = 随机红照旧变成噪音（正是 #4717 要治的形态） |
    | `duplicates` | 幂等键 `(workflow, run_id, job)` 重复 | 同一次失败被记多条 ⇒ 计数被灌水（「N 次标 flaky」的 N 不可信） |
    | `fixed_not_deducted` | `status=fixed` 却（a）缺 `fixed_by` 凭据，或（b）同一 `(workflow, job)` 在它**之后**又出现 flaky 事件 | 销账不成立 / **修了又复发** ⇒ 「已修」是假账 |

    键全空 = 无欠账。**本判据不设阈值、不写死计数**；也**未接 required 门禁**（照实登记：
    它是**消费接口**，由后续单 / agent 按需调用）。
    """
    entries = ledger.get("entries") or []
    new_events, duplicates, fixed_not_deducted = [], [], []

    seen = set()
    for i, entry in enumerate(entries):
        key = entry_key(entry)
        if key in seen:
            duplicates.append({"index": i, "key": list(key),
                               "why": "幂等键重复 ⇒ 同一次失败记了多条（计数被灌水）"})
        seen.add(key)

    latest_flaky = {}
    for i, entry in enumerate(entries):
        if entry.get("kind") == "flaky":
            latest_flaky[f"{entry.get('workflow')} :: {entry.get('job')}"] = i

    for i, entry in enumerate(entries):
        group = f"{entry.get('workflow')} :: {entry.get('job')}"
        if entry.get("kind") == "flaky" and entry.get("status") != "fixed" and not entry.get("follow_up"):
            new_events.append({
                "index": i, "key": list(entry_key(entry)),
                "why": "kind=flaky 且 status=open 但没有 follow_up 跟踪单 ⇒ 未登记修复路径",
                "remedy": entry.get("remedy"),
            })
        if entry.get("status") == "fixed":
            if not entry.get("fixed_by"):
                fixed_not_deducted.append({
                    "index": i, "key": list(entry_key(entry)),
                    "why": "status=fixed 但缺 fixed_by（修复凭据）⇒ 销账不成立",
                })
            elif latest_flaky.get(group, -1) > i:
                fixed_not_deducted.append({
                    "index": i, "key": list(entry_key(entry)),
                    "why": "已标 fixed，但同一 (workflow, job) 之后**又出现 flaky 事件** ⇒ "
                           "修复不成立（复发）",
                })
    return {"new_events": new_events, "duplicates": duplicates,
            "fixed_not_deducted": fixed_not_deducted}


def aggregate(ledger: dict) -> dict:
    """按 `(workflow, job)` 聚合 —— **计数一律现取**（台账里不存任何计数，故不会腐烂）。

    这是台账的**消费接口**：后续单要判「某用例连续 N 次标 flaky ⇒ 必须修」时，
    拿这里的 `flaky` 计数自己定阈值 —— **阈值不写进本仓库**（#4701/#4714/#4742 纪律：
    硬编码计数/阈值会随追加而腐烂；本仓库 `time_flaky_guard.py` 的存量账本同此口径）。
    """
    groups: dict = {}
    for entry in ledger.get("entries") or []:
        key = f"{entry.get('workflow')} :: {entry.get('job')}"
        slot = groups.setdefault(key, {
            "workflow": entry.get("workflow"), "job": entry.get("job"),
            "total": 0, "flaky": 0, "confirmed_failure": 0, "infra_suspect": 0,
            "last_run_id": None, "last_observed_at": None,
        })
        slot["total"] += 1
        if entry.get("kind") in ("flaky", "confirmed_failure", "infra_suspect"):
            slot[entry["kind"]] += 1
        slot["last_run_id"] = entry.get("run_id")
        slot["last_observed_at"] = entry.get("observed_at")
    return groups


# ── 网络薄封装（只取事实；判据不在这里） ────────────────────────────────────────


def _merge_pages(pages) -> dict:
    """**纯函数**：把 `gh api --paginate --slurp` 的多页浅合并成**一个**对象。

    合并口径（按**值的形状**分派，不按字段名）：值是 `list` 的字段 ⇒ **跨页累加**；
    标量（`total_count` 等，各页同值）⇒ **覆盖**。

    🔴 **#5264 的病根就在这个函数的旧口径**（实测，别再重新猜）：旧实现写成
    `merged.update({k: v for k, v in page.items() if k != "jobs"})` + **只**把 `jobs` 累加
    ⇒ **列表字段被每页覆盖** ⇒ 分页后**只剩最后一页**。实测（2026-09-24，`gh` 复算）：

        gh api "repos/zhaokai-mgzn/migao/actions/runs?event=pull_request\
    &branch=chore/flaky-ledger&per_page=100" --paginate --slurp
        ⇒ 3 页（100/100/11），total_count=211
        而旧口径的 `_gh_api(同一 URL)` ⇒ **11** 条，且全是**最老**的
        （created_at ≤ 2026-09-20T06:13:26Z）
        ⇒ `runs_needing_approval()` 只看得到那 11 条早已作废的 run ⇒ 恒返回 `[]`
        ⇒ `approve` 一次都没发出去 ⇒ 台账 PR #5139 的 run 永远停在 `action_required`
        （0 个 job、0 条 check）⇒ auto-merge 永不触发 ⇒ 台账冻结。

    ⚠️ 历史注记：**#4804 当年「实测有效」是真的** —— 那时该分支的 PR run 数 < 100 ⇒
    `--slurp` 返回**单页** ⇒ 走 `_gh_api` 的「单页短路」分支（那条路径**正确**）。
    **跨过一页之后**这个机制才**静默失效**（没有任何东西会因此变红）。⇒ 单页短路**保留**，
    多页合并按上面的形状分派修好。

    刻意**不**在标量冲突时报错：本函数只做浅合并（判据不在这里），且 `total_count` 各页必然同值。
    """
    merged: dict = {}
    for page in pages or []:
        if not isinstance(page, dict):
            continue
        for key, value in page.items():
            if isinstance(value, list):
                prev = merged.get(key)
                merged[key] = (prev if isinstance(prev, list) else []) + list(value)
            else:
                merged[key] = value
    return merged


def _gh_api(path: str) -> dict:
    out = subprocess.run(
        ["gh", "api", "--paginate", "--slurp", path],
        check=True, capture_output=True, text=True).stdout
    data = json.loads(out)
    # --slurp 对单页返回 [obj]；对分页返回 [obj, obj…]（jobs 走 per_page=100 单页即可）
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, list):
        return _merge_pages(data)
    return data


def fetch_bundle(repo: str, run_id: int) -> dict:
    run = _gh_api(f"repos/{repo}/actions/runs/{run_id}")
    attempt = _attempt(run)
    jobs = (_gh_api(f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs")
            .get("jobs") or [])
    prior_jobs = None
    if attempt >= 2:
        prior_jobs = (_gh_api(f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt - 1}/jobs")
                      .get("jobs") or [])
    return {"run": run, "jobs": jobs, "prior_jobs": prior_jobs}


# ── #4804：批准被 GITHUB_TOKEN 抑制的台账 PR run（台账落 main 的唯一通路） ──────


def runs_needing_approval(runs, workflows=None) -> list:
    """**纯函数**：挑出「被 GITHUB_TOKEN 抑制、需显式 approve 才能跑」的 run id（升序）。

    病根（#4804，实测）：本 workflow 用 `GITHUB_TOKEN` 建台账 PR ⇒ GitHub **抑制**该 PR
    的 `pull_request` 事件所引发的 workflow ⇒ 那批 run 全部停在 `conclusion=action_required`
    （**run 被创建了、但一个 job 都没有**，`check-runs` 为空）⇒ `gh pr checks` 报
    「no checks reported」⇒ required 集合永远不满足 ⇒ `--auto` **永不触发** ⇒ 台账停在分支上。
    （与「条件没满足」的区别：条件没满足时 run 会**真的跑**并给出结论；这里是**零 job**。）

    判据只看**事实**：`event == pull_request` ∧ `conclusion == action_required`
    ∧（给了 `workflows` 时）`name ∈ workflows`。

    ⚠️ **为什么要 `workflows` 白名单**（越权面收敛）：同一分支上的 run 不止本 workflow 分流的
    那几个 —— **实测**台账分支上还有 `Drift Audit (真相源契约)` / `PR Issue Link Check` /
    `Deploy Reconcile (PR 对账补偿)`。批准**别的** workflow 的运行不属本机制职责。
    白名单**由调用方传入**（单一事实源 = `TRIAGED_WORKFLOWS`），本函数不硬编码副本。

    故意**不**按 `head_branch` 过滤 —— 过滤是调用方的事（本函数保持可单测的纯粹性），
    且 run 一旦被批准，`run_attempt` 会 +1、`conclusion` 变 null ⇒ **天然幂等**（不会重复 approve）。
    """
    allowed = None if workflows is None else set(workflows)
    out = []
    for run in runs or []:
        if not isinstance(run, dict):
            continue
        if run.get("event") != "pull_request":
            continue
        if run.get("conclusion") != "action_required":
            continue
        if allowed is not None and run.get("name") not in allowed:
            continue
        rid = run.get("id")
        if isinstance(rid, int):
            out.append(rid)
    return sorted(out)


def branch_tip(listing) -> str | None:
    """**纯函数**：从 `GET /repos/{owner}/{repo}/branches/{branch}` 的响应里取分支 tip 的 sha。

    **实测（2026-09-24，读源不是猜）**：`gh api repos/zhaokai-mgzn/migao/branches/chore/flaky-ledger`
    ⇒ `{"name": "chore/flaky-ledger", "commit": {"sha": "519250fe9bf175bcf0a735a0b08969e376382409"}, …}`
    —— 分支名里的 `/` **不编码也能用**（返回的 `name` 逐字就是 `chore/flaky-ledger`，证明它没被
    解析成别的路径）；`chore%2Fflaky-ledger` 拿到**同一个** sha。本函数只认**响应形状**，
    不管调用方的 URL 怎么拼（故两种写法都兼容）。

    取不到 ⇒ `None`（调用方 **fail-closed**；**不许**退回「最新可见的待批准 run 的 sha」——
    见 `runs_for_head` 的说明）。
    """
    if not isinstance(listing, dict):
        return None
    commit = listing.get("commit")
    sha = commit.get("sha") if isinstance(commit, dict) else None
    return sha if isinstance(sha, str) and sha else None


def runs_for_head(runs, head_sha) -> list:
    """**纯函数**：只保留 `head_sha == head_sha`（= **分支 tip 那一次推送**）的候选 run。

    为什么必须收窄（**实测**）：分页修好后候选从 11 个涨到几十上百个 —— 实测该分支 211 个 run 里
    白名单口径命中 **74** 个 ⇒ 全批准 = 74 个 workflow 真的跑起来（**CI 雪崩**），而**只有 tip 那一批**
    的 check-run 能决定 PR 的 required 状态（陈旧 push 的 check 挂在旧 commit 上，required 判定看 head）。

    为什么 tip 要**从分支事实**取（`branch_tip`），而不是「最新可见的待批准 run 的 sha」：
    `flaky-triage.yml` 步骤④ **刚 push 完台账分支就立刻 approve**，而 GitHub 创建 run 是**异步**的 ⇒
    此刻可见的「最新 run」可能还是**上一次**推送的 ⇒ 拿它当 tip 会把**陈旧 SHA** 的 run 批准起来，
    且日志会把「批准了陈旧 SHA」说成「批准了本次推送」—— 正是本仓最忌的**读数与事实不一致**。

    空/畸形输入（含 `head_sha` 为空）⇒ 空集（**不是**「通过」）。
    """
    if not head_sha:
        return []
    return [r for r in (runs or [])
            if isinstance(r, dict) and r.get("head_sha") == head_sha]


def approve_runs(repo: str, run_ids) -> list:
    """逐个 `POST …/actions/runs/{id}/approve`（走 `gh api`，`GH_TOKEN` 来自环境）。

    需要 `actions: write`（本 workflow 已声明）。**fail-closed**：任一 approve 失败 ⇒
    抛 `RuntimeError` ⇒ CLI 非零 ⇒ workflow 红（「批准没发出去」不许装成「已经放行」）。
    """
    failed = []
    for rid in run_ids:
        proc = subprocess.run(
            ["gh", "api", "-X", "POST", f"repos/{repo}/actions/runs/{rid}/approve"],
            capture_output=True, text=True)
        if proc.returncode != 0:
            failed.append((rid, (proc.stderr or proc.stdout or "").strip()[:200]))
    if failed:
        raise RuntimeError("；".join(f"run {rid}：{why}" for rid, why in failed))
    return list(run_ids)


# ── #4825：台账落仓的**状态级对账**（独立兜底；不依赖 flaky-triage.yml 还活着） ────
#
# 为什么需要它（**实测**，别照抄 issue 文本）：#4804 的修法（上面的 `approve`）是
# `flaky-triage.yml` 的一个**步骤** ⇒ 该 workflow 一停（被禁用 / 语法坏 / `actions: write` 丢），
# 台账就**静默**停在 `chore/flaky-ledger` 分支上 —— 它不参与 required 集合，台账停在分支上
# 不会让任何 PR 变红，**没有任何东西会因此告警**。
# 本节的判据只看**状态**（分支内容 vs main 内容），不看事件 ⇒ 与 `workflow_run` 触发面正交，
# 故可作为独立兜底（形态照抄 `.github/workflows/deploy-reconcile.yml` 的「独立对账」先例）。

#: 台账在仓库里的**相对**路径（git 侧按相对路径取分支副本；由 LEDGER_PATH 派生，不写死副本）
LEDGER_REL = "/".join(LEDGER_PATH.parts[-2:])


def _key_str(key) -> str:
    """幂等键的可读/可比较形态（`workflow/run_id/job`）—— 报告与对账都用它，避免元组排序问题。"""
    return "/".join(str(part) for part in key)


def ledger_keys(ledger) -> set:
    """台账条目的幂等键集合（`(workflow, run_id, job)`）。计数一律**现取**。"""
    return {entry_key(e) for e in (ledger or {}).get("entries") or []}


def ledger_drift(main_ledger, branch_ledger) -> dict:
    """**纯函数**（无 IO）：#4825 兜底的判据本体 —— 台账分支相对 main 的漂移。

    期望状态由台账语义决定（**只追加** ⇒ main 的条目集恒为分支的子集）：
      · `ahead`  = 分支有、main 没有 ⇒ **已记账却没落到 main**（本单要治的形态：
        台账停在分支上，而谁也不会因此变红）；
      · `behind` = main 有、分支没有 ⇒ 分支被改写/回退（**不该出现**：只追加语义被破坏）。

    返回的 `ahead`/`behind` 是**排好序的字符串键**（幂等键的可读形态），不是计数 ——
    本文件与 workflow 都**不写死任何条数/阈值**（硬编码计数会随追加腐烂，见 #4701/#4714/#4742）。
    """
    main_keys = ledger_keys(main_ledger)
    branch_keys = ledger_keys(branch_ledger)
    return {
        "ahead": sorted(_key_str(k) for k in branch_keys - main_keys),
        "behind": sorted(_key_str(k) for k in main_keys - branch_keys),
        "main_total": len(main_keys),
        "branch_total": len(branch_keys),
    }


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def read_branch_ledger(branch: str = LEDGER_BRANCH):
    """取**远端台账分支**上的台账。三态，不许把「读不到」当「无漂移」：

    · `dict`  —— 读到了；
    · `None`  —— 分支**不存在**（还没记过账 ⇒ 没有「已记账却未落 main」的内容 ⇒ 非漂移）；
    · 抛 `RuntimeError` —— **无法判定**（网络/权限/文件缺失）⇒ CLI 退 `3`，调用方必须当红读。
    """
    ls = _git("ls-remote", "--heads", "origin", branch)
    if ls.returncode != 0:
        raise RuntimeError(
            f"git ls-remote 失败（无法判定分支是否存在）：{(ls.stderr or '').strip()[:200]}")
    if not ls.stdout.strip():
        return None
    fetch = _git("fetch", "--quiet", "origin", branch)
    if fetch.returncode != 0:
        raise RuntimeError(
            f"git fetch origin {branch} 失败：{(fetch.stderr or '').strip()[:200]}")
    show = _git("show", f"FETCH_HEAD:{LEDGER_REL}")
    if show.returncode != 0:
        raise RuntimeError(
            f"读不到 {branch}:{LEDGER_REL}：{(show.stderr or '').strip()[:200]}")
    return json.loads(show.stdout)


def branch_head_age_minutes():
    """台账分支 HEAD（= 刚 fetch 的 `FETCH_HEAD`）的提交年龄（分钟）；取不到 ⇒ `None`。

    用途：区分「兜底刚发出、check 还在产出（异步窗口）」与「推上去了却久久落不到 main」。
    """
    out = _git("log", "-1", "--format=%ct", "FETCH_HEAD")
    if out.returncode != 0 or not out.stdout.strip():
        return None
    try:
        ct = int(out.stdout.strip())
    except ValueError:
        return None
    return max(0, int((datetime.now(timezone.utc).timestamp() - ct) // 60))


# ── 报告（可见性：结论必须落在 PR / run summary 上，不许只在日志深处） ───────────


def render_comment(decision: dict) -> str:
    """PR 评论：**为什么被停**（哪个 job · 第几次才绿 · 台账条目 id）+ **人工恢复路径**。

    ⚠️ 恢复路径必须是**人工/agent 显式**动作 —— 本机制**绝不自动恢复**（那等于自动放行）。
    """
    entries = decision.get("entries") or []
    first = entries[0] if entries else {}
    lines = [
        f"<!-- flaky-triage: action={decision.get('action')} "
        f"kind={decision.get('kind')} pr={decision.get('pr')} "
        f"run={first.get('run_id', '')} -->",
        "",
    ]

    def table(first_col: str) -> list:
        out = [f"| job | {first_col} | 重跑结果 | 结论 | 台账条目（幂等键） |", "|---|---|---|---|---|"]
        for e in entries:
            step = e.get("first_failure_step") or "（runner 级，无步骤失败）"
            out.append(f"| `{e['job']}` | {step} | `{e['rerun_result']}` | **`{e['kind']}`** "
                       f"| `{e['workflow']}/{e['run_id']}/{e['job']}` |")
        return out

    why = (f"`{first.get('job')}` 在第 **1** 次尝试（run "
           f"[{first.get('run_id')}]({first.get('run_url')})，失败步骤"
           f"「{first.get('first_failure_step') or '（runner 级）'}」）失败")

    if decision.get("action") == "mark_flaky":
        lines += [
            "## 🎈 Flaky Triage —— **这次是「重跑才绿」，不等于通过**",
            "",
            f"**为什么被停**：{why}，**第 2 次尝试通过** ⇒ 判为 **flaky**（随机波动），"
            "**不是**本次改动把它修好了。",
            "",
            "已按「标注 + 记账」处理：",
            "",
            "- 🏷️ `flaky/rerun-green` —— 可见标注（读作「**重跑才绿**」，不是「通过」）",
            "- 🔒 `block/merge` + **已 `gh pr merge --disable-auto`** —— 第二次绿 ≠ 通过，"
            "auto-merge 已卸下（#4248 实证：光靠 `block/merge` 标签拦不住**已 arm** 的 auto-merge）",
            "- 📒 已追加 `.github/flaky-ledger.json`（只追加 · 幂等 · 可审计）",
            "",
            *table("首次失败步骤"),
            "",
            "**下一步（可行动）**：",
            "",
            f"> {first.get('remedy') or '按 `migao-acceptance` 定位机制并给红证'}",
            "",
            "### 🔧 人工恢复路径（**不是**自动恢复）",
            "",
            "本机制**只标注 + 记账，绝不自动放行、也绝不自动恢复**。要恢复合并，由维护者/agent 显式两步：",
            "",
            "1. **修根因**（首选）：按上面的 `remedy` 定位机制并给出红证（注回机制 ⇒ 必红），"
            "再把台账条目标 `status=fixed` + `fixed_by`；或**确认它确为真 flaky 且与本次改动无关**；",
            "2. **显式放行**：移除 `flaky/rerun-green` 与 `block/merge` 两个标签，再 "
            "`gh pr merge --auto --squash` 重新 arm。",
            "",
            f"判据：{decision.get('reason')}",
        ]
    elif decision.get("action") == "record_infra":
        lines += [
            "## 🧰 Flaky Triage —— 重跑绿，但属**基础设施/环境**失败",
            "",
            f"**为什么只记账不打标**：{why}，第 2 次通过；但失败落在"
            "「取代码 · 装依赖 · 配环境」步骤（或 job 从未跑起来）⇒ **环境问题，不是被测对象 flaky**"
            "（把 infra 抖动记成 flaky 会把台账本身变成噪音源）。",
            "",
            *table("首次失败步骤"),
            "",
            f"**下一步（可行动）**：{first.get('remedy') or ''}",
            "",
            "⚠️ 本条**未**卸 auto-merge、**未**打 `flaky/rerun-green`（它不是 flaky）；仅登记台账。",
            "",
            f"判据：{decision.get('reason')}",
        ]
    else:
        lines += [
            "## ❌ Flaky Triage —— 重跑**仍然失败**（确定性失败）",
            "",
            f"**为什么照常失败**：{why}，**第 2 次尝试仍然失败** ⇒ 确定性失败。"
            "已按「照常失败」处理：**不重跑第三次**、**不放行**、**不卸 auto-merge**"
            "（required 检查自己就是红的）。",
            "",
            *table("失败步骤"),
            "",
            f"**下一步（可行动）**：{first.get('remedy') or ''}",
            "",
            f"判据：{decision.get('reason')}",
        ]
    lines += ["", "<sub>机制见 `migao` issue #4717（CI 层两项：重跑分流 + flaky 台账）；"
                  "判据 `tests/unit_ci_workflows/test_flaky_triage.py`</sub>"]
    return "\n".join(lines) + "\n"


def render_summary(decision: dict) -> str:
    return (f"action=`{decision.get('action')}` kind=`{decision.get('kind')}` "
            f"attempt={decision.get('attempt')} pr={decision.get('pr')} "
            f"entries={len(decision.get('entries') or [])} —— {decision.get('reason')}")


# ── CLI ──────────────────────────────────────────────────────────────────────


def _write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CI 失败重跑分流 + flaky 台账（issue #4717）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fetch", help="取 run + 本次/上次尝试的 job 事实（只读网络）")
    p.add_argument("--repo", required=True)
    p.add_argument("--run-id", required=True, type=int)
    p.add_argument("--out", required=True)

    p = sub.add_parser("decide", help="纯函数分流判定（不判定 = 不改任何状态）")
    p.add_argument("--bundle", required=True)
    p.add_argument("--entries-out")
    p.add_argument("--comment-out")
    p.add_argument("--gh-output")
    p.add_argument("--json-out")

    p = sub.add_parser("approve", help="批准被 GITHUB_TOKEN 抑制（action_required）的 PR run")
    p.add_argument("--repo", required=True)
    p.add_argument("--head-branch", required=True,
                   help="只看该分支的 pull_request run（台账分支）")
    p.add_argument("--json-out", help="写出被批准的 run id 列表（供复核/审计）")

    p = sub.add_parser("ledger-drift",
                       help="台账落仓对账（#4825 兜底判据）：台账分支是否领先 main")
    p.add_argument("--branch", default=LEDGER_BRANCH, help="台账分支名")
    p.add_argument("--main-file", default=str(LEDGER_PATH), help="main 侧台账（工作区 = main 检出）")
    p.add_argument("--branch-file", help="离线：直接读该文件当分支台账（测试 / 本地复跑）")
    p.add_argument("--json-out")
    p.add_argument("--gh-output")

    p = sub.add_parser("append", help="只追加 + 幂等地写入台账（`--align-main`：推前先与 main 对齐）")
    p.add_argument("--ledger", default=str(LEDGER_PATH))
    p.add_argument("--entries", required=True)
    p.add_argument("--align-main", action="store_true",
                   help="#5100：推前先与 main 对齐（并集 + 在最新 main 之上重放）；"
                        "需**仓库相对**的 --ledger")
    p.add_argument("--branch", default=LEDGER_BRANCH, help="台账分支名（仅 `--align-main` 用）")
    p.add_argument("--gh-output", help="写出 `lease=<branch>:<sha>`（供 `--force-with-lease` 用）")

    p = sub.add_parser("selftest", help="台账自洽性判据（fail-closed）")
    p.add_argument("--ledger", default=str(LEDGER_PATH))

    p = sub.add_parser("report", help="按 (workflow, job) 聚合（**计数现取**，供后续单消费）")
    p.add_argument("--ledger", default=str(LEDGER_PATH))
    p.add_argument("--json-out")

    p = sub.add_parser("reconcile", help="三态对账：新事件 / 重复计数 / 已修未销账（0/1）")
    p.add_argument("--ledger", default=str(LEDGER_PATH))

    args = ap.parse_args(argv)

    if args.cmd == "fetch":
        bundle = fetch_bundle(args.repo, args.run_id)
        _write(args.out, json.dumps(bundle, ensure_ascii=False))
        run = bundle["run"]
        print(f"📥 run {run.get('id')} `{run.get('name')}` attempt={run.get('run_attempt')} "
              f"conclusion={run.get('conclusion')} event={run.get('event')} "
              f"jobs={len(bundle['jobs'])} prior_jobs="
              f"{'—' if bundle['prior_jobs'] is None else len(bundle['prior_jobs'])}")
        return 0

    if args.cmd == "decide":
        bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
        decision = decide(bundle)
        print(render_summary(decision))
        if args.json_out:
            _write(args.json_out, json.dumps(decision, ensure_ascii=False, indent=2))
        if args.entries_out:
            _write(args.entries_out, json.dumps(decision.get("entries") or [], ensure_ascii=False))
        if args.comment_out:
            _write(args.comment_out, render_comment(decision))
        if args.gh_output:
            with open(args.gh_output, "a", encoding="utf-8") as fh:
                fh.write(f"action={decision['action']}\n")
                fh.write(f"kind={decision['kind'] or ''}\n")
                fh.write(f"pr={decision['pr'] or ''}\n")
                fh.write(f"entry_count={len(decision.get('entries') or [])}\n")
        return 0

    if args.cmd == "approve":
        # ⚠️ 参数名是 **`branch=`**，不是 `head_branch=`（实测：`head_branch=` 被 API **静默忽略**
        #    ⇒ 返回**全仓** 11867 个 run，而不是本分支的 13 个）。写错的失效形态 = 批准一堆无关 run。
        listing = _gh_api(f"repos/{args.repo}/actions/runs"
                          f"?event=pull_request&branch={args.head_branch}&per_page=100")
        all_runs = listing.get("workflow_runs") or []
        needing = set(runs_needing_approval(all_runs, workflows=TRIAGED_WORKFLOWS))
        if not needing:
            # 快速路径：候选为空 ⇒ **不查 tip**（少一次 API 调用，且与既有读数逐字一致）。
            print("✅ 无 `action_required` 的 pull_request run（无需 approve —— 可能已批准或已被正常触发）")
            if args.json_out:
                _write(args.json_out, json.dumps([], ensure_ascii=False))
            return 0
        # #5264：候选**非空** ⇒ 只批准**分支 tip 那一次推送**的 run（收窄理由见 `runs_for_head`）。
        # ⚠️ tip 必须从**分支事实**取：本步骤在 push 台账分支之后**立刻**执行，而 GitHub 创建 run 是
        #    **异步**的 ⇒ 「此刻可见的最新 run」可能还是**上一次**推送的。拿它当 tip = 批准**陈旧 SHA**
        #    却把日志说成「批准了本次推送」（读数与事实不一致）⇒ 故意**不**做这个退回：
        #    解析不到 tip 就 fail-closed（非零退出，workflow 侧会 `::error::` 显性化）。
        candidates = [r for r in all_runs if r.get("id") in needing]
        tip = branch_tip(_gh_api(f"repos/{args.repo}/branches/{args.head_branch}"))
        if not tip:
            print(f"⛔ 无法确定台账分支 `{args.head_branch}` 的 tip（`GET /repos/{{repo}}/branches/…` "
                  f"取不到 `commit.sha`）⇒ 不敢用「最新可见推送」代替 —— 那会把**陈旧 SHA** 的 run "
                  f"批准起来、并把读数说成「批准了本次推送」。**本轮零动作、fail-closed**"
                  f"（历史待批准 {len(needing)} 个一个不批；下一轮触发会重试）。", file=sys.stderr)
            return 1
        ids = sorted(r["id"] for r in runs_for_head(candidates, tip))
        if not ids:
            # 诚实读数：tip 上确实没有待批准 run（GitHub 尚未创建、或已批准）。
            # **不许**在此时改去批准陈旧 SHA（见上）—— 它们对 required 判定零贡献。
            print(f"ℹ️ tip={tip} 暂无待批准 run（尚未创建或已批准）⇒ 本轮零动作，下一轮触发会重试"
                  f"（历史待批准 {len(needing)} 个均为**陈旧推送**，批准它们对 required 判定无贡献）")
            if args.json_out:
                _write(args.json_out, json.dumps([], ensure_ascii=False))
            return 0
        print(f"🔓 历史待批准 {len(needing)} 个，其中属于分支 tip={tip} 的 {len(ids)} 个"
              f" ⇒ 只批准这 {len(ids)} 个（被 GITHUB_TOKEN 抑制 ⇒ 无 job ⇒ 无 check）：{ids}")
        try:
            approve_runs(args.repo, ids)
        except RuntimeError as exc:
            print(f"⛔ approve 失败 ⇒ 台账 PR 仍无 check、`--auto` 仍不会触发（**不许静默**）：{exc}",
                  file=sys.stderr)
            return 1
        print(f"✅ 已 approve {len(ids)} 个 run —— 它们将真正执行并产出 check-runs")
        if args.json_out:
            _write(args.json_out, json.dumps(ids, ensure_ascii=False))
        return 0

    if args.cmd == "ledger-drift":
        age = None
        try:
            main_ledger = load_ledger(Path(args.main_file))
            if args.branch_file:
                branch_ledger = load_ledger(Path(args.branch_file))
            else:
                branch_ledger = read_branch_ledger(args.branch)
                if branch_ledger is not None:
                    age = branch_head_age_minutes()
        except (RuntimeError, OSError, ValueError) as exc:
            print(f"⛔ 无法判定台账漂移（{exc}）⇒ **不得**当「无漂移」读（未跑 ≠ 通过）",
                  file=sys.stderr)
            return 3
        if branch_ledger is None:
            # 分支不存在 ⇒ 没有「已记账却未落 main」的内容。**不**把它读成「main 有而分支没有」
            # （那会凭空报一堆分叉），故显式给零漂移。
            drift = {"ahead": [], "behind": [],
                     "main_total": len(ledger_keys(main_ledger)), "branch_total": 0}
            state = "no-branch"
        else:
            drift = ledger_drift(main_ledger, branch_ledger)
            state = "drift" if drift["ahead"] else "in-sync"
        drift["state"] = state
        drift["age_minutes"] = age
        print(f"📒 台账对账（{args.branch}）：main {drift['main_total']} 条 · "
              f"分支 {drift['branch_total']} 条 ⇒ **领先 main {len(drift['ahead'])} 条** / "
              f"落后 {len(drift['behind'])} 条"
              f"（分支 HEAD {age if age is not None else '—'} 分钟前；状态 {state}）")
        for key in drift["ahead"]:
            print(f"   ⏳ 已记账但未落 main：{key}")
        for key in drift["behind"]:
            print(f"   ⚠️ main 有而分支没有（台账**只追加** ⇒ 这是分叉）：{key}")
        if args.json_out:
            _write(args.json_out, json.dumps(drift, ensure_ascii=False, indent=2))
        if args.gh_output:
            with open(args.gh_output, "a", encoding="utf-8") as fh:
                fh.write(f"drift={1 if drift['ahead'] else 0}\n")
                fh.write(f"ahead={len(drift['ahead'])}\n")
                fh.write(f"behind={len(drift['behind'])}\n")
                fh.write(f"state={state}\n")
                fh.write(f"age_minutes={age if age is not None else ''}\n")
        return 0

    if args.cmd == "append":
        lease = ""
        if args.align_main:
            # #5100：**推前先与 main 对齐**（并集 + 最新 main 之上重放）。失败 ⇒ 拒绝在旧基线上追加。
            try:
                info = align_with_main(args.ledger, args.branch)
            except RuntimeError as exc:
                print(f"⛔ 推前对齐失败（{exc}）⇒ **拒绝在旧基线上追加**（fail-closed，不静默）",
                      file=sys.stderr)
                return 1
            lease = info["lease"]
            print(f"🧭 推前已与 main 对齐：main {info['main_total']} 条 · "
                  f"分支 {info['branch_total']} 条 ⇒ 并集 {info['merged_total']} 条"
                  f"（基线 = origin/main；lease={'有' if lease else '无（分支尚不存在）'}）")
        if args.gh_output:
            # lease 期望值必须**在推送前**交给调用方（它决定 `--force-with-lease=<ref>:<sha>`）；
            # 没走对齐时为空串（= 分支还不存在 ⇒ 调用方用普通推送）。
            with open(args.gh_output, "a", encoding="utf-8") as fh:
                fh.write(f"lease={lease}\n")
        ledger = load_ledger(args.ledger)
        entries = json.loads(Path(args.entries).read_text(encoding="utf-8"))
        bad = ledger_violations(ledger)
        if bad:
            print("⛔ 台账自身不合规，拒绝写入：\n  - " + "\n  - ".join(bad), file=sys.stderr)
            return 1
        added, skipped = append_entries(ledger, entries)
        if not added:
            print(f"⏭️ 幂等：{len(skipped)} 条已登记（键={'/'.join(map(str, skipped[0])) if skipped else '—'}）"
                  " ⇒ 台账未改动")
            return 0
        save_ledger(args.ledger, ledger)
        print(f"📒 台账追加 {len(added)} 条"
              f"（幂等跳过 {len(skipped)} 条）→ {args.ledger}")
        return 0

    if args.cmd == "selftest":
        ledger = load_ledger(args.ledger)
        bad = ledger_violations(ledger)
        if bad:
            print("⛔ 台账不合规：\n  - " + "\n  - ".join(bad), file=sys.stderr)
            return 1
        print(f"✅ 台账自洽（条目数现取 = {len(ledger.get('entries') or [])}）")
        return 0

    if args.cmd == "report":
        ledger = load_ledger(args.ledger)
        groups = aggregate(ledger)
        rows = sorted(groups.values(),
                      key=lambda r: (-r["flaky"], -r["total"], r["job"] or ""))
        print(f"📊 flaky 台账聚合（条目数现取 = {len(ledger.get('entries') or [])}，"
              f"不同 (workflow, job) = {len(rows)}）")
        for row in rows:
            print(f"  · {row['workflow']} :: {row['job']} —— flaky={row['flaky']} "
                  f"confirmed_failure={row['confirmed_failure']} "
                  f"infra_suspect={row['infra_suspect']} 合计={row['total']}"
                  f"（最近 run {row['last_run_id']} @ {row['last_observed_at']}）")
        print("⚠️ 本命令**不设阈值**（不写死计数）：「同一 job 反复 flaky ⇒ 必须修根因」的"
              "判定留给消费方，按 `migao-acceptance`「随机红 = 归因层失效」开单。")
        if args.json_out:
            _write(args.json_out, json.dumps(
                {"entry_total": len(ledger.get("entries") or []), "groups": rows},
                ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "reconcile":
        ledger = load_ledger(args.ledger)
        bad = ledger_violations(ledger)
        if bad:
            print("⛔ 台账不合规（先 `selftest`）：\n  - " + "\n  - ".join(bad), file=sys.stderr)
            return 1
        result = reconcile(ledger)
        dirty = 0
        for name, rows in result.items():
            if not rows:
                continue
            dirty += len(rows)
            print(f"❌ {name} = {len(rows)}")
            for row in rows:
                print(f"   - {row['key']}：{row['why']}")
        if dirty == 0:
            print("✅ 三态对账干净（无未登记修复路径 / 无重复计数 / 无已修未销账）")
            return 0
        print("⚠️ 本命令**未接 required 门禁**（照实登记）：它是**消费接口**，"
              "由后续单 / agent 按需调用 —— 判红不等于阻塞合并。")
        return 1

    return 3


if __name__ == "__main__":
    sys.exit(main())
