# case_ids: MC-049
#
# runner_plane_ledger.json（迁移面登记表）的判据 —— 「`runs-on` 漂移」必须可见。
#
# ## 为什么需要它（issue #5814，2026-09-30）
#
# PR 面验证腿从 GitHub 托管迁到自托管 runner（`runs-on: [self-hosted, migao-mac]`）之后，
# 「哪条腿在哪一侧」这件事变成了**只在 YAML 里散着的事实**：
#
#   · 某个 PR 把某条 job 悄悄改回 `ubuntu-latest` ⇒ 它照样跑、照样可能绿，**没有任何东西变红**；
#   · 新增一条 job 用了没人审过的 runner ⇒ 同上；
#   · 反过来，把已迁的腿删了 ⇒ 台账里留下一条指向空气的登记，**也没有东西变红**。
#
# 这三态合起来就是本仓点名的形态：**漂移无告警**。判据 = 逐条登记 + 未登记即红 + 删条目即红。
#
# ## 这一层判什么 / 不判什么（边界如实登记，见台账 `coverage_boundary`）
#
# 判（纯静态、零网络、零 `gh`、同一份代码任何时刻同一读数）：
#   1. 每个 job 的 `runs-on` **逐值**等于台账登记值（未登记 / 漂移 / 新 job ⇒ 红）；
#   2. 台账里的（workflow, job）键**一个都不许静默消失**（删条目 ⇒ 红）；
#   3. 凡 `kind == "self-hosted"` 的 job，若用到 `actions/setup-python`，**必须**带
#      `if: ... runner.environment != 'self-hosted'`（本机实测：该 action 在非 `/Users/runner`
#      主机上必然失败 —— 见 `scripts/setup-self-hosted-runner.sh` 头部）；
#   4. 凡 **PR 触发 + 用 setup-python + 仍留在托管侧**的 job，必须**具名**给出理由
#      （`reason` / `kind`），不许靠缺省静默兜底；
#   5. 兜底面：`github-hosted` 类条目必须有非空 `reason`，`reusable-workflow-call` 必须有
#      `delegates_runs_on_to`；
#   6. 自托管 runner 的 `runs_on` 取值必须与 `.env` 期望值同源脚本的声明一致
#      （`scripts/setup-self-hosted-runner.sh` 的 `RUNNER_LABELS` 默认值 + `self-hosted`）；
#   7. 覆盖边界与冻结语义**在位**（台账 `coverage_boundary` 非空、`frozen_note` 非空、
#      `measured.recompute` 非空）—— 否则本判据会退化成「指向空气的判据」。
#
# **不判**（任何一种都不是本判据能覆盖的，不要把它读成覆盖面更大的东西）：
#   ① 该腿在自托管上**是否真能跑绿**（运行期事实，由 PR 上的 CI 结果承担）；
#   ② 自托管 runner 的**可用性**（机器睡眠 / 关机 ⇒ required 腿 `BLOCKED`）——没有任何静态
#      判据能变红；
#   ③ `on.pull_request.paths:` 过滤造成的「某些 PR 上根本不触发」（**既有**语义，本表不改）；
#   ④ `not_migrated_this_round` 那批留在托管侧的**安全性**（它们只是**现状登记**）。
from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
LEDGER_PATH = REPO / "tests" / "unit_ci_workflows" / "runner_plane_ledger.json"
SETUP_SCRIPT = REPO / "scripts" / "setup-self-hosted-runner.sh"
SELF_REL = "tests/unit_ci_workflows/test_runner_plane_ledger.py"

SCHEMA = "runner-plane-ledger/v1"
SELF_HOSTED_RUNS_ON = ["self-hosted", "migao-mac"]
SETUP_PYTHON = "actions/setup-python@v7"
SKIP_IF = "runner.environment != 'self-hosted'"


# ── 载入（唯一的 IO 面：台账 + 现取 workflow）────────────────────────────────────
def _workflow_doc(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), f"{path.name} 不是 YAML 映射"
    return doc


