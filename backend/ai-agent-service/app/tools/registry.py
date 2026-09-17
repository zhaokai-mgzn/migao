"""
AI 智能客服系统 - Tool 注册器

提供 Tool 的注册、管理和获取功能。
支持通过 contextvars 注入 ToolContext，让 LangChain Tool 能够调用实际的业务逻辑。
"""

import asyncio
import json
import time
import contextvars
from typing import Dict, List, Optional, Any, Type
from loguru import logger
from pydantic import BaseModel, Field, create_model

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.tools.langchain_adapter import LangChainToolAdapter
from app.utils.http_client import AdminApiClient, get_admin_api_client
from app.utils.log_sanitizer import LogSanitizer

# 全局 ToolContext，用于在 LangChain Tool 执行时传递上下文
_current_tool_context: contextvars.ContextVar[Optional[ToolContext]] = contextvars.ContextVar(
    'current_tool_context', default=None
)


def set_tool_context(context: ToolContext) -> None:
    """设置当前请求的 Tool 执行上下文"""
    _current_tool_context.set(context)


def get_tool_context() -> Optional[ToolContext]:
    """获取当前请求的 Tool 执行上下文"""
    return _current_tool_context.get()


# ── 当前**执行域**：本轮模型真正能调用的工具集（issue #4017 / A5）──────────────
# 事实源只有一处：`base_skill.create_skill_registry(tool_names)` 造出的 skill 工具子集
#（同一份事实被 `get_langchain_tools()` 拿去告诉模型"你有哪些工具"）。存在理由：
# `validate_input` 的校验域是全局的（`_VALIDATION_RULES`），执行却是域相关的（skill 外工具
# 一律 `Tool not found`），两侧从不比对 ⇒ 域外目标校验返回 success=True → 落「已校验待执行」
# → 确认卡 → 点卡后 `Tool not found` → 空头承诺、订单永不落库（#3976）。
#
# 三态语义（适用域声明见 `ValidateInputTool.execute` 的域比对分支）：
#   · `frozenset[str]`：skill 回合，本轮可执行工具集；· `frozenset()`：**空域** ⇒ 任何目标都
#   不可执行 ⇒ `validate_input` fail-closed 全拒；· `None`：**无 skill 域**（`api/chat.py` /
#   `api/internal.py` 直调全局注册表、单测直调）⇒ 域即全局注册表（由已注册检查兜底）——
#   这是**可读的事实**（调用方不经 skill 回合），不是"读不到"。
# 作用域 = 当前 asyncio 任务上下文（与 `_current_tool_context` 同族）：每个 skill 回合都重新
# 登记，故同一任务里后一次执行总是看到本回合的域。
_current_tool_scope: contextvars.ContextVar[Optional[frozenset]] = contextvars.ContextVar(
    'current_tool_scope', default=None
)


def set_tool_scope(tool_names=None) -> None:
    """登记当前 skill 的可执行工具集（调用方：`base_skill.create_skill_registry`）。

    传 `None` 表示"无 skill 域"（非 skill 执行路径 / 测试隔离）。
    """
    _current_tool_scope.set(None if tool_names is None else frozenset(tool_names))


def get_tool_scope() -> Optional[frozenset]:
    """当前 skill 的可执行工具集；`None` = 无 skill 域（非 skill 回合）。"""
    return _current_tool_scope.get()


# ── 写操作审计落库（issue #4039）────────────────────────────────────────────
# 为什么走 HTTP 而不是直连 DB：本仓架构契约 = 工具层一律经 admin-api 访问数据
# （ai-agent-service 不持有 DB 凭据/租户会话上下文），审计表 audit_logs 在 admin-api 侧。
# 端点路径以**字面量**写在调用点（`tests/test_tool_payload_backend_contract.py` 的
# 「payload 调用点必须静态归属到端点」门禁要求可静态渲染，常量会让调用点脱离射程）。
# audit_logs.resource_type：把「AI 工具写操作」与人工表单审计（product/order/briefing_config 等）区分开
_WRITE_AUDIT_RESOURCE_TYPE = "agent_tool"
# 审计上报的硬上限（秒）：http_client 默认 25s ⇒ admin-api 挂住会把写路径一起拖住。
# fail-open 只有在**有界**时才有意义：宁可丢一行审计，也不能让商户等 25s 才下完单。
# ⚠️ 口径由 issue #4071 裁定为**保持有界 fail-open**（不做 fail-closed：后者会新增一条业务写
# 失败面，且与「审计是旁路」的既有口径冲突）。本常量即「有界」的可判定判据（红证见
# tests/test_write_audit_action_semantics.py）。
_WRITE_AUDIT_TIMEOUT_S = 3.0

