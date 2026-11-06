"""
ID 自动解析器 — LLM 传名称/序号/UUID/前缀都能正确转为 UUID。

设计原则：不要让 LLM 记住 UUID。LLM 传什么过来都能解析。
匹配优先级：UUID 精确匹配 → UUID 前缀 → 名称 → 序号（1-based）
→ 服务端 id 精确匹配（最后兜底：兼容非 UUID 的历史/种子 id，如 `p-zg-001`）

⚠️ **读写两条路径的失败语义不同，解析器也必须分家**（issue #8788）：
`resolve_product_id()` 是**只读**口径 —— 允许「名称模糊命中多条 ⇒ 取第一条」，因为查错商品的
代价只是「没找到，再搜一次」；`resolve_unique_product_id()` 是**写**口径 —— 只接受
**唯一确定**的结果，命中多条/不命中一律拒绝（见该函数的 docstring）。
⇒ 写工具**不许**调用前者。
"""

import re
import logging
from typing import NamedTuple, Optional

logger = logging.getLogger(__name__)

# UUID v4 格式: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)
# LLM 可能截断 UUID: 至少 8 位十六进制
UUID_PREFIX_PATTERN = re.compile(r'^[0-9a-f]{8,}$', re.IGNORECASE)
# 纯数字 = 序号
NUMBER_PATTERN = re.compile(r'^\d+$')


async def resolve_product_id(
    raw: str,
    tenant_id: int,
    http_client,
) -> Optional[str]:
    """解析商品 ID：支持 UUID / 名称 / 序号 / UUID 前缀。

    Args:
        raw: LLM 传入的原始值
        tenant_id: 租户 ID
        http_client: AdminApiClient 实例

    Returns:
        解析后的 UUID，或 None
    """
    if not raw or not raw.strip():
        return None
    raw = raw.strip()

    # 1. 精确 UUID
    if UUID_PATTERN.match(raw):
        return raw

    # 2. UUID 前缀 — 直接去服务端查
    if UUID_PREFIX_PATTERN.match(raw) and len(raw) >= 8:
        resp = await http_client.get("/api/admin/products", params={
            "productId": raw, "page": 1, "size": 1
        }, tenant_id=tenant_id)
        products = (resp.get("data", {}) or {}).get("items", [])
        if products and len(products) == 1:
            return products[0].get("id")
        # 也可能是 UUID 前缀，尝试模糊匹配
        resp = await http_client.get("/api/admin/products", params={
            "keyword": raw, "page": 1, "size": 1
        }, tenant_id=tenant_id)
        products = (resp.get("data", {}) or {}).get("items", [])
        if products:
            pid = products[0].get("id", "")
            if pid and pid.startswith(raw[:min(16, len(raw))]):
                return pid

    # 3. 纯数字 → 1-based 序号
    if NUMBER_PATTERN.match(raw):
        idx = int(raw) - 1
        if idx >= 0:
            resp = await http_client.get("/api/admin/products", params={
                "page": idx + 1, "size": 1
            }, tenant_id=tenant_id)
            products = (resp.get("data", {}) or {}).get("items", [])
            if products:
                return products[0].get("id")

    # 4. 按名称搜索 — 精确匹配优先
    resp = await http_client.get("/api/admin/products", params={
        "keyword": raw, "page": 1, "size": 5
    }, tenant_id=tenant_id)
    products = (resp.get("data", {}) or {}).get("items", [])
    if products:
        # 精确名称匹配
        for p in products:
            if p.get("name") == raw:
                return p.get("id")
        # 模糊匹配：取第一个
        return products[0].get("id")

    # 5. 服务端 id 精确匹配 —— 兼容**非 UUID 的历史/种子 id**（如 demo-seed 的 `p-zg-001`）。
    #    admin-api 的 `productId` 是**精确**过滤（ProductService.buildProductQueryWrapper 用
    #    `eq(Product::getId, ...)`），所以传一个名字只会拿到空集、不会误命中别的商品。
    #    为什么放在最后：它是**多一次**服务端往返，只在前面全部落空时才付这个成本；
    #    放在前面虽然也能工作，但每次按名称查详情都要多一次调用。
    #    注意：只走 query 参数，**不**把 raw 拼进 `/products/{raw}` —— 那是 issue #8783 的 bug 形态。
    resp = await http_client.get("/api/admin/products", params={
        "productId": raw, "page": 1, "size": 1
    }, tenant_id=tenant_id)
    products = (resp.get("data", {}) or {}).get("items", [])
    for p in products:
        if p.get("id") == raw:
            return raw

    return None