def _event_names(doc: dict) -> set[str]:
    """顶层 `on:` 的事件名集合。`on` 在 YAML 1.1 里会被解析成布尔 `True` ⇒ 两个键都看。"""
    on = doc.get("on", doc.get(True, None)) or {}
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(x) for x in on}
    assert isinstance(on, dict), f"顶层 `on:` 形态不认识：{type(on).__name__}"
    return {str(k) for k in on}


def _live_jobs() -> dict[tuple[str, str], dict]:
    """现取每个 job 的关键事实（**不读台账** —— 两边独立取值才判得出漂移）。"""
    out: dict[tuple[str, str], dict] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = _workflow_doc(path)
        pr = "pull_request" in _event_names(doc)
        for jid, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            steps = [s for s in (job.get("steps") or []) if isinstance(s, dict)]
            sp = [s for s in steps if str(s.get("uses", "")).startswith("actions/setup-python")]
            out[(f".github/workflows/{path.name}", jid)] = {
                "runs_on": job.get("runs-on"),
                "uses": job.get("uses"),
                "pr": pr,
                "setup_python_if": [s.get("if") for s in sp],
            }
    return out


def _ledger() -> dict:
    assert LEDGER_PATH.exists(), f"缺迁移面登记表 {LEDGER_PATH.relative_to(REPO)}（issue #5814）"
    data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "登记表不是 JSON 对象"
    return data


def _entries(data: dict) -> list[dict]:
    jobs = data.get("jobs")
    assert isinstance(jobs, list) and jobs, (
        "登记表 `jobs` 为空 ⇒ 本判据会在空集上恒真（空跑成绿）。"
        "复算：python3 -m pytest tests/unit_ci_workflows/test_runner_plane_ledger.py -q -s"
    )
    return jobs


def _rel(key: str) -> str:
    """归一成**仓库相对全路径**（`Path.name` 会让两个不同目录的同名文件撞在一起）。"""
    key = str(key)
    return key if key.startswith(".github/") else f".github/workflows/{Path(key).name}"


def _entry_key(e: dict) -> tuple[str, str]:
    return (_rel(e.get("workflow") or ""), str(e.get("job") or ""))


def _problems(data: dict, live: dict[tuple[str, str], dict]) -> list[str]:
    """判定本体（纯函数，便于用**内存构造**的坏形态做注入式红证）。"""
    problems: list[str] = []
    seen: dict[tuple[str, str], dict] = {}
    for e in _entries(data):
        key = _entry_key(e)
        if not all(key):
            problems.append(f"条目缺 workflow/job：{e!r}")
            continue
        if key in seen:
            problems.append(f"重复登记的条目：{key[0]}::{key[1]}")
            continue
        seen[key] = e
        if key not in live:
            problems.append(
                f"登记了**不存在**的 job：{key[0]}::{key[1]}"
                "（job 被删/改名 ⇒ 登记指向空气；同步改登记表或恢复该 job）"
            )
            continue
        got, exp = live[key]["runs_on"], e.get("runs_on")
        if got != exp:
            problems.append(
                f"`runs-on` 漂移：{key[0]}::{key[1]} 现取 {got!r} ≠ 登记 {exp!r}"
            )
        kind = e.get("kind")
        if exp == SELF_HOSTED_RUNS_ON and kind != "self-hosted":
            problems.append(f"{key[0]}::{key[1]} 的 runs-on 是自托管取值，但 kind={kind!r}")
        if exp is None and kind != "reusable-workflow-call":
            problems.append(f"{key[0]}::{key[1]} 无 `runs-on`，kind 应为 reusable-workflow-call，实为 {kind!r}")
        if kind == "reusable-workflow-call" and not e.get("delegates_runs_on_to"):
            problems.append(
                f"{key[0]}::{key[1]} 是复用 workflow 调用，但缺 `delegates_runs_on_to`"
                "（执行环境由被调用方决定 ⇒ 必须点名是哪一个）"
            )
        if kind == "github-hosted" and len(str(e.get("reason") or "")) < 8:
            problems.append(f"{key[0]}::{key[1]} 留在托管侧但没有理由（`reason` 缺失/过短）")

        # 环境假设：自托管 + 用 setup-python ⇒ 必须带自托管跳过条件
        if exp == SELF_HOSTED_RUNS_ON and live[key]["setup_python_if"]:
            for cond in live[key]["setup_python_if"]:
                if SKIP_IF not in str(cond or ""):
                    problems.append(
                        f"自托管 job 的 {SETUP_PYTHON} 缺自托管跳过条件：{key[0]}::{key[1]} "
                        f"（现取 if={cond!r}）—— 该 action 在非 /Users/runner 主机上必然失败"
                    )

    # 反向：现取里有、登记表里没有 ⇒ 未登记即红
    for key in sorted(live):
        if key not in seen:
            problems.append(
                f"**未登记**的 job：{key[0]}::{key[1]}（runs-on={live[key]['runs_on']!r}）"
                " —— 新增/改名的 job 必须同步登记进 runner_plane_ledger.json"
            )
    return problems


