# case_ids: MC-126
"""外部作者守卫的常驻判据（issue #8386）。

## 治的形态（真实事故，不是假想）

外部账号 `llwand1`（非协作者）的 fork PR #6897 关闭未合并，但同日被搬到**同仓分支**
以 PR #6924 重开并 squash 合并 ⇒ 陌生账号的代码进入 main；squash 后 `git log` 看不到原作者。
`automerge.yml` 只排 fork PR，这条路径在它眼里与自研 PR 无异。

本判据锁 `scripts/external_authorship_guard.py` 的分类器 + 接线：

| # | 判据 | 红证（只改一处即翻转） |
|---|---|---|
| 1 | **真实事故提交必须判红** | 拿掉 `classify()` 的白名单比对 ⇒ 用例 1 红 |
| 2 | 已知账号 / 机器人 / noreply 形态**必须放行** | 把 noreply 分支删掉 ⇒ 用例 2 红 |
| 3 | 陌生 noreply 登录名**必须判红**（不许「凡 noreply 都放行」） | 把 noreply 判定改成「只判后缀」⇒ 用例 3 红 |
| 4 | 白名单**空** ⇒ 拒绝启动（空名单 = 放行一切） | 去掉空名单检查 ⇒ 用例 4 红 |
| 5 | 白名单**通配** ⇒ 拒绝启动（通配 = 名单形同虚设） | 去掉通配检查 ⇒ 用例 5 红 |
| 6 | CLI 离线形态：陌生提交 ⇒ `exit 1` | 分类器恒返回空 ⇒ 用例 6 红 |
| 7 | CLI 离线形态：自家提交 ⇒ `exit 0` | 分类器恒返回违规 ⇒ 用例 7 红 |
| 8 | **fork 来源 ⇒ 无论作者是谁都判红** | 删掉 head-repo 比较 ⇒ 用例 8 红 |
| 9 | **接线**：`pr-check.yml` 有这个 job、有 `timeout-minutes`、真的调用脚本 | 删 job / 改脚本路径 ⇒ 用例 9 红 |
| 10 | 真实白名单**精确且非空**（不许通配、两个协作者在列） | 把 `zhaokai-mgzn` 删掉 ⇒ 用例 10 红 |
| 11 | **PR 作者**不命中 `pr_authors` ⇒ 判红（dependabot 为已知例外） | 删掉 `main` 的 PR 作者检查 ⇒ 用例 11 红 |
| 12 | **类级（#8398）**：workflow 里以机器人身份推提交（`git config user.email`）⇒ 该身份必须在白名单里，否则**该 bot 的每个提交都判红** | 从 `emails` 里删掉 `flaky-bot@users.noreply.github.com` ⇒ 用例 12 红 |

## 边界（照实登记）

- 判不了「内容来源」：外部代码被**本人身份重新提交**时，作者面看不出异常（squash 更看不出）。
- 白名单是自证式的：伪造 team 邮箱可绕过 —— 流程护栏，不是安全边界。
- 本判据不跑网络：CLI 用例全部走 `--commits-json` + `--head-repo` 夹具。
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "external_authorship_guard.py"
ALLOW = REPO / ".github" / "external-authorship-allow.json"
PR_CHECK = REPO / ".github" / "workflows" / "pr-check.yml"
JOB_ID = "external-authorship-guard"
CHECK_NAME = "External Authorship Guard"

# 真实事故提交（llwand1 在 PR #6897 / #6924 里的那一条）
INCIDENT_COMMIT = {
    "sha": "5e1c56f745fe6f7bffb06857098321c95b4e72af",
    "author": {"login": "llwand1"},
    "commit": {"author": {"name": "llwand1", "email": "llwand1@users.noreply.github.com"}},
}
# 自家提交（账号 / 团队邮箱 / noreply 三种形态各一条）
TEAM_COMMITS = [
    {"sha": "1111111", "author": {"login": "zhaokai-mgzn"},
     "commit": {"author": {"name": "guangzhen", "email": "272535866@qq.com"}}},
    {"sha": "2222222", "author": None,
     "commit": {"author": {"name": "赵凯", "email": "zhaokai@migao.com"}}},
    {"sha": "3333333", "author": {"login": "zhaokai-mgzn"},
     "commit": {"author": {"name": "guangzhen", "email": "26737420+zhaokai-mgzn@users.noreply.github.com"}}},
    {"sha": "4444444", "author": {"login": "dependabot[bot]"},
     "commit": {"author": {"name": "dependabot[bot]",
                           "email": "49699333+dependabot[bot]@users.noreply.github.com"}}},
]


def _guard():
    spec = importlib.util.spec_from_file_location("external_authorship_guard_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_cli(
    tmp_path: Path,
    commits: list[dict],
    head_repo: str = "zhaokai-mgzn/migao",
    pr_author: str = "zhaokai-mgzn",
) -> subprocess.CompletedProcess:
    fixture = tmp_path / "commits.json"
    fixture.write_text(json.dumps(commits), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--repo", "zhaokai-mgzn/migao",
            "--pr", "1",
            "--allow-file", str(ALLOW),
            "--commits-json", str(fixture),
            "--head-repo", head_repo,
            "--pr-author", pr_author,
            "--no-remediate",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO),
    )


def test_real_incident_commit_is_flagged():
    guard = _guard()
    logins, emails = guard.load_allowlist(ALLOW)
    violations = guard.classify([INCIDENT_COMMIT], logins, emails)
    assert len(violations) == 1, f"真实事故提交必须判红，实际违规数={len(violations)}"
    assert violations[0]["login"] == "llwand1", f"违规清单必须具名到 llwand1：{violations}"
    assert violations[0]["email"] == "llwand1@users.noreply.github.com"


def test_known_team_identities_are_allowed():
    guard = _guard()
    logins, emails = guard.load_allowlist(ALLOW)
    violations = guard.classify(TEAM_COMMITS, logins, emails)
    assert violations == [], f"自家账号 / 团队邮箱 / 机器人必须放行，误报={violations}"


def test_unknown_noreply_login_is_flagged():
    guard = _guard()
    logins, emails = guard.load_allowlist(ALLOW)
    stranger = {
        "sha": "9999999",
        "author": {"login": "some-stranger"},
        "commit": {"author": {"name": "s", "email": "88888888+some-stranger@users.noreply.github.com"}},
    }
    violations = guard.classify([stranger], logins, emails)
    assert len(violations) == 1, "陌生 noreply 登录名必须判红（不许「凡 noreply 都放行」）"
    assert violations[0]["login"] == "some-stranger"


def test_empty_allowlist_is_refused(tmp_path: Path):
    guard = _guard()
    empty = tmp_path / "allow.json"
    empty.write_text(json.dumps({"logins": [], "emails": ["x@y.z"]}), encoding="utf-8")
    try:
        guard.load_allowlist(empty)
    except ValueError as exc:
        assert "空" in str(exc) or "logins" in str(exc), f"空名单必须报出可读原因：{exc}"
    else:
        raise AssertionError("空名单必须拒绝启动（fail-closed），实际被放行了")


def test_wildcard_allowlist_is_refused(tmp_path: Path):
    guard = _guard()
    wildcard = tmp_path / "allow.json"
    wildcard.write_text(json.dumps({"logins": ["*"], "emails": []}), encoding="utf-8")
    try:
        guard.load_allowlist(wildcard)
    except ValueError as exc:
        assert "通配" in str(exc), f"通配必须报出可读原因：{exc}"
    else:
        raise AssertionError("通配白名单必须拒绝启动，实际被放行了")


def test_cli_flags_foreign_commit_offline(tmp_path: Path):
    result = _run_cli(tmp_path, [INCIDENT_COMMIT])
    assert result.returncode == 1, f"陌生提交必须 exit 1（实际 {result.returncode}）：{result.stdout}{result.stderr}"
    assert "llwand1" in result.stdout, "判红输出必须具名到账号"


def test_cli_allows_team_commit_offline(tmp_path: Path):
    result = _run_cli(tmp_path, TEAM_COMMITS)
    assert result.returncode == 0, f"自家提交必须 exit 0（实际 {result.returncode}）：{result.stdout}{result.stderr}"


def test_cli_flags_fork_head_repo(tmp_path: Path):
    result = _run_cli(tmp_path, TEAM_COMMITS, head_repo="llwand1/migao")
    assert result.returncode == 1, f"fork 来源必须判红（实际 {result.returncode}）：{result.stdout}"
    assert "fork" in result.stdout, "判红输出必须说明是 fork 来源"


def test_cli_flags_unknown_pr_author_offline(tmp_path: Path):
    result = _run_cli(tmp_path, TEAM_COMMITS, pr_author="llwand1")
    assert result.returncode == 1, f"陌生 PR 作者必须 exit 1（实际 {result.returncode}）：{result.stdout}{result.stderr}"
    assert "PR 作者" in result.stdout, "判红输出必须说明是 PR 作者面"
    assert "llwand1" in result.stdout, "判红输出必须具名到陌生作者"


def test_cli_allows_known_bot_pr_authors_offline(tmp_path: Path):
    for author in ("github-actions[bot]", "dependabot[bot]"):
        result = _run_cli(tmp_path, TEAM_COMMITS, pr_author=author)
        assert result.returncode == 0, f"{author} 必须放行（实际 {result.returncode}）：{result.stdout}{result.stderr}"


def test_missing_pr_authors_is_refused(tmp_path: Path):
    guard = _guard()
    path = tmp_path / "allow.json"
    path.write_text(json.dumps({"logins": ["zhaokai-mgzn"], "emails": []}), encoding="utf-8")
    try:
        guard.load_pr_authors(path)
    except ValueError as exc:
        assert "pr_authors" in str(exc) or "空" in str(exc), f"缺少 pr_authors 必须报出可读原因：{exc}"
    else:
        raise AssertionError("缺少 pr_authors 必须 fail-closed，实际被放行了")


def test_real_allowlist_has_auto_merge_and_pr_author_lists():
    data = json.loads(ALLOW.read_text(encoding="utf-8"))
    assert data["auto_merge_logins"] == ["zhaokai-mgzn", "ciyuantongda", "github-actions[bot]"], (
        f"自动合并白名单必须是两名使用账号 + CI bot：{data.get('auto_merge_logins')}"
    )
    assert set(data["pr_authors"]) == {
        "zhaokai-mgzn", "ciyuantongda", "github-actions[bot]", "dependabot[bot]",
    }, f"PR 作者白名单必须含已知 dependabot 例外：{data.get('pr_authors')}"
    for key in ("auto_merge_logins", "pr_authors"):
        assert data[key], f"{key} 不能为空"
        wildcards = [x for x in data[key] if "*" in x or "?" in x]
        assert wildcards == [], f"{key} 不许通配：{wildcards}"


def test_workflow_wires_the_guard():
    workflow = yaml.safe_load(PR_CHECK.read_text(encoding="utf-8"))
    jobs = workflow.get("jobs") or {}
    assert JOB_ID in jobs, f"pr-check.yml 缺少 job `{JOB_ID}` —— 守卫没有接线"
    job = jobs[JOB_ID]
    assert job.get("name") == CHECK_NAME, f"检查名必须稳定为 `{CHECK_NAME}`：{job.get('name')}"
    assert isinstance(job.get("timeout-minutes"), int) and job["timeout-minutes"] > 0, "job 必须声明 timeout-minutes"
    run_text = "\n".join(str(step.get("run") or "") for step in job.get("steps") or [])
    assert "scripts/external_authorship_guard.py" in run_text, "job 必须真的调用守卫脚本"
    # workflow 级不得有 paths 过滤（将来翻 required 的前提；@see tests/unit_ci_workflows/test_required_check_no_paths_filter.py）
    pull_request = (workflow.get("on") or {}).get("pull_request") or {}
    assert not ({"paths", "paths-ignore"} & set(pull_request)), "pr-check 的 on.pull_request 不得带 paths 过滤"


def test_real_allowlist_is_exact_and_covers_known_accounts():
    data = json.loads(ALLOW.read_text(encoding="utf-8"))
    logins = data.get("logins") or []
    emails = data.get("emails") or []
    assert "zhaokai-mgzn" in logins and "ciyuantongda" in logins, f"两个协作者必须在白名单：{logins}"
    assert len(emails) >= 5, f"团队邮箱至少要有 5 条，实际 {len(emails)}"
    wildcards = [x for x in list(logins) + list(emails) if "*" in str(x) or "?" in str(x)]
    assert wildcards == [], f"白名单不许通配：{wildcards}"
    assert "llwand1" not in logins, "事故账号不得出现在白名单里"


# ── 判据 12（类级，issue #8398）：**每个会推提交的机器人身份**都必须在白名单里 ─────────

#: 推提交的身份只有一个来源 = workflow 里的 `git config user.email`（`user.name` 不参与白名单比对）。
BOT_EMAIL_RE = re.compile(r'git\s+config\s+user\.email\s+"?([^"\s]+)"?')
WORKFLOWS = REPO / ".github" / "workflows"


def bot_identity_problems(sources: dict[str, str], allow: dict) -> list[str]:
    """**类级判据**：workflow 里以机器人身份推提交 ⇒ 该身份必须已在白名单里（#8398）。

    病（2026-11-02 **实测**，`Flaky Ledger Reconcile` 每轮判红的真因之一）：
    `external-authorship-allow.json` 的 `logins` 里写着 `migao-flaky-bot`（那是 **git 署名 name**），
    而 `classify()` 只比对 **GitHub 账号 `author.login`** 与 **提交邮箱**，**从不看 name**
    ⇒ `migao-flaky-bot <flaky-bot@users.noreply.github.com>` 这条身份**一条判据都不命中**
    ⇒ `flaky-triage.yml` 追加到台账分支的**每个提交**都被判红 + 打 `block/merge`
    ⇒ 台账 PR 落不了 main ⇒ 分支领先 main 却没有 open PR ⇒ 对账腿每轮报红（#8398 / #6773）。

    同族**尚未爆**的两条（本判据就是为它们设的）：`migao-fixture-bot` / `migao-drift-bot` ——
    它们各自推送后同样会撞上这一堵墙，而那时才发现就又是一轮白烧。

    ⚠️ 有意**只**看 `user.email`：`user.name` 写在白名单里是**空条目**（`classify()` 不读 name），
    所以「加一行 name 就以为放行了」正是本单的病根形态。
    """
    emails = {str(x).strip().lower() for x in (allow.get("emails") or [])}
    logins = {str(x).strip().lower() for x in (allow.get("logins") or [])}
    problems: list[str] = []
    for name, src in sorted(sources.items()):
        for email in sorted(set(BOT_EMAIL_RE.findall(src))):
            normalized = email.strip().lower()
            if normalized in emails:
                continue
            local = normalized.split("@", 1)[0]
            login = local.split("+", 1)[1] if "+" in local else local
            if login in logins:
                continue
            problems.append(
                f"{name}: 机器人身份 `{email}` 未登记进 .github/external-authorship-allow.json 的 "
                f"emails/logins ⇒ 该 bot 推的每个提交都会被 External Authorship Guard 判红（#8398 实证）"
            )
    return problems


def _workflow_sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(WORKFLOWS.glob("*.yml"))}


def test_every_bot_identity_is_allowlisted():
    """三个推提交的机器人身份（flaky / fixture / drift）都必须已在白名单里。"""
    problems = bot_identity_problems(
        _workflow_sources(), json.loads(ALLOW.read_text(encoding="utf-8")))
    assert problems == [], "\n".join(problems)


def test_bot_identity_check_can_go_red():
    """注入式红证：未登记的机器人身份 ⇒ 必红；已登记的同一形态 ⇒ 不红（否则是恒红的空判据）。"""
    allow = json.loads(ALLOW.read_text(encoding="utf-8"))
    known = {"fake.yml": 'git config user.email "flaky-bot@users.noreply.github.com"'}
    assert bot_identity_problems(known, allow) == [], "已登记的身份不该判红（否则同一形态两套口径）"
    stranger = {"fake.yml": 'git config user.email "stranger-bot@users.noreply.github.com"'}
    problems = bot_identity_problems(stranger, allow)
    assert problems and "stranger-bot" in problems[0], "未登记的机器人身份必须判红"


# ── 判据 13（issue #7549 / #8398）：**「判不了」不许落闸** ───────────────────────────

def test_undecidable_does_not_block_merge(monkeypatch):
    """判据 13：读不到（限流 / 网络 / 权限）⇒ 本腿红，但**不许**打 `block/merge` / 解除 auto-merge。

    实测（2026-11-02，PR #8442）：CI 的安装令牌限流
    （`gh: API rate limit exceeded for installation`）让本守卫 exit 3，而原实现在这一支**也**调
    `remediate()` ⇒ 一次**瞬态**失败把 PR 变成**人工闸**（`block/merge` 打上，需人工摘）。
    而那一刻**根本没有违规**：本机用同参数复跑同一守卫 ⇒ `rc=0`。

    ⇒ 落闸只属于**真违规**（下一条判据按住那一半）；「判不了」= 红腿 + 可重跑。
    """
    guard = _guard()
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        guard, "fetch_head_repo",
        lambda *a: (_ for _ in ()).throw(RuntimeError("gh: API rate limit exceeded for installation")),
    )
    monkeypatch.setattr(guard, "remediate", lambda repo, pr: calls.append((repo, pr)) or ["spy"])
    rc = guard.main(["--repo", "zhaokai-mgzn/migao", "--pr", "1", "--allow-file", str(ALLOW)])
    assert rc == guard.EXIT_UNDECIDABLE, f"读不到必须是 exit 3（不得当 0 读），实际 {rc}"
    assert calls == [], "「无法判定」时不许落闸（block/merge / disarm）—— 那会把瞬态变成人工闸"


def test_violation_still_remediates(monkeypatch):
    """判据 13 的**反向对照**：真违规（陌生 PR 作者）⇒ 必须仍然落闸（不许顺手把护栏拆了）。"""
    guard = _guard()
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(guard, "fetch_head_repo", lambda *a: "zhaokai-mgzn/migao")
    monkeypatch.setattr(guard, "fetch_pr_author", lambda *a: "stranger-account")
    monkeypatch.setattr(guard, "fetch_commits", lambda *a: [])
    monkeypatch.setattr(guard, "remediate", lambda repo, pr: calls.append((repo, pr)) or ["spy"])
    rc = guard.main(["--repo", "zhaokai-mgzn/migao", "--pr", "1", "--allow-file", str(ALLOW)])
    assert rc == guard.EXIT_VIOLATION, f"陌生 PR 作者必须判违规，实际 {rc}"
    assert calls, "真违规时必须落闸（否则本条把护栏拆了）"
