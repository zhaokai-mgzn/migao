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

import importlib.machinery
import importlib.util
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


def test_redproof_green_with_injections_closes(tmp_path):
    """`[red-proof]` 的「真跑过」口径与 `[post-merge]` **不同字面量**（`真跑 N 条`，不是 `跑判据 N`）。

    为什么单独一条：本腿是 2026-10-01 才纳入自动回收射程的，若读数口径没同批覆盖，
    它就成了「永远关不掉」的登记（登记了却零动作 = 假交付）。
    """
    issue = _issue("[red-proof] 红证实跑巡检未通过（注入 ⇒ 判据不红 ⇔ 红证已退化）")
    env, log = _fixture(tmp_path, [issue], GREEN_RUNS,
                        run_log="巡检读数：登记 13 条 / 真跑 13 条 / 跳过 0 条（原因：无）\n")
    out = _run(tmp_path, env, "--apply")
    calls = _calls(log)
    assert any(c.startswith("issue close") for c in calls), f"有「真跑」证据却没关：{calls} / {out.stdout}"


def test_redproof_zero_action_green_is_not_closed(tmp_path):
    """反向对照：同一条腿「真跑 **0** 条」的绿 ⇒ **不得**当「判过了」（fail-closed）。"""
    issue = _issue("[red-proof] 红证实跑巡检未通过（注入 ⇒ 判据不红 ⇔ 红证已退化）")
    env, log = _fixture(tmp_path, [issue], GREEN_RUNS,
                        run_log="巡检读数：登记 13 条 / 真跑 0 条 / 跳过 13 条（原因：无）\n")
    out = _run(tmp_path, env, "--apply")
    calls = _calls(log)
    assert not any(c.startswith("issue close") for c in calls), f"零动作的绿被当成判过了：{calls}"


# ── 类级元守卫：**会自动开单的腿必须逐条登记**（2026-10-01，issue #5814 收口复核发现）──────────
#
# 病（现取）：`main-freshness-guard` / `redproof-sweep` / `fixture-record` 三条腿**会自动开单却从未登记**
# ⇒ 腿转绿后报告**永远不会被回收**（实测 #5866：main 侧生成物新鲜度腿自 05:45Z 起连续 success，
# 而该单仍 open，reaper 每轮只打印「前缀未登记」）。这正是 issue #5491 要治的病，只是漏在**登记面** ——
# 登记表是手工维护的，新腿却会自动出现 ⇒ 漏登记**不会红**，只会静默退化成「这张单永远挂着」。
# 本守卫就是那条绊线：现取（扫 workflow 正文）⇄ 登记（可回收表 ∪ 有意不回收表）双向对账。

WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def _load_reaper():
    """按仓内惯例动态加载 `scripts/**` 模块（纯模块，`__main__` 之外零副作用）。"""
    loader = importlib.machinery.SourceFileLoader("stale_report_reaper_under_test", str(CLI))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


REAPER = _load_reaper()


def _corpus() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(WORKFLOWS_DIR.glob("*.yml"))}


def test_every_issue_opening_leg_is_registered():
    """**未登记即红**：会自动开单的腿，必须二选一 —— 进「可回收」表，或进「有意不回收」表（带理由）。

    红证形态：往 `.github/workflows/` 加一条带 `gh issue create` 的腿（不登记）⇒ 本判据立刻具名判红。
    """
    unregistered = REAPER.unregistered_issue_opening_legs(_corpus())
    assert not unregistered, (
        "以下腿**会自动开单但没有登记** ⇒ 腿转绿后它的报告将**永远挂着**（issue #5491 的病灶）：\n  "
        + "\n  ".join(f"{wf}：{why}" for wf, why in sorted(unregistered.items())))


def test_coverage_guard_has_discriminating_power():
    """判别力自证（内存注入，不碰真语料）：五种形态各自给出正确判定 + 对照读数。

    ① 新腿带 `gh issue create` 未登记 ⇒ **具名判红**；
    ② 同一份文本登记进「可回收」表 ⇒ **不报**（对照读数）；
    ③ `actions/github-script` 的 `issues.create(` 形态 ⇒ **同样**算开单腿（只扫 `gh issue create` 会漏 ——
       实测 `fixture-record.yml` 正是这个形态）；
    ④ `issues.createComment(` ⇒ **不算**（只评论不建单，`pr-issue-link.yml` 等属此类）⇒ 不报；
    ⑤ 整行 YAML **注释**里提一句 `gh issue create` ⇒ **不算**（对照读数：判据不许被自己的文案喂红 ——
       本仓反复踩过的「守卫扫到自己」形态）。
    """
    opener = "run: gh issue create --title '[X] 失败'\n"
    stray = {"brand-new-leg.yml": opener}
    got = REAPER.unregistered_issue_opening_legs(stray)
    assert "brand-new-leg.yml" in got, f"未登记的开单腿没被判红：{got}"

    registered = REAPER.unregistered_issue_opening_legs(
        stray, reapable={"brand-new-leg.yml"})
    assert registered == {}, f"已登记的腿仍被判红（假红）：{registered}"

    script_style = {"x.yml": "await github.rest.issues.create({\n  title,\n})\n"}
    assert "x.yml" in REAPER.unregistered_issue_opening_legs(script_style), "github-script 形态的开单腿漏判"

    comment_only = {"y.yml": "await github.rest.issues.createComment({\n  body,\n})\n"}
    assert REAPER.unregistered_issue_opening_legs(comment_only) == {}, "「只评论不建单」被误判成开单腿"

    yaml_comment = {"z.yml": "# 失败时 gh issue create 一张单（本行是注释，不是开单）\nrun: echo hi\n"}
    assert REAPER.unregistered_issue_opening_legs(yaml_comment) == {}, "注释里的字样被当成开单腿（自己成为命中源）"


