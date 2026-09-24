# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 test_guard_parsing_is_comment_aware.py / test_mechanism_jobs_alerting.py /
#   test_agent_permission_parity.py 的同款声明与 `.github/cases/misc.yml` MC-012 的登记。
#   本 PR 不新建用例族。）
r"""「机制静默失效」这一**类别**的判据（issue #5326）。

## 病根（一类缺陷，不是一个缺陷）

一个自动化机制**停摆或瞎了**，但**没有任何读数会因此改变** ⇒ 只能靠人偶然发现。
今晚两例各藏 **约 40 小时**：

| 实例 | 为什么没人发现 |
|---|---|
| `#5264`：台账 `approve` 因分页缺陷**一次都没发出去** | 机制「跑了」且每次都**成功退出**，打印的 ✅ 读数**与事实相反** |
| `#5307`：台账分支 required 测试**恒红** | 不在 required 集合 + `flaky-triage` 自指守卫跳过它 + reconcile 只补 approve/arm、不读失败原因 |

**已有一半（本单不重做）**：`scripts/drift_audit.py::check_heartbeat()` 判的是「`schedule:` 存在
且没被注释停用」= **调度存在**；它答不了「**最近一次真的干成过事**没有」。

## 本文件锁的五条（各带**注入式**红证 —— 变异点 + 逐字期望）

| 判据 | 判据本体 | 红证（变异点 ⇒ 必红） |
|---|---|---|
| 1 执行成果的存活读数 | 每个 `instrumented` 机制的 workflow 必须有**独立、`if: always()`、最后一步**的读数步 | ① 删掉某机制的读数步；② 把发射器的**零动作**分支改成静默 |
| 2 看门人（最近一次成功处置新鲜） | `judge_watchdog()`：main 上最近一次**已完成** run 的注解里必须有**绑定该 run id** 的读数 | 删掉读数 / 把读数改成旧 run id / 让读数与 run 结论矛盾 |
| 3 机制清单是显式登记 | 结构性发现面（无人值守 × 写作用域）⊆ 登记面 ∪ 豁免面 | 加一个「scheduled + `issues: write`」的 workflow 且不登记 |
| 4 零动作与未运行可区分 | 零动作 ⇒ 有读数且 `acted=0` + `why`；未运行 ⇒ **没有这一行** | 同判据 1 的 ② |
| 5 未固化逐条登记 | `reading: unfixed` ⇒ `unfixed` 非空且每条带 `what/reason/issue/consumer` | 把 `unfixed` 清空 |

## 为什么判据是**语义**的、不是一行字面量

- 判据 3 的发现面读**真 YAML 结构**（`on:` 里的无人值守触发面 × `permissions:` 里的**写**作用域），
  不是文件名清单 —— **实测它零特例地重现 issue #5326 正文列出的 8 条机制**；
- 判据 1 按**实际 argv** 定位读数步（`emit <id>` 出现在 `run:` 里），不按步骤名文案；
- 负控（`test_comment_mention_does_not_satisfy_the_rule`）：注释里写 `issues: write` **不算** ——
  本仓 `#5323` 清扫过的正是「把原文文本当代码读」。

## 测试方式

- **真跑**发射器（`subprocess` + `bash`，注入 `GITHUB_RUN_ID` / 处置文件），判据来自它的 stdout；
- **真跑**判定本体（`judge_watchdog` 是纯函数，夹具即观测）；
- **注入式红证**一律做**单点变异**后重跑（变异点在**源码文本**上，避开「判据被自己的文案喂绿」）。

复算：`python3 -m pytest tests/unit_ci_workflows/test_mechanism_liveness.py -q -s`
"""
from __future__ import annotations

import importlib.util
import json
import re
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EMITTER = REPO_ROOT / ".github" / "scripts" / "mechanism_liveness.sh"
CHECKER = REPO_ROOT / "scripts" / "mechanism_liveness.py"
REGISTRY = REPO_ROOT / "scripts" / "mechanism-registry.json"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _load_checker():
    """按**路径**加载判定本体（不往 `sys.path` 里塞常驻条目，同 drift_audit 的加载口径）。"""
    spec = importlib.util.spec_from_file_location("mechanism_liveness", CHECKER)
    assert spec is not None and spec.loader is not None, f"判定本体加载失败：{CHECKER}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mechanism_liveness"] = mod
    spec.loader.exec_module(mod)
    return mod


ML = _load_checker()


# ══════════════════════════════════════════════════════════════════════════
# 夹具：临时仓库（真文件的副本 + 单点变异）
# ══════════════════════════════════════════════════════════════════════════
def _mini_repo(tmp_path: Path) -> Path:
    """真仓库的**最小副本**（workflows + 发射器 + 登记数据 + 判定本体）—— 供注入式变异用。"""
    repo = tmp_path / "repo"
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "scripts").mkdir(parents=True)
    (repo / "scripts").mkdir(parents=True)
    for src in sorted(WORKFLOWS.glob("*.yml")):
        shutil.copy2(src, repo / ".github" / "workflows" / src.name)
    shutil.copy2(EMITTER, repo / ".github" / "scripts" / EMITTER.name)
    shutil.copy2(CHECKER, repo / "scripts" / CHECKER.name)
    shutil.copy2(REGISTRY, repo / "scripts" / REGISTRY.name)
    return repo


def _registry_data() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _run_emitter(script: Path, args: list[str], tmp_path: Path, **env_extra: str):
    """真跑发射器：返回 (退出码, 读数行列表, 完整 stdout)。"""
    disposition = tmp_path / "disposition"
    env = {
        **os.environ,
        "GITHUB_RUN_ID": "1234567890",
        "MECHANISM_LIVENESS_DISPOSITION": str(disposition),
        **env_extra,
    }
    proc = subprocess.run(
        ["bash", str(script), *args], capture_output=True, text=True, env=env, timeout=60,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ML.MECHANISM_MARKER in ln]
    return proc.returncode, lines, proc.stdout


def _mutate_emitter(tmp_path: Path, old: str, new: str, label: str) -> Path:
    """对发射器做**单点变异**，并**自证注入生效**（G7 / G10）。

    三层自证，缺一层这个红证就不成立：
      ① 变异锚点在源码里**唯一**（否则改了别处也说得通）；
      ② `old != new` 且落盘文本**确实与原文件不同**（注入真的写进去了）；
      ③ 调用方断言**行为变了**（读数消失 / 解析失败）—— 只判"锚点可命中"是**弱前提**。
    """
    text = EMITTER.read_text(encoding="utf-8")
    assert old != new, f"[{label}] 变异前后文本相同 ⇒ 什么也没注入"
    assert text.count(old) == 1, f"[{label}] 变异锚点必须唯一，实测 {text.count(old)} 处：{old!r}"
    target = tmp_path / f"mutant-{label}.sh"
    target.write_text(text.replace(old, new), encoding="utf-8")
    assert target.read_text(encoding="utf-8") != text, f"[{label}] 注入未落盘 ⇒ 红证不成立"
    return target


def _checker_exit(repo: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--repo", str(repo), *args],
        capture_output=True, text=True, timeout=180, cwd=str(REPO_ROOT),
    )
    return proc.returncode, proc.stdout + proc.stderr


# ══════════════════════════════════════════════════════════════════════════
# 判据 1：执行成果的存活读数（零动作也必须出声）
# ══════════════════════════════════════════════════════════════════════════
def test_emitter_speaks_on_zero_action(tmp_path):
    """**零动作也出声**：`acted=0` + `why` 写明原因 —— 这是「我没做事」。"""
    (tmp_path / "disposition").write_text("seen=7\nacted=0\nwhy=本轮无待处理 PR\n", encoding="utf-8")
    rc, lines, _ = _run_emitter(EMITTER, ["emit", "demo", "--outcome", "success"], tmp_path)
    assert rc == 0, "发射行为不得改变机制结论（rc 必须仍是 0）"
    assert len(lines) == 1, f"每轮只许**恰好一行**读数（解析器依赖它），实测 {lines}"
    parsed = ML.parse_readings(lines, "demo")
    assert len(parsed) == 1, f"判定本体解析不出自己发射的读数（语法不同源）：{lines}"
    got = parsed[0]
    assert got["acted"] == "0", f"零动作必须以 `acted=0` 表达，实测 {got}"
    assert got["seen"] == "7", f"`seen` 必须转达机制体声明的计数，实测 {got}"
    assert got["why"].strip(), f"零动作必须写明**为什么零动作**，实测 {got}"
    assert got["rc"] == "0" and lines[0].startswith("::notice::"), f"成功轮的读数级别必须是 notice：{lines}"


