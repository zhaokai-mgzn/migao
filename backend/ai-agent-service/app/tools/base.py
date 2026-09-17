"""
AI 智能客服系统 - Tool 基础设施

提供 Tool 基类和上下文定义，所有 Tool 必须继承 BaseTool。
"""

# 前向引用：`admin_api_failure` 在 `ToolResult` 之前定义（常量与映射点放在文件头部，
# 便于「单一映射点」一眼可见），返回注解因此延迟求值。
from __future__ import annotations

import re
from abc import ABC, abstractmethod
import re
from typing import Annotated, Any, Dict, List, Optional
from pydantic import BaseModel, Field, create_model
from pydantic.functional_validators import BeforeValidator
from loguru import logger


# ── 授权/认证类错误码（admin-api 实际产出的字面量，逐个有出处）──────────────────
#
# **跨包契约**：另一个包会 `from app.tools.base import NON_RETRYABLE_ERROR_CODES`
# 来停止对「权限拒绝」的自动重试。名字与语义都不得随意变更。
#
# 口径 = 「换多少次参数都不可能成功」的 401/403：身份/授权问题，不是参数问题。
#   PERMISSION_DENIED  GlobalExceptionHandler 第 117 行 / BusinessException.permissionDenied()
#   FORBIDDEN          SecurityConfig 第 179 行（accessDeniedHandler，裸 JSON 直写）
#   AUTH_REQUIRED      GlobalExceptionHandler 第 98 行（AuthenticationException）
#   AUTH_FAILED        BusinessException.authFailed()
#   UNAUTHORIZED       SecurityConfig 第 172 行（authenticationEntryPoint）+ UserController
# 刻意**不含** TENANT_INVALID（BusinessException 第 116 行，401）：那是租户配置问题，
# 不是「当前账号缺权限」，交给调用方的默认文案更诚实。
NON_RETRYABLE_ERROR_CODES = frozenset({
    "PERMISSION_DENIED", "FORBIDDEN", "AUTH_REQUIRED", "AUTH_FAILED", "UNAUTHORIZED",
})

#: admin-api 在异常 message 里携带缺失权限码的形态（`PermissionInterceptor` 第 107 行）
_REQUIRED_PERMISSION_RE = re.compile(r"需要权限[:：]?\s*([A-Za-z][A-Za-z0-9_:]*)")


def _clean(value: Any) -> Optional[str]:
    """非空字符串化的取值：空串 / 纯空白 / 非字符串一律视为「没给」。"""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _first_code(value: Any) -> Optional[str]:
    """`requiredPermission` 可能是字符串或字符串数组 —— 取第一个非空码。"""
    if isinstance(value, str):
        return _clean(value)
    if isinstance(value, (list, tuple)):
        for item in value:
            code = _clean(item)
            if code:
                return code
    return None


def _required_permission(response: Dict[str, Any]) -> Optional[str]:
    """从失败响应里取「服务端说缺哪个权限码」（拿不到就返回 None，不臆造）。

    形状纪律（不猜，逐个有出处）：

    1. `error.details[{"field": "requiredPermission", "message": "<code>"}]`
       —— admin-api #4105/#4112 之后的**结构化真值**
       （`PermissionDeniedResponse.of()` 之 `ErrorDetail`）。
    2. `error.requiredPermission` / `error.requiredPermissions` / 顶层 `requiredPermission`
       —— `http_client` 对 4xx 整份透传（顶层字段也一起带过来），故平铺形态一并认。
    3. 兜底：异常 message 里的 `需要权限: <code>`（`PermissionInterceptor` 的原文）。
    """
    error = response.get("error")
    error = error if isinstance(error, dict) else {}
    for raw in (
        _detail_required_permission(error.get("details")),
        error.get("requiredPermission"),
        error.get("requiredPermissions"),
        response.get("requiredPermission"),
    ):
        code = _first_code(raw)
        if code:
            return code
    matched = _REQUIRED_PERMISSION_RE.search(_clean(error.get("message")) or "")
    return matched.group(1) if matched else None


