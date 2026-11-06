"""写路径「商品引用解析失败」的**统一出口**（issue #8788）。

只读面的解析失败可以是「没找到，请用 product_search 再搜一次」；**写**面不是 ——
改错商品**不可逆**，所以写路径只有两种结局：**唯一确定 ⇒ 照写**，或**拒绝 ⇒ 零写请求**。
本模块只把 `ProductResolution` 翻译成给模型看的话术，**不做任何匹配/猜测**（零网络、零 IO）。

⚠️ 三条不许改的口径（每条都有判据钉住，见 `backend/ai-agent-service/tests/test_write_path_id_resolution.py`）：

1. 「命中多条」与「不命中」的**话术必须不同** —— 混成一句「未找到」会让模型反复重试同一个名称；
2. 每条都必须写明 **未执行修改** —— 写工具的半成功话术（「已帮你改价」）就是数据事故的开端；
3. 只有 `ambiguous` 才列候选；`not_found` 不编候选。
"""

from app.tools.base import ToolResult
from app.utils.id_resolver import ProductResolution


def product_ref_failure(resolution: ProductResolution, raw: str) -> ToolResult:
    """把「写路径解析不唯一/不存在」翻译成 fail-closed 的 ToolResult（**未执行修改**）。"""
    if resolution.status == "ambiguous":
        listed = "、".join(f"「{name}」" for name in resolution.candidates)
        return ToolResult(
            success=False,
            error="商品不唯一",
            message=(f"「{raw}」匹配到 {resolution.candidate_count} 个商品（{listed}），"
                     f"未执行修改"),
            suggestion=(
                "匹配到多个商品，写操作不会替你挑一个。请先用 product_search 按名字搜出候选，"
                "把候选给商家确认后，用**该商品的 id** 重新调用本工具"
            ),
        )

    if resolution.status == "unavailable":
        return ToolResult(
            success=False,
            error="商品查询失败",
            message=f"查询「{raw}」对应的商品失败，未执行修改",
            suggestion="商品查询接口本次失败（不是「商品不存在」）：请稍后用同样的入参重试一次，仍失败则如实告知商家系统繁忙",
        )

    return ToolResult(
        success=False,
        error="商品不存在",
        message=f"未找到商品「{raw}」，未执行修改",
        suggestion=(
            "未找到该商品：请用 product_search 按名字搜出候选并提供给商家确认；"
            "不要重复提交同一个名称，也不要凭印象编一个 id"
        ),
    )