# ── `audit_logs.action` 的语义 = **动词**（issue #4071 裁定 ①）────────────────
# 现状病灶：`action` 里放**工具名** + `resource_type='agent_tool'` ⇒ **同一列两种语义**，
# 查询/报表侧必须知道「action 的含义取决于 resource_type」这条隐式规则 ——
# 正是本仓库反复批判的「同一概念两个来源」形态。
# 收敛后：`action` 只放动作（create/update/delete/toggle_status/confirm_payment…），
# 工具名另置 `audit_logs.tool_name`（迁移 V52）。
#
# 动作来源两档（**顺序固定**，不得颠倒）：
#   ① 工具调用的 `action` 参数 —— 权威（它就是本次调用的动作语义）；
#   ② 无 `action` 参数的工具 ⇒ 查下表兜底。**禁止用工具名当动词**（本条的全部分量所在）。
# 下表是**显式映射**：工具集里 read_only=False 且无 `action` 参数的工具必须逐条在此登记，
# 漏登记 ⇒ tests/test_write_audit_action_semantics.py 红（该测试按源码解析工具集，与实现单一源比对）。
_NO_ACTION_PARAM_TOOL_ACTION: Dict[str, str] = {
    # 单一动作工具（自身即「做什么」）
    "order_create": "create",
    "aftersale_create": "create",
    "product_update": "update",
    "sku_update": "update",
    # human_handoff 建的是**投诉工单**（description：「自动创建投诉工单 → 通知管理员」）
    "human_handoff": "create",
    # processing_order_generate 语义是「批量生成加工单」（description【语义】），
    # 不是 create —— 与 processing_item_manage 的 create_processing_item 区分开
    "processing_order_generate": "generate",
}


# 派生不出动作时的 `action` 落库哨兵（**不是**工具名，也不是合法动词）——只为不违反 NOT NULL。
_UNMAPPED_ACTION_SENTINEL = "(unmapped)"


def derive_audit_action(tool_name: str, params: Optional[Dict[str, Any]]) -> Optional[str]:
    """派生本次写调用的**动作动词**（`audit_logs.action`，issue #4071 裁定 ①）。

    ① 工具调用的 `action` 参数优先（如 order_manage 的 confirm_payment / employee_manage 的
       toggle_status）—— 它就是动作语义本身；
    ② 无 `action` 参数的工具查 `_NO_ACTION_PARAM_TOOL_ACTION`。

    两档都取不到 ⇒ 返回 `None`（**绝不回退成工具名**：那正是本函数要消灭的形态）。
    调用方 `audit_write_tool` 对该形态打 `[AUDIT] ACTION_UNMAPPED`（可观测），
    `action` 落哨兵值以免违反 `audit_logs.action NOT NULL`；
    「哪个工具漏登记」由 `tests/test_write_audit_action_semantics.py` 在 L0 层拦下。
    """
    raw = (params or {}).get("action")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return _NO_ACTION_PARAM_TOOL_ACTION.get(tool_name)


def desensitize_params(params: Dict[str, Any]) -> Dict[str, str]:
    """参数脱敏（PII 纪律**单点实现**）：只保留字段名与类型占位，绝不带真实值。

    手机号/地址/姓名等真实值一旦进日志或 `audit_logs.action_details`，就是不可撤销的
    PII 泄露（多租户 SaaS 的合规问题）。故这里是唯一实现，调用方不得各写一份。
    """
    return {k: f"<{type(v).__name__}>" for k, v in (params or {}).items()}


