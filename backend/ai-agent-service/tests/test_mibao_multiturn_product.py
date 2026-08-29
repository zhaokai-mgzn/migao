"""
米宝多轮 — 商品域（批量创建/促销/推荐/不一致检测）

（由 test_mibao_advanced_multiturn.py 按场景域拆分，2026-08-29）
"""
# case_ids: PR-011, PR-012
from unittest.mock import patch, AsyncMock, MagicMock

from tests.mibao_multiturn_shared import (
    MultiTurnRunner, make_graph_result, make_thinking_response,
    verify_thinking_stripped, verify_thinking_not_leaked, _reset_singletons,
    TurnResult, CaseResult,
)


class TestMibaoMultiturnProduct:
    """米宝多轮 — 商品域（批量创建/促销/推荐/不一致检测）"""

    async def test_case_13_batch_product_create_and_refine(self):
        """
        Case 13: 商品批量创建与属性完善（5轮）
        验证重点：连续创建、属性补充、批量上架
        涉及Skill: product | Tools: product_manage, product_detail
        """
        runner = MultiTurnRunner(13, "商品批量创建与属性完善")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="帮我新建一个商品'丝绒遮光帘'，价格369",
            expected_graph_result=make_graph_result(
                final_answer="商品「丝绒遮光帘」已创建成功！\n- 商品ID: p_new_101\n- 价格: ¥369\n- 状态: 待上架",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_manage",
                tool_args={"action": "create", "name": "丝绒遮光帘", "price": 369},
                tool_result_data={"id": "p_new_101", "name": "丝绒遮光帘", "price": 369.0, "status": "draft"},
            ),
            checks=[
                {"fn": lambda s, r, e: "p_new_101" in r.content or "丝绒" in r.content, "desc": "商品A创建成功"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="再建一个'竹纤维卷帘'，价格229",
            expected_graph_result=make_graph_result(
                final_answer="商品「竹纤维卷帘」已创建成功！\n- 商品ID: p_new_102\n- 价格: ¥229\n- 状态: 待上架",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_manage",
                tool_args={"action": "create", "name": "竹纤维卷帘", "price": 229},
                tool_result_data={"id": "p_new_102", "name": "竹纤维卷帘", "price": 229.0, "status": "draft"},
            ),
            checks=[
                {"fn": lambda s, r, e: "p_new_102" in r.content or "竹纤维" in r.content, "desc": "商品B创建成功"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="刚才那个丝绒遮光帘我忘了加分类了，帮我加到遮光帘分类下",
            expected_graph_result=make_graph_result(
                final_answer="已将「丝绒遮光帘」(p_new_101) 设置到遮光帘分类下。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="product_manage",
                tool_args={"action": "update", "product_id": "p_new_101", "category_id": "cat_blackout"},
                tool_result_data={"id": "p_new_101", "category": "遮光帘"},
            ),
            checks=[
                {"fn": lambda s, r, e: "丝绒" in r.content and "分类" in r.content, "desc": "属性补充成功（跨轮指代消解）"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="给它加上面料属性：丝绒，遮光率98%",
            expected_graph_result=make_graph_result(
                final_answer="已为「丝绒遮光帘」(p_new_101) 添加属性：\n- 面料: 丝绒\n- 遮光率: 98%",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="product_manage",
                tool_args={"action": "update", "product_id": "p_new_101", "attributes": {"面料": "丝绒", "遮光率": "98%"}},
                tool_result_data={"id": "p_new_101", "attributes": {"面料": "丝绒", "遮光率": "98%"}},
            ),
            checks=[
                {"fn": lambda s, r, e: "丝绒" in r.content and "98%" in r.content, "desc": "属性添加成功"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="这两个新商品都上架吧",
            expected_graph_result=make_graph_result(
                final_answer="已批量上架：\n- 丝绒遮光帘(p_new_101) ✓\n- 竹纤维卷帘(p_new_102) ✓\n两款商品现已对客户可见。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="product_manage",
                tool_args={"action": "batch_toggle_status", "product_ids": ["p_new_101", "p_new_102"], "status": "on_sale"},
                tool_result_data={"updated": [{"id": "p_new_101", "status": "on_sale"}, {"id": "p_new_102", "status": "on_sale"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "上架" in r.content, "desc": "批量上架确认"},
                {"fn": lambda s, r, e: "p_new_101" in r.content and "p_new_102" in r.content, "desc": "两个商品都已上架"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 13 存在失败检查点\n{report}"

    # ---------- Case 14: 订单财务汇总与对账 ----------

    async def test_case_16_knowledge_driven_product_recommendation(self):
        """
        Case 16: 知识辅助的精准商品推荐（5轮）
        验证重点：knowledge→product联动推荐
        涉及Skill: knowledge, product | Tools: knowledge_search, product_search, product_detail
        """
        runner = MultiTurnRunner(16, "知识辅助的精准商品推荐")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="客户想要遮光效果好又透气的面料，有什么推荐",
            expected_graph_result=make_graph_result(
                final_answer="关于遮光又透气的需求：\n- 纯遮光面料（如涂银布）遮光100%但不透气\n- 雪尼尔面料遮光95%，有一定透气性\n- 三明治结构面料（外遮光+内透气）是最佳选择\n推荐您看看我们的三明治结构系列。",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.88,
                tool_name="knowledge_search",
                tool_args={"query": "遮光透气面料推荐"},
                tool_result_data={"chunks": [{"content": "三明治结构面料兼顾遮光与透气"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""), "desc": "先走知识库分析需求"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="三明治结构的有哪些款式",
            expected_graph_result=make_graph_result(
                final_answer="为您找到2款三明治结构窗帘：\n1. 三明治遮光透气帘 ¥459 - 遮光98%+微透气\n2. 双层复合功能帘 ¥399 - 遮光95%+自然透气",
                skill_used="product", intent="product_inquiry", confidence=0.90,
                tool_name="product_search",
                tool_args={"keyword": "三明治结构"},
                tool_result_data={"products": [
                    {"id": "p020", "name": "三明治遮光透气帘", "price": 459},
                    {"id": "p021", "name": "双层复合功能帘", "price": 399},
                ]},
            ),
            checks=[
                {"fn": lambda s, r, e: "product" in e.get("skill_used", ""), "desc": "切换到product搜索"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="这两个的区别是什么",
            expected_graph_result=make_graph_result(
                final_answer="两款对比：\n| 项目 | 三明治遮光透气帘 | 双层复合功能帘 |\n| 价格 | ¥459 | ¥399 |\n| 遮光率 | 98% | 95% |\n| 透气性 | 微透气 | 自然透气 |\n| 适合 | 卧室 | 客厅/书房 |",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="product_detail",
                tool_args={"product_id": "p020"},
                tool_result_data={"id": "p020", "name": "三明治遮光透气帘", "price": 459, "specifications": {"遮光率": "98%", "透气性": "微透气"}},
            ),
            checks=[
                {"fn": lambda s, r, e: "459" in r.content and "399" in r.content, "desc": "对比两款商品价格"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="客户是卧室用的，需要遮光好一点",
            expected_graph_result=make_graph_result(
                final_answer="卧室使用推荐「三明治遮光透气帘」(¥459)：\n- 遮光率98%，满足卧室暗光需求\n- 微透气设计不会闷热\n- 是我们这个价位遮光+透气的最优选择",
                skill_used="product", intent="product_inquiry", confidence=0.88,
            ),
            checks=[
                {"fn": lambda s, r, e: "三明治遮光透气帘" in r.content or "459" in r.content, "desc": "根据场景推荐合适商品"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="好的，这款怎么保养",
            expected_graph_result=make_graph_result(
                final_answer="三明治结构窗帘保养：\n1. 不可机洗，建议局部擦拭或干洗\n2. 每月用吸尘器轻吸除尘\n3. 避免高温熨烫\n4. 收纳时平放或卷起",
                skill_used="knowledge", intent="knowledge_faq", confidence=0.88,
                tool_name="knowledge_search",
                tool_args={"query": "三明治结构窗帘保养方法"},
                tool_result_data={"chunks": [{"content": "三明治结构窗帘保养方法"}]},
            ),
            checks=[
                {"fn": lambda s, r, e: "knowledge" in e.get("skill_used", ""), "desc": "保养问题回到knowledge"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 16 存在失败检查点\n{report}"

    # ---------- Case 17: 促销活动商品管理全流程 ----------

    async def test_case_17_promotion_product_management(self):
        """
        Case 17: 促销活动商品管理全流程（5轮）
        验证重点：查询→调价→库存确认→上架
        涉及Skill: product | Tools: product_search, product_manage, inventory_manage
        """
        runner = MultiTurnRunner(17, "促销活动商品管理全流程")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="帮我查所有遮光帘类目的商品",
            expected_graph_result=make_graph_result(
                final_answer="遮光帘类目共5款商品：\n1. 雪尼尔遮光帘 ¥299 (p001)\n2. 北欧简约遮光帘 ¥199 (p002)\n3. 丝绒遮光帘 ¥369 (p003)\n4. 涂银全遮光帘 ¥159 (p004)\n5. 三明治遮光透气帘 ¥459 (p020)",
                skill_used="product", intent="product_inquiry", confidence=0.90,
                tool_name="product_search",
                tool_args={"category_id": "cat_blackout"},
                tool_result_data={"products": [
                    {"id": "p001", "name": "雪尼尔遮光帘", "price": 299},
                    {"id": "p002", "name": "北欧简约遮光帘", "price": 199},
                    {"id": "p003", "name": "丝绒遮光帘", "price": 369},
                    {"id": "p004", "name": "涂银全遮光帘", "price": 159},
                    {"id": "p020", "name": "三明治遮光透气帘", "price": 459},
                ]},
            ),
            checks=[
                {"fn": lambda s, r, e: "5" in r.content or "遮光帘" in r.content, "desc": "查询到遮光帘类目商品"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="做活动，前3个打8折",
            expected_graph_result=make_graph_result(
                final_answer="已调整促销价格（8折）：\n- 雪尼尔遮光帘: ¥299→¥239\n- 北欧简约遮光帘: ¥199→¥159\n- 丝绒遮光帘: ¥369→¥295",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="product_manage",
                tool_args={"action": "batch_update_price", "items": [
                    {"product_id": "p001", "price": 239},
                    {"product_id": "p002", "price": 159},
                    {"product_id": "p003", "price": 295},
                ]},
                tool_result_data={"updated": 3},
            ),
            checks=[
                {"fn": lambda s, r, e: "239" in r.content or "8折" in r.content, "desc": "批量调价成功"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="这三个的库存够不够，活动至少要100件",
            expected_graph_result=make_graph_result(
                final_answer="库存检查：\n- 雪尼尔遮光帘(p001): 105件 ✓\n- 北欧简约遮光帘(p002): 88件 ⚠️ 不足100\n- 丝绒遮光帘(p003): 200件 ✓\n建议为北欧简约遮光帘补货。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="inventory_manage",
                tool_args={"action": "query_batch", "product_ids": ["p001", "p002", "p003"]},
                tool_result_data={"results": [
                    {"product_id": "p001", "stock": 105},
                    {"product_id": "p002", "stock": 88},
                    {"product_id": "p003", "stock": 200},
                ]},
            ),
            checks=[
                {"fn": lambda s, r, e: "88" in r.content or "不足" in r.content, "desc": "检测到库存不足的商品"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="北欧简约遮光帘补到150件",
            expected_graph_result=make_graph_result(
                final_answer="已为北欧简约遮光帘(p002)补货，库存: 88→150件(+62)。现在三款活动商品库存均充足。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="inventory_manage",
                tool_args={"action": "adjust", "product_id": "p002", "quantity": 62},
                tool_result_data={"product_id": "p002", "new_stock": 150},
            ),
            checks=[
                {"fn": lambda s, r, e: "150" in r.content, "desc": "补货到目标数量"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="好，活动商品确认上架",
            expected_graph_result=make_graph_result(
                final_answer="活动商品已确认上架：\n✅ 雪尼尔遮光帘 ¥239 库存105\n✅ 北欧简约遮光帘 ¥159 库存150\n✅ 丝绒遮光帘 ¥295 库存200\n促销活动准备就绪！",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_manage",
                tool_args={"action": "batch_toggle_status", "product_ids": ["p001", "p002", "p003"], "status": "on_sale"},
                tool_result_data={"updated": 3},
            ),
            checks=[
                {"fn": lambda s, r, e: "上架" in r.content and "就绪" in r.content, "desc": "活动商品上架确认"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 17 存在失败检查点\n{report}"

    # ---------- Case 18: 客户全景画像构建 ----------

    async def test_case_22_product_inconsistency_detection(self):
        """
        Case 22: 商品信息矛盾检测与修正（5轮）
        验证重点：异常数据检测、修正操作、验证结果
        涉及Skill: product | Tools: product_detail, product_manage, inventory_manage
        """
        runner = MultiTurnRunner(22, "商品信息矛盾检测与修正")
        mock_graph = AsyncMock()
        runner.setup_agent(mock_graph)

        await runner.run_turn(
            turn_num=1,
            user_message="帮我看看商品p005的信息",
            expected_graph_result=make_graph_result(
                final_answer="商品p005信息：\n- 名称: 亚麻混纺帘\n- 价格: ¥0.01 ⚠️\n- 状态: 在售\n- 库存: 200件\n注意：价格¥0.01可能是录入错误，建议核实。",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_detail",
                tool_args={"product_id": "p005"},
                tool_result_data={"id": "p005", "name": "亚麻混纺帘", "price": 0.01, "status": "on_sale", "stock": 200},
            ),
            checks=[
                {"fn": lambda s, r, e: "0.01" in r.content or "异常" in r.content or "⚠" in r.content, "desc": "检测到价格异常"},
            ],
        )

        await runner.run_turn(
            turn_num=2,
            user_message="再查一下库存详情",
            expected_graph_result=make_graph_result(
                final_answer="商品p005库存详情：\n- 系统库存: -15件 ⚠️\n- 这是负数！说明存在超卖或数据异常。\n当前商品价格和库存均存在问题，建议暂停销售并修正。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="inventory_manage",
                tool_args={"action": "query", "product_id": "p005"},
                tool_result_data={"product_id": "p005", "stock": -15},
            ),
            checks=[
                {"fn": lambda s, r, e: "-15" in r.content or "负数" in r.content, "desc": "检测到库存负数异常"},
            ],
        )

        await runner.run_turn(
            turn_num=3,
            user_message="先下架，然后把价格改成269",
            expected_graph_result=make_graph_result(
                final_answer="已处理：\n1. 商品「亚麻混纺帘」(p005) 已下架\n2. 价格已修正: ¥0.01→¥269",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_manage",
                tool_args={"action": "update", "product_id": "p005", "status": "off_sale", "price": 269},
                tool_result_data={"id": "p005", "status": "off_sale", "price": 269},
            ),
            checks=[
                {"fn": lambda s, r, e: "下架" in r.content and "269" in r.content, "desc": "下架+修正价格"},
            ],
        )

        await runner.run_turn(
            turn_num=4,
            user_message="库存也归零重新盘点",
            expected_graph_result=make_graph_result(
                final_answer="已将商品p005库存重置为0。请完成实际盘点后再设置正确库存数量。",
                skill_used="product", intent="product_inquiry", confidence=0.85,
                tool_name="inventory_manage",
                tool_args={"action": "set", "product_id": "p005", "quantity": 0},
                tool_result_data={"product_id": "p005", "new_stock": 0},
            ),
            checks=[
                {"fn": lambda s, r, e: "0" in r.content or "归零" in r.content, "desc": "库存重置成功"},
            ],
        )

        await runner.run_turn(
            turn_num=5,
            user_message="确认一下现在的状态",
            expected_graph_result=make_graph_result(
                final_answer="商品p005当前状态确认：\n- 名称: 亚麻混纺帘\n- 价格: ¥269 ✓ (已修正)\n- 库存: 0件 ✓ (待盘点)\n- 状态: 已下架 ✓\n所有异常已修正，待盘点后可重新上架。",
                skill_used="product", intent="product_inquiry", confidence=0.88,
                tool_name="product_detail",
                tool_args={"product_id": "p005"},
                tool_result_data={"id": "p005", "name": "亚麻混纺帘", "price": 269, "status": "off_sale", "stock": 0},
            ),
            checks=[
                {"fn": lambda s, r, e: "269" in r.content and "下架" in r.content, "desc": "验证修正后状态正确"},
            ],
        )

        report = runner.report()
        logger.info(report)
        print(report)
        assert runner.all_passed, f"Case 22 存在失败检查点\n{report}"

    # ---------- Case 23: 物流异常分级处理 ----------

