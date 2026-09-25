# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012）
"""`scripts/stale_report_reaper.py` —— **腿转绿 ⇒ 自动关陈旧 CI 报告**（issue #5491）。

## 病灶与代价

CI 腿失败会**自动开单**（`[Post-Deploy] …` / `[Nightly] …` / `[drift] …`），腿恢复后报告仍挂着，
**没有任何东西会发现** ⇒ 2026-09-25 的存量清理里 **7 条**这类单子靠人工逐条核验才关掉。

## 判据（三条同时成立才关）

1. 该报告映射到的 workflow 最近 `--consecutive`（默认 3）次**已完成** run 全部 `success`；
2. 最新一次 success **晚于**该 issue 的创建时间（它报的那次失败已被取代）；
3. 该 issue 已存在 **> `--min-age-hours`**（默认 24，不抢跑新报告）。

另加**钉住**：带 `block/need-human` / `ai-draft` / `hold/auto-fail` 的一律不自动关。

## 红证（每条都能单独变红；开发时逐条注入并还原过）

| 注入 | 变红的用例 |
|---|---|
| 去掉「最近 N 次全 success」这条 | `test_red_leg_keeps_issue_open` |
| 去掉「success 晚于 issue 创建」这条 | `test_success_before_issue_creation_keeps_open` |
| 去掉「24h 最小年龄」这条 | `test_too_new_issue_is_not_touched` |
| 去掉 pin 标签判定 | `test_pinned_issue_is_never_touched` |
| 把 dry-run 分支删掉 | `test_dry_run_writes_nothing` |

`gh` 一律用**替身可执行文件**注入（`MIGAO_GH_BIN` + 同时挂到 `PATH` 首位，因为
`agent-presets-guard` 那类模块里有**字面量** `"gh"`）；命令走**真 CLI**（subprocess）。
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "stale_report_reaper.py"

STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$GH_LOG"
case "$1 $2" in
  "issue list") cat "$GH_ISSUES" ;;
  "run list")   cat "$GH_RUNS" ;;
  "run view")   cat "${GH_RUN_LOG:-/dev/null}" ;;
esac
exit 0
"""

NOW = datetime.now(timezone.utc)


