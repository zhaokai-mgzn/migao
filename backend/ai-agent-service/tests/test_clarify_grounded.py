"""
图片澄清候选 grounded — 关键词提取纯函数测试（issue #2799）

覆盖 extract_search_keywords / pick_primary_keyword：
- 面料材质/颜色/风格提取
- 颜色名去"色"、行业色号处理
- 停用词过滤、去重、上限
- 无可提取内容兜底
"""
# case_ids: CH-018, CH-020

import pytest

from app.graph.clarify_grounded import (
    extract_search_keywords,
    pick_primary_keyword,
)


class TestExtractSearchKeywords:
    """从 vision 文本提取可检索关键词"""

    def test_extracts_fabric_and_color(self):
        kws = extract_search_keywords("图片中是雪尼尔面料的窗帘，米白色")
        assert "雪尼尔" in kws
        assert "米白" in kws  # 米白色 → 米白

    def test_multi_color_extraction(self):
        kws = extract_search_keywords("颜色有米白色和浅灰色，材质是棉麻")
        assert "棉麻" in kws
        assert "米白" in kws
        assert "浅灰" in kws

    def test_style_keywords(self):
        kws = extract_search_keywords("这是现代简约风格的窗帘，涤纶材质")
        assert "涤纶" in kws
        assert any(k in kws for k in ("现代", "简约"))

    def test_color_with_industry_code(self):
        # "2699-01 白色" → 白色（颜色部分）；纯描述应保留可检索词
        kws = extract_search_keywords("色号 2699-01 白色，遮光面料")
        assert "遮光" in kws
        assert "白" in kws  # 白色 → 检索词 '白'（product_search 模糊匹配可命中）

    def test_stopwords_filtered(self):
        kws = extract_search_keywords("图片看起来像是窗帘的布料")
        # "图片/窗帘/面料/布料/看起来" 均为停用词
        assert kws == []

    def test_dedup_and_cap(self):
        text = "雪尼尔材质，" + "米白色，" * 10 + "浅灰色"
        kws = extract_search_keywords(text)
        assert kws.count("米白") <= 1
        assert len(kws) <= 5

    def test_empty_and_none_input(self):
        assert extract_search_keywords("") == []
        assert extract_search_keywords(None) == []


class TestPickPrimaryKeyword:
    """主检索词选择：材质优先"""

    def test_fabric_preferred_over_color(self):
        assert pick_primary_keyword("雪尼尔窗帘，米白色") == "雪尼尔"

    def test_color_when_no_fabric(self):
        assert pick_primary_keyword("米白色的窗帘") == "米白"

    def test_none_when_unsearchable(self):
        assert pick_primary_keyword("图片里的窗帘") is None