def _detail_required_permission(details: Any) -> Optional[str]:
    """`error.details` 里 `field == "requiredPermission"` 那条的 `message`（即缺失的权限码）。"""
    if not isinstance(details, (list, tuple)):
        return None
    for item in details:
        if isinstance(item, dict) and item.get("field") == "requiredPermission":
            return _first_code(item.get("message"))
    return None


def _denial_suggestion(required_permission: Optional[str]) -> str:
    """授权失败给模型的**可执行**建议（不是「稍后重试」套话）。

    必须同时说清三件事，否则模型只会原地重试或胡编参数：
    ① 这是权限限制、不是参数问题；② **不要重试**；③ 去哪开通（管理后台的授权路径）。
    """
    missing = f"「{required_permission}」" if required_permission else "执行该操作所需的"
    return (
        "这是权限限制（不是参数问题）：请不要重试，也不要换参数重试。"
        f"当前账号缺少{missing}权限，请如实告知用户，并指引其联系管理员在管理后台"
        "（「员工管理 → 编辑员工 → 权限」或「角色管理 → 岗位权限」）为该账号开通后，"
        "再由用户重新发起本次操作。"
    )


def admin_api_failure(
    response: Dict[str, Any],
    *,
    error: Optional[str] = None,
    message: Optional[str] = None,
    suggestion: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> ToolResult:
    """**admin-api 失败响应 → `ToolResult` 的唯一映射点**（issue #4106 F6）。

    `app/utils/http_client.py` 对 4xx 已整份透传响应体（`error.code`/`error.message`/
    顶层 `suggestion` 都在），但工具侧过去会把它们丢掉、统一换成「请稍后重试」套话
    ⇒ **授权失败被当成参数问题**：模型反复重试同一调用，用户被告知「稍后重试」而不是
    「你的账号没有这个权限、去哪里开通」。

    映射规则：

    - `error.code ∈ NON_RETRYABLE_ERROR_CODES` ⇒ 建议一律换成可执行的权限指引
      （说明是权限限制、不要重试、指向管理后台授权路径），并保留服务端给的缺失权限码。
      **调用方的 `suggestion` 在这一支被刻意忽略** —— 它正是要被顶掉的套话。
    - 其它失败 ⇒ 服务端非空的 `suggestion` 优先，其次才是调用方给的默认文案；
      `message` / `error` 同理（调用方给了就用调用方的，因为它通常已拼上服务端 message）。
    - `error_code` 始终带上服务端的码（拿不到则留空，不臆造）。

    Args:
        response: `AdminApiClient` 返回的失败响应（含 `error` / `suggestion`）。
        error: 调用方给出的错误串（缺省回落到服务端 `error.message`）。
        message: 调用方给出的用户可见文案（缺省回落到服务端 `error.message`）。
        suggestion: 调用方给出的**兜底**建议（服务端给了建议时不用它）。
        data: 失败时仍要给模型的**结构化事实**（如 `{"notificationSent": False}`）；
            缺省为 None（绝大多数失败没有可回传的数据）。

    Returns:
        ToolResult: `success=False` 的失败结果，带 `error_code`。
    """
    payload = response if isinstance(response, dict) else {}
    error_info = payload.get("error")
    error_info = error_info if isinstance(error_info, dict) else {}
    code = _clean(error_info.get("code"))
    service_message = _clean(error_info.get("message"))

    if code in NON_RETRYABLE_ERROR_CODES:
        return ToolResult(
            success=False,
            data=data,
            error=error or service_message or "权限不足",
            message=message or service_message or "您没有权限执行该操作",
            suggestion=_denial_suggestion(_required_permission(payload)),
            error_code=code,
        )

    return ToolResult(
        success=False,
        data=data,
        error=error or service_message or "操作失败",
        message=message or service_message or "操作失败",
        suggestion=_clean(payload.get("suggestion")) or suggestion,
        error_code=code,
    )


class ToolContext(BaseModel):
    """Tool 执行上下文
    
    包含租户信息、用户信息、会话信息等，用于多租户隔离和权限控制。
    """
    tenant_id: int = Field(..., description="租户 ID")
    user_id: str = Field(..., description="用户 ID")
    session_id: Optional[str] = Field(None, description="会话 ID")
    role: str = Field("customer", description="用户角色: customer/admin/agent")
    permissions: list[str] = Field(default_factory=list, description="细粒度权限码列表")

    @property
    def ticket_source(self) -> str:
        """本会话调用方的**真实来源**，用于建售后工单时向 admin-api 声明（issue #3686）。

        米宝（B 端）与 小布（C 端）都通过 Service Token 调同一个
        `POST /api/admin/agent/after-sales`，服务端**无法自行判定**来源（operator 恒为
        internal-service、body 无 source —— #3605 已删）⇒ 由 ai-agent 侧按本上下文声明，
        经 `X-Agent-Client` 请求头下发，服务端只接受白名单内的值。

        - C 端（role 折叠为 customer/agent，见 api/chat.py `_to_agent_role`）→ `customer`（顾客发起）
        - B 端员工 → `agent`（AI 建单）

        与既有 `context.role == "customer"` 口径同源（inventory_manage / aftersale_query /
        order_query 等已用同一判据区分两端），不新增第二套身份判定。
        """
        return "customer" if self.role in CUSTOMER_ONLY_ROLES else "agent"

    class Config:
        arbitrary_types_allowed = True


# C 端（顾客）角色集合 —— **单点定义**（`api/chat.py` 直接 import 本常量，不再各自声明
# 一份：同值不同对象的两份口径会各自漂移，而注释却声称"chat.py 复用"，见 #4013 A10）。
# 统一折叠为 customer，禁止访问管理类工具；与 admin-api SecurityConfig 门禁口径一致：
# customer/agent 不属于商户员工。
CUSTOMER_ONLY_ROLES = frozenset({"customer", "agent"})


class ToolResult(BaseModel):
    """Tool 执行结果

    summary 字段: LLM 友好的摘要文本。若为 None，fallback 到 message。
    suggestion 字段: 失败时必须填写，告诉 LLM 如何引导用户修复问题。
    每个 tool 应自行设定 summary，确保 LLM 能快速理解结果。
    示例: ToolResult(success=True, data={...}, summary="共3个分类: 卧室系列,窗帘布艺,测试分类")
    """
    success: bool = Field(..., description="是否成功")
    data: Optional[Dict[str, Any]] = Field(None, description="返回数据")
    error: Optional[str] = Field(None, description="错误信息")
    message: Optional[str] = Field(None, description="提示消息（给用户看的）")
    summary: Optional[str] = Field(None, description="LLM友好摘要（每个tool自行填写）")
    suggestion: Optional[str] = Field(None, description="失败时的修复建议（给LLM看，帮助引导用户）")
    # admin-api 的 `error.code`（如 PERMISSION_DENIED / NOT_FOUND / VALIDATION_ERROR）。
    # **跨包契约**：另一个包按 `result.error_code in NON_RETRYABLE_ERROR_CODES` 决定是否
    # 抑制自动重试（issue #4106 F6）。新增字段默认空 ⇒ 对既有构造调用向后兼容。
    error_code: Optional[str] = Field(None, description="admin-api 错误码（失败时由 admin_api_failure 填充）")
    # terminal=True 表示该工具执行是一个「事务终态」：下单成功/售后创建成功/转人工成功等。
    # 触发 ContextManager.reset_domain()——清空当前域会话级状态（草稿/待确认/实体），
    # 避免旧状态污染下一轮对话（替代脆弱的字符串匹配清理，见 xiaobu-c-end-redesign.md §4.2 T2）。
    terminal: bool = Field(default=False, description="是否为事务终态（完成后需重置会话级上下文）")
    # 缺参的**结构化**形态（issue #4080 T3）：参数名清单（如 ["sms_code"] / ["items"]）。
    # 为什么必须有：此前的「缺哪个参数」是靠**中文错误原文子串匹配**反推的
    # （`WRITE_INPUT_ERROR_PARAMS` 表 + `key in text`）—— 错误文案改一个字，判据就静默失效。
    # 消费点：`execution/react_turn.py` 的缺参记账（→ 跨轮索要指令 + 重复动作拦截）。
    missing_params: Optional[List[str]] = Field(
        None, description="失败时缺失/非法的参数名清单（结构化，供缺参恢复链消费）")

    class Config:
        extra = "allow"


# ── 入参契约：`parameters`（JSON-Schema 形态）→ Pydantic 模型（**全仓唯一实现**）──
# 病根（issue #4080，母单 #4043 的 T-B 包 T2）：每个工具都声明了 `parameters`
# （type/properties/required/enum/description），而 `BaseTool._get_args_schema()` 的实现体
# **字面就是 `return None`**（注释自述"简化实现"）⇒ 声明存在、消费为零。同一段生成逻辑当时在
# `langchain_adapter` 与 `registry` 各有一份副本 —— 本函数把三处收敛成一处（判据单点来源）。

# JSON Schema type -> Python type（与收敛前的两份副本逐字一致）
_JSON_TYPE_TO_PYTHON = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _json_string_parser(value: Any) -> Any:
    """BeforeValidator: LLM 传了 JSON 字符串时自动解析为 list/dict。"""
    import json
    if isinstance(value, str) and value.strip().startswith(("[", "{")):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"[ToolArgsSchema] Failed to parse JSON string arg: value={value[:200]}")
    return value


