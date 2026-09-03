"""
测试 app.tools.human_handoff — 转人工工具

业务真值 #3: 客户说转人工→自动创建工单并通知管理员
GB-01（GB/T 47746-2026）: 转人工创建人工会话时携带 AI 对话上下文快照
"""
# case_ids: CH-008, CH-017
import pytest
from unittest.mock import patch, AsyncMock


@pytest.fixture(autouse=True)
def _no_db_history():
    """单元测试默认不访问真实 DB：SessionMemory.get_history 打桩返回空。

    需要断言上下文快照的用例在测试内再覆盖该桩。
    """
    with patch(
        "app.memory.session_memory.SessionMemory.get_history",
        new=AsyncMock(return_value=[]),
    ):
        yield


class TestHumanHandoffPermission:
    """权限校验 — 只有customer角色可以使用"""

    async def test_customer_role_allowed(self, sample_tool_context):
        """customer角色可以调用转人工"""
        from app.tools.human_handoff import HumanHandoffTool
        tool = HumanHandoffTool()
        assert tool.check_permission(sample_tool_context) is True

    async def test_admin_role_denied(self, admin_tool_context):
        """admin角色不应使用转人工（只给C端用户）"""
        from app.tools.human_handoff import HumanHandoffTool
        tool = HumanHandoffTool()
        assert tool.check_permission(admin_tool_context) is False

    async def test_guest_role_denied(self, unauthorized_tool_context):
        """guest角色不能使用转人工"""
        from app.tools.human_handoff import HumanHandoffTool
        tool = HumanHandoffTool()
        assert tool.check_permission(unauthorized_tool_context) is False


class TestHumanHandoffSuccess:
    """成功创建转人工工单"""

    @patch("app.tools.human_handoff.get_admin_api_client")
    async def test_xiaobu_handoff_creates_ticket(self, mock_get_client, sample_tool_context):
        """客户说转人工→自动创建投诉工单+通知管理员"""
        from app.tools.human_handoff import HumanHandoffTool

        mock_client = AsyncMock()
        # #518: 现在有2次 post 调用 — ① 创建工单 ② 通知管理员
        mock_client.post = AsyncMock(side_effect=[
            # 第1次: 创建工单
            {
                "success": True,
                "data": {
                    "id": "ticket-handoff-001",
                    "ticketNo": "AS-2024-H001",
                    "ticketType": "complaint",
                    "status": "pending",
                    "reason": "客户请求转人工",
                    "source": "customer",
                },
            },
            # 第2次: 通知管理员
            {"success": True, "data": {"id": "notif-001"}},
        ])
        mock_get_client.return_value = mock_client

        tool = HumanHandoffTool()
        result = await tool.execute(
            context=sample_tool_context,
            reason="我要投诉产品质量问题",
            description="窗帘收到后有色差，要求退货",
        )

        assert result.success is True
        assert "ticket-handoff-001" in str(result.data)

        # 验证至少调用了2次 post（创建工单+通知管理员）
        assert mock_client.post.call_count >= 2, (
            f"应至少调用2次post: {mock_client.post.call_count}"
        )

        # 验证第1次调用创建的是投诉工单
        first_call = mock_client.post.call_args_list[0]
        json_data = first_call[1]["json_data"]
        assert json_data["ticketType"] == "complaint"

    @patch("app.tools.human_handoff.get_admin_api_client")
    async def test_handoff_default_reason_when_empty(self, mock_get_client, sample_tool_context):
        """reason为空时使用默认值"""
        from app.tools.human_handoff import HumanHandoffTool

        mock_client = AsyncMock()
        # #518: 2次 post — ① 创建工单 ② 通知管理员
        mock_client.post = AsyncMock(side_effect=[
            {"success": True, "data": {"id": "ticket-h-002", "ticketType": "complaint"}},
            {"success": True, "data": {"id": "notif-002"}},
        ])
        mock_get_client.return_value = mock_client

        tool = HumanHandoffTool()
        result = await tool.execute(
            context=sample_tool_context,
        )

        assert result.success is True
        first_call = mock_client.post.call_args_list[0]
        json_data = first_call[1]["json_data"]
        assert "转人工" in json_data["reason"]


class TestHumanHandoffFailure:
    """转人工失败处理"""

    @patch("app.tools.human_handoff.get_admin_api_client")
    async def test_handoff_returns_suggestion_on_error(self, mock_get_client, sample_tool_context):
        """失败时返回suggestion字段引导用户"""
        from app.tools.human_handoff import HumanHandoffTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": False,
            "error": {"message": "创建工单失败"},
        })
        mock_get_client.return_value = mock_client

        tool = HumanHandoffTool()
        result = await tool.execute(
            context=sample_tool_context,
            reason="需要人工帮助",
        )

        assert result.success is False
        assert result.suggestion is not None
        assert len(result.suggestion) > 0

    @patch("app.tools.human_handoff.get_admin_api_client")
    async def test_handoff_network_error_graceful(self, mock_get_client, sample_tool_context):
        """网络异常时优雅降级"""
        from app.tools.human_handoff import HumanHandoffTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
        mock_get_client.return_value = mock_client

        tool = HumanHandoffTool()
        result = await tool.execute(
            context=sample_tool_context,
            reason="请帮我转人工",
        )

        assert result.success is False
        assert result.suggestion is not None