class ProductResolution(NamedTuple):
    """写路径的严格解析结果 —— **只有** `status == "ok"` 才允许发写请求。

    status 四态（缺一不可，都是「拒绝写」的不同理由，话术不同）：
    - `ok`         唯一确定，`product_id` 为可直接写进 URL 的真实 id；
    - `ambiguous`  命中多条（含重名）⇒ **绝不写**，把 `candidate_count` / `candidates` 交给调用方回给模型；
    - `not_found`  一条都没命中 ⇒ 不写；
    - `unavailable` 列表查询本身失败 ⇒ 不写，但**不许**说成「商品不存在」（那是另一件事）。
    """

    status: str
    product_id: Optional[str] = None
    candidate_count: int = 0
    candidates: tuple = ()


#: 写路径名称候选的取数上限。唯一性必须在**有界**候选集上判定：打满上限仍有多条 ⇒
#: 一律按「多条」拒绝 —— **绝不**因为截断而把「多条」误判成「唯一」。
NAME_CANDIDATE_LIMIT = 20


def _list_items(resp) -> list:
    """从 admin-api 的列表响应里取 items（形状不对 ⇒ 空列表，交给调用方判 unavailable/not_found）。"""
    data = (resp or {}).get("data") or {}
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


async def resolve_unique_product_id(
    raw: str,
    tenant_id: int,
    http_client,
) -> ProductResolution:
    """**写路径专用**的严格解析：只有唯一确定的商品才返回 `ok`（issue #8788）。

    与只读的 `resolve_product_id()` 的三条硬差别（写错商品的代价**不可逆**）：

    1. **名称命中多条 ⇒ `ambiguous`**，绝不取第一条（只读面允许，写面禁止）；
    2. **没有「模糊包含取第一条」的兜底**，也不把 skuCode 命中当商品名命中；
    3. 入参本身是 id ⇒ 直通，不做名称解析：UUID **零 HTTP**；非 UUID 的真实 id
       （`docs/deployment/demo-seed.sql` 的 `p-zg-001` 等）用 `productId` **精确** eq 探测一次。

    为什么写工具不直接把原值交给服务端（那里其实有一段 `ProductService.resolveProductId`）：
    它的第 5 步是 `getName().contains(raw) ⇒ 取第一条` ⇒ **写哪一件商品由"谁先被查到"决定**，
    正是「改错商品」的入口。本函数保证发出去的 `{id}` 永远是一个**已确定**的真实 id。

    Args:
        raw: LLM 传入的原始值（名称 / 序号 / UUID / 非 UUID 真实 id）
        tenant_id: 租户 ID（每次查询都带，跨租户不可能命中）
        http_client: AdminApiClient 实例

    Returns:
        `ProductResolution`；调用方只允许在 `status == "ok"` 时发写请求。
    """
    if raw is None or not str(raw).strip():
        return ProductResolution("not_found")
    raw = str(raw).strip()

    # 1. 精确 UUID —— 本身就是唯一 id，**零 HTTP**（负控：合法 id 直传不多一次往返）
    if UUID_PATTERN.match(raw):
        return ProductResolution("ok", raw)

    # 2. 纯数字 = 1-based 序号 —— 服务端 size=1，结果唯一或空（不存在"命中多条"）
    if NUMBER_PATTERN.match(raw):
        idx = int(raw) - 1
        if idx < 0:
            return ProductResolution("not_found")
        resp = await http_client.get("/api/admin/products", params={
            "page": idx + 1, "size": 1
        }, tenant_id=tenant_id)
        if (resp or {}).get("success") is False:
            return ProductResolution("unavailable")
        items = _list_items(resp)
        if items and items[0].get("id"):
            return ProductResolution("ok", items[0]["id"])
        return ProductResolution("not_found")

    # 3. 非 UUID 的真实 id（种子/历史数据）—— **精确** `eq(id)`，命中即直通。
    #    为什么放在名称之前：写路径上「这串东西可能是个 id」必须先排除，否则真实 id 会被
    #    当成名称去搜（搜不到 ⇒ 把**存在的商品**判成不存在，等于用修 bug 的方式造新 bug）。
    #    这一步**只**查 productId（精确），绝不查 keyword ⇒ 不会产生任何模糊候选。
    resp = await http_client.get("/api/admin/products", params={
        "productId": raw, "page": 1, "size": 1
    }, tenant_id=tenant_id)
    if (resp or {}).get("success") is False:
        return ProductResolution("unavailable")
    if any(p.get("id") == raw for p in _list_items(resp)):
        return ProductResolution("ok", raw)

    # 4. 名称 —— 在**有界候选集**上判唯一；命中多条 ⇒ ambiguous（**绝不**取第一条）
    resp = await http_client.get("/api/admin/products", params={
        "keyword": raw, "page": 1, "size": NAME_CANDIDATE_LIMIT
    }, tenant_id=tenant_id)
    if (resp or {}).get("success") is False:
        return ProductResolution("unavailable")
    # keyword 同时搜 name **和** skuCode（见 ProductService.buildProductQueryWrapper）
    # ⇒ 必须按名称再筛一次：货号命中不是「商品名命中」，拿它写商品同样是猜。
    named = [p for p in _list_items(resp) if raw in (p.get("name") or "")]
    exact = [p for p in named if p.get("name") == raw]
    pool = exact or named
    if len(pool) == 1 and pool[0].get("id"):
        return ProductResolution("ok", pool[0]["id"])
    if len(pool) > 1:
        return ProductResolution(
            "ambiguous", None, len(pool),
            tuple((p.get("name") or "") for p in pool[:5]),
        )
    return ProductResolution("not_found")


