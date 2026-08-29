"""
米宝多轮 — 订单域（批量筛选/财务汇总/订单恢复）

（由 test_mibao_advanced_multiturn.py 按场景域拆分，2026-08-29）
"""
# case_ids: OR-006, OR-007
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from tests.mibao_multiturn_shared import (
    MultiTurnRunner, make_graph_result, make_thinking_response,
    verify_thinking_stripped, verify_thinking_not_leaked, _reset_singletons,
    logger, TurnResult, CaseResult,
)


@pytest.fixture(autouse=True)
def _auto_reset_singletons():
    """每个测试重置全局单例（原为模块内 autouse，拆分后补回）"""
    reset_agent()
    reset_tool_registry()
    yield
    reset_agent()
    reset_tool_registry()



class TestMibaoMultiturnOrder:
    """米宝多轮 — 订单域（批量筛选/财务汇总/订单恢复）"""

    async def test_case_11_batch_order_filter_and_mark(self):
        """
        Case 11: 批量订单状态查询与筛选（5轮）
        验证重点：分页、多条件筛选、批量操作
        涉及Skill: order | Tools: order_query, order_manage
        """
        runner = MultiTurnRunner(11, "批量订单状态查询与筛选")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # 轮1: 按状态筛选
        await runner.run_turn(
            turn_num=1,
            user_message="帮我查所有待发货的订单",
            expected_graph_result=make_graph_result(
                final_answer="找到12个待发货订单（显示前5个）：\n1. ORD20250501001 ¥299\n2. ORD20250501002 ¥459\n3. ORD20250501003 ¥198\n4. ORD20250501004 ¥356\n5. ORD20250501005 ¥520\n还有7个，需要翻页查看吗？",
                skill_used="order", intent="order_query", confidence=0.92,
                tool_name="order_query",
                tool_args={"status": "pending_shipment", "page": 1, "page_size": 5},
                tool_result_data={"orders": [
                    {"order_no": f"ORD2025050100{i}", "status": "pending_shipment", "total_amount": amt}
                    for i, amt in enumerate([299, 459, 198, 356, 520], 1)
                ], "total": 12, "page": 1, "page_size": 5},
            ),
            checks=[
                {"fn": lambda s, r, e: "order" in e.get("skill_used", ""), "desc": "路由到 order_skill"},
                {"fn": lambda s, r, e: "12" in r.content or "待发货" in r.content, "desc": "回复包含订单总数或状态"},
            ],
        )

        # 轮2: 翻页
        await runner.run_turn(
            turn_num=2,
            user_message="看下一页",
            expected_graph_result=make_graph_result(
                final_answer="第2页待发货订单：\n6. ORD20250501006 ¥188\n7. ORD20250501007 ¥420\n8. ORD20250501008 ¥299\n9. ORD20250501009 ¥615\n10. ORD20250501010 ¥278",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_query",
                tool_args={"status": "pending_shipment", "page": 2, "page_size": 5},
                tool_result_data={"orders": [
                    {"order_no": f"ORD202505010{i:02d}", "status": "pending_shipment"}
                    for i in range(6, 11)
                ], "total": 12, "page": 2},
            ),
            checks=[
                {"fn": lambda s, r, e: "ORD20250501006" in r.content, "desc": "翻页显示第二页数据"},
            ],
        )

        # 轮3: 按日期范围再筛选
        await runner.run_turn(
            turn_num=3,
            user_message="只看5月1号当天的",
            expected_graph_result=make_graph_result(
                final_answer="5月1日待发货订单有4个：\n1. ORD20250501001 ¥299\n2. ORD20250501002 ¥459\n3. ORD20250501003 ¥198\n4. ORD20250501004 ¥356",
                skill_used="order", intent="order_query", confidence=0.90,
                tool_name="order_query",
                tool_args={"status": "pending_shipment", "date_from": "2025-05-01", "date_to": "2025-05-01"},
                tool_result_data={"orders": [
                    {"order_no": f"ORD2025050100{i}", "status": "pending_shipment"}
                    for i in range(1, 5)
                ], "total": 4},
            ),
            checks=[
                {"fn": lambda s, r, e: "4" in r.content, "desc": "日期筛选后结果正确缩小"},
            ],
        )

        # 轮4: 批量标记
        await runner.run_turn(
            turn_num=4,
            user_message="这4个都标记为已发货",
            expected_graph_result=make_graph_result(
                final_answer="已将4个订单批量标记为「已发货」：\n- ORD20250501001 ✓\n- ORD20250501002 ✓\n- ORD20250501003 ✓\n- ORD20250501004 ✓",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "batch_update_status", "order_ids": ["ORD20250501001", "ORD20250501002", "ORD20250501003", "ORD20250501004"], "new_status": "shipped"},
                tool_result_data={"updated": 4, "status": "shipped"},
            ),
            checks=[
                {"fn": lambda s, r, e: "已发货" in r.content, "desc": "批量更新确认"},
                {"fn": lambda s, r, e: "ORD20250501001" in r.content and "ORD20250501004" in r.content, "desc": "回复列出所有更新的订单"},
            ],
        )

        # 轮5: 确认操作
        await runner.run_turn(
            turn_num=5,
            user_message="再查一下现在还有多少待发货的",
            expected_graph_result=make_graph_result(
                final_answer="当前剩余8个待发货订单（原12个已标记4个为已发货）。",
                skill_used="order", intent="order_query", confidence=0.90,
                tool_name="order_query",
                tool_args={"status": "pending_shipment"},
                tool_result_data={"orders": [], "total": 8},
            ),
            checks=[
                {"fn": lambda s, r, e: "8" in r.content, "desc": "确认批量操作后数量正确减少"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 11 存在失败检查点\n{report}"

    # ---------- Case 12: 库存预警与批量补货 ----------

    async def test_case_14_order_financial_summary(self):
        """
        Case 14: 订单财务汇总与对账（4轮）
        验证重点：日期查询、金额计算、异常检测
        涉及Skill: order | Tools: order_query, order_manage
        """
        runner = MultiTurnRunner(14, "订单财务汇总与对账")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="帮我查一下5月1号到5月3号的所有已完成订单",
            expected_graph_result=make_graph_result(
                final_answer="5月1日-3日已完成订单共8个，总金额¥3,580：\n1. ORD0501A ¥299\n2. ORD0501B ¥459\n3. ORD0502A ¥198\n4. ORD0502B ¥899\n5. ORD0502C ¥356\n6. ORD0503A ¥520\n7. ORD0503B ¥150\n8. ORD0503C ¥699",
                skill_used="order", intent="order_query", confidence=0.90,
                tool_name="order_query",
                tool_args={"status": "completed", "date_from": "2025-05-01", "date_to": "2025-05-03"},
                tool_result_data={"orders": [
                    {"order_no": "ORD0501A", "total_amount": 299}, {"order_no": "ORD0501B", "total_amount": 459},
                    {"order_no": "ORD0502A", "total_amount": 198}, {"order_no": "ORD0502B", "total_amount": 899},
                    {"order_no": "ORD0502C", "total_amount": 356}, {"order_no": "ORD0503A", "total_amount": 520},
                    {"order_no": "ORD0503B", "total_amount": 150}, {"order_no": "ORD0503C", "total_amount": 699},
                ], "total": 8},
            ),
            checks=[
                {"fn": lambda s, r, e: "8" in r.content or "3,580" in r.content or "3580" in r.content, "desc": "回复包含订单数或总金额"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="金额最高的那个是哪个订单，多少钱",
            expected_graph_result=make_graph_result(
                final_answer="金额最高的是 ORD0502B，金额¥899，商品为「定制大尺寸遮光帘2.8m×3.0m」。",
                skill_used="order", intent="order_query", confidence=0.85,
                tool_name="order_query",
                tool_args={"order_no": "ORD0502B"},
                tool_result_data={"order_no": "ORD0502B", "total_amount": 899, "items": [{"product_name": "定制大尺寸遮光帘2.8m×3.0m"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "899" in r.content and "ORD0502B" in r.content, "desc": "正确找出金额最高订单"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="感觉ORD0503C的金额不对，帮我看看详情",
            expected_graph_result=make_graph_result(
                final_answer="ORD0503C 详情：\n- 商品: 北欧简约帘 ¥199 × 2件 + 安装服务 ¥50\n- 应付: ¥448\n- 实付: ¥699\n⚠️ 确实存在异常：实付金额比应付高出¥251，可能是优惠券退还或录入错误。",
                skill_used="order", intent="order_query", confidence=0.90,
                tool_name="order_query",
                tool_args={"order_no": "ORD0503C"},
                tool_result_data={"order_no": "ORD0503C", "total_amount": 699, "calculated_amount": 448, "items": [{"product_name": "北欧简约帘", "price": 199, "quantity": 2}, {"product_name": "安装服务", "price": 50, "quantity": 1}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "异常" in r.content or "不对" in r.content or "⚠" in r.content, "desc": "检测到金额异常"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="帮我标记这个订单需要人工核查",
            expected_graph_result=make_graph_result(
                final_answer="已将订单 ORD0503C 标记为「需人工核查」状态，备注：金额异常，实付¥699与应付¥448不符。",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "update_status", "order_id": "ORD0503C", "new_status": "audit_required", "reason": "金额异常"},
                tool_result_data={"order_no": "ORD0503C", "new_status": "audit_required"},
            ),
            checks=[
                {"fn": lambda s, r, e: "核查" in r.content or "标记" in r.content, "desc": "异常订单标记成功"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 14 存在失败检查点\n{report}"

    # ==================== B. 跨领域联动类 ====================

    # ---------- Case 15: 售后退货→库存回收→重新上架 ----------

    async def test_case_20_order_not_found_recovery(self):
        """
        Case 20: 订单不存在时的多策略恢复（5轮）
        验证重点：多策略兜底、引导用户、最终转人工
        涉及Skill: order | Tools: order_query
        """
        runner = MultiTurnRunner(20, "订单不存在时的多策略恢复")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="帮我查订单 ORD000000000",
            expected_graph_result=make_graph_result(
                final_answer="抱歉，未找到订单 ORD000000000。请确认订单号是否正确，或者您可以尝试用手机号或姓名来查询。",
                skill_used="order", intent="order_query", confidence=0.92,
                tool_name="order_query",
                tool_args={"order_no": "ORD000000000"},
                tool_result_data=None,
            ),
            checks=[
                {"fn": lambda s, r, e: "未找到" in r.content or "抱歉" in r.content, "desc": "友好提示订单不存在"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="那用手机号 13000000000 查",
            expected_graph_result=make_graph_result(
                final_answer="通过手机号 13000000000 也未找到相关订单。您还可以试试：\n1. 确认手机号是否正确\n2. 按日期范围查询\n3. 提供客户姓名",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_query",
                tool_args={"customer_phone": "13000000000"},
                tool_result_data={"orders": [], "total": 0},
            ),
            checks=[
                {"fn": lambda s, r, e: "未找到" in r.content or "也" in r.content, "desc": "第二次查询也无结果"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="试试上个月的全部订单里有没有",
            expected_graph_result=make_graph_result(
                final_answer="查询了4月1日-4月30日的全部订单(共156个)，未找到与该客户匹配的订单记录。可能原因：\n1. 订单信息录入有误\n2. 客户通过其他渠道下单\n3. 订单已被删除",
                skill_used="order", intent="order_query", confidence=0.85,
                tool_name="order_query",
                tool_args={"date_from": "2025-04-01", "date_to": "2025-04-30"},
                tool_result_data={"orders": [], "total": 0, "scanned": 156},
            ),
            checks=[
                {"fn": lambda s, r, e: "未找到" in r.content or "原因" in r.content, "desc": "日期范围查询也无结果"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="都查不到怎么办",
            expected_graph_result=make_graph_result(
                final_answer="多种方式都未能找到订单，建议：\n1. 请客户确认是否在我们平台下单\n2. 检查是否是其他分店/渠道的订单\n3. 如确认是我们的订单，建议转人工客服进行系统后台排查",
                skill_used="general_agent", intent="general", confidence=0.60,
            ),
            checks=[
                {"fn": lambda s, r, e: "建议" in r.content, "desc": "给出解决建议"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="转人工吧",
            expected_graph_result=make_graph_result(
                final_answer="好的，正在为您转接人工客服。已将之前的查询记录（订单号ORD000000000、手机号13000000000）一并转交，方便人工客服继续跟进。请稍等。",
                skill_used="general_agent", intent="general", confidence=0.75,
            ),
            checks=[
                {"fn": lambda s, r, e: "转接" in r.content or "人工" in r.content, "desc": "转人工并携带上下文"},
                {"fn": lambda s, r, e: "ORD000000000" in r.content or "13000000000" in r.content, "desc": "转接时携带之前查询信息"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 20 存在失败检查点\n{report}"

    # ---------- Case 21: 权限不足时的优雅降级 ----------

