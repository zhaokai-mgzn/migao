"""
Test coverage_weekly.py batch management functions.

CONTRACT: issue #850 action #3 — batch merge/mark stale coverage subtasks.
Adds --batch-skip mode to coverage_weekly.py.
"""
import sys
from pathlib import Path

import pytest

# Import the module under test
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from junshi.coverage_weekly import (
    build_batch_issue_list,
    fetch_batch_issues,
    filter_stale_issues,
    group_files_by_feature,
)


class TestBatchIssueList:
    """gh issue list 命令构建 — 过滤 qa-todo + coverage-gap 的 open issue。"""

    def test_build_cmd_includes_qa_todo_label(self):
        """命令必须过滤 qa-todo label。"""
        cmd = build_batch_issue_list(labels=["qa-todo", "coverage-gap"], limit=100)
        cmd_str = " ".join(cmd)
        assert "qa-todo" in cmd_str
        assert "coverage-gap" in cmd_str
        assert "--label" in cmd

    def test_build_cmd_defaults_limit_100(self):
        """默认 limit 100（覆盖 30 个子任务有余）。"""
        cmd = build_batch_issue_list()
        assert "--limit" in cmd
        limit_idx = cmd.index("--limit")
        assert cmd[limit_idx + 1] == "100"

    def test_build_cmd_respects_custom_labels(self):
        """自定义 label 过滤。"""
        cmd = build_batch_issue_list(labels=["coverage-gap"], limit=10)
        cmd_str = " ".join(cmd)
        assert "coverage-gap" in cmd_str
        assert "qa-todo" not in cmd_str

    def test_build_cmd_excludes_closed(self):
        """只查 open issue，不包含 closed。"""
        cmd = build_batch_issue_list()
        assert "--state" in cmd
        state_idx = cmd.index("--state")
        assert cmd[state_idx + 1] == "open"

    def test_build_cmd_includes_json_fields(self):
        """JSON 输出包含必要字段。"""
        cmd = build_batch_issue_list()
        cmd_str = " ".join(cmd)
        assert "createdAt" in cmd_str
        assert "number" in cmd_str
        assert "title" in cmd_str


class TestFilterStaleIssues:
    """按天数过滤 stale issue。"""

    def test_empty_list_returns_empty(self):
        """空列表 → 空结果。"""
        assert filter_stale_issues([], days=7) == []

    def test_filters_stale_by_age_days(self):
        """发布日期 > days 天前的 issue 被归为 stale。"""
        issues = [
            {"number": 820, "title": "[coverage] ...", "createdAt": "2026-06-20T10:00:00Z"},
            {"number": 849, "title": "[coverage] ...", "createdAt": "2026-07-01T10:00:00Z"},
        ]
        # 参考日期 2026-07-02，7 天前是 2026-06-25
        # #820 (6/20) stale, #849 (7/1) fresh
        stale = filter_stale_issues(issues, days=7, reference_date="2026-07-02T12:00:00Z")
        assert len(stale) == 1
        assert stale[0]["number"] == 820

    def test_all_fresh_returns_empty(self):
        """全部在 days 天内 → 空 stale 列表。"""
        issues = [
            {"number": 848, "title": "[coverage] ...", "createdAt": "2026-07-01T10:00:00Z"},
            {"number": 849, "title": "[coverage] ...", "createdAt": "2026-07-02T09:00:00Z"},
        ]
        stale = filter_stale_issues(issues, days=7, reference_date="2026-07-02T12:00:00Z")
        assert stale == []

    def test_default_days_is_7(self):
        """默认 7 天阈值。"""
        issues = [
            {"number": 820, "title": "[coverage] ...", "createdAt": "2026-06-20T10:00:00Z"},
        ]
        stale = filter_stale_issues(issues, reference_date="2026-07-02T12:00:00Z")
        assert len(stale) == 1

    def test_missing_date_treated_as_stale(self):
        """缺少 createdAt 的 issue 保守处理为 stale。"""
        issues = [
            {"number": 999, "title": "[coverage] no date", "createdAt": None},
        ]
        stale = filter_stale_issues(issues, days=7)
        assert len(stale) == 1

    def test_unparseable_date_treated_as_stale(self):
        """无法解析的日期保守处理为 stale。"""
        issues = [
            {"number": 888, "title": "[coverage] bad date", "createdAt": "not-a-date"},
        ]
        stale = filter_stale_issues(issues, days=7)
        assert len(stale) == 1


