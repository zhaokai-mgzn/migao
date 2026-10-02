"""米宝「导航类」指引 Tool（issue #5989 · P1，**纯本地只读**）。

回答的是**两件事**（第一批范围，用户裁定 2026-10-02）：**这个功能在哪一页** / **你这角色有没有权限**。
**不回答操作步骤** —— 问「怎么做」时给导航答案 + 如实说「我没有步骤级指引」，**禁止**编步骤。

## 真值源（**仓内**，不调 admin-api）

`app/context/menu_navigator.py`：
- 结构层 = `frontend/admin-web/src/config/menu.ts` 的镜像（节点 key / 菜单名 / 路径 / 权限码），
  由 `tests/unit_ci_workflows/test_menu_navigator.py` 逐节点逐字段逐序核；
- 语义层（意图 → 功能）= **显式登记**的 `NAV_FEATURES`，匹配是**确定性最长前缀**，
  **未登记 ⇒ 默认拒绝**（不猜、不近似匹配、不给「可能在哪」）。

⇒ 本模块**没有任何 admin-api 调用点**（纯本地）⇒ 与 `interact` / `image_recognize` 同口径。
判据：`tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `LOCAL_ONLY_TOOLS`（判据 1 双向核对）。

## 权限码：**不声明**（`required_permissions = []`）—— 为什么

与本仓既有两条**纯本地**工具同口径（`interact` / `image_recognize`，见
`tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `LOCAL_ONLY_TOOLS`）：
**没有 admin-api 调用点 ⇒ 没有可对账的端点码** ⇒ 该守卫的判据 2（`工具码 ≡ 端点生效码`）
在这里**结构性不成立**（空端点集 ≠ 任何非空码集），而判据 2 的具名出口
`CODE_DIVERGENCE_EXCEPTIONS` 的形态是「跨码端点」（`code` / `diverges`）—— 不是为本形态设的
（硬挂进去 = 把「本地工具」记成「跨码工具」，属登记表语义污染）。

**授权面并没有因此放松**，反而**更细**：本工具根本不碰业务数据（答案全部来自仓内登记表），
真正的越权面是「**答案里能不能带出路径与权限码**」—— 那由 `build_navigation_answer` 按
**服务端会话的 `permissions`** 逐节点裁剪（见下）。工具层再挂一个码只会**收窄**它
（例如只持 `dashboard:view` 的人能问导航、不持的人被工具层拒），与本包要治的问题无关。

## 角色裁剪（**越权面**）

裁剪**只**按 `ToolContext.permissions`（**服务端会话**下发）判；**不读任何客户端递交的 role**——
与 `app/context/page_registry.py` 同纪律（`build_navigation_answer` 的签名里就没有 role）。
无权访问该页 ⇒ **不把路径与权限码说出去**（只给菜单名 + 「你没有权限」），但 citation 仍可溯。

## 为 P2（主动新手引导）预留

登记表本身已能回答「这一页有什么 / 哪些角色能看」（`visible_nodes` / `nodes_for_feature`）——
P2 的推送面**直接复用**，**不要另造第二份真值**（本包不做推送）。
"""

from typing import Any, Dict

from loguru import logger

from app.context.menu_navigator import build_navigation_answer
from app.tools.base import BaseTool, ToolContext, ToolResult


class NavGuideTool(BaseTool):
    """「这个功能在哪一页 / 你这角色有没有权限」导航指引（只读，纯本地）"""

    name = "nav_guide"
    description = (
        "【触发】用户问'XX 功能在哪一页''XX 在哪里''XX 有没有权限''我的角色能不能看 XX''XX 菜单找不到''权限不足去哪个页面开通'"
        "时调用（**只**在这一类问题上调用）。"
        "【参数】question 必填：用户的**原话**（照抄，不要改写/不要拆词/不要翻译）。"
        "【返回】登记在册的菜单路径 + 需要的权限码 + 按你当前会话权限裁剪后的可见性 + citation；"
        "**未登记**的功能会返回'我没有这条指引'。"
        "【反例】问'怎么做/从哪一步开始/怎么导出'（**步骤级**问题）→ 仍可调用本工具拿到**导航**信息，"
        "但**必须**如实告知'我没有步骤级指引'，**不得**自己编步骤；"
        "查业务数据（订单/库存/客户/生产…）用对应的查询工具，本工具**不查数据**。"
        "【标注】READONLY — 只读导航指引（仓内登记表，不访问业务数据）"
    )

    # ⚠️ **不声明权限码**（纯本地、零 admin-api 调用点 ⇒ 无可对账的端点码）——
    # 与 `interact` / `image_recognize` 同口径；授权面落在**答案级**的角色裁剪
    # （`build_navigation_answer` 按服务端会话 `permissions` 逐节点裁剪）。
    # 理由与后果逐条写在模块 docstring「权限码：**不声明**」一节。
    required_permissions = []
    read_only = True
    destructive = False
    idempotent = True

    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": (
                    "用户的**原话**（照抄即可）：如「工艺配置在哪」「我的角色能看到财务对账吗」"
                    "「商品管理菜单找不到」。不要改写、不要拆词、不要加英文。"
                ),
            },
        },
        "required": ["question"],
    }

    async def execute(self, context: ToolContext, question: str = "") -> ToolResult:
        # 授权面 = **答案级**裁剪（下面按服务端会话权限逐节点过滤）—— 本工具不碰业务数据，
        # 工具层没有可对账的端点码（见模块 docstring「权限码：**不声明**」）。
        # 裁剪的**唯一**输入 = 服务端会话的权限码（`context.permissions`）。
        # 客户端递交的 role 一律不读（与 `page_registry.build_page_context` 同纪律）。
        permissions = context.permissions or []
        answer = build_navigation_answer(question, permissions)
        data: Dict[str, Any] = answer.to_data()
        logger.info(
            f"[nav_guide] registered={answer.registered} feature={answer.feature_id or '-'} "
            f"granted={len(answer.granted)} denied={len(answer.denied)}"
        )

        if not answer.registered:
            return ToolResult(
                success=False,
                error="nav_not_registered",
                data=data,
                message=(
                    "⚠️ 这条问题没有命中登记在册的「功能 → 页面 → 权限」登记项 —— 我**不确定**它在哪一页，"
                    "**没有**这条指引。请**如实**告知用户你不确定，"
                    "并请他把功能名说清楚（或去「帮助 / 反馈」提一下）；"
                    "**不要**猜测页面，**不要**按猜测的页面口径作答。"
                ),
                summary="未登记的功能：如实告知没有这条指引（不要猜页面、不要编步骤）",
                suggestion=(
                    "把上面的『未登记』原话转述给用户：你不确定它在哪一页。"
                    "**不要**猜测页面，**不要**编造操作步骤。"
                    "🔴 本轮只有**导航类**信息：**不得**扩写成逐步指引、图文说明或操作顺序；"
                    "用户问「怎么做」时，给导航答案 + **如实说「我没有步骤级指引」**。"
                ),
            )

        return ToolResult(
            success=True,
            data=data,
            message=(
                f"{answer.render()}"
                "（以上仅为导航信息；用户若要操作指引，如实说没有步骤级指引。）"
            ),
            summary=f"「{answer.label}」的导航指引（{len(answer.granted)} 个可见页面）",
            suggestion=(
                "🔴 本轮只有**导航类**信息（功能在哪个页面 + 你这角色有没有权限）："
                "**不得**把它扩写成逐步指引、图文说明或操作顺序；"
                "用户问「怎么做」时，给导航答案 + **如实说「我没有步骤级指引」**。"
            ),
        )
