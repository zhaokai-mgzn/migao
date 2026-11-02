# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 tests/unit_ci_workflows/test_required_check_no_paths_filter.py 的同款声明。）
"""**Contribution Gate**：不可伪造的外部贡献闸门（issue #8395）。

## 病灶（为什么需要一条 `pull_request_target` 的 required）

仓库公开（`visibility: public`、`allow_forking: true`），而 16 条 required 检查**全部**来自
`pull_request` 型 workflow ⇒ 它们的**执行体就是 PR 里的那份定义**。fork PR 的工作流审批一旦放行，
攻击者再推一个 commit 改 `.github/workflows/pr-check.yml`，就能让 required 检查**名字照旧、一条不跑**。
`External Authorship Guard`（issue #8386）自己也住在 `pr-check.yml` 里、且不在 required 集合
⇒ 「先改 workflow 再伪造」这条路它拦不住。

本 workflow 定义在 **base 分支**、只检出 base（`ref: main`）、不执行任何 PR 代码，判定只读 REST API
⇒ PR 改 workflow 改不动它。两道判定：

| # | 判定 | 实现（**唯一**，不复制） | 红证（只改一处即翻转） |
|---|---|---|---|
| ① | 外部作者 / fork 来源 | `scripts/external_authorship_guard.py`（issue #8386） | 把 `--no-remediate` 换成对 `classify()` 的本地重写 ⇒ 判据 9 红 |
| ② | 敏感路径（`.github/workflows/**` 等） | `.github/scripts/sensitive_path_guard.py` | 放宽任一前缀 / 去掉标签豁免 ⇒ 判据 3~7 各自变红 |

## 判据表

| # | 判据 | 红证（只改一处即翻转） |
|---|---|---|
| 1 | 敏感路径分类的**边界**（目录是前缀、文件是全名；`.github/workflows-archive/` 不算） | 把前缀匹配改成 `in` ⇒ 判据 1 红 |
| 2 | 干净 PR 放行 | 判定恒红 ⇒ 判据 2 红 |
| 3 | 命中敏感面判红且**具名** | 去掉具名 ⇒ 判据 3 红 |
| 4 | `guard/allow-sensitive-paths` 标签解除（写权限才能加） | 去掉标签分支 ⇒ 判据 4 红 |
| 5 | bot 作者豁免（dependabot 升 action 版本） | 去掉 bot 分支 ⇒ 判据 5 红 |
| 6 | 仓库 owner 豁免（维护者自己的 PR） | 去掉 owner 分支 ⇒ 判据 6 红 |
| 7 | **文件清单截断 ⇒ fail-closed**（`changed_files` ≠ 取到的条数） | 去掉长度比较 ⇒ 判据 7 红 |
| 8 | **静态不变式**：只挂 `pull_request_target`（带 `types` + `branches: [main]`）、**无 `paths`**、job 级**无 `if`/`needs`**、checkout **只取 base**、`permissions` 全只读、两道判定都调**既有实现**、**每道判定都经策略层包一层** | 逐个注入 ⇒ 判据 9 各条非空 |
| 9 | **判别力自证**：9 种注入（加 `paths` / 加 job `if` / 加 `needs` / 检出 head / 加 `pull_request` 面 / 改写权限 / 去掉 `--no-remediate` / **去掉限流策略层** / 改 job 名）各自必红 | 判据函数退化成恒空 ⇒ 判据 9 红 |
| 10 | **限流不判红**（`.github/scripts/contribution_gate.py retry`）：可证明是限流 ⇒ 有界重试 3 次；**仍限流 ⇒ exit 0 + 具名 `::warning::`「本次未判定」** | 去掉重试 ⇒ 判据 10「必须重试一次」红；去掉宽容 ⇒ 判据 10「仍限流不判红」红 |
| 11 | **真实命中永不被宽容**：退出码 1 原样判红，**即使输出里含 `rate limit` 字样** | 删掉 `is_provable_rate_limit` 里 `rc == 1` 的短路 ⇒ 判据 11 红 |
| 12 | **非限流读不到仍 fail-closed**：退出码 2 / 3 原样透传（既有口径一字不改） | 把所有非零都当「未判定」⇒ 判据 12 红 |
| 13 | **直连真实接线**（§28.2）：真策略层 → 真 `sensitive_path_guard.py` → 假 `gh`（PATH 注入、不联网）：「限流 ⇒ 绿 + 具名 warning」「重试即成功 ⇒ 绿」「真命中 ⇒ 1」「非限流 ⇒ 2」各一条 | 把 `is_sensitive` 改成恒 False ⇒ 判据 13③ 红 |

## 边界（照实登记）

- **不判「内容来源」**：外部代码被维护者**用自己的身份**重新提交时，作者面看不出异常
  （该形态靠 `sensitive_path_guard` 的敏感面 + 人工评审，见 issue #8386 的同款边界）。
- 豁免是**流程护栏，不是安全边界**：加标签需要 write 权限，但获得 write 的人本就能改一切。
- 判据**不跑网络**：纯函数 + 静态 YAML，CLI 的真实 API 路径由 CI 自己跑。
"""
from __future__ import annotations