def test_watchdog_leg_is_registered_as_intentionally_not_reapable():
    """**看门人型腿**（`[liveness]`）必须显式登记为「有意不回收」，且**理由非空**。

    为什么不能像其它腿那样回收：它报的是**别的**机制不再出声 ⇒ 它**自己**的绿**不是**「被报机制已恢复」
    的证据（恢复信号来自被报机制的心跳读数）⇒ 拿它的绿去自动关单 = 把活故障当陈旧报告关掉。
    红证形态：把 `[liveness]` 塞进 `PREFIX_TO_WORKFLOW` ⇒ 本条与元守卫同时判红。
    """
    entry = REAPER.NON_REAPABLE_PREFIXES.get("[liveness]")
    assert entry, "看门人型腿没登记进 NON_REAPABLE_PREFIXES"
    wf, why = entry
    assert wf == "mechanism-liveness.yml", wf
    assert len(why.strip()) >= 20, f"豁免必须写清理由（不许空白豁免）：{why!r}"
    assert "[liveness]" not in REAPER.PREFIX_TO_WORKFLOW, "看门人型腿不得进「可回收」表"


def test_runtime_names_the_exemption_reason(tmp_path):
    """运行期也要**出声**：看门人型前缀的单子，跳过行必须打出「有意不回收 + 理由」，不是笼统的「未登记」。"""
    env, log = _fixture(tmp_path, [_issue("[liveness] 有维护类机制**不再出声**（机制存活看门人）")], GREEN_RUNS)
    out = _run(tmp_path, env, "--apply")
    assert "有意不回收" in out.stdout, out.stdout
    assert not [c for c in _calls(log) if c.startswith("issue close")], "看门人型的单被自动关了"


# ── 「判过了」的第三种口径：**共享发射器**读数（2026-10-01）────────────────────────────────
#  `main-freshness-guard` 这类腿的读数不是 `跑判据 N` / `真跑 N 条`，而是全仓唯一发射器的一行
#  `::notice::MECHANISM-LIVENESS mech=… seen=<n> acted=<n> …`。不覆盖它 ⇒ 要么把这类腿挡在
#  「真跑过」闸门外（漏关），要么把它们当「结论绿就算判过」（假关）。

FRESHNESS_ISSUE = "[main-freshness] main 上的生成物与用例单一源漂移（main 侧生成物新鲜度守护腿未通过）"


def test_main_freshness_green_with_emitter_reading_closes(tmp_path):
    """正控：`[main-freshness]`（发射器读数 `seen=2`）⇒ 正常关。"""
    env, log = _fixture(tmp_path, [_issue(FRESHNESS_ISSUE)], GREEN_RUNS,
                        run_log="##[notice]MECHANISM-LIVENESS mech=main-freshness-guard "
                                "run=36830947429 rc=0 seen=2 acted=0 why=verdict=fresh\n")
    out = _run(tmp_path, env, "--apply")
    assert any(c.startswith("issue close") for c in _calls(log)), f"有发射器读数却没关：{out.stdout}"


def test_emitter_zero_seen_green_is_not_closed(tmp_path):
    """反向对照：同一行读数但 `seen=0`（**零动作**的绿）⇒ 不得当"判过了"。"""
    env, log = _fixture(tmp_path, [_issue(FRESHNESS_ISSUE)], GREEN_RUNS,
                        run_log="##[notice]MECHANISM-LIVENESS mech=main-freshness-guard "
                                "run=1 rc=0 seen=0 acted=0 why=no-artifacts\n")
    out = _run(tmp_path, env, "--apply")
    assert not [c for c in _calls(log) if c.startswith("issue close")], f"零动作的绿被当成判过了：{out.stdout}"


# ── 影子前缀（2026-10-01 同批引入的形态）──────────────────────────────────────────────────
#  `[Agent Eval]` 一个根前缀下**两条腿**（冒烟 / 对抗）⇒ 登记的是两条**更具体的子前缀**；而匹配是
#  `startswith` + **表序** ⇒ 若有人把更短的 `[Agent Eval]` 登记在**前面**，两条子前缀永远匹配不到
#  （静默失效），而更短的那条会横跨两条腿 ⇒ **拿错腿的绿去关单**（关掉还没恢复的活故障）。


def test_no_registered_prefix_shadows_another():
    """真语料：登记表里不得有「更短的在前 ⇒ 吃掉更具体的」影子关系。"""
    shadowed = REAPER.shadowed_prefixes()
    assert not shadowed, f"影子前缀（更具体的永远匹配不到，且更短的横跨多腿）：{shadowed}"


def test_shadow_guard_has_discriminating_power():
    """判别力自证（内存注入）：① 更短的登记在前 ⇒ 判红并具名；② 更长的在前 ⇒ 不报（对照读数）。"""
    shadow = {"[X]": "a.yml", "[X] 冒烟": "b.yml"}
    assert REAPER.shadowed_prefixes(shadow) == [("[X] 冒烟", "[X]")], REAPER.shadowed_prefixes(shadow)
    ordered = {"[X] 冒烟": "b.yml", "[X] 对抗": "c.yml"}
    assert REAPER.shadowed_prefixes(ordered) == [], REAPER.shadowed_prefixes(ordered)