def test_emitter_speaks_even_when_mechanism_declared_nothing(tmp_path):
    """机制体**忘了声明**也必须出声 —— 它是「跑了但没说自己做了什么」，**不是**「没跑」。"""
    rc, lines, _ = _run_emitter(EMITTER, ["emit", "demo", "--outcome", "success"], tmp_path)
    assert rc == 0
    assert len(lines) == 1, f"没声明 ≠ 不出声（这两者一混淆，本单的判据 4 就失效）：{lines}"
    got = ML.parse_readings(lines, "demo")[0]
    assert got["seen"] == "unknown" and got["acted"] == "unknown", f"取不到就写 unknown，**不得编造**：{got}"
    assert got["why"] == "no-declaration", f"未声明必须自曝形态，实测 {got}"


def test_emitter_reports_failure_as_warning_not_notice(tmp_path):
    """失败轮**不许报成 notice** —— 「读数与事实相反」正是 `#5264` 的形态。"""
    rc, lines, _ = _run_emitter(EMITTER, ["emit", "demo", "--outcome", "failure"], tmp_path)
    assert len(lines) == 1
    assert lines[0].startswith("::warning::"), f"失败轮必须是 warning 级别：{lines}"
    assert ML.parse_readings(lines, "demo")[0]["rc"] == "1", f"rc 必须与 --outcome failure 一致：{lines}"
    # 发射器**自己的**退出码有意恒 0（它是**报告者**：发射行为绝不改变机制结论 ——
    # 否则读数步自己会把一个成功的机制判红，那是新的假红源）。
    assert rc == 0, f"发射器不得用自己的退出码改写机制结论，实测 rc={rc}"


def test_declare_from_mechanism_body_is_carried_through(tmp_path):
    """机制体用 `source` + `mechanism_liveness_declare` 交出计数（**一行**，纯追加）。"""
    script = (
        f'source "{EMITTER}"\n' 
        'mechanism_liveness_declare --seen 12 --acted 3 --why "关闭 3 个 issue"\n'
        "mechanism_liveness_emit demo --outcome success\n"
    )
    body = tmp_path / "body.sh"
    body.write_text(script, encoding="utf-8")
    disposition = tmp_path / "disposition"
    proc = subprocess.run(
        ["bash", str(body)], capture_output=True, text=True, timeout=60,
        env={**os.environ, "GITHUB_RUN_ID": "1234567890",
             "MECHANISM_LIVENESS_DISPOSITION": str(disposition)},
    )
    lines = [ln for ln in proc.stdout.splitlines() if ML.MECHANISM_MARKER in ln]
    assert len(lines) == 1, f"实测 {proc.stdout!r}"
    got = ML.parse_readings(lines, "demo")[0]
    assert (got["seen"], got["acted"]) == ("12", "3"), f"计数没有被转达：{got}"


def test_red_proof_silencing_the_zero_action_path_turns_it_red(tmp_path):
    """**注入式红证（判据 1 / 4 的核心）**：把发射器的**零动作分支**改成静默 ⇒ 读数消失。

    变异点 = 在级别判定前插一行 `acted=0 ⇒ return 0`（零动作不再出声）。
    期望（逐字）：未变异 ⇒ 恰好 1 行读数；变异后 ⇒ **0 行**（= 与「没跑」不可区分）。
    """
    (tmp_path / "disposition").write_text("seen=7\nacted=0\nwhy=本轮无待处理\n", encoding="utf-8")
    _rc, baseline, _ = _run_emitter(EMITTER, ["emit", "demo", "--outcome", "success"], tmp_path)
    assert len(baseline) == 1, f"基线必须出声，否则本红证无判别力：{baseline}"

    anchor = '  if [ "$rc" = "0" ]; then level="notice"; else level="warning"; fi'
    mutant = _mutate_emitter(
        tmp_path, anchor,
        '  if [ "$acted" = "0" ]; then return 0; fi\n' + anchor,
        "silent-zero",
    )
    _rc, after, stdout = _run_emitter(mutant, ["emit", "demo", "--outcome", "success"], tmp_path)
    assert after == [], f"变异后零动作仍出声 ⇒ 本判据没有判别力（红证不成红证）。实测 stdout={stdout!r}"


def test_red_proof_grammar_drift_breaks_the_checker(tmp_path):
    """**注入式红证（同源判据）**：把读数语法改一处 ⇒ 判定本体**解析不出来**。"""
    lines = [
        "::notice::MECHANISM-LIVENESS mech=demo run=1234567890 rc=0 seen=7 acted=0 why=x",
    ]
    assert ML.parse_readings(lines, "demo"), "基线必须解析得出（否则红证无判别力）"
    mutant = _mutate_emitter(tmp_path, "mech=${id} run=", "mechanism=${id} run=", "grammar-drift")
    _rc, after, _ = _run_emitter(mutant, ["emit", "demo", "--outcome", "success"], tmp_path)
    assert len(after) == 1, f"变异体仍应出一行（只是字段名变了）：{after}"
    assert ML.parse_readings(after, "demo") == [], (
        "语法漂移后判定本体仍能解析 ⇒ 发射器与看门人**不同源**（写进判据的读数与看门人读的不是一回事）"
    )


# ══════════════════════════════════════════════════════════════════════════
# 判据 1（结构面）：每个登记在册的机制都必须有读数落点
# ══════════════════════════════════════════════════════════════════════════
def test_every_instrumented_mechanism_has_a_reading_step():
    """每个 `reading: instrumented` 的机制都必须有**独立、`if: always()`、最后一步**的读数步。"""
    registry = _registry_data()
    report = ML.check_readings(REPO_ROOT, registry)
    problems = "\n".join(f"  [{f.kind}] {f.key}: {f.detail}" for f in report.findings)
    instrumented = [e["id"] for e in registry["mechanisms"] if e.get("reading") == "instrumented"]
    print(f"[燃尽锚点] 登记机制={len(registry['mechanisms'])} / instrumented={len(instrumented)} "
          f"/ 未固化={len(registry['mechanisms']) - len(instrumented)}")
    assert not report.findings, f"读数落点判据判红：\n{problems}"
    assert instrumented, "instrumented 机制数为 0 ⇒ 判据面为空（护栏失效）"


def test_reading_step_is_its_own_step():
    """读数步必须是**独立的一步**（`emit <id>` 只出现一次）—— 注解有 per-step 上限，挤在一起会被丢。"""
    registry = _registry_data()
    for entry in registry["mechanisms"]:
        if entry.get("reading") != "instrumented":
            continue
        steps = ML._job_steps(REPO_ROOT, entry["workflow"], entry["job"])
        site = entry.get("reading_site", "emitter")
        needle = f"emit {entry['id']}" if site == "emitter" else f"mech={entry['id']}"
        emitting = [
            s for s in steps
            if isinstance(s.get("run"), str) and needle in s["run"]
            # 内联落点的 `run` 里还必须有**读数标记**（否则 `mech=<id>` 可能是别处的字符串）
            and (site == "emitter" or ML.MECHANISM_MARKER in s["run"])
        ]
        assert len(emitting) == 1, f"{entry['id']}（site={site}）：读数步必须**恰好一步**，实测 {len(emitting)}"
        assert emitting[0] is steps[-1], (
            f"{entry['id']}：读数步必须是 job 的**最后一步**（否则读数不是本轮的最终结论）"
        )


def _delete_reading_step(repo: Path, workflow_name: str) -> None:
    victim = repo / ".github" / "workflows" / workflow_name
    text = victim.read_text(encoding="utf-8")
    marker = "      - name: 存活读数（本轮做了什么 / 为什么零动作）"
    assert text.count(marker) == 1, f"夹具前置不成立：{workflow_name} 里没有唯一的读数步"
    victim.write_text(text[: text.index(marker)].rstrip("\n") + "\n", encoding="utf-8")


