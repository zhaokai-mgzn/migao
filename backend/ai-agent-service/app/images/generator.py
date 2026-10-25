"""商品图生成内核（issue #7335）——MaaS 图生图（qwen-image 系列）。

## 它做什么

商家在建品页上传一张**样图**（色卡 / 面料实拍 / 场景照），选一个用途
（`main` 主图 / `texture` 材质 / `craft` 工艺 / `scene` 场景），本模块把
「样图 + 按用途生成的提示词」发给 MaaS 多模态生图接口，返回**一张** 1440×1440 图片的
临时 URL（供应方 OSS，24h 过期）与模型名。

## 边界

1. 🔴 **不下载、不落盘、不落库**：只回 `{"image_url", "model"}`；转存 OSS 与
   「是否采用」都在 admin-api / 商家页面（与 `vision` 的 `TestNoWriteBoundary` 同口径）。
2. 🔴 **模型可轮换**：`IMAGE_GEN_MODELS` 按顺序尝试；只有**配额类**错误
   （429 / `AllocationQuota` / `Throttling` / free tier）与**模型不可用**
   （ModelNotFound / UnsupportedModel / HTTP 400 InvalidParameter）才切下一个 —— 其它错误直接上抛，
   不把「提示词写错了」伪装成「换个模型试试」。
   🔴 **凭证 / 权限类错误（401 `InvalidApiKey` / 403 `AccessDenied`）例外：一次都不轮换**
   —— 账号级问题，同一个 Key 换模型还是 401，轮换只白烧请求与时间（2026-10-25 线上实测）。
   它归入 `ImageGenerationAuthError`（`ImageGenerationUnavailable` 的子类 ⇒ 对外 503 语义、不可重试）。
   ⚠️ **当前配置（用户 2026-10-24 裁定，issue #7661，见 app/config.py 的 `IMAGE_GEN_MODELS`）**：
   `qwen-image-3.0-pro`，端点 = MaaS token-plan 的原生多模态路径。历史坑（保留以免重犯）：
   2026-10-23 曾切到图片翻译模型（不接图生图载荷，issue #7341/#7538）⇒ 全链不可用时**必须**报
   `ImageGenerationUnavailable`（「模型不接这类请求」）而不是「额度用尽」—— 两者给商家的
   行动方向相反（等额度 vs 找平台换模型）。
3. 🔴 **缺 Key 即 fail-closed**：`IMAGE_GEN_API_KEY` 未配置且 `ASR_API_KEY` 也为空 ⇒
   `ImageGenerationUnavailable`（端点 503），**不发任何外部请求**。
"""
from __future__ import annotations

from typing import Dict, List, Optional

import httpx
from loguru import logger

from app.config import settings

KINDS = ("main", "texture", "craft", "scene")


class ImageGenerationError(Exception):
    """生图失败（对外 502/422 的可读理由）。"""


class ImageGenerationUnavailable(ImageGenerationError):
    """开关关闭 / 未配置 Key / 全链都接不了这类请求（对外 503，不重试、不回落）。

    `code` = 503 响应体的**机器可读**失败码（issue #7552）：admin-api 据此分叉话术，
    不再从中文 detail 里猜成因。默认值 = 「模型接不了这类请求」，开关 / 缺 Key 用显式 code。
    """

    code = "IMAGE_GEN_MODEL_UNSUPPORTED"

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        if code:
            self.code = code


class ImageGenerationQuotaExceeded(ImageGenerationError):
    """配置的所有模型都因配额不可用（对外 503 + 可行动 suggestion）。"""

    code = "IMAGE_GEN_QUOTA_EXCEEDED"


class ImageGenerationAuthError(ImageGenerationUnavailable):
    """生图服务**凭证 / 权限**失效（HTTP 401 `InvalidApiKey` / 403 `AccessDenied`）。

    归到「不可用」这一族（对外 503 语义、**不可重试**），而不是「这次没成功、再试一次」：
    Key 无效时重试永远不会成功（2026-10-25 线上实测：现役 MaaS key 打真实端点回 401
    `InvalidApiKey`，端点可达）。与「配额用尽」也**不冒充** —— 等额度解决不了凭证问题。

    为什么不复用父类直接抛：本类在 `generate_product_image` 的轮换循环里**立即上抛**
    （账号级问题，换模型同一个 Key 还是 401），而普通 `ImageGenerationUnavailable`
    （模型接不了这类请求）仍需继续试下一个模型。
    """

    # 对外失败码（issue #7552）复用「凭证不可用」这一格：与「未配置 Key」同属**平台侧**凭证问题，
    # 商家的下一个动作相同（找平台换 Key，别重试）；不新增第五个码（与 #7680 的码位口径一致）。
    # detail 里仍如实写明「生图凭证无效（HTTP 401/403）：InvalidApiKey」。
    code = "IMAGE_GEN_NO_KEY"


