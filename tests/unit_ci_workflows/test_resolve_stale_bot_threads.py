# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 —— 见
#   tests/unit_ci_workflows/test_drift_audit_contract.py 的同款声明与 `.github/cases/misc.yml`
#   MC-012「CI workflow 结构由 pytest 单测验证」的登记。本 PR 不新建用例族：塞进行为用例库会污染覆盖矩阵。）
"""`scripts/resolve_stale_bot_threads.py` —— #4231「全绿却永久 BLOCKED」的判定与陈旧机器人线程解决。

守的地雷（**判定链全程用夹具驱动，不 mock 被测函数本身**）：`main` 的分支保护开了
`required_conversation_resolution`（实测 API 读回 `{'enabled': True}`），而一条**已 outdated、
但仍未 resolve** 的机器人评审线程（如 gitleaks 留言、作者 force-push 修好后检查转绿）会把 PR
**永久钉在 `BLOCKED`**，且**没有任何检查会变红**。实证 #4218：21 pass / 0 fail、`MERGEABLE`、
`labels=[]`、auto-merge 已启用，25 分钟不合并；手动 resolve 后 **46 秒**自动合并。

用例分组（每组都要有**判别力**，不是"跑通就算"）：

① **命中形态必判 1**：全绿 + `MERGEABLE` + 无阻塞 label + `BLOCKED` + 未解决 outdated bot 线程；
② **三条反向必须判 0**（防误报把人工闸/真失败混成这一形态）：
   A 同形态但**无未解决线程**（缺 required review 等）⇒ 0；
   B 有未解决线程但**检查未全绿**（真失败/在跑）⇒ 0；
   C 未解决线程的作者是**人类** ⇒ 0 + 单列「需人工评审」，**且 `--apply` 绝不 resolve 人类线程**；
③ **三态**：`gh` 不在 PATH / GraphQL 报错 / `mergeStateStatus=UNKNOWN`（GitHub 重算中）⇒ **exit=3，
   不是 0**（「看不了」不得当「没问题」，与 `red_proof.py` / `eval_slot_status.sh` 同口径）；
④ **`--apply` 的安全边界**：默认 dry-run **零写操作**；`--apply` 只 resolve「未解决 + bot + outdated」，
   非 outdated 的 bot 线程（机器人指出的问题可能仍在）与人类线程**都不动**；
⑤ **可行动**：命中时输出必须列出线程 path / 作者 / 是否 bot / 是否 outdated，并给出一条能直接粘走的
   `resolveReviewThread` 命令（含 thread id）。

夹具：`gh` 用**替身可执行文件**（`SBT_GH_BIN`）注入 —— 不 mock git/网络，而是把 CLI 边界当注入点，
故「gh 缺失 ⇒ 3」「GraphQL 报错 ⇒ 3」「mutation 真的发出去了没」都在同一条真实进程链上被验证。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "resolve_stale_bot_threads.py"


def _load_module():
    """按路径加载被测脚本（`scripts/` 不是包）。"""
    spec = importlib.util.spec_from_file_location("resolve_stale_bot_threads", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 夹具构造（纯数据，供纯函数直调）────────────────────────────────────────────

def _thread(tid="PRRT_stale", resolved=False, outdated=True, path="frontend/bmini-app/tests/production-qr.test.ts",
            login="github-actions", typename="Bot"):
    return {"id": tid, "isResolved": resolved, "isOutdated": outdated, "path": path,
            "comments": {"nodes": [{"author": {"login": login, "__typename": typename}}]}}


def _pull_request(threads=(), merge_state="BLOCKED", mergeable="MERGEABLE", labels=(),
                  state="OPEN", draft=False, number=4218):
    return {"number": number, "state": state, "isDraft": draft, "mergeable": mergeable,
            "mergeStateStatus": merge_state,
            "labels": {"nodes": [{"name": n} for n in labels]},
            "reviewThreads": {"totalCount": len(threads), "nodes": list(threads)}}


def _checks(n_pass=21, n_fail=0, n_pending=0, bucket="pass"):
    """`gh pr checks --json name,state,bucket` 的等价读数（#4218 实测 21 pass / 0 fail）。"""
    rows = []
    for i in range(n_pass):
        rows.append({"name": f"check-{i}", "state": "SUCCESS", "bucket": "pass"})
    for i in range(n_fail):
        rows.append({"name": f"fail-{i}", "state": "FAILURE", "bucket": "fail"})
    for i in range(n_pending):
        rows.append({"name": f"pending-{i}", "state": "PENDING", "bucket": "pending"})
    return rows


