# case_ids: MC-008
"""app/llm/__init__.py 导出契约测试

覆盖：LLM 基础设施层公共 API 导出完整性 + MiniMax 品牌清理（issue #2943）：
- LLMFactory / LLM_API_KEY / LLM_BASE_URL 等统一凭据导出
- 向后兼容别名（DASHSCOPE_* / MODEL_MAX 等）仍可用
- 旧 MINIMAX_* 命名已移除（防残留回潮）
"""
import pytest

import app.llm as llm_mod
from app.config import settings


class TestExports:
    """公共导出契约"""

    def test_core_exports_present(self):
        for name in (
            "LLMFactory",
            "select_model",
            "has_images",
            "MODEL_PRIMARY",
            "MODEL_FAST",
            "CostTracker",
            "MODEL_PRICING",
            "call_with_retry",
            "cost_tracker",
        ):
            assert hasattr(llm_mod, name), f"缺少导出 {name}"

    def test_llm_credentials_exported(self):
        """主 LLM 凭据统一导出（原 MINIMAX_* 语义，已去品牌命名 issue #2943）"""
        assert hasattr(llm_mod, "LLM_API_KEY")
        assert hasattr(llm_mod, "LLM_BASE_URL")
        # 与 settings 值一致（PRIMARY 优先 VISION 兜底）
        assert llm_mod.LLM_API_KEY == settings.LLM_API_KEY
        assert llm_mod.LLM_BASE_URL == settings.LLM_BASE_URL

    def test_dashscope_alias_kept(self):
        """DASHSCOPE_* 兼容别名保留（测试/旧代码 monkeypatch 依赖）"""
        assert llm_mod.DASHSCOPE_BASE_URL == settings.LLM_BASE_URL
        assert llm_mod.DASHSCOPE_MODEL == settings.LLM_MODEL

    def test_model_aliases_kept(self):
        assert llm_mod.MODEL_MAX == llm_mod.MODEL_PRIMARY
        assert llm_mod.MODEL_PLUS == llm_mod.MODEL_PRIMARY
        assert llm_mod.MODEL_LITE == llm_mod.MODEL_FAST
        assert llm_mod.MODEL_FLASH == llm_mod.MODEL_FAST

    def test_minimax_export_removed(self):
        """MiniMax 品牌命名已清理：不导出 MINIMAX_*（防残留回潮）"""
        for name in ("MINIMAX_API_KEY", "MINIMAX_BASE_URL"):
            assert not hasattr(llm_mod, name), f"残留导出 {name}"