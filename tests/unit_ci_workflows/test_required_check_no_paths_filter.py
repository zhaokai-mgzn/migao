# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012。）
r"""**required 检查不得被 workflow 级 `paths:` 过滤遮住**（issue #3507 ① / #4786 / #5101 的类级锁）。

## 病根（一类缺陷：**required 检查永不报告 ⇒ PR 永久 BLOCKED，且没有任何东西会变红**）

GitHub 的分支保护按「**检查名**」要 required 状态。若提供该检查名的 workflow 在
`on.pull_request` 上带 `paths:` / `paths-ignore:` 过滤，那么**不碰这些路径的 PR 上该 workflow
根本不触发** ⇒ 那条 required 检查**永远不会被上报** ⇒ PR 卡在
`Expected — waiting for status to be reported`，**既不合也并不变红**（"全绿却合不了"，
排查极易被引向 CI / 冲突 / label —— 与 #4231 同族）。

本仓**已被这个形态烧过两次**（`docs/wiki/CI-CD.md`「变更门控」+ `migao-dev-flow` §2.2）：
**翻一条 job 成 required 有两条前置，缺一不可** —— ① 它在每个 PR 上都会被上报
（该 workflow 的 `on.pull_request` **不得**有 `paths:` 过滤）② 它的判定方式是确定的。
**实证**：#5101 上把 `worker-h5 unit tests` 与 `Mini-app e2e static contract preflight`
翻成 required 后**立刻 `BLOCKED`**；撤回两条后立刻 `MERGEABLE/CLEAN`（零代码改动）。

## 本判据（三条腿，各自能单独变红）

| # | 判据 | 红证（只改一处即翻转） |
|---|---|---|
| 1 | **凡上报 required 检查名的 workflow，其 `on.pull_request` 不得有 `paths` / `paths-ignore`** | 往 `.github/workflows/mini-app.yml` 的 `on.pull_request` 加一行 `paths: ['frontend/mini-app/**']` ⇒ 必红（红证实跑记录见 PR body） |
| 2 | **snapshot 的每个 required 名都必须真被某个 PR 触发 job 上报**（陈旧检测：job 改名 / 删除 / 从未上报 ⇒ 红） | 把 snapshot 里某个名改一个字 ⇒ 必红 |
| 3 | **snapshot 与成本台账的 `required` 口径必须一致**（两个数据文件不许各说各话） | 把 `ci_cost_ledger.json` 里某条 `required` 翻转 ⇒ 必红 |

## required 集合从哪来（**取法选择与边界，照实登记**）

- **首选（attended / 本机）：现取 API** ——
  `gh api repos/<owner>/<repo>/branches/main/protection`（复用 `scripts/merge_gate.py` 的
  `gh_repo` / `fetch_required`，**不另写一套读法**）。现取成功时与 snapshot **逐字比对**：
  不一致 ⇒ **红**（判据 4，逼你刷新 snapshot），并打印可复制的刷新命令。
- **退路（CI）：checked-in snapshot** —— `ci workflow tests` job **读不到**该 API：
  `GET /branches/main/protection` **需 admin**，而 CI 只有 `secrets.GITHUB_TOKEN`
  （该事实在本仓 `tests/unit_ci_workflows/test_automerge_bot_safe_path.py` 与
  `.github/workflows/automerge.yml` 里都已实测登记）。此时退回
  `required_status_snapshot.json`，并**大字打印**「当前走的是 snapshot 形态」+ 捕获时间 +
  年龄 + 刷新命令。
- 🔴 **退路不覆盖什么（不许读成"已覆盖"）**：CI 里**无法**发现「分支保护新增了一条 required、
  而 snapshot 还不知道」—— 那条新 required 若恰好带 `paths:` 过滤，CI **不会**红。
  覆盖它的唯一形态是 **attended 现取比对**（判据 4）⇒ 引入/变更分支保护后**必须**在本机
  （或任何能读该 API 的环境）跑一次本文件，并按提示刷新 snapshot。
  判据 2/3 在 CI 里仍然有效：**已知** required 名一旦失去上报来源、或与台账口径脱节，都会红。

## 一键复算 / 刷新

    python3 -m pytest tests/unit_ci_workflows/test_required_check_no_paths_filter.py -q -s
    python3 tests/unit_ci_workflows/test_required_check_no_paths_filter.py --refresh   # 现取 API 重写 snapshot

（`--refresh` 需要能读分支保护的凭据；读不到即**非零退出**，绝不静默写空集合。）
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO / ".github" / "workflows"
SNAPSHOT_PATH = REPO / "tests" / "unit_ci_workflows" / "required_status_snapshot.json"
LEDGER_PATH = REPO / "tests" / "unit_ci_workflows" / "ci_cost_ledger.json"
MERGE_GATE_PATH = REPO / "scripts" / "merge_gate.py"
SELF_REL = "tests/unit_ci_workflows/test_required_check_no_paths_filter.py"

REPO_SLUG = "zhaokai-mgzn/migao"
BRANCH = "main"
REFRESH_CMD = f"python3 {SELF_REL} --refresh"


# ══════════════════════════════════════════════════════════════════════════════
# 现取 required 集合（复用 scripts/merge_gate.py 的读法，不另写一套）
# ══════════════════════════════════════════════════════════════════════════════


def _merge_gate():
    spec = importlib.util.spec_from_file_location("merge_gate_for_required_guard", MERGE_GATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _live_required() -> set[str] | None:
    """现取 required 集合；**读不到 ⇒ `None`**（`None` 不是空集合 —— 空集合会被读成"没有 required"）。"""
    mg = _merge_gate()
    gh_bin = os.environ.get("MG_GH_BIN", "gh")
    try:
        return set(mg.fetch_required(mg.gh_repo(gh_bin), BRANCH, gh_bin))
    except mg.Undecidable:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 读真实 YAML（不按文件名/文案清单枚举）
# ══════════════════════════════════════════════════════════════════════════════


def _pr_config(doc: dict) -> dict | None:
    on = doc.get("on") if isinstance(doc.get("on"), dict) else doc.get(True)
    if not isinstance(on, dict) or on.get("pull_request") is None:
        return None
    pr = on["pull_request"]
    return pr if isinstance(pr, dict) else {}


def _workflows() -> dict[str, dict]:
    return {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(WORKFLOWS_DIR.glob("*.yml"))}


def _pr_reported_checks() -> tuple[dict[str, set[str]], dict[str, list[str]]]:
    """→ (workflow 文件 → 它在 PR 事件上**会上报**的检查名集合, 检查名 → 上报它的 `workflow::job` 清单)。"""
    by_workflow: dict[str, set[str]] = {}
    by_check: dict[str, list[str]] = {}
    for name, doc in _workflows().items():
        if _pr_config(doc) is None:
            continue
        names: set[str] = set()
        for jid, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            check = str(job.get("name") or jid)
            names.add(check)
            by_check.setdefault(check, []).append(f"{name}::{jid}")
        by_workflow[name] = names
    return by_workflow, by_check


def _snapshot() -> dict:
    assert SNAPSHOT_PATH.exists(), (
        f"缺 required 集合 snapshot：{SNAPSHOT_PATH.relative_to(REPO)}（fail-closed —— 没有它本判据会静默空跑）"
    )
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _snapshot_contexts() -> list[str]:
    ctx = _snapshot().get("contexts")
    assert isinstance(ctx, list), "snapshot 的 `contexts` 必须是数组（形态漂移 ⇒ 红）"
    assert len(ctx) > 0, "snapshot 的 `contexts` 是**空集** ⇒ 本判据会在空集上恒真（空跑成绿）"
    assert len(set(ctx)) == len(ctx), f"snapshot 的 `contexts` 有重复项 ⇒ 同名 required 被登记两次：{sorted(ctx)}"
    for name in ctx:
        assert isinstance(name, str) and name.strip() == name and name, f"snapshot 里的检查名不合规：{name!r}"
    return [str(c) for c in ctx]


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1（承重）：required 检查不得被 workflow 级 paths 过滤遮住
# ══════════════════════════════════════════════════════════════════════════════


def test_no_pr_paths_filter_on_a_workflow_reporting_a_required_check() -> None:
    """🔴 承重判据：上报 required 检查名的 workflow 不得在 `on.pull_request` 上带 `paths` / `paths-ignore`。"""
    required = set(_snapshot_contexts())
    by_workflow, _ = _pr_reported_checks()
    scanned = 0
    offenders: list[str] = []
    filtered_but_not_required: list[str] = []
    for wf, names in sorted(by_workflow.items()):
        pr = _pr_config(_workflows()[wf]) or {}
        paths = list(pr.get("paths") or [])
        ignored = list(pr.get("paths-ignore") or [])
        scanned += 1
        if not (paths or ignored):
            continue
        hit = sorted(names & required)
        if hit:
            offenders.append(
                f"{wf}：`on.pull_request` 带过滤 paths={paths} paths-ignore={ignored}，"
                f"而它上报 required 检查 {hit} ⇒ 不碰这些路径的 PR **永远拿不到该检查**"
                "（GitHub 报 `Expected — waiting for status to be reported`，且**不会变红**）"
            )
        else:
            filtered_but_not_required.append(wf)
    print(f"扫到 PR 触发 workflow {scanned} 个；其中 PR 级路径过滤 {len(filtered_but_not_required) + len(offenders)} 个"
          f"（**非 required** 的过滤属合法例外：{filtered_but_not_required}）；"
          f"snapshot required 名 {len(required)} 条")
    assert scanned > 0, "一个 PR 触发 workflow 都没扫到 ⇒ 读法失效（本判据会静默空跑成绿）"
    assert not offenders, (
        "「required 检查被 workflow 级 paths 过滤遮住」—— 这是**永久 BLOCKED 且无红信号**的形态"
        "（issue #3507 ①；实证据 #5101 / #4786）：\n"
        + "\n".join("  " + o for o in offenders)
        + "\n修法（二选一）：① **删掉** workflow 级 `paths:`，改成 job 内 diff 门控"
        "（`git diff --name-only origin/main...HEAD` + `$GITHUB_OUTPUT`，同 `pr-check.yml` 的"
        " `Detect admin-web changes` 步，登记册见 tests/unit_ci_workflows/declaration_gate_registry.json）；"
        "② 真的不需要它当 required ⇒ **从分支保护里撤掉**这条检查（不是留着 paths 过滤）。"
        "⚠️ 顺序不可换：**先删 paths、再改分支保护**（见 docs/wiki/CI-CD.md「变更门控」）。"
    )


def test_every_snapshot_context_is_reported_by_a_pr_triggered_job() -> None:
    """判据 2：snapshot 里每个 required 名都必须真被某个 PR 触发 job 上报（陈旧 ⇒ 红）。"""
    required = _snapshot_contexts()
    _, by_check = _pr_reported_checks()
    missing = [c for c in required if c not in by_check]
    print(f"snapshot required={len(required)} 条；能在 PR 触发 workflow 里找到上报者的={len(required) - len(missing)} 条")
    assert not missing, (
        "snapshot 里的检查名**在 PR 触发 workflow 里找不到任何上报它的 job** ⇒ snapshot 陈旧"
        "（job 被改名/删除），或该 required 检查由非 PR 触发面提供（那本身就是 PR 永久 BLOCKED 形态）：\n"
        + "\n".join(f"  {c}" for c in missing)
        + f"\n修法：本机跑 `{REFRESH_CMD}` 用现取 API 重写 snapshot；"
        "若该名字仍存在但 job 改了名，说明**分支保护与新名字脱节** ⇒ 先对齐分支保护。"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 3：snapshot 与成本台账口径一致（两个数据文件不许各说各话）
# ══════════════════════════════════════════════════════════════════════════════


def test_snapshot_and_cost_ledger_agree_on_required_set() -> None:
    """判据 3：台账里 `required: true` 的检查名集合 ≡ snapshot 的 required 集合。"""
    assert LEDGER_PATH.exists(), f"缺成本台账：{LEDGER_PATH.relative_to(REPO)}（issue #3507 ②）"
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    legs = ledger.get("legs") or []
    in_ledger = {str(leg["check_name"]) for leg in legs if leg.get("required") is True}
    required = set(_snapshot_contexts())
    print(f"台账 required 腿={len(in_ledger)} 条；snapshot required={len(required)} 条")
    assert len(legs) >= len(required), (
        f"台账只有 {len(legs)} 条腿 < required {len(required)} 条 ⇒ 台账漏登记（漏掉的腿不会被任何判据看到）"
    )
    assert in_ledger == required, (
        "台账的 `required` 口径与分支保护 snapshot **不一致**（两边必须同源）：\n"
        f"  只在台账里：{sorted(in_ledger - required)}\n"
        f"  只在 snapshot 里：{sorted(required - in_ledger)}\n"
        f"修法：本机跑 `{REFRESH_CMD}` 刷新 snapshot，或把台账按现取 required 重算"
        "（`python3 scripts/ci_cost_ledger.py --measure`）。"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 4：现取可用时，snapshot 必须与现取**逐字**一致（陈旧 ⇒ 红）
# ══════════════════════════════════════════════════════════════════════════════


def test_snapshot_matches_live_required_set_when_readable() -> None:
    """判据 4：能读到分支保护时，snapshot 必须与现取一致；读不到 ⇒ **大字退路横幅**（不谎报成通过）。"""
    snap = _snapshot()
    live = _live_required()
    if live is None:
        captured = str(snap.get("captured_at") or "")
        age = _age_days(captured)
        print(
            "\n" + "=" * 78 + "\n"
            f"⚠️ 退路形态：现取分支保护**读不到**（CI 的 GITHUB_TOKEN 无 admin，见 .github/workflows/automerge.yml）\n"
            f"   判据走 checked-in snapshot：captured_at={captured!r}（{age}）\n"
            f"   snapshot 覆盖：已知 required 名 {len(snap.get('contexts') or [])} 条 —— 判据 1/2/3 照常生效\n"
            f"   snapshot **不**覆盖：分支保护**新增**了某条 required 而 snapshot 还不知道（那条若带 paths 过滤，CI 不会红）\n"
            f"   ⇒ 引入/变更分支保护后，请在能读该 API 的环境跑一次 `{REFRESH_CMD}`\n"
            + "=" * 78
        )
        assert live is None
        return
    assert set(live) == set(_snapshot_contexts()), (
        "现取 required 集合与 snapshot **不一致** ⇒ snapshot 陈旧（CI 退路会按旧集合判，新集合的 paths 遮盖查不出来）：\n"
        f"  只在现取里（snapshot 缺）：{sorted(set(live) - set(_snapshot_contexts()))}\n"
        f"  只在 snapshot 里（现取已无）：{sorted(set(_snapshot_contexts()) - set(live))}\n"
        f"修法：`{REFRESH_CMD}`（会重写 snapshot 的 contexts 与 captured_at）。"
    )
    print(f"现取 required={len(live)} 条，与 snapshot 逐字一致 ✅")


def _age_days(captured: str) -> str:
    try:
        when = datetime.strptime(captured, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return f"捕获时间无法解析（{captured!r}）"
    days = (datetime.now(timezone.utc) - when).total_seconds() / 86400.0
    return f"{days:.1f} 天前"


# ══════════════════════════════════════════════════════════════════════════════
# 一键刷新（`--refresh`）：现取 API → 重写 snapshot
# ══════════════════════════════════════════════════════════════════════════════


def refresh_snapshot() -> int:
    """现取分支保护 required 集合并重写 snapshot。**读不到即非零退出**（绝不写空集合）。"""
    live = _live_required()
    if live is None:
        print(f"❌ 读不到分支保护 required 集合（需 admin 凭据；gh 是否已登录？）⇒ **不写** snapshot。\n"
              f"   命令：gh api repos/{REPO_SLUG}/branches/{BRANCH}/protection --jq '.required_status_checks.contexts[]'",
              file=sys.stderr)
        return 3
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = {
        "schema": "required-status-snapshot/v1",
        "what": (
            "分支保护 required 检查名的**只读快照**（issue #3507 ①）。用途：CI 里读不到 "
            "`GET /branches/main/protection`（需 admin）时，判据仍能对「已知 required 名」执行"
            "「不得被 workflow 级 paths 过滤遮住」这条类级锁。"
        ),
        "repo": REPO_SLUG,
        "branch": BRANCH,
        "captured_at": now,
        "capture_command": f"gh api repos/{REPO_SLUG}/branches/{BRANCH}/protection --jq '.required_status_checks.contexts[]'",
        "refresh_command": REFRESH_CMD,
        "contexts": sorted(live),
    }
    SNAPSHOT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ 已重写 {SNAPSHOT_PATH.relative_to(REPO)}：required {len(live)} 条 @ {now}")
    return 0


if __name__ == "__main__":  # pragma: no cover —— 刷新入口，不参与 pytest 收集
    if "--refresh" in sys.argv:
        raise SystemExit(refresh_snapshot())
    print(f"用法：python3 {SELF_REL} --refresh", file=sys.stderr)
    raise SystemExit(2)
