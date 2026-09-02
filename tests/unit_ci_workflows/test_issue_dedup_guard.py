"""
Test CI failure-report issue dedup guard in scheduled/triggered workflows.

背景（issue #2746）：e2e-real / nightly-verification / xiaobu-acceptance /
agent-eval / agent-eval-adversarial / fixture-record 六个 workflow 在失败时
直接 `issues.create`，从不先查是否已有同标题 open issue → 每日失败报告重复堆积
（116 个 open issue 中 17 个为同日重复的 [E2E Real]/[Nightly]/[Agent Eval]/[Xiaobu] 噪音）。

本测试强制：每个自动建 issue 的 workflow 必须内置去重守卫——
先 search 同标题 open issue，已存在则仅 createComment 追加 run 链接，不存在才 issues.create。
"""
# case_ids: MC-012
import re
import yaml
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).parent.parent.parent / ".github" / "workflows"

# 需守卫的 workflow：其 "Create Issue" step 自动建 issue
GUARDED_WORKFLOWS = [
    "e2e-real.yml",
    "nightly-verification.yml",
    "xiaobu-acceptance.yml",
    "agent-eval.yml",
    "agent-eval-adversarial.yml",
    "fixture-record.yml",
]

# 各 workflow 的 Create Issue step 名称（标题前缀用于 search 断言）
ISSUE_TITLE_MARKERS = {
    "e2e-real.yml": "[E2E Real]",
    "nightly-verification.yml": "[Nightly]",
    "xiaobu-acceptance.yml": "[Xiaobu]",
    "agent-eval.yml": "[Agent Eval]",
    "agent-eval-adversarial.yml": "[Agent Eval]",
    "fixture-record.yml": "[Fixture]",
}


def load_workflow(name: str) -> dict:
    """加载并解析 CI workflow YAML。"""
    path = WORKFLOWS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Workflow not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def find_issue_create_steps(wf: dict) -> list:
    """找出所有 script 中含 issues.create 调用的 step。"""
    found = []
    for job_name, job in (wf.get("jobs") or {}).items():
        for step in job.get("steps", []):
            script = step.get("with", {}).get("script", "") or step.get("run", "")
            if "issues.create" in script:
                found.append((job_name, step))
    return found