#: 按商品名里的品类给「主图」一个**贴近真实用途**的场景（不按名称硬编码商品，只选场景）。
_SCENES = (
    ("卷帘", "安装在现代厨房窗上的整幅卷帘"),
    ("罗马杆", "安装在现代客厅窗顶的金属窗帘杆"),
    ("帘头", "安装在现代客厅窗顶的帘头"),
    ("幔", "安装在现代客厅窗顶的帘头"),
    ("纱", "挂在明亮客厅落地窗前的整幅纱帘"),
    ("面料", "自然垂坠陈列的面料"),
    ("布帘", "挂在现代客厅落地窗前的整幅布帘"),
    ("窗帘", "挂在现代客厅落地窗前的整幅窗帘"),
)

_COMMON = "保持参考图里的真实颜色、纹理与材质，画面干净、无水印、无文字、无logo，正方形构图"

_PROMPTS = {
    "main": "以参考图里的这款商品（{name}）为准，生成一张商品主图：{scene}，{common}。",
    "texture": "以参考图里的这款商品（{name}）为准，生成一张商品详情图：材质微距特写，"
               "能看清表面织纹与纱线肌理，侧光显出立体感，摄影棚布光，{common}。",
    "craft": "以参考图里的这款商品（{name}）为准，生成一张商品详情图：做工与结构细节特写"
             "（褶皱 / 包边 / 缝线 / 五金 / 卷轴等与商品相符的工艺），缝线平整，摄影棚级商品图，{common}。",
    "scene": "以参考图里的这款商品（{name}）为准，生成一张商品详情图：在家居空间里的实际使用效果，"
             "自然光，温暖真实的氛围，{common}。",
}


def _scene_for(product_name: str) -> str:
    for keyword, scene in _SCENES:
        if keyword in (product_name or ""):
            return scene
    return "挂在现代客厅落地窗前的整幅商品"


def build_prompt(product_name: str, kind: str) -> str:
    """按用途生成提示词（`kind` 非白名单 ⇒ ValueError，调用方 bug 不降级）。"""
    if kind not in _PROMPTS:
        raise ValueError(f"kind 只能是 {'/'.join(KINDS)}，收到 {kind!r}")
    return _PROMPTS[kind].format(
        name=(product_name or "").strip() or "这款商品",
        scene=_scene_for(product_name),
        common=_COMMON,
    )


def _models() -> List[str]:
    return [m.strip() for m in (settings.IMAGE_GEN_MODELS or "").split(",") if m.strip()]


def _api_key() -> str:
    # 与语音同一个 MaaS 账号：IMAGE_GEN_API_KEY 显式配优先，否则复用 ASR_API_KEY。
    # 不回落 PRIMARY_API_KEY —— 那是 DeepSeek 的 Key（主推理不动），打到 MaaS 只会 invalid_api_key。
    return (settings.IMAGE_GEN_API_KEY or settings.ASR_API_KEY or "").strip()


def _is_quota(data: Dict, status: int) -> bool:
    if status == 429:
        return True
    code = str(data.get("code") or "")
    message = str(data.get("message") or "")
    return any(k in code or k in message for k in (
        "AllocationQuota", "Throttling", "FreeTier", "free tier", "quota", "Quota", "limit",
    ))


def _is_model_unavailable(data: Dict, status: int) -> bool:
    """该模型**接不了这类请求** ⇒ 切下一个（不是我们的输入错，也不是配额）。

    实测（issue #7341）：图片翻译类模型（2026-10-23 的默认链，已于 2026-10-24 退役）对多模态图生图的
    `messages` 载荷回 **HTTP 400 + InvalidParameter**，旧逻辑把它当「其它错误」直接上抛
    ⇒ 回落链在它这里整条断掉，后面的可用模型永远轮不到。
    只对 400 + InvalidParameter 放宽：内容审核类 400（DataInspectionFailed）不切模型
    —— 换个模型重试只会把同一张违规图再送一遍。
    """
    code = str(data.get("code") or "")
    message = str(data.get("message") or "")
    if any(k in code or k in message for k in ("ModelNotFound", "model not found", "UnsupportedModel")):
        return True
    return status == 400 and "InvalidParameter" in code


def _is_auth_failure(data: Dict, status: int) -> bool:
    """凭证 / 权限失败 ⇒ **账号级、不可重试**（也不许换模型重试）。

    形态来源 = 2026-10-25 线上实测：现役 MaaS key 打真实端点回
    `HTTP 401 {"code": "InvalidApiKey", "message": "Invalid API-key provided."}`（0.48s，端点可达）。
    这类错误此前落进「其它错误」分支 ⇒ 对外等价于「这次没成功，**再生成一次**」，
    而真实动作是「平台侧换 Key」⇒ 给商家的方向正好反了（重试永远不会成功）。
    """
    code = str(data.get("code") or "")
    message = str(data.get("message") or "")
    if status in (401, 403):
        return True
    return any(k in code or k in message for k in (
        "InvalidApiKey", "invalid_api_key", "Unauthorized", "AccessDenied", "SignatureDoesNotMatch",
    ))