import copy
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github" / "scripts" / "sensitive_path_guard.py"
WORKFLOW = REPO / ".github" / "workflows" / "contribution-gate.yml"
AUTHORSHIP = REPO / "scripts" / "external_authorship_guard.py"
POLICY = REPO / ".github" / "scripts" / "contribution_gate.py"

CHECK_NAME = "Contribution Gate (authorship + sensitive paths)"
EXEMPT_LABEL = "guard/allow-sensitive-paths"
JOB_ID = "gate"
ALLOWED_PERMISSIONS = {"contents": "read", "pull-requests": "read"}


def _guard():
    spec = importlib.util.spec_from_file_location("sensitive_path_guard_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _on(doc: dict) -> dict:
    value = doc.get(True, doc.get("on"))
    assert isinstance(value, dict), "workflow 缺 `on:`"
    return value


def _job(doc: dict) -> dict:
    return (doc.get("jobs") or {})[JOB_ID]


def _run_text(doc: dict) -> str:
    return "\n".join(str(step.get("run") or "") for step in _job(doc).get("steps") or [])


# ───────────────────────── ① 敏感路径分类（纯函数） ─────────────────────────

def test_sensitive_boundaries_are_exact() -> None:
    guard = _guard()
    for path in (
        ".github/workflows/pr-check.yml",
        ".github/workflows/nested/any.yml",
        ".github/scripts/sensitive_path_guard.py",
        "deploy/docker-compose.yml",
        "deploy/",
        ".gitleaksignore",
        ".githooks/pre-commit",
        ".github/CODEOWNERS",
    ):
        assert guard.is_sensitive(path), f"应判敏感：{path}"
    for path in (
        "backend/admin-api/pom.xml",
        "docs/deploy.md",
        ".github/workflows-archive/old.yml",
        ".github/workflows",                      # 目录本身不是文件
        ".gitleaksignore.bak",
        ".github/ISSUE_TEMPLATE/bug.md",
        "scripts/some_tool.py",
    ):
        assert not guard.is_sensitive(path), f"不应判敏感：{path}"


def test_clean_pr_is_allowed() -> None:
    allowed, reason = _guard().decide(["backend/a.java", "docs/x.md"], [], "stranger", "User", "owner")
    assert allowed, reason
    assert "未命中敏感路径" in reason


def test_sensitive_paths_fail_and_are_named() -> None:
    guard = _guard()
    allowed, reason = guard.decide(
        [".github/workflows/pr-check.yml", "deploy/x.sh", "backend/a.java"], [], "stranger", "User", "owner"
    )
    assert not allowed, reason
    assert ".github/workflows/pr-check.yml" in reason and "deploy/x.sh" in reason
    assert "backend/a.java" not in reason


def test_exemption_label_unblocks() -> None:
    allowed, reason = _guard().decide(
        [".github/workflows/pr-check.yml"], [EXEMPT_LABEL], "stranger", "User", "owner"
    )
    assert allowed, reason
    assert EXEMPT_LABEL in reason


def test_bot_author_is_exempt() -> None:
    allowed, reason = _guard().decide([".github/workflows/x.yml"], [], "dependabot[bot]", "Bot", "owner")
    assert allowed and "bot" in reason


def test_owner_author_is_exempt() -> None:
    allowed, reason = _guard().decide([".github/workflows/x.yml"], [], "zhaokai-mgzn", "User", "zhaokai-mgzn")
    assert allowed and "owner" in reason


def test_truncated_change_list_fails_closed() -> None:
    allowed, reason = _guard().decide(["backend/a.java"], [], "stranger", "User", "owner", changed_files=3)
    assert not allowed, reason
    assert "无法完整列出" in reason


# ───────────────────────── ② workflow 静态不变式 ─────────────────────────

def _problems(doc: dict) -> list[str]:
    problems: list[str] = []
    on = _on(doc)
    faces = set(on)
    if faces != {"pull_request_target"}:
        problems.append(f"`on:` 只能有 pull_request_target（实际 {sorted(map(str, faces))}）—— 多面会让同名检查的结论不确定")
    prt = on.get("pull_request_target") or {}
    if not isinstance(prt, dict):
        problems.append("pull_request_target 必须是映射（要声明 types / branches）")
        prt = {}
    types = set(prt.get("types") or [])
    want_types = {"opened", "synchronize", "reopened", "labeled", "unlabeled"}
    if not want_types <= types:
        problems.append(f"types 缺 {sorted(want_types - types)}（label 变更必须重跑豁免判定）")
    if prt.get("branches") != ["main"]:
        problems.append("branches 必须恰为 [main]")
    for key in ("paths", "paths-ignore"):
        if key in prt:
            problems.append(f"`{key}` 会把 required 检查遮成永不上报（PR 永久 BLOCKED）")

    job = _job(doc)
    if job.get("name") != CHECK_NAME:
        problems.append(f"job name 必须是 {CHECK_NAME!r}（required context 按名字匹配）")
    for key in ("if", "needs"):
        if key in job:
            problems.append(f"job 级 `{key}` 会让该检查在部分 PR 上永不创建 ⇒ 禁止")
    timeout = job.get("timeout-minutes")
    if not isinstance(timeout, int) or not 1 <= timeout <= 10:
        problems.append("timeout-minutes 必须是 1~10 的整数")

    permissions = doc.get("permissions") or {}
    if permissions != ALLOWED_PERMISSIONS:
        problems.append(f"permissions 必须恰为 {ALLOWED_PERMISSIONS}（只读）")

    steps = job.get("steps") or []
    checkouts = [s for s in steps if str(s.get("uses") or "").startswith("actions/checkout")]
    if not checkouts:
        problems.append("缺 actions/checkout（gh 需要 git 上下文）")
    for step in checkouts:
        with_ = step.get("with") or {}
        if with_.get("ref") != "main":
            problems.append("checkout 必须 `ref: main`（只取 base）")
        if with_.get("persist-credentials") is not False:
            problems.append("checkout 必须 `persist-credentials: false`")

    body = _run_text(doc)
    for needle in ("github.event.pull_request.head", "refs/pull/"):
        if needle in body:
            problems.append(f"run 正文不得引用 {needle}（不许执行/检出 PR 内容）")

    if "scripts/external_authorship_guard.py" not in body:
        problems.append("必须调用既有的 scripts/external_authorship_guard.py（唯一实现，不许重写分类器）")
    if "--no-remediate" not in body:
        problems.append("authorship 步必须 `--no-remediate`（书面解除 auto-merge / 打标签由 pr-check 负责）")
    if ".github/scripts/sensitive_path_guard.py" not in body:
        problems.append("必须调用 .github/scripts/sensitive_path_guard.py")

    # 🔴 「判不了 ≠ 违规」（issue #8395 裁定）：每道判定都必须是**策略层包一层**的形态。
    # 直接跑守卫会让可证明的 API 限流按 fail-closed 变成判红 ⇒ 翻 required 后每次限流窗口
    # 都会锁死所有合并（2026-11-02 实测 4 次假红）⇒ 未包 = 红。
    run_steps = [s for s in steps if str(s.get("run") or "").strip()]
    for step in run_steps:
        if not str(step.get("run") or "").lstrip().startswith(
            "python3 .github/scripts/contribution_gate.py retry"
        ):
            problems.append(
                f"步骤 {step.get('name')!r} 未经 `.github/scripts/contribution_gate.py retry` 包一层"
                "（限流会被按判红处理 ⇒ 翻 required 后锁死合并）"
            )
    if not POLICY.exists():
        problems.append("缺限流策略层 .github/scripts/contribution_gate.py（引用悬空）")
    if not AUTHORSHIP.exists() or not SCRIPT.exists():
        problems.append("被判定的实现文件不存在（引用悬空）")
    return problems


def test_workflow_is_internally_consistent() -> None:
    assert _problems(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))) == []


