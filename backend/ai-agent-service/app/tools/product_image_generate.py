"""
商品图生成工具（B 端黄金策，只读）——「对**已选商品**生成商品图」

商家说「给这个商品生成一张图 / 做张商品图 / 换张主图 / 出张材质图（工艺图 / 场景图）」时调用：
取该商品档案里的**主图**做样图，交给既有生图内核
（`backend/ai-agent-service/app/images/generator.py` 的 `generate_product_image`）生成一张新图，
回传卡载荷供前端预览（PC 下载 / 手机保存到相册）。

## 口径（用户 2026-10-23 裁定，issue #7541）

1. **入口 = 已选商品**：`product_id` 必填 —— 模型先用 `product_search` / `product_detail`
   定位到具体商品再调用；本工具**不做**商品搜索、也不从对话里猜商品。
2. **样图 = 该商品的 `mainImage`**（缺失时回退 `images[0]`；两者都无 ⇒ **可行动拒绝**，
   不凭空造图、不拿别的商品的图凑）。
3. **不写表单、不落库**：内核只回临时 URL，本工具把它交回对话卡；
   「用不用这张图」由商家在后台决定（转存 / 设为主图都不在这里）。
4. 🔴 **不新增第二套生图实现**：Key / 额度 / 模型轮换全部由既有内核承担
   （`IMAGE_GEN_MODELS` 轮换链与 `IMAGE_GEN_API_KEY` 的 fail-closed 都在那边），
   本工具只做「取样图 → 调内核 → 把失败语义如实翻成人话」。
5. 🔴 **失败语义必须如实**（不许互相冒充、不许静默）：

   ============================================  ==========================
   内核抛出                                        本工具错误码
   ============================================  ==========================
   `ImageGenerationUnavailable`（未配置 Key /      `IMAGE_GEN_UNAVAILABLE`
   开关关闭 / **模型接不了这类图生图请求**）
   `ImageGenerationAuthError`（凭证 / 权限失效：  `IMAGE_GEN_UNAVAILABLE`
   401 `InvalidApiKey` / 403 `AccessDenied`）      同码，但**话术里不给「再生成一次」**
   `ImageGenerationQuotaExceeded`（所有模型都因配额）`IMAGE_GEN_QUOTA_EXCEEDED`
   其它供应商失败                                    `IMAGE_GEN_FAILED`
   商品没有可用主图                                  `IMAGE_SOURCE_MISSING`
   ============================================  ==========================

   四种失败码都带可行动的 `suggestion`；用户可见 `message` **一律不说成「额度用尽」**
   （模型不接这类请求 / 凭证失效 都不等于额度没了 —— 这是本工具存在的理由之一）。
   凭证失效的出路与「这次没成功」正相反：**重试永远不会成功**（要平台换 Key），
   如实说成「能力用不了」而不是「再生成一次」（2026-10-25 线上实测 401 `InvalidApiKey`）。
6. **不新增 LLM 文案生成**：不写标题、不写卖点、不生成任何营销文案
   （文案类需求走 `marketing_poster`）。

卡片发射点：`app/api/chat.py::_detect_card_type` → `generated_image`；
`_should_send_card` 只在**成功且真有 `image_url`** 时发卡（失败 / 空图不发卡）。
跨端契约判据 = `tests/test_card_type_cross_end_contract.py`。

权限：`GET /api/admin/products/{id}` 的读码 `product:list`（与 `product_detail` 同码）。
只读、仅 B 端（`c_end_reachable=False`）—— 商品图是商家素材，元元（顾客）没有这个面。
"""

from typing import Any, Dict, Optional

from loguru import logger

from app.images.generator import (
    KINDS,
    ImageGenerationAuthError,
    ImageGenerationError,
    ImageGenerationQuotaExceeded,
    ImageGenerationUnavailable,
    generate_product_image,
)
from app.tools.base import BaseTool, ToolContext, ToolResult, admin_api_failure
from app.utils.http_client import get_admin_api_client

#: 用途 → 用户可见的中文名（只用于 `message` / `summary`，不参与提示词）
KIND_LABELS = {
    "main": "商品主图",
    "texture": "材质细节图",
    "craft": "工艺细节图",
    "scene": "场景效果图",
}