# ============================================================
# GAP-3: 转人工 → 必须通知管理员
# 业务真值: 转人工创建工单后通知管理员（推送/钉钉/系统消息任一种）
# 当前状态: FAIL — 只创建工单，未通知管理员
# ============================================================

class TestHumanHandoffAdminNotification:
    """Gap-3: 转人工后必须通知管理员"""

    @patch("app.tools.human_handoff.get_admin_api_client")
    async def test_handoff_notifies_admin_after_ticket_creation(self, mock_get_client, sample_tool_context):
        """转人工创建工单后 → 必须调用通知管理员"""
        from app.tools.human_handoff import HumanHandoffTool

        mock_client = AsyncMock()
        # 创建工单成功
        mock_client.post = AsyncMock(side_effect=[
            # 第一个 post: 创建售后工单
            {"success": True, "data": {"id": "ticket-h-001", "ticketNo": "AS-H-001", "ticketType": "complaint"}},
            # 第二个 post: 通知管理员（如果使用 notification 接口）
            {"success": True, "data": {"id": "notif-001"}},
        ])
        mock_get_client.return_value = mock_client

        tool = HumanHandoffTool()
        result = await tool.execute(
            context=sample_tool_context,
            reason="产品质量问题",
            description="窗帘收到后有色差",
        )

        assert result.success is True, f"工单创建应成功: {result.error}"

        # 验证至少调用了两次（创建工单 + 通知管理员）
        assert mock_client.post.call_count >= 2, (
            f"应至少调用2次: 创建工单 + 通知管理员，实际调用{len(mock_client.post.call_args_list)}次"
        )

        # 验证第二次调用是通知内容
        # 检查至少有一个post调用包含通知内容
        found_notification = False
        for call_args in mock_client.post.call_args_list:
            json_data = call_args[1].get("json_data", {})
            # 通知调用：检查是否包含 recipient_role 或 channel 或 title 等通知字段
            if "notification" in str(call_args[0][0]).lower() or json_data.get("recipientRole") or json_data.get("channel"):
                found_notification = True
                break
        assert found_notification, (
            f"必须包含通知管理员调用: {mock_client.post.call_args_list}"
        )

    @patch("app.tools.human_handoff.get_admin_api_client")
    async def test_handoff_succeeds_even_if_notification_fails(self, mock_get_client, sample_tool_context):
        """通知管理员失败不影响转人工成功（工单已创建）"""
        from app.tools.human_handoff import HumanHandoffTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[
            # 工单创建成功
            {"success": True, "data": {"id": "ticket-h-002", "ticketNo": "AS-H-002"}},
            # 通知失败（如管理员不存在）
            Exception("Notification service unavailable"),
        ])
        mock_get_client.return_value = mock_client

        tool = HumanHandoffTool()
        result = await tool.execute(
            context=sample_tool_context,
            reason="需要人工帮助",
        )

        # 工单创建成功了，转人工应该算成功
        assert result.success is True, (
            f"工单已创建，通知失败不应影响转人工结果: error={result.error}"
        )


# ============================================================
# GB-01 (GB/T 47746-2026, issue #2776): 转人工携带 AI 对话上下文快照
# 业务真值: human_handoff 创建人工会话时，POST 载荷携带 aiContextSummary /
#           aiContextMessages（最近 N 轮 user/assistant 文本；剥 think、空内容过滤、图片占位）
# ============================================================