def build_args_schema(name: str, parameters: dict) -> Optional[type]:
    """从工具声明的 `parameters` 动态生成 Pydantic 模型（`args_schema`）。

    `required` **只按 schema 显式声明**取 —— 角色条件必填（如 `order_create.sms_code`：
    描述写着「customer 角色必填，admin/agent 不需要」）**不在** `required` 里，
    因此不会把 B 端流程拦死。
    """
    parameters = parameters or {}
    props = parameters.get("properties") or {}
    if not props:
        return None

    required_fields = set(parameters.get("required") or [])
    field_definitions: Dict[str, Any] = {}
    for field_name, field_schema in props.items():
        field_schema = field_schema or {}
        py_type = _JSON_TYPE_TO_PYTHON.get(field_schema.get("type", "string"), str)
        description = field_schema.get("description", "")
        default = field_schema.get("default", ...)
        # array/object 字段加 BeforeValidator，在 Pydantic 类型强制前解析 JSON 字符串
        # LLM 可能把 colors='["米白"]' 传成字符串，不处理 Pydantic 会用 list(str) 逐字符拆分
        validators = [BeforeValidator(_json_string_parser)] if py_type in (list, dict) else []
        if field_name in required_fields:
            field_definitions[field_name] = (
                Annotated[py_type, *validators] if validators else py_type,
                Field(description=description),
            )
        else:
            field_definitions[field_name] = (
                Annotated[Optional[py_type], *validators] if validators else Optional[py_type],
                Field(default=default if default is not ... else None, description=description),
            )

    if not field_definitions:
        return None
    return create_model(f"{name.title().replace('_', '')}Args", **field_definitions)


