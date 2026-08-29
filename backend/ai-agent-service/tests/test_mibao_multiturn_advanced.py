"""
米宝多轮 — 高级域（画像/指代/生命周期/话题切换/思考剥离）

（由 test_mibao_advanced_multiturn.py 按场景域拆分，2026-08-29）
"""
# case_ids: CH-002, CH-005, CH-006
from unittest.mock import patch, AsyncMock, MagicMock

from tests.mibao_multiturn_shared import (
    MultiTurnRunner, make_graph_result, make_thinking_response,
    verify_thinking_stripped, verify_thinking_not_leaked, _reset_singletons,
    TurnResult, CaseResult,
)


class TestMibaoMultiturnAdvanced:
    """米宝多轮 — 高级域（画像/指代/生命周期/话题切换/思考剥离）"""

    async def test_case_18_customer_portrait_building(self):
        """
        Case 18: 客户全景画像构建（6轮）
        验证重点：跨多个Tool聚合客户信息
        涉及Skill: order, product, knowledge | Tools: order_query, product_detail, knowledge_search
        """
        runner = MultiTurnRunner(18, "客户全景画像构建")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="帮我看看手机号13912345678的客户所有订单",
            expected_graph_result=make_graph_result(
                final_answer="客户(13912345678)共有5个订单：\n1. ORD0301 雪尼尔遮光帘 ¥299 已完成\n2. ORD0315 雪尼尔绒感帘 ¥259 已完成\n3. ORD0401 丝绒遮光帘 ¥369 已完成\n4. ORD0420 北欧纱帘 ¥129 已完成\n5. ORD0501 雪尼尔遮光帘 ¥299 已发货",
                skill_used="order", intent="order_query", confidence=0.92,
                tool_name="order_query",
                tool_args={"customer_phone": "13912345678"},
                tool_result_data={"orders": [
                    {"order_no": "ORD0301", "product_name": "雪尼尔遮光帘", "total_amount": 299},
                    {"order_no": "ORD0315", "product_name": "雪尼尔绒感帘", "total_amount": 259},
                    {"order_no": "ORD0401", "product_name": "丝绒遮光帘", "total_amount": 369},
                    {"order_no": "ORD0420", "product_name": "北欧纱帘", "total_amount": 129},
                    {"order_no": "ORD0501", "product_name": "雪尼尔遮光帘", "total_amount": 299},
                ], "total": 5},
            ),
            checks=[
                {"fn": lambda s, r, e: "5" in r.content, "desc": "查到客户全部订单"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="这个客户买得最多的是什么类型的",
            expected_graph_result=make_graph_result(
                final_answer="该客户购买偏好分析：\n- 雪尼尔系列: 3次（60%）— 明显偏好\n- 丝绒系列: 1次\n- 纱帘系列: 1次\n主要偏好：高品质遮光面料，预算区间¥259-369。",
                skill_used="order", intent="order_query", confidence=0.82,
            ),
            checks=[
                {"fn": lambda s, r, e: "雪尼尔" in r.content and ("3" in r.content or "60" in r.content), "desc": "分析出购买偏好"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="那个雪尼尔遮光帘的详细信息给我看看",
            expected_graph_result=make_graph_result(
                final_answer="雪尼尔遮光帘(p001)：\n- 价格: ¥299\n- 面料: 雪尼尔\n- 遮光率: 95%\n- 颜色: 米白/浅灰/深咖\n- 规格: 支持定制\n- 好评率: 96%",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_detail",
                tool_args={"product_id": "p001"},
                tool_result_data={"id": "p001", "name": "雪尼尔遮光帘", "price": 299, "specifications": {"面料": "雪尼尔", "遮光率": "95%"}},
            ),
            checks=[
                {"fn": lambda s, r, e: "product" in e.get("skill_used", ""), "desc": "跨Skill到product查详情"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="这种面料怎么保养，客户可能会问",
            expected_graph_result=make_graph_result(
                final_answer="雪尼尔面料保养指南：\n1. 日常：吸尘器轻吸除尘\n2. 清洗：建议干洗，不可机洗\n3. 晾晒：避免阳光直射\n4. 存放：卷起收纳，避免折叠\n可以将此保养卡发送给客户。",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.90,
                tool_name="knowledge_search",
                tool_args={"query": "雪尼尔面料保养"},
                tool_result_data={"chunks": [{"content": "雪尼尔面料保养方法：干洗、避光、卷起收纳"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""), "desc": "跨Skill到knowledge查保养"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="根据这个客户的购买习惯，有什么新品可以推荐",
            expected_graph_result=make_graph_result(
                final_answer="基于该客户偏好（雪尼尔+高遮光率），推荐新品：\n1. 雪尼尔加厚遮光帘(新) ¥359 - 遮光98%\n2. 雪尼尔星空系列 ¥329 - 遮光95%+星空印花\n理由：符合客户面料偏好和价格区间。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="product_search",
                tool_args={"keyword": "雪尼尔", "min_price": 250, "max_price": 400},
                tool_result_data={"products": [
                    {"id": "p050", "name": "雪尼尔加厚遮光帘", "price": 359},
                    {"id": "p051", "name": "雪尼尔星空系列", "price": 329},
                ]},
            ),
            checks=[
                {"fn": lambda s, r, e: "推荐" in r.content, "desc": "生成个性化推荐"},
            ],
        )

        await runner.run_turn(
            turn_num=6,
            user_message="好的，帮我总结一下这个客户的画像",
            expected_graph_result=make_graph_result(
                final_answer="客户画像总结(13912345678)：\n📊 消费频次: 5单/2个月(高活跃)\n💰 客单价: ¥271(中高端)\n🎯 偏好面料: 雪尼尔(占60%)\n🏠 使用场景: 卧室遮光为主\n📈 推荐策略: 推送雪尼尔新品+遮光升级款",
                skill_used="order", intent="order_query", confidence=0.80,
            ),
            checks=[
                {"fn": lambda s, r, e: "画像" in r.content or "偏好" in r.content, "desc": "生成客户画像总结"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 18 存在失败检查点\n{report}"

    # ---------- Case 19: 供应链异常处理链路 ----------

    async def test_case_25_cross_skill_coreference_chain(self):
        """
        Case 25: 跨4个Skill的复杂指代消解链（5轮）
        验证重点：跨Skill指代消解、实体传递
        涉及Skill: product, order, knowledge | Tools: product_search, order_query, logistics_track, knowledge_search, order_manage
        """
        runner = MultiTurnRunner(25, "跨4个Skill的复杂指代消解链")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="搜一下遮光窗帘",
            expected_graph_result=make_graph_result(
                final_answer="找到3款遮光窗帘：\n1. 雪尼尔遮光帘 ¥299 (p001)\n2. 丝绒遮光帘 ¥369 (p003)\n3. 涂银全遮光帘 ¥159 (p004)",
                skill_used="product", intent="product_inquiry", confidence=0.92,
                tool_name="product_search",
                tool_args={"keyword": "遮光窗帘"},
                tool_result_data={"products": [
                    {"id": "p001", "name": "雪尼尔遮光帘", "price": 299},
                    {"id": "p003", "name": "丝绒遮光帘", "price": 369},
                    {"id": "p004", "name": "涂银全遮光帘", "price": 159},
                ]},
            ),
            checks=[
                {"fn": lambda s, r, e: "product" in e.get("skill_used", ""), "desc": "product Skill处理搜索"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="第一个最近有谁买过",
            expected_graph_result=make_graph_result(
                final_answer="雪尼尔遮光帘(p001)最近订单：\n- ORD20250501088 李先生 5月1日\n- ORD20250428066 李女士 4月28日",
                skill_used="order", intent="order_query", confidence=0.85,
                tool_name="order_query",
                tool_args={"product_id": "p001"},
                tool_result_data={"orders": [
                    {"order_no": "ORD20250501088", "customer_name": "李先生"},
                    {"order_no": "ORD20250428066", "customer_name": "李女士"},
                ]},
            ),
            checks=[
                {"fn": lambda s, r, e: "order" in e.get("skill_used", ""), "desc": "跨到order Skill（指代消解'第一个'→p001）"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="第一个订单的物流到哪了",
            expected_graph_result=make_graph_result(
                final_answer="订单ORD20250501088物流：\n- 快递: 顺丰 SF20250502001\n- 状态: 已到达杭州分拣中心\n- 预计明天送达",
                skill_used="order", intent="logistics_track", confidence=0.88,
                tool_name="logistics_track",
                tool_args={"order_id": "ORD20250501088"},
                tool_result_data={"tracking_number": "SF20250502001", "status": "in_transit"},
            ),
            checks=[
                {"fn": lambda s, r, e: "SF20250502001" in r.content or "物流" in r.content, "desc": "物流追踪（指代消解'第一个订单'→ORD20250501088）"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="那个商品的安装方法是什么",
            expected_graph_result=make_graph_result(
                final_answer="雪尼尔遮光帘安装方法：\n1. 确认窗帘杆/轨道已安装\n2. 将窗帘挂钩插入帘头孔\n3. 逐个挂到窗帘杆环上\n4. 调整帘褶均匀度\n注意：建议两人配合安装大尺寸窗帘。",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.88,
                tool_name="knowledge_search",
                tool_args={"query": "雪尼尔遮光帘安装方法"},
                tool_result_data={"chunks": [{"content": "窗帘安装步骤：挂钩→挂杆→调整"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""), "desc": "跨到knowledge（指代消解'那个商品'→雪尼尔遮光帘）"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="帮我取消那个订单",
            expected_graph_result=make_graph_result(
                final_answer="已取消订单 ORD20250501088（李先生的雪尼尔遮光帘订单）。",
                skill_used="order", intent="order_query", confidence=0.85,
                tool_name="order_manage",
                tool_args={"action": "cancel", "order_id": "ORD20250501088"},
                tool_result_data={"order_no": "ORD20250501088", "status": "cancelled"},
            ),
            checks=[
                {"fn": lambda s, r, e: "order" in e.get("skill_used", ""), "desc": "跨回order（指代消解'那个订单'→ORD20250501088）"},
                {"fn": lambda s, r, e: "取消" in r.content, "desc": "取消操作成功"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 25 存在失败检查点\n{report}"

    # ---------- Case 26: 对话阶段完整生命周期 ----------

    async def test_case_26_conversation_lifecycle(self):
        """
        Case 26: 对话阶段完整生命周期（6轮）
        验证重点：INITIAL→QUERYING→CONFIRMING→PROCESSING→COMPLETED→INITIAL
        涉及Skill: direct_reply, product, order | Tools: product_search, product_detail, order_manage
        """
        runner = MultiTurnRunner(26, "对话阶段完整生命周期")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # INITIAL
        await runner.run_turn(
            turn_num=1,
            user_message="你好，我想买窗帘",
            expected_graph_result=make_graph_result(
                final_answer="您好！欢迎光临。我可以帮您挑选窗帘。请问您有什么需求？比如遮光、装饰、或者特定风格？",
                skill_used="direct_reply", intent="greeting", confidence=0.90,
            ),
            checks=[
                {"fn": lambda s, r, e: "greeting" in e.get("intent_result", {}).get("intent", ""), "desc": "阶段INITIAL: 问候识别"},
            ],
        )

        # QUERYING
        await runner.run_turn(
            turn_num=2,
            user_message="想要遮光效果好的，预算300左右",
            expected_graph_result=make_graph_result(
                final_answer="为您推荐300左右的遮光帘：\n1. 雪尼尔遮光帘 ¥299 遮光95%\n2. 雪尼尔星空系列 ¥329 遮光95%\n要看哪款的详情？",
                skill_used="product", intent="product_inquiry", confidence=0.92,
                tool_name="product_search",
                tool_args={"keyword": "遮光", "min_price": 200, "max_price": 400},
                tool_result_data={"products": [{"id": "p001", "name": "雪尼尔遮光帘", "price": 299}, {"id": "p051", "name": "雪尼尔星空系列", "price": 329}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "product_inquiry" in e.get("intent_result", {}).get("intent", ""), "desc": "阶段QUERYING: 商品查询"},
            ],
        )

        # CONFIRMING
        await runner.run_turn(
            turn_num=3,
            user_message="第一个不错，想要这个",
            expected_graph_result=make_graph_result(
                final_answer="确认您选择「雪尼尔遮光帘」¥299：\n- 遮光率95%\n- 可选颜色: 米白/浅灰/深咖\n- 支持尺寸定制\n请问需要什么颜色和尺寸？确认后可以下单。",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_detail",
                tool_args={"product_id": "p001"},
                tool_result_data={"id": "p001", "name": "雪尼尔遮光帘", "price": 299, "colors": ["米白", "浅灰", "深咖"]},
            ),
            checks=[
                {"fn": lambda s, r, e: "确认" in r.content, "desc": "阶段CONFIRMING: 确认购买意向"},
            ],
        )

        # PROCESSING
        await runner.run_turn(
            turn_num=4,
            user_message="浅灰色，宽2米高2.5米",
            expected_graph_result=make_graph_result(
                final_answer="已为您记录选择：\n- 商品: 雪尼尔遮光帘\n- 颜色: 浅灰\n- 尺寸: 2m×2.5m\n- 金额: ¥299\n订单已创建，等待支付确认。",
                skill_used="order", intent="order_query", confidence=0.85,
                tool_name="order_manage",
                tool_args={"action": "create", "product_id": "p001", "specifications": {"color": "浅灰", "width": "2m", "height": "2.5m"}},
                tool_result_data={"order_no": "ORD20250505NEW", "status": "pending_payment"},
            ),
            checks=[
                {"fn": lambda s, r, e: "创建" in r.content or "记录" in r.content, "desc": "阶段PROCESSING: 订单创建"},
            ],
        )

        # COMPLETED
        await runner.run_turn(
            turn_num=5,
            user_message="好的，已经付款了",
            expected_graph_result=make_graph_result(
                final_answer="收到付款确认！订单ORD20250505NEW已更新为「待发货」状态。预计1-2天内发货，届时我会通知您物流信息。感谢购买！",
                skill_used="order", intent="order_query", confidence=0.88,
                tool_name="order_manage",
                tool_args={"action": "update_status", "order_id": "ORD20250505NEW", "new_status": "pending_shipment"},
                tool_result_data={"order_no": "ORD20250505NEW", "new_status": "pending_shipment"},
            ),
            checks=[
                {"fn": lambda s, r, e: "感谢" in r.content or "待发货" in r.content, "desc": "阶段COMPLETED: 交易完成"},
            ],
        )

        # 回到 INITIAL
        await runner.run_turn(
            turn_num=6,
            user_message="谢谢，再见",
            expected_graph_result=make_graph_result(
                final_answer="不客气！祝您生活愉快，有需要随时找我。再见！",
                skill_used="direct_reply", intent="farewell", confidence=0.95,
            ),
            checks=[
                {"fn": lambda s, r, e: "farewell" in e.get("intent_result", {}).get("intent", ""), "desc": "阶段回到INITIAL: 告别"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 26 存在失败检查点\n{report}"

    # ---------- Case 27: 会话中途主题切换与回溯 ----------

    async def test_case_27_topic_switch_and_backtrack(self):
        """
        Case 27: 会话中途主题切换与回溯（6轮）
        验证重点：主题切换、"回到刚才"的回溯、两个主题并行
        涉及Skill: product, order | Tools: product_detail, logistics_track, product_manage
        """
        runner = MultiTurnRunner(27, "会话中途主题切换与回溯")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="帮我看看丝绒遮光帘的详情",
            expected_graph_result=make_graph_result(
                final_answer="丝绒遮光帘(p003)：\n- 价格: ¥369\n- 面料: 丝绒\n- 遮光率: 99%\n- 颜色: 深蓝/墨绿/酒红\n- 重量: 较重，需要加固杆",
                skill_used="product", intent="product_inquiry", confidence=0.90,
                tool_name="product_detail",
                tool_args={"product_id": "p003"},
                tool_result_data={"id": "p003", "name": "丝绒遮光帘", "price": 369},
            ),
            checks=[
                {"fn": lambda s, r, e: "丝绒" in r.content, "desc": "主题A启动：查看丝绒遮光帘"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="等一下，先帮我查个物流 ORD20250501088",
            expected_graph_result=make_graph_result(
                final_answer="订单ORD20250501088物流：\n- 快递: 韵达 YD20250502333\n- 状态: 配送中\n- 预计今天送达\n查完了，需要继续看刚才的商品吗？",
                skill_used="order", intent="logistics_track", confidence=0.92,
                tool_name="logistics_track",
                tool_args={"order_id": "ORD20250501088"},
                tool_result_data={"tracking_number": "YD20250502333", "company": "韵达", "status": "delivering"},
            ),
            checks=[
                {"fn": lambda s, r, e: "logistics_track" in e.get("intent_result", {}).get("intent", ""), "desc": "主题切换：突然问物流"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="这个包裹到了联系客户确认收货",
            expected_graph_result=make_graph_result(
                final_answer="好的，订单ORD20250501088快递已在配送中，到货后我提醒您联系客户确认收货。",
                skill_used="order", intent="order_query", confidence=0.82,
            ),
            checks=[
                {"fn": lambda s, r, e: "确认收货" in r.content or "提醒" in r.content, "desc": "物流主题继续处理"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="回到刚才那个商品，帮我调一下价格到349",
            expected_graph_result=make_graph_result(
                final_answer="已将「丝绒遮光帘」(p003) 价格调整：¥369→¥349。",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_manage",
                tool_args={"action": "update", "product_id": "p003", "price": 349},
                tool_result_data={"id": "p003", "price": 349},
            ),
            checks=[
                {"fn": lambda s, r, e: "丝绒" in r.content and "349" in r.content, "desc": "回溯到主题A（指代消解'刚才那个商品'→丝绒遮光帘）"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="这个商品再补50件库存",
            expected_graph_result=make_graph_result(
                final_answer="已为「丝绒遮光帘」(p003) 补货50件，当前库存250件。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="inventory_manage",
                tool_args={"action": "adjust", "product_id": "p003", "quantity": 50},
                tool_result_data={"product_id": "p003", "new_stock": 250},
            ),
            checks=[
                {"fn": lambda s, r, e: "250" in r.content or "50" in r.content, "desc": "继续主题A操作"},
            ],
        )

        await runner.run_turn(
            turn_num=6,
            user_message="今天处理了两件事，帮我总结一下",
            expected_graph_result=make_graph_result(
                final_answer="今日处理总结：\n1. 物流追踪：订单ORD20250501088（韵达配送中，待确认收货）\n2. 商品管理：丝绒遮光帘(p003) 调价369→349，补货50件(库存250)\n两件事都已处理完毕。",
                skill_used="general_agent", intent="general", confidence=0.75,
            ),
            checks=[
                {"fn": lambda s, r, e: "ORD20250501088" in r.content and "丝绒" in r.content, "desc": "总结覆盖两个主题"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 27 存在失败检查点\n{report}"

    # ==================== E. Thinking Mode 专项验证类 ====================

    # ---------- Case 28: 复杂推理：多条件商品筛选决策 ----------

    async def test_case_28_thinking_complex_product_reasoning(self):
        """
        Case 28: 复杂推理：多条件商品筛选决策（5轮）
        验证重点：thinking mode推理过程、多条件组合搜索
        涉及Skill: product, knowledge | Tools: product_search, product_detail, knowledge_search
        """
        runner = MultiTurnRunner(28, "复杂推理：多条件商品筛选决策")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        thinking_1 = "用户需求分析：预算300以内+北欧风格+遮光好。需要搜索遮光帘类目，价格筛选300以下，风格关键词北欧。"

        await runner.run_turn(
            turn_num=1,
            user_message="我预算300以内，想要北欧风格的，遮光效果要好的窗帘",
            expected_graph_result=make_graph_result(
                final_answer="根据您的需求（预算≤300、北欧风格、高遮光），为您筛选：\n1. 北欧简约遮光帘 ¥199 遮光90%\n2. 北欧灰调遮光帘 ¥269 遮光95%\n3. 北欧几何纹遮光帘 ¥289 遮光92%\n推荐第2款，性价比和遮光率最优。",
                skill_used="product", intent="product_inquiry", confidence=0.90,
                tool_name="product_search",
                tool_args={"keyword": "北欧遮光", "max_price": 300},
                tool_result_data={"products": [
                    {"id": "p002", "name": "北欧简约遮光帘", "price": 199, "blackout_rate": "90%"},
                    {"id": "p030", "name": "北欧灰调遮光帘", "price": 269, "blackout_rate": "95%"},
                    {"id": "p031", "name": "北欧几何纹遮光帘", "price": 289, "blackout_rate": "92%"},
                ]},
                thinking_content=thinking_1,
            ),
            checks=[
                {"fn": lambda s, r, e: "北欧" in r.content and "遮光" in r.content, "desc": "多条件筛选结果正确"},
                {"fn": lambda s, r, e: "<think>" not in r.content, "desc": "thinking标签未泄露到回复中"},
                {"fn": lambda s, r, e: thinking_1 not in r.content, "desc": "thinking内容未泄露到回复中"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="第二个遮光95%是真的吗，怎么做到的",
            expected_graph_result=make_graph_result(
                final_answer="北欧灰调遮光帘遮光率95%的技术原理：\n- 采用三层复合结构（面料+遮光涂层+里布）\n- 中间层为银色遮光涂层\n- 经国标GB/T测试达95%\n是真实数据，不是虚标。",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.88,
                tool_name="knowledge_search",
                tool_args={"query": "遮光帘95%遮光率原理"},
                tool_result_data={"chunks": [{"content": "三层复合结构+遮光涂层实现95%遮光率"}]},
                thinking_content="用户质疑遮光率数据，需要从知识库找到遮光率的技术原理来解答",
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""), "desc": "技术问题走knowledge"},
                {"fn": lambda s, r, e: "<think>" not in r.content, "desc": "thinking标签未泄露"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="和第三个比呢，哪个更适合卧室",
            expected_graph_result=make_graph_result(
                final_answer="卧室推荐对比：\n| | 北欧灰调 ¥269 | 北欧几何纹 ¥289 |\n|遮光|95% ✓|92%|\n|风格|纯色低调|几何图案|\n|适合|极简卧室|有设计感的卧室|\n\n💡推理结论：如果纯粹追求遮光睡眠，选灰调款；如果想要设计感，选几何纹款。",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_detail",
                tool_args={"product_id": "p030"},
                tool_result_data={"id": "p030", "name": "北欧灰调遮光帘", "price": 269},
                thinking_content="对比两款商品：灰调遮光率更高适合纯睡眠场景，几何纹有设计感适合想要装饰效果的卧室",
            ),
            checks=[
                {"fn": lambda s, r, e: "灰调" in r.content and "几何" in r.content, "desc": "对比分析两款商品"},
                {"fn": lambda s, r, e: "<think>" not in r.content, "desc": "thinking标签清除验证"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="我就要遮光最好的那个",
            expected_graph_result=make_graph_result(
                final_answer="好的，为您确认选择「北欧灰调遮光帘」¥269（遮光率95%）。这是您预算范围内遮光效果最好的选择。需要什么尺寸和颜色？",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                thinking_content="用户说'遮光最好的'，根据之前对比，灰调款95%>几何纹92%，所以选灰调款",
            ),
            checks=[
                {"fn": lambda s, r, e: "灰调" in r.content or "269" in r.content, "desc": "推理出最优选择"},
                {"fn": lambda s, r, e: "<think>" not in r.content, "desc": "thinking内容不泄露"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="灰色，宽1.8米高2.4米",
            expected_graph_result=make_graph_result(
                final_answer="已确认：\n- 商品: 北欧灰调遮光帘\n- 颜色: 灰色\n- 尺寸: 1.8m×2.4m\n- 价格: ¥269\n遮光率95%，非常适合卧室使用。如需下单请确认。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
            ),
            checks=[
                {"fn": lambda s, r, e: "1.8" in r.content and "2.4" in r.content, "desc": "规格确认完整"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 28 存在失败检查点\n{report}"

    # ---------- Case 29: 复杂推理：售后纠纷判责 ----------

    async def test_case_30_thinking_output_strip_verification(self):
        """
        Case 30: Thinking输出清理验证（4轮）
        验证重点：_strip_think_tags()正确性、thinking不泄露
        涉及Skill: product, order | Tools: product_search, order_query
        """
        runner = MultiTurnRunner(30, "Thinking输出清理验证")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        # 轮1: 模拟LLM返回带think标签的响应
        thinking_content_1 = "用户想搜索窗帘，应该调用product_search工具，关键词为窗帘"
        raw_response_1 = make_thinking_response(thinking_content_1, "为您找到以下窗帘商品：\n1. 雪尼尔遮光帘 ¥299")
        clean_answer_1 = "为您找到以下窗帘商品：\n1. 雪尼尔遮光帘 ¥299"

        await runner.run_turn(
            turn_num=1,
            user_message="搜一下窗帘",
            expected_graph_result=make_graph_result(
                final_answer=clean_answer_1,
                skill_used="product", intent="product_inquiry", confidence=0.90,
                tool_name="product_search",
                tool_args={"keyword": "窗帘"},
                tool_result_data={"products": [{"id": "p001", "name": "雪尼尔遮光帘", "price": 299}]},
                thinking_content=thinking_content_1,
            ),
            checks=[
                {"fn": lambda s, r, e: verify_thinking_stripped(raw_response_1, r.content), "desc": "_strip_think_tags: think标签已清除"},
                {"fn": lambda s, r, e: verify_thinking_not_leaked(r.content, thinking_content_1), "desc": "thinking内容未泄露给用户"},
                {"fn": lambda s, r, e: "窗帘" in r.content, "desc": "最终回答内容正确"},
            ],
        )

        # 轮2: 复杂thinking（含多行推理）
        thinking_content_2 = "用户说'查订单'但没给订单号。分析上下文：之前搜了窗帘。可能是想查和窗帘相关的订单。但不确定，应该问清楚。考虑因素：1.用户可能是管理员查看订单列表 2.也可能是查具体订单。决策：询问更多信息。"
        clean_answer_2 = "请问您想查哪个订单？可以提供订单号、客户手机号或姓名来查询。"

        await runner.run_turn(
            turn_num=2,
            user_message="查个订单",
            expected_graph_result=make_graph_result(
                final_answer=clean_answer_2,
                skill_used="order", intent="order_query", confidence=0.70,
                thinking_content=thinking_content_2,
            ),
            checks=[
                {"fn": lambda s, r, e: verify_thinking_stripped(make_thinking_response(thinking_content_2, clean_answer_2), r.content), "desc": "_strip_think_tags: 多行thinking清除"},
                {"fn": lambda s, r, e: "分析上下文" not in r.content and "决策" not in r.content, "desc": "推理过程关键词不出现在回复中"},
                {"fn": lambda s, r, e: "订单号" in r.content or "手机号" in r.content, "desc": "回复正常引导用户"},
            ],
        )

        # 轮3: thinking含特殊字符和代码片段
        thinking_content_3 = "用户提供了订单号ORD20250501001。调用order_query(order_no='ORD20250501001')。结果：{status: 'shipped', amount: 299}。格式化输出给用户。"
        clean_answer_3 = "订单 ORD20250501001：\n- 状态: 已发货\n- 金额: ¥299\n- 快递: 顺丰速运"

        await runner.run_turn(
            turn_num=3,
            user_message="ORD20250501001",
            expected_graph_result=make_graph_result(
                final_answer=clean_answer_3,
                skill_used="order", intent="order_query", confidence=0.95,
                tool_name="order_query",
                tool_args={"order_no": "ORD20250501001"},
                tool_result_data={"order_no": "ORD20250501001", "status": "shipped", "total_amount": 299},
                thinking_content=thinking_content_3,
            ),
            checks=[
                {"fn": lambda s, r, e: "order_query" not in r.content, "desc": "thinking中的工具调用细节不泄露"},
                {"fn": lambda s, r, e: "格式化输出" not in r.content, "desc": "thinking中的内部指令不泄露"},
                {"fn": lambda s, r, e: "ORD20250501001" in r.content and "299" in r.content, "desc": "最终回答包含正确订单信息"},
            ],
        )

        # 轮4: 嵌套think标签（边界情况）
        thinking_content_4 = "用户问物流状态。<think>这是嵌套标签测试</think>需要调用logistics_track。"
        clean_answer_4 = "物流状态：已到达杭州分拣中心，预计明天送达。"

        await runner.run_turn(
            turn_num=4,
            user_message="物流到哪了",
            expected_graph_result=make_graph_result(
                final_answer=clean_answer_4,
                skill_used="order", intent="logistics_track", confidence=0.88,
                tool_name="logistics_track",
                tool_args={"order_id": "ORD20250501001"},
                tool_result_data={"status": "in_transit", "location": "杭州分拣中心"},
                thinking_content=thinking_content_4,
            ),
            checks=[
                {"fn": lambda s, r, e: "<think>" not in r.content and "</think>" not in r.content, "desc": "嵌套think标签全部清除"},
                {"fn": lambda s, r, e: "嵌套标签测试" not in r.content, "desc": "嵌套thinking内容不泄露"},
                {"fn": lambda s, r, e: "杭州" in r.content or "明天" in r.content, "desc": "最终回答正常输出"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 30 存在失败检查点\n{report}"


# ========== 汇总报告测试 ==========