async def audit_write_tool(
    tool_name: str,
    context: ToolContext,
    params: Dict[str, Any],
    success: bool,
    duration_ms: float,
) -> bool:
    """把一次写工具调用落进 admin-api 的 audit_logs（成功/失败/异常都必须留痕）。

    Args:
        tool_name: 工具名 → `audit_logs.tool_name`（**不再**进 `action`，issue #4071 裁定 ①）
        context: 执行上下文；`tenant_id`/`user_id` 经请求头透传（**不放 body**：
            服务端以认证上下文为准，body 无从伪造身份）
        params: **原始**参数 —— 本函数内部脱敏，调用方无从漏脱敏；
            同时是动作派生的输入（`params["action"]` 优先，见 `derive_audit_action`）
        success: 执行是否成功（`success=false` 同样落库：尝试过但失败也要可追溯）
        duration_ms: 耗时（毫秒）

    Returns:
        bool: 是否落库成功。False ⇒ 已打 `[AUDIT] PERSIST_FAILED` 警告（可观测），
        但**不阻断**业务写操作 —— 审计不是业务护栏，端点故障时宁可丢审计行也不能让
        商户下不了单。口径由 issue #4071 裁定为**有界 fail-open**（3s 硬上限，
        `_WRITE_AUDIT_TIMEOUT_S`），**不做 fail-closed**。
    """
    action = derive_audit_action(tool_name, params)
    if action is None:
        # 不猜、不用工具名兜底：显式留痕 + 落哨兵，让「漏登记」自己现形
        action = _UNMAPPED_ACTION_SENTINEL
        logger.warning(
            f"[AUDIT] ACTION_UNMAPPED tool={tool_name} —— 该工具无 `action` 参数且未登记"
            f" `_NO_ACTION_PARAM_TOOL_ACTION`；action 落哨兵 {_UNMAPPED_ACTION_SENTINEL}。"
            f"修复：在 registry._NO_ACTION_PARAM_TOOL_ACTION 补该工具的动词"
        )
    try:
        client = get_admin_api_client()
        resp = await asyncio.wait_for(
            client.post(
                "/api/admin/agent/audit-logs",
                json_data={
                    "action": action,
                    "toolName": tool_name,
                    "resourceType": _WRITE_AUDIT_RESOURCE_TYPE,
                    "actionDetails": {
                        # ⚠️ 重复 `action` 是**有意**的：`action` 列在迁移 V52 里被回填为
                        # 「动词」，而回填只能从 `action_details->>'action'` 派生 ——
                        # 新行带上它，回填规则才对**新行**同样成立（否则 V52 的注释
                        # 「新写入方已直接写 action」与回填语句的射程不一致）。
                        # 唯一事实源仍是 `derive_audit_action` 的返回值（上方 action 变量）。
                        "action": action,
                        "params": desensitize_params(params),
                        "success": success,
                        "durationMs": round(duration_ms, 1),
                        "role": context.role,
                        "sessionId": context.session_id,
                    },
                },
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            ),
            timeout=_WRITE_AUDIT_TIMEOUT_S,
        )
        if not (isinstance(resp, dict) and resp.get("success") is True):
            raise RuntimeError(f"audit endpoint rejected: {resp}")
        return True
    except Exception as e:
        # ⚠️ 本 except 自身绝不能再抛（fail-open 的最后一道）：`context` 可能是 None
        # （既有单测 `_execute_tool_safe(tool, args, None, state)` 就是这种形态），
        # 直接取属性会让「审计失败」升级成「工具执行失败」。
        logger.warning(
            f"[AUDIT] PERSIST_FAILED tool={tool_name} "
            f"tenant={getattr(context, 'tenant_id', None)} "
            f"user={getattr(context, 'user_id', None)} error={type(e).__name__}: {e} | "
            f"suggestion=检查 admin-api 存活与 POST /api/admin/agent/audit-logs 的 Service Token/租户上下文"
        )
        return False


