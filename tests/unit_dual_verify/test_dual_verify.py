"""
双验收逻辑单测（#450b / #454）

不依赖外部工具（Playwright/mvn），纯逻辑测试。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import pytest
from dual_verify import primary, reviewer, merge


class TestPrimarySpecExtraction:
    def test_extracts_e2e_specs(self):
        body = """
        ## 验收用例
        - `tests/e2e/specs/dashboard/dashboard.spec.ts`
        - `tests/e2e/specs/orders/order-list.spec.ts`
        """
        specs = primary.extract_specs(body)
        assert "tests/e2e/specs/dashboard/dashboard.spec.ts" in specs
        assert "tests/e2e/specs/orders/order-list.spec.ts" in specs

    def test_extracts_python_tests(self):
        body = """
        - `tests/test_tools_order.py`
        - `tests/test_e2e_mibao.py`
        """
        specs = primary.extract_specs(body)
        assert "tests/test_tools_order.py" in specs
        assert "tests/test_e2e_mibao.py" in specs

    def test_extracts_java_tests(self):
        body = """
        - `src/test/java/com/migao/admin/controller/OrderControllerTest.java`
        """
        specs = primary.extract_specs(body)
        assert "src/test/java/com/migao/admin/controller/OrderControllerTest.java" in specs

    def test_empty_body(self):
        assert primary.extract_specs("") == []

    def test_deduplicates(self):
        body = "- `tests/foo.spec.ts`\n- `tests/foo.spec.ts`"
        specs = primary.extract_specs(body)
        assert len(specs) == 1


class TestPrimaryClassifier:
    def test_e2e(self):
        assert primary.classify("tests/x.spec.ts") == "e2e"

    def test_python(self):
        assert primary.classify("tests/test_x.py") == "python"

    def test_java(self):
        assert primary.classify("src/test/java/XTest.java") == "java"

    def test_unknown(self):
        assert primary.classify("foo.txt") == "unknown"


class TestReviewerBusinessTruths:
    def test_extract_truths(self):
        body = """
        ## 业务真值
        - 含加工待发货 = 状态为待发货 且 含加工项
        - 看板跳转后筛选条件 = 卡片标题一致
        - 客户搜索支持手机号
        """
        truths = reviewer.extract_business_truths(body)
        assert len(truths) == 3
        assert "含加工待发货 = 状态为待发货 且 含加工项" in truths

    def test_skip_html_comments(self):
        body = """
        ## 业务真值
        - <!-- 这是注释 -->
        - 真实业务真值
        """
        truths = reviewer.extract_business_truths(body)
        assert len(truths) == 1
        assert "真实业务真值" in truths[0]

    def test_no_truths_section(self):
        truths = reviewer.extract_business_truths("没有真值段")
        assert truths == []


class TestReviewerAssertInference:
    def test_infer_processing(self):
        truths = ["含加工待发货 = 状态为待发货 且 含加工项"]
        asserts = reviewer.infer_business_asserts(truths)
        assert len(asserts) == 1
        assert asserts[0]["type"] == "db"
        assert "has_processing=true" in asserts[0]["sql"]

    def test_infer_pending_shipment(self):
        truths = ["待发货 = 状态为待发货"]
        asserts = reviewer.infer_business_asserts(truths)
        assert len(asserts) == 1
        assert asserts[0]["type"] == "db"
        assert "status='pending_shipment'" in asserts[0]["sql"]
        assert "has_processing" not in asserts[0]["sql"]

    def test_infer_inventory(self):
        truths = ["商品库存 = 所有 SKU 库存求和"]
        asserts = reviewer.infer_business_asserts(truths)
        assert len(asserts) == 1
        assert asserts[0]["type"] == "db"
        assert "sku" in asserts[0]["sql"]

    def test_infer_tenant(self):
        truths = ["不同租户看不到彼此客户"]
        asserts = reviewer.infer_business_asserts(truths)
        assert asserts[0]["type"] == "db"

    def test_infer_unknown(self):
        truths = ["某个未识别业务"]
        asserts = reviewer.infer_business_asserts(truths)
        assert asserts[0]["type"] == "manual"


class TestMergeJudge:
    def test_close_path(self):
        primary_r = {"status": "pass", "confidence": 100}
        reviewer_r = {"status": "pass", "confidence": 100}
        result = merge.judge(primary_r, reviewer_r)
        assert result["decision"] == "close"

    def test_hold_path(self):
        primary_r = {"status": "fail", "confidence": 0}
        reviewer_r = {"status": "fail", "confidence": 0}
        result = merge.judge(primary_r, reviewer_r)
        assert result["decision"] == "hold"

    def test_block_path_mock_cheat(self):
        primary_r = {"status": "pass", "confidence": 100}
        reviewer_r = {"status": "fail", "confidence": 0}
        result = merge.judge(primary_r, reviewer_r)
        assert result["decision"] == "block"
        assert any("mock" in c.lower() or "复核" in c for c in result["conflicts"])

    def test_block_path_low_confidence(self):
        primary_r = {"status": "pass", "confidence": 95}
        reviewer_r = {"status": "pass", "confidence": 30}
        result = merge.judge(primary_r, reviewer_r)
        assert result["decision"] == "block"

    def test_hold_manual_review(self):
        primary_r = {"status": "pass", "confidence": 100}
        reviewer_r = {"status": "manual_review", "confidence": 50}
        result = merge.judge(primary_r, reviewer_r)
        assert result["decision"] == "hold"

    def test_both_skip(self):
        primary_r = {"status": "skip", "confidence": 0}
        reviewer_r = {"status": "skip", "confidence": 0}
        result = merge.judge(primary_r, reviewer_r)
        assert result["decision"] == "hold"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