def _self_hosted_entries(data: dict) -> list[dict]:
    return [e for e in _entries(data) if e.get("runs_on") == SELF_HOSTED_RUNS_ON]


# ── 判据 1：真语料必须判绿 ──────────────────────────────────────────────────────
def test_real_corpus_has_no_problems():
    problems = _problems(_ledger(), _live_jobs())
    assert problems == [], "迁移面登记表与现取 workflow 漂移：\n" + "\n".join(f"  · {p}" for p in problems)


def test_ledger_is_wellformed_and_recomputable():
    data = _ledger()
    assert data.get("schema") == SCHEMA, f"schema 不是 {SCHEMA}：{data.get('schema')!r}"
    measured = data.get("measured") or {}
    for k in ("at", "source", "recompute"):
        assert str(measured.get(k) or "").strip(), f"登记表缺 `measured.{k}`（读数不可复算 = 不可验证的断言）"
    runner = measured.get("self_hosted_runner") or {}
    assert runner.get("runs_on_value") == SELF_HOSTED_RUNS_ON, (
        f"登记的 runs-on 取值与判据冻结值不一致：{runner.get('runs_on_value')!r} vs {SELF_HOSTED_RUNS_ON!r}"
    )
    assert data.get("coverage_boundary"), "登记表缺 `coverage_boundary`（未覆盖形态必须如实登记）"
    assert str(data.get("frozen_note") or "").strip(), "登记表缺 `frozen_note`（冻结语义不在位 ⇒ 删条目就无人拦）"
    print(f"登记 job 数={len(_entries(data))} / 自托管={len(_self_hosted_entries(data))}")


# ── 判据 2：迁移面必须真的到位（**不是**只把数字写进台账）────────────────────────
def test_migrated_plane_is_non_trivial_and_declared():
    data = _ledger()
    self_hosted = _self_hosted_entries(data)
    assert len(self_hosted) >= 1, "一条 self-hosted 登记都没有 —— 迁移面没落地（判据会在空集上恒真）"
    files = sorted({_rel(e["workflow"]) for e in self_hosted})
    print(f"自托管 job 数={len(self_hosted)} 覆盖 workflow={files}")
    for name in (".github/workflows/pr-check.yml",):
        assert any(_rel(e["workflow"]) == name for e in self_hosted), f"{name} 没有一条 job 登记为自托管"


def test_pr_triggered_github_hosted_legs_are_named_not_defaulted():
    """PR 触发 + 仍留在托管侧的腿必须**具名**（`kind` 不许是宽松缺省）。"""
    data = _ledger()
    vague = []
    for e in _entries(data):
        if not e.get("triggers_on_pull_request"):
            continue
        if e.get("runs_on") in (SELF_HOSTED_RUNS_ON, None):
            continue
        kind = str(e.get("kind") or "")
        if not kind or kind in ("github-hosted", "other"):
            vague.append(f"{_rel(e['workflow'])}::{e['job']} kind={kind!r}")
    assert vague == [], (
        "PR 触发的托管侧腿没有具名分类（`kind` 必须是 docker-build-leg / held_by_other_package / "
        "llm-eval-leg / not_migrated_this_round / pr-triggered-not-migrated_this_round 之一）：\n  · "
        + "\n  · ".join(vague)
    )