def _iso(delta_hours: float) -> str:
    return (NOW - timedelta(hours=delta_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _issue(title: str, *, age_hours: float = 48, labels: list[str] | None = None, number: int = 900,
           author: str = "app/github-actions"):
    """⚠️ 默认作者是 **CI**：2026-09-25 起本脚本加了作者闸门（人写的单永不自动收）⇒
    夹具必须显式表达"这是 CI 开的报告"，否则测的就不是窗口逻辑而是闸门了。"""
    return {"number": number, "title": title, "createdAt": _iso(age_hours),
            "author": {"login": author},
            "labels": [{"name": n} for n in (labels or [])]}


def _runs(conclusions: list[str], hours: list[float]) -> list[dict]:
    return [{"status": "completed", "conclusion": c, "createdAt": _iso(h), "databaseId": 5000 + i}
            for i, (c, h) in enumerate(zip(conclusions, hours))]


def _fixture(tmp_path: Path, issues: list[dict], runs: list[dict] | None = None,
             run_list_rc: int = 0, run_log: str = ""):
    stub = tmp_path / "gh"
    stub.write_text(STUB, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "gh").write_text(STUB, encoding="utf-8")
    (bindir / "gh").chmod(0o755)
    (tmp_path / "issues.json").write_text(json.dumps(issues), encoding="utf-8")
    (tmp_path / "runs.json").write_text(json.dumps(runs or []), encoding="utf-8")
    log = tmp_path / "gh.log"
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
        "MIGAO_GH_BIN": str(stub),
        "GH_LOG": str(log),
        "GH_ISSUES": str(tmp_path / "issues.json"),
        "GH_RUNS": str(tmp_path / ("missing.json" if run_list_rc else "runs.json")),
        "GH_RUN_LOG": str(tmp_path / "runlog.txt"),
    }
    (tmp_path / "runlog.txt").write_text(run_log, encoding="utf-8")
    return env, log


def _run(tmp_path: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=str(tmp_path), env=env,
                          capture_output=True, text=True, timeout=60)


def _calls(log: Path) -> list[str]:
    return [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()] if log.exists() else []


GREEN_RUNS = _runs(["success", "success", "success"], [1, 5, 9])   # 都比 issue（48h 前）新


def test_green_leg_closes_with_evidence_then_reason(tmp_path):
    """腿转绿 ⇒ 关单：**先贴证据评论、再 `close --reason "not planned"`**，并交出计数。"""
    env, log = _fixture(tmp_path, [_issue("[Post-Deploy] 部署后回归失败 — 2026-09-18")], GREEN_RUNS)
    out = _run(tmp_path, env, "--apply")
    assert out.returncode in (0, 2), (out.stdout, out.stderr)
    calls = _calls(log)
    assert calls, "应真的发命令"
    ci = next(i for i, c in enumerate(calls) if c.startswith("issue comment 900"))
    cl = next(i for i, c in enumerate(calls) if c.startswith("issue close 900"))
    assert ci < cl, f"必须先评论后关单，实测：{calls}"
    assert '--reason "not planned"' in calls[cl] or "--reason not planned" in calls[cl], calls[cl]
    assert "MIGAO-REAPER-SUMMARY seen=1 acted=1" in out.stdout, out.stdout


def test_red_leg_keeps_issue_open(tmp_path):
    """最近 3 次里有一次失败 ⇒ 腿仍红 ⇒ **不关**（红证：删掉该判据 ⇒ 本用例红）。"""
    env, log = _fixture(tmp_path, [_issue("[Post-Deploy] 部署后回归失败 — 2026-09-18")],
                        _runs(["success", "failure", "success"], [1, 5, 9]))
    out = _run(tmp_path, env, "--apply")
    assert "未全绿" in out.stdout, out.stdout
    assert not [c for c in _calls(log) if c.startswith("issue close")], "腿仍红却关了单"


def test_success_before_issue_creation_keeps_open(tmp_path):
    """唯一/最新的 success **早于**本报告创建 ⇒ 本次失败未被取代 ⇒ 不关。"""
    env, log = _fixture(tmp_path, [_issue("[Nightly] 全量验证失败 — 2026-09-15", age_hours=48)],
                        _runs(["success", "success", "success"], [72, 80, 96]))
    out = _run(tmp_path, env, "--apply")
    assert "未被取代" in out.stdout, out.stdout
    assert not [c for c in _calls(log) if c.startswith("issue close")]


def test_too_new_issue_is_not_touched(tmp_path):
    """报告太新（< 24h）⇒ 不抢跑（红证：删掉该判据 ⇒ 本用例红）。"""
    env, log = _fixture(tmp_path, [_issue("[drift] 真相源契约审计未通过（定时腿）", age_hours=2)], GREEN_RUNS)
    out = _run(tmp_path, env, "--apply")
    assert "太新" in out.stdout, out.stdout
    assert not [c for c in _calls(log) if c.startswith("issue close")]


def test_pinned_issue_is_never_touched(tmp_path):
    """带 `block/need-human` 的报告**钉住**，永不自动关（红证：删掉 pin 判定 ⇒ 本用例红）。"""
    env, log = _fixture(tmp_path,
                        [_issue("[Post-Deploy] 部署后回归失败 — 2026-09-18", labels=["block/need-human"])],
                        GREEN_RUNS)
    out = _run(tmp_path, env, "--apply")
    assert "钉住" in out.stdout, out.stdout
    assert not [c for c in _calls(log) if c.startswith("issue close")]


def test_dry_run_writes_nothing(tmp_path):
    """默认 dry-run：只打印判定、**零写操作**（红证：删掉 dry-run 分支 ⇒ 本用例红）。"""
    env, log = _fixture(tmp_path, [_issue("[Post-Deploy] 部署后回归失败 — 2026-09-18")], GREEN_RUNS)
    out = _run(tmp_path, env)
    assert out.returncode == 0, (out.stdout, out.stderr)
    assert "dry-run" in out.stdout, out.stdout
    writes = [c for c in _calls(log) if c.startswith(("issue comment", "issue close"))]
    assert not writes, f"dry-run 允许只读查询，但**不许有写操作**：{writes}"


def test_unknown_runs_is_fail_closed(tmp_path):
    """取不到 run 数据 ⇒ **一条都不关** + exit 3（「没跑」必须长得像「没跑」）。"""
    env, log = _fixture(tmp_path, [_issue("[Post-Deploy] 部署后回归失败 — 2026-09-18")],
                        run_list_rc=1)
    out = _run(tmp_path, env, "--apply")
    assert out.returncode == 3, (out.returncode, out.stdout, out.stderr)
    assert "无法判定" in out.stdout, out.stdout
    assert not [c for c in _calls(log) if c.startswith("issue close")]


def test_unmapped_prefix_is_named_not_silently_skipped(tmp_path):
    """未登记前缀（如 `[部署]`，人工开的部署单）⇒ 跳过**并点名**（不静默）。"""
    env, log = _fixture(tmp_path, [_issue("[部署] ai-agent 部署腿的 Post-Deploy P0 Smoke 失败")], GREEN_RUNS)
    out = _run(tmp_path, env, "--apply")
    assert "前缀未登记" in out.stdout and "#900" in out.stdout, out.stdout
    assert not [c for c in _calls(log) if c.startswith("issue close")]

# ── 「自动关单会不会漏东西」的两条守卫（2026-09-25，用户提问驱动）────────────────

def test_human_authored_report_is_never_auto_closed(tmp_path):
    """**人写的单永不自动收** —— 哪怕标题前缀与自动报告模板完全一致。

    为什么：本脚本只按标题前缀认单，而人完全可能写同前缀的标题；那种单里往往有**人补充的上下文**
    ⇒ 自动关掉就是**丢证据**。⇒ 作者不是 CI/机器人 ⇒ 一条都不关（并点名）。
    红证形态：去掉作者闸门 ⇒ 本判据立刻红。
    """
    human = _issue("[Post-Deploy] 部署后回归失败 — 我补充了现场日志", author="guangzhen")
    env, log = _fixture(tmp_path, [human], GREEN_RUNS)
    out = _run(tmp_path, env, "--apply")
    calls = _calls(log)
    assert not any(c.startswith("issue close") for c in calls), f"人写的单被自动关了：{calls}"
    assert not any(c.startswith("issue comment") for c in calls), f"对人写的单贴了自动证据评论：{calls}"
    assert "作者不是 CI/机器人" in out.stdout, out.stdout


def test_green_but_no_readings_is_not_closed(tmp_path):
    """**窗口驱动**的腿（post-merge）：run 绿但**取不到「判过」的证据** ⇒ 不关。

    为什么（实测两种假绿，都会丢信号）：① 「零动作/短路径」的绿 —— 窗口内无变更时 2m56s 就 success、
    **一条判据都没跑**；② 「判据自 skip」的绿 —— `test_drift_audit_contract.py` 在浅检出里自己 skip。
    ⇒ 只看 `conclusion == success` 就关单 = 把"**没判**"当成"**判过了**"。
    红证形态：让 `run_has_readings` 恒 True ⇒ 本判据立刻红。
    """
    issue = _issue("[post-merge] main 上的判据与它约束的数据不同刻落地（合并后守护腿未通过）")
    # 让标题映射到 post-merge 腿：直接用 --only + 该前缀（前缀表里加）
    env, log = _fixture(tmp_path, [issue], GREEN_RUNS, run_log="（日志里没有任何读数行）\n")
    out = _run(tmp_path, env, "--apply")
    calls = _calls(log)
    assert not any(c.startswith("issue close") for c in calls), f"没有「判过」证据却关了：{calls}"
    assert "无法判定" in out.stdout or "不关" in out.stdout, out.stdout


def test_green_with_readings_closes(tmp_path):
    """正控：同一条腿，run 绿 **且日志里跑判据 > 0** ⇒ 正常关（守卫不能把正常路径也堵死）。"""
    issue = _issue("[post-merge] main 上的判据与它约束的数据不同刻落地（合并后守护腿未通过）")
    env, log = _fixture(tmp_path, [issue], GREEN_RUNS,
                        run_log="读数（与负载无关）：变更文件 21 / 命中判据 66 / 跑判据 66\n")
    out = _run(tmp_path, env, "--apply")
    calls = _calls(log)
    assert any(c.startswith("issue close") for c in calls), f"有「判过」证据却没关：{calls} / {out.stdout}"
