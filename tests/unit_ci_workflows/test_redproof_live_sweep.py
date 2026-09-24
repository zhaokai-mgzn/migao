# case_ids: MC-017, MC-018, MC-020
"""红证**实跑**巡检的判据（issue #5328，L0：零 LLM、零网络、零 Maven/npm/PG）。

## 缺陷（**类**：红证退化 = 「不红也过」，三例实测）

| 实例 | 退化形态 | 谁发现的 |
|---|---|---|
| `#5268` 判据 4 的原夹具 | 注入 `SECRETS_RE` **不再让判据变红**（夹具已失效） | 人读到 |
| `#5286` 判据 4 的原夹具 | 同形（第二把尺子红了、判据 4 却绿） | 人读到 |
| `#5272` 的既有红证 | `_strip_comments` 抽走后**夹具不再变红** ⇒ 「不红也过」（空断言） | 人复跑发现 |

**机器已有的只是「前提自检」**（锚点可命中 / 期望判据方法存在，`red_proof_harness.py --check`，
每个 PR 都跑）—— **「期望判据方法**存在**」≠「注入之后它**会红**」**。实跑此前只在手动入口
（`./verify-all.sh redproof`）⇒ **没有任何自动巡检**，退化只能靠人恰好手工跑一次。

## 本守卫锁什么（每条判据都带**注入式红证**）

1. **巡检必须真跑**（不是只 grep 文件/锚点存在）：夹具判据**真的被调用 3 次**
   （基线 / 注入 / 还原），证据 = 夹具自己追加的运行日志 ⇒ 把巡检退化成「只查存在性」
   ⇒ 本判据**必红**（`test_grep_only_sweep_produces_no_run_evidence` 用**真·退化实现**取证）。
2. **退化必须报出来**：判据在注入后仍然绿 ⇒ 巡检必须**具名**说「**该红证已退化**」
   （注入已生效，见 fingerprint 差异），而不是让人自己对比两次日志。
3. **注入点失配必须报**（不许静默跳过）；**期望失败文本与实际不符必须报**（弱前提的反面）。
4. **注入只在临时副本上做**：跑完夹具仓库的源文件必须**逐字节未变**
   （工作区里真实文件一次都不被写）。
5. **超时上限**：判据跑不完 ⇒ 掐断并报超时（不是「通过」、不是无限等）。
6. **存活读数（零动作也要出声）**：每轮输出「登记 / 真跑 / 跳过（逐条原因）/ 注入 / 还原 / 退化」
   —— 一条都没真跑时走**三态出口** `3`（无法判定），**不得**回落成通过。
7. **登记册**：每个红证机具必须在册（`entries` 或 `unfixed`，未登记 ⇒ 红）；每条登记项要有
   **逐字注入点 + 期望红形态**；未固化项必须写「原因 + 谁看」（**不许留白**）。
8. **巡检自己停摆要能被看见**：新定时 workflow 合并后自动落进 `scripts/drift_audit.py` 的
   `heartbeat` 判定面（**复用**既有机制，不另立心跳表）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
SWEEP = SCRIPTS / "redproof_sweep.py"
REGISTRY = SCRIPTS / "redproof_registry.json"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "redproof-sweep.yml"

# append（不是 insert）：只作兜底解析路径，避免遮蔽同名模块。
sys.path.append(str(SCRIPTS))

import redproof_sweep as rs  # noqa: E402

PROBE = """\
import os, pathlib, sys
with open(os.environ["SWEEP_FIXTURE_LOG"], "a", encoding="utf-8") as fh:
    fh.write("criteria-run\\n")
src = pathlib.Path("guarded/sample.py").read_text(encoding="utf-8")
if "VALUE = 2" in src:
    print("BOOM: 注入后的值被读到了")
    sys.exit(1)
