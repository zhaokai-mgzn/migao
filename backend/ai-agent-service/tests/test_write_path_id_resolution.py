"""
写路径的 id 解析：**宁可失败，绝不猜**（issue #8788）

## 病（与 #8783 同族，但**失败语义不同**）

`product_update` / `sku_update` 的 `product_id` 描述都写「支持名称/序号/UUID」，
而两者修前把入参**原样**拼进写 URL：`PATCH /api/admin/agent/products/{raw}`。

写路径与只读路径的差别是**后果**，不是措辞：

- 只读（`product_detail`）：解析不到 ⇒ 回「没找到，请用 product_search」⇒ **安全**；
- 写（本单）：解析不到却仍发请求 ⇒ 一旦服务端「差不多就写」⇒ **改错商品不可逆**。

而服务端 `ProductService.resolveProductId` 的第 5 步正是 `getName().contains(raw) ⇒ 取第一条`
⇒ 把「改哪一件商品」交给「谁先被查到」。本文件锁住的就是这条入口。

## 本文件锁四条（对应 issue #8788 的四种情形，每条都能单独变红）

| 情形 | 判据 |
|---|---|
| 唯一命中（名称 / 序号） | 正常写，且**写 URL 里是解析出的真实 id**（不是原名） |
| 命中多条（模糊名称） | **拒绝写**：`error=商品不唯一`、message 含「匹配到 2 个商品」+「未执行修改」、**零 PATCH** |
| 不命中 | **拒绝写**：`error=商品不存在`、message 含原名 +「未执行修改」、**零 PATCH** |
| 入参本身就是合法 id | UUID：**零解析请求**（负控）；非 UUID 真实 id：**只**一次 `productId` 精确探测，**零** keyword 探测 |

红证（修前在 `origin/main` 上跑本文件）：名称被原样拼进写 URL ⇒ 「写 URL 是解析出的 id」两条红；
「零 PATCH」两条红（修前恰好各发出一次 PATCH，payload 就是那个名字）。

另锁两条**结构性**不变式（防"修好了又被改回去"）：写工具不许调用只读的宽松解析器
（`resolve_product_id()` 允许"模糊取第一条"）；「多条」与「不命中」的话术不得混成一句。

判据层零 LLM / 零网络 / 零 DB：假客户端 `_FakeAdminApi` 照 admin-api 契约分流
（`ProductService.buildProductQueryWrapper`：`productId` 精确 eq、`keyword` 只搜 name/skuCode）。
"""
# case_ids: MC-252

from pathlib import Path

import pytest

from app.tools.base import ToolContext
from app.tools.product_update import ProductUpdateTool
from app.tools.sku_update import SkuUpdateTool


# ── 商品夹具：UUID / 非 UUID 真实 id / 名称 / 序号 四种入参形态 + 一组「重名候选」 ──
UUID_CHE_AIR = "a1b2c3d4-e5f6-4a7b-8c9d-0123456789ab"
UUID_CLOUD = "b2c3d4e5-f6a7-4b8c-9d0e-123456789abc"
UUID_TIE_A = "d4e5f6a7-b8c9-4d0e-9f1a-3456789abcde"
UUID_TIE_B = "d4e5f6a7-c9d0-4e1f-8a2b-456789abcdef"   # 与 TIE_A 共享 8 位前缀 d4e5f6a7
#: 前缀唯一的商品（「id 前缀」形态的负控：唯一命中 ⇒ 正常写）
UUID_PREFIX_UNIQUE = "f7a8b9c0-1d2e-4f3a-8b4c-56789abcdef0"
# docs/deployment/demo-seed.sql 的 products 段：**真实存在的非 UUID 商品 id**
LEGACY_ID = "p-zg-001"
UNAVAILABLE = "unavailable"

FIELD_NAME = "2699系列雪尼尔窗帘面料"
UNIQUE_FUZZY = "云朵半遮光"          # 只是商品名的一部分 ⇒ 唯一命中
AMBIGUOUS_NAME = "奶油风提花布"       # 命中两条 ⇒ 必须拒绝写
MISSING_NAME = "不存在的窗帘XYZ"