def test_each_mutation_is_detected() -> None:
    base = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    def mutate(fn) -> list[str]:
        doc = copy.deepcopy(base)
        fn(doc)
        return _problems(doc)

    prt = lambda doc: _on(doc)["pull_request_target"]  # noqa: E731
    mutations = {
        "加 paths 过滤": lambda doc: prt(doc).__setitem__("paths", ["backend/**"]),
        "加 job if": lambda doc: _job(doc).__setitem__("if", "false"),
        "加 job needs": lambda doc: _job(doc).__setitem__("needs", "x"),
        "检出 PR head": lambda doc: _job(doc)["steps"][0]["with"].__setitem__(
            "ref", "${{ github.event.pull_request.head.sha }}"
        ),
        "多挂 pull_request 面": lambda doc: _on(doc).__setitem__("pull_request", {}),
        "改成写权限": lambda doc: doc.__setitem__("permissions", {"contents": "write"}),
        "去掉 --no-remediate": lambda doc: _job(doc)["steps"][1].__setitem__(
            "run", _job(doc)["steps"][1]["run"].replace("--no-remediate", "")
        ),
        "去掉限流策略层": lambda doc: _job(doc)["steps"][1].__setitem__(
            "run",
            "\n".join(
                line
                for line in _job(doc)["steps"][1]["run"].splitlines()
                if "contribution_gate.py" not in line
            ),
        ),
        "改 job 名": lambda doc: _job(doc).__setitem__("name", "x"),
    }
    for title, fn in mutations.items():
        assert mutate(fn), f"注入未被判红：{title}"