def test_the_one_unmigrated_pr_triggered_leg_is_explicitly_named():
    """本包唯一一条「命中迁移判据但未迁」的 PR 触发腿必须被**显式点名**（缺口不粉饰）。"""
    data = _ledger()
    named = [
        e for e in _entries(data)
        if e.get("kind") == "pr-triggered-not-migrated_this_round"
    ]
    assert named, (
        "没有任何 `pr-triggered-not-migrated_this_round` 条目 —— 要么缺口被悄悄补上了（那要同批改"
        "本判据与登记表），要么它被写成「有意保留」（不许）"
    )
    keys = {f"{_rel(e['workflow'])}::{e['job']}" for e in named}
    print(f"登记的未迁 PR 触发腿：{sorted(keys)}")


def test_setup_python_skip_condition_is_sourced_from_the_setup_script():
    """自托管跳过条件的**环境真值**必须仍由环境脚本提供（脚本与判据同源，不是两处各写一份）。"""
    assert SETUP_SCRIPT.exists(), f"缺环境可复现脚本 {SETUP_SCRIPT.relative_to(REPO)}"
    text = SETUP_SCRIPT.read_text(encoding="utf-8")
    for token in ("RUNNER_LABELS", "_shims", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "--check"):
        assert token in text, (
            f"环境脚本里找不到 {token!r} —— workflow 侧的环境假设（自托管标签 / shim / alternates / 只读自检）"
            "失去了可复现的真值源"
        )
    assert _self_hosted_label_default() == SELF_HOSTED_RUNS_ON[1], (
        "环境脚本的默认标签与 workflow 侧的 runs-on 取值不再同源"
    )


def _self_hosted_label_default() -> str:
    """从环境脚本现取 `RUNNER_LABELS` 的默认值（**不读工作树之外的东西**）。

    ⚠️ **不按 `#` 截断行尾**：`${VAR:-default}` 的默认值与 `}` 之间没有注释，先按 `#` 截断是
    **本地朴素 `#` 截断**（字符串里的 `#` 会吃掉行尾 ⇒ 假绿），判据 =
    `tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py`（本文件初版正是被它判红的）。
    """
    for line in SETUP_SCRIPT.read_text(encoding="utf-8").splitlines():
        if line.startswith("RUNNER_LABELS="):
            raw = line.split("=", 1)[1]
            raw = raw.split(":-", 1)[1] if ":-" in raw else raw
            return raw.split("}", 1)[0].strip().strip('"').strip("'")
    raise AssertionError("环境脚本里找不到 RUNNER_LABELS 的默认值")


# ── 注入式红证（**内存构造**的坏形态；每条都自证「坏形态 ≠ 基线读数」）──────────
def test_red_proof_unregistered_new_job_is_red():
    live = _live_jobs()
    live[(".github/workflows/pr-check.yml", "__new_job__")] = {
        "runs_on": "ubuntu-latest", "uses": None, "pr": True, "setup_python_if": [],
    }
    problems = _problems(_ledger(), live)
    assert any("未登记" in p and "__new_job__" in p for p in problems), problems


def test_red_proof_runs_on_drift_is_red():
    live = _live_jobs()
    key = (".github/workflows/pr-check.yml", "case-coverage-gate")
    live[key] = dict(live[key], runs_on="ubuntu-latest")
    problems = _problems(_ledger(), live)
    assert any("漂移" in p and "case-coverage-gate" in p for p in problems), problems


def test_red_proof_deleted_entry_is_red():
    data = copy.deepcopy(_ledger())
    data["jobs"] = [e for e in data["jobs"] if _entry_key(e) != (".github/workflows/pr-check.yml", "gitleaks-scan")]
    problems = _problems(data, _live_jobs())
    assert any("未登记" in p and "gitleaks-scan" in p for p in problems), problems


def test_red_proof_removed_setup_python_condition_is_red():
    live = _live_jobs()
    key = (".github/workflows/pr-check.yml", "llm-sink-ledger")
    live[key] = dict(live[key], setup_python_if=[None])
    problems = _problems(_ledger(), live)
    assert any("缺自托管跳过条件" in p and "llm-sink-ledger" in p for p in problems), problems