PRODUCTS = [
    {"id": UUID_CHE_AIR, "name": FIELD_NAME, "skuCode": "MG-2699"},
    {"id": UUID_CLOUD, "name": "云朵半遮光窗帘", "skuCode": "MG-YD-001"},
    {"id": LEGACY_ID, "name": "星空全遮光窗帘", "skuCode": "MG-ZG-001"},
    {"id": UUID_TIE_A, "name": "奶油风提花布-米白", "skuCode": "MG-TH-001"},
    {"id": UUID_TIE_B, "name": "奶油风提花布-灰蓝", "skuCode": "MG-TH-002"},
    {"id": UUID_PREFIX_UNIQUE, "name": "亚麻遮光布", "skuCode": "MG-YM-001"},
]


class _FakeAdminApi:
    """按 admin-api 真实契约分流的假客户端，记录**每一次**读写调用（判据只看调用面）。

    - `GET /api/admin/products`：`productId` **精确**过滤；`keyword` 搜 name **或** skuCode
      （照 `ProductService.buildProductQueryWrapper`）；分页语义照 `page`/`size`。
    - `PATCH /api/admin/agent/products/...`：记录 path + body，回成功。
    """

    def __init__(self, products=None, list_fails=False):
        self.products = list(PRODUCTS if products is None else products)
        self.list_fails = list_fails
        self.calls = []

    async def get(self, path, params=None, tenant_id=None, user_id=None):
        params = dict(params or {})
        self.calls.append({"method": "GET", "path": path, "params": params,
                           "tenant_id": tenant_id})
        assert path == "/api/admin/products", f"写路径的解析只许查商品列表，实际发了: {path}"
        if self.list_fails:
            return {"success": False, "error": {"code": "INTERNAL", "message": "list boom"}}
        page = int(params.get("page", 1))
        size = int(params.get("size", 10))
        items = self._filter(params)
        return {"success": True,
                "data": {"items": items[(page - 1) * size:page * size], "total": len(items)}}

    async def patch(self, path, json_data=None, tenant_id=None, user_id=None):
        self.calls.append({"method": "PATCH", "path": path, "json_data": json_data,
                           "tenant_id": tenant_id})
        return {"success": True, "data": {"path": path}}

    def _filter(self, params):
        items = list(self.products)
        if params.get("productId"):
            items = [p for p in items if p["id"] == params["productId"]]
        keyword = params.get("keyword")
        if keyword:
            items = [p for p in items
                     if keyword in p["name"] or keyword in p["skuCode"]]
        return items

    # ── 判据辅助：别只看「有没有调用」，要看**发的是哪条 path / 哪些参数** ──────
    def writes(self):
        return [c for c in self.calls if c["method"] == "PATCH"]

    def write_paths(self):
        return [c["path"] for c in self.writes()]

    def resolve_calls(self):
        return [c for c in self.calls if c["method"] == "GET"]


class _HugeCatalogApi(_FakeAdminApi):
    """商品目录**大于扫描上限**的假面：用来钉「无法证明唯一 ⇒ 拒绝」这条 fail-closed 出口。"""

    async def get(self, path, params=None, tenant_id=None, user_id=None):
        params = dict(params or {})
        self.calls.append({"method": "GET", "path": path, "params": params,
                           "tenant_id": tenant_id})
        page = int(params.get("page", 1))
        size = int(params.get("size", 10))
        items = [{"id": f"f7a8b9c0-{page:02d}{i:02d}-4e1f-8a2b-456789abcdef",
                  "name": f"商品{page}-{i}"} for i in range(size)]
        return {"success": True, "data": {"items": items, "total": 1000}}


def _ctx() -> ToolContext:
    """商户管理员上下文（`admin` 在 admin-api 恒为通配 `["*"]`，#4106 F3）。"""
    return ToolContext(tenant_id=1, user_id="u1", role="admin", permissions=["*"])


@pytest.fixture
def product_update():
    return ProductUpdateTool()


@pytest.fixture
def sku_update():
    return SkuUpdateTool()


