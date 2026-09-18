# case_ids: PR-008
"""商品↔加工项**解耦**回归锁（issue #4371，用户裁定 2026-09-19，零 LLM）。

用户裁定原文：「我们的产品和加工项现在是有绑定关系的，但是从实际业务来看，这两者
现在需要解耦掉，用户选择完商品以及安装方式后，加工工序已经固定了，额外的加工项可以
单独从加工项中选择，不需要通过商品来关联上加工项进行过滤一道，这个点得现在重构掉。」

领域真值（issue #4365 冻结）：工序主线固定（`app/production/routing.py` 的
`ROUTINGS[(部位,工艺)]`），**加工项是触发器/配件**（「选了不同加工项 ⇒ 表现为不同生产工艺」）
⇒ Agent 必须停止问「这个商品有哪些加工项？」，改为把**店铺级加工项目录**独立摆给用户。

为什么单独立一个文件（而不是散在既有用例里）：解耦是**跨模块删除性变更**，
「删干净了」这件事没有天然的红灯 —— 残留一个 schema 参数 / 一句 prompt 铁律，
模型就会继续走后端已不认的老路（下发 DTO 没有的键 = Jackson 静默丢弃 + 工具报成功）。
本文件把 6 条解耦事实钉成**可判红**的断言，任何一条被回退即红。

用例锚点 = `PR-008`（「创建商品 - 完整流程」，product.yml）：它的建品引导链
（分类确认 → 货号 → 汇总确认卡 → create）正是解耦后**唯一**的建品形态 ——
用例自己的 merge_log（2026-09-19）已写明「建品流程已不再下发加工项多选卡」，
故本文件的断言与该用例的被测契约同向。
"""

import inspect
import re
from pathlib import Path

from app.tools.processing_item_query import ProcessingItemQueryTool
from app.tools.product_detail import ProductDetailTool
from app.tools.product_manage import ProductManageTool
from app.tools.registry import get_tool_registry

# 仓库根：tests/ → backend/ai-agent-service/ → backend/ → <repo root>
REPO_ROOT = Path(__file__).resolve().parents[3]
_AGENT_CREATE_DTO = (REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java"
                     / "com" / "migao" / "admin" / "dto" / "agent"
                     / "AgentProductCreateRequest.java")

# 解耦前的绑定面（产品建品参数 + 商品详情字段 + 店铺目录过滤参数）
_PRODUCT_CREATE_PARAMS = ("processing_item_ids", "processing_item_configs")
_PRODUCT_CREATE_PAYLOAD_KEYS = ("processingItemIds", "processingItemConfigs")


def _product_detail_payload() -> dict:
    """用真实 admin-api 形状的响应跑一次 `_format_product`（不调网络）。"""
    return ProductDetailTool()._format_product({
        "id": "prod_001",
        "name": "高遮光雪尼尔窗帘",
        "basePrice": 299.0,
        "skus": [],
    })


# ── ① Python 侧 schema：product_manage(create) 不再有加工项参数 ──

def test_product_manage_schema_has_no_processing_item_params():
    """红证：`processing_item_ids` / `processing_item_configs` 不得再出现在 schema 或签名里。

    留着 = LLM 按 schema 传、后端 DTO 不认 ⇒ 静默丢数据 + 工具报成功（工具审计 A4 同型）。
    """
    props = ProductManageTool.parameters["properties"]
    leaked = [p for p in _PRODUCT_CREATE_PARAMS if p in props]
    assert leaked == [], f"product_manage schema 仍有加工项参数（解耦被回退）：{leaked}"

    sig = inspect.signature(ProductManageTool.execute)
    leaked_sig = [p for p in _PRODUCT_CREATE_PARAMS if p in sig.parameters]
    assert leaked_sig == [], (
        f"product_manage.execute 签名仍有加工项参数（schema 删了签名没删 = 两处漂移）：{leaked_sig}")


# ── ② 跨模块契约钉：Java DTO 侧也没有这两个字段 ──

def test_java_dto_declares_no_processing_item_fields():
    """红证（跨模块）：`AgentProductCreateRequest` 的**字段声明**里没有加工项。

    ⚠️ 只扫**字段声明行**（`private <Type> <name>;`），不扫全文 —— 该 DTO 的 Javadoc
    会**点名解释**「没有 processingItemIds / processingItemConfigs」（那是合规的说明文字），
    全文扫描会把正确文档误判成回退。字段声明的形态是唯一可判的真相。
    """
    assert _AGENT_CREATE_DTO.exists(), (
        f"找不到 Java DTO {_AGENT_CREATE_DTO} —— 跨模块契约钉无法判定（不是通过）")
    src = _AGENT_CREATE_DTO.read_text(encoding="utf-8")
    declared = set(re.findall(r"private\s+[\w<>,\s\[\]]+?\s+(\w+)\s*;", src))
    leaked = sorted(set(_PRODUCT_CREATE_PAYLOAD_KEYS) & declared)
    assert leaked == [], (
        f"Java DTO 仍有加工项字段声明（Java 侧解耦被回退）：{leaked}；"
        f"实测声明字段={sorted(declared)}")


