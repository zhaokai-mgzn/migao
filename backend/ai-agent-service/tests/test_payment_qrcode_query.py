# case_ids: ST-011, ST-012
"""`PaymentQrcodeQueryTool` 单测 —— C 端收款二维码查询（issue #4085 第 1 项 / #3990 M3-F-3）。

契约（复用既有数据源，不新造）：
    GET /api/admin/agent/payment-qrcodes
    → {"success": true, "data": {"wechat": {"paymentType", "imageUrl", "payeeName"}, "alipay": {...}}}
C 端同源端点 = `app/api/payments.py` 的 `GET /chat/payment-qrcodes`（snake_case 精简字段）。

零真实网络：`get_admin_api_client` 全部 mock。

本文件管**工具自身**（元数据 / 成功面 / 失败面 / suggestion 不变式）；
「工具 → 卡型 → 卡载荷 → 渲染」的发射链与可达性由
`tests/test_payment_card_emission.py` 覆盖（同一裁定、两处职责，避免把链路判据塞进工具单测）。
"""
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.base import ToolContext
from app.tools.payment_qrcode_query import PaymentQrcodeQueryTool

# 冻结契约端点（admin-api AgentPaymentController，#3990）
PAYMENT_PATH = "/api/admin/agent/payment-qrcodes"

_REPO_ROOT = Path(__file__).resolve().parents[3]

# 冻结契约样例：admin-api 返回 camelCase（imageUrl/payeeName），C 端只透出精简字段
ADMIN_DATA = {
    "wechat": {"paymentType": "wechat", "imageUrl": "https://img.migao.test/w.png",
               "payeeName": "亿家纺织"},
    "alipay": {"paymentType": "alipay", "imageUrl": "https://img.migao.test/a.png",
               "payeeName": "亿家纺织"},
}


@pytest.fixture
def tool():
    return PaymentQrcodeQueryTool()


@pytest.fixture
def customer_context():
    """C 端顾客（小布）上下文"""
    return ToolContext(tenant_id=1, user_id="customer_001", session_id="sess_pay_1",
                       role="customer")


class TestMetadataContract:
    """工具元数据：LLM 只读 description 选工具 ⇒ 触发/前置/反例/标注必须自带"""

    def test_read_only_and_customer_only(self, tool):
        assert tool.name == "payment_qrcode_query"
        assert tool.read_only is True
        assert tool.destructive is False
        assert tool.idempotent is True
        # C 端专属：商家设置端走 SettingsController（不经 Agent），故只对顾客开放
        assert tool.allowed_roles == ["customer"]

    def test_description_carries_trigger_counterexample_and_readonly(self, tool):
        desc = tool.description
        assert "【触发】" in desc and "付款" in desc
        assert "【反例】" in desc and "customer_order_query" in desc
        assert "READONLY" in desc
        # 反编造口径必须在描述里（收款码是"付给谁"的钱路，编造后果最重）
        assert "禁止编造" in desc

    def test_no_required_params(self, tool):
        """无入参：收款码按当前租户取（顾客无法、也不该指定别的商家）"""
        assert tool.parameters["properties"] == {}
        assert tool.parameters["required"] == []