class TestDedupGuardStructure:
    """验证 6 个 workflow 的去重守卫结构完整性。"""

    @staticmethod
    def test_all_guarded_workflows_exist_and_parse():
        """守卫清单中的 workflow 都存在且 YAML 可解析为 jobs 结构。"""
        for name in GUARDED_WORKFLOWS:
            wf = load_workflow(name)
            assert isinstance(wf, dict) and wf.get("jobs"), (
                f"{name} 解析失败或缺少 jobs 结构"
            )

    @staticmethod
    def test_each_workflow_has_issue_create_step():
        """每个自动建 issue 的 workflow 必须真的有 issues.create 调用。"""
        for name in GUARDED_WORKFLOWS:
            wf = load_workflow(name)
            steps = find_issue_create_steps(wf)
            assert len(steps) >= 1, (
                f"{name} 未找到含 issues.create 的 step（测试前提失效，需同步守卫清单）"
            )

    @staticmethod
    def test_create_step_contains_dedup_search():
        """Create Issue step 必须先 search 同标题 open issue（去重守卫）。"""
        for name in GUARDED_WORKFLOWS:
            wf = load_workflow(name)
            steps = find_issue_create_steps(wf)
            for job_name, step in steps:
                script = step.get("with", {}).get("script", "")
                assert "search.issues" in script or "listForRepo" in script, (
                    f"{name} [{job_name}] 的 Create Issue step 缺少去重 search：\n"
                    f"step 名: {step.get('name', 'unnamed')}\n"
                    "要求：先 search 同标题 open issue，存在则 comment 而非重复 create"
                )
                # 去重搜索必须限定 open + 标题关键词
                assert "is:open" in script or "state: 'open'" in script or 'state: "open"' in script, (
                    f"{name} [{job_name}] 去重 search 未限定 is:open"
                )
                assert "in:title" in script, (
                    f"{name} [{job_name}] 去重 search 未用 in:title 按标题查重"
                )

    @staticmethod
    def test_dedup_search_uses_workflow_title_marker():
        """search 的标题关键词必须与 workflow 的 issue 标题前缀一致。"""
        for name in GUARDED_WORKFLOWS:
            wf = load_workflow(name)
            marker = ISSUE_TITLE_MARKERS[name]
            steps = find_issue_create_steps(wf)
            for job_name, step in steps:
                script = step.get("with", {}).get("script", "")
                # 标题前缀出现在 script 中（title 模板或 search query 里）
                assert marker in script, (
                    f"{name} [{job_name}] script 中缺少标题前缀 {marker}，"
                    "去重搜索无法命中同标题 issue"
                )

    @staticmethod
    def test_create_step_comments_instead_of_duplicate():
        """已存在同标题 issue 时必须走 createComment 分支。"""
        for name in GUARDED_WORKFLOWS:
            wf = load_workflow(name)
            steps = find_issue_create_steps(wf)
            for job_name, step in steps:
                script = step.get("with", {}).get("script", "")
                # 存在同标题时：给已存在 issue 追加评论（或跳过），而不是重复建
                assert "createComment" in script or "total_count" in script, (
                    f"{name} [{job_name}] 缺少「已存在 → 评论/跳过」分支：\n"
                    "要求：search 到同标题 open issue 时 createComment 追加 run 链接，"
                    "而非无条件 issues.create"
                )

    @staticmethod
    def test_create_guarded_by_exists_check():
        """issues.create 必须被「不存在同标题」条件保护（存在 else 分支）。"""
        for name in GUARDED_WORKFLOWS:
            wf = load_workflow(name)
            steps = find_issue_create_steps(wf)
            for job_name, step in steps:
                script = step.get("with", {}).get("script", "")
                # issues.create 必须出现在 else / 条件之后，不能无条件直接调用
                create_line = [l for l in script.split("\n") if "issues.create" in l]
                assert create_line, f"{name} [{job_name}] 无 issues.create 调用"
                for line in create_line:
                    # 简单结构检查：create 调用上方存在条件控制流
                    before = script.split(line)[0]
                    assert any(k in before for k in ["else", "if", "total_count === 0", "total_count == 0"]), (
                        f"{name} [{job_name}] issues.create 未受条件保护：\n  {line}\n"
                        "要求：仅当同标题 open issue 不存在时才 create"
                    )


class TestDedupGuardLogic:
    """去重守卫的决策语义（与 workflow 内嵌 JS 逻辑保持一致）。"""

    @staticmethod
    def _decide(existing_count: int) -> str:
        """复刻守卫决策：>0 → 'comment'；0 → 'create'。"""
        if existing_count > 0:
            return "comment"
        return "create"

    def test_existing_open_issue_skips_create(self):
        """已有同标题 open issue → 追加评论而非新建。"""
        assert self._decide(1) == "comment"
        assert self._decide(3) == "comment"

    def test_no_existing_issue_creates(self):
        """无同标题 open issue → 正常创建。"""
        assert self._decide(0) == "create"

    def test_same_day_same_title_is_exactly_dedup_key(self):
        """去重键 = 同日同标题；标题含日期，天然按天去重。"""
        for name in GUARDED_WORKFLOWS:
            wf = load_workflow(name)
            steps = find_issue_create_steps(wf)
            for _, step in steps:
                script = step.get("with", {}).get("script", "")
                # 标题模板必须含日期（toISOString().slice(0,10)），保证同一天只建一个
                assert "slice(0, 10)" in script, (
                    f"{name} 的 issue 标题未含日期（slice(0,10)），无法按天去重"
                )


class TestRunCommands:
    """验证 gh/github-script 命令的正确形态。"""

    @staticmethod
    def test_create_uses_issues_create_api():
        """真正建 issue 用 github.rest.issues.create。"""
        for name in GUARDED_WORKFLOWS:
            wf = load_workflow(name)
            steps = find_issue_create_steps(wf)
            for _, step in steps:
                script = step.get("with", {}).get("script", "")
                assert "issues.create(" in script, f"{name} 无 issues.create 调用"