# 宽松数值形态（issue #3586 的既有契约）：允许货币符号前缀 + 单位后缀，按**前导数字**解析。
# "3米" / "2.8 米" / "¥168.00" 都是工具**已经容忍**的合法输入 ⇒ 契约层不得把它们判成类型错误
# （R2：判据不得拦掉原本合法的输入）。
_LENIENT_NUMBER_RE = re.compile(r"^\s*[¥$￥]?\s*[-+]?\d+(?:\.\d+)?\s*[^\d\s]*\s*$")
_TRUE_WORDS = frozenset({"true", "1", "yes", "是"})
_FALSE_WORDS = frozenset({"false", "0", "no", "否"})


def _value_fits_type(declared: str, value: Any) -> bool:
    """值能否按声明的 JSON-Schema 类型被工具消费（**宽松**口径，fail-open 优先）。

    只拦「**结构上不可能**被消费」的值；凡是既有链路已经容忍的形态一律放行。
    `None` / 空串按"没填"处理（可选字段不填是合法形态），由 `required` 判据负责缺参。
    """
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if declared in ("number", "integer"):
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return True
        return isinstance(value, str) and bool(_LENIENT_NUMBER_RE.match(value))
    if declared == "string":
        return not isinstance(value, (list, dict))
    if declared == "boolean":
        if isinstance(value, bool):
            return True
        if isinstance(value, (int, float)):
            return True
        return isinstance(value, str) and value.strip().lower() in (_TRUE_WORDS | _FALSE_WORDS)
    if declared == "array":
        return isinstance(value, list) or (isinstance(value, str) and value.strip().startswith("["))
    if declared == "object":
        return isinstance(value, dict) or (isinstance(value, str) and value.strip().startswith("{"))
    return True   # 未声明/未知类型 ⇒ 不判（fail-open）


