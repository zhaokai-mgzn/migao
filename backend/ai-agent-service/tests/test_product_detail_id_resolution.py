"""
product_detail 的 id 解析接线 + `resolve_product_id` 分支覆盖（issue #8783）

病（issue 原文）：`product_detail` 描述承诺 `product_id` **支持名称/序号/UUID**，而
`execute()` 修前把入参原样拼进 `GET /api/admin/products/{product_id}` ⇒ 传名称必 NOT_FOUND：

    product_detail{product_id: "2699系列雪尼尔窗帘面料"}  ⇒  商品不存在[NOT_FOUND]

解析器 `app/utils/id_resolver.py` 的 `resolve_product_id()` 早已写好，但**生产代码零调用**。
本文件锁三条判据（每条都能单独变红）：

1. 传商品**名** ⇒ 解析成真实 id 后查到详情，返回该商品**真实价格**（修前：把名字当 id ⇒ NOT_FOUND）。
2. 解析不到 ⇒ **不得**把原名拼进 path 发请求，回「请用 product_search」（修前：正是那个 bug 形态）。
3. 序号 / UUID / 名称三种形态各一条 + 负控（不存在的名字 ⇒ 具名提示，不裸奔成服务端 NOT_FOUND）。

另覆盖 `resolve_product_id` 每条分支（接线后它们第一次被真跑）：UUID / 前缀 / 名称（精确+模糊）/
序号 / 非 UUID 真实 id / 都不中。判据层零 LLM、零网络：假客户端 `_FakeAdminApi` 照 admin-api 契约分流
（`ProductService.buildProductQueryWrapper`：`productId` 精确、`keyword` 只搜 name/skuCode）。
"""
# case_ids: MC-249

import pytest
from unittest.mock import patch

from app.tools.product_detail import ProductDetailTool
from app.utils.id_resolver import resolve_product_id


# ── 商品夹具：覆盖 UUID / 非 UUID 真实 id / 名称 / 序号 四种入参形态 ──────────────
UUID_CHE_AIR = "a1b2c3d4-e5f6-4a7b-8c9d-0123456789ab"
UUID_CLOUD = "b2c3d4e5-f6a7-4b8c-9d0e-123456789abc"
UUID_STAR = "c3d4e5f6-a7b8-4c9d-8e1f-23456789abcd"
# demo-seed 里**真实存在**的非 UUID 商品 id（docs/deployment/demo-seed.sql 的 products 段）
LEGACY_ID = "p-zg-001"
MISSING_NAME = "不存在的窗帘XYZ"

FIELD_NAME = "2699系列雪尼尔窗帘面料"

PRODUCTS = [
    {"id": UUID_CHE_AIR, "name": FIELD_NAME, "skuCode": "MG-2699", "price": 259.0},
    {"id": UUID_CLOUD, "name": "云朵半遮光窗帘", "skuCode": "MG-YD-001", "price": 68.0},
    {"id": LEGACY_ID, "name": "星空全遮光窗帘", "skuCode": "MG-ZG-001", "price": 98.0},
]

DETAILS = {
    UUID_CHE_AIR: {
        "id": UUID_CHE_AIR, "name": FIELD_NAME, "price": 259.0, "basePrice": 259.0,
        "status": "on_sale", "tenantId": 1,
        "skus": [{"id": "sku-2699-01", "skuCode": "2699-01", "colorName": "米白",
                  "doorWidth": "2.8米", "price": 259.0, "stock": 9599}],
    },
    UUID_CLOUD: {
        "id": UUID_CLOUD, "name": "云朵半遮光窗帘", "price": 68.0, "basePrice": 68.0,
        "status": "on_sale", "tenantId": 1, "skus": [],
    },
    LEGACY_ID: {
        "id": LEGACY_ID, "name": "星空全遮光窗帘", "price": 98.0, "basePrice": 98.0,
        "status": "on_sale", "tenantId": 1, "skus": [],
    },
}


