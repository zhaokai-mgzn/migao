"""同页填充工具 `image_recognize`（issue #5368 包 2 · Agent 深通道的**可达面**）。

## 它做什么

米宝（B 端）用户站在**建品页 / 建单页**上，把图片丢进浮动面板的对话里 ⇒ 模型调本工具 ⇒
**复用识别内核**（`app/vision/recognizer.py::recognize`，不是第二份识别实现）⇒ 得到
`page_fill` 计划（填哪几格 + 候选 + 解读）⇒ `app/api/chat.py` 以**瞬时** SSE 事件推给页面表单。

## 边界（三条，都有机械判据）

1. 🔴 **不落库、不落盘**：本工具**没有任何 admin-api 调用点**（纯本地：只调 vision 模型 + 纯函数），
   也不触碰任何写入缝（判据 `tests/test_tools_image_recognize.py::TestNoWriteBoundary`，
   含注入式红证）。**提交永远是商家在页面上点按钮的动作。**
2. 🔴 **一个内核**：`recognize` 是内核里那**一个函数对象**（判据用 `is` 身份断言 ——
   「同名两份实现」在静态上与「共用」不可区分）。
3. **能力不下沉给 C 端**：本工具只绑 B 端 skill（`product` / `order`），小布不绑 ⇒ C 端零改动。

`allowed_roles = ["*"]`（**角色层不设限**）：本工具纯本地 + 只读，角色层不构成门禁 ——
而商户侧角色码是**开放集合**（admin-api「角色管理」可建任意岗位码），任何手写角色清单都必然
把持码员工判成「权限不足」（`app/tools/base.py::check_permission` 记载的同款病根，issue #4106 F4）。
可达性由 **skill 绑定**决定（B 端两个 skill），不由角色白名单决定。
"""
import json
from typing import Any, Dict, List, Optional

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.vision.deep_channel import (
    SOURCE_INTERPRETED,
    SOURCE_RECOGNIZED,
    build_page_fill,
    log_summary,
)
from app.vision.recognizer import recognize

#: 四个参数名（schema / execute 签名 / 测试断言共用的唯一一份）
PARAM_NAMES = ("target_type", "images", "catalog", "interpretations")


class ImageRecognizeTool(BaseTool):
    """图 → 字段 + 候选 + 解读，并推给**当前页面表单**（同页填充）。"""

    name = "image_recognize"
    description = (
        "【触发】用户发来图片（色卡 / 面料实拍 / 手写单 / 微信截图 / 旧系统单据）并要"
        "「按这张图建商品 / 建单 / 认字段」时调用；也可用于「这是什么面料 / 工艺 / 适合什么场景」"
        "这类领域解读。"
        "【参数】target_type 必填（product 建品页 / order 建单页）；images 必填"
        "（用户上传的图片 URL，从上下文「[用户上传的图片（可直接引用 URL）：…]」里逐字取，"
        "**不得编造**）；catalog 可选（店铺已有的候选取值，如 {\"color\": [\"藏青\",\"天蓝\"]}，"
        "用来消歧）；interpretations 可选（你的**领域解读 / 推荐**："
        "{\"material\": {\"value\": \"雪尼尔\", \"note\": \"克重偏厚，适合客厅\"}}）。"
        "【行为】识别结果会**自动填进商家当前所在的页面表单**（同页填充，不需要商家跳转，"
        "也不要让商家去点页面上的上传按钮）；你只需用文字说明「哪几格已填、哪几格留空及原因」。"
        "目录里没有的取值**不填**，工具返回候选 + 解释 ⇒ 把候选贴给商家挑；"
        "订单侧的解读**只解释、一格都不填**（客户信息错 ⇒ 货发错人）。"
        "【注意】同一张图不要重复调用（一次调用就够，重复调用会重复填表）。"
        "【反例】不要用它查业务数据（用 product_search / product_detail / order_query）；"
        "不要用它写数据 —— 它**绝不落库**，提交永远是商家在页面上点按钮。"
        "【标注】READONLY — 纯识别 + 同页填充，不写业务数据"
    )

    # 纯本地工具（无 admin-api 调用点）⇒ 角色层不设限；可达性由 skill 绑定决定
    allowed_roles = ["*"]
    required_permissions: List[str] = []
    read_only = True

    parameters = {
        "type": "object",
        "properties": {
            "target_type": {
                "type": "string",
                "description": "识别目标：product（建品页：名称/颜色/材质/工艺/门幅/售价）"
                               "或 order（建单页：客户名/电话/地址/明细/数量/帘宽/帘高）",
                "enum": ["product", "order"],
            },
            "images": {
                "type": "array",
                "description": "图片 URL 列表（https:// 或 /api/files 开头）；从上下文里逐字取，不得编造",
                "items": {"type": "string"},
            },
            "catalog": {
                "type": "object",
                "description": "可选的店铺候选值（消歧用）：{字段键: [已有取值]}。"
                               "给了目录 ⇒ 取值不在目录里就**不填**，只返回候选 + 解释",
            },
            "interpretations": {
                "type": "object",
                "description": "可选的领域解读：{字段键: {value, note}}。"
                               "商品侧只对 material / craft 生效（来源标 [米宝解读]）；"
                               "订单侧只解释不填值",
            },
        },
        "required": ["target_type", "images"],
    }

    async def execute(
        self,
        context: ToolContext,
        target_type: str,
        images: Any,
        catalog: Any = None,
        interpretations: Any = None,
    ) -> ToolResult:
        """识别图片并产出**同页填充计划**（不写任何业务数据）。"""
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="无法识别图片",
                suggestion="请改用当前账号有权限的方式录入（手工填写表单），或请管理员开通权限",
            )

        try:
            result = await recognize(
                target_type, _ensure_image_list(images), tenant_id=context.tenant_id
            )
        except ValueError as e:
            # 未知 target / 没有可用图片 —— 内核 fail-closed，这里如实转达（不回落默认 target）
            return ToolResult(
                success=False,
                error=str(e),
                message=f"无法按这张图识别：{e}",
                suggestion="确认 target_type 只能是 product / order；图片 URL 必须是 "
                            "https:// 或 /api/files 开头（用户没发图时请让用户重新上传）",
            )

        if result.get("degraded"):
            return ToolResult(
                success=False,
                error="recognition_degraded",
                message="这张图没认出可用字段（可能太模糊 / 不是单据或面料图）——"
                        "请商家手工填写，或换一张更清晰的图片重试",
                suggestion="换一张更清晰的图片；或直接引导商家在页面上手工填表",
            )

        plan = build_page_fill(
            target_type,
            result.get("fields") or [],
            catalog=_ensure_dict(catalog),
            interpretations=_ensure_dict(interpretations),
        )
        # 只打安全摘要（target/计数/键名）——**值一律不进日志**（订单侧含客户信息）
        return ToolResult(
            success=True,
            data=plan,
            message=_model_message(plan),
        )


