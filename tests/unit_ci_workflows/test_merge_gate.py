# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 —— 见
#   tests/unit_ci_workflows/test_drift_audit_contract.py 的同款声明与 `.github/cases/misc.yml`
#   MC-012「CI workflow 结构由 pytest 单测验证」的登记。本 PR 不新建用例族：塞进行为用例库会污染覆盖矩阵。）
"""`scripts/merge_gate.py` —— 关联 #4248「报告型判据判红不拦合并」的元判据 + 合并闸门判定。

守的地雷（**判定链全程夹具驱动，不 mock 被测函数本身**）：

**根因**：auto-merge 的判定依据是**分支保护里的 required checks**；`Drift Audit` / `Case Trust Gate` 等
**报告型**判据不在 required 集合 ⇒ **判红不拦合并**，而 PR 页面上红/绿与 required 判据长得一样，
极易被读成「绿 = 可以合」。实测形态：关联 #4214（`Drift Audit` fail 且该 PR 仍 MERGED）、
#4266 / #4267 / #4271 同款复发。本单是**元层面**的判据（不是"少了一道检查"，而是"红了也照合"）。

用例分组（每组都要有**判别力**，不是"跑通就算"）：

① **裸判据红必判 1**：`Drift Audit` 红 + 其余全绿 + 该 job **不在** required ⇒ 1（当前形态下必红）；
② **反向 A**：报告型判据**全绿** ⇒ 0（不得恒红 —— 恒红的判据 = 空判据）；
③ **反向 B**：红的 job **在** required 里（GitHub 自己会拦）⇒ 0 且输出说明「已被 required 拦」
   （**不得**重复报警）；有 required 红时另有裸判据红 ⇒ 同样 0（合并已被拦住，裸判据只作信息列出）；
④ **三态**：`gh` 不可用 / API 报错 / 读不到 required ⇒ **3，不得 fail-open 成 0**
   （「看不了」不得当「没问题」，与 `red_proof.py` / `resolve_stale_bot_threads.py` 同口径）；
⑤ **元判据 `--required-diff`**：差集非空 ⇒ 1、为空 ⇒ 0、读不到分支保护或工作流 ⇒ 3；
⑥ **报告型清单可自证、不硬编码**：判定由「不在 required 里的红 check」**反推** ⇒ 夹具里出现一个
   仓库中**不存在**的新 job 名（红且不在 required）也必须被判成裸判据 —— 若有人写死成
   `("Drift Audit", "Case Trust Gate")` 两条，这条必红（防清单腐烂）；
⑦ **写操作边界**：默认 **dry-run 零写操作**；`--apply-label` 只在**命中 + PR 仍 OPEN** 时落闸，
   且**默认同时 disarm**（`gh pr merge --disable-auto`，仅在 auto-merge **已 arm** 时调用）——
   实测：已 arm 的 auto-merge **不因标签而停**（关联 #4271：标签 07:03:19Z 晚于
   `autoMergeRequest.enabledAt` 07:03:18Z、**合并 07:07:22Z**；关联 #4266：标签 06:57:32Z、
   **合并 07:00:30Z**）⇒ 只打标签等于**没拦住**（关联 #4334 的裁定）。
   逃生口 `--no-disarm-auto` 只打标签且**必须明写**它拦不住；已 MERGED 的 PR **绝不**写。

夹具：`gh` 用**替身可执行文件**（`MG_GH_BIN`，沿用 `resolve_stale_bot_threads.py` 的 `SBT_GH_BIN`
先例）注入 —— 不 mock 网络，而是把 CLI 边界当注入点，故「gh 缺失 ⇒ 3」「API 报错 ⇒ 3」
「写操作到底发出去了没」都在同一条真实进程链上被验证。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "merge_gate.py"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# 真实的 required 集合（2026-09-18 用 `gh api …/protection/required_status_checks` 只读读回；
# 只作夹具基线的**子集**用，不在断言里写死全集 —— 分支保护一变，写死全集的断言就会腐烂）。
REQUIRED_SAMPLE = [
    "admin-api unit tests",
    "ai-agent-service unit tests",
    "admin-web typecheck + unit tests",
    "mini-app typecheck + unit tests",
    "QA Growth Gate",
    "ci workflow helper unit tests",
    "Secret Scan (gitleaks)",
    "Danger Scan (破坏性变更检测)",
    "Case Trust Gate (断言可信度)",
    "Case Coverage Gate",
    "Case Contract (truths_ref)",
    "Block .env files (except .env.example)",
]

DRIFT = "Drift Audit (真相源契约)"


def _load_module():
    """按路径加载被测脚本（`scripts/` 不是包）。"""
    spec = importlib.util.spec_from_file_location("merge_gate", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 夹具构造（纯数据，供纯函数直调）────────────────────────────────────────────

def _check(name, bucket="pass"):
    state = {"pass": "SUCCESS", "fail": "FAILURE", "pending": "PENDING", "skipping": "SKIPPED"}[bucket]
    return {"name": name, "state": state, "bucket": bucket}


def _checks(bare_red=(), required_red=(), extra_green=()):
    """一份 checks 读数：required 全绿 + 指定裸判据红 / required 红。"""
    rows = [_check(n) for n in REQUIRED_SAMPLE]
    rows += [_check(n) for n in extra_green]
    rows += [_check(n, "fail") for n in bare_red]
    rows += [_check(n, "fail") for n in required_red]
    return rows


def _pr(state="OPEN", draft=False, mergeable="MERGEABLE", merge_state="UNSTABLE",
        labels=(), auto_merge=None, number=4248):
    return {
        "number": number, "state": state, "isDraft": draft, "mergeable": mergeable,
        "mergeStateStatus": merge_state,
        "labels": [{"name": n} for n in labels],
        "autoMergeRequest": auto_merge,
    }


def _snapshot(mod, checks=None, pr=None, required=None):
    pr = pr if pr is not None else _pr()
    checks = checks if checks is not None else _checks(bare_red=[DRIFT])
    return mod.build_check_snapshot(pr, checks, REQUIRED_SAMPLE if required is None else required)


# ── gh 替身（CLI 边界注入点；写操作原样记账）───────────────────────────────────

FAKE_GH = '''\
#!/usr/bin/env python3
"""gh 替身：按调用把夹具吐回来，并把**写操作**原样记进 $FAKE_GH_LOG。"""
import json, os, sys

argv = sys.argv[1:]
log = os.environ["FAKE_GH_LOG"]
with open(log, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(argv) + "\\n")


def emit(name, rc_default=0):
    payload = os.environ.get(name + "_JSON", "")
    rc = int(os.environ.get(name + "_RC", str(rc_default)))
    if payload:
        sys.stdout.write(payload)
    sys.stderr.write(os.environ.get(name + "_ERR", ""))
    sys.exit(rc)


joined = " ".join(argv)
if argv[:2] == ["repo", "view"]:
    sys.stdout.write(os.environ.get("FAKE_GH_REPO", "zhaokai-mgzn/migao") + "\\n")
    sys.exit(int(os.environ.get("FAKE_GH_REPO_RC", "0")))
if argv[:1] == ["api"] and "protection" in joined:
    emit("FAKE_GH_PROTECTION")
if argv[:2] == ["pr", "view"]:
    emit("FAKE_GH_PR")
if argv[:1] == ["pr"] and "checks" in argv:
    emit("FAKE_GH_CHECKS")
if argv[:2] in (["pr", "edit"], ["pr", "merge"]):
    emit("FAKE_GH_WRITE")
sys.stderr.write("fake-gh: 未预期的调用 " + joined + "\\n")
sys.exit(2)
'''


@pytest.fixture
def fake_gh(tmp_path):
    """在 PATH 之外放一个 gh 替身，返回 (env 构造器, 调用读取器, 写操作读取器)。"""
    path = tmp_path / "fake-gh"
    path.write_text(FAKE_GH, encoding="utf-8")
    path.chmod(0o755)
    log = tmp_path / "gh-calls.jsonl"
    log.write_text("", encoding="utf-8")

    def configure(**kw):
        env = {"FAKE_GH_LOG": str(log)}
        for k, v in kw.items():
            if k.endswith("_RC"):
                env["FAKE_GH_" + k] = str(v)
            elif k.endswith("_ERR"):
                env["FAKE_GH_" + k] = v
            else:
                name = k[:-len("_JSON")] if k.endswith("_JSON") else k
                env["FAKE_GH_" + name + "_JSON"] = v if isinstance(v, str) else json.dumps(v)
        return env

    def calls():
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def writes():
        return [c for c in calls() if c[:2] in (["pr", "edit"], ["pr", "merge"])]

    return {"bin": str(path), "configure": configure, "calls": calls, "writes": writes}


def _env(fake_gh, **kw):
    """默认夹具：required 读得到、PR 是 OPEN 且 UNSTABLE、checks 里只有 Drift Audit 红。"""
    base = {
        "PROTECTION": {"contexts": REQUIRED_SAMPLE},
        "PR": _pr(),
        "CHECKS": _checks(bare_red=[DRIFT]),
    }
    base.update(kw)
    return {**os.environ, **fake_gh["configure"](**base)}


def _run(fake_gh, *args, env=None, gh_bin=None):
    env = dict(env if env is not None else _env(fake_gh))
    env["MG_GH_BIN"] = gh_bin if gh_bin is not None else fake_gh["bin"]
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env)


# ── ① 裸判据红 ⇒ 判 1 ─────────────────────────────────────────────────────────

def test_bare_red_report_check_is_a_hit():
    """关联 #4214 的形态：Drift Audit 红 + 其余全绿 + 该 job 不在 required ⇒ 判 1。"""
    mod = _load_module()
    v = mod.decide_check(_snapshot(mod))
    assert v.code == 1
    assert v.form_matched is True
    assert [c["name"] for c in v.bare_red] == [DRIFT]
    assert v.required_red == []


