# case_ids: MC-012
r"""
CI workflow 权限不变式（issue #3834）——「失败通知静默」的防复发守卫。

背景（同款三次）
--------------
`permissions:` 一旦在 workflow 顶层显式声明，**未列出的 scope 全部归零**。于是失败
通知步骤（`actions/github-script` 调 `github.rest.issues.create` / `createComment`）
在只声明 `contents: read` 的 workflow 里必然
`Unhandled error: HttpError: Resource not accessible by integration` —— 失败钩子**自己
崩溃**，红而不留痕（人只能手动点 `workflow_dispatch` 才发现）。

- #3270 首发 · #3497 同款第一次复发（`agent-eval.yml` 补 `issues: write`，点修）
- **#3834 同款第二次复发**：`nightly-verification.yml`（run `34909768102` 双 job failure、
  零 issue 留痕、自 2026-09-05 起连红）+ 同类扫描查出 `agent-eval-adversarial.yml`、
  `fixture-record.yml` **仍在静默**。病根同源：`#2659`「workflow 最小权限加固」一次性收窄
  permissions，只有 `agent-eval.yml` 被补回权限，其余漏网（证据：`[Nightly]` 最后一条
  issue 停在 2026-08-29、`[Fixture]` 历史 **0 条**，而 `[E2E Real]`/`[Xiaobu]`（有
  `issues: write`）至今正常留痕）。

判据（本文件 = L0 静态不变式；**读 YAML 真值，不扫全文正则**）
-----------------------------------------------------------
逐 job 计算**有效权限**（job 级 `permissions` 覆盖顶层；`write-all`/`read-all` 字符串按
GitHub 语义展开），比对步骤里**会执行**的文本（`with.script` / `run`；YAML 注释与
`with.body` 不参与，故文档里的示例措辞不会误报）：

| 步骤里出现的调用 | 有效权限必须包含 |
|---|---|
| `issues.create(` · `search.issuesAndPullRequests(` · `gh issue create` · `gh api -X POST <…>/issues` | `issues: write` |
| `issues.createComment(` / `updateComment(` / `addLabels(` · `gh issue comment\|edit\|close\|reopen` · `gh api -X POST\|PATCH <…>/issues/…` | `issues: write` **或** `pull-requests: write` |

REST 形态（`github-script`）与 CLI 形态（`run:` 里的 `gh`）**同属一类**：都是"改了 issue
却没权限 ⇒ 静默失败"，所以同一个守卫一并覆盖（CLI 侧的 `case-draft.yml` / `case-redraft.yml`
此前**没有任何权限断言**，正是漏网位）。

三处**故意**的取舍，防止"稳健判据"退化成假红/假绿：

1. `search.issuesAndPullRequests` 本身只需读权限，这里**从严**要求 `issues: write`：
   在本仓库它只以「失败报告去重守卫」的形态出现（先 search 同标题 open issue → 再
   create/comment），**守卫在而写权限缺 = 正是本 issue 的静默形态**，fail-closed 优先。
2. `createComment` 允许 `pull-requests: write` 兜底：GitHub 对 **PR** 评论只要求 PR 写权限
   （`pr-check.yml` 走的就是这条）——判它红是**假红**，只会逼出无谓的 scope 扩大。
3. 只认**调用形态**（REST 的 token 紧跟 `(`、CLI 的写子命令）：失败说明/日志文案里提到
   `issues.create` 不算调用，否则"解释为什么需要这个权限"的注释会被判违规（假红）。

非空跑保证（每条断言都有红证形态）
--------------------------------
- `test_guard_red_on_prefix_permissions_for_every_repo_workflow`：对**每个**被守卫判绿的
  workflow，把有效权限换成补权限前的 `{contents: read}` 后**必须变红** —— 反证"绿"不是空跑。
- `test_red_proof_3834_prefix_nightly_header`：把 #3834 补权限**之前**的 nightly 头原样喂进
  同一条 audit 路径 → 必须红，并复现 run `34909768102` 的报错链路。
"""
import copy
import re
import textwrap

import pytest
import yaml
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"

