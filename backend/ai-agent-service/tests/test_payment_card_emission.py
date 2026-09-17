# case_ids: ST-011, ST-012
"""收款二维码卡的**发射点**：C 端工具 → `_detect_card_type` → 卡载荷（issue #4085 第 1 项）。

## 缺陷形态（本文件守卫的那条链）

`PaymentCard` 组件与 `GET /chat/payment-qrcodes` 早在 #3990 就交付在 main，但**没有任何发射点**：
#4016 P14 按「工具层无数据源」裁掉了 C 端 `MessageBubble` 的 `case 'payment'`（同时把
`payment` 从「后端可产出集合」的反向契约里剔除）。生产表现 = 顾客在对话里永远拿不到收款码，
而**没有任何东西会红** —— 这是 `production_progress` 的同构形态（用户 2026-09-18 对两者
下的裁定相同：**建触发机制 / 补发射点**）。

本文件把整条链的每一跳都钉成确定性断言（零 LLM、零网络）：

    payment_qrcode_query（工具，C 端只读）
      → 工具 data = {"payment_qrcodes": {...}}        （卡载荷）
      → chat.py `_detect_card_type` → "payment"       （发射点）
      → `_card_payload` 原样下发                       （SSE card 事件）
      → mini-app `MessageBubble.renderCard` case 'payment' → PaymentCard

## 判据为什么必须落在「可达性」而不只是「映射存在」

`_detect_card_type` 里写了映射，不等于模型调得到该工具：模型可见工具集**唯一**来自
`create_skill_registry(SkillConfig.tool_names)`（`base_skill`，`get_langchain_tools` 绑给模型）。
故本文件额外断言 **Skill 注册表事实**：该工具在小布 persona 的 skill 工具集里（两个：
`customer_order` 下单/付款语境 + `customer_general` 兜底语境 —— 后者是低置信问法的落点），
且**不在**米宝 persona 的工具集里（C 端专属，`allowed_roles=["customer"]`）。

## 红证（每条断言都能红 —— 见本 PR 的实测输出）

- **去掉 `_detect_card_type` 的 payment 分支** ⇒ `TestEmissionChain` 全部红（映射/payload/放行）；
- **把工具从 skill 的 tool_names 摘掉** ⇒ `TestToolIsReachableByXiaobu` 红（能力不可达）；
- **把工具从注册表摘掉** ⇒ `test_registered_in_global_registry` 红（模型看不见 + 跨端守卫会判孤儿）。
"""
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.api.chat import _card_payload, _detect_card_type, _should_send_card
from app.graph.skills.skill_registry import get_skill_registry
from app.tools.base import ToolContext
from app.tools.payment_qrcode_query import PaymentQrcodeQueryTool
from app.tools.registry import get_tool_registry

# 冻结契约端点（admin-api AgentPaymentController，#3990；C 端同源端点 app/api/payments.py）
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


class TestToolMetadataContract:
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
        # 空态仍然要发卡（ST-011 明写空态提示由 PaymentCard 渲染）——放行判据见 TestEmissionChain
        assert _should_send_card("payment_qrcode_query",
                                 {"success": True, "data": result.data}) is True


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