def test_cli_hit_prints_evidence_and_actionable_command(fake_gh):
    """命中时输出要能**直接行动**：红的判据名 + job 链接 + 建议动作（含可粘的命令）。"""
    env = _env(fake_gh, CHECKS=[
        _check(n) for n in REQUIRED_SAMPLE] + [
        {"name": DRIFT, "state": "FAILURE", "bucket": "fail",
         "link": "https://github.com/zhaokai-mgzn/migao/actions/runs/1/job/2"}])
    proc = _run(fake_gh, "--check", "4248", env=env)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert DRIFT in proc.stdout
    assert "https://github.com/zhaokai-mgzn/migao/actions/runs/1/job/2" in proc.stdout
    cmds = [line.strip() for line in proc.stdout.splitlines() if line.strip().startswith("gh ")]
    assert any("block/merge" in c for c in cmds), proc.stdout
    assert "dry-run" in proc.stdout.lower()


def test_merged_pr_with_bare_red_is_a_hit_too(fake_gh):
    """已 MERGED 的 PR（关联 #4214 / #4266 / #4267 / #4271）⇒ 形态**既成事实**，仍判 1（事后可追）。"""
    env = _env(fake_gh, PR=_pr(state="MERGED", mergeable="UNKNOWN", merge_state="UNKNOWN",
                               labels=["block/merge"]))
    proc = _run(fake_gh, "--check", "4214", env=env)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "MERGED" in proc.stdout