def test_product_manage_create_payload_keys_are_backend_fields(admin_tool_context):
    """红证：create 的 payload 键不得含后端 DTO 没有的加工项键（双向钉死）。"""
    import asyncio
    from unittest.mock import AsyncMock, patch

    ctx = admin_tool_context
    captured: dict = {}

    client = AsyncMock()

    async def _post(path, json_data=None, **kwargs):
        captured["body"] = json_data
        return {"success": True, "data": {"id": "p-1"}}

    client.post = _post
    with patch("app.tools.product_manage.get_admin_api_client", return_value=client):
        result = asyncio.run(ProductManageTool().execute(
            context=ctx, action="create", name="测试窗帘A", price=168.0))

    assert result.success is True, result.message
    body = captured["body"]
    leaked = sorted(set(_PRODUCT_CREATE_PAYLOAD_KEYS) & set(body))
    assert leaked == [], f"create payload 仍下发加工项键（后端静默丢弃）：{leaked}"
    assert body["name"] == "测试窗帘A" and body["basePrice"] == 168.0, body


# ── ③ 工具注册表：商品加工项关联工具已退场 ──

def test_product_processing_item_manage_tool_is_gone():
    """红证：`product_processing_item_manage` 不在默认注册表，且实现文件已删除。"""
    registered = set(get_tool_registry().get_tool_names())
    assert "product_processing_item_manage" not in registered, (
        "商品加工项关联工具仍在注册表里 —— 模型会继续「给商品挂加工项」（商品已不再持有加工项）")
    tool_file = (Path(__file__).resolve().parent.parent
                 / "app" / "tools" / "product_processing_item_manage.py")
    assert not tool_file.exists(), f"实现文件未删除：{tool_file}"
    # 目录查询/目录 CRUD 仍在（解耦 ≠ 删能力）
    assert "processing_item_query" in registered
    assert "processing_item_manage" in registered


# ── ④ 商品详情输出不再有 processing_items ──

def test_product_detail_output_has_no_processing_items_key():
    """红证：`product_detail` 的格式化产物不得再有 `processing_items` 键。

    留着 = 模型照着旧 prompt 去读一个恒空的字段 ⇒ 断言「这款商品无加工项」（错判能力）。
    """
    payload = _product_detail_payload()
    assert "processing_items" not in payload, (
        "product_detail 仍返回 processing_items —— 商品与加工项仍被绑在一起")


# ── ⑤ 店铺目录：加工项查询不再有「适用商品分类」过滤 ──

def test_processing_item_query_schema_has_no_applicable_category_id():
    """红证：`applicable_category_id` 不得再出现在 schema（admin-api 查询参数已删除）。"""
    props = ProcessingItemQueryTool.parameters["properties"]
    assert "applicable_category_id" not in props, (
        "processing_item_query schema 仍有 applicable_category_id —— "
        "加工项是店铺全目录，不得再按商品分类过滤一道")
    # 店铺级筛选仍可用（解耦 ≠ 只能全量拉）
    for keep in ("keyword", "category_id", "status", "page", "size"):
        assert keep in props, f"processing_item_query 丢了合法参数 {keep}"


def test_processing_item_query_output_has_no_applicable_categories():
    """红证：条目格式化产物不得再有 `applicable_product_categories`（JSONB 列已删除）。"""
    item = ProcessingItemQueryTool._format_item({
        "id": "pi_1", "name": "打孔", "unitPrice": 8.0, "unit": "米",
        "applicableProductCategories": ["cat_curtain"],
    })
    assert "applicable_product_categories" not in item, (
        "加工项条目仍透传 applicable_product_categories —— 该列已随解耦下线（V66 DROP COLUMN）")


# ── ⑥ 建品不再被加工项门槛拦住（工具描述层，LLM 实际可见的口径） ──

def test_product_manage_description_no_longer_requires_processing_item_card():
    """红证：`product_manage` 的 description 不得再要求「先发加工项多选卡」。

    这是 LLM 真正看到的层（`base.get_schema()` 只取类属性 `description`）。
    解耦前那里写着「分类确认 → **必须先发加工项多选卡** → 货号 → 汇总确认卡」，
    与 `PR-014`「跳过加工项多选卡 ⇒ 判失败」配套；解耦后该门槛必须消失。
    """
    desc = ProductManageTool().get_schema()["function"]["description"]
    for forbidden in ("必须先发加工项多选卡", "processing_item_query(",
                      "applicable_category_id"):
        assert forbidden not in desc, (
            f"product_manage 描述仍要求建品先发加工项卡（解耦被回退）：命中「{forbidden}」")
    # create 仍是多步引导（不得因为删了加工项就退化成"看到 create 就抢跑"）
    assert "多步引导" in desc, "product_manage 描述丢了 create 的多步引导口径"
    # 明确告知模型「加工项与商品无关」——防它按旧记忆硬塞参数
    assert "加工项" in desc and "无关" in desc, (
        "product_manage 描述未声明「加工项与商品无关」（模型会照旧记忆硬传加工项参数）")