# ── 调用表：(op 标签, 匹配模式, 可满足该调用的 scope 之一) ──
# 只认**调用形态**：REST 的 token 紧跟 `(`（真实调用必然是 `github.rest.issues.create({…})`）；
# CLI 的写子命令。仅"提到 op 名"（日志文案/注释里的 "issues.create 需要 issues: write"）
# 不算调用，否则会把"解释失败原因"的文案判成违规 → 逼人改判据或扩大 scope（假红）。
_ONLY_ISSUES = ("issues",)
_ISSUES_OR_PR = ("issues", "pull-requests")
_GH_API_WRITE = r"gh\s+api\b[^\n]*?-X\s*(?:POST|PATCH|PUT|DELETE)\b"

ISSUE_OPS = (
    # 无 PR 等价路径 → 只能靠 issues: write
    ("issues.create", re.compile(r"issues\.create\s*\("), _ONLY_ISSUES),
    ("search.issuesAndPullRequests", re.compile(r"search\.issuesAndPullRequests\s*\("), _ONLY_ISSUES),
    ("gh issue create", re.compile(r"gh\s+issue\s+create\b"), _ONLY_ISSUES),
    ("gh api -X POST <…>/issues", re.compile(_GH_API_WRITE + r"[^\n]*?/issues(?![/\w-])"), _ONLY_ISSUES),
    # 对象可能是 PR → issues: write 或 pull-requests: write 皆可
    ("issues.createComment", re.compile(r"issues\.createComment\s*\("), _ISSUES_OR_PR),
    ("issues.updateComment", re.compile(r"issues\.updateComment\s*\("), _ISSUES_OR_PR),
    ("issues.addLabels", re.compile(r"issues\.addLabels\s*\("), _ISSUES_OR_PR),
    ("gh issue comment|edit|close|reopen",
     re.compile(r"gh\s+issue\s+(?:comment|edit|close|reopen)\b"), _ISSUES_OR_PR),
    ("gh api -X POST|PATCH <…>/issues/…", re.compile(_GH_API_WRITE + r"[^\n]*?/issues/"), _ISSUES_OR_PR),
)


