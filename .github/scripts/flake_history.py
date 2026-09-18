#!/usr/bin/env python3
"""跨 run 波动指纹索引（issue #3806）—— 纯取数，**不跑评测**。

## 为什么需要

放行政策（`llm-noise` = 首跑失败 + 重试通过）原先只看**本次 run 的两次尝试**，
而台账是每次 run 独立生成的 ⇒ 「同一首跑指纹」可以永远"首次出现"，
一个"首跑必败、重试偶过"的系统性缺口就被长期按"波动"放行
（实证 PR-016：首跑指纹在 **3/3** 次 run 都出现、首跑通过率 **0/3**，
第三次因"重试碰巧过"被判 `llm-noise`）。

判据补一维需要**历史**；历史来源就是仓库已有的 flake 台账 artifact
（`agent-eval-flakes.json`，各评测 workflow 都上传、保留 30 天）——
本脚本把它们汇总成一份**滚动索引**，供 `local_runner.completion_verdict` 消费。

⚠️ 它**只消费既有 artifact**：没有任何一步需要额外派发真实评测（成本纪律）。
取不到历史（无 gh 凭据 / 首次 / 网络失败）时输出空索引，判定退化为现状 ——
**不新增假红**；反过来，只要索引在，复发就必须显式处理（fail-closed）。

## 用法

    flake_history.py fetch --out flake-history.json [--limit 12]     # 汇总历史（CI 跑这一步）
    flake_history.py merge --history H --ledger L [--ledger L2] --run-id RID
    flake_history.py show  --history H

索引形态：`{"<case_id>": {"<首跑指纹>": {"runs": ["<run_id>", ...]}}}`，
由 `tests/agent_eval/local_runner.py::merge_flake_history` 生成（**单一实现**：
本脚本不复制那份逻辑，避免"两份口径"）。
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"


def _load_runner():
    """加载 runner 以复用 `merge_flake_history` / `load_flake_history`（单一实现）。"""
    spec = importlib.util.spec_from_file_location("migao_eval_runner_flake_history", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lr = _load_runner()

# ── 台账 artifact 的**真实**名字前缀（#3806 复核；2026-09-15 实测）───────────────
# ⚠️ 本常量是"机制是否活着"的唯一开关：命中不了真实名字 ⇒ 索引恒空 ⇒ 复发判据
# **永不生效**（"实现了但永不生效"，本仓库最贵的假绿形态）。
#
# 实测证据（`gh api repos/<repo>/actions/artifacts?per_page=100`，2026-09-15）：
#   · `agent-eval-flake-ledger`                     ← agent-eval.yml
#   · `agent-eval-flake-ledger-behavior-<persona>`  ← agent-behavior-eval.yml（**已随 #4275 删除**，
#                                                     该 artifact 名只存在于历史 run，属**遗留**）
#   · `agent-eval-flake-ledger-shard<N>`            ← xiaobu-acceptance.yml
#   · `post-deploy-eval-<persona>`                  ← post-deploy-eval.yml（汇总+台账同 artifact）
# 抢救包的原值 `agent-eval-flakes` **一个都匹配不上**（真实名字里 `flake` 后是 `-` 而非 `s`）
# —— 而它的单测用的是**编造**的 artifact 名（`agent-eval-flakes`），于是守卫恰好掩盖了缺口：
# 用真实名字跑 `flake_history.py fetch` 得到的是 `命中 flake 台账 artifact 0 个 / 0 条用例`。
#
# 防复发：`tests/unit_ci_workflows/test_flake_history_index.py::
# TestArtifactPrefixesMatchRealProducers` 从 **workflow 源**（唯一事实源）派生"哪些 artifact
# 装着台账"，逐条断言被本常量命中 ⇒ 新增/改名上传点而不更新这里 → 直接红。
FLAKE_ARTIFACT_PREFIXES = (
    "agent-eval-flake",     # 三处 `agent-eval-flake-ledger*`
    "post-deploy-eval-",    # post-deploy：台账与汇总同一个 artifact
)
FLAKE_LEDGER_NAME = "agent-eval-flakes.json"


def select_flake_artifacts(artifacts: list, limit: int = 12,
                           prefixes: tuple = FLAKE_ARTIFACT_PREFIXES) -> list:
    """从 `gh api .../artifacts` 的结果里挑出 flake 台账 artifact（纯函数，可单测）。

    排序 = 创建时间**倒序**（新的在前）；只保留 `expired == false` 的。
    `prefixes` 收字符串是**容错**（`startswith(str)` 会按单字符元组逐字匹配 ⇒ 静默恒假，
    正是本单踩过的形态）；调用方仍应传元组，默认值即 `FLAKE_ARTIFACT_PREFIXES`。
    """
    if isinstance(prefixes, str):
        prefixes = (prefixes,)
    picked = [a for a in (artifacts or [])
              if str(a.get("name") or "").startswith(tuple(prefixes))
              and not a.get("expired")]
    picked.sort(key=lambda a: str(a.get("created_at") or ""), reverse=True)
    return picked[:max(0, int(limit))]


def _gh(args: list, timeout: int = 120) -> str:
    return subprocess.check_output(["gh"] + args, text=True, timeout=timeout)


def list_artifacts(repo: str) -> list:
    """列举本仓库最近的 artifact（含跨 workflow 的 flake 台账）。"""
    raw = _gh(["api", f"repos/{repo}/actions/artifacts?per_page=100"])
    return (json.loads(raw) or {}).get("artifacts") or []


def download_ledger(repo: str, artifact: dict, dest: Path) -> dict | None:
    """下载单个 artifact，找出其中的台账 JSON 并返回（失败返回 None，不致命）。"""
    run_id = str((artifact.get("workflow_run") or {}).get("id") or "")
    name = str(artifact.get("name") or "")
    if not run_id or not name:
        return None
    d = dest / f"{run_id}-{name}"
    d.mkdir(parents=True, exist_ok=True)
    try:
        _gh(["run", "download", run_id, "-n", name, "-D", str(d), "-R", repo])
    except Exception:
        return None
    hit = next(iter(sorted(d.rglob(FLAKE_LEDGER_NAME))), None)
    if hit is None:
        return None
    try:
        data = json.loads(hit.read_text(encoding="utf-8"))
    except Exception:
        return None
    return {"run_id": run_id, "artifact": name, "entries": data if isinstance(data, list) else []}


def fetch_history(repo: str, limit: int, out: Path) -> dict:
    """汇总历史台账 → 滚动索引（写入 out）。任何单点失败都不致命。"""
    history: dict = {}
    try:
        arts = select_flake_artifacts(list_artifacts(repo), limit=limit)
    except Exception as e:
        print(f"⚠️ 列举 artifact 失败（历史为空，判定退化为现状）: {e}")
        arts = []
    print(f"ℹ️ 命中 flake 台账 artifact {len(arts)} 个（limit={limit}）")
    with tempfile.TemporaryDirectory() as td:
        for a in arts:
            got = download_ledger(repo, a, Path(td))
            if not got:
                print(f"   ⚠️ 取不到台账：{a.get('name')}（run {(a.get('workflow_run') or {}).get('id')}）")
                continue
            history = lr.merge_flake_history(history, got["entries"], got["run_id"])
            print(f"   ✓ {got['artifact']} run={got['run_id']} 台账 {len(got['entries'])} 条")
    out.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")
    cases = len(history)
    fps = sum(len(v or {}) for v in history.values())
    print(f"📇 跨 run 指纹索引 → {out}（{cases} 条用例 / {fps} 个指纹）")
    if not history:
        # **不许静默退化**（#3806 的立意与 #3803 同族）：索引为空 ⇒ 复发判据本次不生效
        # ⇒ 放行政策悄悄退回"只看本次两次尝试"（正是本单要修的那个口径）。
        # 用 `::warning::` 落进 run 的 annotation，让人在 run 页面上就能看见
        # （`continue-on-error: true` 只保证"不因此变红"，不保证"看得见"）。
        print("::warning::跨 run 波动指纹索引为空（未命中任何 flake 台账 artifact，"
              f"prefixes={FLAKE_ARTIFACT_PREFIXES}）—— #3806 的复发判据本次**不生效**，"
              "放行政策退化为只按本次两次尝试；若本应命中，说明上传点改名/过期了")
    return history


def merge_ledgers(history_path: Path, ledger_paths: list, run_id: str) -> dict:
    """把本次 run 的台账并入索引（幂等：同一 run_id 不重复计数）。"""
    history = lr.load_flake_history(str(history_path)) if history_path.exists() else {}
    for p in ledger_paths:
        try:
            entries = json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:
            continue
        history = lr.merge_flake_history(history, entries if isinstance(entries, list) else [],
                                        run_id or os.environ.get("GITHUB_RUN_ID", "local"))
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"📇 已并入 → {history_path}")
    return history


def main() -> int:
    ap = argparse.ArgumentParser(description="跨 run 波动指纹索引（#3806，纯取数）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="汇总既有 flake 台账 artifact → 滚动索引")
    f.add_argument("--out", default="flake-history.json")
    f.add_argument("--limit", type=int, default=12)
    f.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))

    m = sub.add_parser("merge", help="把本次 run 的台账并入索引")
    m.add_argument("--history", default="flake-history.json")
    m.add_argument("--ledger", action="append", default=[])
    m.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "local"))

    s = sub.add_parser("show", help="打印索引摘要")
    s.add_argument("--history", default="flake-history.json")

    args = ap.parse_args()
    if args.cmd == "fetch":
        if not args.repo:
            print("⚠️ 未提供 --repo 且 GITHUB_REPOSITORY 为空 → 写空索引（判定退化为现状）")
            print("::warning::跨 run 波动指纹索引未取（GITHUB_REPOSITORY 为空）"
                  "—— #3806 的复发判据本次**不生效**")
            Path(args.out).write_text("{}", encoding="utf-8")
            return 0
        fetch_history(args.repo, args.limit, Path(args.out))
        return 0
    if args.cmd == "merge":
        merge_ledgers(Path(args.history), args.ledger, args.run_id)
        return 0
    hist = lr.load_flake_history(args.history)
    for cid, fps in sorted(hist.items()):
        for fp, info in sorted((fps or {}).items()):
            print(f"{cid}\t{len(info.get('runs') or [])}\t{fp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