def test_unknown_new_job_name_is_also_bare():
    """⑥ 不硬编码清单：仓库里**不存在**的新 job 名（红 + 不在 required）也必须被判成裸判据。"""
    mod = _load_module()
    v = mod.decide_check(_snapshot(mod, checks=_checks(bare_red=["Future Gate (未来新增)"])))
    assert v.code == 1
    assert [c["name"] for c in v.bare_red] == ["Future Gate (未来新增)"]


# ── ② 反向 A：报告型全绿 ⇒ 判 0（不得恒红）─────────────────────────────────────

def test_reverse_a_all_green_is_ok():
    mod = _load_module()
    v = mod.decide_check(_snapshot(mod, checks=_checks()))
    assert v.code == 0
    assert v.form_matched is False
    assert v.bare_red == []


def test_reverse_a_cli_exits_zero(fake_gh):
    proc = _run(fake_gh, "--check", "4248", env=_env(fake_gh, CHECKS=_checks()))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "未命中" in proc.stdout


# ── ③ 反向 B：红的 job 在 required 里 ⇒ 判 0（不重复报警）──────────────────────

def test_reverse_b_red_required_check_is_not_our_form(fake_gh):
    """GitHub 自己就会拦 required 红 ⇒ 判 0，且输出要说明「已被 required 拦」。"""
    proc = _run(fake_gh, "--check", "4248", env=_env(fake_gh, CHECKS=_checks(
        required_red=["QA Growth Gate"])))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "required" in proc.stdout
    assert "已被" in proc.stdout or "拦住" in proc.stdout


