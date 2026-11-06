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

    status 五态（都是「拒绝写」的不同理由，话术各不相同）：
    - `ok`         唯一确定，`product_id` 为可直接写进 URL 的真实 id；
    - `ambiguous`  命中多条（含重名）⇒ 把 `candidate_count` / `candidates` 交回调用方；
    - `not_found`  一条都没命中；
    - `unsafe_ref` 入参形态**在写路径上不可信**（序号 / 无法证明唯一的 id 前缀），`detail` 说明原因；
    - `unavailable` 列表查询本身失败（不许说成「商品不存在」）。
    """

    status: str
    product_id: Optional[str] = None
    candidate_count: int = 0
    candidates: tuple = ()
    detail: str = ""


#: 写路径名称候选的取数上限。唯一性必须在**有界**候选集上判定：打满上限仍有多条 ⇒
#: 一律按「多条」拒绝 —— **绝不**因为截断而把「多条」误判成「唯一」。
NAME_CANDIDATE_LIMIT = 20

#: id 前缀扫描的页大小 / 页数上限。前缀在 admin-api 侧**没有**查询面（`productId` 精确、
#: `keyword` 只搜 name/skuCode）⇒ 只能翻页扫目录；扫不完（目录大于上限）⇒ **无法证明唯一**
#: ⇒ fail-closed 拒绝，绝不拿「扫到的第一条」当答案。
PREFIX_SCAN_PAGE_SIZE = 100
PREFIX_SCAN_MAX_PAGES = 5


def _list_page(resp) -> tuple:
    """→ (items, total)。形状不对 ⇒ ([], 0)。"""
    data = (resp or {}).get("data") or {}
    items = data.get("items") if isinstance(data, dict) else None
    total = data.get("total") if isinstance(data, dict) else None
    return (items if isinstance(items, list) else [],
            total if isinstance(total, int) else 0)


def _ambiguous(shape: str, hits: list) -> ProductResolution:
    """多条命中 ⇒ ambiguous（**绝不**取第一条）。`hits` 只用于展示，条数另算。"""
    return ProductResolution(
        "ambiguous", None, len(hits),
        tuple((h.get("name") or "") for h in hits[:5]),
    )


async def _resolve_id_prefix_strict(prefix: str, tenant_id: int, http_client) -> ProductResolution:
    """按 **id 前缀**严格解析：唯一才写，多条拒绝，扫不完 ⇒ 无法证明唯一（拒绝）。

    为什么不用 `?productId=<prefix>`：admin-api 的 `productId` 是**精确 eq**（见
    `ProductService.buildProductQueryWrapper`），前缀查不到；`keyword` 只搜 name/货号 ⇒
    唯一可行的是翻页扫目录。cost 只在前缀形态上付（名称/序号不付）。
    """
    matched: list = []
    scanned = 0
    total = 0
    for page in range(1, PREFIX_SCAN_MAX_PAGES + 1):
        resp = await http_client.get("/api/admin/products", params={
            "page": page, "size": PREFIX_SCAN_PAGE_SIZE
        }, tenant_id=tenant_id)
        if (resp or {}).get("success") is False:
            return ProductResolution("unavailable")
        items, total = _list_page(resp)
        scanned += len(items)
        matched.extend(p for p in items if (p.get("id") or "").startswith(prefix))
        if len(items) < PREFIX_SCAN_PAGE_SIZE:
            break
    else:
        if total > scanned:
            return ProductResolution(
                "unsafe_ref", detail=(
                    f"「{prefix}」是 id 前缀，而商品目录超过 {scanned} 件、本次没能扫完 "
                    f"⇒ 无法证明只有一个商品匹配"
                ),
            )

    if len(matched) == 1 and matched[0].get("id"):
        return ProductResolution("ok", matched[0]["id"])
    if len(matched) > 1:
        return _ambiguous("id 前缀", matched)
    return ProductResolution("not_found")


async def resolve_unique_product_id(
    raw: str,
    tenant_id: int,
    http_client,
) -> ProductResolution:
    """**写路径专用**的严格解析：只有唯一确定的商品才返回 `ok`（issue #8788）。

    与只读的 `resolve_product_id()` 的差别（写错商品的代价**不可逆**，只读面最坏是多查一次）：

    1. **序号一律拒绝**（`unsafe_ref`）：服务端的「序号」= 按创建时间排序的第 N 件 ⇒
       任何一次增删商品都会让它**漂移** ⇒「第 3 个」不是可信目标（写路径不接受"差不多"）；
    2. **id 前缀要求唯一**：8 位以上十六进制按前缀扫描目录，唯一才写、多条拒绝、
       扫不完 ⇒ 无法证明唯一（拒绝）；
    3. **名称要求唯一**：精确名称/名称片段命中多条 ⇒ 拒绝，**绝不**取第一条；
    4. 合法 id 直通：UUID **零 HTTP**；非 UUID 的真实 id（`docs/deployment/demo-seed.sql`
       的 `p-zg-001` 等）只做一次 `productId` **精确**探测。

    为什么写工具不直接把原值交给服务端（那里其实有一段 `ProductService.resolveProductId`）：
    它的第 2/4/5 步分别是「前缀取第一条」「序号」「名称 contains 取第一条」——
    写哪一件商品会取决于「谁先被查到」。本函数保证写 URL 里永远是一个**已确定**的真实 id。
    """
    if raw is None or not str(raw).strip():
        return ProductResolution("not_found")
    raw = str(raw).strip()

    # 1. 精确 UUID —— 本身就是唯一 id，**零 HTTP**（负控：合法 id 直传不多一次往返）
    if UUID_PATTERN.match(raw):
        return ProductResolution("ok", raw)

    # 2. 纯数字序号 —— **写路径一律拒绝**（零 HTTP）。服务端的序号 = 按创建时间排序的第 N 件，
    #    增删商品后漂移 ⇒ 同一个「3」今天是 A、明天是 B。用户说「第 3 个」不构成可信目标。
    if NUMBER_PATTERN.match(raw):
        return ProductResolution(
            "unsafe_ref", detail=(
                f"「{raw}」是商品序号：序号按创建时间排序，增删商品后会漂移，写操作不接受序号"
            ),
        )

    # 3. id 前缀（8 位以上十六进制，且不是完整 UUID）—— 唯一才写
    if UUID_PREFIX_PATTERN.match(raw) and 8 <= len(raw) <= 16:
        return await _resolve_id_prefix_strict(raw, tenant_id, http_client)

    # 4. 非 UUID 的真实 id（种子/历史数据）—— **精确** `eq(id)`，命中即直通。
    #    为什么放在名称之前：写路径上「这串东西可能是个 id」必须先排除，否则真实 id 会被
    #    当成名称去搜（搜不到 ⇒ 把**存在的商品**判成不存在，等于用修 bug 的方式造新 bug）。
    resp = await http_client.get("/api/admin/products", params={
        "productId": raw, "page": 1, "size": 1
    }, tenant_id=tenant_id)
    if (resp or {}).get("success") is False:
        return ProductResolution("unavailable")
    items, _ = _list_page(resp)
    if any(p.get("id") == raw for p in items):
        return ProductResolution("ok", raw)

    # 5. 名称 —— 在**有界候选集**上判唯一；命中多条 ⇒ ambiguous（**绝不**取第一条）
    resp = await http_client.get("/api/admin/products", params={
        "keyword": raw, "page": 1, "size": NAME_CANDIDATE_LIMIT
    }, tenant_id=tenant_id)
    if (resp or {}).get("success") is False:
        return ProductResolution("unavailable")
    items, _ = _list_page(resp)
    # keyword 同时搜 name **和** skuCode（见 ProductService.buildProductQueryWrapper）
    # ⇒ 必须按名称再筛一次：货号命中不是「商品名命中」，拿它写商品同样是猜。
    named = [p for p in items if raw in (p.get("name") or "")]
    exact = [p for p in named if p.get("name") == raw]
    pool = exact or named
    if len(pool) == 1 and pool[0].get("id"):
        return ProductResolution("ok", pool[0]["id"])
    if len(pool) > 1:
        return _ambiguous("名称", pool)
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