async def resolve_processing_item_ids(
    raw_ids: list,
    tenant_id: int,
    http_client,
) -> list[str]:
    """批量解析加工项 ID：支持 UUID / 名称 / 序号 / UUID 前缀。

    Args:
        raw_ids: LLM 传入的原始 ID 列表（可能含名称/序号/UUID）
        tenant_id: 租户 ID
        http_client: AdminApiClient 实例

    Returns:
        解析后的 UUID 列表（跳过无法解析的项）
    """
    if not raw_ids:
        return []

    # 获取全量加工项列表（数量不大，一次性获取用于序号/名称匹配）
    resp = await http_client.get("/api/admin/processing-items", params={
        "page": 1, "size": 200, "status": "active"
    }, tenant_id=tenant_id)
    all_items = (resp.get("data", {}) or {}).get("items", [])

    resolved = []
    for raw in raw_ids:
        if not raw or not str(raw).strip():
            continue
        raw = str(raw).strip()

        # 兼容 "pi_xxx|加工项名" 格式
        if "|" in raw:
            raw = raw.split("|")[0].strip()

        found = None

        # 1. 精确 UUID
        if UUID_PATTERN.match(raw):
            found = raw

        # 2. UUID 前缀
        elif UUID_PREFIX_PATTERN.match(raw) and len(raw) >= 8:
            prefix = raw[:min(16, len(raw))]
            for item in all_items:
                if item.get("id", "").startswith(prefix):
                    found = item["id"]
                    break

        # 3. 纯数字 → 1-based 序号
        elif NUMBER_PATTERN.match(raw):
            idx = int(raw) - 1
            if 0 <= idx < len(all_items):
                found = all_items[idx].get("id")

        # 4. ID 精确匹配（_auto_resolve_ids 可能已解析为短 ID）
        if not found:
            for item in all_items:
                if item.get("id") == raw:
                    found = item["id"]
                    break

        # 5. 名称匹配（精确 > 前缀）
        if not found:
            for item in all_items:
                if item.get("name") == raw:
                    found = item["id"]
                    break

        if not found:
            # 6. 名称包含匹配
            for item in all_items:
                if raw in (item.get("name") or ""):
                    found = item["id"]
                    break

        if found:
            resolved.append(found)
        else:
            logger.warning(f"[id-resolver] Cannot resolve processing_item_id: {raw}")

    return resolved