class TestEmissionChain:
    """发射点：工具名 → 卡型 → 卡载荷 → 是否下发（全部对**真实函数**求值）"""

    def test_tool_maps_to_payment_card(self):
        assert _detect_card_type("payment_qrcode_query", {}) == "payment"

    def test_card_payload_is_the_tool_data(self):
        data = {"payment_qrcodes": {"wechat": {"payment_type": "wechat",
                                               "image_url": "https://img/w.png",
                                               "payee_name": "亿家纺织"}}}
        card_type, card_data = _card_payload(
            "payment_qrcode_query", {"success": True, "data": data}
        )
        assert card_type == "payment"
        # 载荷原样下发（非 order 类不做归一化）——前端 PaymentCard 直接读 payment_qrcodes
        assert card_data == data

    @pytest.mark.parametrize("result,expected", [
        ({"success": True, "data": {"payment_qrcodes": {}}}, True),      # 空态也要发卡
        ({"success": True, "data": {"payment_qrcodes": {"wechat": {}}}}, True),
        ({"success": True, "data": {}}, False),                          # 无载荷不发卡
        ({"success": False, "data": {"payment_qrcodes": {}}}, False),    # 失败不发卡
        ({"success": True}, False),
    ])
    def test_should_send_card_matrix(self, result, expected):
        assert _should_send_card("payment_qrcode_query", result) is expected

    def test_mapping_is_not_vacuous(self):
        """判别性：注册表里**只有一个**工具产出 payment 卡，且它就是这个工具。

        防「映射写成兜底默认」这类恒真形态（那样任何工具都会发支付卡）。
        """
        producers = sorted(
            name for name in get_tool_registry().get_tool_names()
            if _detect_card_type(name, {}) == "payment"
        )
        assert producers == ["payment_qrcode_query"], producers

    def test_card_payload_carries_no_extra_keys(self):
        """载荷只带 payment_qrcodes：前端 PaymentCard 的读键与后端下发键必须一致"""
        _, payload = _card_payload(
            "payment_qrcode_query",
            {"success": True, "data": {"payment_qrcodes": {"wechat": {"image_url": "u"}}}},
        )
        assert set(payload) == {"payment_qrcodes"}


class TestToolIsReachableByXiaobu:
    """可达性（**能力真的可达**的判据）——与跨端卡型契约守卫同源事实、各自独立断言。

    病根形态：工具写好了却没进任何 skill 的 tool_names ⇒注册表里有、模型永远调不到
    （`create_skill_registry` 是唯一的模型可见工具集工厂）。
    """

    def test_registered_in_global_registry(self):
        assert "payment_qrcode_query" in get_tool_registry().get_tool_names()

    def test_skill_registry_exposes_it_to_xiaobu(self):
        registry = get_skill_registry()
        skills = list(getattr(registry, "_skills", {}).values())
        assert skills, "Skill 注册表为空 —— 可达性断言会退化成空断言"

        xiaobu_skills = [s for s in skills if "xiaobu" in (s.system_prompts or {})]
        assert xiaobu_skills, "没有小布 persona 的 skill —— 判据的被测对象不存在"
        xiaobu_tools = {t for s in xiaobu_skills for t in (s.tool_names or [])}
        assert "payment_qrcode_query" in xiaobu_tools, (
            "小布的工具集里没有 payment_qrcode_query ⇒ 模型永远调不到该工具，"
            "收款码卡仍是零发射点（不允许「只注册不绑定」）"
        )

        # 兜底 skill 也必须绑（低置信/跨域问法是本能力最常见的落点）
        fallback = [s for s in xiaobu_skills if s.name == "customer_general"]
        assert fallback, "小布兜底 skill（customer_general）不在注册表里"
        assert "payment_qrcode_query" in (fallback[0].tool_names or []), (
            "兜底 skill 未绑定 ⇒「我想付款」这类不在订单域关键词里的问法拿不到收款码"
        )

    def test_not_exposed_to_mibao(self):
        """C 端专属：米宝 persona 的工具集里不得出现（商家设置走 SettingsController）"""
        skills = list(getattr(get_skill_registry(), "_skills", {}).values())
        mibao_tools = {
            t for s in skills if "mibao" in (s.system_prompts or {})
            for t in (s.tool_names or [])
        }
        assert "payment_qrcode_query" not in mibao_tools

    def test_tool_is_callable_through_a_skill_registry_subset(self):
        """端到端可达性：按 skill 工具集造出的子注册表里能取到该工具实例"""
        from app.graph.skills.base_skill import create_skill_registry

        subset = create_skill_registry(["payment_qrcode_query"])
        assert subset.get_tool("payment_qrcode_query") is not None