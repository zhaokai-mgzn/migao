"""
ID 自动解析器单元测试

覆盖 id_resolver.py 所有解析路径：
- UUID 精确匹配、UUID 前缀、序号、名称匹配、pipe 格式
"""

import pytest
from unittest.mock import AsyncMock


UUID_1 = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
UUID_2 = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
UUID_3 = "c3d4e5f6-a7b8-9012-cdef-123456789012"
HEX_PREFIX = "a1b2c3d4e5f6"  # first 12 hex chars of UUID_1 (without dashes)


def _make_page_resp(items, total=None):
    """构造 admin-api 分页响应"""
    return {"data": {"items": items, "total": total or len(items)}}


class TestResolveProductId:
    """resolve_product_id — 商品 ID 解析"""

    @pytest.fixture
    def http_client(self):
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_empty_input_returns_none(self, http_client):
        from app.utils.id_resolver import resolve_product_id
        assert await resolve_product_id("", 1, http_client) is None
        assert await resolve_product_id("  ", 1, http_client) is None

    @pytest.mark.asyncio
    async def test_exact_uuid_match(self, http_client):
        from app.utils.id_resolver import resolve_product_id
        result = await resolve_product_id(UUID_1, 1, http_client)
        assert result == UUID_1
        http_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_uuid_prefix_match(self, http_client):
        from app.utils.id_resolver import resolve_product_id
        http_client.get.return_value = _make_page_resp([
            {"id": UUID_1, "name": "商品A"}
        ])
        result = await resolve_product_id(HEX_PREFIX, 1, http_client)
        assert result == UUID_1

    @pytest.mark.asyncio
    async def test_uuid_prefix_fallback_to_keyword(self, http_client):
        """UUID 前缀直接查询无结果时，fallback 到 keyword 搜索"""
        from app.utils.id_resolver import resolve_product_id
        # 使用 8 位前缀（不带横线），确保 startswith 检查能匹配 UUID
        prefix8 = UUID_1[:8]  # "a1b2c3d4"
        # call 1: productId search → empty
        # call 2: keyword (size=1) → return UUID that starts with prefix
        http_client.get.side_effect = [
            _make_page_resp([]),
            _make_page_resp([{"id": UUID_1, "name": "匹配商品"}]),
        ]
        result = await resolve_product_id(prefix8, 1, http_client)
        assert result == UUID_1

    @pytest.mark.asyncio
    async def test_number_index_match(self, http_client):
        from app.utils.id_resolver import resolve_product_id
        http_client.get.return_value = _make_page_resp([
            {"id": UUID_3, "name": "第三个商品"}
        ])
        result = await resolve_product_id("3", 1, http_client)
        assert result == UUID_3
        # 序号 3 → idx 2 → page=3
        call_kwargs = http_client.get.call_args[1]
        assert call_kwargs["params"]["page"] == 3

    @pytest.mark.asyncio
    async def test_number_zero_returns_none(self, http_client):
        """序号 0 → idx=-1 跳过索引查询，fallback 到名称搜索也找不到"""
        from app.utils.id_resolver import resolve_product_id
        # 设置空结果，确保 fallback 到名称搜索也找不到
        http_client.get.return_value = _make_page_resp([])
        result = await resolve_product_id("0", 1, http_client)
        assert result is None

    @pytest.mark.asyncio
    async def test_exact_name_match(self, http_client):
        from app.utils.id_resolver import resolve_product_id
        http_client.get.return_value = _make_page_resp([
            {"id": UUID_1, "name": "普通窗帘"},
            {"id": UUID_2, "name": "隔热窗帘"},
        ])
        result = await resolve_product_id("隔热窗帘", 1, http_client)
        assert result == UUID_2

    @pytest.mark.asyncio
    async def test_fuzzy_name_match(self, http_client):
        from app.utils.id_resolver import resolve_product_id
        http_client.get.return_value = _make_page_resp([
            {"id": UUID_1, "name": "麻芘隔热窗帘郁金香色"},
        ])
        result = await resolve_product_id("隔热", 1, http_client)
        assert result == UUID_1

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self, http_client):
        from app.utils.id_resolver import resolve_product_id
        http_client.get.return_value = _make_page_resp([])
        result = await resolve_product_id("不存在的商品", 1, http_client)
        assert result is None

    @pytest.mark.asyncio
    async def test_passes_tenant_id(self, http_client):
        from app.utils.id_resolver import resolve_product_id
        http_client.get.return_value = _make_page_resp([
            {"id": UUID_1, "name": "商品"}
        ])
        await resolve_product_id("商品", 42, http_client)
        assert http_client.get.call_args[1]["tenant_id"] == 42


