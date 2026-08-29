"""
米宝高级多轮汇总报告（由 test_mibao_advanced_multiturn.py 拆分，2026-08-29）
"""
# case_ids: AS-005, CH-002, OR-006, PR-011, PR-012
import pytest


@pytest.fixture(autouse=True)
def _auto_reset_singletons():
    """每个测试重置全局单例（原为模块内 autouse，拆分后补回）"""
    reset_agent()
    reset_tool_registry()
    yield
    reset_agent()
    reset_tool_registry()



class TestMibaoAdvancedSummaryReport:
    """汇总运行全部高级 Case 并生成报告"""

    async def test_advanced_summary(self, capsys):
        """运行全部高级 Case 并输出汇总报告"""
        # 局部导入避免 pytest 重复收集域类
        from tests.test_mibao_multiturn_order import TestMibaoMultiturnOrder
        from tests.test_mibao_multiturn_product import TestMibaoMultiturnProduct
        from tests.test_mibao_multiturn_aftersales import TestMibaoMultiturnAftersales
        from tests.test_mibao_multiturn_reliability import TestMibaoMultiturnReliability
        from tests.test_mibao_multiturn_advanced import TestMibaoMultiturnAdvanced
        suites = [TestMibaoMultiturnOrder(), TestMibaoMultiturnProduct(),
                  TestMibaoMultiturnAftersales(), TestMibaoMultiturnReliability(),
                  TestMibaoMultiturnAdvanced()]
        cases = []
        for s in suites:
            for name in dir(s):
                if name.startswith("test_case_"):
                    cases.append((name, getattr(s, name)))
        import re as _re
        def _key(item):
            m = _re.search(r"test_case_(\d+)", item[0])
            return int(m.group(1)) if m else 999
        cases.sort(key=_key)
        results = []
        for label, fn in cases:
            try:
                await fn()
                results.append((label, True))
            except Exception as e:
                results.append((label, False, str(e)))
        passed = sum(1 for r in results if r[1])
        print("\n" + "=" * 60)
        print("高级多轮汇总: %d/%d 通过" % (passed, len(results)))
        for r in results:
            if not r[1]:
                print("  FAIL %s: %s" % (r[0], r[2]))
        print("=" * 60)