#: 四种工具错误码的**可行动**话术（互不冒充；用户面一律不说成「额度用尽」）。
#: 另有一条**同码不同话术**的 `IMAGE_GEN_CREDENTIAL`（码仍是 `IMAGE_GEN_UNAVAILABLE`）：
#: 凭证失效时唯一正确的事是「平台换 Key」，给「再生成一次」等于把商家引向一个永远不会成功的动作。
#: 调用点一律就地构造 `ToolResult(success=False, error=…, message=…, suggestion=…)`
#: （**不**包一层自定义构造器：模型可见文本的射程判据只认已登记的构造点，
#: 判据 = `tests/unit_ci_workflows/test_dead_capability_meta_guard.py::test_suggestion_kwarg_is_only_on_registered_builders`）。
#: 🔴 码写在这里的**字面** `"error"` 里（不靠日志文案推断），因为失败码现取判据
#: （`tests/unit_ci_workflows/test_remedy_registry_guard.py`）只认静态可见的短码，
#: 而「每个失败码都要有补救登记」正是靠它落地的。
_IMAGE_FAILURES: Dict[str, Dict[str, str]] = {
    "IMAGE_SOURCE_MISSING": {
        "error": "IMAGE_SOURCE_MISSING",
        "message": "这个商品还没有可用作样图的主图，暂时没法生成商品图",
        "suggestion": "请商家先在「商品管理」里给该商品上传一张清晰的主图（正面、整图、"
                      "无文字水印），再让我生成；不要凭空描述或编造商品图。",
    },
    "IMAGE_GEN_UNAVAILABLE": {
        "error": "IMAGE_GEN_UNAVAILABLE",
        "message": "商品图生成能力现在用不了（可能是配置未开通，或当前模型接不了这类图生图请求）",
        "suggestion": "不要再说「额度用尽」——这不是额度问题。可以晚些再让我生成，"
                      "或先在「商品管理」里手工上传一张商品图；如一直不行请告知商家该能力暂未开通。",
    },
    # 凭证 / 权限失效（401 `InvalidApiKey` / 403 `AccessDenied`，2026-10-25 线上实测）：
    # 对外码仍是 `IMAGE_GEN_UNAVAILABLE`（配置/能力问题，不是可重试的失败），但**话术必须换**——
    # 「晚些再让我生成」/「再生成一次」对一个无效 Key 是**永远不会成功**的建议（反向出路）。
    "IMAGE_GEN_CREDENTIAL": {
        "error": "IMAGE_GEN_UNAVAILABLE",
        "message": "商品图生成现在用不了（平台侧的生图凭证失效了，需要平台更换后才能用）",
        "suggestion": "这不是额度问题，也不是这张图的问题：现在请让商家先在「商品管理」里手工上传一张"
                      "商品图；凭证换好之前重复生成不会成功，先不要重试 —— "
                      "如商家追问，就说明是平台侧的生图凭证问题、已在处理。",
    },
    "IMAGE_GEN_QUOTA_EXCEEDED": {
        "error": "IMAGE_GEN_QUOTA_EXCEEDED",
        "message": "商品图生成额度暂时用尽了",
        "suggestion": "可以晚些再让我生成，或先在「商品管理」里手工上传一张商品图；"
                      "不要反复重试（短时间内不会恢复）。",
    },
    "IMAGE_GEN_FAILED": {
        "error": "IMAGE_GEN_FAILED",
        "message": "商品图没生成成功",
        "suggestion": "可以让我再生成一次；如仍失败，先在「商品管理」里手工上传一张商品图。",
    },
}


