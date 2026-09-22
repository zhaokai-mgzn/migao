# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 tests/unit_ci_workflows/test_merge_gate.py 与 tests/unit_ci_workflows/test_close_linked_issues_chain.py
#   的同款声明，以及 `.github/cases/misc.yml` MC-012 的登记。本 PR 不新建用例族：
#   塞进行为用例库会污染覆盖矩阵。）
"""`automerge.yml` 的 **bot 安全路径** L0 守卫（关联 #5077）。

## 被移除的人工环节（本守卫存在的理由）

`automerge.yml` 原 `if:` 逐字含 `github.event.pull_request.user.type != 'Bot'`，
注释自陈「bot PR（dependabot 等）跳过 —— 依赖升级仍需人工按 SOP 分类」⇒
**每一条 dependabot PR 都要人工分类与合并**。实测（2026-09-21/22，见 issue #5077）：
16 条 dependabot PR 全部停在「没人合」；其中 `#4470` / `#4475` 改 `.github/workflows/**`，
**连人工 `gh pr merge` 都合不了**（本机 token 无 `workflow` scope，GraphQL 拒），
属 `migao-dev-flow` §7.1 的「⏸ 保留 | 保持 open，留给有权限者」—— 这一行正是要移除的人工环节。

## 本守卫锁什么（每条都要有**能单独让它变红**的变异）

| # | 形态 | 红证（只改一处即翻转） |
|---|---|---|
| 1 | bot + 只改 `uses:` 版本 tag ⇒ arm | 同夹具多一行非 `uses:` 改动 ⇒ `NOT_USES_ONLY` |
| 2 | bot + patch/minor ⇒ arm | 同夹具只把 `to` 版本改成 major ⇒ `VERSION_MAJOR` |
| 3 | bot + 新增 workflow 文件 ⇒ 不 arm | `status: added` ⇒ `FILE_ADDED_OR_REMOVED` |
| 4 | bot + diff 新增 `secrets.*` ⇒ 不 arm | 加一行 secrets ⇒ `SECRETS_ADDED` |
| 5 | bot + `block/merge` 标签 ⇒ 不 arm | 标签存在 ⇒ `BLOCK_LABEL` |
| 6 | bot + required 检查判红 ⇒ 不 arm | `mergeStateStatus=BLOCKED` + 判红检查 ⇒ `CHECKS_FAILED` |
| 7 | 非 bot（人类 PR）路径**逐字不变** | 删掉 bot 排除子句 ⇒ 该断言变红 |
| 8 | 每条判据都能**单独**变红 | `TestGuardMutationsProveDiscriminatingPower`（6 个单点源码变异） |

## 判据 6 的口径（**实测证据，非推断**）

「required 检查全绿」**不能**实现成「`gh pr checks` 一条不红」。实测（#5077 ③）：
dependabot PR 上恒有一条**非 required** 的陈旧红 `Reconcile and dispatch missing deploys`
（真因 = dependabot 触发的 workflow 拿不到仓库 secrets ⇒ `docker login` 无凭据）⇒
按字面实现会让 `#4475` / `#4471` / `#4469` 依然不 arm，**本包等于零生效**。

CI 里也**读不到** required 集合：`GET /repos/{o}/{r}/branches/main/protection` 需 admin
（`GITHUB_TOKEN` 不是 admin）；实测 `gh pr view --json statusCheckRollup` 的 `isRequired`
**恒为 `null`**（该字段是需带参的 GraphQL 字段，`gh` 不暴露）。故采用 **GitHub 自己的
required 判定** `mergeStateStatus`：`UNSTABLE` = 「required 未判红、只是非 required 项在红」
（此时 arm 是安全的：native auto-merge 仍只认 required 集合）；required 真红时 GitHub 报
`BLOCKED` ⇒ 仍然不 arm（判据 6 的红证即建在此，且**断言不得落进 UNSTABLE 例外**）。

## 注入点

`gh` 走 **`AUTOMERGE_GH_BIN` 替身可执行文件**（沿用 `scripts/merge_gate.py` 的 `MG_GH_BIN` /
`scripts/resolve_stale_bot_threads.py` 的 `SBT_GH_BIN` 先例）：不 mock 被测函数，而是把 CLI
边界当注入点 ⇒「arm 到底发出去了没」「fail-closed 时打印了什么理由」都在**同一条真实进程链**上验证。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "automerge.yml"

BOT_JOB = "enable-auto-merge-bot-safe"
NONBOT_JOB = "enable-auto-merge"
MERGE_CMD = "pr merge 1 --auto --squash --delete-branch"
WF_TITLE = "chore(deps): bump actions/download-artifact from 7 to 8"

# ── 判据 7：非 bot 路径的**逐字快照**（原文件文本，含 YAML 缩进）─────────────────
# 这些片段必须**原样**留在文件里。改了它们 = 改了人类 PR 的既有行为。
ORIGINAL_NONBOT_IF_RAW = """      github.event.pull_request.base.ref == 'main' &&
      github.event.pull_request.draft == false &&
      github.event.pull_request.user.type != 'Bot' &&
      github.event.pull_request.head.repo.full_name == github.repository &&
      !contains(github.event.pull_request.labels.*.name, 'block/merge')"""

# ⚠️ 2026-09-22 刷新：`#5109` 给该 run 块加了「arm 后回读 autoMergeRequest」的后置条件 ⇒
# 本常量随之更新为 **origin/main 当前内容**（判据 7 的语义 = 「非 bot 路径相对**当前主干**逐字不变」，
# 而不是「相对某个历史快照不变」）。刷新方式：从 origin/main 原始文本提取该 run 块。
# ⚠️ 2026-09-22 刷新：`#5109` 给该 run 块加了「arm 后回读 autoMergeRequest」的后置条件 ⇒
# 本常量随之更新为 **origin/main 当前内容**（判据 7 的语义 = 「非 bot 路径相对**当前主干**逐字不变」，
# 而不是「相对某个历史快照不变」）。提取方式：从 origin/main 版 `automerge.yml` 的该 run 块按行取原文。
# ⚠️ 2026-09-22 刷新：`#5109` 给该 run 块加了「arm 后回读 autoMergeRequest」的后置条件 ⇒
# 本常量随之更新为 **origin/main 当前内容**（判据 7 的语义 = 「非 bot 路径相对**当前主干**逐字不变」，
# 而不是「相对某个历史快照不变」）。提取方式：从 origin/main 版 `automerge.yml` 的该 run 块按行取原文。
# ⚠️ 2026-09-22 刷新：`#5109` 给该 run 块加了「arm 后回读 autoMergeRequest」的后置条件 ⇒
# 本常量随之更新为 **origin/main 当前内容**（判据 7 的语义 = 「非 bot 路径相对**当前主干**逐字不变」，
# 而不是「相对某个历史快照不变」）。提取方式：从该 run 块按行取原文并**转义反斜杠**。
ORIGINAL_NONBOT_RUN_RAW = """          set -uo pipefail

          merge_out="$(mktemp)"
          # ⚠️ trap 里的变量名必须与主流程的 `rc` **不同名**：trap 是 EXIT 时执行的，
          #    用 `rc=$?` 会覆盖主流程已判定的退出码（本脚本初版就这么错过一次）。
          trap 'trc=$?; rm -f "${merge_out:-}"; exit $trc' EXIT

          rc=0
          gh pr merge "$PR_NUMBER" --auto --squash --delete-branch >"$merge_out" 2>&1 || rc=$?

          if [ "$rc" -ne 0 ]; then
            # 预期内（幂等/暂不可合并）：**只收窄**——必须逐字命中这些标记才算预期内，
            # 其余一律按真失败处理（fail-closed：宁可多报一次，也不静默放过）。
            if grep -qiE 'already (in|queued|enabled|merged)|already been merged' "$merge_out"; then
              echo "ℹ️  预期内（幂等）返回 ${rc}：$(tr '\\n' ' ' < "$merge_out")"
              echo "    PR #$PR_NUMBER 的 auto-merge 已处于目标状态，非失败。"
              exit 0
            fi
            echo "::error::gh pr merge --auto 真失败（rc=${rc}）—— PR #$PR_NUMBER 未被 arm，且不会有别的东西因此停手"
            sed 's/^/    /' "$merge_out"
            {
              echo "### Enable auto-merge — 真失败"
              echo ""
              echo "- PR：#$PR_NUMBER"
              echo "- \\`gh pr merge --auto\\` 退出码：$rc"
              echo "- 输出（未命中预期内幂等标记）："
              echo '```'
              cat "$merge_out"
              echo '```'
              echo "- ⇒ **auto-merge 未 arm**；本 job 判红即为真问题（不是幂等正常）。"
            } >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
            exit 1
          fi

          # ---------- 后置条件：命令成功 ≠ 真的 arm 上了（issue #4829 的「静默没 arm」）----------
          state="$(gh pr view "$PR_NUMBER" \\
            --json autoMergeRequest \\
            --jq 'if .autoMergeRequest == null then "none" else "armed" end' 2>/dev/null || true)"
          if [ -z "$state" ]; then
            echo "::error::auto-merge 后置状态查询失败（PR #${PR_NUMBER}：gh 限流/网络/无权限）—— 无法判定是否已 arm，不得当成功"
            {
              echo "### Enable auto-merge — 后置状态无法判定"
              echo ""
              echo "- PR：#$PR_NUMBER"
              echo "- \\`gh pr merge --auto\\` 返回 0，但 \\`gh pr view --json autoMergeRequest\\` 查询失败。"
              echo "- ⇒ 三态判定为 **unknown**，不得当「已 arm」读。"
            } >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
            exit 1
          fi
          case "$state" in
            armed)
              echo "✅ auto-merge 已 arm（PR #${PR_NUMBER}，squash + delete-branch）"
              ;;
            none)
              echo "::error::auto-merge 未 arm：gh 返回 0 但 PR #$PR_NUMBER 的 autoMergeRequest 仍为 null（issue #4829 的静默没 arm 形态）"
              {
                echo "### Enable auto-merge — 未 arm（静默失效）"
                echo ""
                echo "- PR：#$PR_NUMBER"
                echo "- \\`gh pr merge --auto\\` 返回 **0**，但 \\`autoMergeRequest == null\\`。"
                echo "- ⇒ 命令成功不代表 arm 成功（#4829）：CI 一绿**不会**自动合并。"
              } >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
              exit 1
              ;;
            *)
              echo "::error::auto-merge 后置状态不可解析（PR #${PR_NUMBER}）：state='$state'"
              exit 1
              ;;
          esac"""

# 原文件里唯一的一处 secrets 引用（本 PR 不得新增第二处）
ORIGINAL_SECRETS_LINE = "          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}"


# ── gh 替身（夹具驱动；CLI 边界即注入点）────────────────────────────────────────
FAKE_GH_SRC = '''#!/usr/bin/env python3
"""gh 替身：夹具驱动。沿用 merge_gate.py 的 MG_GH_BIN / resolve_stale_bot_threads.py 的 SBT_GH_BIN 先例。"""
import os
import sys

FX = os.environ["FAKE_GH_FIXTURES"]
argv = sys.argv[1:]


def read(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return f.read()


def append(name, text):
    with open(os.path.join(FX, name), "a", encoding="utf-8") as f:
        f.write(text + "\\n")


if argv[:1] == ["api"]:
    rc = int(read("api_exit").strip() or "0")
    if rc == 0:
        sys.stdout.write(read("files.ndjson"))
    else:
        sys.stderr.write("fake-gh: api failure (injected)\\n")
    sys.exit(rc)

if argv[:1] == ["pr"] and argv[1:2] == ["checks"]:
    sys.stdout.write(read("checks.json"))
    sys.exit(int(read("checks_exit").strip() or "0"))

if argv[:1] == ["pr"] and argv[1:2] == ["view"]:
    sys.stdout.write(read("merge_state.txt").strip() + "\\n")
    sys.exit(0)

if argv[:1] == ["pr"] and argv[1:2] == ["merge"]:
    append("merge_calls.log", " ".join(argv))
    sys.exit(0)

sys.stderr.write("fake-gh: unhandled argv=" + repr(argv) + "\\n")
sys.exit(9)
'''


# ── 夹具构造 ───────────────────────────────────────────────────────────────────
def wf_file(name=".github/workflows/xiaobu-acceptance.yml", old="v7", new="v8",
            action="actions/download-artifact", extra_added=(), status="modified"):
    """一个「只改 uses 版本 tag」的 workflow 文件夹具（`#4475` 的真实形态）。"""
    patch = (
        "@@ -1,7 +1,7 @@\n"
        " jobs:\n"
        "   build:\n"
        "     steps:\n"
        f"-      - uses: {action}@{old}\n"
        f"+      - uses: {action}@{new}\n"
        "       - run: echo hi\n"
    )
    for line in extra_added:
        patch += f"+{line}\n"
    return {"filename": name, "status": status, "patch": patch}


def dep_file(name="frontend/admin-web/package.json", old="16.3.2", new="16.3.3",
             status="modified", omit_new=False, comment=""):
    """一个 patch/minor 依赖升级夹具（非 workflow 文件）。"""
    patch = "@@ -20,7 +20,7 @@\n"
    patch += f'-    "pkg": "{old}",\n'
    patch += f'+    "pkg": "{old if omit_new else new}",{comment}\n'
    return {"filename": name, "status": status, "patch": patch}


def checks(*rows):
    return [{"name": n, "state": s, "bucket": b} for n, s, b in rows]


GREEN_CHECKS = checks(("QA Growth Gate", "SUCCESS", "pass"),
                      ("admin-api unit tests", "SUCCESS", "pass"))
# required 判红（实测形态：#4477 的 admin-web typecheck）⇒ GitHub 报 mergeStateStatus=BLOCKED
FAIL_CHECKS = checks(("admin-web typecheck + unit tests", "FAILURE", "fail"),
                     ("QA Growth Gate", "SUCCESS", "pass"))
# 非 required 陈旧红（实测形态：#5077 ③ 的 Reconcile and dispatch missing deploys）
STALE_NONREQUIRED_CHECKS = checks(("Reconcile and dispatch missing deploys", "FAILURE", "fail"),
                                  ("QA Growth Gate", "SUCCESS", "pass"))


class GuardRun:
    """一次 guard 调用的可观测结果。"""

    def __init__(self, proc, merge_calls, summary):
        self.proc = proc
        self.merge_calls = merge_calls
        self.summary = summary

    @property
    def armed(self) -> bool:
        return MERGE_CMD in self.merge_calls

    def field(self, name: str) -> str:
        """从 step summary 里取 `NAME=` 行（唯一事实源 = 被测进程打印的东西）。"""
        for line in self.summary.splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
        raise AssertionError(f"step summary 里没有 {name}= 行：{self.summary!r}")

    def code(self) -> str:
        return self.field("CODE")


def run_guard(tmp_path, files, *, checks_json=None, checks_exit=None, merge_state="CLEAN",
              title="", labels="", api_exit=0, checks_raw=None, script=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    fx = tmp_path / "fixtures"
    fx.mkdir(exist_ok=True)
    (fx / "files.ndjson").write_text(
        "\n".join(json.dumps(f) for f in files) + ("\n" if files else ""), encoding="utf-8")
    rows = checks_json if checks_json is not None else GREEN_CHECKS
    (fx / "checks.json").write_text(checks_raw if checks_raw is not None else json.dumps(rows),
                                    encoding="utf-8")
    if checks_exit is None:
        checks_exit = 1 if any(r.get("bucket") in ("fail", "cancel") for r in rows) else 0
    (fx / "checks_exit").write_text(str(checks_exit), encoding="utf-8")
    (fx / "merge_state.txt").write_text(merge_state, encoding="utf-8")
    (fx / "api_exit").write_text(str(api_exit), encoding="utf-8")

    fake = tmp_path / "fake-gh"
    fake.write_text(FAKE_GH_SRC, encoding="utf-8")
    fake.chmod(0o755)
    guard = tmp_path / "guard.py"
    guard.write_text(script if script is not None else bot_script(), encoding="utf-8")
    summary_path = tmp_path / "summary.md"

    env = {k: v for k, v in os.environ.items() if not k.startswith("GH_")}
    env.update({
        "AUTOMERGE_GH_BIN": str(fake),
        "FAKE_GH_FIXTURES": str(fx),
        "GH_REPO": "o/r",
        "PR_NUMBER": "1",
        "PR_TITLE": title,
        "PR_LABELS": labels,
        "GITHUB_STEP_SUMMARY": str(summary_path),
    })
    proc = subprocess.run([sys.executable, str(guard)], capture_output=True, text=True,
                          env=env, timeout=120)
    calls_path = fx / "merge_calls.log"
    return GuardRun(proc, calls_path.read_text(encoding="utf-8") if calls_path.exists() else "",
                    summary_path.read_text(encoding="utf-8") if summary_path.exists() else "")


# ── workflow 解析 / 脚本抽取 ───────────────────────────────────────────────────
def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def workflow_yaml() -> dict:
    return yaml.safe_load(workflow_text())


def bot_job() -> dict:
    job = workflow_yaml()["jobs"].get(BOT_JOB)
    assert job, f"缺少 bot 安全路径 job：{BOT_JOB}（本包的核心交付物）"
    return job


def bot_script() -> str:
    """从 bot job 的 heredoc step 里抽出被测的 python 脚本（单一事实源 = 真文件）。"""
    for step in bot_job()["steps"]:
        run = step.get("run") or ""
        if "AUTOMERGE_GH_BIN" not in run:
            continue
        lines = run.splitlines()
        start = next(i for i, line in enumerate(lines) if line.strip().startswith("python3 - <<"))
        end = next(i for i in range(len(lines) - 1, start, -1) if lines[i].strip() == "PY")
        return "\n".join(lines[start + 1:end])
    raise AssertionError(f"{BOT_JOB} 里找不到含 AUTOMERGE_GH_BIN 的分类脚本 step")


def guard_ns() -> dict:
    """把真脚本 exec 进独立命名空间（`__name__` 非 __main__ ⇒ 不触发 main()）。"""
    ns: dict = {"__name__": "automerge_bot_guard_under_test"}
    exec(compile(bot_script(), str(WORKFLOW) + "::guard", "exec"), ns)  # noqa: S102
    return ns


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1：bot + 只改 uses 版本 tag ⇒ arm
# ══════════════════════════════════════════════════════════════════════════════
class TestCriterion1WorkflowUsesTagOnly:
    def test_bot_uses_tag_only_arms(self, tmp_path):
        """`#4475` 的真实形态：只改 `uses: ...@v7` → `@v8`。"""
        run = run_guard(tmp_path, [wf_file()], title=WF_TITLE)
        assert run.proc.returncode == 0, run.proc.stderr
        assert run.armed, run.summary
        assert run.code() == "ARMED"
        assert run.field("CLASS") == "WORKFLOW_USES_TAG_ONLY"

    def test_two_workflow_files_uses_tag_only_arms(self, tmp_path):
        """`#4470` 的真实形态：两个 workflow 文件各改一处 uses tag。"""
        run = run_guard(
            tmp_path,
            [wf_file(".github/workflows/post-deploy-eval.yml", "v3", "v4",
                     "docker/setup-buildx-action"),
             wf_file(".github/workflows/xiaobu-acceptance.yml", "v7", "v8")],
            title="chore(deps): bump docker/setup-buildx-action from 3 to 4")
        assert run.armed, run.summary

    def test_pinned_sha_tag_change_arms(self, tmp_path):
        """tag 也可以是 40 位 sha（dependabot 的 pin 形态）—— 只 tag 变即安全。"""
        run = run_guard(
            tmp_path,
            [wf_file(old="11bd71901bbe5b1630ceea73d27597364c9af683",
                     new="08c6903cd8c0fde910a37f88322edcfb5dd907a8")],
            title="chore(deps): bump actions/checkout from 4 to 5")
        assert run.armed, run.summary


# ══════════════════════════════════════════════════════════════════════════════
# 判据 2：bot + patch/minor ⇒ arm；major ⇒ 不 arm
# ══════════════════════════════════════════════════════════════════════════════
PATCH_TITLE = "chore(deps): bump pyjwt from 2.13.0 to 2.14.0 in /backend/ai-agent-service"


class TestCriterion2PatchMinorArmsMajorDoesNot:
    @pytest.mark.parametrize("title,old,new,expect", [
        # patch
        ("chore(deps-dev): bump @testing-library/react from 16.3.2 to 16.3.3 in /frontend/admin-web",
         "16.3.2", "16.3.3", True),
        # minor（同 major）
        (PATCH_TITLE, "2.13.0", "2.14.0", True),
        # pip 的 `update ... requirement from >=A to >=B` 形态
        ("chore(deps): update dashscope requirement from >=1.27.4 to >=1.27.5 in /backend/ai-agent-service",
         ">=1.27.4", ">=1.27.5", True),
        # major ⇒ 留人工（仓库原本跳过 bot PR 的真实理由：半套升级/大版本破坏）
        ("chore(deps-dev): bump eslint from 8.57.1 to 10.10.0 in /frontend/admin-web",
         "8.57.1", "10.10.0", False),
        ("chore(deps): bump numpy from 1.26.4 to 2.5.3 in /backend/ai-agent-service",
         "1.26.4", "2.5.3", False),
        # 多包 / 无 from-to ⇒ 解析不出 ⇒ fail-closed（`#4478` 的真实形态）
        ("chore(deps): bump react-dom and @types/react-dom in /frontend/admin-web", "", "", False),
        # 版本回退 ⇒ fail-closed
        ("chore(deps): bump pyjwt from 2.14.0 to 2.13.0 in /backend/ai-agent-service",
         "2.14.0", "2.13.0", False),
    ])
    def test_version_kind_decides_arming(self, tmp_path, title, old, new, expect):
        files = [dep_file(old=old, new=new)] if old else [dep_file()]
        run = run_guard(tmp_path, files, title=title)
        assert run.armed is expect, f"{title} ⇒ {run.summary}"
        if expect:
            assert run.field("CLASS") == "DEP_PATCH_OR_MINOR"

    def test_major_only_mutation_turns_it_red(self, tmp_path):
        """**变异**：同一夹具、只把 `to` 版本从 patch 改成 major ⇒ 结论翻转。"""
        ok = run_guard(tmp_path / "a", [dep_file(old="2.13.0", new="2.14.0")], title=PATCH_TITLE)
        assert ok.armed and ok.field("CLASS") == "DEP_PATCH_OR_MINOR"
        mutated = run_guard(
            tmp_path / "b", [dep_file(old="2.13.0", new="3.0.0")],
            title="chore(deps): bump pyjwt from 2.13.0 to 3.0.0 in /backend/ai-agent-service")
        assert not mutated.armed
        assert mutated.code() == "VERSION_MAJOR"

    def test_title_lies_about_version_turns_it_red(self, tmp_path):
        """**变异**：标题说是 patch，但 diff 里没有那个版本字面量 ⇒ 不 arm（不信标题）。"""
        run = run_guard(tmp_path, [dep_file(old="2.13.0", new="2.14.0", omit_new=True)],
                        title=PATCH_TITLE)
        assert not run.armed
        assert run.code() == "TITLE_PATCH_MISMATCH"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 3：bot + 新增 workflow 文件 ⇒ 不 arm
# ══════════════════════════════════════════════════════════════════════════════
class TestCriterion3AddedWorkflowFile:
    def test_added_workflow_file_does_not_arm(self, tmp_path):
        added = wf_file(name=".github/workflows/brand-new.yml", status="added")
        added["patch"] = ("@@ -0,0 +1,5 @@\n"
                          "+name: Brand New\n+on: push\n+jobs:\n+  x:\n+    steps: []\n")
        run = run_guard(tmp_path, [added], title=WF_TITLE)
        assert not run.armed
        assert run.code() == "FILE_ADDED_OR_REMOVED"

    def test_deleted_workflow_file_does_not_arm(self, tmp_path):
        run = run_guard(tmp_path, [wf_file(status="removed")], title=WF_TITLE)
        assert not run.armed
        assert run.code() == "FILE_ADDED_OR_REMOVED"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 4：bot + diff 新增 secrets.* ⇒ 不 arm
# ══════════════════════════════════════════════════════════════════════════════
class TestCriterion4NewSecretsReference:
    def test_new_secrets_reference_does_not_arm(self, tmp_path):
        f = wf_file()
        f["patch"] += "+          NEW_TOKEN: ${{ secrets.MY_NEW_SECRET }}\n"
        f["patch"] += "-          OLD_TOKEN: literal\n"
        run = run_guard(tmp_path, [f], title=WF_TITLE)
        assert not run.armed
        assert run.code() == "SECRETS_ADDED"

    def test_secrets_added_is_checked_before_uses_only(self, tmp_path):
        """**变异**：把 secrets 行换成普通非 uses 行 ⇒ 拒绝码从 SECRETS_ADDED 变成 NOT_USES_ONLY。

        证明两个判据**各自独立**（不是"一起红"）。
        """
        f = wf_file()
        f["patch"] += "+          NEW_TOKEN: plain-text\n"
        f["patch"] += "-          OLD_TOKEN: literal\n"
        run = run_guard(tmp_path, [f], title=WF_TITLE)
        assert not run.armed
        assert run.code() == "NOT_USES_ONLY"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 5：bot + block/merge 标签 ⇒ 不 arm
# ══════════════════════════════════════════════════════════════════════════════
class TestCriterion5BlockMergeLabel:
    def test_block_merge_label_does_not_arm(self, tmp_path):
        run = run_guard(tmp_path, [wf_file()], labels="role/qa,block/merge", title=WF_TITLE)
        assert not run.armed
        assert run.code() == "BLOCK_LABEL"

    def test_other_labels_do_not_block(self, tmp_path):
        """反向：只有 `block/merge` 是人工闸，别的标签不得拦住。"""
        run = run_guard(tmp_path, [wf_file()], labels="role/qa,type/chore", title=WF_TITLE)
        assert run.armed, run.summary

    def test_bot_job_if_excludes_block_merge(self):
        """job 级 `if:` 也含人工闸（纵深防御：带标签时 job 根本不跑）。"""
        assert "!contains(github.event.pull_request.labels.*.name, 'block/merge')" in bot_job()["if"]


# ══════════════════════════════════════════════════════════════════════════════
# 判据 6：bot + required 检查判红 ⇒ 不 arm
# ══════════════════════════════════════════════════════════════════════════════
class TestCriterion6Checks:
    def test_required_check_failure_does_not_arm_and_does_not_use_the_unstable_exception(self, tmp_path):
        """required 判红（实测形态：`admin-web typecheck + unit tests` = fail）⇒ GitHub 报
        `mergeStateStatus=BLOCKED` ⇒ 不 arm，**且不得落进 UNSTABLE 例外**。"""
        run = run_guard(tmp_path, [wf_file()], checks_json=FAIL_CHECKS, merge_state="BLOCKED",
                        title=WF_TITLE)
        assert not run.armed, run.summary
        assert run.code() == "CHECKS_FAILED"
        assert "UNSTABLE" not in run.summary, "required 判红却走了非 required 例外"
        assert "admin-web typecheck + unit tests" in run.summary

    def test_all_green_arms(self, tmp_path):
        """反向（不得恒红）：全绿 + CLEAN ⇒ arm。"""
        run = run_guard(tmp_path, [wf_file()], checks_json=GREEN_CHECKS, merge_state="CLEAN",
                        title=WF_TITLE)
        assert run.armed, run.summary
        assert run.field("CHECKS") == "CHECKS_GREEN"

    def test_stale_non_required_red_still_arms(self, tmp_path):
        """**判据 6 的口径红证**：非 required 陈旧红 + `mergeStateStatus=UNSTABLE` ⇒ arm。

        实测（#5077 ③）：dependabot PR 上恒有一条非 required 的 `Reconcile and dispatch
        missing deploys` 判红。若把它当成"required 判红"处理，#4475/#4471/#4469 依然不 arm
        ⇒ 本包零生效。**变异**：把 state 从 UNSTABLE 改成 BLOCKED ⇒ 立刻不 arm。
        """
        run = run_guard(tmp_path / "a", [wf_file()], checks_json=STALE_NONREQUIRED_CHECKS,
                        merge_state="UNSTABLE", title=WF_TITLE)
        assert run.armed, run.summary
        assert run.field("CHECKS") == "CHECKS_UNSTABLE_NONREQUIRED"

        mutated = run_guard(tmp_path / "b", [wf_file()], checks_json=STALE_NONREQUIRED_CHECKS,
                            merge_state="BLOCKED", title=WF_TITLE)
        assert not mutated.armed
        assert mutated.code() == "CHECKS_FAILED"

    def test_unreadable_checks_fail_closed(self, tmp_path):
        """读不到检查状态 ⇒ fail-closed（`3` 不当 `0` 读，同 `scripts/merge_gate.py` 口径）。"""
        run = run_guard(tmp_path, [wf_file()], checks_raw="", checks_exit=7, merge_state="CLEAN",
                        title=WF_TITLE)
        assert not run.armed
        assert run.code() == "CHECKS_UNREADABLE"

    def test_unreadable_file_list_fails_closed(self, tmp_path):
        run = run_guard(tmp_path, [], api_exit=1, title=PATCH_TITLE)
        assert not run.armed
        assert run.code() == "GH_API_FAILED"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 7：非 bot（人类 PR）路径逐字不变 —— 回归守卫
# ══════════════════════════════════════════════════════════════════════════════
class TestCriterion7NonBotPathUnchanged:
    def test_nonbot_if_block_is_byte_identical(self):
        assert ORIGINAL_NONBOT_IF_RAW in workflow_text(), (
            "非 bot job 的 `if:` 被改动了 —— 人类 PR 的既有行为必须逐字不变")

    def test_nonbot_run_block_is_byte_identical(self):
        assert ORIGINAL_NONBOT_RUN_RAW in workflow_text(), (
            "非 bot job 的合并 step 被改动了 —— 人类 PR 的既有行为必须逐字不变")

    def test_nonbot_job_shape_unchanged(self):
        job = workflow_yaml()["jobs"][NONBOT_JOB]
        assert job["name"] == "Enable auto-merge"
        assert [s.get("name") for s in job["steps"]] == [
            "Checkout", "Enable native auto-merge (squash)"]
        assert job["steps"][1]["env"]["GH_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"

    def test_two_jobs_are_disjoint_on_author_type(self):
        """两个 job 的作者类型条件必须互斥 ⇒ 任一 PR 只可能走一条路径。"""
        assert "github.event.pull_request.user.type == 'Bot'" in bot_job()["if"]
        assert "github.event.pull_request.user.type != 'Bot'" in workflow_yaml()["jobs"][NONBOT_JOB]["if"]

    def test_bot_job_keeps_all_existing_guardrails(self):
        cond = bot_job()["if"]
        for clause in ("github.event.pull_request.base.ref == 'main'",
                       "github.event.pull_request.draft == false",
                       "github.event.pull_request.head.repo.full_name == github.repository",
                       "!contains(github.event.pull_request.labels.*.name, 'block/merge')"):
            assert clause in cond, f"bot 路径丢了既有护栏：{clause}"

    def test_nonbot_if_mutation_turns_the_assertion_red(self):
        """**变异红证**：把 bot 排除子句删掉 ⇒ `ORIGINAL_NONBOT_IF_RAW` 不再是文件子串。

        这是判据 7 的"能单独变红"证明（不读断言自己的文案，读的是**真文件文本**）。
        """
        mutated = workflow_text().replace(
            "      github.event.pull_request.user.type != 'Bot' &&\n", "")
        assert ORIGINAL_NONBOT_IF_RAW not in mutated
        # 语义上确认改的正是**非 bot job 的 if**（不是别处同名字符串）
        assert "user.type != 'Bot'" not in yaml.safe_load(mutated)["jobs"][NONBOT_JOB]["if"]


# ══════════════════════════════════════════════════════════════════════════════
# 判据 8：每条判据都能**单独**变红 —— 对真脚本做**单点源码变异**
# ══════════════════════════════════════════════════════════════════════════════
def mutate(source: str, old: str, new: str) -> str:
    assert old in source, f"变异锚点不存在（脚本已漂移）：{old!r}"
    return source.replace(old, new, 1)


class TestGuardMutationsProveDiscriminatingPower:
    """把守卫的**某一条**判据改坏 ⇒ 对应的红证**必须**变红（否则那条红证 = 空断言）。

    注入点是**脚本源码文本**（不是断言自己的文案）⇒ 避开「判据被自己的文案喂绿」。
    """

    def test_c1_removing_tag_change_judge_kills_the_red_proof(self, tmp_path):
        """打掉「tag 必须有实际变化」⇒ 判据 1 的 `NO_TAG_CHANGE` 红证变红（变成 arm）。"""
        src = mutate(bot_script(),
                     'if [m.group(2) for m in a_uses] == [m.group(2) for m in r_uses]:',
                     "if False:")
        run = run_guard(tmp_path, [wf_file(old="v8", new="v8")], title=WF_TITLE, script=src)
        assert run.armed, "去掉 NO_TAG_CHANGE 判据后仍不 arm ⇒ 该红证没有判别力"

    def test_c2_removing_major_gate_kills_the_red_proof(self, tmp_path):
        """打掉 major 闸 ⇒ 判据 2 的 `VERSION_MAJOR` 红证变红。"""
        src = mutate(bot_script(), "if new[0] != old[0]:", "if False:")
        run = run_guard(tmp_path, [dep_file(old="2.13.0", new="3.0.0")],
                        title="chore(deps): bump pyjwt from 2.13.0 to 3.0.0 in /backend/ai-agent-service",
                        script=src)
        assert run.armed, "去掉 major 闸后仍不 arm ⇒ 该红证没有判别力"

    def test_c3_removing_status_gate_kills_the_red_proof(self, tmp_path):
        """打掉「只接受 modified」⇒ 判据 3 的 `FILE_ADDED_OR_REMOVED` 红证变红。"""
        src = mutate(bot_script(), 'if f.get("status") != "modified":', "if False:")
        run = run_guard(tmp_path, [wf_file(name=".github/workflows/brand-new.yml", status="added")],
                        title=WF_TITLE, script=src)
        assert run.armed, "去掉 status 闸后仍不 arm ⇒ 该红证没有判别力"

    def test_c4_removing_secrets_gate_kills_the_red_proof(self, tmp_path):
        """打掉 secrets 闸 ⇒ 判据 4 的 `SECRETS_ADDED` 红证变红。

        夹具用**非 workflow 文件**（否则会先被 uses-only 判据拦下，无法证明 secrets 闸本身有判别力）。
        """
        src = mutate(bot_script(),
                     'if line.startswith("+") and not line.startswith("+++") and SECRETS_RE.search(line):',
                     "if False:")
        run = run_guard(tmp_path,
                        [dep_file(old="2.13.0", new="2.14.0", comment="  # ${{ secrets.FOO }}")],
                        title=PATCH_TITLE, script=src)
        assert run.armed, "去掉 secrets 闸后仍不 arm ⇒ 该红证没有判别力"

    def test_c5_removing_label_gate_kills_the_red_proof(self, tmp_path):
        """打掉 block/merge 闸 ⇒ 判据 5 的 `BLOCK_LABEL` 红证变红。"""
        src = mutate(bot_script(), 'if "block/merge" in LABELS:', "if False:")
        run = run_guard(tmp_path, [wf_file()], labels="block/merge", title=WF_TITLE, script=src)
        assert run.armed, "去掉标签闸后仍不 arm ⇒ 该红证没有判别力"

    def test_c6_relaxing_unstable_exception_kills_the_required_red_proof(self, tmp_path):
        """**把例外条件放宽成「只要有 fail 也 arm」⇒ required 判红红证必须变红。**

        这是 `mergeStateStatus == UNSTABLE` 这个例外**不是后门**的证明：
        一旦它被放宽成无条件，`TestCriterion6Checks.test_required_check_failure_*` 立刻失去判别力。
        """
        src = mutate(bot_script(), 'if state == "UNSTABLE":', "if True:")
        run = run_guard(tmp_path, [wf_file()], checks_json=FAIL_CHECKS, merge_state="BLOCKED",
                        title=WF_TITLE, script=src)
        assert run.armed, "例外被放宽成无条件后仍不 arm ⇒ 判据 6 的红证没有判别力"


# ══════════════════════════════════════════════════════════════════════════════
# 结构 / 硬约束守卫
# ══════════════════════════════════════════════════════════════════════════════
class TestWorkflowStructureAndHardConstraints:
    def test_workflow_is_valid_yaml(self):
        assert workflow_yaml()["name"] == "Auto Merge"

    def test_no_new_secrets_reference_was_introduced(self):
        """本 PR 的硬约束：**不得新增 `secrets.*` 引用**（`Danger Scan` 会 BLOCK）。

        bot job 用 `github.token`（= 内置 GITHUB_TOKEN，同一凭据）⇒ 全文 `secrets.` 仍**只有**
        既有的那一处。
        """
        text = workflow_text()
        # 只数**真正的 secrets 引用形态**（`${{ secrets.NAME }}`），不数注释/正则里的字面量
        refs = re.findall(r"\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}", text)
        assert refs == ["GITHUB_TOKEN"], f"新增了 secrets.* 引用（硬约束禁止）：{refs}"
        assert ORIGINAL_SECRETS_LINE in text

    def test_bot_job_uses_github_token_context(self):
        env = bot_job()["steps"][-1]["env"]
        assert env["GH_TOKEN"] == "${{ github.token }}"

    def test_bot_job_passes_title_and_labels(self):
        env = bot_job()["steps"][-1]["env"]
        assert "github.event.pull_request.title" in env["PR_TITLE"]
        assert "labels" in env["PR_LABELS"]

    def test_bot_job_does_not_checkout_pr_head(self):
        """`pull_request_target` 下不得 checkout PR 代码（否则 = 在特权上下文跑不可信代码）。"""
        for step in bot_job()["steps"]:
            if step.get("uses", "").startswith("actions/checkout"):
                with_ = step.get("with") or {}
                assert "ref" not in with_, "不得 checkout 指定 ref（PR head）"

    def test_guard_script_is_fail_closed_by_default(self):
        """脚本不得在任何路径上 `exit 1` 造红（未 arm 是正常结局，不是 CI 失败）。"""
        assert "sys.exit(1)" not in bot_script()

    def test_guard_exits_zero_when_not_arming(self, tmp_path):
        run = run_guard(tmp_path, [wf_file(status="added")], title=WF_TITLE)
        assert run.proc.returncode == 0
        assert not run.armed

    def test_summary_states_why_it_did_not_arm(self, tmp_path):
        """fail-closed 的理由必须**可行动**（不是"看起来安全"）。"""
        run = run_guard(tmp_path, [wf_file(status="added")], title=WF_TITLE)
        assert "CODE=FILE_ADDED_OR_REMOVED" in run.summary
        assert "REASON=" in run.summary
        assert "处置=" in run.summary
        assert run.field("REASON")

    def test_every_rejection_code_is_reachable_and_has_a_cure(self):
        """每个拒绝码都必须有「可行动」的处置文案（否则 summary 只是噪音）。"""
        action = guard_ns()["ACTION"]
        for required in ("BLOCK_LABEL", "GH_API_FAILED", "NO_FILES", "FILE_ADDED_OR_REMOVED",
                         "SECRETS_ADDED", "PATCH_UNAVAILABLE", "NOT_USES_ONLY",
                         "ACTION_NAME_CHANGED", "NO_TAG_CHANGE", "MIXED_SURFACE",
                         "TITLE_UNPARSEABLE", "NO_VERSION_CHANGE", "VERSION_DOWNGRADE",
                         "VERSION_MAJOR", "TITLE_PATCH_MISMATCH", "CHECKS_UNREADABLE",
                         "CHECKS_FAILED", "MERGE_CMD_FAILED", "ARMED"):
            assert required in action, f"拒绝码 {required} 没有可行动处置文案"
            assert action[required].strip(), f"拒绝码 {required} 的处置文案为空"

    def test_every_action_code_is_actually_emitted_somewhere(self):
        """反向：`ACTION` 里的码不得是死条目（每个都必须真的可能被打印）。"""
        src = bot_script()
        for code in guard_ns()["ACTION"]:
            if code == "ARMED":
                continue
            assert f'"{code}"' in src, f"拒绝码 {code} 在脚本里从未被产出（死条目）"

    def test_mixed_surface_does_not_arm(self, tmp_path):
        run = run_guard(tmp_path, [wf_file(), dep_file()], title=WF_TITLE)
        assert not run.armed
        assert run.code() == "MIXED_SURFACE"

    def test_workflow_files_only_but_empty_patch_fails_closed(self, tmp_path):
        run = run_guard(tmp_path, [{"filename": ".github/workflows/x.yml", "status": "modified"}],
                        title=WF_TITLE)
        assert not run.armed
        assert run.code() == "PATCH_UNAVAILABLE"

    def test_action_name_change_does_not_arm(self, tmp_path):
        f = wf_file()
        f["patch"] = f["patch"].replace("+      - uses: actions/download-artifact@v8",
                                        "+      - uses: actions/upload-artifact@v8")
        run = run_guard(tmp_path, [f], title=WF_TITLE)
        assert not run.armed
        assert run.code() == "ACTION_NAME_CHANGED"

    def test_unchanged_tag_does_not_arm(self, tmp_path):
        run = run_guard(tmp_path, [wf_file(old="v8", new="v8")], title=WF_TITLE)
        assert not run.armed
        assert run.code() == "NO_TAG_CHANGE"