def _patch_client(monkeypatch, module: str, api: _FakeAdminApi):
    """把工具模块里的 `get_admin_api_client` 换成假客户端（同一个假面同时承接读与写）。"""
    import importlib

    mod = importlib.import_module(module)
    monkeypatch.setattr(mod, "get_admin_api_client", lambda: api)
    return api


class TestProductUpdateResolvesBeforeWrite:
    """`product_update`：四种入参形态各一条 + 红线（多条/不命中 ⇒ 零写请求）。"""

    @pytest.mark.asyncio
    async def test_uuid_is_written_directly_with_zero_resolution_requests(
            self, product_update, monkeypatch):
        """负控：合法 UUID 直传 ⇒ **不产生任何解析请求**（每写一次只多一次写请求，不少也不多）。"""
        api = _patch_client(monkeypatch, "app.tools.product_update", _FakeAdminApi())

        result = await product_update.execute(
            _ctx(), product_id=UUID_CHE_AIR, price=100.0, before_price=259.0)

        assert result.success is True, result.message
        assert api.resolve_calls() == [], f"UUID 直传不该有任何解析往返: {api.resolve_calls()}"
        assert api.write_paths() == [f"/api/admin/agent/products/{UUID_CHE_AIR}"]

    @pytest.mark.asyncio
    async def test_unique_name_is_resolved_then_written_by_id(
            self, product_update, monkeypatch):
        """判据 ①：名称**唯一命中** ⇒ 正常写，且写 URL 里是**解析出的真实 id**（不是原名）。"""
        api = _patch_client(monkeypatch, "app.tools.product_update", _FakeAdminApi())

        result = await product_update.execute(
            _ctx(), product_id=FIELD_NAME, price=100.0, before_price=259.0)

        assert result.success is True, result.message
        assert api.write_paths() == [f"/api/admin/agent/products/{UUID_CHE_AIR}"]
        assert FIELD_NAME not in api.write_paths()[0], "商品名不得出现在写 URL 里"

    @pytest.mark.asyncio
    async def test_unique_partial_name_resolves_to_that_product(
            self, product_update, monkeypatch):
        """名称片段只有**一个**候选 ⇒ 唯一命中（唯一性来自候选集，不是「取第一条」）。"""
        api = _patch_client(monkeypatch, "app.tools.product_update", _FakeAdminApi())

        result = await product_update.execute(
            _ctx(), product_id=UNIQUE_FUZZY, name="云朵半遮光窗帘")

        assert result.success is True, result.message
        assert api.write_paths() == [f"/api/admin/agent/products/{UUID_CLOUD}"]

    @pytest.mark.asyncio
    async def test_index_is_refused_with_zero_write_and_zero_http(
            self, product_update, monkeypatch):
        """🔴 **写路径拒绝序号**（issue #8788 裁定，与只读面不同）：序号按创建时间排序，
        增删商品后漂移 ⇒ 同一个「3」今天是 A、明天是 B ⇒「第 3 个」不是可信目标。

        判据同时钉住两件事：**零 PATCH**（不写）+ **零 HTTP**（不为了"确认一下"去查目录）。
        """
        api = _patch_client(monkeypatch, "app.tools.product_update", _FakeAdminApi())

        result = await product_update.execute(_ctx(), product_id="2", name="改个名")

        assert result.success is False
        assert result.error == "商品引用不可用于写入"
        assert "序号" in result.message and "漂移" in result.message
        assert "未执行修改" in result.message
        assert "product_search" in result.suggestion
        assert api.writes() == [], f"序号必须拒绝，实际写了: {api.write_paths()}"
        assert api.resolve_calls() == [], f"序号不该产生任何查询: {api.resolve_calls()}"

    @pytest.mark.asyncio
    async def test_legacy_non_uuid_id_needs_one_exact_probe_and_no_name_search(
            self, product_update, monkeypatch):
        """非 UUID 真实 id（种子数据 `p-zg-001`）⇒ **一次** `productId` 精确探测即写，**零** keyword 探测。

        为什么允许这一次探测：`p-zg-001` 与商品名在**静态上不可区分**，不探测就会把
        **真实存在的商品**判成「不存在」（#8783 踩过的"用修 bug 的方式造新 bug"）。
        但它必须是**精确 eq**、绝不产生模糊候选 ⇒ 这条断言就是"绝不猜"的形态判据。
        """
        api = _patch_client(monkeypatch, "app.tools.product_update", _FakeAdminApi())

        result = await product_update.execute(
            _ctx(), product_id=LEGACY_ID, price=100.0, before_price=98.0)

        assert result.success is True, result.message
        assert [c["params"] for c in api.resolve_calls()] == [
            {"productId": LEGACY_ID, "page": 1, "size": 1}]
        assert not any("keyword" in c["params"] for c in api.resolve_calls()), (
            f"非 UUID 真实 id 不该走名称搜索: {api.resolve_calls()}")
        assert api.write_paths() == [f"/api/admin/agent/products/{LEGACY_ID}"]

    @pytest.mark.asyncio
    async def test_unique_id_prefix_is_resolved_then_written(
            self, product_update, monkeypatch):
        """id 前缀**唯一命中** ⇒ 正常写（写 URL 里是完整 id）。

        服务端没有 id 前缀查询面（`productId` 精确 eq、`keyword` 只搜 name/货号）⇒ 只能翻页扫目录；
        本判据同时钉住「扫描只发生在前缀形态上」（名称/序号形态不付这个成本）。
        """
        api = _patch_client(monkeypatch, "app.tools.product_update", _FakeAdminApi())

        result = await product_update.execute(_ctx(), product_id="f7a8b9c0", name="改个名")

        assert result.success is True, result.message
        assert api.write_paths() == [f"/api/admin/agent/products/{UUID_PREFIX_UNIQUE}"]
        assert [c["params"] for c in api.resolve_calls()] == [
            {"page": 1, "size": 100}]  # 只扫了一页（目录已到底）

    @pytest.mark.asyncio
    async def test_id_prefix_matching_multiple_products_is_refused(
            self, product_update, monkeypatch):
        """🔴 id 前缀命中**多条** ⇒ 拒绝写（零 PATCH）：「低概率猜错」在写路径上不接受。"""
        api = _patch_client(monkeypatch, "app.tools.product_update", _FakeAdminApi())

        result = await product_update.execute(_ctx(), product_id="d4e5f6a7", name="改个名")

        assert result.success is False
        assert result.error == "商品不唯一"
        assert "匹配到 2 个商品" in result.message
        assert "未执行修改" in result.message
        assert api.writes() == []

    @pytest.mark.asyncio
    async def test_unprovable_prefix_is_refused(self, product_update, monkeypatch):
        """目录大于扫描上限 ⇒ **无法证明唯一** ⇒ 拒绝（fail-closed，不许拿"扫到的第一条"当答案）。"""
        api = _patch_client(monkeypatch, "app.tools.product_update", _HugeCatalogApi())

        result = await product_update.execute(_ctx(), product_id="f7a8b9c0", name="改个名")

        assert result.success is False
        assert result.error == "商品引用不可用于写入"
        assert "无法证明只有一个商品匹配" in result.message
        assert api.writes() == []

    @pytest.mark.asyncio
    async def test_ambiguous_name_is_refused_with_zero_write(
            self, product_update, monkeypatch):
        """🔴 红线：命中多条 ⇒ **拒绝写**（零 PATCH），话术含「匹配到 2 个商品」+ 候选 + product_search。"""
        api = _patch_client(monkeypatch, "app.tools.product_update", _FakeAdminApi())

        result = await product_update.execute(_ctx(), product_id=AMBIGUOUS_NAME, name="新名字")

        assert result.success is False, "匹配到多个商品时**绝不能**写成功"
        assert result.error == "商品不唯一"
        assert "匹配到 2 个商品" in result.message
        assert AMBIGUOUS_NAME in result.message
        assert "未执行修改" in result.message, "写工具必须明确「什么都没改」"
        assert "product_search" in result.suggestion
        assert api.writes() == [], f"拒绝时零写请求，实际发了: {api.write_paths()}"

    @pytest.mark.asyncio
    async def test_unknown_name_is_refused_with_zero_write(
            self, product_update, monkeypatch):
        """不命中 ⇒ 拒绝写（零 PATCH），且**任何请求 path/参数**都不含那个名字。"""
        api = _patch_client(monkeypatch, "app.tools.product_update", _FakeAdminApi())

        result = await product_update.execute(_ctx(), product_id=MISSING_NAME, name="新名字")

        assert result.success is False
        assert result.error == "商品不存在"
        assert MISSING_NAME in result.message
        assert "未执行修改" in result.message
        assert api.writes() == [], f"拒绝时零写请求，实际发了: {api.write_paths()}"
        # 原名**只**允许出现在解析查询的 query 参数里（精确 eq / keyword 检索）；
        # 任何请求的 **path** 里都不许有它 —— 修前的 bug 形态正是 `PATCH .../{原名}`。
        assert all(MISSING_NAME not in str(c["path"]) for c in api.calls)

    @pytest.mark.asyncio
    async def test_sku_code_hit_is_not_accepted_as_a_product_name(
            self, product_update, monkeypatch):
        """货号命中 ≠ 商品名命中：`keyword` 也搜 skuCode，但拿它写商品同样是猜 ⇒ 拒绝。"""
        api = _patch_client(monkeypatch, "app.tools.product_update", _FakeAdminApi())

        result = await product_update.execute(_ctx(), product_id="MG-ZG-001", name="新名字")

        assert result.success is False
        assert result.error == "商品不存在"
        assert api.writes() == []

    @pytest.mark.asyncio
    async def test_list_api_failure_is_not_reported_as_not_found(
            self, product_update, monkeypatch):
        """查询失败 ⇒ 不许说成「商品不存在」（那是另一件事），仍然零写请求。"""
        api = _patch_client(monkeypatch, "app.tools.product_update",
                            _FakeAdminApi(list_fails=True))

        result = await product_update.execute(_ctx(), product_id=FIELD_NAME, name="新名字")

        assert result.success is False
        assert result.error == "商品查询失败"
        assert "未执行修改" in result.message
        assert api.writes() == []