def test_red_proof_deleting_a_reading_step_is_detected(tmp_path):
    """**注入式红证（判据 1）**：删掉某机制的读数步 ⇒ 判定本体**必红**。

    两种形态都要红（都表示「该机制不再出声」）：
      · workflow 里**没有** declare ⇒ `reading-missing:<id>`（整个发射器引用都没了）；
      · workflow 里**还有** declare（机制体的计数声明）却删掉了读数步 ⇒ `reading-noemitterstep:<id>`
        —— **文案里有、argv 里没有**，正是本仓 §17.3 ③ 反复踩的「判据被自己的文案喂绿」形态。
    """
    repo = _mini_repo(tmp_path)
    _delete_reading_step(repo, "stale.yml")
    keys = {f.key for f in ML.check_readings(repo, ML.load_registry(repo)).findings}
    assert "reading-missing:stale" in keys, f"实测 findings={sorted(keys)}"
    assert not [k for k in keys if k.endswith(":automerge")], (
        "单点变异不该牵连别的机制（判据必须按机制定位）"
    )

    repo2 = _mini_repo(tmp_path / "second")
    _delete_reading_step(repo2, "deploy-reconcile.yml")   # 该 run 块里仍有 `source … ; declare`
    keys2 = {f.key for f in ML.check_readings(repo2, ML.load_registry(repo2)).findings}
    assert "reading-noemitterstep:deploy-reconcile" in keys2, (
        f"只剩文案、没有 `emit <id>` 的 argv ⇒ 必须按「没有读数步」判红。实测 findings={sorted(keys2)}"
    )


def test_red_proof_weakening_always_condition_is_detected(tmp_path):
    """**注入式红证**：把读数步的 `if: always()` 改成 `if: success()` ⇒ **失败轮不再出声** ⇒ 必红。"""
    repo = _mini_repo(tmp_path)
    victim = repo / ".github" / "workflows" / "drift-audit.yml"
    text = victim.read_text(encoding="utf-8")
    anchor = "      - name: 存活读数（本轮做了什么 / 为什么零动作）\n        if: always()\n"
    assert text.count(anchor) == 1, "夹具前置不成立"
    victim.write_text(text.replace(anchor, anchor.replace("always()", "success()")), encoding="utf-8")

    keys = {f.key for f in ML.check_readings(repo, ML.load_registry(repo)).findings}
    assert "reading-notalways:drift-audit" in keys, f"实测 findings={sorted(keys)}"


def test_red_proof_reading_step_moved_off_the_end_is_detected(tmp_path):
    """**注入式红证**：读数步后面再插一步 ⇒ 读数不再是本轮的**最终结论** ⇒ 必红。"""
    repo = _mini_repo(tmp_path)
    victim = repo / ".github" / "workflows" / "stale.yml"
    text = victim.read_text(encoding="utf-8")
    assert "      - name: 存活读数（本轮做了什么 / 为什么零动作）\n" in text, "夹具前置不成立"
    assert text.rstrip("\n").endswith("fi"), "夹具前置不成立：读数步本该是 job 的最后一步"
    victim.write_text(
        text.rstrip("\n") + "\n\n      - name: 事后又做了一步（读数不再是最终结论）\n"
                            "        if: success()\n        run: echo late\n",
        encoding="utf-8",
    )
    keys = {f.key for f in ML.check_readings(repo, ML.load_registry(repo)).findings}
    assert "reading-notlast:stale" in keys, f"实测 findings={sorted(keys)}"


# ══════════════════════════════════════════════════════════════════════════
# 判据 2：看门人（最近一次成功处置必须新鲜）—— 纯函数，夹具即观测
# ══════════════════════════════════════════════════════════════════════════
RUN_ID = "987654321"


def _obs(**over) -> dict:
    base = {
        "completed_runs": 3,
        "run_id": RUN_ID,
        "conclusion": "success",
        "head_sha": "a" * 40,
        "emitter_at_head_sha": True,
        "annotations": [
            f"::notice::MECHANISM-LIVENESS mech=demo run={RUN_ID} rc=0 seen=7 acted=0 why=本轮零动作",
        ],
    }
    base.update(over)
    return base


def _single(reg_entry: dict) -> dict:
    return {"mechanisms": [reg_entry], "exempt": []}


def _demo_entry(**over) -> dict:
    entry = {
        "id": "demo", "name": "演示机制", "workflow": ".github/workflows/stale.yml", "job": "stale",
        "expected_observable": "x", "criterion": "y", "consumer": "z",
        "reading": "instrumented", "unfixed": [],
    }
    entry.update(over)
    return entry


def test_watchdog_green_on_fresh_reading():
    """基线：读数绑定**这一次** run ⇒ 绿（否则后面几条红证都没有判别力）。"""
    rep = ML.judge_watchdog(_single(_demo_entry()), {"demo": _obs()})
    assert not rep.findings, f"基线不该判红：{[f.key for f in rep.findings]}"
    assert rep.evaluated["judged_mechanisms"] == 1, f"判定面为空 ⇒ 护栏失效：{rep.evaluated}"


def test_red_proof_deleted_reading_makes_watchdog_red():
    """**注入式红证（判据 2）**：把某机制的存活读数**删掉** ⇒ 看门人**必红**。"""
    rep = ML.judge_watchdog(_single(_demo_entry()), {"demo": _obs(annotations=[])})
    assert [f.key for f in rep.findings] == ["watchdog-no-reading:demo"], (
        f"删掉读数必须判红且只判一条，实测 {[f.key for f in rep.findings]}"
    )


def test_red_proof_stale_reading_makes_watchdog_red():
    """**注入式红证（判据 2）**：把读数**改旧**（绑定到上一次 run）⇒ 看门人**必红**。"""
    rep = ML.judge_watchdog(_single(_demo_entry()), {"demo": _obs(annotations=[
        f"::notice::MECHANISM-LIVENESS mech=demo run={int(RUN_ID) - 1} rc=0 seen=7 acted=0 why=上一轮的读数",
    ])})
    assert [f.key for f in rep.findings] == ["watchdog-stale-reading:demo"], (
        f"旧读数必须判红，实测 {[f.key for f in rep.findings]}"
    )


def test_red_proof_contradicting_reading_makes_watchdog_red():
    """**注入式红证（`#5264` 的形态）**：run 结论 = success 而读数 `rc=1` ⇒ **读数与事实相反** ⇒ 必红。"""
    rep = ML.judge_watchdog(_single(_demo_entry()), {"demo": _obs(
        conclusion="success",
        annotations=[f"::warning::MECHANISM-LIVENESS mech=demo run={RUN_ID} rc=1 seen=? acted=? why=炸了"],
    )})
    assert [f.key for f in rep.findings] == ["watchdog-contradiction:demo"], (
        f"读数与 run 结论矛盾必须判红，实测 {[f.key for f in rep.findings]}"
    )


def test_red_proof_reverse_contradiction_makes_watchdog_red():
    """反向矛盾（run 失败而读数报 `rc=0`）同样判红 —— 只判一个方向就会漏掉另一半。"""
    rep = ML.judge_watchdog(_single(_demo_entry()), {"demo": _obs(
        conclusion="failure",
        annotations=[f"::notice::MECHANISM-LIVENESS mech=demo run={RUN_ID} rc=0 seen=? acted=? why=看起来很好"],
    )})
    assert [f.key for f in rep.findings] == ["watchdog-contradiction:demo"], (
        f"实测 {[f.key for f in rep.findings]}"
    )


def test_first_run_and_pending_instrumentation_are_notes_not_findings():
    """**监控自己不得自造假红**：首发日 / 读数落点尚未上线 ⇒ **备注**，不是 finding。"""
    first = ML.judge_watchdog(_single(_demo_entry()), {"demo": {"completed_runs": 0}})
    assert not first.findings and any("pending-first-run" in n for n in first.notes), (
        f"首发日必须记备注而不是判红：findings={[f.key for f in first.findings]} notes={first.notes}"
    )
    pending = ML.judge_watchdog(_single(_demo_entry()), {"demo": _obs(emitter_at_head_sha=False, annotations=[])})
    assert not pending.findings and any("pending-instrumentation" in n for n in pending.notes), (
        f"读数落点上线前的 run 必须记备注：findings={[f.key for f in pending.findings]} notes={pending.notes}"
    )