def test_reverse_b_required_red_shadows_bare_red(fake_gh):
    """required 红 + 裸判据红 ⇒ 仍是 0（合并已被拦住）；裸判据只作信息列出，不升级成 1。"""
    proc = _run(fake_gh, "--check", "4248", env=_env(fake_gh, CHECKS=_checks(
        bare_red=[DRIFT], required_red=["QA Growth Gate"])))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert DRIFT in proc.stdout          # 如实列出，不隐瞒
    assert "required" in proc.stdout


def test_already_labelled_pr_is_zero(fake_gh):
    """已带 `block/merge` 的 PR ⇒ 闸门已生效，判 0（幂等，不重复报警）。"""
    proc = _run(fake_gh, "--check", "4248", env=_env(fake_gh, PR=_pr(labels=["block/merge"])))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "block/merge" in proc.stdout


# ── ④ 三态 ⇒ 判 3（绝不 fail-open）────────────────────────────────────────────

def test_undecidable_when_gh_missing(fake_gh):
    proc = _run(fake_gh, "--check", "4248", gh_bin="/nonexistent/gh-4248")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "无法判定" in proc.stdout


def test_undecidable_when_api_errors(fake_gh):
    env = _env(fake_gh, PR_JSON="", PR_RC=1, PR_ERR="HTTP 502: Bad gateway")
    proc = _run(fake_gh, "--check", "4248", env=env)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "无法判定" in proc.stdout


def test_undecidable_when_required_unreadable(fake_gh):
    """读不到 required 集合 ⇒ 无法区分「裸判据」与「required 判据」⇒ 3，不得谎报 0。"""
    env = _env(fake_gh, PROTECTION_JSON="", PROTECTION_RC=1,
               PROTECTION_ERR="Resource not accessible by integration")
    proc = _run(fake_gh, "--check", "4248", env=env)
    assert proc.returncode == 3, proc.stdout + proc.stderr


def test_undecidable_when_merge_state_unknown(fake_gh):
    """GitHub 仍在重算（mergeable=UNKNOWN）⇒ 3（§7.3：等 30~60s 再试）。"""
    proc = _run(fake_gh, "--check", "4248",
                env=_env(fake_gh, PR=_pr(mergeable="UNKNOWN", merge_state="UNKNOWN")))
    assert proc.returncode == 3, proc.stdout + proc.stderr


# ── ⑤ 元判据 --required-diff ──────────────────────────────────────────────────