def _snapshot(mod, threads=(), checks=None, **kw):
    return mod.build_snapshot(_pull_request(threads=threads, **kw), checks if checks is not None else _checks())


# ── gh 替身（CLI 边界注入点；含 mutation 记录）─────────────────────────────────

FAKE_GH = '''\
#!/usr/bin/env python3
"""gh 替身：按调用把夹具吐回来，并把「写操作」原样记进 $FAKE_GH_LOG。"""
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
if "resolveReviewThread" in joined:
    emit("FAKE_GH_MUTATION")
if argv[:2] == ["repo", "view"]:
    sys.stdout.write(os.environ.get("FAKE_GH_REPO", "zhaokai-mgzn/migao") + "\\n")
    sys.exit(int(os.environ.get("FAKE_GH_REPO_RC", "0")))
if argv[:2] == ["api", "graphql"]:
    emit("FAKE_GH_PR")
if argv[:1] == ["pr"] and "checks" in argv:
    emit("FAKE_GH_CHECKS")
sys.stderr.write("fake-gh: 未预期的调用 " + joined + "\\n")
sys.exit(2)
'''


@pytest.fixture
def fake_gh(tmp_path):
    """在 PATH 之外放一个 gh 替身，返回 (env_extra, mutations 读取器, 配置写入器)。"""
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

    def mutations():
        return [c for c in calls() if "resolveReviewThread" in " ".join(c)]

    return {"bin": str(path), "configure": configure, "calls": calls, "mutations": mutations}


def _run(fake_gh, *args, env_extra=None, gh_bin=None):
    env = {**os.environ, **fake_gh["configure"](**(env_extra or {}))}
    env["SBT_GH_BIN"] = gh_bin if gh_bin is not None else fake_gh["bin"]
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env)


# ── ① 命中形态 ⇒ 判 1 ─────────────────────────────────────────────────────────

def test_stale_bot_thread_is_a_hit():
    """#4218 的确切读数（含真实 thread id / path / 作者）⇒ 判 1。"""
    mod = _load_module()
    v = mod.decide(_snapshot(mod, threads=[_thread(tid="PRRT_kwDOSVaRac6jnQPa")]))
    assert v.code == 1
    assert v.form_matched is True
    assert [t["id"] for t in v.stale_bot] == ["PRRT_kwDOSVaRac6jnQPa"]
    assert v.human == [] and v.fresh_bot == []


def test_cli_hit_prints_actionable_evidence_and_command(fake_gh):
    """命中时输出要能**直接行动**：线程 path/作者/是否 bot/是否 outdated + 一条可粘的命令。"""
    proc = _run(fake_gh, "4218", env_extra={
        "PR_JSON": json.dumps({"data": {"repository": {"pullRequest": _pull_request([_thread()])}}}),
        "CHECKS": _checks(),
    })
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "PRRT_stale" in proc.stdout
    assert "frontend/bmini-app/tests/production-qr.test.ts" in proc.stdout
    assert "github-actions" in proc.stdout
    assert "outdated" in proc.stdout
    cmds = [line.strip() for line in proc.stdout.splitlines() if "resolveReviewThread" in line]
    assert len(cmds) == 1, proc.stdout
    assert cmds[0].startswith("gh api graphql"), cmds
    assert "PRRT_stale" in cmds[0]


def test_dry_run_is_default_and_writes_nothing(fake_gh):
    """默认只读：命中形态也**零写操作**（与 delete_orders.py 同风格）。"""
    proc = _run(fake_gh, "4218", env_extra={
        "PR_JSON": json.dumps({"data": {"repository": {"pullRequest": _pull_request([_thread()])}}}),
        "CHECKS": _checks(),
    })
    assert proc.returncode == 1
    assert fake_gh["mutations"]() == []
    assert "dry-run" in proc.stdout.lower()


# ── ② 三条反向 ⇒ 判 0（防误报）────────────────────────────────────────────────

def test_reverse_a_green_blocked_without_unresolved_threads_is_ok():
    """A：全绿 + BLOCKED 但**没有**未解决线程（缺 required review / 缺必填检查）⇒ 0，不得误报。"""
    mod = _load_module()
    v = mod.decide(_snapshot(mod, threads=[_thread(resolved=True)]))
    assert v.code == 0
    assert v.form_matched is True          # 形态成立，但**不是**机器人陈旧线程所致
    assert v.stale_bot == []