class TestSkuUpdateResolvesBeforeWrite:
    """`sku_update` 同一口径（它是另一个写工具，接线必须各自有判据，不能靠"同一个 helper"推断）。"""

    @pytest.mark.asyncio
    async def test_uuid_is_written_directly_with_zero_resolution_requests(
            self, sku_update, monkeypatch):
        api = _patch_client(monkeypatch, "app.tools.sku_update", _FakeAdminApi())

        result = await sku_update.execute(
            _ctx(), product_id=UUID_CHE_AIR, price=9.9, before_price=259.0,
            color="米白", door_width="2.8米")

        assert result.success is True, result.message
        assert api.resolve_calls() == []
        assert api.write_paths() == [
            f"/api/admin/agent/products/{UUID_CHE_AIR}/skus/price"]

    @pytest.mark.asyncio
    async def test_unique_name_is_resolved_then_written_by_id(
            self, sku_update, monkeypatch):
        api = _patch_client(monkeypatch, "app.tools.sku_update", _FakeAdminApi())

        result = await sku_update.execute(
            _ctx(), product_id=FIELD_NAME, price=9.9, before_price=259.0, color="米白")

        assert result.success is True, result.message
        assert api.write_paths() == [
            f"/api/admin/agent/products/{UUID_CHE_AIR}/skus/price"]

    @pytest.mark.asyncio
    async def test_ambiguous_name_is_refused_with_zero_write(self, sku_update, monkeypatch):
        api = _patch_client(monkeypatch, "app.tools.sku_update", _FakeAdminApi())

        result = await sku_update.execute(
            _ctx(), product_id=AMBIGUOUS_NAME, price=9.9, before_price=10.0, color="米白")

        assert result.success is False
        assert result.error == "商品不唯一"
        assert "匹配到 2 个商品" in result.message
        assert "未执行修改" in result.message
        assert api.writes() == []

    @pytest.mark.asyncio
    async def test_unknown_name_is_refused_with_zero_write(self, sku_update, monkeypatch):
        api = _patch_client(monkeypatch, "app.tools.sku_update", _FakeAdminApi())

        result = await sku_update.execute(
            _ctx(), product_id=MISSING_NAME, price=9.9, before_price=10.0)

        assert result.success is False
        assert result.error == "商品不存在"
        assert MISSING_NAME in result.message
        assert api.writes() == []