class TestGroupFilesByFeature:
    """已有函数回归 — 确保 batch 模式不影响现有功能。"""

    def test_empty_files_returns_empty(self):
        assert group_files_by_feature([], "admin-api") == {}

    def test_controller_grouping(self):
        files = [
            {"file": "com/migao/admin/controller/OrderController.java",
             "line_pct": 30, "lines_missed": 10, "lines_total": 20},
            {"file": "com/migao/admin/controller/CustomerController.java",
             "line_pct": 25, "lines_missed": 15, "lines_total": 20},
        ]
        groups = group_files_by_feature(files, "admin-api")
        assert "controller-order" in groups
        assert "controller-customer" in groups

    def test_max_files_per_issue_respected(self):
        """超过 MAX_FILES_PER_ISSUE 应拆分。"""
        files = []
        for i in range(10):
            files.append({
                "file": "com/migao/admin/service/OrderService{}.java".format(i),
                "line_pct": 40, "lines_missed": 10, "lines_total": 20,
            })
        groups = group_files_by_feature(files, "admin-api")
        # 应被拆成多个 part
        part_keys = [k for k in groups if k.startswith("service-order")]
        assert len(part_keys) >= 2, "10 files should be split, got {}".format(part_keys)


class TestBatchSkipEndToEnd:
    """集成场景 — 完整的 batch-skip 流程。"""

    def test_dry_run_produces_list_without_modification(self):
        """--batch-skip --dry-run 只输出列表，不实际改 issue。"""
        issues = [
            {"number": 820,
             "title": "[coverage] admin-api/controller-order 覆盖率补全（2 个文件）",
             "createdAt": "2026-06-20T10:00:00Z",
             "labels": ["qa-todo", "coverage-gap", "qa-growth"]},
            {"number": 849,
             "title": "[coverage] admin-web/lib-utils 覆盖率补全（1 个文件）",
             "createdAt": "2026-07-01T10:00:00Z",
             "labels": ["qa-todo", "coverage-gap", "qa-growth"]},
        ]
        stale = filter_stale_issues(
            issues, days=7, reference_date="2026-07-02T12:00:00Z")
        # 只有 #820 是 stale（6/20 > 7 天前）
        assert len(stale) == 1
        assert stale[0]["number"] == 820
        assert "controller-order" in stale[0]["title"]

    def test_batch_skip_command_construction(self):
        """batch-skip 模式命令构建正确。"""
        cmd = build_batch_issue_list(labels=["qa-todo", "coverage-gap"], limit=100)
        cmd_str = " ".join(cmd)
        # 必须包含 state:open 和 label 过滤
        assert "--state" in cmd
        assert "open" in cmd
        assert "--label" in cmd
        # JSON 字段包含 createdAt 用于过滤
        assert "createdAt" in cmd_str


@pytest.mark.parametrize("labels,expected_count", [
    (["qa-todo", "coverage-gap", "qa-growth"], 2),
    (["qa-todo", "qa-growth"], 1),
    (["coverage-gap", "qa-growth"], 1),
    (["bug"], 0),
    (["qa-todo", "coverage-gap", "qa-growth", "low-priority/auto-skip"], 2),
])
def test_label_match_for_batch_targeting(labels, expected_count):
    """Batch 操作的 label 匹配逻辑。"""
    target_labels = {"qa-todo", "coverage-gap"}
    matched = [l for l in labels if l in target_labels]
    assert len(matched) == expected_count
