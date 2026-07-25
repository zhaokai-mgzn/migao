"""
Tests for app/api/routes.py — API route registration

Note: `app.api.routes` imports `app.api.asr` at module level,
which requires dashscope to be installed. The module-level import
is tested in the first test; subsequent tests drill into sub-modules
that are already verified by test_api_coverage.py.
"""
import pytest
from unittest.mock import MagicMock


class TestRouterModule:
    """验证 routes.py 模块导入和路由注册"""

    def test_routes_module_imports(self):
        """routes.py 可正常导入"""
        import app.api.routes as routes_mod
        assert routes_mod.router is not None

    def test_router_has_all_route_groups(self):
        """至少有 4 个路由组：chat/asr/upload/internal"""
        import app.api.routes as routes_mod
        assert len(routes_mod.router.routes) >= 4

    def test_asr_route_registered(self):
        """ASR 路由已注册并包含 transcribe 端点"""
        import app.api.routes as routes_mod
        # ASR router 包含 /api/chat/transcribe
        all_paths = []
        for route in routes_mod.router.routes:
            sub_routes = getattr(route, "routes", [])
            for sr in sub_routes:
                all_paths.append(getattr(sr, "path", ""))
        assert any("transcribe" in p for p in all_paths), f"transcribe not in: {all_paths}"

    def test_chat_routes_exist(self):
        """Chat 路由已注册"""
        import app.api.routes as routes_mod
        all_paths = []
        for route in routes_mod.router.routes:
            sub_routes = getattr(route, "routes", [])
            for sr in sub_routes:
                all_paths.append(getattr(sr, "path", ""))
        assert any("/chat/send" in p for p in all_paths), f"chat/send not in: {all_paths}"

    def test_prefix_is_set_on_chat(self):
        """Chat 路由带有 /chat 前缀"""
        import app.api.routes as routes_mod
        # include_router 的 prefix 参数体现在 route.path 中
        prefixes = [getattr(r, "path", "") for r in routes_mod.router.routes]
        assert any("chat" in p for p in prefixes), f"No /chat prefix found in {prefixes}"
