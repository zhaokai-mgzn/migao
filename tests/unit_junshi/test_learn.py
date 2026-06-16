"""junshi/learn.py 单测"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 加 junshi 到 path
sys.path.insert(0, str(Path("/opt/youke/junshi").parent))


def test_scan_with_no_qa_results(tmp_path):
    """无 qa-results 时不报错"""
    from junshi import learn
    with patch.object(learn, "QA_RESULTS_DIR", tmp_path):
        data = learn.scan_real_cases()
        assert data["issues"] == []


def test_detect_patterns_low_truths():
    """业务真值=0 时给建议"""
    from junshi import learn
    scan_data = {"issues": [
        {"issue_id": 1, "truths_count": 0, "primary_status": "skip", "reviewer_status": "pass", "primary_confidence": 0, "reviewer_confidence": 90, "asserts_total": 0, "asserts_pass": 0},
        {"issue_id": 2, "truths_count": 0, "primary_status": "skip", "reviewer_status": "pass", "primary_confidence": 0, "reviewer_confidence": 90, "asserts_total": 0, "asserts_pass": 0},
    ]}
    detection = learn.detect_patterns(scan_data)
    assert 1 in detection["patterns"]["low_truths_count"]
    assert 2 in detection["patterns"]["low_truths_count"]
    assert any(r["type"] == "add_section" for r in detection["recommendations"])


def test_detect_patterns_deployment():
    """部署类 skip 时给建议"""
    from junshi import learn
    scan_data = {"issues": [
        {"issue_id": 366, "truths_count": 19, "primary_status": "skip_deployment", "reviewer_status": "manual_review", "primary_confidence": 0, "reviewer_confidence": 50, "asserts_total": 19, "asserts_pass": 0},
    ]}
    detection = learn.detect_patterns(scan_data)
    assert 366 in detection["patterns"]["deployment_skipped"]


def test_load_rules_default():
    """规则文件不存在时返回默认"""
    from junshi import learn
    with patch.object(learn, "RULES_FILE", Path("/nonexistent.json")):
        rules = learn.load_rules()
        assert "version" in rules
        assert rules["version"] == "v0.1"


def test_actual_rules_file():
    """真实规则文件存在且结构正确"""
    rules_path = Path("/opt/youke/junshi/learned_rules.json")
    assert rules_path.exists()
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    assert rules["version"] == "v1.0"
    assert len(rules["rules"]) >= 3
    rule_ids = [r["id"] for r in rules["rules"]]
    assert "is_deployment_issue" in rule_ids
    assert "extract_business_truths" in rule_ids
    assert "merge_decision" in rule_ids


def test_actual_stats():
    """实战统计正确"""
    rules_path = Path("/opt/youke/junshi/learned_rules.json")
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    stats = rules["stats"]
    assert stats["total_runs"] == 5
    assert 387 in stats["issues_verified"]
    assert 366 in stats["issues_verified"]