def test_watchdog_verdict_ignores_wall_clock():
    """**判据 4 的负控**：同一观测、只把挂钟时间改到 10 年前/后 ⇒ 判定**逐字相同**（禁挂钟时长）。

    （本仓实测：时长受 runner 负载污染；且 GitHub 对分钟级 cron 节流到 2~5.5h ⇒ 时间窗判定不确定。）
    """
    fresh = ML.judge_watchdog(_single(_demo_entry()), {"demo": _obs(created_at="2026-09-24T00:00:00Z")})
    ancient = ML.judge_watchdog(_single(_demo_entry()), {"demo": _obs(created_at="2016-01-01T00:00:00Z")})
    assert [f.key for f in fresh.findings] == [f.key for f in ancient.findings] == [], (
        "挂钟时间改变了判定 ⇒ 判据里混进了时长依赖（判据 4 禁止）"
    )
    stale = ML.judge_watchdog(_single(_demo_entry()), {"demo": _obs(
        created_at="2026-09-24T00:00:00Z",
        annotations=[f"::notice::MECHANISM-LIVENESS mech=demo run=1 rc=0 seen=1 acted=0 why=旧"],
    )})
    assert [f.key for f in stale.findings] == ["watchdog-stale-reading:demo"], "新鲜度必须由 run 归属判，不是时长"


def test_watchdog_marks_missing_observation_as_unknown_not_green():
    """观测取不到 ⇒ **未知**（备注），**不得**当成通过。"""
    rep = ML.judge_watchdog(_single(_demo_entry()), {})
    assert not rep.findings, "取不到观测本身不该判红（那是 unknown 通道）"
    assert any("未知" in n for n in rep.notes), f"取不到观测必须显式记未知：{rep.notes}"
    assert rep.evaluated.get("judged_mechanisms", 0) == 0, "取不到观测时不得计入判定面（否则是假绿）"


# ══════════════════════════════════════════════════════════════════════════
# 判据 3：机制清单是**显式登记**（发现面 = 结构性规则，不是文件名清单）
# ══════════════════════════════════════════════════════════════════════════
def test_discovery_rule_reproduces_the_known_mechanisms():
    """发现面必须**非空**且含 issue #5326 点名的机制 —— 规则失效（取空）时判据会静默空跑成绿。"""
    found = ML.discover_maintenance_workflows(REPO_ROOT)
    print(f"[发现面] 维护类机制现取 {len(found)} 个：{sorted(found)}")
    assert len(found) >= 8, f"发现面过小 ⇒ 规则可能失效：{sorted(found)}"
    for expected in ("automerge.yml", "close-linked-issues.yml", "deploy-reconcile.yml", "drift-audit.yml",
                     "fixture-record.yml", "flaky-ledger-reconcile.yml", "flaky-triage.yml", "stale.yml"):
        assert expected in found, f"{expected} 没被发现 —— 它正是 issue #5326 点名过的机制"


def test_every_maintenance_workflow_is_registered_or_exempt():
    """主线不变量：**新增维护类机制必须同时登记**，否则『新机制没人看』重演。"""
    exit_code, out = _checker_exit(REPO_ROOT, "--check")
    assert exit_code == 0, f"判定本体判红（退出码 {exit_code}）：\n{out}"
    assert "无 finding" in out, f"退出码 0 但报告不是无 finding ⇒ 报告与退出码不一致：\n{out}"


def test_red_proof_unregistered_maintenance_workflow_is_red(tmp_path):
    """**注入式红证（判据 3）**：加一个「scheduled + `issues: write`」的 workflow 且不登记 ⇒ **必红**。"""
    repo = _mini_repo(tmp_path)
    (repo / ".github" / "workflows" / "brand-new-sweeper.yml").write_text(
        "name: Brand New Sweeper\n"
        "on:\n"
        "  schedule:\n"
        "    - cron: '7 7 * * *'\n"
        "  workflow_dispatch:\n"
        "permissions:\n"
        "  issues: write\n"
        "jobs:\n"
        "  sweep:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo sweeping\n",
        encoding="utf-8",
    )
    exit_code, out = _checker_exit(repo, "--check")
    assert exit_code == 1, f"未登记的维护类机制必须判红（退出码 1），实测 {exit_code}：\n{out}"
    assert "brand-new-sweeper.yml" in out and "unregistered" in out, f"判红必须点名那个文件：\n{out}"


def test_negative_control_readonly_scheduled_workflow_is_not_a_mechanism(tmp_path):
    """**负控**：只读的定时 workflow（报告型）**不是**维护类机制 ⇒ 不登记也**不许判红**。

    它把「发现面」钉在**语义**上：规则不是「凡是新 workflow 都要登记」。
    """
    repo = _mini_repo(tmp_path)
    (repo / ".github" / "workflows" / "nightly-report-only.yml").write_text(
        "name: Nightly Report\n"
        "on:\n"
        "  schedule:\n"
        "    - cron: '7 7 * * *'\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  report:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo reporting\n",
        encoding="utf-8",
    )
    exit_code, out = _checker_exit(repo, "--check")
    assert exit_code == 0, f"只读报告型定时 workflow 不该被判成未登记机制：\n{out}"


def test_negative_control_comment_mention_does_not_satisfy_the_rule(tmp_path):
    """**负控（判据不读文案）**：注释里写 `issues: write` **不算**写作用域 —— 本仓 `#5323` 的形态。"""
    repo = _mini_repo(tmp_path)
    (repo / ".github" / "workflows" / "commented-only.yml").write_text(
        "name: Commented Only\n"
        "on:\n"
        "  schedule:\n"
        "    - cron: '7 7 * * *'\n"
        "permissions:\n"
        "  contents: read\n"
        "  # 本 workflow **不**声明 issues: write（这句注释不得被读成声明）\n"
        "jobs:\n"
        "  noop:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        '      - run: "echo \'# issues: write\'"\n',
        encoding="utf-8",
    )
    found = ML.discover_maintenance_workflows(repo)
    assert "commented-only.yml" not in found, (
        f"注释/字符串里的 `issues: write` 被当成了真权限声明 ⇒ 判据又把原文当代码读了：{sorted(found)}"
    )


def test_negative_control_pr_only_workflow_is_not_unattended(tmp_path):
    """**负控**：有写作用域但**只由 PR 触发**的 workflow 不是无人值守机制（有人推动它）⇒ 不要求登记。"""
    repo = _mini_repo(tmp_path)
    (repo / ".github" / "workflows" / "pr-only-commenter.yml").write_text(
        "name: PR Only Commenter\n"
        "on:\n"
        "  pull_request:\n"
        "    branches: [main]\n"
        "permissions:\n"
        "  pull-requests: write\n"
        "jobs:\n"
        "  comment:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo commented\n",
        encoding="utf-8",
    )
    assert "pr-only-commenter.yml" not in ML.discover_maintenance_workflows(repo), (
        "PR 触发的 workflow 被当成了**无人值守**机制 ⇒ 发现面过宽（会给每个 PR 制造噪声）"
    )


def test_exempt_entries_must_carry_reason_and_issue(tmp_path):
    """豁免 = 台账：每条**必须带理由 + 单号**；且**不得**与 `mechanisms` 重复记账（两处必漂移）。"""
    repo = _mini_repo(tmp_path)
    path = repo / "scripts" / "mechanism-registry.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["mechanisms"] = [e for e in data["mechanisms"] if e["id"] != "stale"]
    data["exempt"] = [{"workflow": ".github/workflows/stale.yml", "reason": "短", "issue": "nope"}]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    keys = {f.key for f in ML.check_registration(repo, ML.load_registry(repo))[0].findings}
    assert "exempt:.github/workflows/stale.yml" in keys, f"缺理由/单号的豁免必须判红：{sorted(keys)}"
    assert not any(k.startswith("unregistered:") for k in keys), (
        f"豁免面已覆盖 stale.yml ⇒ 不该再报「未登记」（豁免是合法出口，不是装饰）：{sorted(keys)}"
    )

    # **负控**：补上理由 + 单号后，同一个豁免条目必须**放行**（否则「登记」这条出口是假的）
    data["exempt"] = [{"workflow": ".github/workflows/stale.yml",
                       "reason": "夹具：验证豁免面是合法出口（真实场景下每个豁免都必须有理由 + 单号）",
                       "issue": "#5326"}]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    keys_ok = {f.key for f in ML.check_registration(repo, ML.load_registry(repo))[0].findings}
    assert not keys_ok, f"合规的豁免条目必须放行，实测仍判红：{sorted(keys_ok)}"