def _ensure_image_list(value: Any) -> List[Any]:
    """图片入参归一：数组原样；JSON 字符串数组解析；单个 URL 直接包成单元素数组。

    模型实测会把这三种形态都传出来（`interact` 的 `options` 同因）。
    归一后仍由内核的 `normalize_image_urls` 逐条校验（非法 URL 一样被过滤掉）。
    """
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return []
            return parsed if isinstance(parsed, list) else []
        return [text]
    return []


def _ensure_dict(value: Any) -> Dict[str, Any]:
    """模型常把对象参数传成 JSON 字符串（与 `interact` 的 `_ensure_list` 同因）。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _model_message(plan: Dict[str, Any]) -> str:
    """给**模型**看的转述文本：逐格说明填了什么、留空的为什么、候选有哪些。

    为什么逐格写清（而不是只回一句「已填表」）：模型要据此**向商家解释**
    （歧义为什么这几个最接近、哪几格是它的解读而非图上抄的）——那正是深通道存在的理由。
    """
    lines: List[str] = [
        f"已按图产出同页填充计划（{log_summary(plan)}）。",
        "识别结果已推给商家**当前页面**的表单（同页填充，商家不需要跳转）。",
        "",
        "逐格情况：",
    ]
    for field in plan.get("fields") or []:
        label = field.get("label") or field.get("key")
        if field.get("value"):
            mark = field.get("source")
            lines.append(f"- {label}：{field['value']}（来源 {mark}）")
        else:
            lines.append(f"- {label}：**未填**（{field.get('reason')}）")
        if field.get("candidates"):
            options = "、".join(c["value"] for c in field["candidates"])
            lines.append(f"  ↳ 目录里最接近的是：{options} —— 请**贴给商家挑**，不要替他选")
        if field.get("note"):
            lines.append(f"  ↳ 米宝解读：{field['note']}（{SOURCE_INTERPRETED}，不是图上抄的）")
    lines += [
        "",
        "口径：",
        f"- 「{SOURCE_RECOGNIZED}」= 图上抄下来的；「{SOURCE_INTERPRETED}」= 你的解读/推荐 —— "
        "两者**必须对商家讲清楚**，不要混为一谈；",
        "- 留空的格子**不要**自行补值，也不要让商家以为已经填了；",
        "- 🔴 提交永远是商家的动作：你只填表，不要替商家提交、不要发写确认卡。",
    ]
    return "\n".join(lines)