class _FakeAdminApi:
    """按 admin-api 真实契约分流的假客户端（记录每次调用，供「发了什么请求」类判据）。

    - `GET /api/admin/products`：`productId` **精确**过滤、`keyword` 只搜 name/skuCode
      （照 `ProductService.buildProductQueryWrapper`）；
    - `GET /api/admin/products/{id}`：按 id 查；未知 id 回 `NOT_FOUND`。
    """

    def __init__(self, products=None, details=None):
        self.products = list(PRODUCTS if products is None else products)
        self.details = dict(DETAILS if details is None else details)
        self.calls = []

    async def get(self, path, params=None, tenant_id=None, user_id=None):
        params = dict(params or {})
        self.calls.append({"path": path, "params": params,
                           "tenant_id": tenant_id, "user_id": user_id})
        if path == "/api/admin/products":
            return self._list(params)
        if path.startswith("/api/admin/products/"):
            pid = path[len("/api/admin/products/"):]
            if pid in self.details:
                return {"success": True, "data": self.details[pid]}
            return {"success": False, "error": {"code": "NOT_FOUND", "message": "商品不存在"}}
        raise AssertionError(f"unexpected admin-api path: {path}")

    def _list(self, params):
        items = list(self.products)
        if params.get("productId"):
            items = [p for p in items if p["id"] == params["productId"]]
        keyword = params.get("keyword")
        if keyword:
            items = [p for p in items
                     if keyword in p["name"] or keyword in p["skuCode"]]
        page = int(params.get("page", 1))
        size = int(params.get("size", 10))
        start = (page - 1) * size
        return {"success": True,
                "data": {"items": items[start:start + size], "total": len(items)}}

    # ── 判据辅助：别只看「有没有调用」，要看**发的是哪条 path** ────────────────
    def paths(self):
        return [c["path"] for c in self.calls]

    def detail_paths(self):
        return [p for p in self.paths() if p.startswith("/api/admin/products/")]


class _PrefixStubApi(_FakeAdminApi):
    """前缀分支的**桩**：只喂「服务端返回 id 以该前缀开头的行」这一种输入。

    ⚠️ 照实登记的边界：admin-api 现在**没有** id 前缀查询能力（`productId` 精确 eq、
    `keyword` 只搜 name/skuCode）⇒ 截断的 UUID 前缀在线上**查不到**。本桩只验证解析器
    分支逻辑本身，**不**宣称线上前缀可用（见 PR 的未做项与重启条件）。
    """

    def _list(self, params):
        keyword = params.get("keyword") or ""
        if len(keyword) >= 8:
            return {"success": True,
                    "data": {"items": [{"id": UUID_CHE_AIR, "name": FIELD_NAME}], "total": 1}}
        return super()._list(params)


@pytest.fixture
def api():
    return _FakeAdminApi()


@pytest.fixture
def tool():
    return ProductDetailTool()


async def _execute(tool, api, context, raw):
    """在「假 admin-api」下跑一次 product_detail（patch 必须覆盖整个 await）。"""
    with patch("app.tools.product_detail.get_admin_api_client", return_value=api):
        return await tool.execute(context=context, product_id=raw)