class TestHumanHandoffAiContext:
    """转人工 → AI 上下文同步（人工客服可见，避免顾客复述）"""

    _SAMPLE_HISTORY = [
        {"id": "m1", "session_id": "sess_test_001", "role": "user",
         "content_type": "text", "content": "我的窗帘订单到哪了？",
         "tool_calls": None, "metadata": {}, "created_at": "2026-09-01T10:00:00Z"},
        {"id": "m2", "session_id": "sess_test_001", "role": "assistant",
         "content_type": "text", "content": "正在为您查询，<think>内部推理</think>请稍候。",
         "tool_calls": None, "metadata": {}, "created_at": "2026-09-01T10:00:01Z"},
        {"id": "m3", "session_id": "sess_test_001", "role": "system",
         "content_type": "text", "content": "系统消息不应入快照",
         "tool_calls": None, "metadata": {}, "created_at": "2026-09-01T10:00:02Z"},
        {"id": "m4", "session_id": "sess_test_001", "role": "user",
         "content_type": "image", "content": "",
         "tool_calls": None, "metadata": {}, "created_at": "2026-09-01T10:00:03Z"},
    ]

    @patch("app.tools.human_handoff.get_admin_api_client")
    async def test_handoff_posts_ai_context_snapshot(self, mock_get_client, sample_tool_context):
        """创建人工会话的 POST 应携带清洗后的 AI 对话快照"""
        from app.tools.human_handoff import HumanHandoffTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[
            {"success": True, "data": {"id": "t-ctx-1", "ticketNo": "AS-C-1", "ticketType": "complaint"}},
            {"success": True, "data": {"id": "n-ctx-1"}},
            {"success": True, "data": {"id": "as-ctx-1"}},
        ])
        mock_get_client.return_value = mock_client

        tool = HumanHandoffTool()
        with patch(
            "app.memory.session_memory.SessionMemory.get_history",
            new=AsyncMock(return_value=self._SAMPLE_HISTORY),
        ) as mock_get_history:
            result = await tool.execute(context=sample_tool_context, reason="我要投诉")

        assert result.success is True, f"转人工应成功: {result.error}"
        assert mock_client.post.call_count == 3, (
            f"应 3 次 post（工单+通知+人工会话）: {mock_client.post.call_count}"
        )

        session_call = mock_client.post.call_args_list[2]
        assert "agent-sessions" in str(session_call[0][0])
        json_data = session_call[1]["json_data"]
        assert json_data["aiSessionId"] == "sess_test_001"
        assert json_data["aiContextSummary"] == ""

        turns = json_data["aiContextMessages"]
        assert isinstance(turns, list)
        # user 消息保留原文
        user_turn = turns[0]
        assert user_turn["role"] == "user"
        assert user_turn["content"] == "我的窗帘订单到哪了？"
        # assistant <think> 已剥离
        assistant_turn = turns[1]
        assert assistant_turn["role"] == "assistant"
        assert "内部推理" not in assistant_turn["content"]
        assert "<think>" not in assistant_turn["content"]
        # system 消息被过滤
        roles = [t["role"] for t in turns]
        assert "system" not in roles
        # 图片消息占位（不透传 URL）
        image_turn = next((t for t in turns if t.get("contentType") == "image"), None)
        assert image_turn is not None
        assert image_turn["content"] == "[图片]"
        # 历史读取确实发生
        assert mock_get_history.await_count == 1

    @patch("app.tools.human_handoff.get_admin_api_client")
    async def test_handoff_passes_llm_summary(self, mock_get_client, sample_tool_context):
        """LLM 提供的 summary 参数应透传到 aiContextSummary"""
        from app.tools.human_handoff import HumanHandoffTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[
            {"success": True, "data": {"id": "t-ctx-2", "ticketNo": "AS-C-2"}},
            {"success": True, "data": {"id": "n-ctx-2"}},
            {"success": True, "data": {"id": "as-ctx-2"}},
        ])
        mock_get_client.return_value = mock_client

        tool = HumanHandoffTool()
        with patch(
            "app.memory.session_memory.SessionMemory.get_history",
            new=AsyncMock(return_value=[]),
        ):
            result = await tool.execute(
                context=sample_tool_context,
                reason="窗帘色差",
                summary="顾客反馈窗帘遮光率与描述不符，已咨询三次仍不满意，要求人工处理",
            )

        assert result.success is True
        json_data = mock_client.post.call_args_list[2][1]["json_data"]
        assert "人工处理" in json_data["aiContextSummary"]
        assert json_data["aiContextMessages"] == []

    @patch("app.tools.human_handoff.get_admin_api_client")
    async def test_handoff_succeeds_when_history_fetch_fails(self, mock_get_client, sample_tool_context):
        """AI 历史读取异常时转人工仍成功（快照降级为空，不影响主流程）"""
        from app.tools.human_handoff import HumanHandoffTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[
            {"success": True, "data": {"id": "t-ctx-3", "ticketNo": "AS-C-3"}},
            {"success": True, "data": {"id": "n-ctx-3"}},
            {"success": True, "data": {"id": "as-ctx-3"}},
        ])
        mock_get_client.return_value = mock_client

        tool = HumanHandoffTool()
        with patch(
            "app.memory.session_memory.SessionMemory.get_history",
            new=AsyncMock(side_effect=Exception("db down")),
        ):
            result = await tool.execute(context=sample_tool_context, reason="需要人工")

        assert result.success is True, f"历史读取失败不应阻塞转人工: {result.error}"
        json_data = mock_client.post.call_args_list[2][1]["json_data"]
        assert json_data["aiContextSummary"] == ""
        assert json_data["aiContextMessages"] == []