# ─────────── ③ 「判不了 ≠ 违规」：限流有界重试 + 不判红（issue #8395 裁定） ───────────
#
# 裁定原文（2026-11-03）：**先证明「判不了 ≠ 违规」在 CI 层不会把 required 变红，再翻 required**。
# 2026-11-02 实测 run 41483003592：`gh: API rate limit exceeded for installation` ⇒ 两道守卫按
# fail-closed 返回 exit 2/3 ⇒ job 判红（当晚共 4 次假红）。下面 5 条单元判据 + 4 条端到端判据
# （直连真实接线，§28.2）各自能单独变红。

def _policy():
    spec = importlib.util.spec_from_file_location("contribution_gate_policy", POLICY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


#: 逐字取自 run 41483003592（2026-11-02 16:35）的失败日志 —— 判据的语料必须是**真实读数**。
RATE_LIMIT_LINE = (
    "⛔ 无法判定（exit 3，**不得当 0 读**）：gh api 取 head 仓库失败：gh: API rate limit "
    "exceeded for installation. If you reach out to GitHub Support for help, please include "
    "the request ID C441:45162:94ED8E:1E8D34A:6AE8BBEC ... (HTTP 403)"
)


def test_rate_limit_detection_boundaries() -> None:
    """「可证明是限流」只认具体标记；退出码 0/1 一律**不**当限流（防「含字样的违规输出」洗白闸门）。"""
    p = _policy()
    assert p.is_provable_rate_limit(3, RATE_LIMIT_LINE)
    assert p.is_provable_rate_limit(2, "HTTP 403\nX-RateLimit-Remaining: 0")
    assert p.is_provable_rate_limit(3, "You have exceeded a secondary rate limit")
    assert not p.is_provable_rate_limit(3, "gh api 失败 rc=1：connection reset by peer")
    assert not p.is_provable_rate_limit(2, "HTTP 403 Resource not accessible by integration")
    # 🔴 真实命中（1）/ 放行（0）**永不**是限流
    assert not p.is_provable_rate_limit(1, RATE_LIMIT_LINE)
    assert not p.is_provable_rate_limit(0, RATE_LIMIT_LINE)


class _Recorder:
    """注入式 runner：按脚本返回 `(rc, output)`，并记录调用次数（数重试次数的唯一办法）。"""

    def __init__(self, responses: list[tuple[int, str]]) -> None:
        self.responses = list(responses)
        self.calls: list[list[str]] = []

    def __call__(self, argv) -> tuple[int, str]:
        self.calls.append(list(argv))
        return self.responses.pop(0)


def test_rate_limited_attempt_is_retried_then_passes(capsys) -> None:
    """① 限流 ⇒ **有界重试**（既不是直接判红、也不是直接宽容）。"""
    p = _policy()
    rec = _Recorder([(3, RATE_LIMIT_LINE), (0, "✅ 全部放行")])
    sleeps: list[float] = []
    rc = p.run_with_retry(["x"], label="外部作者 / fork 来源", run=rec, sleep=sleeps.append)
    assert rc == 0, "重试后通过 ⇒ 绿"
    assert len(rec.calls) == 2, f"必须重试一次（实测 {len(rec.calls)} 次判定）"
    assert len(sleeps) == 1 and sleeps[0] > 0, f"重试必须有退避（实测 {sleeps}）"
    assert "未判定" not in capsys.readouterr().out, "重试已通过就不该播报「本次未判定」"


def test_still_rate_limited_after_bounded_retries_is_not_red(capsys) -> None:
    """① 重试后仍限流 ⇒ **不判红** + 具名 `::warning::`（裁定 ①）。"""
    p = _policy()
    rec = _Recorder([(3, RATE_LIMIT_LINE)] * p.MAX_ATTEMPTS)
    rc = p.run_with_retry(["x"], label="敏感路径", run=rec, sleep=lambda _s: None)
    out = capsys.readouterr().out
    assert rc == 0, f"重试后仍限流 ⇒ 不判红（exit {rc}）"
    assert len(rec.calls) == p.MAX_ATTEMPTS, f"必须**有界**重试（实测 {len(rec.calls)} 次）"
    assert "::warning::" in out, "必须播报 GitHub annotation（不是静默变绿）"
    assert "敏感路径" in out and "未判定" in out, f"warning 必须具名「本次未判定」：{out!r}"


def test_real_violation_is_never_tolerated_even_if_output_mentions_rate_limit() -> None:
    """② 真实命中（exit 1）原样判红 —— 即使输出里恰好含 `rate limit` 字样（**不许**被洗白）。"""
    p = _policy()
    leaky = "❌ PR 改动了敏感面：.github/workflows/pr-check.yml\n(note: API rate limit exceeded upstream)"
    rec = _Recorder([(1, leaky)])
    rc = p.run_with_retry(["x"], label="敏感路径", run=rec, sleep=lambda _s: None)
    assert rc == 1, f"真实命中必须 exit 1（实测 {rc}）"
    assert len(rec.calls) == 1, "真实命中不重试"


def test_non_rate_limit_undecidable_keeps_existing_semantics() -> None:
    """③ 非限流的读不到 ⇒ 原样透传既有退出码（2 / 3 仍判红，fail-closed 不变）。"""
    p = _policy()
    for code in (2, 3):
        rec = _Recorder([(code, "gh api 失败 rc=1：connection reset by peer")])
        rc = p.run_with_retry(["x"], label="x", run=rec, sleep=lambda _s: None)
        assert rc == code, f"exit {code} 必须原样透传（实测 {rc}）"


# ── 直连真实接线（§28.2）：真策略层 → 真守卫 → 假 `gh`（不联网） ──

#: 假 `gh`：按 `$FAKE_GH_MODE` 分形态；每次调用记一个字节到 `$FAKE_GH_CALLS`（用于数重试次数）。
_FAKE_GH = """#!/bin/sh
printf x >> "$FAKE_GH_CALLS"
if [ "$FAKE_GH_MODE" = "rate_limit_always" ]; then
  echo "gh: API rate limit exceeded for installation. (HTTP 403)" >&2
  exit 1
fi
if [ "$FAKE_GH_MODE" = "rate_limit_once" ] && [ ! -f "$FAKE_GH_SEEN" ]; then
  : > "$FAKE_GH_SEEN"
  echo "gh: API rate limit exceeded for installation. (HTTP 403)" >&2
  exit 1
fi
if [ "$FAKE_GH_MODE" = "api_error" ]; then
  echo "gh: HTTP 502 Bad Gateway" >&2
  exit 1
fi
case "$*" in
  *"/files"*) printf '%s\\n' "$FAKE_GH_FILES" ;;
  *"/labels"*) : ;;
  *) printf '{"changed_files": %s}' "$FAKE_GH_CHANGED" ;;
esac
"""


def _run_policy_e2e(tmp_path, *, mode: str, files: str, changed: int = 2):
    """真策略层 + 真 `sensitive_path_guard.py` + 假 `gh`（PATH 注入）⇒ `(proc, gh 调用次数)`。"""
    bins = tmp_path / "bin"
    bins.mkdir(exist_ok=True)
    gh = bins / "gh"
    gh.write_text(_FAKE_GH, encoding="utf-8")
    gh.chmod(0o755)
    calls = tmp_path / "calls"
    env = dict(
        os.environ,
        PATH=f"{bins}{os.pathsep}{os.environ.get('PATH', '')}",
        FAKE_GH_MODE=mode,
        FAKE_GH_FILES=files,
        FAKE_GH_CHANGED=str(changed),
        FAKE_GH_CALLS=str(calls),
        FAKE_GH_SEEN=str(tmp_path / "seen"),
    )
    proc = subprocess.run(
        [
            sys.executable, str(POLICY), "retry", "--label", "敏感路径", "--backoff-seconds", "0", "--",
            sys.executable, str(SCRIPT), "--repo", "owner/repo", "--pr", "7",
            "--author", "stranger", "--author-type", "User", "--owner", "owner",
        ],
        capture_output=True, text=True, env=env, cwd=REPO,
    )
    return proc, (len(calls.read_text()) if calls.exists() else 0)


def test_e2e_rate_limit_is_not_red_and_named(tmp_path) -> None:
    """① 端到端：真守卫遇限流 ⇒ 有界重试 3 次后**不判红** + 具名 warning。"""
    proc, calls = _run_policy_e2e(tmp_path, mode="rate_limit_always", files="backend/a.java")
    assert proc.returncode == 0, f"限流不得判红（rc={proc.returncode}）：\n{proc.stdout}{proc.stderr}"
    assert "::warning::" in proc.stdout and "未判定" in proc.stdout and "敏感路径" in proc.stdout
    assert calls == 3, f"必须是有界重试 3 次（实测 gh 调用 {calls} 次）"


def test_e2e_retry_recovers_within_bound(tmp_path) -> None:
    """① 端到端：第一次限流、重试即成功 ⇒ 绿且**不**播报「未判定」。"""
    proc, calls = _run_policy_e2e(tmp_path, mode="rate_limit_once", files="backend/a.java", changed=1)
    assert proc.returncode == 0, f"重试后应通过：\n{proc.stdout}{proc.stderr}"
    assert "未判定" not in proc.stdout
    assert calls == 4, f"实测应为 1 次限流 + 重试后 3 次成功调用（实测 {calls}）"


def test_e2e_real_sensitive_hit_still_red(tmp_path) -> None:
    """② 端到端：真敏感路径命中 ⇒ exit 1（**不放宽**；红证 = 把 `is_sensitive` 改成恒 False）。"""
    proc, calls = _run_policy_e2e(
        tmp_path, mode="ok", files=".github/workflows/pr-check.yml\nbackend/a.java"
    )
    assert proc.returncode == 1, f"真实命中必须判红（rc={proc.returncode}）：\n{proc.stdout}{proc.stderr}"
    assert ".github/workflows/pr-check.yml" in (proc.stdout + proc.stderr), "判红必须具名"
    assert calls == 3, f"真实命中不重试（实测 gh 调用 {calls} 次）"


def test_e2e_non_rate_limit_read_failure_still_red(tmp_path) -> None:
    """③ 端到端：非限流的读不到 ⇒ 原样透传 exit 2（既有口径），且**不**播报「未判定」。"""
    proc, calls = _run_policy_e2e(tmp_path, mode="api_error", files="backend/a.java")
    assert proc.returncode == 2, f"非限流读不到仍判红（rc={proc.returncode}）：\n{proc.stdout}{proc.stderr}"
    assert "::warning::" not in proc.stdout
    assert calls == 1, f"非限流故障不重试（实测 {calls}）"