def test_red_proof_empty_ledger_is_red_not_green():
    """fail-closed：清空 `jobs` 必须是**非空违规**，不是「没东西可判 ⇒ 绿」。"""
    data = copy.deepcopy(_ledger())
    data["jobs"] = []
    with pytest.raises(AssertionError):
        _entries(data)
    live = _live_jobs()
    assert _problems({"jobs": [{"workflow": ".github/workflows/nope.yml", "job": "x", "runs_on": "ubuntu-latest"}]}, live)


def test_red_proof_comment_only_edit_is_not_red():
    """对照读数：**只改注释**不得判红（否则判据会对着噪声喊）。"""
    baseline = _problems(_ledger(), _live_jobs())
    assert baseline == []
    path = WORKFLOWS / "pr-check.yml"
    text = path.read_text(encoding="utf-8")
    mutated = text.replace("name: PR Check", "name: PR Check  # 只改注释", 1)
    assert mutated != text, "变异没生效（自证失败）⇒ 这条对照读数无意义"
    assert _problems(_ledger(), _live_jobs()) == [], "只改注释却判红了 —— 判据读的不是结构"


# =============================================================================
# 预置工作区的**健康判定 + 自愈**（集成侧两轮真机读数的加固项）
#
# 病（实测）：`actions/checkout` 用 `--depth=1` fetch ⇒ 预置仓库**必然** shallow 化
#   （`.git` 仍 293M、服务端建的分支照样 fetch ✅ ⇒ **shallow 不是病**，当成病会
#   **每个 job 之后都假红 + 白重建**）；真正的坏态是 `HEAD`/refs 指向**对象已不存在**的提交
#   （实测退化成 `.git` 293M → 2.6M、`git fsck` 报 `invalid sha1 pointer`）——
#   到了这个状态，下一次 checkout 又退回真·批量拉取 ⇒ early EOF 卡死。
#
# 判据（`0` = 健康）：
#   ① `.git` 在 ② `HEAD` 可解析 ③ `HEAD^{commit}` 对象真的存在 ④ `git fsck` 无 `error`
#   ⇒ 不满足就**重建**（`rm -rf` + `git clone --no-checkout <本机主仓>`，实测 293 MB / 0.28 s）。
#
# 三态 + 一条对照读数（全部用**真 git 夹具**跑脚本本体，不 mock —— 判据读的就是脚本的真实行为）：
#   态 1 `--depth=1` 预置（shallow）⇒ **健康、不重建**（这条是**防假红**的反向判据）
#   态 2 删掉 `HEAD` 指向的对象（复现 `invalid sha1 pointer`）⇒ 判坏 + 重建 + 复检通过
#   态 3 健康仓库再跑一次 ⇒ 不重建（幂等）
#   对照 安装档源码里「不健康就重建」的分支**必须**呼叫复检（删掉复检 ⇒ 红）
# =============================================================================
_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
}
_FIXTURE_REPO = "zhaokai-mgzn/migao"


def _git(args: list[str], cwd: Path, check: bool = True):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=check,
        capture_output=True, text=True,
        env={**os.environ, **_GIT_ENV},
    )


def _run_setup(*args: str, runner_dir: Path, mirror: Path):
    return subprocess.run(
        ["bash", str(SETUP_SCRIPT), *args],
        cwd=str(REPO), capture_output=True, text=True,
        env={**os.environ, "RUNNER_DIR": str(runner_dir), "MIRROR_REPO": str(mirror),
             "REPO": _FIXTURE_REPO, "HOME": str(runner_dir)},
    )


def _seed_mirror(root: Path) -> Path:
    """最小「本机镜像仓库」（有 2 个提交，够复现 shallow / 悬空 HEAD 两态）。"""
    mirror = root / "mirror"
    mirror.mkdir(parents=True)
    _git(["init", "-q", "."], mirror)
    (mirror / "a.txt").write_text("a\n", encoding="utf-8")
    _git(["add", "a.txt"], mirror)
    _git(["commit", "-q", "-m", "c1"], mirror)
    (mirror / "b.bin").write_bytes(b"\x00" * 128)
    _git(["add", "b.bin"], mirror)
    _git(["commit", "-q", "-m", "c2"], mirror)
    return mirror


