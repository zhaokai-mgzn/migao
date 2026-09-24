"""页面上下文（issue #5371 · B 端能力地图族 4）。

route → 真值源登记表 + 默认拒绝的注入面。对外只暴露 `page_registry` 的公开 API。
"""

from app.context.page_registry import (
    CONTEXT_FIELDS,
    ENTITY_ID_RE,
    PAGE_CONTEXT_UNKNOWN_NOTICE,
    PAGE_REGISTRY,
    TRUTH_SOURCES,
    PageContext,
    PageEntry,
    TruthSource,
    build_page_context,
    context_field_names,
    has_permissions,
    normalize_entity_id,
    normalize_route,
    render_page_context,
    resolve_page_entry,
    resolve_truth_source,
)

__all__ = [
    "CONTEXT_FIELDS",
    "ENTITY_ID_RE",
    "PAGE_CONTEXT_UNKNOWN_NOTICE",
    "PAGE_REGISTRY",
    "TRUTH_SOURCES",
    "PageContext",
    "PageEntry",
    "TruthSource",
    "build_page_context",
    "context_field_names",
    "has_permissions",
    "normalize_entity_id",
    "normalize_route",
    "render_page_context",
    "resolve_page_entry",
    "resolve_truth_source",
]