class TestNoGuessIsStructural:
    """结构性不变式：防「修好了又被改回去」，也防两个写工具的话术各自漂移。"""

    TOOLS_DIR = Path(__file__).resolve().parents[1] / "app" / "tools"

    def test_write_tools_use_the_strict_resolver_only(self):
        """写工具**只许**用严格解析器 —— 只读那个 `resolve_product_id()` 会「模糊取第一条」。

        这是本单的核心不变式：接线接错对象（接成只读解析器）会**看起来也接了**，
        但写路径重新长出"猜"的分支 ⇒ 必须在文本层钉死。
        """
        for name in ("product_update.py", "sku_update.py"):
            source = (self.TOOLS_DIR / name).read_text(encoding="utf-8")
            assert "resolve_unique_product_id(" in source, f"{name} 未接线严格解析器"
            assert "resolve_product_id(" not in source, (
                f"{name} 调用了只读的宽松解析器（它允许名称模糊取第一条）—— 写路径禁止")

    REPO_ROOT = Path(__file__).resolve().parents[3]

    def _java_code(self, rel: str) -> str:
        """读 Java 源并剥掉注释行 —— 判据只看**代码**（注释里的字样不算接线）。"""
        source = (self.REPO_ROOT / rel).read_text(encoding="utf-8")
        return "\n".join(
            line for line in source.splitlines()
            if not line.lstrip().startswith(("*", "//", "/*"))
        )

    def test_controller_write_paths_use_the_strict_resolver(self):
        """**服务层才是真相所在地**：`AgentProductController` 的每个写端点都必须用严格解析。

        这条守卫是 Python 侧不变式的**上游孪生**：工具侧只发已确定的 id，但服务端仍有别的调用方
        （以及未来新增的端点）⇒ 控制器这一层也必须只走 `resolveProductIdStrict`
        （共享的 `resolveProductId` 允许「前缀/序号/名称模糊取第一条」，出现在写侧就是改错商品）。
        """
        code = self._java_code(
            "backend/admin-api/src/main/java/com/migao/admin/controller/agent/AgentProductController.java")

        assert "productService.resolveProductIdStrict(" in code, "控制器没有接线严格解析"
        assert "productService.resolveProductId(" not in code, (
            "写侧出现了共享解析器（它允许前缀/序号/名称模糊取第一条）—— 改错商品不可逆")
        # 4 个写端点（改品/改库存/改 SKU 价/按 SKU id 改价）一个都不许漏
        assert code.count("productService.resolveProductIdStrict(") >= 4

    def test_service_strict_resolver_keeps_the_three_refusals(self):
        """服务层严格解析器必须**自带**三种拒绝出口（序号 / 重名 / 前缀多条）。"""
        code = self._java_code(
            "backend/admin-api/src/main/java/com/migao/admin/service/ProductService.java")

        assert "public String resolveProductIdStrict(" in code
        assert "PRODUCT_INDEX_NOT_ALLOWED" in code, "序号必须在服务层也被拒绝（会随增删漂移）"
        assert "PRODUCT_AMBIGUOUS" in code, "多条命中必须具名拒绝"
        assert "ambiguousProductRef(" in code

    def test_ambiguous_and_not_found_do_not_share_one_message(self):
        """两种拒绝的**话术必须不同**：混成一句「未找到」会把模型推向反复重试同一个名称。"""
        source = (self.TOOLS_DIR / "write_refusal.py").read_text(encoding="utf-8")
        assert "商品不唯一" in source
        assert "商品不存在" in source
        assert "product_search" in source
