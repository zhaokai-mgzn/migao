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
| 8 | **静态不变式**：只挂 `pull_request_target`（带 `types` + `branches: [main]`）、**无 `paths`**、job 级**无 `if`/`needs`**、checkout **只取 base**、`permissions` 全只读、两道判定都调**既有实现** | 逐个注入 ⇒ 判据 9 各条非空 |
| 9 | **判别力自证**：8 种注入（加 `paths` / 加 job `if` / 加 `needs` / 检出 head / 加 `pull_request` 面 / 改写权限 / 去掉 `--no-remediate` / 改 job 名）各自必红 | 判据函数退化成恒空 ⇒ 判据 9 红 |

## 边界（照实登记）

- **不判「内容来源」**：外部代码被维护者**用自己的身份**重新提交时，作者面看不出异常
  （该形态靠 `sensitive_path_guard` 的敏感面 + 人工评审，见 issue #8386 的同款边界）。
- 豁免是**流程护栏，不是安全边界**：加标签需要 write 权限，但获得 write 的人本就能改一切。
- 判据**不跑网络**：纯函数 + 静态 YAML，CLI 的真实 API 路径由 CI 自己跑。
"""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github" / "scripts" / "sensitive_path_guard.py"
WORKFLOW = REPO / ".github" / "workflows" / "contribution-gate.yml"
AUTHORSHIP = REPO / "scripts" / "external_authorship_guard.py"

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
        "改 job 名": lambda doc: _job(doc).__setitem__("name", "x"),
    }
    for title, fn in mutations.items():
        assert mutate(fn), f"注入未被判红：{title}"