def test_negative_control_duplicate_exempt_and_registry_is_red(tmp_path):
    """**负控**：同一个 workflow **同时**登记在 `mechanisms` 与 `exempt` ⇒ 判红（别两处记账）。"""
    repo = _mini_repo(tmp_path)
    path = repo / "scripts" / "mechanism-registry.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["exempt"] = [{"workflow": ".github/workflows/stale.yml",
                       "reason": "夹具：故意与 mechanisms 重复记账，验证该形态会被拦",
                       "issue": "#5326"}]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    keys = {f.key for f in ML.check_registration(repo, ML.load_registry(repo))[0].findings}
    assert "exempt-duplicate:.github/workflows/stale.yml" in keys, (
        f"两处记账必须判红（它们必然漂移成互相矛盾的读数）：{sorted(keys)}"
    )


def test_stale_registry_entry_is_red(tmp_path):
    """登记的 workflow 若已**不再是**维护类机制 ⇒ 条目陈旧，必红（台账只许缩短）。"""
    repo = _mini_repo(tmp_path)
    (repo / ".github" / "workflows" / "stale.yml").unlink()
    report, _ = ML.check_registration(repo, ML.load_registry(repo))
    keys = {f.key for f in report.findings}
    assert "entry-workflow:stale" in keys, f"登记指向不存在的工作流必须判红：{sorted(keys)}"


# ══════════════════════════════════════════════════════════════════════════
# 判据 4：零动作与未运行可区分
# ══════════════════════════════════════════════════════════════════════════
def test_zero_action_and_not_run_have_different_shapes(tmp_path):
    """**「我没做事」≠「我没跑」**：前者有读数（`acted=0` + `why`），后者**没有这一行**。"""
    (tmp_path / "disposition").write_text("seen=9\nacted=0\nwhy=本轮无待处理\n", encoding="utf-8")
    _rc, ran_zero_action, _ = _run_emitter(EMITTER, ["emit", "demo", "--outcome", "success"], tmp_path)
    # 「没跑」= 读数步根本没执行 ⇒ 发射器没有产出
    never_ran: list[str] = []
    assert len(ran_zero_action) == 1 and never_ran == [], (
        f"零动作必须出声，未运行必须无声 —— 两者同形就退化成 {{{{无法区分}}}}："
        f"zero_action={ran_zero_action} never_ran={never_ran}"
    )
    zero = ML.parse_readings(ran_zero_action, "demo")[0]
    assert zero["acted"] == "0" and zero["why"].strip(), f"零动作读数的形态不对：{zero}"


def test_unfixed_and_zero_action_are_counted_apart():
    """**判据 5 的燃尽锚点**：instrumented / unfixed **现取计数**（不写死数字）。"""
    registry = _registry_data()
    instrumented = [e["id"] for e in registry["mechanisms"] if e.get("reading") == "instrumented"]
    unfixed = [e["id"] for e in registry["mechanisms"] if e.get("reading") != "instrumented"]
    unfixed_items = sum(len(e.get("unfixed") or []) for e in registry["mechanisms"])
    print(f"[燃尽锚点] 机制={len(registry['mechanisms'])} / instrumented={len(instrumented)} "
          f"/ unfixed 机制={len(unfixed)}（{unfixed}）/ 未固化子项={unfixed_items}")
    assert instrumented, "instrumented 为 0 ⇒ 读出面为空"
    assert unfixed_items > 0, (
        "未固化子项为 0 ⇒ 要么全部固化（好），要么**判据 5 的登记口子被绕过**（没人登记缺口）——本单实测非 0，"
        "该断言一旦变红请先确认是哪种"
    )


# ══════════════════════════════════════════════════════════════════════════
# 判据 5：未固化必须逐条登记「未固化 + 原因 + 谁看」，**不许留白**
# ══════════════════════════════════════════════════════════════════════════
def test_unfixed_entries_are_registered_with_reason_and_consumer():
    """每个未固化条目必须带 `what` / `reason` / `issue` / `consumer` —— 留白即判红。"""
    registry = _registry_data()
    report, _ = ML.check_registration(REPO_ROOT, registry)
    bad = [f for f in report.findings if f.key.startswith(("unfixed-", "entry-"))]
    assert not bad, "未固化登记不合规：\n" + "\n".join(f"  {f.key}: {f.detail}" for f in bad)
    for entry in registry["mechanisms"]:
        if entry.get("reading") != "instrumented":
            continue
        for item in entry.get("unfixed") or []:
            assert str(item.get("reason", "")).strip() and str(item.get("consumer", "")).strip(), (
                f"{entry['id']} 的未固化条目缺 原因/谁看：{item}"
            )


def test_red_proof_blank_unfixed_entry_is_red(tmp_path):
    """**注入式红证（判据 5）**：把某机制的未固化条目**清空** ⇒ **必红**（`unfixed-blank:<id>`）。"""
    repo = _mini_repo(tmp_path)
    path = repo / "scripts" / "mechanism-registry.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    victim = next(e for e in data["mechanisms"] if e.get("reading") != "instrumented")
    victim["unfixed"] = []
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    report, _ = ML.check_registration(repo, ML.load_registry(repo))
    keys = {f.key for f in report.findings}
    assert f"unfixed-blank:{victim['id']}" in keys, (
        f"`reading: unfixed` 却没有条目 ⇒ 必须判红（不许留白）。实测 {sorted(keys)}"
    )


def test_red_proof_unfixed_item_missing_consumer_is_red(tmp_path):
    """**注入式红证（判据 5）**：未固化条目抽掉 `consumer`（谁看）⇒ **必红**。"""
    repo = _mini_repo(tmp_path)
    path = repo / "scripts" / "mechanism-registry.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    victim = next(e for e in data["mechanisms"] if e.get("unfixed"))
    victim["unfixed"][0]["consumer"] = ""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    report, _ = ML.check_registration(repo, ML.load_registry(repo))
    keys = {f.key for f in report.findings}
    assert f"unfixed-fields:{victim['id']}" in keys, f"缺「谁看」必须判红，实测 {sorted(keys)}"


# ══════════════════════════════════════════════════════════════════════════
# 三态：无法判定**不得当绿**
# ══════════════════════════════════════════════════════════════════════════
def test_undecidable_is_exit_three_not_zero(tmp_path):
    """取不到判定面（没有 `.github/workflows`）⇒ 退出码 **3**（无法判定），**不是 0**。"""
    empty = tmp_path / "empty"
    empty.mkdir()
    exit_code, out = _checker_exit(empty, "--check")
    assert exit_code == 3, f"判定面取空必须退出 3（不得当 0 读），实测 {exit_code}：\n{out}"
    assert "无法判定" in out, f"退出 3 必须写明为什么：\n{out}"


def test_missing_registry_is_exit_three(tmp_path):
    """登记数据缺失 ⇒ 退出码 3（**没有任何机制被登记**不得当绿）。"""
    repo = _mini_repo(tmp_path)
    (repo / "scripts" / "mechanism-registry.json").unlink()
    exit_code, out = _checker_exit(repo, "--check")
    assert exit_code == 3, f"清单缺失必须退出 3，实测 {exit_code}：\n{out}"


def test_watchdog_fixture_leg_matches_network_leg_judgement():
    """夹具腿与网络腿走**同一个**判定本体（`judge_watchdog`）—— 否则「本地绿」不代表 CI 绿。"""
    registry = _registry_data()
    observations = {}
    for entry in registry["mechanisms"]:
        observations[entry["id"]] = _obs(
            annotations=[f"::notice::MECHANISM-LIVENESS mech={entry['id']} run={RUN_ID} "
                         f"rc=0 seen=unknown acted=unknown why=本轮零动作"],
        )
    rep = ML.judge_watchdog(registry, observations)
    assert not rep.findings, f"全量夹具应绿：{[f.key for f in rep.findings]}"
    assert rep.evaluated["judged_mechanisms"] == len(registry["mechanisms"]), (
        f"判定面必须覆盖全部登记机制：{rep.evaluated} vs {len(registry['mechanisms'])}"
    )


