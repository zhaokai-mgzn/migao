"""
米宝多轮 — 售后域（库存回收/纠纷判定）

（由 test_mibao_advanced_multiturn.py 按场景域拆分，2026-08-29）
"""
# case_ids: AS-005
import pytest
from app.agents.customer_service_agent import reset_agent
from app.tools.registry import reset_tool_registry
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



class TestMibaoMultiturnAftersales:
    """米宝多轮 — 售后域（库存回收/纠纷判定）"""

    async def test_case_15_aftersales_inventory_recovery(self):
        """
        Case 15: 售后退货→库存回收→重新上架（6轮）
        验证重点：跨Skill联动（aftersales→order→product）
        涉及Skill: aftersales, order, product | Tools: order_query, order_manage, inventory_manage, product_manage
        """
        runner = MultiTurnRunner(15, "售后退货→库存回收→重新上架")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="客户李女士说收到的窗帘颜色不对，要退货",
            expected_graph_result=make_graph_result(
                final_answer="收到李女士的退货投诉（颜色不对）。请提供订单号，我帮您查看详情并处理。",
                skill_used="aftersales_skill", intent="complaint", confidence=0.92,
            ),
            checks=[
                {"fn": lambda s, r, e: "complaint" in e.get("intent_result", {}).get("intent", ""), "desc": "识别为投诉意图"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="订单号 ORD20250428066",
            expected_graph_result=make_graph_result(
                final_answer="订单 ORD20250428066：\n- 客户: 李女士\n- 商品: 米白色雪尼尔窗帘 ×1\n- 金额: ¥299\n- 状态: 已签收\n签收3天内，符合退货条件。",
                skill_used="order", intent="order_query", confidence=0.95,
                tool_name="order_query",
                tool_args={"order_no": "ORD20250428066"},
                tool_result_data={"order_no": "ORD20250428066", "customer_name": "李女士", "status": "received", "items": [{"product_id": "p001", "product_name": "米白色雪尼尔窗帘", "quantity": 1, "price": 299}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "ORD20250428066" in r.content, "desc": "订单查询成功"},
                {"fn": lambda s, r, e: "退货" in r.content or "符合" in r.content, "desc": "确认符合退货条件"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="确认退货，帮我处理",
            expected_graph_result=make_graph_result(
                final_answer="已将订单 ORD20250428066 状态更新为「退货中」。请通知李女士寄回商品。",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "update_status", "order_id": "ORD20250428066", "new_status": "returning", "reason": "颜色不对"},
                tool_result_data={"order_no": "ORD20250428066", "new_status": "returning"},
            ),
            checks=[
                {"fn": lambda s, r, e: "退货" in r.content, "desc": "退货状态更新成功"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="商品已收回，帮我把库存加回去",
            expected_graph_result=make_graph_result(
                final_answer="已将退回的「米白色雪尼尔窗帘」(p001) 库存+1件，当前库存: 106件。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="inventory_manage",
                tool_args={"action": "adjust", "product_id": "p001", "quantity": 1},
                tool_result_data={"product_id": "p001", "new_stock": 106},
            ),
            checks=[
                {"fn": lambda s, r, e: "product" in e.get("skill_used", ""), "desc": "跨Skill到product处理库存"},
                {"fn": lambda s, r, e: "106" in r.content, "desc": "库存回增成功"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="这个商品现在是什么状态？在售吗",
            expected_graph_result=make_graph_result(
                final_answer="米白色雪尼尔窗帘(p001) 当前状态：在售，库存106件，一切正常。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="product_detail",
                tool_args={"product_id": "p001"},
                tool_result_data={"id": "p001", "name": "米白色雪尼尔窗帘", "status": "on_sale", "stock": 106},
            ),
            checks=[
                {"fn": lambda s, r, e: "在售" in r.content or "on_sale" in r.content, "desc": "商品状态确认为在售"},
            ],
        )

        await runner.run_turn(
            turn_num=6,
            user_message="好，那这个退货完成了，帮我把订单改成退货完成",
            expected_graph_result=make_graph_result(
                final_answer="已将订单 ORD20250428066 状态更新为「退货完成」。整个退货流程已处理完毕。",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "update_status", "order_id": "ORD20250428066", "new_status": "returned"},
                tool_result_data={"order_no": "ORD20250428066", "new_status": "returned"},
            ),
            checks=[
                {"fn": lambda s, r, e: "退货完成" in r.content or "完毕" in r.content, "desc": "退货流程闭环确认"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 15 存在失败检查点\n{report}"

    # ---------- Case 16: 知识辅助的精准商品推荐 ----------

    async def test_case_29_thinking_aftersales_dispute_judgment(self):
        """
        Case 29: 复杂推理：售后纠纷判责（5轮）
        验证重点：thinking推理责任归属、证据链、政策适用
        涉及Skill: aftersales, order, knowledge | Tools: order_query, logistics_track, knowledge_search, order_manage
        """
        runner = MultiTurnRunner(29, "复杂推理：售后纠纷判责")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="一个客户说窗帘安装后发现尺寸比下单时写的小了5cm，要求退款",
            expected_graph_result=make_graph_result(
                final_answer="了解情况：客户反映实际尺寸比订单规格小5cm。这需要核实：\n1. 订单规格是什么\n2. 实际商品是否确实偏小\n3. 是生产偏差还是客户量错\n请提供订单号，我帮您查看。",
                skill_used="aftersales_skill", intent="after_sales", confidence=0.90,
                thinking_content="售后纠纷场景，尺寸偏差需要判断责任方：生产方/物流方/客户方。先收集订单信息。",
            ),
            checks=[
                {"fn": lambda s, r, e: "after_sales" in e.get("intent_result", {}).get("intent", ""), "desc": "识别为售后意图"},
                {"fn": lambda s, r, e: "<think>" not in r.content, "desc": "thinking未泄露"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="订单ORD20250425200，客户说下单写的2.0m但收到的只有1.95m",
            expected_graph_result=make_graph_result(
                final_answer="查到订单信息：\n- 订单号: ORD20250425200\n- 规格: 宽2.0m×高2.5m\n- 商品: 定制雪尼尔遮光帘\n- 备注: 客户自行量尺\n客户下单确实写的2.0m。需要确认偏差5cm是否在容许范围内。",
                skill_used="order", intent="order_query", confidence=0.92,
                tool_name="order_query",
                tool_args={"order_no": "ORD20250425200"},
                tool_result_data={"order_no": "ORD20250425200", "specifications": {"width": "2.0m", "height": "2.5m"}, "product_name": "定制雪尼尔遮光帘", "note": "客户自行量尺"},
                thinking_content="订单规格2.0m，实际1.95m，偏差5cm=2.5%。需要查知识库确认定制商品的允许偏差范围。",
            ),
            checks=[
                {"fn": lambda s, r, e: "2.0m" in r.content, "desc": "查到订单规格信息"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="我们的定制误差标准是多少",
            expected_graph_result=make_graph_result(
                final_answer="定制商品尺寸误差标准：\n- 宽度误差容许: ±2cm（即2.0m允许范围1.98m-2.02m）\n- 高度误差容许: ±3cm\n- 超出容许范围：可退换或补做\n📋 判断：偏差5cm超出容许范围(±2cm)，属于生产质量问题。",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.90,
                tool_name="knowledge_search",
                tool_args={"query": "定制商品尺寸误差容许范围标准"},
                tool_result_data={"chunks": [{"content": "定制窗帘宽度误差±2cm，高度±3cm，超出可退换"}]},
                thinking_content="偏差5cm超出±2cm的容许范围，判定为生产方责任。客户可以退换或要求补做。",
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""), "desc": "查询政策标准"},
                {"fn": lambda s, r, e: "超出" in r.content or "5cm" in r.content or "质量" in r.content, "desc": "判定超出容许范围"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="那按照政策应该怎么处理",
            expected_graph_result=make_graph_result(
                final_answer="根据推理判定和政策：\n\n📋 判责结论：生产方责任（偏差5cm超出±2cm标准）\n\n🔧 处理方案：\n1. 【推荐】免费补做正确尺寸+客户保留原帘作为补偿\n2. 全额退款退货\n3. 退差价30%作为补偿\n\n建议方案1，客户满意度最高且成本可控。",
                skill_used="aftersales_skill", intent="after_sales", confidence=0.88,
                thinking_content="责任明确：生产方。方案选择推理：1.补做+保留原品=客户获得超值补偿,满意度高;2.全退=客户流失;3.退差价=客户可能不满。推荐方案1。",
            ),
            checks=[
                {"fn": lambda s, r, e: "生产" in r.content or "责任" in r.content, "desc": "给出明确判责"},
                {"fn": lambda s, r, e: "补做" in r.content or "退款" in r.content, "desc": "给出处理方案"},
                {"fn": lambda s, r, e: "<think>" not in r.content, "desc": "thinking推理不泄露"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="客户接受方案1，帮我安排",
            expected_graph_result=make_graph_result(
                final_answer="已安排处理：\n- 订单ORD20250425200标记为「补做处理中」\n- 补做规格: 宽2.0m×高2.5m（已加强QC检查标记）\n- 客户保留原帘\n- 预计5-7天补做完成\n已通知生产部门优先处理。",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "update_status", "order_id": "ORD20250425200", "new_status": "remaking", "reason": "尺寸偏差补做"},
                tool_result_data={"order_no": "ORD20250425200", "new_status": "remaking"},
            ),
            checks=[
                {"fn": lambda s, r, e: "补做" in r.content, "desc": "执行补做方案"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 29 存在失败检查点\n{report}"

    # ---------- Case 30: Thinking输出清理验证 ----------