def test_required_diff_nonempty_is_one(fake_gh):
    """差集非空 ⇒ 1（存在裸判据：会红但不拦合并）。"""
    proc = _run(fake_gh, "--required-diff", env=_env(fake_gh))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert DRIFT in proc.stdout


def test_required_diff_empty_is_zero(fake_gh):
    """差集为空（所有会判红的 job 都在 required 里）⇒ 0。"""
    mod = _load_module()
    jobs = mod.job_names_on_pull_requests(WORKFLOWS_DIR)
    env = _env(fake_gh, PROTECTION={"contexts": sorted(set(jobs) | set(REQUIRED_SAMPLE))})
    proc = _run(fake_gh, "--required-diff", env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0" in proc.stdout


def test_required_diff_unreadable_protection_is_three(fake_gh):
    env = _env(fake_gh, PROTECTION_JSON="", PROTECTION_RC=1,
               PROTECTION_ERR="Resource not accessible by integration")
    proc = _run(fake_gh, "--required-diff", env=env)
    assert proc.returncode == 3, proc.stdout + proc.stderr


def test_required_diff_unreadable_workflows_is_three(fake_gh, tmp_path):
    proc = _run(fake_gh, "--required-diff", "--workflows-dir", str(tmp_path / "nope"))
    assert proc.returncode == 3, proc.stdout + proc.stderr


def test_required_diff_lists_real_bare_jobs():
    """真实仓库锚点：`Drift Audit (真相源契约)` 必须出现在裸判据清单里（#4248 的中心 job）。"""
    mod = _load_module()
    jobs = mod.job_names_on_pull_requests(WORKFLOWS_DIR)
    bare = mod.bare_jobs(jobs, REQUIRED_SAMPLE)
    assert DRIFT in bare
    # 每个条目都要能追到「哪个 workflow 的哪个 job」——否则输出不可行动
    assert jobs[DRIFT].endswith("drift-audit.yml:audit")


# ── ⑦ 写操作边界 ──────────────────────────────────────────────────────────────

def test_dry_run_is_default_and_writes_nothing(fake_gh):
    proc = _run(fake_gh, "--check", "4248")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert fake_gh["writes"]() == []
    assert "dry-run" in proc.stdout.lower()


def test_apply_label_adds_label_only_on_hit(fake_gh):
    """未 arm 的 PR：`--apply-label` 只打标签（**没有** auto-merge 需要解除）。

    未 arm 时标签本身就足够 —— `automerge.yml` 的 `if:`（含 `!contains(labels,'block/merge')`）
    会让它在 `labeled` / `synchronize` 等事件上**永不 arm**。
    """
    proc = _run(fake_gh, "--check", "4248", "--apply-label", env=_env(fake_gh))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    writes = fake_gh["writes"]()
    assert writes == [["pr", "edit", "4248", "--add-label", "block/merge"]], writes
    assert "pr merge" not in json.dumps(writes)      # 未 arm ⇒ 无可解除


def test_apply_label_disarms_auto_by_default(fake_gh):
    """关联 #4334 的裁定：`--apply-label` **默认同时 disarm** —— 「打 block/merge」= 「拦住合并」。

    实测依据（关联 #4271）：`autoMergeRequest.enabledAt` 07:03:18Z → 标签 07:03:19Z → **合并 07:07:22Z**；
    关联 #4266：标签 06:57:32Z → **合并 07:00:30Z** ⇒ 只打标签**没拦住**。
    """
    proc = _run(fake_gh, "--check", "4248", "--apply-label",
                env=_env(fake_gh, PR=_pr(auto_merge={"enabledAt": "2026-09-18T07:03:18Z"})))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    writes = fake_gh["writes"]()
    assert ["pr", "edit", "4248", "--add-label", "block/merge"] in writes, writes
    assert ["pr", "merge", "4248", "--disable-auto"] in writes, writes


def test_no_disarm_auto_escape_hatch_labels_only_and_warns(fake_gh):
    """逃生口 `--no-disarm-auto`：只打标签、**不得**发 disarm 调用，且必须**明写**它拦不住。"""
    proc = _run(fake_gh, "--check", "4248", "--apply-label", "--no-disarm-auto",
                env=_env(fake_gh, PR=_pr(auto_merge={"enabledAt": "2026-09-18T07:03:18Z"})))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    writes = fake_gh["writes"]()
    assert writes == [["pr", "edit", "4248", "--add-label", "block/merge"]], writes
    assert "不会被本标签拦住" in proc.stdout, proc.stdout


def test_no_disarm_auto_without_apply_label_writes_nothing(fake_gh):
    """`--no-disarm-auto` 不是写开关：不带 `--apply-label` ⇒ 仍是 dry-run 零写。"""
    proc = _run(fake_gh, "--check", "4248", "--no-disarm-auto",
                env=_env(fake_gh, PR=_pr(auto_merge={"enabledAt": "2026-09-18T07:03:18Z"})))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert fake_gh["writes"]() == []


def test_disarm_auto_flag_still_accepted_for_compat(fake_gh):
    """`--disarm-auto` 已是默认行为，但**仍须被接受** —— 关联 #4325 登记的接线命令里有它。"""
    proc = _run(fake_gh, "--check", "4248", "--apply-label", "--disarm-auto",
                env=_env(fake_gh, PR=_pr(auto_merge={"enabledAt": "2026-09-18T07:03:18Z"})))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert ["pr", "merge", "4248", "--disable-auto"] in fake_gh["writes"]()


def test_apply_label_is_idempotent_when_label_present(fake_gh):
    """已带标签 ⇒ 判 0（闸门已生效），**零写**（不再重复打标签，也不动 auto-merge）。"""
    proc = _run(fake_gh, "--check", "4248", "--apply-label",
                env=_env(fake_gh, PR=_pr(labels=["block/merge"])))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert fake_gh["writes"]() == []


def test_apply_label_never_writes_on_green_or_merged(fake_gh):
    green = _run(fake_gh, "--check", "4248", "--apply-label", env=_env(fake_gh, CHECKS=_checks()))
    assert green.returncode == 0, green.stdout + green.stderr
    merged = _run(fake_gh, "--check", "4214", "--apply-label",
                  env=_env(fake_gh, PR=_pr(state="MERGED", mergeable="UNKNOWN", merge_state="UNKNOWN",
                                           auto_merge={"enabledAt": "2026-09-18T07:03:18Z"})))
    assert merged.returncode == 1, merged.stdout + merged.stderr
    assert fake_gh["writes"]() == []


def test_auto_merge_armed_is_reported_in_output(fake_gh):
    """已 arm 的 auto-merge 必须在输出里点明（否则「打了标签就安全了」是错的真相模型）。"""
    proc = _run(fake_gh, "--check", "4248",
                env=_env(fake_gh, PR=_pr(auto_merge={"enabledAt": "2026-09-18T07:03:18Z"})))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "auto-merge" in proc.stdout
    assert "--disable-auto" in proc.stdout


def test_dry_run_hint_mentions_default_disarm(fake_gh):
    """dry-run 的「可行动」必须给出**一步落闸**的命令（disarm 已是默认，不再要人记两个开关）。"""
    proc = _run(fake_gh, "--check", "4248",
                env=_env(fake_gh, PR=_pr(auto_merge={"enabledAt": "2026-09-18T07:03:18Z"})))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "--check 4248 --apply-label" in proc.stdout, proc.stdout
    assert "--no-disarm-auto" in proc.stdout, proc.stdout


# ── ⑧ 参数与用法边界 ─────────────────────────────────────────────────────────

def test_subcommands_are_mutually_exclusive(fake_gh):
    proc = _run(fake_gh, "--required-diff", "--check", "4248")
    assert proc.returncode == 3, proc.stdout + proc.stderr