def test_watchdog_fixture_file_leg_is_wired(tmp_path):
    """`--readings <file>` 这条腿必须真的接上（供离线复跑与**本机**验证，零成本）。"""
    repo = _mini_repo(tmp_path)
    registry = ML.load_registry(repo)
    fixture = tmp_path / "readings.json"
    fixture.write_text(json.dumps({
        e["id"]: _obs(annotations=[
            f"::notice::MECHANISM-LIVENESS mech={e['id']} run={RUN_ID} rc=0 seen=unknown acted=unknown why=ok",
        ]) for e in registry["mechanisms"]
    }, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--repo", str(repo), "--check", "--watchdog",
         "--readings", str(fixture)],
        capture_output=True, text=True, timeout=180, cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, f"夹具腿应绿，实测 {proc.returncode}：\n{proc.stdout}{proc.stderr}"
    assert "judged_mechanisms" in proc.stdout, f"报告里必须现取判定面：\n{proc.stdout}"


# ══════════════════════════════════════════════════════════════════════════
# 内联落点（`reading_site: inline`）—— 同一真值的**第二处投影**，必须机械钉等价
# ══════════════════════════════════════════════════════════════════════════
def _inline_step_run(entry: dict) -> str:
    steps = ML._job_steps(REPO_ROOT, entry["workflow"], entry["job"])
    hits = [
        s for s in steps
        if isinstance(s.get("run"), str) and ML.MECHANISM_MARKER in s["run"]
        and f"mech={entry['id']}" in s["run"]
    ]
    assert len(hits) == 1, f"{entry['id']}：内联读数步必须**恰好一步**，实测 {len(hits)}"
    return hits[0]["run"]


def _run_inline(run_text: str, outcome: str, mech: str):
    """**真跑**内联读数文本（不重写判定逻辑），返回 (读数行, 级别)。"""
    env = {**os.environ, "GITHUB_RUN_ID": "1234567890", "OUTCOME": outcome}
    proc = subprocess.run(["bash", "-c", run_text], capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 0, f"内联读数步不得失败（它是报告者）：{proc.stderr}"
    parsed = ML.parse_readings(proc.stdout.splitlines(), mech)
    assert len(parsed) == 1, f"内联发射必须恰好一行可解析读数，实测 {proc.stdout!r}"
    level = "notice" if "::notice::" in proc.stdout else "warning"
    return parsed[0], level


def test_inline_emission_is_grammar_equivalent_to_the_emitter(tmp_path):
    """`reading_site: inline` 与共享发射器必须**逐字段同语法**（同一真值两处投影 ⇒ 机械钉等价）。

    为什么需要：`close-linked-issues` 因**安全不变量**（`pull_request_target` 不得 checkout）取不到
    发射器文件，只能内联发射。内联 = 第二处投影 ⇒ 不钉等价就会漂移成「写进判据的读数」与
    「看门人读的读数」不是一回事（本仓 #5346 ③ 记的正是这条）。
    """
    registry = _registry_data()
    inline_entries = [e for e in registry["mechanisms"] if e.get("reading_site") == "inline"]
    assert inline_entries, "没有 inline 落点 ⇒ 本判据面为空（若已全部走共享发射器，请删掉本测并销账）"
    for entry in inline_entries:
        assert len(str(entry.get("reading_site_reason") or "")) >= ML.INLINE_REASON_MIN, (
            f"{entry['id']}：内联必须写明**为什么不能共享发射器**（否则就是绕过单一真值源的口子）"
        )
        run_text = _inline_step_run(entry)
        for outcome, want_level, want_rc in (("success", "notice", "0"), ("failure", "warning", "1")):
            inline, level = _run_inline(run_text, outcome, entry["id"])
            emitted_rc, emitted_lines, _ = _run_emitter(
                EMITTER, ["emit", entry["id"], "--outcome", outcome], tmp_path,
            )
            emitter = ML.parse_readings(emitted_lines, entry["id"])[0]
            emitter_level = "notice" if emitted_lines[0].startswith("::notice::") else "warning"
            assert set(inline) == set(emitter), (
                f"{entry['id']}：内联与发射器的**字段集**不同 —— {sorted(inline)} vs {sorted(emitter)}"
            )
            assert (inline["rc"], level) == (emitted_rc_expected := (want_rc, want_level)), (
                f"{entry['id']}/{outcome}：内联 rc/级别 = {(inline['rc'], level)}，期望 {emitted_rc_expected}"
            )
            assert (emitter["rc"], emitter_level) == (want_rc, want_level), (
                f"{entry['id']}/{outcome}：发射器 rc/级别 = {(emitter['rc'], emitter_level)}，期望 {(want_rc, want_level)}"
            )
            assert emitted_rc == 0, "发射器自身的退出码恒 0（报告者不得改写机制结论）"
            assert inline["mech"] == emitter["mech"] == entry["id"], f"{entry['id']}：mech 归属不一致"
            assert inline["run"] and inline["why"].strip() and emitter["why"].strip(), (
                f"{entry['id']}：读数必须绑定 run 且写明原因：inline={inline} emitter={emitter}"
            )


def test_red_proof_breaking_the_inline_grammar_is_detected(tmp_path):
    """**注入式红证（两处投影）**：把内联读数行的字段名改掉 ⇒ **本判据必红**。"""
    registry = _registry_data()
    entry = next(e for e in registry["mechanisms"] if e.get("reading_site") == "inline")
    run_text = _inline_step_run(entry)
    assert "rc=%s" in run_text, f"夹具前置不成立：内联文本里找不到字段 `rc=`：{run_text!r}"
    broken = run_text.replace("rc=%s", "exit=%s", 1)
    env = {**os.environ, "GITHUB_RUN_ID": "1234567890", "OUTCOME": "success"}
    proc = subprocess.run(["bash", "-c", broken], capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert ML.parse_readings(proc.stdout.splitlines(), entry["id"]) == [], (
        f"字段名漂移后仍能解析 ⇒ 内联与发射器不同源。实测 stdout={proc.stdout!r}"
    )


def test_injection_helper_self_proves_it_took_effect(tmp_path):
    """**G7 的自证**：注入辅助函数必须拒绝「没注入」与「锚点不唯一」两种假红证。"""
    unique = 'MECHANISM_LIVENESS_MARKER="MECHANISM-LIVENESS"'
    assert EMITTER.read_text(encoding="utf-8").count(unique) == 1, "夹具前置：该锚点本该唯一"
    _mutate_emitter(tmp_path, unique, 'MECHANISM_LIVENESS_MARKER="MUTATED"', "self-proof-ok")
    for old, new, why in (
        (unique, unique, "前后相同（什么也没注入）"),
        ("不存在的锚点（故意）", "x", "锚点不存在"),
        ('  printf \'%s\\n\' "$line"', '  printf \'%s\\n\' "$line"', "锚点重复出现且未变"),
    ):
        with pytest.raises(AssertionError) as caught:
            _mutate_emitter(tmp_path, old, new, "should-fail")
        # 断言**具体理由**（不是「抛了就行」）：辅助函数必须点名它为什么拒绝，
        # 否则调用方读不出「这个红证到底成不成立」。
        assert "[should-fail]" in str(caught.value), (
            f"注入辅助函数放行了「{why}」或没给出可读理由 ⇒ 红证可能是空红证：{caught.value}"
        )


# ══════════════════════════════════════════════════════════════════════════
# 判据 5 的**燃尽靶子**（§23 G2）：未固化条数**只许缩短**
# ══════════════════════════════════════════════════════════════════════════
def test_unfixed_ledger_only_shrinks():
    """未固化条数**现取**并对着预算比对 —— 预算只许缩短（涨了就是判红，不是"多登记一条"）。"""
    registry = _registry_data()
    budget = registry.get("unfixed_budget")
    assert isinstance(budget, dict) and isinstance(budget.get("max_items"), int), (
        "登记数据缺 `unfixed_budget` ⇒ 未固化条数可以无限增长而无处可见（G2 的靶子没了）"
    )
    live_items = sum(len(e.get("unfixed") or []) for e in registry["mechanisms"])
    live_mech = sum(1 for e in registry["mechanisms"] if e.get("reading") != "instrumented")
    print(f"[燃尽靶子] 未固化：机制 {live_mech}/{budget.get('max_mechanisms')} · "
          f"子项 {live_items}/{budget['max_items']}（**只许缩短**；冻结于 {budget.get('frozen_at')}）")
    assert live_items <= budget["max_items"], f"现取 {live_items} > 预算 {budget['max_items']} —— 债务涨了"
    assert live_mech <= budget.get("max_mechanisms", live_mech), "未固化机制数涨了"


def test_red_proof_unfixed_budget_growth_is_red(tmp_path):
    """**注入式红证（G2）**：往台账里**多塞一条**未固化条目 ⇒ 预算判红（不是"登记完就没事"）。"""
    repo = _mini_repo(tmp_path)
    path = repo / "scripts" / "mechanism-registry.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    victim = next(e for e in data["mechanisms"] if e.get("unfixed"))
    victim["unfixed"].append({
        "what": "夹具：故意多塞一条未固化条目，验证燃尽靶子会拦",
        "reason": "夹具：验证「把新债务登记进 unfixed」不是出口（预算只许缩短）",
        "issue": "#5326",
        "consumer": "夹具：验证 G2 靶子生效",
    })
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    keys = {f.key for f in ML.check_registration(repo, ML.load_registry(repo))[0].findings}
    assert "unfixed-budget-exceeded" in keys, (
        f"未固化条数超出预算必须判红（否则「登记」就是绕过判据 5 的口子）：{sorted(keys)}"
    )


def test_red_proof_removing_the_burn_down_target_is_red(tmp_path):
    """**注入式红证（G2）**：把 `unfixed_budget` 抹掉 ⇒ 判红（靶子不在 = 债务无处可见）。"""
    repo = _mini_repo(tmp_path)
    path = repo / "scripts" / "mechanism-registry.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("unfixed_budget", None)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    keys = {f.key for f in ML.check_registration(repo, ML.load_registry(repo))[0].findings}
    assert "unfixed-budget-missing" in keys, f"缺燃尽靶子必须判红，实测 {sorted(keys)}"


# ══════════════════════════════════════════════════════════════════════════
# 元守卫：**本包自己踩过的两处缺陷形态**，让它们进不来（§23 G1「实例判据 + 类级元守卫成对」）
# ══════════════════════════════════════════════════════════════════════════
def _outcome_binding_problems(repo: Path) -> tuple[int, list[str]]:
    """读数步的 `env.OUTCOME` 必须是 ``${{ job.status }}`` —— 返回 (现取数, 逐条问题)。

    定位口径与判定本体**同源**（`reading_site` 分派：`emitter` 按 `emit <id>`，`inline` 按 `mech=<id>`）
    —— 否则「元守卫扫 0 个 step 却报绿」这种空跑会自己发生。
    """
    registry = json.loads((repo / "scripts" / "mechanism-registry.json").read_text(encoding="utf-8"))
    problems: list[str] = []
    checked = 0
    for entry in registry["mechanisms"]:
        site = entry.get("reading_site", "emitter")
        needle = f"emit {entry['id']}" if site == "emitter" else f"mech={entry['id']}"
        for step in ML._job_steps(repo, entry["workflow"], entry["job"]):
            run = str(step.get("run") or "")
            if needle not in run:
                continue
            if site == "inline" and ML.MECHANISM_MARKER not in run:
                continue
            checked += 1
            env = step.get("env")
            bound = env.get("OUTCOME") if isinstance(env, dict) else None
            if "--outcome" not in run:
                # 工作步内联发射（automerge：读数并入跑判据脚本的那一步）不吃 `env.OUTCOME`，
                # 它用 `--rc "$RC"`；⇒ 改判「rc 确实来自被捕获的退出码」。
                # 两种合法的 rc 来源（都要求 rc 是**真读出来的**，不是字面量常量）：
                #   · 工作步内联（automerge）：`set +e; <cmd>; RC=$?` ⇒ `--rc "$RC"`；
                #   · 专用内联读数步（close-linked-issues，无 checkout）：`case "$OUTCOME"` 映射 rc
                #     —— 该映射的**等价性**由 `test_inline_emission_is_grammar_equivalent_to_the_emitter` 真跑钉住。
                reads_rc = bool(re.search(r"RC=\$\?", run)) or 'case "$OUTCOME" in' in run
                # rc 必须**真读出来**并**真的进了读数行**：
                #   · 调发射器 ⇒ `--rc "$RC"`；· 纯内联 printf ⇒ 格式串含 `rc=%s` 且实参含 `"$RC"`。
                passes_rc = '--rc "$RC"' in run or ("rc=%s" in run and '"$RC"' in run)
                if not (reads_rc and passes_rc):
                    problems.append(
                        f"{entry['id']}：内联发射必须把**真读出来的** rc 送进读数行"
                        f"（`RC=$?` 或 `case \"$OUTCOME\"` 映射 + `--rc \"$RC\"` / `rc=%s`）：{run[-160:]!r}"
                    )
            elif bound != "${{ job.status }}":
                problems.append(f"{entry['id']}：读数步的 `env.OUTCOME` = {bound!r}")
            elif "$OUTCOME" not in run:
                # 只要求 `run:` **真的用到** `$OUTCOME`（把 env 绑定交给机制体）；
                # 内联落点（close-linked-issues）用 `case "$OUTCOME"`，同样是合法用法。
                problems.append(f"{entry['id']}：`run:` 里没用到 `$OUTCOME`（env 绑了个没人读的值）")
    return checked, problems


def test_reading_step_binds_outcome_to_the_github_expression():
    """读数步的 `OUTCOME` 必须绑定 ``${{ job.status }}`` —— **不许是字面量 / 被吃掉花括号的残骸**。

    这是本包**自己踩过**的缺陷：生成读数步时用 `str.format()` 拼模板 ⇒ ``${{ job.status }}``
    被吃成 `${ job.status }`，GitHub 不再解析它 ⇒ `--outcome` 落到 `rc=?`，
    **每一轮读数都变成 `::warning::`**（机制看着像永久失败）。**6 个 workflow 同时中招**，
    而当时的判据一条都没红 ⇒ 正是「判据没覆盖到的地方 = 永久免检」。
    """
    checked, problems = _outcome_binding_problems(REPO_ROOT)
    print(f"[元守卫] 读数步现取 = {checked} 个（全部绑定 job.status）")
    assert checked >= 8, f"读数步现取 {checked} 个 ⇒ 判据面过小（元守卫失效）"
    assert not problems, "读数步的 OUTCOME 绑定不合规（GitHub 不解析 ⇒ 每轮读数都像失败）：\n" + "\n".join(
        f"  {x}" for x in problems
    )


def test_red_proof_unbound_outcome_expression_is_red(tmp_path):
    """**注入式红证**：把 `env.OUTCOME` 换成被吃花括号的残骸 `${ job.status }` ⇒ **必红**。"""
    repo = _mini_repo(tmp_path)
    assert _outcome_binding_problems(repo)[1] == [], "夹具前置不成立：副本本该是合规的"
    victim = repo / ".github" / "workflows" / "stale.yml"
    text = victim.read_text(encoding="utf-8")
    good = "          OUTCOME: ${{ job.status }}\n"
    assert text.count(good) == 1, "夹具前置：该绑定本该唯一"
    victim.write_text(text.replace(good, "          OUTCOME: ${ job.status }\n"), encoding="utf-8")
    checked, problems = _outcome_binding_problems(repo)
    assert checked >= 8, f"现取读数步 {checked} 个 ⇒ 元守卫扫漏了（空跑会报绿）"
    assert any("stale" in x for x in problems), (
        f"被吃花括号的 `OUTCOME` 绑定没有让元守卫判红 ⇒ 该缺陷形态仍能溜过。实测 {problems}"
    )


def _shell_syntax_problems(repo: Path) -> tuple[int, list[str]]:
    """扫该仓库所有 workflow 的 `run:` 块做 `bash -n`（**纯语法**）—— 返回 (现取数, 逐条问题)。"""
    import yaml

    checked = 0
    broken: list[str] = []
    for path in sorted((repo / ".github" / "workflows").glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in ((doc or {}).get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                if not isinstance(step, dict) or not isinstance(step.get("run"), str):
                    continue
                shell = str(step.get("shell") or "bash")
                if "bash" not in shell and shell not in ("sh", ""):
                    continue
                checked += 1
                proc = subprocess.run(
                    ["bash", "-n", "/dev/stdin"], input=step["run"],
                    capture_output=True, text=True, timeout=60,
                )
                if proc.returncode != 0:
                    first = proc.stderr.strip().splitlines()[0] if proc.stderr.strip() else "?"
                    broken.append(f"{path.name} / job={job_name} / step={step.get('name')!r}：{first}")
    return checked, broken


def test_every_workflow_run_block_is_shell_valid():
    """**元守卫**：每个 workflow 的每个 `run:` 块都必须通过 `bash -n`（纯语法）。

    这也是本包**自己踩过**的缺陷：分段 patch 把 `fixture-record.yml` 的 run 块拼成
    `if … then` 没配平的 `fi`，**YAML 照样合法、当时全部判据都绿**，而该机制在 runner 上会直接语法错
    ⇒ 一次运行都不出声（正是本单要消灭的「静默失效」）。⇒ 把「run 块能跑」本身做成判据。

    边界（照实登记）：只做**语法**检查，不做语义检查；`shell:` 非 bash/sh 的步骤跳过。
    """
    checked, broken = _shell_syntax_problems(REPO_ROOT)
    print(f"[元守卫] 现取 run 块 = {checked} 个（全部通过 bash -n）")
    assert checked >= 150, f"判据面过小（现取 {checked} 个 run 块）⇒ 元守卫可能静默空跑成绿"
    assert not broken, "workflow 的 run 块有 shell 语法错（YAML 合法 ⇒ 不会有别的判据发现）：\n" + "\n".join(
        f"  {b}" for b in broken
    )


def test_red_proof_shell_broken_run_block_is_red(tmp_path):
    """**注入式红证**：把某个 run 块改成 `if … then` 不配平 ⇒ **必红**（而 YAML 仍合法）。

    这是本包真踩过的形态（`fixture-record.yml`），所以红证必须证明它**真的会被抓到**。
    """
    repo = _mini_repo(tmp_path)
    assert _shell_syntax_problems(repo)[1] == [], "夹具前置不成立：副本本该是合规的"
    victim = repo / ".github" / "workflows" / "fixture-record.yml"
    text = victim.read_text(encoding="utf-8")
    good = "            mechanism_liveness_declare --seen 1 --acted 0"
    assert text.count(good) == 1, "夹具前置：注入点本该唯一"
    # 注入一个 **`if` 没配平** 的块（这是真踩过的形态：分段 patch 少了一个 `fi`）
    victim.write_text(text.replace(good, "          if true; then\n" + good), encoding="utf-8")
    import yaml as _yaml
    _yaml.safe_load(victim.read_text(encoding="utf-8"))  # YAML 仍必须合法 ⇒ 别的判据发现不了
    checked, broken = _shell_syntax_problems(repo)
    assert checked >= 150, "判据面过小"
    assert any("fixture-record" in b for b in broken), (
        f"注入不配平的 `if` 后元守卫没有判红 ⇒ 该红证没有判别力。实测 {broken}"
    )


def test_red_proof_injection_helper_self_proves_in_shell_guard(tmp_path):
    """**负控**：合规副本上元守卫**不得**判红（否则它是「永远红」的空判据）。"""
    repo = _mini_repo(tmp_path)
    checked, broken = _shell_syntax_problems(repo)
    assert checked >= 150 and broken == [], f"合规副本被判红 ⇒ 空判据：checked={checked} broken={broken}"
    assert _outcome_binding_problems(repo)[1] == [], "合规副本的 OUTCOME 绑定被判红 ⇒ 空判据"


# ══════════════════════════════════════════════════════════════════════════
# 元守卫（第二批）：**CI 实测撞出来的两处**，同样各配注入式红证
# ══════════════════════════════════════════════════════════════════════════
def test_sourcing_the_emitter_does_not_mutate_caller_shell(tmp_path):
    """`source` 发射器**不得改写调用者的 shell 选项** —— 它是报告者，不该把机制弄挂。

    本包**CI 实测**撞出来的：发射器顶层写了 `set -uo pipefail` ⇒ 被 `drift-audit.yml` 的 run 块
    `source` 后，**调用者**变成 `-u` 模式，于是它后面一句引用尚未赋值的 `${OUT_SCOPE}`
    直接 `unbound variable` ⇒ **整个审计 job 判红**（`OUT_SCOPE: unbound variable`）。
    """
    probe = 'source "{emitter}" >/dev/null 2>&1; printf "flags=%s " "$-"; printf "unset=[%s]" "${{DEFINITELY_UNSET_XYZ:-}}"; echo'
    baseline = subprocess.run(["bash", "-c", 'printf "flags=%s" "$-"'], capture_output=True, text=True, timeout=60)
    sourced = subprocess.run(
        ["bash", "-c", probe.format(emitter=EMITTER)], capture_output=True, text=True, timeout=60,
    )
    assert sourced.returncode == 0, f"source 发射器后调用者直接失败（报告者把机制弄挂了）：{sourced.stderr}"
    got_flags = sourced.stdout.split("flags=")[1].split()[0]
    want_flags = baseline.stdout.strip().removeprefix("flags=")
    assert got_flags == want_flags, (
        f"source 发射器改变了调用者的 shell 选项：{got_flags!r} vs 基线 {want_flags!r} "
        f"⇒ 调用者后续引用未赋值变量会直接死"
    )
    assert "unset=[]" in sourced.stdout, f"source 后引用未赋值变量不安全：{sourced.stdout!r}"


def test_red_proof_emitter_mutating_caller_shell_is_red(tmp_path):
    """**注入式红证**：把 `set -uo pipefail` 加回发射器顶层 ⇒ **必红**（调用者选项被改写）。"""
    mutant = _mutate_emitter(
        tmp_path, 'MECHANISM_LIVENESS_MARKER="MECHANISM-LIVENESS"',
        'set -uo pipefail\nMECHANISM_LIVENESS_MARKER="MECHANISM-LIVENESS"', "shell-mutation",
    )
    proc = subprocess.run(
        ["bash", "-c", f'source "{mutant}" >/dev/null 2>&1; printf "flags=%s " "$-"; echo "unset=[${{NOPE_XYZ:-}}]"'],
        capture_output=True, text=True, timeout=60,
    )
    baseline = subprocess.run(["bash", "-c", 'printf "flags=%s" "$-"'], capture_output=True, text=True, timeout=60)
    assert proc.stdout.split("flags=")[1].split()[0] != baseline.stdout.strip().removeprefix("flags="), (
        f"注入 `set -uo pipefail` 后调用者选项竟然没变 ⇒ 该红证没有判别力：{proc.stdout!r}"
    )


def test_every_emitter_reading_step_fails_open_when_the_emitter_is_absent():
    """读数步必须**降级为 warning**，而不是判红：发射器可能不在检出里（固定 `ref: main` / 浅检出）。

    本包**CI 实测**撞出来的：`deploy-reconcile.yml` 检出 `ref: main`，而发射器是本 PR 新增 ⇒
    PR 自己的 CI 上取不到该文件 ⇒ `bash .github/scripts/mechanism_liveness.sh: No such file or directory`
    （exit 127）⇒ **job 判红**。判「静默」的地方是看门人（定时腿），不是这里 —— 报告者不改变机制结论。
    """
    missing: list[str] = []
    checked = 0
    for entry in _registry_data()["mechanisms"]:
        if entry.get("reading_site", "emitter") != "emitter":
            continue
        needle = f"emit {entry['id']}"
        for step in ML._job_steps(REPO_ROOT, entry["workflow"], entry["job"]):
            run = str(step.get("run") or "")
            if needle not in run:
                continue
            checked += 1
            if "if [ -f .github/scripts/mechanism_liveness.sh ]" not in run:
                missing.append(f"{entry['id']}：读数步没有「发射器不在检出里 ⇒ 降级」的护栏")
    print(f"[元守卫] 带护栏的读数步现取 = {checked} 个")
    assert checked >= 7, f"现取 {checked} 个 ⇒ 判据面过小（元守卫可能空跑报绿）"
    assert not missing, "读数步会把「发射器不在检出里」判红（报告者不得把机制弄挂）：\n" + "\n".join(
        f"  {m}" for m in missing
    )


def test_red_proof_reading_step_without_fail_open_guard_is_red(tmp_path):
    """**注入式红证**：把某个读数步的护栏去掉 ⇒ **必红**。"""
    repo = _mini_repo(tmp_path)
    victim = repo / ".github" / "workflows" / "stale.yml"
    text = victim.read_text(encoding="utf-8")
    guard = "          if [ -f .github/scripts/mechanism_liveness.sh ]; then\n"
    assert text.count(guard) == 1, "夹具前置：该护栏本该唯一"
    victim.write_text(text.replace(guard, "          if true; then\n"), encoding="utf-8")
    registry = ML.load_registry(repo)
    missing = []
    for entry in registry["mechanisms"]:
        if entry.get("reading_site", "emitter") != "emitter":
            continue
        for step in ML._job_steps(repo, entry["workflow"], entry["job"]):
            run = str(step.get("run") or "")
            if f"emit {entry['id']}" in run and "if [ -f .github/scripts/mechanism_liveness.sh ]" not in run:
                missing.append(entry["id"])
    assert "stale" in missing, f"去掉护栏后元守卫没有判红 ⇒ 该红证没有判别力：{missing}"