def _workdir(runner_dir: Path) -> Path:
    repo = _FIXTURE_REPO.split("/")[1]
    return runner_dir / "_work" / repo / repo


def test_workdir_predicate_treats_shallow_as_healthy(tmp_path):
    """态 1（**防假红**）：`actions/checkout` 留下的 shallow 仓库必须判**健康**、不被重建。"""
    mirror = _seed_mirror(tmp_path)
    runner_dir = tmp_path / "runner"
    wd = _workdir(runner_dir)
    wd.parent.mkdir(parents=True)
    # ⚠️ 必须走 `file://`：**本地路径克隆会忽略 `--depth`**（Git 明确警告并做全量拷贝）
    # ⇒ 用本地路径造的「shallow 夹具」其实不 shallow，红证会变成假绿。
    _git(["clone", "-q", "--depth=1", "--no-checkout", f"file://{mirror}", str(wd)], tmp_path)
    assert (wd / ".git" / "shallow").exists(), "夹具自证失败：没有造出 shallow 仓库"
    r = _run_setup("--reseed-workdir", runner_dir=runner_dir, mirror=mirror)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "健康（未重建）" in r.stdout, r.stdout
    assert "重建完成" not in r.stdout, "shallow 被当成病 ⇒ 每个 job 之后都会假红 + 白重建"


def test_workdir_predicate_detects_missing_head_object_and_selfheals(tmp_path):
    """态 2：`HEAD` 指向的对象被删（实测形态 = `invalid sha1 pointer`）⇒ 判坏 + 重建 + 复检。"""
    mirror = _seed_mirror(tmp_path)
    runner_dir = tmp_path / "runner"
    wd = _workdir(runner_dir)
    wd.parent.mkdir(parents=True)
    _git(["clone", "-q", "--no-checkout", "--", str(mirror), str(wd)], tmp_path)
    head = _git(["rev-parse", "HEAD"], wd).stdout.strip()
    obj = wd / ".git" / "objects" / head[:2] / head[2:]
    # 夹具自证：对象真的**是散对象**（否则删不到，红证会变成假绿）
    assert obj.exists(), f"夹具自证失败：HEAD 对象不在散对象目录里（{obj}）"
    obj.unlink()
    assert _git(["cat-file", "-e", "HEAD^{commit}"], wd, check=False).returncode != 0

    r = _run_setup("--reseed-workdir", runner_dir=runner_dir, mirror=mirror)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "不健康" in r.stdout and "重建完成并复检通过" in r.stdout, r.stdout
    assert _git(["cat-file", "-e", "HEAD^{commit}"], wd, check=False).returncode == 0, "重建后 HEAD^{commit} 仍取不到"
    assert _git(["fsck", "--no-progress"], wd, check=False).stdout.find("error") == -1


def test_workdir_reseed_is_idempotent_on_healthy_repo(tmp_path):
    """态 3：健康仓库再跑一次 ⇒ **不重建**（幂等；安装档每次运行都会走这条）。"""
    mirror = _seed_mirror(tmp_path)
    runner_dir = tmp_path / "runner"
    wd = _workdir(runner_dir)
    wd.parent.mkdir(parents=True)
    _git(["clone", "-q", "--no-checkout", "--", str(mirror), str(wd)], tmp_path)
    first = _run_setup("--reseed-workdir", runner_dir=runner_dir, mirror=mirror)
    second = _run_setup("--reseed-workdir", runner_dir=runner_dir, mirror=mirror)
    assert first.returncode == 0 and second.returncode == 0, first.stdout + second.stdout
    assert "健康（未重建）" in second.stdout, second.stdout
    assert "重建完成" not in second.stdout


def test_install_path_checks_workdir_health_and_names_the_selfheal_command(tmp_path):
    """对照读数：安装档源码里「不健康 ⇒ 重建 ⇒ **复检**」这条链必须在位（删掉复检即红）。"""
    text = SETUP_SCRIPT.read_text(encoding="utf-8")
    for token in ("--reseed-workdir", "workdir_problem", "cat-file -e 'HEAD^{commit}'",
                  "重建完成并复检通过", "reseed_workdir"):
        assert token in text, f"环境脚本里找不到 {token!r}（自愈链断了一环）"
