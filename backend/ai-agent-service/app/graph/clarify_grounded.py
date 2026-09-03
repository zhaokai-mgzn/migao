"""
图片澄清候选 grounded 商户库 — 关键词提取（issue #2799）

轻量版 grounded（不引入向量/OCR，调研 §7 风险表）：vision 分析文本 → 提取
可检索关键词（颜色/材质/风格/名称）→ 供 product_search 命中真实商品 → 澄清
候选引用真实结果，不编造。

纯函数设计（可单测）：
- extract_search_keywords: 从 vision 文本提取候选检索关键词
- pick_primary_keyword: 挑 1 个最可能命中的主关键词（product_search 单次查询用）
"""

from __future__ import annotations

import re
from typing import List, Optional

# ── 面料材质词表（vision 识别常用，优先作为检索词）──
_FABRIC_KEYWORDS = (
    "雪尼尔", "棉麻", "涤纶", "绒布", "纱", "高精密", "真丝", "亚麻",
    "羊绒", "法兰绒", "天鹅绒", "提花", "绣花", "色织", "印花", "遮光",
)

# ── 颜色/风格泛词（颜色名常为"XX色"，风格多词）──
# 负向后顾排除"颜色/有色/染色"等非颜色名："XX色"前的字不能是 颜/有/染/着/配/上
_COLOR_PATTERN = re.compile(r"(?<![颜有染着配上])[\u4e00-\u9fa5]{1,4}色")
_STYLE_KEYWORDS = (
    "现代", "简约", "欧式", "中式", "北欧", "轻奢", "田园", "法式",
    "美式", "日式", "极简", "奶油风", "侘寂", "复古",
)

# ── 通用干扰词（"图片""窗帘"等太泛或 vision 描述词，不单独作检索词）──
_STOPWORDS = {
    "图片", "窗帘", "面料", "布料", "这个", "就是", "类似", "一样",
    "颜色", "材质", "风格", "款式", "感觉", "看起来", "花纹",
}

# 颜色名后缀（"米白"从"米白色"提取；行业色号如"2699-01 白色"取后部颜色名）
_MAX_KEYWORDS = 5


def _strip_color_name(color_token: str) -> str:
    """'米白色'→'米白'；'2699-01 白色'→'白色'；纯色号如'2699-01'返回原样。

    去除颜色名前误连的连接/动词词头（'有米白'→'米白'、'和浅灰'→'浅灰'）。
    """
    t = color_token.strip()
    while t and t[0] in "有和与或是及跟同":
        t = t[1:]
    if t.endswith("色"):
        return t[:-1]
    return t


def extract_search_keywords(vision_text: str) -> List[str]:
    """从 vision 分析文本提取可检索关键词（颜色/材质/风格）。

    策略（去重保序，上限 _MAX_KEYWORDS）：
    1. 面料材质词（优先，最可能命中商品名）
    2. 颜色名（'XX色' → 'XX'；含行业色号时尽量保留颜色部分）
    3. 风格词
    4. 过滤停用词

    Args:
        vision_text: vision LLM 的分析文本（自由描述）

    Returns:
        去重后的关键词列表；无可提取返回 []
    """
    if not vision_text:
        return []
    text = str(vision_text)
    seen: List[str] = []

    def _add(kw: str) -> None:
        kw = kw.strip()
        if not kw or kw in _STOPWORDS or kw in seen:
            return
        if len(kw) > 10:  # 过长非词
            return
        seen.append(kw)

    # 1. 面料材质（含"雪尼尔面料"等组合 → 取材质词本身）
    for fab in _FABRIC_KEYWORDS:
        if fab in text:
            _add(fab)

    # 2. 颜色名（'XX色' → 'XX'；行业色号 '2699-01 白色' 亦能匹配 '白色'）
    #    先剔除固定词"颜色/染色"避免误抓（后顾在字符串边界不生效）
    color_scan = text.replace("颜色", "  ").replace("染色", "  ")
    for m in _COLOR_PATTERN.finditer(color_scan):
        color_token = m.group(0)  # 如 "米白色"/"浅灰色"/"白色"
        _add(_strip_color_name(color_token))

    # 3. 风格词
    for sty in _STYLE_KEYWORDS:
        if sty in text:
            _add(sty)

    return seen[:_MAX_KEYWORDS]


def pick_primary_keyword(vision_text: str) -> Optional[str]:
    """挑 1 个主检索关键词。

    优先级：面料材质 > 颜色 > 风格（材质最可能出现在商品名/描述中）。
    供 product_search keyword 参数使用。

    Returns:
        主关键词或 None（无可检索内容）
    """
    kws = extract_search_keywords(vision_text)
    if not kws:
        return None
    # 第一个（材质优先，见 extract 顺序）
    return kws[0]