print("ok")
"""
#: 退化形态（= `#5272` 的形状）：把断言换成 `pass` —— 判据**永远绿**，注入看不出任何效果。
PROBE_NEVER_RED = PROBE.replace('if "VALUE = 2" in src:', "if False:")
PROBE_SLEEP = ("import os, pathlib, time\n"
               "with open(os.environ['SWEEP_FIXTURE_LOG'], 'a', encoding='utf-8') as fh:\n"
               "    fh.write('criteria-run\\n')\n"
               "time.sleep(8)\n")

GUARDED_BEFORE = "VALUE = 1\n"
ENTRY = {
    "id": "fixture/one",
    "tool": "scripts/fake-red-proof.py",
    "mutation": "M1",
    "criterion": "夹具判据（注入后必须红）",
    "guarded": "guarded/sample.py",
    "anchor": "VALUE = 1",
    "replacement": "VALUE = 2",
    "criteria": {"cwd": ".", "cmd": [sys.executable, "criteria/probe.py"],
                 "kind": "stdout", "red_text": "BOOM"},
    "requires": [],
}


def _fixture(tmp_path: Path, entries: list[dict], probe: str = PROBE) -> Path:
    """造一个最小仓库（副本机制 = `git archive HEAD`，与真实仓库**同一条路径**）。"""
    root = tmp_path / "fixture"
    files = {"guarded/sample.py": GUARDED_BEFORE,
             "criteria/probe.py": probe,
             "scripts/fake-red-proof.py": "# 夹具机具（只为登记册判据存在）\n",
             "scripts/redproof_registry.json": json.dumps(
                 {"schema": "migao.redproof-registry/1", "entries": entries, "unfixed": []},
                 ensure_ascii=False)}
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "fixture"]):
        subprocess.run(["git", *argv], cwd=root, check=True, env=env, capture_output=True)
    return root


def _sweep(fixture: Path, log: Path, *args: str, script: Path = SWEEP) -> subprocess.CompletedProcess:
    """跑**真**巡检（或它的一个退化副本），夹具判据的运行痕迹落进 `log`。"""
    return subprocess.run(
        [sys.executable, str(script), "--repo", str(fixture),
         "--registry", str(fixture / "scripts" / "redproof_registry.json"), *args],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "SWEEP_FIXTURE_LOG": str(log)})


def _runs(log: Path) -> int:
    return len(log.read_text(encoding="utf-8").splitlines()) if log.is_file() else 0


# ══════════════════ ①③④ 真跑：夹具判据真的被执行 3 次，且只在副本里注入 ══════════════════

class TestLiveSweepReallyRuns:
    """「真跑」= 判据被真调用（基线 / 注入 / 还原），且注入落在临时副本而不是真实文件上。"""

    def test_healthy_entry_is_injected_reddened_and_restored(self, tmp_path):
        fixture = _fixture(tmp_path, [ENTRY])
        log = tmp_path / "runs.log"
        r = _sweep(fixture, log)
        assert r.returncode == rs.OK, f"健康的红证必须巡检通过：rc={r.returncode}\n{r.stdout}\n{r.stderr}"
        assert _runs(log) == 3, (
            f"判据必须被**真跑 3 次**（基线 / 注入 / 还原），实测 {_runs(log)} 次 —— "
            f"少于 3 次说明巡检退化成「只查存在性」\n{r.stdout}")
        assert "真跑 1 条 / 跳过 0 条" in r.stdout, r.stdout
        assert "注入 1 次 / 还原 1 次" in r.stdout, r.stdout
        assert "工作区被守卫文件：1/1 个 sha256 前后一致" in r.stdout, (
            f"巡检必须报出「工作区里的真实文件没被碰过」这个读数：\n{r.stdout}")
        assert (fixture / "guarded" / "sample.py").read_text(encoding="utf-8") == GUARDED_BEFORE, (
            "注入只许落在临时副本上 —— 来源仓库的文件被写脏了")

    def test_grep_only_sweep_produces_no_run_evidence(self, tmp_path):
        """**判据 3 的注入式红证**：把巡检退化成「只 grep 文件/锚点存在」⇒ 本判据必红。

        做法：把 `run_criteria()` 里的真调用换成「凭空判绿」，得到一份**只会查存在性**的退化实现；
        它对同一条红证报「通过」，而**夹具判据一次都没被调用**（运行痕迹为 0）⇒
        上面那条「真跑 3 次」的判据在这里必然红（本用例断言这个判别力**真的存在**）。
        """
        fixture = _fixture(tmp_path, [ENTRY])
        real = SWEEP.read_text(encoding="utf-8")
        # 退化形态 = **只查存在性**：不跑任何判据，直接按「文件/锚点都在」报红（其余结构一字未动）
        degraded = real.replace(
            "    base = run_criteria(copy, entry, timeout)\n",
            "    return Verdict(eid, \"red\", \"（退化实现：只查了文件与锚点存在）\", "
            "injection=\"n/a\")  # [RED-PROOF] 退化成「只 grep 存在性」\n"
            "    base = run_criteria(copy, entry, timeout)\n", 1)
        assert degraded != real, "退化注入没生效（巡检源码结构变了就同步本守卫）"
        fake_dir = tmp_path / "bin" / "scripts"      # 退化副本要能 import 到 red_proof（同目录放一份）
        fake_dir.mkdir(parents=True)
        shutil.copy(SCRIPTS / "red_proof.py", fake_dir / "red_proof.py")
        fake = fake_dir / "sweep_grep_only.py"
        fake.write_text(degraded, encoding="utf-8")
        log = tmp_path / "runs.log"
        r = _sweep(fixture, log, script=fake)
        assert _runs(log) == 0, (
            "退化实现竟然真的调用了判据 —— 本用例的前提（它只查存在性）不成立，同步本守卫")
        assert r.returncode == rs.OK, (
            f"退化实现必须**看起来是绿的**（这才是被固化的那个反面形态）：rc={r.returncode}\n{r.stdout}")
        assert "真跑 1 条 / 跳过 0 条" in r.stdout, r.stdout

    def test_never_red_criterion_is_reported_as_degenerated(self, tmp_path):
        """**判据 1/2 的注入式红证**：判据被改成「永不红」（断言 → `pass`）⇒ 巡检**必报**。"""
        fixture = _fixture(tmp_path, [ENTRY], probe=PROBE_NEVER_RED)
        log = tmp_path / "runs.log"
        r = _sweep(fixture, log)
        assert r.returncode == rs.BAD, f"退化必须判红：rc={r.returncode}\n{r.stdout}"
        assert "该红证已退化" in r.stdout, f"必须**直接点明**退化，而不是让人对比日志：\n{r.stdout}"
        assert "注入已生效" in r.stdout and "fingerprint" in r.stdout, r.stdout
        assert "判据没有红" in r.stdout or "没有失败" in r.stdout, r.stdout
        assert _runs(log) == 3, (
            f"退化时判据仍应真跑（基线 + 注入 + 还原后对照）：{_runs(log)}")

    def test_anchor_pointing_nowhere_is_reported(self, tmp_path):
        """**判据 1 的另一半**：把注入点指向不存在的锚 ⇒ **必报**（不许静默跳过）。

        两种载体都锁：① 锚在**随登记册提交的源码**里就不存在（登记册结构判据当场拦下）；
        ② 锚只在**未提交的脏改动**里存在（工作区有、HEAD 没有）⇒ 副本（HEAD 的树）里命中 0 次，
        运行期判据拦下 —— 顺带钉住「巡检对象 = HEAD 的树」这条语义。
        """
        fixture = _fixture(tmp_path, [dict(ENTRY, anchor="VALUE = 42", id="fixture/bad_anchor")])
        log = tmp_path / "runs.log"
        r = _sweep(fixture, log)
        assert r.returncode == rs.BAD, f"注入点失配必须判红：rc={r.returncode}\n{r.stdout}"
        assert "命中" in r.stdout + r.stderr and "1 次" in r.stdout + r.stderr, (
            r.stdout + r.stderr)
        assert _runs(log) == 0, "锚点都不命中时不该跑判据（更不该报成功）"

    def test_anchor_present_only_in_dirty_worktree_is_reported_at_runtime(self, tmp_path):
        entry = dict(ENTRY, id="fixture/dirty_only", anchor="EXTRA = 0\n")
        fixture = _fixture(tmp_path, [entry])
        # 只写进**工作区**、不提交 ⇒ 副本（HEAD 的树）里没有它
        (fixture / "guarded" / "sample.py").write_text(GUARDED_BEFORE + "EXTRA = 0\n",
                                                       encoding="utf-8")
        log = tmp_path / "runs.log"
        r = _sweep(fixture, log)
        assert r.returncode == rs.BAD, f"运行期锚点失配必须判红：rc={r.returncode}\n{r.stdout}"
        assert "注入点失配" in r.stdout and "命中 0 次" in r.stdout, r.stdout
        assert _runs(log) == 0, "锚点不命中时不该跑判据"

    def test_expectation_mismatch_is_reported(self, tmp_path):
        """登记册的「期望失败文本」与实际不符 ⇒ **必红**（弱前提「期望存在」的反面）。"""
        entry = json.loads(json.dumps(ENTRY))
        entry["criteria"]["red_text"] = "NEVER_MATCHES_THIS"
        fixture = _fixture(tmp_path, [entry])
        r = _sweep(fixture, tmp_path / "runs.log")
        assert r.returncode == rs.BAD, f"红形态不符必须判红：rc={r.returncode}\n{r.stdout}"
        assert "NEVER_MATCHES_THIS" in r.stdout and "期望不符" in r.stdout, r.stdout

    def test_timeout_is_capped(self, tmp_path):
        """判据跑不完 ⇒ 按超时上限掐断并报**超时**（不是通过、不是无限等、也不是「红证坏了」）。"""
        fixture = _fixture(tmp_path, [ENTRY], probe=PROBE_SLEEP)
        r = _sweep(fixture, tmp_path / "runs.log", "--timeout", "2")
        assert r.returncode == rs.UNKNOWN, (
            f"掐断 = **无法判定**（看不了 ≠ 没问题）：rc={r.returncode}\n{r.stdout}\n{r.stderr}")
        assert "超时" in r.stdout, r.stdout


# ══════════════════ ⑥ 存活读数：零动作也要出声 ══════════════════

class TestLivenessReadout:
    """「一条都没跑」与「跑过且通过」必须长得不一样（§19.1 / `migao-acceptance`）。"""

    def test_all_skipped_is_undecidable_not_pass(self, tmp_path):
        entry = dict(ENTRY, id="fixture/needs_a_toolchain", requires=["cmd:no-such-command-5328"])
        fixture = _fixture(tmp_path, [entry])
        r = _sweep(fixture, tmp_path / "runs.log")
        assert r.returncode == rs.UNKNOWN, (
            f"一条都没真跑 ⇒ **无法判定**（3），不是通过：rc={r.returncode}\n{r.stdout}\n{r.stderr}")
        assert "零动作" in r.stderr, r.stderr
        assert "跳过 1 条" in r.stdout and "缺命令 no-such-command-5328" in r.stdout, (
            f"跳过必须**具名原因**：\n{r.stdout}")
        assert "登记 1 条 / 真跑 0 条" in r.stdout, r.stdout

    def test_skipped_entry_says_skip_is_not_pass(self, tmp_path):
        entry = dict(ENTRY, id="fixture/needs_a_toolchain", requires=["dir:no/such/dir-5328"])
        fixture = _fixture(tmp_path, [entry])
        r = _sweep(fixture, tmp_path / "runs.log")
        assert "跳过 ≠ 通过" in r.stdout, r.stdout


# ══════════════════ ⑦ 登记册：未登记即红 + 逐字注入点 + 未固化不许留白 ══════════════════

class TestRegistry:
    """登记册是「哪条判据有红证」的单一事实源（issue #5328 判据 2/3/6）。"""

    def test_real_registry_is_clean(self):
        data = rs.load_registry(REGISTRY)
        problems = rs.registry_problems(data, rs._default_tools())
        assert problems == [], "登记册有结构问题：" + repr(problems)

    def test_every_red_proof_tool_is_registered(self):
        """「号称有红证」而未登记的机具不许存在 —— 现取机具清单（不写死条数）。"""
        tools = rs._default_tools()
        assert tools, "scripts/ 下找不到任何红证机具（目录变了就同步本守卫）"
        assert WORKFLOW.is_file(), f"找不到实跑巡检的定时 workflow：{WORKFLOW}"
        registered = {e["tool"] for e in rs.load_registry(REGISTRY)["entries"]
                      if rs.is_red_proof_tool(e["tool"])}
        assert registered <= set(tools), f"登记册里有不存在的机具：{sorted(registered - set(tools))}"
        assert set(tools) - registered <= {
            u["tool"] for u in rs.load_registry(REGISTRY).get("unfixed", [])
            if rs.is_red_proof_tool(u.get("tool", ""))}, (
            f"有机具既未登记实跑、也未登记未固化原因：{sorted(set(tools) - registered)}")

    def test_unregistered_tool_is_caught(self):
        """**判据 2 的注入式红证**：新增一处未登记的红证机具 ⇒ 判据必红。"""
        data = rs.load_registry(REGISTRY)
        problems = rs.registry_problems(data, rs._default_tools() + ["scripts/brand-new-red-proof.py"])
        assert problems, "新增未登记的机具必须判红 ⇒ 否则「号称有红证」可以溜进来"
        assert any("brand-new-red-proof.py" in p and "未登记" in p for p in problems), repr(problems)

    def test_unfixed_entry_without_reason_or_owner_is_caught(self):
        """未固化项必须写「原因 + 谁看」；**留白即红**（issue #5328 判据 6）。"""
        data = {"entries": [], "unfixed": [{"tool": "scripts/zz-red-proof.py"}]}
        problems = rs.registry_problems(data, ["scripts/zz-red-proof.py"])
        assert any("缺 `reason`" in p for p in problems), repr(problems)
        assert any("缺 `owner`" in p for p in problems), repr(problems)
        ok = {"entries": [], "unfixed": [
            {"tool": "scripts/zz-red-proof.py", "reason": "需真栈", "owner": "红证机具 owner"}]}
        assert rs.registry_problems(ok, ["scripts/zz-red-proof.py"]) == []

    def test_entry_without_red_text_or_verbatim_anchor_is_caught(self):
        """「期望存在」是弱前提：登记项必须给出**逐字注入点 + 期望失败文本**。"""
        data = rs.load_registry(REGISTRY)
        broken = json.loads(json.dumps(data))
        broken["entries"][0]["criteria"].pop("red_text")
        broken["entries"][1]["anchor"] = "这个锚在源码里根本不存在"
        problems = rs.registry_problems(broken, rs._default_tools())
        assert any("red_text" in p for p in problems), repr(problems)
        assert any("恰好 1 次" in p for p in problems), repr(problems)

    @pytest.mark.parametrize("path, tool", [(REGISTRY, "scripts/redproof_sweep.py")])
    def test_registry_entries_match_the_shipped_sources(self, path, tool):
        """每条登记的注入锚必须在**随该登记册一起提交的源码**里命中恰好 1 次（漂移即红）。"""
        data = rs.load_registry(path)
        for e in data["entries"]:
            src = (REPO_ROOT / e["guarded"]).read_text(encoding="utf-8")
            assert src.count(e["anchor"]) == 1, (
                f"[{e['id']}] 注入锚在 {e['guarded']} 里命中 {src.count(e['anchor'])} 次 —— "
                f"源码已漂移，按巡检报告重取锚点后再登记")