def _extract_image(data: Dict) -> Optional[str]:
    message = ((data.get("output") or {}).get("choices") or [{}])[0].get("message") or {}
    content = message.get("content")
    items = content if isinstance(content, list) else [content]
    for item in items:
        if isinstance(item, dict) and item.get("image"):
            return item["image"]
    return None


async def _request_one(model: str, prompt: str, image_url: str, client: httpx.AsyncClient) -> str:
    """调一次百炼；成功返回图片 URL，失败抛 ImageGenerationError（配额/模型不可用单独标注）。"""
    body = {
        "model": model,
        "input": {"messages": [{"role": "user", "content": [
            {"image": image_url},
            {"text": prompt},
        ]}]},
        "parameters": {"size": "1440*1440", "watermark": False, "n": 1},
    }
    resp = await client.post(
        settings.IMAGE_GEN_BASE_URL,
        headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
        json=body,
    )
    try:
        data = resp.json()
    except Exception:
        data = {"message": resp.text[:300]}

    if resp.status_code != 200 or data.get("output") is None:
        # 凭证/权限优先判：账号级问题既不是配额、也不该被当成「这次运气不好」（顺序有意义）
        if _is_auth_failure(data, resp.status_code):
            raise ImageGenerationAuthError(
                f"{model}: 生图凭证无效（HTTP {resp.status_code}）："
                f"{data.get('code') or data.get('message')}")
        if _is_quota(data, resp.status_code):
            raise ImageGenerationQuotaExceeded(f"{model}: {data.get('code') or data.get('message')}")
        if _is_model_unavailable(data, resp.status_code):
            raise ImageGenerationUnavailable(f"{model}: {data.get('code') or data.get('message')}")
        raise ImageGenerationError(
            f"{model} 生图失败（HTTP {resp.status_code}）：{data.get('code') or data.get('message')}")

    url = _extract_image(data)
    if not url:
        raise ImageGenerationError(f"{model} 响应里没有图片：{str(data)[:200]}")
    return url


async def generate_product_image(
    image_url: str,
    product_name: str,
    kind: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, str]:
    """样图 → 一张商品图：返回 `{"image_url", "model"}`（不落盘、不落库）。"""
    if not settings.IMAGE_GEN_ENABLED:
        raise ImageGenerationUnavailable(
            "商品图生成未启用（IMAGE_GEN_ENABLED=false）", code="IMAGE_GEN_DISABLED")
    if not _api_key():
        raise ImageGenerationUnavailable(
            "未配置 IMAGE_GEN_API_KEY / ASR_API_KEY", code="IMAGE_GEN_NO_KEY")
    if not (image_url or "").startswith(("http://", "https://")):
        raise ValueError("image_url 必须是 http(s) 图片地址")

    prompt = build_prompt(product_name, kind)
    models = _models()
    if not models:
        raise ImageGenerationUnavailable("IMAGE_GEN_MODELS 为空")

    owned = client is None
    http_client = client or httpx.AsyncClient(timeout=settings.IMAGE_GEN_TIMEOUT)
    reasons: List[str] = []
    quota_hit = False
    try:
        for model in models:
            try:
                url = await _request_one(model, prompt, image_url, http_client)
                logger.info(f"[image-gen] ok model={model} kind={kind} product={product_name!r}")
                return {"image_url": url, "model": model}
            except ImageGenerationAuthError:
                # 账号级凭证问题：换 `IMAGE_GEN_MODELS` 里下一个模型还是 401 ⇒ 不空转、立即上抛
                raise
            except ImageGenerationQuotaExceeded as e:
                quota_hit = True
                reasons.append(str(e))
                logger.warning(f"[image-gen] quota exhausted, next model: {e}")
            except ImageGenerationUnavailable as e:
                reasons.append(str(e))
                logger.warning(f"[image-gen] model unavailable, next model: {e}")
        detail = "；".join(reasons) or "无"
        if quota_hit:
            raise ImageGenerationQuotaExceeded(
                f"生图额度已用尽（{len(models)} 个模型均不可用）：{detail}")
        # 全部模型都「接不了这类请求」≠ 额度用尽：2026-10-23 起的默认链正是这种形态
        # （图片翻译模型不接图生图，issue #7341；该模型已于 2026-10-24 退役，issue #7661）。理由必须是真的 ——
        # 说成「额度用尽」会把商家引向「等额度」，而真正的动作是「找平台换回可用模型」。
        raise ImageGenerationUnavailable(
            f"生图模型不可用：配置的 {len(models)} 个模型都不接这类图生图请求（非配额原因）：{detail}")
    finally:
        if owned:
            await http_client.aclose()