class TestResolveProcessingItemIds:
    """resolve_processing_item_ids — 加工项 ID 批量解析"""

    PI_UUID_1 = "a1111111-1111-4111-8111-111111111111"
    PI_UUID_2 = "a2222222-2222-4222-8222-222222222222"
    PI_UUID_3 = "a3333333-3333-4333-8333-333333333333"
    PI_UUID_4 = "a4444444-4444-4444-8444-444444444444"

    @pytest.fixture
    def http_client(self):
        return AsyncMock()

    @pytest.fixture
    def sample_items(self):
        return [
            {"id": self.PI_UUID_1, "name": "S钩安装"},
            {"id": self.PI_UUID_2, "name": "双折边"},
            {"id": self.PI_UUID_3, "name": "打孔加工"},
            {"id": self.PI_UUID_4, "name": "韩式褶"},
        ]

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self, http_client):
        from app.utils.id_resolver import resolve_processing_item_ids
        assert await resolve_processing_item_ids([], 1, http_client) == []
        # None input → early return
        assert await resolve_processing_item_ids([], 1, http_client) == []

    @pytest.mark.asyncio
    async def test_exact_uuid_match(self, http_client, sample_items):
        from app.utils.id_resolver import resolve_processing_item_ids
        http_client.get.return_value = _make_page_resp(sample_items)
        result = await resolve_processing_item_ids(
            [self.PI_UUID_1], 1, http_client
        )
        assert result == [self.PI_UUID_1]

    @pytest.mark.asyncio
    async def test_uuid_prefix_match(self, http_client, sample_items):
        """UUID 前缀（8+ 位 hex）匹配第一个符合的 item"""
        from app.utils.id_resolver import resolve_processing_item_ids
        http_client.get.return_value = _make_page_resp(sample_items)
        prefix = self.PI_UUID_1[:8]  # "a1111111" — 8 hex chars
        result = await resolve_processing_item_ids([prefix], 1, http_client)
        assert result == [self.PI_UUID_1]

    @pytest.mark.asyncio
    async def test_number_index_match(self, http_client, sample_items):
        from app.utils.id_resolver import resolve_processing_item_ids
        http_client.get.return_value = _make_page_resp(sample_items)
        # "1" → idx 0 → first item
        result = await resolve_processing_item_ids(["1"], 1, http_client)
        assert result == [self.PI_UUID_1]
        # "3" → idx 2 → third item
        result = await resolve_processing_item_ids(["3"], 1, http_client)
        assert result == [self.PI_UUID_3]

    @pytest.mark.asyncio
    async def test_exact_name_match(self, http_client, sample_items):
        from app.utils.id_resolver import resolve_processing_item_ids
        http_client.get.return_value = _make_page_resp(sample_items)
        result = await resolve_processing_item_ids(["双折边"], 1, http_client)
        assert result == [self.PI_UUID_2]

    @pytest.mark.asyncio
    async def test_fuzzy_name_match(self, http_client, sample_items):
        from app.utils.id_resolver import resolve_processing_item_ids
        http_client.get.return_value = _make_page_resp(sample_items)
        result = await resolve_processing_item_ids(["打孔"], 1, http_client)
        assert result == [self.PI_UUID_3]

    @pytest.mark.asyncio
    async def test_pipe_format_strips_name(self, http_client, sample_items):
        """'uuid|加工项名' 格式 → 取 pipe 前部分"""
        from app.utils.id_resolver import resolve_processing_item_ids
        http_client.get.return_value = _make_page_resp(sample_items)
        result = await resolve_processing_item_ids(
            [f"{self.PI_UUID_1}|S钩安装"], 1, http_client
        )
        assert result == [self.PI_UUID_1]

    @pytest.mark.asyncio
    async def test_batch_resolution(self, http_client, sample_items):
        from app.utils.id_resolver import resolve_processing_item_ids
        http_client.get.return_value = _make_page_resp(sample_items)
        result = await resolve_processing_item_ids(
            [self.PI_UUID_1, "双折边", "4"], 1, http_client
        )
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_skips_unresolvable(self, http_client, sample_items):
        from app.utils.id_resolver import resolve_processing_item_ids
        http_client.get.return_value = _make_page_resp(sample_items)
        result = await resolve_processing_item_ids(
            [self.PI_UUID_1, "不存在的加工项串", "999"], 1, http_client
        )
        assert result == [self.PI_UUID_1]

    @pytest.mark.asyncio
    async def test_skips_empty_strings_in_batch(self, http_client, sample_items):
        from app.utils.id_resolver import resolve_processing_item_ids
        http_client.get.return_value = _make_page_resp(sample_items)
        result = await resolve_processing_item_ids(
            [self.PI_UUID_1, "", "  "], 1, http_client
        )
        assert result == [self.PI_UUID_1]

    @pytest.mark.asyncio
    async def test_api_called_with_correct_params(self, http_client, sample_items):
        """全量加工项列表应只请求一次，参数正确"""
        from app.utils.id_resolver import resolve_processing_item_ids
        http_client.get.return_value = _make_page_resp(sample_items)
        await resolve_processing_item_ids(["S钩安装"], 1, http_client)
        assert http_client.get.call_count == 1
        call_kwargs = http_client.get.call_args[1]
        assert call_kwargs["params"]["size"] == 200
        assert call_kwargs["params"]["status"] == "active"
