"""图片管线：URL 校验 / CDN 重写 / 文本提示 —— **单一事实源**（issue #5321 包 1）。

## 为什么要抽出来

这三段规则此前只长在**对话路径**上（`app/api/chat.py` 的私有函数），页面入口
（建品页 / 建单页）无法独立使用 ⇒ 本模块把它抽成可复用服务，这是本能力真正的工程量所在。

对话路径改为**调用本模块**（`app/api/chat.py` 保留 `_validate_image_url` /
`_rewrite_image_url` / `_image_url_hint` 三个同名别名，语义逐字不变），
⇒ 同一张图在两条入口上过的是**同一段代码**，不会漂移。

## 边界（有意为之）

本模块**只做 URL 层**，不碰会话、不碰记忆、不碰 admin-api ⇒
页面路径可以在**没有会话**的情况下独立调用（静态面判据见
`backend/ai-agent-service/tests/test_vision_pipeline.py::TestPipelineIsNotCoupledToChatPath`）。
"""
from typing import Any, List

from app.config import settings


def validate_image_url(url: Any) -> bool:
    """校验图片 URL 格式（必须是 https:// 或 /api/files 开头）。

    非字符串（`None` / 数字）一律判无效，**不抛异常** —— 调用方来自前端 JSON，
    让一个脏值把整条链打挂是不划算的。
    """
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    return url.startswith("https://") or url.startswith("/api/files")


def rewrite_image_url(url: str) -> str:
    """将 CDN 域名图片 URL 重写为 OSS URL（由 IMAGE_URL_REWRITE_FROM/TO 配置）。

    两个配置**都**非空时才重写（只配一边 = 没配，原样返回）—— 与对话路径既有口径一致。
    """
    if not settings.IMAGE_URL_REWRITE_FROM or not settings.IMAGE_URL_REWRITE_TO:
        return url
    return url.replace(settings.IMAGE_URL_REWRITE_FROM, settings.IMAGE_URL_REWRITE_TO)


def image_url_hint(images) -> str:
    """把用户上传图片 URL 转成文本提示，供 LLM 在工具调用中直接引用（issue #3046）。

    仅做展示提示，不改变发送给 vision 的图像块；无效 URL 过滤、CDN 域名重写
    与 `normalize_image_urls` 保持同一规则。
    """
    valid = normalize_image_urls(images)
    if not valid:
        return ""
    joined = "；".join(valid)
    return f"\n\n[用户上传的图片（可直接引用 URL）：{joined}]"


def normalize_image_urls(images) -> List[str]:
    """页面路径与对话路径共用的**唯一**入口：一次做完「过滤无效 + CDN 重写」，保序。

    抽这段的动机：对话路径里「校验一次、重写一次」写在两处
    （`_convert_history_to_agent_format` 与 `send_message`）⇒ 再抄第三遍必然漂移。
    """
    if not images or not isinstance(images, (list, tuple)):
        return []
    return [rewrite_image_url(url) for url in images if validate_image_url(url)]