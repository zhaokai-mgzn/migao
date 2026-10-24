"""出站文本的**内部路由清洗**（issue #7236）。

故障现场（2026-10-18 用户实测，黄金策 B 端 session `sess_742201cbf83f4f58`）：assistant 正文
把内部前端路由当展示文案上屏 —— 『发货需要在后台「销售订单」页**（`/orders` 形态）**找到该订单』
（该页 2026-10-20 由「订单列表」正名为「销售订单」，issue #7354 —— 引文按现行页名书写）——
商家看不懂那个技术路径。两层治：① 源头话术只写中文页面名；② **本模块 = 出站兜底**
（纯函数，接在落库 / SSE 下发 / 历史回放之前，防模型抄旧话术、防历史行带出）。

确定性规则（可逐条复算）：
  1. 括号包住的前端路由（半角括号 / 全角括号 / 括号内可带空白）⇒ **整段删除**（含括号）；
  2. markdown 链接（方括号标签 + 圆括号内的路由）⇒ 只留标签（内部路由不得变成可点链接）；
  3. 删除点两侧的空白规整：两侧**都是中文**（含中文标点）⇒ 直接相连、不留空格；
     否则保留**恰好 1 个**空格（英文单词不粘连，原本没有空白也补 1 个）；
  4. 幂等：清洗结果再跑一次逐字不变。

刻意**不动**（负控，「说代码」不是展示文案）：` ``` 围栏 ``` `/ 行内反引号内的文本、
URL（`http(s)://…`）、业务斜杠（`¥29/米` / `定高买宽/定宽买高`）—— 后者根本不匹配路由形态。

只做「不泄露」：不做「把路由替换成可点链接」的能力（本期裁定）。
"""

import re

#: 前端路由 token：以 `/` 开头的 ASCII 路径段（不含空白/括号/中文）。
_ROUTE = r"/[a-zA-Z][a-zA-Z0-9/_-]*"

#: markdown 链接（内部路由）：标签只留文字，括号内的路由整段丢弃。先于括起形态处理。
_MD_ROUTE_LINK_RE = re.compile(r"\[([^\[\]\n]{1,40})\]\([ \t]*" + _ROUTE + r"[ \t]*\)")

#: 括起的路由：半角/全角括号 + 括号内允许空白 ⇒ 整段删除。
_PAREN_ROUTE_RE = re.compile(r"[（(][ \t]*" + _ROUTE + r"[ \t]*[)）]")

#: 代码片段（``` 围栏 / 行内反引号）——整段保护，一个字不动。
_CODE_SPLIT_RE = re.compile(r"(```[\s\S]*?```|`[^`\n]*`)")

#: 删除点占位符（Unicode 私用区；生产文本不会出现）。
_SENTINEL = "\ue000"

_CJK_RANGES = (
    (0x3000, 0x303F),   # CJK 标点（「」、。，等）
    (0x3400, 0x4DBF),   # 扩展 A
    (0x4E00, 0x9FFF),   # 基本汉字
    (0xF900, 0xFAFF),   # 兼容汉字
    (0xFF00, 0xFFEF),   # 全角形式
    (0x20000, 0x2FA1F),  # 扩展 B+
)


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def _merge_junctions(text: str) -> str:
    """把删除点两侧的空白按规则规整，并去掉删除点本身（规则 3）。"""
    out: list = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != _SENTINEL:
            out.append(text[i])
            i += 1
            continue
        while i < n and text[i] == _SENTINEL:   # 连续删除点合并成一处
            i += 1
        k = len(out) - 1
        while k >= 0 and out[k] in " \t":       # 左侧空白回退
            k -= 1
        left = out[k] if k >= 0 else ""
        del out[k + 1:]
        r = i
        while r < n and text[r] in " \t":       # 右侧空白跳过
            r += 1
        right = text[r] if r < n else ""
        if left and right and not (_is_cjk(left) and _is_cjk(right)):
            out.append(" ")                     # 非中文相邻 ⇒ 恰好 1 个空格
        i = r
    return "".join(out)


def _strip_outside_code(segment: str) -> str:
    """清洗一段**非代码**文本（代码片段由调用方切分保护）。"""
    previous = None
    while previous != segment:
        previous = segment
        segment = _MD_ROUTE_LINK_RE.sub(r"\1", segment)
        segment = _PAREN_ROUTE_RE.sub(_SENTINEL, segment)
    if _SENTINEL not in segment:
        return segment
    return _merge_junctions(segment)


def strip_internal_routes(text: str) -> str:
    """删掉展示文案里的内部前端路由（纯函数、幂等；规则见模块 docstring）。

    Args:
        text: 出站展示文本；None / 非字符串原样返回。

    Returns:
        清洗后的文本；已清洗文本再跑一次逐字不变。
    """
    if not text or not isinstance(text, str):
        return text
    parts = _CODE_SPLIT_RE.split(text)
    for idx in range(0, len(parts), 2):   # 偶数位 = 代码片段之外的展示文案
        parts[idx] = _strip_outside_code(parts[idx])
    return "".join(parts)