class ToolRegistry:
    """Tool 注册器
    
    管理所有可用的 Tool，提供注册、获取和 LangChain 兼容接口。
    
    使用示例：
        registry = ToolRegistry()
        registry.register(ProductSearchTool())
        
        # 获取 Tool
        tool = registry.get_tool("product_search")
        
        # 获取所有 Tool
        tools = registry.get_all_tools()
        
        # 获取 LangChain 兼容格式
        langchain_tools = registry.get_langchain_tools()
    """
    
    def __init__(self):
        """初始化 Tool 注册器"""
        self._tools: Dict[str, BaseTool] = {}
        self._admin_api_client: Optional[AdminApiClient] = None
    
    def register(self, tool: BaseTool) -> "ToolRegistry":
        """注册 Tool
        
        Args:
            tool: Tool 实例
            
        Returns:
            ToolRegistry: 支持链式调用
            
        Raises:
            ValueError: 如果 Tool 名称已存在
        """
        if tool.name in self._tools:
            logger.warning(f"Tool '{tool.name}' already registered, overwriting")
        
        self._tools[tool.name] = tool
        logger.info(f"Tool registered: {tool.name}")
        return self
    
    def unregister(self, name: str) -> bool:
        """注销 Tool
        
        Args:
            name: Tool 名称
            
        Returns:
            bool: 是否成功注销
        """
        if name in self._tools:
            del self._tools[name]
            logger.info(f"Tool unregistered: {name}")
            return True
        return False
    
    def get_tool(self, name: str) -> Optional[BaseTool]:
        """获取 Tool
        
        Args:
            name: Tool 名称
            
        Returns:
            Optional[BaseTool]: Tool 实例或 None
        """
        return self._tools.get(name)
    
    def get_all_tools(self) -> List[BaseTool]:
        """获取所有已注册的 Tool
        
        Returns:
            List[BaseTool]: Tool 列表
        """
        return list(self._tools.values())
    
    def get_tool_names(self) -> List[str]:
        """获取所有 Tool 名称
        
        Returns:
            List[str]: Tool 名称列表
        """
        return list(self._tools.keys())
    
    def has_tool(self, name: str) -> bool:
        """检查 Tool 是否存在
        
        Args:
            name: Tool 名称
            
        Returns:
            bool: 是否存在
        """
        return name in self._tools
    
    def get_schemas(self) -> List[Dict[str, Any]]:
        """获取所有 Tool 的 JSON Schema
        
        Returns:
            List[Dict]: OpenAI function schema 列表
        """
        return [tool.get_schema() for tool in self._tools.values()]
    
    def get_tools_description(self) -> str:
        """获取 Tool 描述文本
        
        用于生成系统提示词中的 Tool 说明。
        
        Returns:
            str: Tool 描述文本
        """
        if not self._tools:
            return "暂无可用工具"
        
        descriptions = []
        for name, tool in self._tools.items():
            descriptions.append(f"- {name}: {tool.description}")
        
        return "\n".join(descriptions)
    
    def get_langchain_tools(self) -> List[Any]:
        """获取 LangChain 兼容的 Tool 列表
        
        每个 LangChain Tool 通过 contextvars 获取 ToolContext，
        实际调用对应 BaseTool 的 execute 方法。
        
        Returns:
            List: LangChain Tool 列表
        """
        langchain_tools = []
        for tool in self._tools.values():
            lc_tool = LangChainToolAdapter.create_langchain_tool(
                tool=tool,
                get_context_func=get_tool_context,
            )
            langchain_tools.append(lc_tool)
        
        return langchain_tools
    
    @staticmethod
    def _build_args_schema(tool: BaseTool) -> Optional[Type[BaseModel]]:
        """从 Tool 的 parameters JSON Schema 动态生成 Pydantic 模型

        **实现单点来源**（issue #4080）：生成逻辑在 `app.tools.base.build_args_schema()`，
        本方法只做转接（此处曾是三份副本之一）。

        Args:
            tool: 原始 Tool

        Returns:
            Optional[Type[BaseModel]]: Pydantic 模型类，用作 args_schema
        """
        from app.tools.base import build_args_schema
        return build_args_schema(tool.name, tool.parameters)

    def _create_langchain_tool(self, tool: BaseTool) -> Any:
        """创建 LangChain Tool（已废弃，使用 LangChainToolAdapter）
        
        Args:
            tool: 原始 Tool
            
        Returns:
            StructuredTool: LangChain Tool
        """
        return LangChainToolAdapter.create_langchain_tool(
            tool=tool,
            get_context_func=get_tool_context,
        )
    
    async def execute_tool(
        self,
        name: str,
        context: ToolContext,
        **kwargs,
    ) -> ToolResult:
        """执行指定 Tool
        
        Args:
            name: Tool 名称
            context: Tool 执行上下文
            **kwargs: Tool 参数
            
        Returns:
            ToolResult: 执行结果
            
        Raises:
            ValueError: 如果 Tool 不存在
        """
        tool = self.get_tool(name)
        if not tool:
            logger.warning(f"[tool-registry] Tool not found: {name}")
            return ToolResult(
                success=False,
                error=f"Tool '{name}' not found",
                message=f"未知工具：{name}",
                suggestion="该工具名不在可用工具列表中，请从当前技能可用的工具里重新选择，不要臆造工具名",
            )
        
        # 权限检查
        if not tool.check_permission(context):
            logger.info(f"[tool-registry] Permission denied: {name} | tenant={context.tenant_id} role={context.role if hasattr(context, 'role') else 'unknown'}")
            return ToolResult(
                success=False,
                error="Permission denied",
                message="您没有权限使用该功能",
                suggestion="当前账号无该工具权限，请改用只读查询或请用户联系管理员开通权限",
            )
        
        # 入参契约校验（issue #4080 T2）：判据本体在 `BaseTool.validate_args`（单一来源），
        # 此处是**第二个共享消费点**（与 `base_skill._execute_tool_safe` 同一条）。
        # 只认 `ToolResult` 实例（MagicMock 替身会自动变出 Mock ⇒ 不得当成契约失败而误拦）
        _contract_failure = tool.validate_args(kwargs)
        if isinstance(_contract_failure, ToolResult):
            return _contract_failure

        # 写操作审计日志：记录所有非只读操作的用户/参数/结果
        # 参数脱敏：仅记录结构化字段名，不记录值（避免 phone/address/name 等 PII 入日志）
        is_write = not tool.read_only
        if is_write:
            safe_params = desensitize_params(kwargs)
            logger.info(
                f"[AUDIT] WRITE tool={name} "
                f"tenant={context.tenant_id} user={context.user_id} "
                f"role={context.role} session={context.session_id} "
                f"params={json.dumps(safe_params, ensure_ascii=False)}"
            )

        start = time.time()
        try:
            logger.info(f"[tool-registry] Executing: {name} | tenant={context.tenant_id}")
            result = await tool.execute(context, **kwargs)
            duration_ms = (time.time() - start) * 1000
            status = "OK" if result.success else "FAIL"
            if is_write:
                logger.info(
                    f"[AUDIT] WRITE_RESULT tool={name} "
                    f"tenant={context.tenant_id} user={context.user_id} "
                    f"success={result.success} duration={duration_ms:.1f}ms"
                )
                # 落库（issue #4039）：此前审计只进 loguru ⇒ audit_logs 0 行、写操作不可追溯
                await audit_write_tool(name, context, kwargs, result.success, duration_ms)
            else:
                logger.info(f"[tool-registry] Completed: {name} | success={result.success} duration={duration_ms:.1f}ms | tenant={context.tenant_id}")
            return result
        except Exception as e:
            # 记录详细错误信息到日志（包含租户上下文便于排查）
            logger.error(
                f"[tool-registry] Failed: {name} | tenant={context.tenant_id} error={type(e).__name__}: {e}",
                exc_info=True,
            )
            if is_write:
                # 异常路径同样留痕（否则「尝试过但失败」不可追溯）
                await audit_write_tool(name, context, kwargs, False, (time.time() - start) * 1000)
            # 返回泛化错误，不暴露内部细节
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="工具执行失败，请稍后重试",
                suggestion="请稍后重试；若持续失败，请改用其它可用工具完成用户诉求，必要时转人工",
            )
    
    def clear(self):
        """清空所有 Tool"""
        self._tools.clear()
        logger.info("Tool registry cleared")
    
    def __len__(self) -> int:
        """返回 Tool 数量"""
        return len(self._tools)
    
    def __contains__(self, name: str) -> bool:
        """检查是否包含指定 Tool"""
        return name in self._tools
    
    def __repr__(self) -> str:
        return f"ToolRegistry(tools={list(self._tools.keys())})"