class ProductImageGenerateTool(BaseTool):
    """对已选商品生成商品图（样图 = 该商品主图；卡片预览 + 下载 / 保存到相册）"""

    name = "product_image_generate"
    description = (
        "【触发】商家说「给这个商品生成一张图 / 做张商品图 / 换张主图 / 出张材质图（工艺图 / 场景图）」"
        "时调用。"
        "【前置·必须先定位商品】本工具只接受**已选定的商品**：先用 product_search 按商品名查、"
        "或 product_detail 看档案，拿到 product_id 后再调用；商品不明确时先问商家/发 choice 卡消歧，"
        "**不要**猜一个 product_id 试。"
        "【样图】取该商品**档案里的主图**（没有主图时工具会明确拒绝并让你先让商家上传，不编造）。"
        "【参数】product_id（必填）/ kind（可选：main 主图 / texture 材质 / craft 工艺 / "
        "scene 场景，默认 main；商家没说用途就用 main）。"
        "【返回】商品图卡（一张 1440×1440 的图 + 商品名），商家可在电脑上下载、手机上保存到相册。"
        "【本工具不写库、不改商品】不会把新图设成主图，也不写任何表单 —— "
        "商家要换主图请在「商品管理」里自行上传。"
        "【文案】本工具不写任何营销文案；要做海报/宣传图（带标题与卖点）请用 marketing_poster。"
        "【标注】READONLY"
    )

    # 与 `GET /api/admin/products/{id}` 的读码逐字同码（与 product_detail / marketing_poster 同族）。
    required_permissions = ["product:list"]
    read_only = True
    # 仅 B 端：商品图是商家素材，元元（顾客）没有这个面。
    c_end_reachable = False

    parameters = {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "商品 ID（已选定的商品：先 product_search 按商品名定位，不要猜）",
            },
            "kind": {
                "type": "string",
                "enum": list(KINDS),
                "default": "main",
                "description": (
                    "生成用途：main 商品主图（默认）/ texture 材质细节 / craft 工艺细节 / "
                    "scene 场景效果。商家没说用途就不要传"
                ),
            },
        },
        "required": ["product_id"],
    }

    async def execute(
        self,
        context: ToolContext,
        product_id: str,
        kind: str = "main",
    ) -> ToolResult:
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限生成商品图",
                suggestion="请联系管理员开通商品查看权限（product:list）",
            )

        product_id = (product_id or "").strip() if isinstance(product_id, str) else ""
        if not product_id:
            return ToolResult(
                success=False,
                error="缺少商品 ID",
                message="请先告诉我要给哪个商品生成图",
                suggestion="缺少 product_id：先用 product_search 按商品名查到商品，再调用本工具",
                missing_params=["product_id"],
            )

        kind = (kind or "main").strip() if isinstance(kind, str) else ""
        if kind not in KINDS:
            return ToolResult(
                success=False,
                error="生成用途不合法",
                message=f"生成用途只能是{'/'.join(KINDS)}",
                suggestion=f"kind 取值只能是 {'/'.join(KINDS)}；商家没说用途就传 main",
                missing_params=["kind"],
            )

        try:
            client = get_admin_api_client()
            response = await client.get(
                f"/api/admin/products/{product_id}",
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:  # noqa: BLE001 —— 取不到商品事实就不生成（不编造）
            logger.error(f"Product image generate: fetch product failed: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="查询商品失败，暂时没法生成商品图",
                suggestion="请稍后重试；如持续失败请联系技术支持",
            )

        if not response.get("success"):
            error_code = (response.get("error") or {}).get("code", "")
            error_msg = (response.get("error") or {}).get("message", "查询失败")
            # 结构化判定（只认 error.code）—— 不对中文文案做子串匹配（同 marketing_poster）。
            if error_code == "NOT_FOUND":
                return admin_api_failure(
                    response,
                    error="商品不存在",
                    message="抱歉，未找到该商品，请检查商品 ID 是否正确",
                    suggestion="该商品 ID 在库中不存在，请改用 product_search 按商品名搜索，"
                               "并把候选结果给商家确认后再生成",
                )
            return admin_api_failure(
                response,
                error=error_msg,
                message="查询商品失败，暂时没法生成商品图",
                suggestion="请稍后重试；如持续失败请联系技术支持",
            )

        data = response.get("data") or {}
        if not data:
            return ToolResult(
                success=False,
                error="商品不存在",
                message="抱歉，未找到该商品",
                suggestion="该商品不存在或已下架，请改用 product_search 按商品名搜索并把候选给商家确认",
            )

        # 租户隔离（与 product_detail / marketing_poster 同款）：跨租户一律按「不存在」处理
        resp_tenant_id = data.get("tenantId") or data.get("tenant_id")
        if resp_tenant_id is not None and str(resp_tenant_id) != str(context.tenant_id):
            logger.error(
                f"Tenant data integrity violation in product_image_generate: "
                f"response tenant_id={resp_tenant_id}, expected={context.tenant_id}"
            )
            return ToolResult(
                success=False,
                error="商品不存在",
                message="抱歉，未找到该商品",
                suggestion="该商品不属于当前商户，请在本店范围内重新搜索",
            )

        product_name = str(data.get("name") or "").strip() or "这款商品"
        image_url = _sample_image(data)
        if not image_url:
            logger.info(f"Product image generate: no sample image, product={product_id}")
            failure = _IMAGE_FAILURES["IMAGE_SOURCE_MISSING"]
            return ToolResult(
                success=False,
                error=failure["error"],
                message=failure["message"],
                suggestion=failure["suggestion"],
                missing_params=[],
            )

        # 生图内核只接 http(s) 样图；相对路径 / 本地文件一律按「样图不可用」如实拒绝，
        # 不拼接、不猜测域名（猜错只会把请求打到错误的主机上）。
        if not image_url.startswith(("http://", "https://")):
            logger.warning(
                f"Product image generate: sample image is not absolute url, product={product_id}")
            failure = _IMAGE_FAILURES["IMAGE_SOURCE_MISSING"]
            return ToolResult(
                success=False,
                error=failure["error"],
                message=failure["message"],
                suggestion="该商品的主图地址不是完整可访问的图片地址，请商家在「商品管理」里"
                           "重新上传主图后再让我生成。",
            )

        try:
            generated = await generate_product_image(
                image_url=image_url,
                product_name=product_name,
                kind=kind,
            )
        except ImageGenerationAuthError as e:
            # 凭证 / 权限失效：同属「能力不可用」，但**不能**沿用「可以晚些再让我生成」——
            # 重试永远不会成功（2026-10-25 线上实测：现役 MaaS key 回 401 InvalidApiKey）。
            logger.error(f"Product image generate credential invalid: product={product_id}, err={e}")
            failure = _IMAGE_FAILURES["IMAGE_GEN_CREDENTIAL"]
            return ToolResult(
                success=False,
                error=failure["error"],
                message=failure["message"],
                suggestion=failure["suggestion"],
            )
        except ImageGenerationUnavailable as e:
            # 含「模型接不了这类请求」—— 与额度用尽**必须**分开，不冒充。
            # 内核自 #7540 起已把这件事分开抛：全链「都不接这类请求」⇒ 本异常
            # （消息含「非配额原因」）；命中配额 ⇒ `ImageGenerationQuotaExceeded`。
            # 本工具的映射与该真值一一对应（判据 = tests/test_product_image_generate.py
            # 的 TestFailureSemantics），不在这里二次猜测原因。
            logger.warning(f"Product image generate unavailable: product={product_id}, err={e}")
            failure = _IMAGE_FAILURES["IMAGE_GEN_UNAVAILABLE"]
            return ToolResult(
                success=False,
                error=failure["error"],
                message=failure["message"],
                suggestion=failure["suggestion"],
            )
        except ImageGenerationQuotaExceeded as e:
            logger.warning(f"Product image generate quota exceeded: product={product_id}, err={e}")
            failure = _IMAGE_FAILURES["IMAGE_GEN_QUOTA_EXCEEDED"]
            return ToolResult(
                success=False,
                error=failure["error"],
                message=failure["message"],
                suggestion=failure["suggestion"],
            )
        except ImageGenerationError as e:
            logger.error(f"Product image generate failed: product={product_id}, err={e}")
            failure = _IMAGE_FAILURES["IMAGE_GEN_FAILED"]
            return ToolResult(
                success=False,
                error=failure["error"],
                message=failure["message"],
                suggestion=failure["suggestion"],
            )
        except Exception as e:  # noqa: BLE001 —— 兜底同样给出可行动出路，不静默
            logger.error(f"Product image generate error: {e}", exc_info=True)
            failure = _IMAGE_FAILURES["IMAGE_GEN_FAILED"]
            return ToolResult(
                success=False,
                error=failure["error"],
                message=failure["message"],
                suggestion=failure["suggestion"],
            )

        label = KIND_LABELS[kind]
        logger.info(
            f"Product image generated: product={product_id}, kind={kind}, "
            f"model={generated.get('model')}, tenant={context.tenant_id}"
        )
        return ToolResult(
            success=True,
            data={
                "image_url": generated.get("image_url"),
                "model": generated.get("model"),
                "product": {"id": data.get("id") or product_id, "name": product_name, "kind": kind},
            },
            message=f"已为商品【{product_name}】生成一张{label}",
            summary=f"商品图卡：{product_name}｜{label}",
        )


def _sample_image(data: Dict[str, Any]) -> str:
    """样图 = 该商品主图（`mainImage`，缺失时回退 `images[0]`）；都没有 ⇒ 空串。"""
    images = data.get("images") if isinstance(data.get("images"), list) else []
    candidate: Optional[Any] = data.get("mainImage") or (images[0] if images else None)
    return str(candidate or "").strip()
