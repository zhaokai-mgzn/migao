# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 `.github/cases/misc.yml` 的 MC-012 登记与同目录 `test_merge_gate.py` 的同款声明。
#   本 PR 不新建用例族：塞进行为用例库会污染覆盖矩阵。）
"""`scripts/merge_gate.py --required-diff` 的 **job 级 `if:` 解析 + 读数来源**（关联 #5269）。

## 病根（实测，可复算）

「裸判据（会判红但不拦合并）」清单按**文件级** `on:` 收 job、**不解析 job 级 `if:`**
⇒ 把**根本不在 PR 事件上创建**的 job 也算了进去。实测（当前 main 的 workflows）：
`automerge.yml:detect-dangling-prs` 的 `if:` 逐字是
`github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'`
⇒ 裸判据 **15** 条 / PR 事件会跑的 job **30** 条（多报 1 条；修后 14 / 29）。
第二个坑：它读的是**工作区本地文件**（不是 git 对象）⇒ 主工作区常年落后 main 几十个提交
⇒ 同一命令给出**过期清单**且**无任何提示**。

## 四条判据 ↔ 本文件（每条都配「注入后必红」的对照）

| # | 判据 | 红证（`TestRedProofs…`；注入点 = **脚本源码文本**，避开「判据被自己的文案喂绿」） |
|---|---|---|
| 1 | job 级 `if:` **可证明排除** `pull_request*` ⇒ 不计入 | 打掉 `condition = job.get("if")` ⇒ `Detect dangling PRs` 重新出现在裸判据清单里 |
| 2 | **负例（防修过头）**：**没有**限制性 `if:`（或 `if:` 在 PR 事件下为真）⇒ **必须仍然计入** | `if all(value is False …)` → `if True:` ⇒ `E2E quality gate` / `Enable auto-merge` 从清单里消失 |
| 3 | 不可判的 `if:` **保守计入** + 登记「已知不覆盖」 | 把 `uncovered` 改成 `excluded` ⇒ 不可判的 job 被免计（判据 2 的负例同样必红） |
| 4 | 输出必须**自报读数来源**（绝对路径 + git ref） | `if source:` → `if False:` ⇒ 该行消失（**负控**：脚本文案里本来就有「读数来源」字样 ⇒ 只有**行为面**判据有判别力） |

## 保守边界（有意为之，不是遗漏）

只解析 `github.event_name ==/!= '<字面量>'`（字面量在左亦可）的 `!` / `&&` / `||` / 括号组合，
按三值（True/False/未知）Kleene 逻辑求值；**只有每个 PR 触发事件下都确定取 False 才免计**。
`contains(...)` / `github.event.action` 等其它原子、非字符串 `if:`、解析不了的表达式一律计入
⇒ 清单**可能仍多报**（宁多勿少：**少报**才是危险的）。
「声明了哪些 PR 触发」取自**文件级 `on:`**（workflow 只声明 `on: pull_request` 时
`github.event_name` 只可能是它）⇒ `if: github.event_name != 'pull_request'` 属**可证明排除**
（判据 1 的「明确排除」形态），而 `if: github.event_name == 'pull_request'` 与
`github.event.pull_request.*` 一律计入（判据 2）。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "merge_gate.py"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

DANGLING = "Detect dangling PRs (open >N min, no red, required not met)"
DANGLING_WHERE = "automerge.yml:detect-dangling-prs"
DANGLING_IF = "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
DRIFT = "Drift Audit (真相源契约)"
# 判据 2 的真实锚点（**必须保持计入**）：`pr-check.yml` 里 `if: github.event_name == 'pull_request'` 的 job
PR_ONLY_JOB = "E2E quality gate"
# 判据 3 的真实锚点（不可判 ⇒ 保守计入）：`pr-issue-link.yml` 的 `github.event.pull_request.user.type != 'Bot'`
UNCOVERED_JOB = "Check Closes"


def _load_module(path=SCRIPT):
    """按路径加载被测脚本（`scripts/` 不是包）；`path` 也可以是**变异后的副本**。"""
    spec = importlib.util.spec_from_file_location(f"merge_gate_under_test_{abs(hash(str(path)))}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def mutate(source: str, old: str, new: str) -> str:
    """单点源码变异：锚点必须**恰好出现一次**（否则变异不是单点的，红证会失真）。"""
    count = source.count(old)
    assert count == 1, f"变异锚点出现 {count} 次（要求恰好 1 次，脚本已漂移）：{old!r}"
    return source.replace(old, new)


def mutated_script(tmp_path, old, new) -> Path:
    """把真脚本变异后落成临时副本（注入点是**真源码文本**，不是断言自己的文案）。"""
    path = tmp_path / "merge_gate_mutated.py"
    path.write_text(mutate(SCRIPT.read_text(encoding="utf-8"), old, new), encoding="utf-8")
    return path


# ── 夹具（workflow 文本 + gh 替身）────────────────────────────────────────────

def _job(job_id, if_expr=None, name=None):
    body = f"  {job_id}:\n    name: {name or job_id}\n"
    if if_expr is not None:
        body += f"    if: {if_expr}\n"
    return body + "    runs-on: ubuntu-latest\n"


def _fixture_dir(tmp_path, jobs_yaml, pr_trigger="pull_request_target"):
    """一份最小 workflow：`on:` 含 `pr_trigger`（默认 pull_request_target）+ schedule。"""
    root = tmp_path / "wf"
    root.mkdir(exist_ok=True)
    (root / "fixture.yml").write_text(
        "name: fixture-5269\n"
        f"on:\n  {pr_trigger}:\n  schedule:\n    - cron: '0 0 * * *'\n"
        f"jobs:\n{jobs_yaml}",
        encoding="utf-8")
    return root


FAKE_GH = '''\
#!/usr/bin/env python3
"""gh 替身：只覆盖 `--required-diff` 用到的两条只读调用（本文件不测写操作）。"""
import json, os, sys

argv = sys.argv[1:]
if argv[:2] == ["repo", "view"]:
    sys.stdout.write(os.environ.get("FAKE_GH_REPO", "zhaokai-mgzn/migao") + "\\n")
    sys.exit(0)
if argv[:1] == ["api"] and "protection" in " ".join(argv):
    sys.stdout.write(os.environ["FAKE_GH_PROTECTION"])
    sys.exit(0)
sys.stderr.write("fake-gh: 未预期的调用 " + " ".join(argv) + "\\n")
sys.exit(2)
'''


@pytest.fixture
def fake_gh(tmp_path):
    path = tmp_path / "fake-gh"
    path.write_text(FAKE_GH, encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def _cli(fake_gh, protection, *args, workflows_dir=WORKFLOWS_DIR, script=SCRIPT, gh_bin=None):
    """跑一次脚本（只读路径）；`protection` = 分支保护 required 名字列表。

    `--workflows-dir` **总是显式传**：变异副本落在 tmp_path，默认值（相对脚本位置）会指错目录。
    """
    argv = [sys.executable, str(script), "--required-diff", *args,
            "--workflows-dir", str(workflows_dir)]
    env = {**os.environ,
           "MG_GH_BIN": gh_bin if gh_bin is not None else fake_gh,
           "FAKE_GH_PROTECTION": json.dumps({"contexts": sorted(protection)})}
    return subprocess.run(argv, capture_output=True, text=True, env=env)


def _real_repo_protection(mod):
    """`required` = 「真实 PR job 集合 − Drift Audit」⇒ 差集**恰好** 1 条，裸判据清单非空（可判红）。

    **不写死数字**（仓库会演化）：全部由被测脚本自己的扫描反推。
    """
    return sorted(set(mod.scan_pr_jobs(WORKFLOWS_DIR).jobs) - {DRIFT})


# ── 判据 1：job 级 `if:` 可证明排除 `pull_request*` ⇒ 不计入 ─────────────────────

def test_criterion1_schedule_only_job_is_excluded(tmp_path):
    """逐字复刻 `automerge.yml:detect-dangling-prs` 的 `if:` ⇒ 判「不在 PR 事件上创建」。"""
    mod = _load_module()
    root = _fixture_dir(tmp_path, _job("detect-dangling-prs", DANGLING_IF, name=DANGLING))
    scan = mod.scan_pr_jobs(root)
    assert DANGLING not in scan.jobs
    assert scan.excluded == ("fixture.yml:detect-dangling-prs",)
    assert scan.uncovered == ()


def test_criterion1_real_repo_dangling_prs_job_is_not_counted(tmp_path):
    """真实锚点：该 job **仍在** `automerge.yml` 里声明（不是被删了），但**不计入** PR job 集合。"""
    mod = _load_module()
    declared = yaml.safe_load((WORKFLOWS_DIR / "automerge.yml").read_text(encoding="utf-8"))
    job = declared["jobs"]["detect-dangling-prs"]
    assert job["if"].strip() == DANGLING_IF, "被测对象的 if: 已漂移，判据需同步"
    scan = mod.scan_pr_jobs(WORKFLOWS_DIR)
    assert DANGLING_WHERE in scan.excluded
    assert DANGLING not in scan.jobs
    assert DANGLING not in mod.job_names_on_pull_requests(WORKFLOWS_DIR)


def test_criterion1_cli_bare_list_has_no_dangling_prs(fake_gh):
    """CLI 面：裸判据清单**不含**它（`--required` 是 `--required-diff` 的无歧义前缀）。"""
    mod = _load_module()
    proc = _cli(fake_gh, _real_repo_protection(mod), "--required")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert DRIFT in proc.stdout
    assert DANGLING not in proc.stdout, proc.stdout
    assert f"排除 {DANGLING_WHERE}" in proc.stdout, proc.stdout


def test_criterion1_cli_evidence_matches_the_scan(fake_gh):
    """证据行的「PR 事件会跑的 job N 条」必须来自**同一次扫描**（不写死数字）。"""
    mod = _load_module()
    scan = mod.scan_pr_jobs(WORKFLOWS_DIR)
    proc = _cli(fake_gh, _real_repo_protection(mod))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert f"PR 事件会跑的 job {len(scan.jobs)} 条" in proc.stdout, proc.stdout
    assert f"差集 {len(scan.jobs) - len(_real_repo_protection(mod))} 条" in proc.stdout, proc.stdout
    assert f"job 级 if: 排除 {len(scan.excluded)} 条" in proc.stdout, proc.stdout
    assert set(scan.jobs).isdisjoint(scan.excluded), "排除集与计入集必须互斥"


def test_criterion1_only_provably_excluded_forms_are_exempted(tmp_path):
    """「明确排除」的另一种写法：`!= 'pull_request'` 且 workflow 只声明 `on: pull_request`。

    此时 `github.event_name` **只可能**是 `pull_request` ⇒ 该 job 永远不会被创建 ⇒ 属可证明排除
    （判据 1）。反向形态（`== 'pull_request'`）见判据 2 —— **一律计入**。
    """
    mod = _load_module()
    root = _fixture_dir(tmp_path, _job("never", "github.event_name != 'pull_request'"),
                        pr_trigger="pull_request")
    scan = mod.scan_pr_jobs(root)
    assert scan.jobs == {}
    assert scan.excluded == ("fixture.yml:never",)


# ── 判据 2：负例（防修过头）—— 无限制性 if: 的 job **必须仍然计入** ────────────────

def test_criterion2_job_without_if_is_counted(tmp_path):
    mod = _load_module()
    scan = mod.scan_pr_jobs(_fixture_dir(tmp_path, _job("plain")))
    assert list(scan.jobs) == ["plain"]
    assert scan.jobs["plain"] == "fixture.yml:plain"
    assert scan.excluded == ()


def test_criterion2_job_requiring_pull_request_event_is_counted(tmp_path):
    """`if: github.event_name == 'pull_request'` **含** `pull_request` ⇒ 必须计入。"""
    mod = _load_module()
    root = _fixture_dir(tmp_path, _job("pr-only", "github.event_name == 'pull_request'"),
                        pr_trigger="pull_request")
    scan = mod.scan_pr_jobs(root)
    assert list(scan.jobs) == ["pr-only"]
    assert scan.excluded == ()


def test_criterion2_job_with_pull_request_context_atom_is_counted(tmp_path):
    """`github.event.pull_request.*` 是不可判原子 ⇒ 保守计入（**不得**因不可判而免计）。"""
    mod = _load_module()
    root = _fixture_dir(tmp_path, _job("human-only", "github.event.pull_request.user.type != 'Bot'"))
    scan = mod.scan_pr_jobs(root)
    assert list(scan.jobs) == ["human-only"]
    assert scan.uncovered == ("fixture.yml:human-only",)


def test_criterion2_real_repo_pr_jobs_are_still_counted():
    """真实锚点：`pr-check.yml` 的 required 族与 `automerge.yml` 的 arm 族**一个都不能少**。

    这四类正是「修过头」会误删的对象：① `== 'pull_request'`（判据 2 正例）；
    ② `github.event.pull_request.*` / `failure()` 等不可判原子；③ 无 `if:`；④ 纯 `||` 组合。
    """
    mod = _load_module()
    scan = mod.scan_pr_jobs(WORKFLOWS_DIR)
    for name in (PR_ONLY_JOB, "QA Growth Gate", "Enable auto-merge",
                 "Enable auto-merge (bot, safe classes only)", UNCOVERED_JOB,
                 "Reconcile and dispatch missing deploys", DRIFT):
        assert name in scan.jobs, f"{name} 被误判为「不在 PR 事件上创建」"
    # `--file-level on:` 闸门本身没被改坏：不声明 PR 触发的 workflow 的 job 一律不收
    assert PR_ONLY_JOB in scan.jobs
    for where in scan.excluded:      # 排除的必须是**真实存在**的 job（不许排除幽灵）
        filename, job_id = where.split(":")
        declared = yaml.safe_load((WORKFLOWS_DIR / filename).read_text(encoding="utf-8"))
        assert job_id in declared["jobs"], f"排除了一条不存在的 job：{where}"


def test_criterion2_workflow_without_pr_trigger_is_not_scanned(tmp_path):
    """文件级 `on:` 闸门（既有语义，未改）：不声明 PR 触发 ⇒ 整份 workflow 的 job 都不收。"""
    mod = _load_module()
    root = tmp_path / "wf"
    root.mkdir()
    (root / "scheduled.yml").write_text(
        "name: scheduled\non:\n  schedule:\n    - cron: '0 0 * * *'\njobs:\n"
        + _job("nightly"), encoding="utf-8")
    scan = mod.scan_pr_jobs(root)
    assert scan.jobs == {}
    assert scan.excluded == ()


# ── 判据 3：不可判 ⇒ 保守计入 + 显式登记「已知不覆盖」──────────────────────────

def test_criterion3_unknown_atom_if_is_counted_and_registered(tmp_path):
    """`contains(...)` 不在解析范围内 ⇒ 计入 **且**登记为 `uncovered`（不假装判了）。"""
    mod = _load_module()
    root = _fixture_dir(tmp_path, _job("maybe", "contains(github.event_name, 'pull')"))
    scan = mod.scan_pr_jobs(root)
    assert list(scan.jobs) == ["maybe"]
    assert scan.uncovered == ("fixture.yml:maybe",)


def test_criterion3_unparsable_if_is_counted(tmp_path):
    """结构解析不了的形态（括号不配对 / 悬空运算符）⇒ 计入（走 `uncovered`，**不是**免计、也不是 3）。"""
    mod = _load_module()
    root = _fixture_dir(tmp_path,
                        _job("unbalanced", "(github.event_name == 'schedule'")
                        + _job("dangling", "github.event_name == 'schedule' ||"))
    scan = mod.scan_pr_jobs(root)
    assert set(scan.jobs) == {"unbalanced", "dangling"}
    assert set(scan.uncovered) == {"fixture.yml:unbalanced", "fixture.yml:dangling"}
    assert scan.excluded == ()


def test_criterion3_mixed_expression_with_function_call_is_counted(tmp_path):
    """`github.event_name == 'schedule' && !contains(…)` ⇒ **必须计入**。

    函数调用 `contains(...)` 的括号不在覆盖范围内 ⇒ 整个表达式不可判 ⇒ 保守计入
    （哪怕前半段可判 `False`）。这正是「只对**可证明排除**的免计」的反面教材。
    """
    mod = _load_module()
    expr = "github.event_name == 'schedule' && !contains(github.event, 'pull_request')"
    scan = mod.scan_pr_jobs(_fixture_dir(tmp_path, _job("guarded", expr)))
    assert list(scan.jobs) == ["guarded"]
    assert scan.uncovered == ("fixture.yml:guarded",)


def test_criterion3_non_string_if_is_counted(tmp_path):
    """非字符串 `if:`（YAML 布尔）⇒ 计入（登记为不可判）。"""
    mod = _load_module()
    scan = mod.scan_pr_jobs(_fixture_dir(
        tmp_path, _job("plain") + _job("boolish", "true", name="bool-if")))
    assert set(scan.jobs) == {"plain", "bool-if"}
    assert scan.uncovered == ("fixture.yml:boolish",)


def test_criterion3_precedence_is_not_flattened(tmp_path):
    """`A || B && C` 不得被当成同优先级左结合 —— 那会把**实际会跑**的 job 判成排除（少报）。

    三值下 `A=True(可判) && C=False(可判)`：正确 `A || (B && C)` = True；左结合 `(A || B) && C` = False。
    """
    mod = _load_module()
    expr = ("github.event_name == 'pull_request' || github.actor == 'x' "
            "&& github.event_name == 'schedule'")
    root = _fixture_dir(tmp_path, _job("keepme", expr), pr_trigger="pull_request")
    scan = mod.scan_pr_jobs(root)
    assert list(scan.jobs) == ["keepme"]
    assert scan.excluded == ()


def test_criterion3_known_uncovered_is_registered_in_output(fake_gh):
    """登记必须**可见**（输出里的「已知不覆盖」行 + 不可判计数），否则保守口径是隐形的。"""
    mod = _load_module()
    scan = mod.scan_pr_jobs(WORKFLOWS_DIR)
    proc = _cli(fake_gh, _real_repo_protection(mod))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "已知不覆盖" in proc.stdout and "保守计入" in proc.stdout, proc.stdout
    assert mod.KNOWN_UNCOVERED_IF in proc.stdout, proc.stdout
    assert f"不可判 {len(scan.uncovered)} 条" in proc.stdout, proc.stdout
    assert set(scan.uncovered).isdisjoint(scan.excluded)


# ── 判据 4：输出**自报读数来源**（陈旧工作区读数可见）──────────────────────────

def test_criterion4_reports_absolute_path_and_git_ref(fake_gh):
    mod = _load_module()
    source = mod.describe_reading_source(WORKFLOWS_DIR)
    assert str(WORKFLOWS_DIR.resolve()) in source
    assert "git HEAD" in source and "origin/main" in source
    proc = _cli(fake_gh, _real_repo_protection(mod))
    assert "读数来源：" in proc.stdout, proc.stdout
    assert str(WORKFLOWS_DIR.resolve()) in proc.stdout, proc.stdout


def test_criterion4_stale_worktree_is_visible(tmp_path):
    """挂在**落后 origin/main** 的检出上 ⇒ 该行必须点明「落后 N 个提交 ⇒ 清单可能过期」。"""
    mod = _load_module()
    repo = tmp_path / "stale"
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "fixture.yml").write_text("name: x\non:\n  pull_request:\njobs:\n" + _job("a"),
                                           encoding="utf-8")

    def git(*args):
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        assert proc.returncode == 0, f"git {args} 失败：{proc.stderr}"

    git("init", "-q")
    git("config", "user.email", "fixture@example.com")
    git("config", "user.name", "fixture")
    git("add", "-A")
    git("commit", "-qm", "first")
    old = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    (workflows / "fixture.yml").write_text("name: x\non:\n  pull_request:\njobs:\n"
                                           + _job("a") + _job("b"), encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "second")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    git("update-ref", "--no-deref", "HEAD", old)      # HEAD 回到第一个提交 ⇒ 落后 origin/main 1 个

    source = mod.describe_reading_source(workflows)
    assert "落后 origin/main 1 个提交" in source, source
    assert "可能过期" in source, source


def test_criterion4_non_git_dir_says_unverifiable(tmp_path, fake_gh):
    """非 git 检出（如 `git archive` 解出来的临时目录）⇒ **如实说无法核对**，不装作同步。"""
    mod = _load_module()
    root = _fixture_dir(tmp_path, _job("a"))
    source = mod.describe_reading_source(root)
    assert "非 git 检出" in source and "无法核对" in source, source
    proc = _cli(fake_gh, _real_repo_protection(mod), workflows_dir=root)
    assert "读数来源：" in proc.stdout and "非 git 检出" in proc.stdout, proc.stdout


def test_criterion4_missing_workflows_dir_still_reports_source(fake_gh):
    """读不到工作流（退 3）时**仍要**打印读数来源 —— 否则「读的是哪份文件」无从追溯。"""
    mod = _load_module()
    proc = _cli(fake_gh, _real_repo_protection(mod), workflows_dir="/nonexistent/5269-workflows")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "读数来源：" in proc.stdout and "/nonexistent/5269-workflows" in proc.stdout, proc.stdout


def test_criterion4_without_git_degrades_gracefully(monkeypatch):
    """环境里没有 `git` ⇒ 该行**降级为「读不到 git」**且不抛异常（不是 3、更不是静默无来源）。"""
    mod = _load_module()
    monkeypatch.setenv("PATH", "")
    source = mod.describe_reading_source(WORKFLOWS_DIR)
    assert "读不到 git" in source and str(WORKFLOWS_DIR.resolve()) in source, source


# ── 判据 1~4 的注入式红证（对**真源码**单点变异后重跑）──────────────────────────

class TestRedProofs:
    """把某一条判据改坏 ⇒ 对应红证**必须**变红（否则那条红证 = 空断言）。"""

    def test_c1_red_proof_ignoring_job_if_brings_dangling_prs_back(self, tmp_path, fake_gh):
        """判据 1 红证：不解析 job 级 `if:` ⇒ `Detect dangling PRs` 重新出现在裸判据清单里。"""
        mutated = mutated_script(tmp_path, 'condition = job.get("if")', "condition = None")
        mod = _load_module(mutated)
        assert DANGLING in mod.scan_pr_jobs(WORKFLOWS_DIR).jobs          # 变异后：被算进去了
        proc = _cli(fake_gh, _real_repo_protection(_load_module()), script=mutated)
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert DANGLING in proc.stdout, proc.stdout                       # 清单多报 = 判据 1 变红

    def test_c2_red_proof_exempting_every_if_drops_real_pr_jobs(self, tmp_path):
        """判据 2 红证：放宽成「任何可判 `if:` 都不计」⇒ 真实 PR job 从清单里消失（修过头）。"""
        mutated = mutated_script(tmp_path, "if all(value is False for value in values):", "if True:")
        jobs = _load_module(mutated).scan_pr_jobs(WORKFLOWS_DIR).jobs
        assert PR_ONLY_JOB not in jobs, "修过头后 E2E quality gate 仍在 ⇒ 该红证没有判别力"
        assert "QA Growth Gate" not in jobs
        # 含 `!contains(…)` 的那两条**解析不了**，走的是 `except _Unparsable` 支 ⇒ 不受本次变异影响
        # （证明这是**单点**变异：只打掉「解析成功」这一支，不是把整个函数打坏）
        assert "Enable auto-merge" in jobs

    def test_c3_red_proof_exempting_uncovered_drops_conservative_jobs(self, tmp_path):
        """判据 3 红证：把不可判也免计 ⇒ ① 不可判原子（`!= 'Bot'`）② 结构解析不了 都被误免。"""
        by_atom = mutated_script(
            tmp_path,
            'return "uncovered" if any(value is None for value in values) else "runs"',
            'return "excluded" if any(value is None for value in values) else "runs"')
        jobs = _load_module(by_atom).scan_pr_jobs(WORKFLOWS_DIR).jobs
        assert UNCOVERED_JOB not in jobs, "不可判 job 未被免计 ⇒ 该红证没有判别力"

        unparsable = tmp_path / "unparsable.py"
        unparsable.write_text(mutate(SCRIPT.read_text(encoding="utf-8"),
                                     '    except _Unparsable:\n        return "uncovered"',
                                     '    except _Unparsable:\n        return "excluded"'),
                              encoding="utf-8")
        root = _fixture_dir(tmp_path, _job("dangling", "github.event_name == 'schedule' ||"))
        scan = _load_module(unparsable).scan_pr_jobs(root)
        assert scan.jobs == {}, "解析不了的形态未被免计 ⇒ 该红证没有判别力"

    def test_c4_red_proof_removing_source_line_is_red(self, tmp_path, fake_gh):
        """判据 4 红证：去掉该行 ⇒ 输出里没有读数来源（**行为面**必红）。"""
        mutated = mutated_script(tmp_path, "if source:", "if False:")
        proc = _cli(fake_gh, _real_repo_protection(_load_module()), script=mutated)
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert "读数来源：" not in proc.stdout, proc.stdout

    def test_c4_negative_control_text_check_would_be_fed_green(self, tmp_path, fake_gh):
        """**负控**：脚本源码里本来就有「读数来源」字样 ⇒ 只有 stdout（行为面）判据有判别力。

        若把判据 4 写成「源码里含『读数来源』」这类**文案面**检查，去掉真行为后它照样绿 ——
        本测试把这两种口径的差异钉死。
        """
        mutated = mutated_script(tmp_path, "if source:", "if False:")
        proc = _cli(fake_gh, _real_repo_protection(_load_module()), script=mutated)
        assert "读数来源" in mutated.read_text(encoding="utf-8")     # 文案面：仍在（绿）
        assert "读数来源：" not in proc.stdout                        # 行为面：已红