"""
米宝多轮 — 可靠性域（补货/供应链/权限/物流/容错）

（由 test_mibao_advanced_multiturn.py 按场景域拆分，2026-08-29）
"""
# case_ids: DF-011, DF-007
from unittest.mock import patch, AsyncMock, MagicMock

from tests.mibao_multiturn_shared import (
    MultiTurnRunner, make_graph_result, make_thinking_response,
    verify_thinking_stripped, verify_thinking_not_leaked, _reset_singletons,
    logger, TurnResult, CaseResult,
)


class TestMibaoMultiturnReliability:
    """米宝多轮 — 可靠性域（补货/供应链/权限/物流/容错）"""

    async def test_case_12_inventory_alert_batch_restock(self):
        """
        Case 12: 库存预警与批量补货（5轮）
        验证重点：低库存筛选、逐个确认、批量调整、结果验证
        涉及Skill: product | Tools: product_search, inventory_manage
        """
        runner = MultiTurnRunner(12, "库存预警与批量补货")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # 轮1: 查询低库存商品
        await runner.run_turn(
            turn_num=1,
            user_message="有没有库存不足10件的商品",
            expected_graph_result=make_graph_result(
                final_answer="以下3款商品库存不足10件：\n1. 雪尼尔遮光帘(p001) - 库存:5件\n2. 棉麻纱帘(p008) - 库存:3件\n3. 北欧简约帘(p012) - 库存:8件",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_search",
                tool_args={"stock_status": "low", "min_stock": 0, "max_stock": 10},
                tool_result_data={"products": [
                    {"id": "p001", "name": "雪尼尔遮光帘", "stock": 5},
                    {"id": "p008", "name": "棉麻纱帘", "stock": 3},
                    {"id": "p012", "name": "北欧简约帘", "stock": 8},
                ]},
            ),
            checks=[
                {"fn": lambda s, r, e: "3" in r.content or "库存" in r.content, "desc": "列出低库存商品"},
            ],
        )

        # 轮2: 逐个确认补货量
        await runner.run_turn(
            turn_num=2,
            user_message="雪尼尔遮光帘补100件，棉麻纱帘补50件",
            expected_graph_result=make_graph_result(
                final_answer="已调整库存：\n- 雪尼尔遮光帘(p001): 5→105件(+100)\n- 棉麻纱帘(p008): 3→53件(+50)",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="inventory_manage",
                tool_args={"action": "batch_adjust", "items": [{"product_id": "p001", "quantity": 100}, {"product_id": "p008", "quantity": 50}]},
                tool_result_data={"results": [{"product_id": "p001", "new_stock": 105}, {"product_id": "p008", "new_stock": 53}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "105" in r.content and "53" in r.content, "desc": "批量补货结果正确"},
            ],
        )

        # 轮3: 继续补货第三个
        await runner.run_turn(
            turn_num=3,
            user_message="北欧简约帘也补80件吧",
            expected_graph_result=make_graph_result(
                final_answer="已调整库存：北欧简约帘(p012): 8→88件(+80)",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="inventory_manage",
                tool_args={"action": "adjust", "product_id": "p012", "quantity": 80},
                tool_result_data={"product_id": "p012", "new_stock": 88},
            ),
            checks=[
                {"fn": lambda s, r, e: "88" in r.content, "desc": "单个补货结果正确"},
            ],
        )

        # 轮4: 验证调整结果
        await runner.run_turn(
            turn_num=4,
            user_message="帮我确认一下这三个商品现在的库存",
            expected_graph_result=make_graph_result(
                final_answer="当前库存确认：\n1. 雪尼尔遮光帘(p001): 105件\n2. 棉麻纱帘(p008): 53件\n3. 北欧简约帘(p012): 88件\n全部已脱离低库存预警线。",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="inventory_manage",
                tool_args={"action": "query_batch", "product_ids": ["p001", "p008", "p012"]},
                tool_result_data={"results": [{"product_id": "p001", "stock": 105}, {"product_id": "p008", "stock": 53}, {"product_id": "p012", "stock": 88}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "105" in r.content and "53" in r.content and "88" in r.content, "desc": "三个商品库存验证正确"},
            ],
        )

        # 轮5: 生成摘要
        await runner.run_turn(
            turn_num=5,
            user_message="帮我总结一下今天的补货情况",
            expected_graph_result=make_graph_result(
                final_answer="今日补货汇总：\n- 共补货3款商品，总计增加230件\n- 雪尼尔遮光帘 +100件\n- 棉麻纱帘 +50件\n- 北欧简约帘 +80件\n所有商品已脱离预警线。",
                skill_used="product", intent="product_inquiry", confidence=0.82,
            ),
            checks=[
                {"fn": lambda s, r, e: "230" in r.content or ("100" in r.content and "50" in r.content and "80" in r.content), "desc": "补货汇总包含总数或各项明细"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 12 存在失败检查点\n{report}"

    # ---------- Case 13: 商品批量创建与属性完善 ----------

    async def test_case_19_supply_chain_exception_handling(self):
        """
        Case 19: 供应链异常处理链路（5轮）
        验证重点：物流异常→订单→售后→知识库联动
        涉及Skill: order, knowledge | Tools: logistics_track, order_query, order_manage, knowledge_search
        """
        runner = MultiTurnRunner(19, "供应链异常处理链路")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="客户反馈订单ORD20250425100的快递已经5天没更新了",
            expected_graph_result=make_graph_result(
                final_answer="我来查看物流状态。订单ORD20250425100物流信息：\n- 快递: 圆通 YT20250425888\n- 最新状态: 4月26日到达郑州中转站\n- 已停滞5天\n确实存在物流异常，我帮您进一步处理。",
                skill_used="order", intent="logistics_track", confidence=0.92,
                tool_name="logistics_track",
                tool_args={"order_id": "ORD20250425100"},
                tool_result_data={"tracking_number": "YT20250425888", "company": "圆通", "status": "stalled", "last_update": "2025-04-26", "traces": [{"desc": "到达郑州中转站", "time": "2025-04-26"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "停滞" in r.content or "异常" in r.content or "5天" in r.content, "desc": "确认物流异常"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="帮我查下这个订单的收件信息",
            expected_graph_result=make_graph_result(
                final_answer="订单ORD20250425100收件信息：\n- 收件人: 王先生\n- 电话: 13666666666\n- 地址: 浙江省杭州市西湖区XXX\n收件信息正确，应该不是地址问题。",
                skill_used="order", intent="order_query", confidence=0.90,
                tool_name="order_query",
                tool_args={"order_no": "ORD20250425100"},
                tool_result_data={"order_no": "ORD20250425100", "receiver": "王先生", "phone": "13666666666", "address": "浙江省杭州市西湖区XXX"},
            ),
            checks=[
                {"fn": lambda s, r, e: "杭州" in r.content or "王先生" in r.content, "desc": "查到收件信息"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="按照我们的物流异常政策，这种情况怎么处理",
            expected_graph_result=make_graph_result(
                final_answer="根据物流异常处理政策：\n- 停滞3-5天：联系快递公司催件\n- 停滞超5天：可选择①补发 ②退款\n- 赔偿标准：超5天补偿订单金额10%优惠券\n当前已超5天，建议与客户沟通选择补发或退款。",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.90,
                tool_name="knowledge_search",
                tool_args={"query": "物流异常停滞超5天处理政策"},
                tool_result_data={"chunks": [{"content": "停滞超5天可补发或退款，补偿10%优惠券"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""), "desc": "查询知识库获取政策"},
                {"fn": lambda s, r, e: "补发" in r.content or "退款" in r.content, "desc": "给出处理方案"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="客户选择补发，帮我处理",
            expected_graph_result=make_graph_result(
                final_answer="已为订单ORD20250425100安排补发：\n- 原订单标记为「物流异常-补发中」\n- 新发货将通过顺丰快递\n- 已添加10%优惠券补偿\n请通知客户预计2-3天到货。",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "update_status", "order_id": "ORD20250425100", "new_status": "resending", "reason": "物流异常补发"},
                tool_result_data={"order_no": "ORD20250425100", "new_status": "resending"},
            ),
            checks=[
                {"fn": lambda s, r, e: "补发" in r.content, "desc": "执行补发操作"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="新发的快递单号出来了吗",
            expected_graph_result=make_graph_result(
                final_answer="补发快递已发出：\n- 快递公司: 顺丰速运\n- 新单号: SF20250501999\n- 预计到达: 5月3日\n已通知客户新的物流信息。",
                skill_used="order", intent="logistics_track", confidence=0.88,
                tool_name="logistics_track",
                tool_args={"order_id": "ORD20250425100"},
                tool_result_data={"tracking_number": "SF20250501999", "company": "顺丰速运", "status": "in_transit", "estimated_arrival": "2025-05-03"},
            ),
            checks=[
                {"fn": lambda s, r, e: "SF20250501999" in r.content, "desc": "新物流单号追踪成功"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 19 存在失败检查点\n{report}"


    # ==================== C. 异常与边界处理类 ====================

    # ---------- Case 20: 订单不存在时的多策略恢复 ----------

    async def test_case_21_permission_graceful_degradation(self):
        """
        Case 21: 权限不足时的优雅降级（4轮）
        验证重点：权限检测、降级处理、引导
        涉及Skill: order | Tools: order_manage, order_query
        """
        runner = MultiTurnRunner(21, "权限不足时的优雅降级")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="帮我删除订单 ORD20250301001",
            expected_graph_result=make_graph_result(
                final_answer="抱歉，当前账号没有「删除订单」的权限。订单删除属于高危操作，需要管理员权限。\n我可以帮您：\n1. 取消订单（标记为已取消）\n2. 查看订单详情\n请问需要哪种操作？",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "delete", "order_id": "ORD20250301001"},
                tool_result_data={"error": "permission_denied", "required_role": "admin"},
            ),
            checks=[
                {"fn": lambda s, r, e: "权限" in r.content or "抱歉" in r.content, "desc": "提示权限不足"},
                {"fn": lambda s, r, e: "取消" in r.content or "查看" in r.content, "desc": "提供替代方案"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="那修改金额呢",
            expected_graph_result=make_graph_result(
                final_answer="修改订单金额也需要财务管理员权限，当前账号无此权限。\n可执行的操作包括：\n- 查询订单信息\n- 更新订单状态（发货/完成/取消）\n- 添加订单备注",
                skill_used="order", intent="order_query", confidence=0.85,
                tool_name="order_manage",
                tool_args={"action": "update_amount", "order_id": "ORD20250301001"},
                tool_result_data={"error": "permission_denied", "required_role": "finance_admin"},
            ),
            checks=[
                {"fn": lambda s, r, e: "权限" in r.content, "desc": "再次提示权限限制"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="那帮我查看这个订单详情吧",
            expected_graph_result=make_graph_result(
                final_answer="订单 ORD20250301001 详情：\n- 客户: 张三\n- 商品: 雪尼尔遮光帘 ×1\n- 金额: ¥299\n- 状态: 已完成\n- 下单时间: 2025-03-01",
                skill_used="order", intent="order_query", confidence=0.92,
                tool_name="order_query",
                tool_args={"order_no": "ORD20250301001"},
                tool_result_data={"order_no": "ORD20250301001", "customer_name": "张三", "total_amount": 299, "status": "completed"},
            ),
            checks=[
                {"fn": lambda s, r, e: "ORD20250301001" in r.content and "299" in r.content, "desc": "降级为查询操作成功"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="我需要删除订单的权限，怎么申请",
            expected_graph_result=make_graph_result(
                final_answer="申请高级权限流程：\n1. 联系系统管理员(admin@migao.com)\n2. 提交权限申请表，说明需要「订单删除」权限\n3. 管理员审批后即可生效\n如需紧急处理，可以直接联系管理员沟通。",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.80,
                tool_name="knowledge_search",
                tool_args={"query": "权限申请流程"},
                tool_result_data={"chunks": [{"content": "权限申请需联系管理员提交申请表"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "管理员" in r.content or "申请" in r.content, "desc": "引导权限申请流程"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 21 存在失败检查点\n{report}"

    # ---------- Case 22: 商品信息矛盾检测与修正 ----------

    async def test_case_23_logistics_exception_graded_handling(self):
        """
        Case 23: 物流异常分级处理（6轮）
        验证重点：分级判断、政策查询、方案执行
        涉及Skill: order, knowledge | Tools: logistics_track, order_query, knowledge_search, order_manage
        """
        runner = MultiTurnRunner(23, "物流异常分级处理")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="查一下 SF20250420001 这个快递",
            expected_graph_result=make_graph_result(
                final_answer="快递 SF20250420001 状态：\n- 公司: 顺丰速运\n- 状态: 异常-包裹破损\n- 最新: 4月22日 中转站发现外包装破损，已暂扣\n⚠️ 物流异常：包裹破损待处理",
                skill_used="order", intent="logistics_track", confidence=0.92,
                tool_name="logistics_track",
                tool_args={"tracking_number": "SF20250420001"},
                tool_result_data={"tracking_number": "SF20250420001", "company": "顺丰", "status": "damaged", "traces": [{"desc": "外包装破损，已暂扣", "time": "2025-04-22"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "破损" in r.content or "异常" in r.content, "desc": "识别物流异常类型"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="这是哪个订单的",
            expected_graph_result=make_graph_result(
                final_answer="快递SF20250420001对应的订单：\n- 订单号: ORD20250420055\n- 客户: 赵先生\n- 商品: 定制丝绒遮光帘 2.5m×2.8m ¥459\n- 下单时间: 4月20日",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_query",
                tool_args={"tracking_number": "SF20250420001"},
                tool_result_data={"order_no": "ORD20250420055", "customer_name": "赵先生", "items": [{"product_name": "定制丝绒遮光帘 2.5m×2.8m", "price": 459}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "ORD20250420055" in r.content, "desc": "关联到对应订单"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="包裹破损我们的政策是怎么处理的",
            expected_graph_result=make_graph_result(
                final_answer="物流破损处理政策（分级）：\n- 外包装破损、商品完好：继续配送，补偿¥20优惠券\n- 商品轻微受损：可选择①打折收货 ②补发\n- 商品严重受损：直接补发，向快递公司索赔\n建议先确认商品是否受损。",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.90,
                tool_name="knowledge_search",
                tool_args={"query": "物流包裹破损处理政策分级"},
                tool_result_data={"chunks": [{"content": "物流破损分级处理：外包装损-补优惠券；轻微损-打折或补发；严重损-直接补发"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "分级" in r.content or "破损" in r.content, "desc": "查询到分级处理政策"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="确认是商品轻微受损，客户选择补发",
            expected_graph_result=make_graph_result(
                final_answer="好的，按照「商品轻微受损-补发」方案处理：\n- 已将订单ORD20250420055标记为「破损补发中」\n- 将为客户重新发货\n- 原包裹由快递站退回",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "update_status", "order_id": "ORD20250420055", "new_status": "resending", "reason": "物流破损补发"},
                tool_result_data={"order_no": "ORD20250420055", "new_status": "resending"},
            ),
            checks=[
                {"fn": lambda s, r, e: "补发" in r.content, "desc": "执行补发方案"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="补发的新快递已发出，单号SF20250502888",
            expected_graph_result=make_graph_result(
                final_answer="已记录新快递单号 SF20250502888。当前物流状态：\n- 顺丰速运\n- 已揽收\n- 预计5月4日送达\n将持续追踪新包裹状态。",
                skill_used="order", intent="logistics_track", confidence=0.88,
                tool_name="logistics_track",
                tool_args={"tracking_number": "SF20250502888"},
                tool_result_data={"tracking_number": "SF20250502888", "status": "picked_up", "estimated_arrival": "2025-05-04"},
            ),
            checks=[
                {"fn": lambda s, r, e: "SF20250502888" in r.content, "desc": "新快递追踪正常"},
            ],
        )

        await runner.run_turn(
            turn_num=6,
            user_message="等收货确认后再帮我把订单改成完成",
            expected_graph_result=make_graph_result(
                final_answer="好的，我记住了。等客户确认收货后将订单ORD20250420055标记为已完成。届时请告诉我一声。",
                skill_used="order", intent="order_query", confidence=0.80,
            ),
            checks=[
                {"fn": lambda s, r, e: "确认" in r.content or "记住" in r.content, "desc": "记录待执行操作"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 23 存在失败检查点\n{report}"

    # ---------- Case 24: 连续错误输入的容错处理 ----------

    async def test_case_24_continuous_error_tolerance(self):
        """
        Case 24: 连续错误输入的容错处理（4轮）
        验证重点：乱码/不完整/格式错误的容错
        涉及Skill: general, order | Tools: order_query
        """
        runner = MultiTurnRunner(24, "连续错误输入的容错处理")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="ajskdhf 2131jkasd",
            expected_graph_result=make_graph_result(
                final_answer="抱歉，我没能理解您的输入。您可以试试：\n1. 查询订单（如：查订单 ORD20250101001）\n2. 搜索商品（如：搜索遮光窗帘）\n3. 咨询知识（如：窗帘怎么选）\n请问需要什么帮助？",
                skill_used="general_agent", intent="general", confidence=0.15,
            ),
            checks=[
                {"fn": lambda s, r, e: e.get("intent_result", {}).get("confidence", 1.0) < 0.3, "desc": "乱码置信度极低"},
                {"fn": lambda s, r, e: "帮助" in r.content or "试试" in r.content, "desc": "给出使用引导"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="查订单",
            expected_graph_result=make_graph_result(
                final_answer="请提供更多信息来查询订单，比如：\n- 订单号（如 ORD20250101001）\n- 客户手机号\n- 客户姓名\n- 或者按状态/日期筛选",
                skill_used="order", intent="order_query", confidence=0.70,
            ),
            checks=[
                {"fn": lambda s, r, e: "订单号" in r.content or "手机号" in r.content, "desc": "引导补充查询条件"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="ORD-2025-0501-001",
            expected_graph_result=make_graph_result(
                final_answer="未找到订单「ORD-2025-0501-001」。我们的订单号格式通常是 ORD 后跟数字（如ORD20250501001）。您输入的格式可能不正确，请确认后重试。",
                skill_used="order", intent="order_query", confidence=0.80,
                tool_name="order_query",
                tool_args={"order_no": "ORD-2025-0501-001"},
                tool_result_data=None,
            ),
            checks=[
                {"fn": lambda s, r, e: "格式" in r.content or "不正确" in r.content, "desc": "提示格式错误"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="ORD20250501001",
            expected_graph_result=make_graph_result(
                final_answer="找到了！订单 ORD20250501001：\n- 客户: 刘女士\n- 商品: 雪尼尔遮光帘 ¥299\n- 状态: 待发货\n- 下单时间: 5月1日",
                skill_used="order", intent="order_query", confidence=0.95,
                tool_name="order_query",
                tool_args={"order_no": "ORD20250501001"},
                tool_result_data={"order_no": "ORD20250501001", "customer_name": "刘女士", "total_amount": 299, "status": "pending_shipment"},
            ),
            checks=[
                {"fn": lambda s, r, e: "ORD20250501001" in r.content and "299" in r.content, "desc": "正确输入后成功查询"},
                {"fn": lambda s, r, e: e.get("intent_result", {}).get("confidence", 0) >= 0.9, "desc": "正确输入后置信度恢复"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 24 存在失败检查点\n{report}"

    # ==================== D. 深度上下文与记忆类 ====================

    # ---------- Case 25: 跨4个Skill的复杂指代消解链 ----------