def test_reverse_b_checks_not_green_is_ok():
    """B：有未解决 bot 线程但**检查未全绿**（真有失败在跑）⇒ 0，不得把真失败混成这一形态。"""
    mod = _load_module()
    failing = mod.decide(_snapshot(mod, threads=[_thread()], checks=_checks(n_fail=1)))
    pending = mod.decide(_snapshot(mod, threads=[_thread()], checks=_checks(n_pending=1)))
    assert failing.code == 0 and failing.form_matched is False
    assert pending.code == 0 and pending.form_matched is False


def test_reverse_c_human_thread_is_manual_not_auto_resolved():
    """C：未解决线程作者是**人类** ⇒ 0 + 单列「需人工评审」，不入 stale_bot（护栏不可被自动关掉）。"""
    mod = _load_module()
    v = mod.decide(_snapshot(mod, threads=[_thread(tid="PRRT_human", login="zhaokai-mgzn", typename="User")]))
    assert v.code == 0
    assert v.stale_bot == []
    assert [t["id"] for t in v.human] == ["PRRT_human"]


def test_apply_never_resolves_human_thread(fake_gh):
    """`--apply` 对人类线程**零动作**（issue #4231 明确：required_conversation_resolution 对人评审有价值）。"""
    proc = _run(fake_gh, "4218", "--apply", env_extra={
        "PR_JSON": json.dumps({"data": {"repository": {"pullRequest": _pull_request(
            [_thread(tid="PRRT_human", login="zhaokai-mgzn", typename="User")])}}}),
        "CHECKS": _checks(),
    })
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert fake_gh["mutations"]() == []
    assert "人工" in proc.stdout


def test_apply_resolves_only_stale_bot_threads(fake_gh):
    """混合场景：`--apply` 只 resolve 「未解决 + bot + outdated」那一类，其余原样不动。"""
    proc = _run(fake_gh, "4218", "--apply", env_extra={
        "PR_JSON": json.dumps({"data": {"repository": {"pullRequest": _pull_request([
            _thread(tid="PRRT_stale"),
            _thread(tid="PRRT_fresh", outdated=False),
            _thread(tid="PRRT_human", login="zhaokai-mgzn", typename="User"),
        ])}}}),
        "CHECKS": _checks(),
        "MUTATION": {"data": {"resolveReviewThread": {"thread": {"isResolved": True}}}},
    })
    assert proc.returncode == 0, proc.stdout + proc.stderr
    sent = json.dumps(fake_gh["mutations"]())
    assert "PRRT_stale" in sent
    assert "PRRT_fresh" not in sent        # 非 outdated：机器人指出的问题可能仍在 ⇒ 不自动 resolve
    assert "PRRT_human" not in sent
    assert "PRRT_fresh" in proc.stdout     # 但仍要如实列出、给人工处置路径


def test_blocking_label_is_not_a_hit():
    """带 `block/merge` 人工闸的 PR ⇒ 该形态不成立（BLOCKED 是**有意**的）。"""
    mod = _load_module()
    v = mod.decide(_snapshot(mod, threads=[_thread()], labels=["block/merge"]))
    assert v.code == 0 and v.form_matched is False


def test_non_blocked_state_is_not_a_hit():
    """`mergeStateStatus != BLOCKED`（CLEAN/UNSTABLE/DIRTY…）⇒ 不是本形态。"""
    mod = _load_module()
    for state in ("CLEAN", "UNSTABLE", "DIRTY", "BEHIND", "DRAFT"):
        v = mod.decide(_snapshot(mod, threads=[_thread()], merge_state=state))
        assert v.code == 0, state
        assert v.form_matched is False, state


def test_unmergeable_is_not_a_hit():
    """`mergeable=CONFLICTING` ⇒ 冲突导致的 BLOCKED，不是本形态。"""
    mod = _load_module()
    v = mod.decide(_snapshot(mod, threads=[_thread()], mergeable="CONFLICTING"))
    assert v.code == 0 and v.form_matched is False


def test_merged_pr_is_not_a_hit():
    """已合并/已关闭的 PR：无需处理（判 0，不是 3）。"""
    mod = _load_module()
    v = mod.decide(_snapshot(mod, threads=[_thread()], state="MERGED"))
    assert v.code == 0


# ── ③ 三态：看不了 ⇒ 3，绝不谎报「正常」──────────────────────────────────────

def test_gh_missing_exits_3(fake_gh, tmp_path):
    proc = _run(fake_gh, "4218", gh_bin=str(tmp_path / "no-such-gh"))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "无法判定" in proc.stdout + proc.stderr


