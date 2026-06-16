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

    def test_is_deployment_issue(self):
        assert primary.is_deployment_issue("Flyway 启动崩溃 SAE 实例 CrashLoop") is True
        assert primary.is_deployment_issue("V1__add_permission.sql 迁移失败") is True
        assert primary.is_deployment_issue("admin-api 返回 500") is False
        assert primary.is_deployment_issue("") is False


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

    def test_extract_from_table(self):
        # 实战发现：#387 业务真值在表格里
        body = """
        ## 业务定义（娜总 17:25 明确）

        | 卡片 | 业务口径 | 条件数 |
        |------|----------|--------|
        | **待发货订单** | 用户成功支付后还没有发货的订单 | 1 个：status = 待发货 |
        | **含加工待发货订单** | 待发货 + 含加工项 | 2 个：status = 待发货 AND has_processing = true |
        """
        truths = reviewer.extract_business_truths(body)
        # 期望：抓到表格里的"业务口径"列
        assert len(truths) >= 1
        assert any("用户成功支付" in t for t in truths)

    def test_extract_acceptance_criteria(self):
        body = """
        ## Acceptance Criteria

        - 含加工待发货 = status=待发货 AND has_processing=true
        - 跳转 URL 必须 = /orders?category=含加工订单
        """
        truths = reviewer.extract_business_truths(body)
        assert len(truths) == 2
        assert any("含加工待发货" in t for t in truths)

    def test_dedup_truths(self):
        body = """
        ## 业务真值
        - 含加工待发货 = A AND B
        ## 业务定义
        - 含加工待发货 = A AND B
        """
        truths = reviewer.extract_business_truths(body)
        # 跨段不去重（让用户看完整）
        assert len(truths) >= 2

    def test_extract_from_comments(self):
        """#366 实战：业务真值在评论里（军师反推）"""
        body = """
        ## 现象
        SAE 实例崩溃

        ## 临时方案
        禁用 Flyway
        """
        comments = [
            {"body": "## 📋 验收标准\n\n- Spring Boot + Flyway 启动**不崩溃**\n- 实例稳定运行"},
            {"body": "其他不相关评论"},
        ]
        truths = reviewer.extract_business_truths(body, comments)
        # 应该从评论里抓到业务真值
        assert len(truths) >= 1
        assert any("崩溃" in t or "稳定" in t for t in truths)

    def test_extract_verification_section(self):
        """#366 实战：issue body 用'验收标准'段（不是'业务真值'）"""
        body = """
        ## 验收标准
        - admin-api 启动成功
        - 数据库 schema 正确
        """
        truths = reviewer.extract_business_truths(body)
        assert len(truths) == 2
        assert "admin-api 启动成功" in truths


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

    def test_three_consistent_pass_close(self):
        primary_r = {"status": "pass", "confidence": 100}
        reviewer_r = {"status": "pass", "confidence": 100}
        cloud_r = {"verdict": "pass"}
        result = merge.judge(primary_r, reviewer_r, cloud_r)
        assert result["decision"] == "close"
        assert "三一致" in result["verdict"]

    def test_cloud_fail_blocks(self):
        primary_r = {"status": "pass", "confidence": 100}
        reviewer_r = {"status": "pass", "confidence": 100}
        cloud_r = {"verdict": "fail"}
        result = merge.judge(primary_r, reviewer_r, cloud_r)
        assert result["decision"] == "block"
        assert "云验收" in result["verdict"]

    def test_cloud_pending_holds(self):
        primary_r = {"status": "pass", "confidence": 100}
        reviewer_r = {"status": "pass", "confidence": 100}
        cloud_r = {"verdict": "skip"}
        result = merge.judge(primary_r, reviewer_r, cloud_r)
        assert result["decision"] == "hold"
        assert "云未验收" in result["verdict"]

    def test_deployment_issue_holds(self):
        """#366 实战：部署类 issue skip_deployment → hold 等云验收"""
        primary_r = {"status": "skip_deployment", "confidence": 0}
        reviewer_r = {"status": "manual_review", "confidence": 50}
        result = merge.judge(primary_r, reviewer_r)
        assert result["decision"] == "hold"
        assert "部署" in result["verdict"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
