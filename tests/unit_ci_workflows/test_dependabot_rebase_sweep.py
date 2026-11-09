# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012 ——
#   见 `.github/cases/misc.yml` 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。
#   本包不新建用例族、不改 `cases/**`。）
r"""dependabot 依赖 PR 的「合并结果 lock 不一致 ⇒ required 腿恒红」自动收口的判据（关联 #8845）。

## 被测行为（issue #8845 的实测口径）

一条 dependabot PR 落后 main 后，**合并结果**（`refs/pull/<n>/merge`，也是 squash 会落地的形状）
的 `package-lock.json` 会缺 `package.json` 里声明的依赖 —— 逐字：`npm error Missing: msw@2.15.0
from lock file`。两侧各自自洽、只有合出来的树坏 ⇒ required 腿恒红 ⇒ auto-merge 永不触发。
本仓 `strict: true` + 仓库 `allow_update_branch=false` ⇒ 页面没有「Update branch」按钮，
**没有任何东西会自己变**。收口 = 自动评论 `@dependabot rebase`（幂等、有界）。

## 本文件锁什么（每条都能单独变红，见文末注入式红证）

| # | 不变式 | 会红的形态 |
|---|---|---|
| 1 | 缺条目要**具名**报出来（不是「有差异」） | 判据退化成布尔 ⇒ 红证读出不到 `msw@^2.15.0` |
| 2 | 一致时**不许**报缺（负控） | 恒真判据（永远说缺） |
| 3 | 读不懂 lock ⇒ **抛错**（fail-closed） | 把「没有 packages 段」当一致 |
| 4 | lock 目录**从 PR 改动文件推导**，不硬编码 | 写死目录清单 ⇒ 新 npm 目录漏检 |
| 5 | 只动 dependabot / 非 draft / 无 `block/merge` | 把人工闸的 PR 也 rebase |
| 6 | **同一 head 只请求一次**（幂等） | 每轮重发 ⇒ 无限 rebase 循环（每次一轮全量 CI） |
| 7 | 每条 PR **最多 2 次**（有界） | 无上限 |
| 8 | 落后/冲突**按 lock 面分流**：无 npm lock ⇒ update-branch；有 ⇒ 只出声 | 一律 update-branch ⇒ 给 npm 制造坏 lock；一律出声 ⇒ 非 npm 的永远不动 |
| 9 | 探测失败 ⇒ `unjudgeable`（**不得当 skip**） | 静默当「没问题」 |
| 10 | 宿主 workflow 的接线（事件 / 权限 / 步骤） | 在 `push` 上跑 / 无写权限 / 不跑脚本 |
| 11 | **不往分支推提交**（§34.13 单写者） | 脚本里出现 push / update-branch ⇒ 与 dependabot 抢写 |
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dependabot_rebase_sweep.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "automerge.yml"
JOB = "rebase-stale-dependabot"


def _load_sweep():
    spec = importlib.util.spec_from_file_location("dependabot_rebase_sweep", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SWEEP = _load_sweep()


# ── 夹具（形状取自 2026-11-09 的真实读数，见 issue #8845）────────────────────────────
MANIFEST = {"dependencies": {"axios": "^1.21.0", "next": "16.4.5"},
            "devDependencies": {"msw": "^2.15.0", "@types/node": "26.6.6"}}
LOCK_OK = {"lockfileVersion": 3,
           "packages": {"": {}, "node_modules/axios": {"version": "1.21.0"},
                        "node_modules/next": {"version": "16.4.5"},
                        "node_modules/msw": {"version": "2.15.0"},
                        "node_modules/@types/node": {"version": "26.6.6"}}}
LOCK_BROKEN = {"lockfileVersion": 3,
               "packages": {"": {}, "node_modules/axios": {"version": "1.21.0"},
                            "node_modules/next": {"version": "16.4.5"},
                            "node_modules/@types/node": {"version": "26.6.6"}}}


def pr(number=8830, author="app/dependabot", draft=False, labels=(), sha="a" * 40,
       state="BLOCKED", title="chore(deps-dev): bump eslint-config-next from 16.4.3 to 16.4.5"):
    return {"number": number, "author": author, "isDraft": draft, "labels": list(labels),
            "headRefOid": sha, "mergeStateStatus": state, "title": title}


def comment(head_sha):
    return {"body": "%s\n@dependabot rebase —— 夹具\n\n说明" % SWEEP.marker_for(head_sha)}


# ── 1~3：lock 判据本体 ──────────────────────────────────────────────────────
def test_missing_entries_are_named():
    missing = SWEEP.lock_mismatches(MANIFEST, LOCK_BROKEN)
    assert [(n, s) for n, s in missing] == [("msw", "^2.15.0")], (
        "缺条目必须**具名**报出（包名 + 声明版本），否则判红不可归因：%r" % (missing,))


def test_consistent_lock_reports_nothing():
    assert SWEEP.lock_mismatches(MANIFEST, LOCK_OK) == [], "负控：一致时不许报缺（防恒真判据）"


@pytest.mark.parametrize("lock", [
    {"lockfileVersion": 1, "dependencies": {}},   # v1 没有 packages 段
    {"lockfileVersion": 3},                        # 缺 packages
    {"packages": []},                              # packages 形状不对
    {},                                            # 空
])
def test_unreadable_lock_is_fail_closed(lock):
    with pytest.raises(SWEEP.LockUnreadable):
        SWEEP.lock_mismatches(MANIFEST, lock)


def test_unreadable_manifest_is_fail_closed():
    with pytest.raises(SWEEP.LockUnreadable):
        SWEEP.lock_mismatches(["not", "a", "dict"], LOCK_OK)


# ── 4：目录从改动文件推导（不硬编码）──────────────────────────────────────────
def test_lock_dirs_are_derived_from_changed_files():
    files = [{"path": "frontend/admin-web/package-lock.json"},
             {"path": "frontend/admin-web/package.json"},
             {"path": "tests/package-lock.json"}]
    assert SWEEP.lock_dirs_from_files(files) == ["frontend/admin-web", "tests"]
    assert SWEEP.lock_dirs_from_files([]) == []


def test_no_hardcoded_lock_directory_list():
    src = SCRIPT.read_text(encoding="utf-8")
    for literal in ("frontend/admin-web", "frontend/mini-app", 'LOCK_DIRS'):
        assert literal not in src, (
            "脚本不许硬编码 lock 目录（%r）：dependabot.yml 新增 npm 目录时必须自动被覆盖" % literal)


# ── 5~9：判定 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kwargs,needle", [
    (dict(author="zhaokai-mgzn"), "非 dependabot"),
    (dict(draft=True), "draft"),
    (dict(labels=("block/merge",)), "block/merge"),
])
def test_skip_human_gates(kwargs, needle):
    verdict = SWEEP.decide(pr(**kwargs), [], {"dir": "d", "missing": [("msw", "^2")]})
    assert verdict["action"] == "skip" and needle in verdict["reason"]


def test_same_head_is_idempotent():
    p = pr(sha="b" * 40)
    verdict = SWEEP.decide(p, [comment("b" * 40)], {"dir": "d", "missing": [("msw", "^2")]})
    assert verdict["action"] == "skip", "同一 head 已请求过 ⇒ 必须跳过（否则 rebase 循环）"
    # 负控：**别的** head 的标记不该挡住本轮
    other = SWEEP.decide(p, [comment("c" * 40)], {"dir": "d", "missing": [("msw", "^2")]})
    assert other["action"] == "rebase"


def test_request_budget_is_bounded():
    p = pr(sha="d" * 40)
    two = [comment("a" * 40), comment("b" * 40)]
    verdict = SWEEP.decide(p, two, {"dir": "d", "missing": [("msw", "^2")]})
    assert verdict["action"] == "skip" and "上限" in verdict["reason"], (
        "每条 PR 最多 %d 次（有界），到顶只出声" % SWEEP.MAX_REBASE_REQUESTS)


@pytest.mark.parametrize("state", ["BEHIND", "DIRTY"])
def test_stale_or_conflicting_pr_requests_rebase_even_without_probe(state):
    verdict = SWEEP.decide(pr(state=state), [], None)
    assert verdict["action"] == "rebase", "落后/冲突本身已足够触发（不必等 lock 探测）"
    assert state in verdict["reason"]


def test_behind_without_npm_lock_uses_update_branch():
    """非 npm（pip / maven / github-actions）的落后分支：直接 update-branch（无 lock 风险）。

    反过来 npm 面的落后分支**不许**走这条路：`gh pr update-branch` 会把 main 合进来，
    正是它产出坏 lock（#7688 的形态）—— 所以两种动作必须按 `dir is None` 分流。
    """
    verdict = SWEEP.decide(pr(state="BEHIND"), [], {"dir": None, "missing": []})
    assert verdict["action"] == "update-branch", verdict
    # 判不出 lock 面（探测失败）⇒ 保守走「只出声」，绝不自动 update-branch
    assert SWEEP.decide(pr(state="BEHIND"), [], None)["action"] == "rebase"


def test_broken_merge_lock_requests_rebase():
    verdict = SWEEP.decide(pr(state="BLOCKED"), [],
                           {"dir": "frontend/admin-web", "missing": [("msw", "^2.15.0")]})
    assert verdict["action"] == "rebase"
    assert "msw@^2.15.0" in verdict["reason"], "判红必须可归因（点名缺哪个包）"
    assert "frontend/admin-web" in verdict["reason"]


def test_probe_failure_is_unjudgeable_not_skip():
    verdict = SWEEP.decide(pr(state="BLOCKED"), [], None)
    assert verdict["action"] == "unjudgeable", "探测失败 ⇒ 不得当「没问题」静默跳过"


def test_unknown_state_is_not_red():
    verdict = SWEEP.decide(pr(state="UNKNOWN"), [], None)
    assert verdict["action"] == "skip", (
        "`mergeStateStatus=UNKNOWN`（GitHub 尚在计算）不得判 unjudgeable/红 —— "
        "与 automerge.yml 的 #5113 口径同源：可合并性未算完不是缺陷")
    assert "UNKNOWN" in verdict["reason"]


def test_clean_pr_is_skipped():
    assert SWEEP.decide(pr(state="CLEAN"), [], {"dir": "d", "missing": []})["action"] == "skip"


# ── 10：宿主 workflow 接线 ─────────────────────────────────────────────────
def _workflow_doc():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def job_wiring_problems(doc):
    problems = []
    jobs = doc.get("jobs") or {}
    job = jobs.get(JOB)
    if not isinstance(job, dict):
        return ["缺 job %s" % JOB]
    condition = " ".join(str(job.get("if") or "").split())
    if "app/dependabot" not in condition:
        problems.append("if 里没有依赖 bot 的判定（会在人写的 PR 上动作）")
    if "schedule" not in condition and "workflow_dispatch" not in condition:
        problems.append("缺 schedule/workflow_dispatch 入口（落后是「没有事件」的形态，扫不到）")
    perms = job.get("permissions") or {}
    if perms.get("pull-requests") != "write":
        problems.append("缺 pull-requests: write（发不出评论）")
    if perms.get("contents") == "write":
        problems.append("contents: write 过大（本 job 只读 + 评论，不需要写代码）")
    runs = [step.get("run") or "" for step in job.get("steps") or []]
    if not any("scripts/dependabot_rebase_sweep.py" in body for body in runs):
        problems.append("没有任何 step 跑 scripts/dependabot_rebase_sweep.py")
    script = SCRIPT.read_text(encoding="utf-8")
    for needle, label in ((SWEEP.MARKER_PREFIX, "幂等标记"),              # noqa: F821
                          (SWEEP.REBASE_COMMAND, "官方入口命令")):        # noqa: F821
        if needle not in script:
            problems.append("脚本里缺 %s（%r）" % (label, needle))
    return problems


def test_host_workflow_wiring_is_clean():
    assert SCRIPT.is_file(), "缺判据脚本"
    assert job_wiring_problems(_workflow_doc()) == []


def test_host_workflow_wiring_guard_is_not_vacuous():
    base = _workflow_doc()
    assert job_wiring_problems(base) == [], "先决条件：真文件必须合规"
    mutations = [
        ("if 放开成 true", lambda d: d["jobs"][JOB].__setitem__("if", "true")),
        ("去掉 schedule 入口",
         lambda d: d["jobs"][JOB].__setitem__("if", "github.event_name == 'pull_request_target'")),
        ("评论权限降成 read",
         lambda d: d["jobs"][JOB].setdefault("permissions", {}).__setitem__("pull-requests", "read")),
        ("步骤不跑脚本",
         lambda d: d["jobs"][JOB]["steps"][-1].__setitem__("run", "echo noop")),
    ]
    for label, mutate in mutations:
        doc = copy.deepcopy(base)
        mutate(doc)
        assert job_wiring_problems(doc), "注入「%s」后仍判绿 ⇒ 该判据是空断言" % label


# ── 11：绝不往分支写 ────────────────────────────────────────────────────────
def test_sweep_never_pushes_to_the_branch():
    src = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("git push", "--force", "gh pr merge"):
        assert forbidden not in src, (
            "%r 会与 dependabot 抢写同一分支（§34.13 单写者），且 GITHUB_TOKEN 的推送不触发 CI" % forbidden)
    # update-branch 允许，但**必须**由「这个 PR 没有 npm lock」这一条闸住（否则会把 lock 合坏）
    assert 'lock_report.get("dir") is None' in src, (
        "update-branch 必须被 `dir is None`（无 npm lock）闸住 —— 否则会给有 lock 的分支制造坏 lock")


# ── 端到端（gh 替身）：真发评论、且第二轮幂等 ───────────────────────────────────
GH_STUB = r'''#!/usr/bin/env python3
import base64, json, os, sys
from pathlib import Path

state_dir = Path(os.environ["SWEEP_STUB_DIR"])
state = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
args = sys.argv[1:]

if args[:2] == ["pr", "list"]:
    print(json.dumps(state["prs"]))
elif args[:2] == ["pr", "view"]:
    number = int(args[2])
    detail = dict(state["details"][str(number)])
    detail["comments"] = state["comments"].get(str(number), [])
    print(json.dumps(detail))
elif args[:2] == ["pr", "update-branch"]:
    state.setdefault("update_branch", []).append(args[2])
    (state_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    print("updated")
elif args[:2] == ["pr", "comment"]:
    number = args[2]
    body = args[args.index("--body") + 1]
    state["comments"].setdefault(number, []).append({"body": body})
    (state_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    print("commented")
elif args[:1] == ["api"]:
    path = args[1].split(" repos/")[0]
    # 形如 repos/<repo>/contents/<path>?ref=<sha>
    rel = path.split("/contents/", 1)[1].split("?ref=", 1)[0]
    payload = state["files"][rel]
    print(json.dumps({"content": base64.b64encode(payload.encode()).decode()}))
else:
    print("unexpected: %r" % (args,), file=sys.stderr)
    sys.exit(2)
'''


def _run_sweep(tmp_path, prs, details, comments, files, extra_args=()):
    stub = tmp_path / "gh"
    stub.write_text(GH_STUB, encoding="utf-8")
    stub.chmod(0o755)
    (tmp_path / "state.json").write_text(json.dumps(
        {"prs": prs, "details": details, "comments": comments, "files": files}), encoding="utf-8")
    env = dict(os.environ, SWEEP_STUB_DIR=str(tmp_path), DEPENDABOT_REBASE_GH_BIN=str(stub))
    proc = subprocess.run([sys.executable, str(SCRIPT), "--repo", "o/r", *extra_args],
                          capture_output=True, text=True, env=env,
                          cwd=str(REPO_ROOT))
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    return proc, state


def _stub_fixture(tmp_path, merge_state="BLOCKED", lock=None):
    detail = {"number": 8830,
              "author": {"login": "app/dependabot"},
              "isDraft": False,
              "labels": [],
              "headRefOid": "a" * 40,
              "mergeStateStatus": merge_state,
              "title": "chore(deps-dev): bump eslint-config-next",
              "files": [{"path": "frontend/admin-web/package-lock.json"}],
              "mergeCommit": {"oid": "f" * 40}}
    return _run_sweep(
        tmp_path,
        prs=[{"number": 8830, "author": {"login": "app/dependabot"}, "isDraft": False,
              "labels": [], "headRefOid": "a" * 40, "mergeStateStatus": merge_state,
              "title": "chore(deps-dev): bump eslint-config-next"}],
        details={"8830": detail},
        comments={},
        files={"frontend/admin-web/package.json": json.dumps(MANIFEST),
               "frontend/admin-web/package-lock.json": json.dumps(lock or LOCK_BROKEN)},
    )


def test_cli_requests_rebase_once_for_broken_merge_lock(tmp_path):
    proc, state = _stub_fixture(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    bodies = [c["body"] for c in state["comments"].get("8830", [])]
    assert len(bodies) == 1, "必须发出恰好一条评论：%r" % (bodies,)
    assert SWEEP.REBASE_COMMAND in bodies[0]
    assert SWEEP.marker_for("a" * 40) in bodies[0], "评论必须带幂等标记（按 head）"


def test_cli_update_branches_non_npm_bot_pr(tmp_path):
    """pip 类的落后 bot PR：走确定性 update-branch，**不发**评论（不依赖 dependabot 的命令通道）。"""
    detail = {"number": 8824, "author": {"login": "app/dependabot"}, "isDraft": False,
              "labels": [], "headRefOid": "e" * 40, "mergeStateStatus": "BEHIND",
              "title": "chore(deps): bump sqlalchemy", "mergeCommit": {"oid": "f" * 40},
              "files": [{"path": "backend/ai-agent-service/requirements.txt"}]}
    proc, state = _run_sweep(
        tmp_path,
        prs=[{"number": 8824, "author": {"login": "app/dependabot"}, "isDraft": False,
              "labels": [], "headRefOid": "e" * 40, "mergeStateStatus": "BEHIND",
              "title": "chore(deps): bump sqlalchemy"}],
        details={"8824": detail}, comments={}, files={})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert state.get("update_branch") == ["8824"], "非 npm 落后 ⇒ 必须走 update-branch"
    assert state["comments"].get("8824", []) == [], "这类不该再发评论"


def test_cli_on_healthy_lock_does_not_comment(tmp_path):
    proc, state = _stub_fixture(tmp_path, lock=LOCK_OK)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert state["comments"].get("8830", []) == [], "lock 一致时不许发评论"


# ── 注入式红证：证明上面第 1 条不是空断言（且注入确实生效）───────────────────
def test_red_proof_missing_entries_assertion_has_teeth():
    from unit_ci_workflows.injection import inject

    src = SCRIPT.read_text(encoding="utf-8")
    mutated = inject(
        src,
        '    for name in sorted(declared):\n'
        '        if ("node_modules/" + name) not in packages:\n'
        '            missing.append((name, declared[name]))',
        '    for name in sorted(declared):\n'
        '        if False:\n'
        '            missing.append((name, declared[name]))',
        where="scripts/dependabot_rebase_sweep.py",
    )
    namespace = {"__name__": "mutant_sweep", "__file__": str(SCRIPT)}
    exec(compile(mutated, str(SCRIPT), "exec"), namespace)  # noqa: S102 —— 红证注入
    assert namespace["lock_mismatches"](MANIFEST, LOCK_BROKEN) == [], "先决条件：变异体确实坏掉（缺条目不再报）"
    # 原实现必须报告 ⇒ 上面那条具名断言不是恒真
    assert SWEEP.lock_mismatches(MANIFEST, LOCK_BROKEN) == [("msw", "^2.15.0")]