def _type_hint(declared: str) -> str:
    return {
        "number": "数字（如 3 或 \"3米\"）",
        "integer": "整数",
        "string": "字符串",
        "boolean": "布尔值",
        "array": "列表（如 [...]）",
        "object": "对象（如 {...}）",
    }.get(declared, declared)


class BaseTool(ABC):
    """Tool 基类
    
    所有 Tool 必须继承此类，并实现 execute 方法。
    
    示例：
        class ProductSearchTool(BaseTool):
            name = "product_search"
            description = "搜索商品列表"
            
            async def execute(self, context: ToolContext, keyword: str = "") -> ToolResult:
                # 实现搜索逻辑
                return ToolResult(success=True, data={...})
    """
    
    # Tool 元数据（子类必须定义）
    name: str = ""
    description: str = ""

    # 参数 JSON Schema（用于 LangChain/OpenAI function calling）
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {},
    }

    # MCP 风格 Tool Annotations — 帮助 LLM 做工具选择决策
    # read_only=True  → 纯查询，LLM 可放心调用，无需确认
    # read_only=False → 会修改数据，LLM 应先确认再调用
    # destructive=True → 可执行不可逆的删除/销毁操作，LLM 必须弹 confirm 卡片
    # requires_confirmation=True → 非 destructive 但高风险写操作（财务/通知/会话/库存等，
    #   审计 07 P0-L1：间接提示注入可驱动其无确认执行），同样必须弹 confirm 卡片
    # idempotent=True → 相同参数多次调用结果一致，可安全重试
    read_only: bool = True
    destructive: bool = False
    requires_confirmation: bool = False
    idempotent: bool = True

    # read_only_actions: destructive 工具中纯只读的 action 集合（如 list/detail/tree）。
    # 这些 action 不修改数据，执行时豁免确认拦截（确认守卫只针对写/破坏性 action）。
    # 空集 = 该工具所有 action 都是写/破坏性操作，一律需确认。
    # 契约：必须是 VALID_ACTIONS 的子集（见 test_destructive_tool_confirm_guard.py）。
    read_only_actions: frozenset = frozenset()

    # 权限控制
    require_auth: bool = True
    # 角色白名单 —— **只在未声明 required_permissions 时生效**（见 check_permission）。
    # 声明了权限码的工具不得再声明它：那是第二份会漂移、且实际不生效的假门禁
    # （issue #4106 F3/F4；由 tests/test_tool_permission_codes.py 静态锁定）。
    allowed_roles: list[str] = ["customer", "admin", "agent", "tenant_admin"]
    # 细粒度权限码（**权威层**）：非空 ⇒ 由 JWT permissions claim 决定访问，
    # 空列表 ⇒ 回落到 allowed_roles 粗筛。码取自 admin-api 权限目录
    # （`RegistrationService.initializeDefaultRolesAndPermissions` 的 18 码），
    # 端点对应关系取各 controller 的 `@RequirePermission`。
    required_permissions: list[str] = []
    
    def __init__(self):
        """初始化 Tool"""
        if not self.name:
            raise ValueError(f"{self.__class__.__name__} must define 'name'")
        if not self.description:
            raise ValueError(f"{self.__class__.__name__} must define 'description'")
    
    @abstractmethod
    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        """执行 Tool
        
        Args:
            context: Tool 执行上下文，包含租户、用户等信息
            **kwargs: Tool 特定参数
            
        Returns:
            ToolResult: 执行结果
        """
        pass
    
    def check_permission(self, context: ToolContext) -> bool:
        """检查权限 —— 与 `[ai-chat.permission-layers]` 契约一致的两层检查。

        1. **细粒度层（权威）**：声明了 `required_permissions` 的工具，由 JWT
           `permissions` claim 决定（`*` = 全权限）。**逐工具的角色白名单在这一层不参与** ——
           按角色码硬编码放行正是 #4106 F3/F4 的病根：`allowed_roles` 是手写清单，
           而 admin-api 的权限目录会演进（「角色管理」还能建任意自定义角色码），
           两者必然漂移 ⇒ 持有权限码的员工被工具判「权限不足」（假拒绝），
           模型随后无法向用户解释任何东西。这一层唯一保留的角色判断是
           **C 端硬闸**（`CUSTOMER_ONLY_ROLES`，两端隔离不变式，见下）。
        2. **角色层（粗筛）**：仅在**未声明权限码**时生效 —— C 端顾客工具
           （C 端 JWT 没有权限码，加码会让 C 端全量失效）与目录里没有对应码的
           通用工具（如 `notification_manage`：`NotificationController` 全类无
           `@RequirePermission`）。这一层是**真正需要**的，不是历史包袱。

        Args:
            context: Tool 执行上下文

        Returns:
            bool: 是否有权限执行

        Note:
            决策依据是 JWT 里的 `permissions` claim；生产环境里 `admin` 恒为 `["*"]`
            （`RoleService.getUserPermissions` 特判），C 端 `customer`/`agent` 恒为空。
            `tenant_admin` 在 admin-api 里**不存在**（无角色行、无权限映射），
            故不再被工具层放行 —— 修掉的正是这条跨服务口径断裂。
        """
        if not self.require_auth:
            return True

        # 细粒度层（权威）：权限码说了算，角色白名单不参与
        if self.required_permissions:
            # C 端硬闸（**两端隔离不变式**，不是第二套授权表）：`customer`/`agent` 永不执行
            # 商户管理类工具。C 端 JWT 本就没有权限码（`UserIdentity.permissions` 默认空、
            # `RoleService` 对 customer/agent 返回空集）⇒ 生产不可达，这里是纵深防御；
            # 沿用既有单点常量 `CUSTOMER_ONLY_ROLES`，不新增任何角色清单。
            # 既有守卫先例：tests/test_tools_base.py 的「customer + `*` 通配 → 拒绝」。
            if context.role in CUSTOMER_ONLY_ROLES:
                return False
            permissions = context.permissions or []
            if "*" in permissions:
                return True
            return any(p in permissions for p in self.required_permissions)

        # 角色层（粗筛）：只给「没有目录权限码」的工具用
        return context.role in self.allowed_roles
    
    def get_schema(self) -> Dict[str, Any]:
        """获取 LangChain/OpenAI 兼容的 function schema

        description 中自动注入工具类型标注（read_only/destructive/idempotent），
        帮助 LLM 在 tool choice 阶段做出更好的选择决策。

        Returns:
            Dict: OpenAI function schema 格式
        """
        # 构建工具类型标注
        tags = []
        if self.read_only:
            tags.append("READONLY")
        else:
            tags.append("WRITE")
        if self.destructive:
            tags.append("DESTRUCTIVE")
        if not self.idempotent:
            tags.append("NON_IDEMPOTENT")

        tagged_desc = f"[{'|'.join(tags)}] {self.description}"

        # 破坏性工具：在 schema 末尾追加确认要求（LLM 做 tool choice 时可见）
        if self.destructive:
            tagged_desc += " ⛔️铁律: 必须先展示操作预览(dry-run汇总)并获取用户明确确认后才能执行,禁止直接调用。"
        elif not self.read_only:
            tagged_desc += " ⚠️ 需先确认再执行,禁止跳过确认直接操作。"

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": tagged_desc,
                "parameters": self.parameters,
            }
        }
    
    def to_langchain_tool(self) -> Any:
        """转换为 LangChain Tool 格式
        
        Returns:
            StructuredTool: LangChain 兼容的 Tool 对象
        """
        from langchain_core.tools import StructuredTool
        
        async def _execute(**kwargs):
            # 注意：这里需要外部注入 context
            # 实际调用时会通过 agent 传递 context
            logger.debug(f"Executing {self.name} with params: {kwargs}")
            # 返回空，实际逻辑在 agent 中处理
            return {"tool": self.name, "params": kwargs}
        
        return StructuredTool.from_function(
            func=_execute,
            name=self.name,
            description=self.description,
            args_schema=self._get_args_schema(),
        )
    
    def _get_args_schema(self) -> Optional[type]:
        """获取参数 Pydantic Schema（用于 LangChain）

        Returns:
            Optional[type]: Pydantic BaseModel 类或 None
        """
        return build_args_schema(self.name, self.parameters)

    # ── 入参契约校验（issue #4080 T2）—— 工具声明的 `parameters` 必须**在执行前被消费** ──
    # 单一来源 + 单一入口：判据只在 `validate_args()` 里；调用点在**共享执行路径**
    # （`base_skill._execute_tool_safe` 与 `ToolRegistry.execute_tool`），不逐工具手写。
    MISSING_REQUIRED_ERROR = "missing_required_args"
    INVALID_TYPE_ERROR = "invalid_arg_type"
    INVALID_ENUM_ERROR = "invalid_arg_enum"

    def validate_args(self, args: Optional[Dict[str, Any]]) -> Optional["ToolResult"]:
        """执行前按 `parameters` 的**显式声明**校验入参。

        Returns:
            None = 放行；`ToolResult(success=False, …)` = 结构化失败（带可执行 `suggestion`
            与结构化 `missing_params`），调用方**不得**再执行工具本体。

        **fail-open 是设计**（逐条都有阴性负例，见 `tests/unit/test_tool_input_contract.py`）：

        - `required` 只按 schema **显式声明**执行 —— 角色条件必填（`order_create.sms_code`
          的「customer 角色必填，admin/agent 不需要」）不在 `required` 里 ⇒ **不拦 B 端**；
        - 类型/枚举按声明执行，但沿用工具**既有的宽松口径**（`"3米"` / `"¥168.00"` 这类
          issue #3586 明写的合法输入必须放行）；
        - **未知多余键一律放行**（跨工具幻觉参数由既有净化链路 `_sanitize_tool_args` 处理）；
        - 无 `properties` / 嵌套明细项（`items[].xxx`，由各工具自己的精确失败面负责）/
          非 `BaseTool` 对象 ⇒ 不校验。
        """
        args = args if isinstance(args, dict) else {}
        props = (self.parameters or {}).get("properties") or {}
        if not props:
            return None

        required = [k for k in (self.parameters.get("required") or []) if k in props]
        missing = [k for k in required if k not in args or args.get(k) is None]
        if missing:
            return self._args_error(
                self.MISSING_REQUIRED_ERROR, missing,
                f"缺少必填参数 {', '.join(missing)}",
                (f"缺少必填参数 {', '.join(missing)} —— 请先补齐它们再调用 {self.name}；"
                 f"若某个参数顾客还没提供，就用自然语言向顾客索要（**不要编造**值），"
                 f"拿到后再调用。"),
            )

        for field, schema in props.items():
            if field not in args:
                continue
            schema = schema or {}
            value = args[field]
            declared = schema.get("type", "")
            allowed = schema.get("enum")
            if isinstance(allowed, (list, tuple)) and allowed:
                if value not in allowed and str(value) not in [str(a) for a in allowed]:
                    return self._args_error(
                        self.INVALID_ENUM_ERROR, [field],
                        f"参数 {field} 取值不在允许范围",
                        (f"参数 {field} 只接受 {' / '.join(str(a) for a in allowed)}，"
                         f"当前值不在其中 —— 请从这些取值里选一个后重试。"),
                    )
            if declared and not _value_fits_type(declared, value):
                return self._args_error(
                    self.INVALID_TYPE_ERROR, [field],
                    f"参数 {field} 类型不符合声明（应为 {declared}）",
                    (f"参数 {field} 声明为 {declared}（{_type_hint(declared)}），当前传入的值"
                     f"无法按该类型解析 —— 请改传 {_type_hint(declared)} 后重试。"),
                )
        return None

    def _args_error(self, code: str, params: List[str], message: str,
                    suggestion: str) -> "ToolResult":
        """构造入参契约失败结果（**统一形状**：结构化缺参 + 可执行 suggestion）。"""
        logger.warning(
            f"[tool-args-contract] {self.name} 入参不满足声明的契约："
            f"code={code} params={params}"
        )
        return ToolResult(
            success=False,
            error=code,
            message=message,
            suggestion=suggestion,
            missing_params=list(params),
        )
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"
    
    def __str__(self) -> str:
        return self.name