def _load(path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _step_text(step) -> str:
    """步骤里**会执行**的文本：github-script 的 `with.script` + run 步骤的 `run`。

    刻意不读 `with.body` / 原始文件文本 —— 只认"会被执行的代码"，避免把 YAML 注释或
    文案里的示例措辞（#4275 前举例 `agent-behavior-eval.yml`，该文件已删；示例措辞形态不变）
    当成真实调用（假红）。取证形态见 test_mentions_without_call_are_not_flagged。
    """
    if not isinstance(step, dict):
        return ""
    parts = []
    with_ = step.get("with")
    if isinstance(with_, dict) and isinstance(with_.get("script"), str):
        parts.append(with_["script"])
    if isinstance(step.get("run"), str):
        parts.append(step["run"])
    return "\n".join(parts)


def _granted(perms, scope: str) -> bool:
    """permissions 真值是否授予 <scope>: write。

    - dict：`{"issues": "write"}` → True；缺 key / 值为 read / None → False
    - `write-all` → True（GitHub 语义：所有 scope 可写）
    - `read-all` / `{}` / 未声明(None) → False（显式声明即收窄，未列出=归零 → fail-closed）
    """
    if perms == "write-all":
        return True
    if not isinstance(perms, dict):
        return False
    return str(perms.get(scope) or "").lower() == "write"


def _effective_permissions(wf: dict, job: dict):
    """job 级 permissions 覆盖顶层（YAML 真值；二者都没有 → None）。"""
    return job["permissions"] if "permissions" in job else wf.get("permissions")


def _ops_in_job(job: dict) -> dict:
    """job 内命中的 issue 调用 → {op 标签: 可满足的 scope 之一}。"""
    found = {}
    for step in job.get("steps") or []:
        text = _step_text(step)
        if not text:
            continue
        for label, rx, scopes in ISSUE_OPS:
            if rx.search(text):
                found[label] = scopes
    return found


def audit(wf: dict, label: str = "<dict>") -> list:
    """返回违规说明列表（空 = 合规）。纯函数，供测试与人工取证共用。"""
    violations = []
    for job_name, job in (wf.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        hits = _ops_in_job(job)
        if not hits:
            continue
        perms = _effective_permissions(wf, job)
        ok_issues = _granted(perms, "issues")
        ok_pr = _granted(perms, "pull-requests")
        missing_strict = sorted(l for l, s in hits.items() if s == _ONLY_ISSUES and not ok_issues)
        missing_either = sorted(
            l for l, s in hits.items() if s != _ONLY_ISSUES and not (ok_issues or ok_pr)
        )
        if missing_strict or missing_either:
            detail = []
            if missing_strict:
                detail.append(f"必须 `issues: write` 却未授予：{missing_strict}")
            if missing_either:
                detail.append(
                    f"既无 `issues: write` 也无 `pull-requests: write`（issue 评论/标签会 403）："
                    f"{missing_either}"
                )
            violations.append(
                f"{label} :: job `{job_name}` —— " + "；".join(detail)
                + f"（当前 permissions={perms!r}）—— 缺权限时失败通知步骤报 "
                "`HttpError: Resource not accessible by integration` **静默崩溃**"
                "（#3270 首发 / #3497 一次复发 / #3834 二次复发）"
            )
    return violations


def audit_path(path) -> list:
    path = Path(path)
    return audit(_load(path), label=path.name)


def _repo_workflows() -> list:
    return sorted(WORKFLOWS_DIR.glob("*.yml"))


def _strip_effective_permissions(wf: dict) -> dict:
    """把每个有 issue 调用的 job 的有效权限压回 #3834 补权限之前的形态 `{contents: read}`。"""
    mutated = copy.deepcopy(wf)
    for job in (mutated.get("jobs") or {}).values():
        if isinstance(job, dict) and _ops_in_job(job):
            job["permissions"] = {"contents": "read"}
    return mutated


def _write_wf(tmp_path, name: str, perms: dict, step_yaml: str) -> Path:
    """造一个单 job/单 step 的 workflow 文件（夹具；走 audit_path 的真实解析路径）。"""
    perms_yaml = "\n".join(f"  {k}: {v}" for k, v in perms.items())
    body = textwrap.indent(textwrap.dedent(step_yaml).strip(), "      ")
    path = tmp_path / name
    path.write_text(
        f"permissions:\n{perms_yaml}\njobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n{body}\n",
        encoding="utf-8",
    )
    return path


_GITHUB_SCRIPT_STEP = """
- uses: actions/github-script@v9
  with:
    script: |
      await github.rest.issues.create({ title: 'x' })
"""


# ── 主守卫：全仓 workflow 逐文件 ──────────────────────────────────────────────

def test_no_workflow_is_missing_issue_scope():
    """凡调用 issue 写 API 的 workflow，有效权限必须覆盖该调用（本 PR 的核心门禁）。"""
    offenders = []
    for path in _repo_workflows():
        offenders.extend(audit_path(path))
    assert offenders == [], (
        "以下 workflow 调用 issue API 但权限不足（结果 = 失败通知静默，见 #3834）：\n"
        + "\n".join(f"  - {v}" for v in offenders)
    )


@pytest.mark.parametrize("path", _repo_workflows(), ids=lambda p: p.name)
def test_workflow_permissions_are_sufficient(path):
    """逐文件版本：红时直接点名是哪个 workflow（便于 CI 定位）。"""
    violations = audit_path(path)
    assert violations == [], "\n".join(violations)


# ── 非空跑保证：守卫必须能红 ────────────────────────────────────────────────

def test_guard_red_on_prefix_permissions_for_every_repo_workflow():
    """对每个调 issue API 的 workflow：摘掉权限后必须红 ⇒ 守卫不是空断言。

    形态等价于「把本 L0 用例打在 #3834 补权限之前的文件上」。
    """
    checked = []
    for path in _repo_workflows():
        wf = _load(path)
        if not any(_ops_in_job(j) for j in (wf.get("jobs") or {}).values() if isinstance(j, dict)):
            continue
        assert audit_path(path) == [], f"{path.name} 当前应合规（先修权限再谈红证）"
        violations = audit(_strip_effective_permissions(wf), label=path.name)
        assert violations, (
            f"{path.name} 摘掉 issue 权限后守卫仍判绿 —— 该不变式对本文件是**空断言**"
            "（不会红的断言=空断言）"
        )
        checked.append(path.name)
    expected = {
        "e2e-real.yml",              # 失败报告六件套（MC-012）
        "nightly-verification.yml",  # #3834 主犯
        "xiaobu-acceptance.yml",
        "agent-eval.yml",            # #3497 点修过 → 不得回退
        "agent-eval-adversarial.yml",  # #3834 同类扫描查出
        "fixture-record.yml",        # #3834 同类扫描查出
    }
    assert expected <= set(checked), (
        f"失败报告六件套必须被守卫覆盖并逐条验红证，缺：{sorted(expected - set(checked))}"
    )


def test_red_proof_3834_prefix_nightly_header():
    """#3834 红证：补权限之前的 nightly 头（`contents: read`）必红。

    用 run `34909768102` 的真实形态（去重守卫：search → comment / create）复现。
    """
    prefix_header = """
name: Nightly Verification (p1 smoke + fixture e2e)
permissions:
  contents: read
on:
  workflow_dispatch:
jobs:
  e2e-fixture-full:
    name: E2E fixture specs (full, web project)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: Create Issue on failure (dedup guard)
        if: failure()
        uses: actions/github-script@v9
        with:
          script: |
            const { data: search } = await github.rest.search.issuesAndPullRequests({ q })
            if (search.total_count > 0) {
              await github.rest.issues.createComment({ issue_number: search.items[0].number })
            } else {
              await github.rest.issues.create({ title, labels: ['bug', 'role/qa'] })
            }
"""
    violations = audit(yaml.safe_load(prefix_header) or {}, label="nightly-verification.yml(prefix)")
    assert len(violations) == 1, violations
    msg = violations[0]
    assert "issues: write" in msg
    assert "issues.create" in msg and "search.issuesAndPullRequests" in msg
    assert "Resource not accessible by integration" in msg


# ── 判据稳健性：不误报 / 不假绿 ──────────────────────────────────────────────

def test_write_all_is_green_and_read_all_is_red(tmp_path):
    """`write-all` 合法（GH 语义：全 scope 可写）；`read-all` 必须红。"""
    body = textwrap.dedent("""
    jobs:
      j:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/github-script@v9
            with:
              script: |
                await github.rest.issues.create({ title: 'x' })
    """).lstrip()
    write_all = tmp_path / "write-all.yml"
    write_all.write_text("permissions: write-all\n" + body, encoding="utf-8")
    assert audit_path(write_all) == [], "permissions: write-all 是合法写法，不得误报"

    read_all = tmp_path / "read-all.yml"
    read_all.write_text("permissions: read-all\n" + body, encoding="utf-8")
    assert audit_path(read_all), "permissions: read-all 不授予 issue 写权限，必须红"


def test_no_permissions_declaration_is_red(tmp_path):
    """完全未声明 permissions = 依赖仓库默认（read）→ fail-closed 判红。"""
    path = tmp_path / "no-perms.yml"
    path.write_text(
        textwrap.dedent("""
        jobs:
          j:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/github-script@v9
                with:
                  script: |
                    await github.rest.issues.create({ title: 'x' })
        """).strip() + "\n",
        encoding="utf-8",
    )
    assert audit_path(path), "未声明 permissions 时不应假定有写权限（fail-closed）"


def test_pr_comment_only_is_green_with_pull_requests_write(tmp_path):
    """纯 PR 评论路径（对象是 PR）由 `pull-requests: write` 满足 —— 不得假红。

    形态取自 `pr-check.yml`（`issues.createComment` + `context.issue.number`）。
    """
    path = _write_wf(tmp_path, "pr-comment.yml", {"contents": "read", "pull-requests": "write"}, """
    - uses: actions/github-script@v9
      with:
        script: |
          await github.rest.issues.createComment({
            issue_number: context.issue.number, body: 'gate ok',
          })
    """)
    assert audit_path(path) == [], (
        "PR 评论只需 pull-requests: write（GitHub 语义）——判红会逼出无谓的 scope 扩大"
    )


def test_issue_comment_without_any_write_scope_is_red(tmp_path):
    """反向：issue 评论（非 PR 语境）没有任何写权限 → 必须红。"""
    path = _write_wf(tmp_path, "issue-comment.yml", {"contents": "read"}, """
    - uses: actions/github-script@v9
      with:
        script: |
          await github.rest.issues.createComment({ issue_number: 123, body: 'x' })
    """)
    assert audit_path(path), "contents: read 下 issue 评论必然 403 → 必须红"


def test_mentions_without_call_are_not_flagged(tmp_path):
    """**提及**≠**调用**：YAML 注释与日志文案里的 op 名不算违规（防"正则扫全文"假红）。

    真实形态（#4275 前）：`agent-behavior-eval.yml` 的权限注释写着「缺 issues: write 时
    （该文件已删除，此处保留为**历史形态**；判据本体针对存续 workflow）
    issues.create 会 HttpError 静默崩溃」；`post-deploy-eval.yml` 同理。
    """
    path = tmp_path / "comment-only.yml"
    path.write_text(
        textwrap.dedent("""
        # 注释提及 github.rest.issues.create / search.issuesAndPullRequests —— 不是调用
        permissions:
          contents: read
        jobs:
          j:
            runs-on: ubuntu-latest
            steps:
              - name: 只输出失败原因说明的步骤
                uses: actions/github-script@v9
                with:
                  script: |
                    console.log('失败原因：github.rest.issues.create 需要 issues: write')
        """).lstrip(),
        encoding="utf-8",
    )
    assert audit_path(path) == [], (
        "`console.log('… issues.create 需要 issues: write')` 是文案而非调用 —— "
        "误报会逼人改判据而非修权限"
    )


def test_job_level_permissions_override_top_level(tmp_path):
    """YAML 真值：job 级 permissions 覆盖顶层（未列出的 scope 归零）。"""
    path = tmp_path / "job-narrowed.yml"
    path.write_text(
        textwrap.dedent("""
        permissions:
          contents: read
          issues: write
        jobs:
          j:
            runs-on: ubuntu-latest
            permissions:
              contents: read
            steps:
              - uses: actions/github-script@v9
                with:
                  script: |
                    await github.rest.issues.create({ title: 'x' })
        """).lstrip(),
        encoding="utf-8",
    )
    assert audit_path(path), (
        "顶层有 issues: write 但 job 级 permissions 覆盖了它（未列出=归零）→ 必须红"
    )


# ── CLI 形态（run: 里的 gh）：同属一类，一并守卫 ─────────────────────────────

def test_cli_read_only_calls_are_not_flagged(tmp_path):
    """`gh issue view` / `gh issue list` 是读操作 —— 不得误报（形态取自生产 workflow）。"""
    path = _write_wf(tmp_path, "cli-read.yml", {"contents": "read"}, """
    - name: read only
      run: |
        gh issue view "$ISSUE_NUMBER" --json body --jq '.body'
        gh issue list --search 'x in:title'
    """)
    assert audit_path(path) == [], "读操作不需要 issues: write；判红是假红"


def test_cli_issue_create_needs_issues_write(tmp_path):
    """`gh issue create` 无 PR 等价路径 → 只有 pull-requests: write 也必须红。"""
    path = _write_wf(tmp_path, "cli-create.yml", {"contents": "read", "pull-requests": "write"}, """
    - name: notify failure
      run: |
        gh issue create --title "[Fixture] 重录失败" --body "详见 run"
    """)
    assert audit_path(path), "gh issue create 必须 issues: write，pull-requests: write 不能替代"


def test_cli_comment_on_pr_is_green_with_pull_requests_write(tmp_path):
    """`gh issue comment` 打在 PR 上时由 pull-requests: write 满足（pr-check 同形）→ 不假红。"""
    path = _write_wf(tmp_path, "cli-pr-comment.yml", {"contents": "read", "pull-requests": "write"}, """
    - name: comment gate result
      run: |
        gh issue comment "$PR_NUMBER" --body-file /tmp/gate.md
    """)
    assert audit_path(path) == [], "PR 评论只需 pull-requests: write"


def test_cli_issue_write_without_any_write_scope_is_red(tmp_path):
    """`gh issue edit/-X PATCH …/issues/comments` 无任何写权限 → 必须红（case-draft/redraft 形态）。"""
    path = _write_wf(tmp_path, "cli-edit.yml", {"contents": "read"}, """
    - name: label + edit draft comment
      run: |
        gh issue edit "$ISSUE_NUMBER" --add-label "needs-verification"
        gh api -X PATCH "repos/$GITHUB_REPOSITORY/issues/comments/$DRAFT_ID" -f body=x
    """)
    assert audit_path(path), "contents: read 下改 issue 标签/评论必然 403 → 必须红"


def test_cli_comment_scope_check_is_not_vacuous_on_current_workflows():
    """CLI 分支不能是空断言：把 case-draft.yml 的 issues: write 摘掉必须红。"""
    path = WORKFLOWS_DIR / "case-draft.yml"
    wf = _load(path)
    assert audit_path(path) == [], "case-draft.yml 当前应合规"
    mutated = copy.deepcopy(wf)
    mutated["permissions"] = {"contents": "read"}
    assert audit(mutated, label=path.name), "摘掉 case-draft.yml 的 issues: write 后必须红"