# 全局注册器实例
_registry_instance: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """获取全局 ToolRegistry 实例（单例模式）
    
    Returns:
        ToolRegistry: Tool 注册器实例（包含默认 Tools）
    """
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = create_default_registry()
    return _registry_instance


def reset_tool_registry():
    """重置全局注册器实例（用于测试）"""
    global _registry_instance
    _registry_instance = None


def create_default_registry() -> ToolRegistry:
    """创建并注册所有默认 Tool
    
    注册以下 Tool：
    - product_search: 商品搜索
    - product_detail: 商品详情
    - logistics_track: 物流查询
    - knowledge_search: 知识卡片检索（本店已发布知识，LLM WIKI）
    - order_query: 订单查询
    - order_manage: 订单管理
    - order_create: 订单创建
    - product_manage: 商品管理
    - inventory_manage: 库存管理
    - processing_item_query: 加工项查询
    - customer_manage: 客户管理
    - employee_manage: 员工管理
    - role_manage: 角色管理
    - dashboard_stats: 经营数据看板
    - after_sales_manage: 售后管理
    - knowledge_manage: 知识库管理
    - notification_manage: 通知管理
    - settings_manage: 系统设置
    - session_manage: 客服会话管理
    - category_manage: 商品分类管理
    - processing_item_manage: 加工项管理
    - production_progress_query: 生产进度查询（双端只读，issue #3996；按 persona 绑定见 skills/*_TOOLS）
    - piecework_query: 计件查询（仅 B 端，issue #3996；不对顾客开放）
    
    Returns:
        ToolRegistry: 配置好的注册器
    """
    from app.tools.product_search import ProductSearchTool
    from app.tools.product_detail import ProductDetailTool
    from app.tools.logistics_track import LogisticsTrackTool
    from app.tools.customer_logistics_track import CustomerLogisticsTrackTool
    from app.tools.knowledge_search import KnowledgeSearchTool
    from app.tools.order_query import OrderQueryTool
    from app.tools.customer_order_query import CustomerOrderQueryTool
    from app.tools.customer_address_query import CustomerAddressQueryTool
    from app.tools.order_manage import OrderManageTool
    from app.tools.order_create import OrderCreateTool
    # 加工单工具类保留但不再注册（产品决策 2026-09-15，issue #3917）：
    # agent 暂不接入 processing_order_* 工具，须区分「加工项/加工单」概念并引导后台；
    # 工具类文件保留（tests/test_tools_processing_order_*.py 直测类），未来恢复接入时
    # 取消本行注释即可。
    # from app.tools.processing_order_generate import ProcessingOrderGenerateTool
    # from app.tools.processing_order_query import ProcessingOrderQueryTool
    # from app.tools.processing_order_update import ProcessingOrderUpdateTool
    from app.tools.product_manage import ProductManageTool
    from app.tools.inventory_manage import InventoryManageTool
    from app.tools.processing_item_query import ProcessingItemQueryTool
    from app.tools.customer_manage import CustomerManageTool
    from app.tools.employee_manage import EmployeeManageTool
    from app.tools.role_manage import RoleManageTool
    from app.tools.dashboard_stats import DashboardStatsTool
    from app.tools.finance_api import FinanceApiTool
    from app.tools.after_sales_manage import AfterSalesManageTool
    from app.tools.aftersale_create import AftersaleCreateTool
    from app.tools.aftersale_query import AftersaleQueryTool
    from app.tools.human_handoff import HumanHandoffTool
    # [RAG 禁用] from app.tools.knowledge_manage import KnowledgeManageTool
    from app.tools.notification_manage import NotificationManageTool
    from app.tools.settings_manage import SettingsManageTool
    from app.tools.session_manage import SessionManageTool
    from app.tools.category_manage import CategoryManageTool
    from app.tools.processing_item_manage import ProcessingItemManageTool
    from app.tools.product_processing_item_manage import ProductProcessingItemManageTool
    from app.tools.product_update import ProductUpdateTool
    from app.tools.sku_update import SkuUpdateTool
    from app.tools.interact import InteractTool  # noqa: F401 保留以备将来使用
    from app.tools.validate_input import ValidateInputTool
    from app.tools.curtain_calc import CurtainCalcTool
    from app.tools.production_progress_query import ProductionProgressQueryTool
    from app.tools.piecework_query import PieceworkQueryTool
    from app.tools.payment_qrcode_query import PaymentQrcodeQueryTool

    registry = ToolRegistry()
    
    # 注册所有 Tool
    registry.register(ProductSearchTool())
    registry.register(ProductDetailTool())
    registry.register(LogisticsTrackTool())
    registry.register(CustomerLogisticsTrackTool())
    registry.register(KnowledgeSearchTool())
    registry.register(OrderQueryTool())
    registry.register(CustomerOrderQueryTool())
    registry.register(CustomerAddressQueryTool())
    registry.register(OrderManageTool())
    registry.register(OrderCreateTool())
    # 加工单工具不注册（issue #3917，见上方 import 注释）：
    # registry.register(ProcessingOrderGenerateTool())
    # registry.register(ProcessingOrderQueryTool())
    # registry.register(ProcessingOrderUpdateTool())
    registry.register(ProductManageTool())
    registry.register(InventoryManageTool())
    registry.register(ProcessingItemQueryTool())
    # 新增12个管理类 Tool
    registry.register(CustomerManageTool())
    registry.register(EmployeeManageTool())
    registry.register(RoleManageTool())
    registry.register(DashboardStatsTool())
    registry.register(FinanceApiTool())
    registry.register(AfterSalesManageTool())
    registry.register(AftersaleCreateTool())
    registry.register(AftersaleQueryTool())
    registry.register(HumanHandoffTool())
    # [RAG 禁用] registry.register(KnowledgeManageTool())
    registry.register(NotificationManageTool())
    registry.register(SettingsManageTool())
    registry.register(SessionManageTool())
    registry.register(CategoryManageTool())
    registry.register(ProcessingItemManageTool())
    registry.register(ProductProcessingItemManageTool())
    registry.register(ProductUpdateTool())
    registry.register(SkuUpdateTool())
    # interact 工具重新启用：支持交互式组件（interactive component support）
    registry.register(InteractTool())
    registry.register(ValidateInputTool())
    registry.register(CurtainCalcTool())
    # 生产进度 / 计件（issue #3996，M4-I）：消费 M4-G-2 冻结契约端点。
    # 注册表只决定「工具存在」；可达性由 persona 的 skill 工具集决定
    # （生产进度：小布 customer_order + 米宝 order；计件：仅米宝 order/staff，不对顾客开放）。
    registry.register(ProductionProgressQueryTool())
    registry.register(PieceworkQueryTool())
    # 收款二维码查询（issue #4085 第 1 项，M3-F-3/#3990 的发射点）：只读、C 端专属
    # （allowed_roles=["customer"]），可达性仍由 persona 的 skill 工具集决定
    # （小布 customer_order；商家设置端走 SettingsController，不经 Agent）。
    registry.register(PaymentQrcodeQueryTool())

    logger.info(f"Default registry created with {len(registry)} tools")
    return registry