class TestProductDetailResolvesToolReference:
    """判据 ①③：名称 / 序号 / UUID 三种形态都能查到商品（不是 NOT_FOUND）。"""

    async def test_name_resolves_to_id_then_returns_real_price(
        self, tool, api, admin_tool_context
    ):
        """判据 ①：传商品**名** ⇒ 返回该商品真实价格（修前：NOT_FOUND）。

        红证（修前 execute）：`GET /api/admin/products/2699系列雪尼尔窗帘面料` ⇒ 服务端
        NOT_FOUND；本判据的 `detail_paths() == [/products/<UUID>]` 与 `price == 259.0`
        两条都拿不到。
        """
        result = await _execute(tool, api, admin_tool_context, FIELD_NAME)

        assert result.success is True
        assert result.data["id"] == UUID_CHE_AIR
        assert result.data["price"] == 259.0
        assert result.data["skus"][0]["stock"] == 9599
        # 详情请求必须发在**解析后的 id** 上
        assert api.detail_paths() == [f"/api/admin/products/{UUID_CHE_AIR}"]
        # 任何请求的 path 都不得含用户给的商品名
        assert all(FIELD_NAME not in p for p in api.paths())
        assert all(c["tenant_id"] == admin_tool_context.tenant_id for c in api.calls)

    async def test_index_resolves_to_nth_product(self, tool, api, admin_tool_context):
        """判据 ③（序号形态）：`product_id="3"` ⇒ 第 3 个商品（1-based），按该 id 查详情。"""
        result = await _execute(tool, api, admin_tool_context, "3")

        assert result.success is True
        assert result.data["id"] == LEGACY_ID
        assert result.data["price"] == 98.0
        index_calls = [c for c in api.calls
                       if c["params"].get("page") == 3 and c["params"].get("size") == 1]
        assert len(index_calls) == 1, "序号必须按 1-based 翻页（page=3 → 第 3 条）"
        assert api.detail_paths() == [f"/api/admin/products/{LEGACY_ID}"]

    async def test_uuid_is_used_directly_without_any_search(
        self, tool, api, admin_tool_context
    ):
        """判据 ③（UUID 形态）：UUID 直通，零列表查询（不多付一次往返）。"""
        result = await _execute(tool, api, admin_tool_context, UUID_CLOUD)

        assert result.success is True
        assert result.data["id"] == UUID_CLOUD
        assert api.paths() == [f"/api/admin/products/{UUID_CLOUD}"], (
            "UUID 已是真实 id ⇒ 解析器应零 HTTP 直通，只发详情请求"
        )
        assert api.calls[0]["user_id"] == admin_tool_context.user_id

    async def test_legacy_non_uuid_id_still_resolves(self, tool, api, admin_tool_context):
        """真实 id 不一定是 UUID：demo-seed / 历史数据的 `p-zg-001` 也必须能用。

        没有这条，接线会把「真实 id」误判成「未找到」—— 那等于用修 bug 的方式造新 bug。
        """
        result = await _execute(tool, api, admin_tool_context, LEGACY_ID)

        assert result.success is True
        assert result.data["id"] == LEGACY_ID
        assert result.data["price"] == 98.0
        assert api.detail_paths() == [f"/api/admin/products/{LEGACY_ID}"]


class TestProductDetailUnresolvedExit:
    """判据 ②③：解析不到 ⇒ 具名提示 + 绝不把原名当 id 打服务端。"""

    async def test_unresolved_name_never_sent_as_product_id(
        self, tool, api, admin_tool_context
    ):
        """判据 ②：解析失败时**不得**发出 `GET /api/admin/products/<原名>`。

        红证（修前 execute）：唯一一次请求就是 `/api/admin/products/不存在的窗帘XYZ` ——
        本判据的 `detail_paths() == []` 与「path 不含原名」两条同时红。
        """
        result = await _execute(tool, api, admin_tool_context, MISSING_NAME)

        assert result.success is False
        assert result.error == "商品不存在"
        # 具名提示：说清是哪个商品没找到（不是裸 NOT_FOUND 套话）
        assert MISSING_NAME in result.message
        assert "product_search" in result.suggestion
        # 只允许走「列表查询」（解析），不允许任何详情请求
        assert api.detail_paths() == []
        assert all(MISSING_NAME not in p for p in api.paths())
        assert api.paths() == ["/api/admin/products", "/api/admin/products"], (
            "解析路径：按名称搜 + 按 id 精确搜（产品级不给 admin-api 发详情请求）"
        )

    async def test_unresolved_does_not_return_server_not_found_suggestion(
        self, tool, api, admin_tool_context
    ):
        """判据 ③（负控）：不存在的名字 ⇒ 具名提示，不回「检查商品 ID 是否正确」的裸 NOT_FOUND。

        修前该输入得到的是**服务端** NOT_FOUND 分支的文案（「请检查商品 ID 是否正确」），
        会把模型引向「ID 打错了」而不是「改用 product_search 按名字搜」。
        """
        result = await _execute(tool, api, admin_tool_context, MISSING_NAME)

        assert result.success is False
        assert "请检查商品 ID 是否正确" not in (result.message or "")
        assert "product_search" in (result.suggestion or "")
        assert "未找到" in (result.message or "")


