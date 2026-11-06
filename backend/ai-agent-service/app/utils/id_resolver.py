"""
ID 自动解析器 — LLM 传名称/序号/UUID/前缀都能正确转为 UUID。

设计原则：不要让 LLM 记住 UUID。LLM 传什么过来都能解析。
匹配优先级：UUID 精确匹配 → UUID 前缀 → 名称 → 序号（1-based）
→ 服务端 id 精确匹配（最后兜底：兼容非 UUID 的历史/种子 id，如 `p-zg-001`）
"""

import re
import logging
from typing import Optional

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