# ══════════════════ ⑧ 巡检自己停摆要能被看见（复用既有 heartbeat 判定面）══════════════════

class TestSweepItselfCannotDieSilently:
    """「治静默失效的机制自己静默失效」是同一个病 —— 新定时腿合并后自动纳入心跳判定。"""

    def test_new_scheduled_workflow_falls_into_the_heartbeat_judgment(self):
        sys.path.append(str(SCRIPTS))
        import drift_audit  # noqa: E402  # 复用既有心跳判定，不另立一套

        audit = drift_audit.Audit(REPO_ROOT, base="HEAD", offline=True)
        result = drift_audit.check_heartbeat(audit)
        scanned = [n for n in result.notes if WORKFLOW.name in n]
        assert scanned, (
            f"{WORKFLOW.name} 不在 `check_heartbeat` 的判定面里（notes={result.notes}）—— "
            f"巡检自己停摆就不会有人看见")
        # 心跳阈值由**声明的 cron 周期**推出 ⇒ 判据面里不能出现「计划被注释掉」或「没有 cron」
        assert not any(WORKFLOW.name in f.key for f in result.findings), (
            f"{WORKFLOW.name} 被判成停摆：{[f.detail for f in result.findings]}")
        head = WORKFLOW.read_text(encoding="utf-8").split("\njobs:")[0]
        assert drift_audit.SCHED_LINE.findall(head), "定时腿必须声明 `schedule:` + `cron:`"

    def test_sweep_is_wired_into_the_documented_entry_point(self):
        """巡检必须能从既有入口跑到（`verify-all.sh redproof`），而不是只能手工敲全路径。"""
        text = (REPO_ROOT / "verify-all.sh").read_text(encoding="utf-8")
        assert "redproof_sweep.py" in text, (
            "verify-all.sh 的 redproof 档没有接线到 `scripts/redproof_sweep.py`")
        logging.getLogger(__name__).info("入口 = ./verify-all.sh redproof")