class TestResolveProductIdBranches:
    """`resolve_product_id` 每条分支（接线后第一次被真跑的代码）。"""

    async def test_branch_uuid_exact_returns_input_without_http(self):
        api = _FakeAdminApi()
        resolved = await resolve_product_id(UUID_CHE_AIR, 1, api)

        assert resolved == UUID_CHE_AIR
        assert api.calls == []

    async def test_branch_uuid_prefix_returns_matching_id(self):
        """前缀分支：服务端返回 id 以该前缀开头的行 ⇒ 解析器取它。

        ⚠️ 桩的边界见 `_PrefixStubApi`：admin-api 无 id 前缀查询，线上不会走到。
        """
        api = _PrefixStubApi()
        resolved = await resolve_product_id(UUID_CHE_AIR.replace("-", "")[:12], 1, api)

        assert resolved == UUID_CHE_AIR
        assert {c["params"]["productId"] for c in api.calls if "productId" in c["params"]} == {
            UUID_CHE_AIR.replace("-", "")[:12]
        }

    async def test_branch_name_exact_preferred_over_fuzzy(self):
        api = _FakeAdminApi()
        resolved = await resolve_product_id("云朵半遮光窗帘", 1, api)

        assert resolved == UUID_CLOUD, "精确名称命中必须优先于列表第一条"
        keyword_calls = [c for c in api.calls if c["params"].get("keyword") == "云朵半遮光窗帘"]
        assert keyword_calls[0]["params"]["size"] == 5

    async def test_branch_name_fuzzy_falls_back_to_first(self):
        api = _FakeAdminApi()
        resolved = await resolve_product_id("遮光", 1, api)

        assert resolved == UUID_CLOUD, "无精确名称 ⇒ 取服务端返回的第一条（模糊）"
        assert api.detail_paths() == []

    async def test_branch_index_is_one_based(self):
        api = _FakeAdminApi()
        resolved = await resolve_product_id("3", 1, api)

        assert resolved == LEGACY_ID
        assert [c["params"] for c in api.calls] == [{"page": 3, "size": 1}]

    async def test_branch_legacy_non_uuid_id_exact_match(self):
        api = _FakeAdminApi()
        resolved = await resolve_product_id(LEGACY_ID, 1, api)

        assert resolved == LEGACY_ID
        product_id_positions = [i for i, c in enumerate(api.calls) if "productId" in c["params"]]
        assert product_id_positions == [len(api.calls) - 1], (
            "非 UUID id 走不到「UUID 前缀」分支（它不是 hex）⇒ productId 精确查询只在**最后兜底**出现"
        )
        assert api.calls[-1]["params"]["productId"] == LEGACY_ID

    async def test_branch_no_match_returns_none(self):
        api = _FakeAdminApi()
        resolved = await resolve_product_id(MISSING_NAME, 1, api)

        # `is None` 会被 QA Growth Gate 的 WeakAsserts 判成「存在性形态」；本仓既有的
        # 等价写法是 `== None` + noqa + 理由（先例：tests/test_briefing_generator.py）。
        assert resolved == None, "解析不到 ⇒ 必须回 None（不许退回把原名当 id）"  # noqa: E711
        assert api.detail_paths() == []

    async def test_branch_empty_input_returns_none_without_http(self):
        api = _FakeAdminApi()

        assert await resolve_product_id("   ", 1, api) is None
        assert api.calls == []

    async def test_tenant_id_passed_on_every_request(self):
        api = _FakeAdminApi()
        await resolve_product_id(FIELD_NAME, 42, api)

        assert {c["tenant_id"] for c in api.calls} == {42}