def test_graphql_error_exits_3(fake_gh):
    proc = _run(fake_gh, "4218", env_extra={
        "PR_JSON": json.dumps({"data": None, "errors": [{"message": "Could not resolve to a PullRequest"}]}),
        "PR_RC": 1,
    })
    assert proc.returncode == 3, proc.stdout + proc.stderr


def test_uncomputable_merge_state_exits_3(fake_gh):
    """`mergeStateStatus=UNKNOWN` = GitHub 还在重算（§7.3）⇒ 3，不许当成 0。"""
    proc = _run(fake_gh, "4218", env_extra={
        "PR_JSON": json.dumps({"data": {"repository": {"pullRequest": _pull_request(
            [_thread()], merge_state="UNKNOWN", mergeable="UNKNOWN")}}}),
        "CHECKS": _checks(),
    })
    assert proc.returncode == 3, proc.stdout + proc.stderr


def test_unreadable_checks_exits_3(fake_gh):
    """`gh pr checks` 吐不出 JSON（不是「无检查」而是「读不到」）⇒ 3。"""
    proc = _run(fake_gh, "4218", env_extra={
        "PR_JSON": json.dumps({"data": {"repository": {"pullRequest": _pull_request([_thread()])}}}),
        "CHECKS": "", "CHECKS_ERR": "error connecting to api.github.com\n", "CHECKS_RC": 1,
    })
    assert proc.returncode == 3, proc.stdout + proc.stderr


def test_checks_not_green_is_not_undecidable(fake_gh):
    """「读到了、但没全绿」是**可判定**的 0（与「读不到」的 3 必须分开）。"""
    proc = _run(fake_gh, "4218", env_extra={
        "PR_JSON": json.dumps({"data": {"repository": {"pullRequest": _pull_request([_thread()])}}}),
        "CHECKS": _checks(n_fail=2), "CHECKS_RC": 1,
    })
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "全绿" in proc.stdout


def test_reverse_a_via_cli(fake_gh):
    """反向 A 走完整 CLI：退 0 且**零写操作**。"""
    proc = _run(fake_gh, "4218", "--apply", env_extra={
        "PR_JSON": json.dumps({"data": {"repository": {"pullRequest": _pull_request([_thread(resolved=True)])}}}),
        "CHECKS": _checks(),
    })
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert fake_gh["mutations"]() == []


# ── 纯函数口径（逐条可判，避免"绿了但没判"）──────────────────────────────────

def test_is_bot_author_accepts_typename_and_login_suffix():
    mod = _load_module()
    assert mod.is_bot_author("github-actions", "Bot") is True
    assert mod.is_bot_author("dependabot[bot]", None) is True
    assert mod.is_bot_author("zhaokai-mgzn", "User") is False
    assert mod.is_bot_author(None, None) is False


def test_checks_all_green_buckets():
    mod = _load_module()
    assert mod.checks_all_green(_checks()) is True
    assert mod.checks_all_green(_checks(n_pass=3) + [{"name": "s", "state": "SKIPPED", "bucket": "skipping"}]) is True
    assert mod.checks_all_green(_checks(n_fail=1)) is False
    assert mod.checks_all_green(_checks(n_pending=1)) is False
    assert mod.checks_all_green([{"name": "c", "state": "CANCELLED", "bucket": "cancel"}]) is False
    assert mod.checks_all_green([]) is False          # 无检查 ≠ 全绿（不得空跑成"绿"）
    assert mod.checks_all_green(None) is False


def test_parse_checks_is_fail_closed():
    mod = _load_module()
    assert mod.parse_checks("[]") == []
    assert mod.parse_checks("not json") is None       # 读不到 ⇒ None（走 3）
    assert mod.parse_checks("") is None


def test_verdict_reports_counts_for_evidence():
    """判定对象要带**证据读数**（多少次 pass/fail），报告与排障都靠它。"""
    mod = _load_module()
    v = mod.decide(_snapshot(mod, threads=[_thread()]))
    assert (v.counts["pass"], v.counts["fail"], v.counts["pending"]) == (21, 0, 0)


def test_no_mutation_when_undecidable(fake_gh, tmp_path):
    """无法判定时 `--apply` 也不得发写操作（fail-closed）。"""
    proc = _run(fake_gh, "4218", "--apply", gh_bin=str(tmp_path / "no-such-gh"), env_extra={
        "PR_JSON": json.dumps({"data": {"repository": {"pullRequest": _pull_request([_thread()])}}}),
        "CHECKS": _checks(),
    })
    assert proc.returncode == 3
    assert fake_gh["mutations"]() == []