def test_red_form_matching_strips_ansi_escapes():
    """红形态匹配**必须先剥 ANSI**（巡检首发日 2026-09-24 实测的误报根因）。

    `npx vitest` 的输出**带颜色码**：转义序列把 `Tests\s+\d+ failed \(\d+\)` 这类**精确**
    期望形态打散 ⇒ 判据**其实红了**却被判成 `red_form_mismatch`（误报"红证不成立"）。
    归因方向必须准（§23 G3）：病根在**读法**（颜色码），不在判据。

    **行为级判据**（走 `red_evidence` 的真实匹配路径，不是只测 helper）：
    把引擎里任一处 `strip_ansi(...)` 去掉 ⇒ 本判据**必红**。
    """
    raw = "\x1b[31mTests\x1b[39m \x1b[31m1 failed\x1b[39m (1)\n"
    entry = {"id": "ansi-probe", "criteria": {"kind": "stdout", "red_text": r"Tests\s+\d+ failed \(\d+\)"}}
    run = SimpleNamespace(rc=1, out=raw, timed_out=False)
    state, detail = rs.red_evidence(entry, Path("."), run)
    assert state == "red", (
        "未剥 ANSI ⇒ 精确期望形态被打散、误报 red_form_mismatch"
        f"（实测 state={state}：{detail}）")