class TestExecuteSuccess:
    """成功路径：调用冻结契约端点 + 输出即卡载荷"""

    @patch("app.tools.payment_qrcode_query.get_admin_api_client")
    async def test_fetches_frozen_endpoint_and_shapes_card_payload(
        self, mock_get_client, tool, customer_context
    ):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": dict(ADMIN_DATA)})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=customer_context)

        assert result.success is True
        # 端点用**字面量**（跨模块 payload 契约门禁要求可静态归属）+ 租户/用户上下文透传
        args, kwargs = mock_client.get.call_args
        assert args[0] == PAYMENT_PATH
        assert kwargs["tenant_id"] == 1
        assert kwargs["user_id"] == "customer_001"

        # data **就是**卡载荷：PaymentCard 读 payment_qrcodes（camelCase → 精简字段归一）
        assert set(result.data) == {"payment_qrcodes"}
        qrcodes = result.data["payment_qrcodes"]
        assert set(qrcodes) == {"wechat", "alipay"}
        assert qrcodes["wechat"] == {
            "payment_type": "wechat",
            "image_url": "https://img.migao.test/w.png",
            "payee_name": "亿家纺织",
        }
        assert qrcodes["alipay"]["payee_name"] == "亿家纺织"
        assert "微信" in result.summary and "亿家纺织" in result.summary

    @patch("app.tools.payment_qrcode_query.get_admin_api_client")
    async def test_snake_case_fields_also_accepted(
        self, mock_get_client, tool, customer_context
    ):
        """C 端同源端点（app/api/payments.py）下发的是 snake_case ⇒ 两种形态都要认"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"wechat": {"image_url": "https://img.migao.test/w.png",
                                "payee_name": "亿家纺织"}},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=customer_context)

        assert result.success is True
        assert result.data["payment_qrcodes"]["wechat"]["image_url"] == "https://img.migao.test/w.png"

    @patch("app.tools.payment_qrcode_query.get_admin_api_client")
    async def test_entry_without_image_is_skipped(
        self, mock_get_client, tool, customer_context
    ):
        """无图不成码：缺 image_url 的配置项跳过（否则前端渲染空白方块）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"wechat": {"payeeName": "亿家纺织"},  # 无 imageUrl
                     "alipay": {"imageUrl": "https://img.migao.test/a.png"}},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=customer_context)

        assert result.success is True
        assert set(result.data["payment_qrcodes"]) == {"alipay"}

    @patch("app.tools.payment_qrcode_query.get_admin_api_client")
    async def test_no_qrcode_configured_is_a_valid_answer_not_a_failure(
        self, mock_get_client, tool, customer_context
    ):
        """商家未配收款码 ⇒ success=true + 空 payment_qrcodes（空态卡，不是失败）。

        真值：评测栈种子（tests/agent_eval/fixtures/*.sql、docs/deployment/demo-seed.sql）
        里 `tenant_payment_qrcodes` **零行** ⇒ 这正是评测环境下的真实形态，
        故 ST-012 只断言「调用 + 载荷形状」，不断言非空内容（否则造恒红）。
        """
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=customer_context)

        assert result.success is True
        assert result.data == {"payment_qrcodes": {}}
        assert "暂未设置收款码" in result.message


class TestExecuteFailure:
    """失败面：一律 success=False + **非空 suggestion**（自愈闸门依赖它，issue #4050）"""

    async def test_non_customer_role_denied(self, tool):
        ctx = ToolContext(tenant_id=1, user_id="agent_001", session_id="s", role="agent")
        result = await tool.execute(context=ctx)

        assert result.success is False
        assert result.error == "权限不足"
        assert result.suggestion and "禁止编造" in result.suggestion

    @patch("app.tools.payment_qrcode_query.get_admin_api_client")
    async def test_transport_exception_is_reported_with_suggestion(
        self, mock_get_client, tool, customer_context
    ):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("connection refused"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=customer_context)

        assert result.success is False
        assert result.error == "tool_execution_failed"
        assert result.suggestion and "禁止编造" in result.suggestion

    @patch("app.tools.payment_qrcode_query.get_admin_api_client")
    async def test_admin_api_rejection_is_reported_with_suggestion(
        self, mock_get_client, tool, customer_context
    ):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False, "error": {"message": "无权访问"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=customer_context)

        assert result.success is False
        assert result.error == "无权访问"
        assert result.suggestion and result.suggestion.strip()


def _failure_sites_have_suggestion() -> list[int]:
    """源码层：本工具每个 `ToolResult(success=False, …)` 字面量都必须带 suggestion。

    与 `tests/test_tool_failure_suggestions.py` 同口径（那里是全仓 L0），此处钉本文件
    的红证可读性：本工具自身不留缺口，无需靠基线豁免。
    """
    src = (_REPO_ROOT / "backend" / "ai-agent-service" / "app" / "tools"
           / "payment_qrcode_query.py").read_text(encoding="utf-8")
    return [
        m.start() for m in re.finditer(r"ToolResult\(\s*success=False", src)
        if "suggestion=" not in src[m.start():m.start() + 600]
    ]


class TestToolSourceInvariants:
    def test_every_failure_site_declares_a_suggestion(self):
        offenders = _failure_sites_have_suggestion()
        assert offenders == [], f"这些失败面缺 suggestion（LLM 无从引导用户）：{offenders}"

    def test_suggestion_detector_is_not_vacuous(self):
        """判据自证：把 suggestion 抠掉必须报出来（防「永远绿的空判据」）"""
        planted = 'ToolResult(\n            success=False,\n            error="x",\n            message="y",\n        )'
        m = re.search(r"ToolResult\(\s*success=False", planted)
        assert m and "suggestion=" not in planted[m.start():m.start() + 600]