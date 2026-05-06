# Hermes Tool 规范

> 版本：v8.0（Review 修订版 + CRM 客户管理 Tool）  
> 日期：2026-04-12  
> 变更：从自定义 Skill 框架全面改写为 Hermes Agent Tool 规范（function calling 标准）

---

## 1. 概述

Tool 是 AI 客服系统的核心业务能力单元。系统基于 **Hermes Agent 框架**，采用标准的 **function calling** 协议（兼容 OpenAI tool_call 格式）。

与之前的自定义 Skill 框架相比，Hermes Tool 架构的核心区别：

| 维度 | 旧 Skill 框架 | Hermes Tool 框架 |
|------|--------------|-----------------|
| 意图识别 | 自建关键词 + SkillRegistry | LLM 原生 function calling |
| 参数提取 | 自建 LLM 提取 + 校验 | LLM 直接输出结构化参数 |
| 多步调用 | 自建链式编排 | Hermes Agent ReAct 循环 |
| Tool 定义 | 自定义 JSON Schema | OpenAI-compatible function schema |
| 调度逻辑 | 框架代码路由 | LLM 自主决策 |

---

## 2. Tool 定义格式

### 2.1 标准 Function Schema

每个 Tool 使用 OpenAI-compatible 的 function 定义格式：

```json
{
  "type": "function",
  "function": {
    "name": "order_query",
    "description": "查询订单状态、详情和物流信息。当用户询问订单相关问题时调用此工具。",
    "parameters": {
      "type": "object",
      "properties": {
        "order_id": {
          "type": "string",
          "description": "订单号，例如 ORD12345"
        }
      },
      "required": ["order_id"]
    }
  }
}
```

### 2.2 命名规范

| 规则 | 要求 | 示例 |
|------|------|------|
| name | 蛇形命名，动词_名词 | `order_query`, `product_search`, `logistics_track` |
| description | 清晰描述功能 + 调用时机 | "查询订单状态...当用户询问订单时调用" |
| parameters | JSON Schema 标准 | `{"type": "object", "properties": {...}}` |

### 2.3 业务 Tool 清单

#### 客服前台 Tools (ai-agent-service)

| Tool 名称 | 分类 | 描述 |
|-----------|------|------|
| `order_query` | 订单 | 查询订单状态、详情 |
| `order_list` | 订单 | 查询用户的订单列表 |
| `logistics_track` | 物流 | 查询物流轨迹信息 |
| `product_search` | 售前 | 搜索商品（关键词、分类、价格） |
| `product_detail` | 售前 | 查询商品详情（规格、价格、库存） |
| `product_recommend` | 售前 | 基于需求推荐商品 |
| `after_sales_create` | 售后 | 发起退货/换货/维修申请 |
| `after_sales_query` | 售后 | 查询售后进度 |
| `knowledge_search` | 知识库 | 查询面料知识库（自托管 RAG / DashVector） |
| `human_handoff` | 转接 | 转接人工客服 |

#### 管理助手 Tools (ai-agent-service)

| Tool 名称 | 分类 | 描述 |
|-----------|------|------|
| `stats_orders` | 统计 | 查询订单统计（销量、营收、趋势） |
| `stats_products` | 统计 | 查询商品统计（热销、库存预警） |
| `stats_customers` | 统计 | 查询客户统计（新增、活跃、转化率） |
| `report_generate` | 报表 | 生成业务报表（日报/周报/月报） |
| `inventory_alert` | 库存 | 查询库存预警信息 |
| `knowledge_manage` | 知识库 | 管理知识库（上传/查询/删除文档，调用 `/api/admin/knowledge/documents`） |

---

## 3. Tool 实现

### 3.1 基类

```python
# packages/hermes_tools/base.py
from abc import ABC, abstractmethod
from typing import Any, Dict
from pydantic import BaseModel

class ToolResult(BaseModel):
    """Tool 执行结果"""
    success: bool
    data: Any = None
    error: str | None = None
    display: Dict[str, Any] | None = None  # 前端展示提示

class BaseTool(ABC):
    """
    Hermes Tool 基类
    - 每个 Tool 必须声明 name, description, parameters
    - 实现 execute() 方法
    - 框架自动将 Tool 注册到 Hermes Agent
    
    安全控制层级：
    1. 角色权限：allowed_roles 控制哪些角色可以调用
    2. 租户隔离：所有查询强制带 tenant_id
    3. 用户隔离：data_scope 控制数据可见范围（self=仅自己, tenant=租户内全部）
    4. 字段脱敏：field_masking 按角色隐藏敏感字段
    """
    
    # 子类必须定义
    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}
    
    # 权限控制
    require_auth: bool = True
    allowed_roles: list[str] = ["customer", "admin"]
    
    # 数据隔离级别：self=仅自己, tenant=租户内全部
    data_scope: str = "self"
    
    # 字段脱敏：角色 -> 需要隐藏的字段列表
    field_masking: Dict[str, list[str]] = {}
    
    def __init__(self, tenant_id: str, user_id: str, db_session, redis_client):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.db = db_session
        self.redis = redis_client
    
    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """
        执行 Tool 逻辑
        kwargs 参数由 Hermes Agent 从 LLM 的 tool_call 中解析
        """
        pass
    
    def apply_data_scope(self, query, model):
        """
        根据 data_scope 自动追加数据过滤条件
        - self: 追加 user_id 过滤
        - tenant: 仅追加 tenant_id 过滤
        """
        query = query.where(model.tenant_id == self.tenant_id)
        if self.data_scope == "self":
            query = query.where(model.user_id == self.user_id)
        return query
    
    def mask_fields(self, data: dict, role: str) -> dict:
        """按角色脱敏敏感字段"""
        if role not in self.field_masking:
            return data
        masked = {k: v for k, v in data.items() if k not in self.field_masking[role]}
        return masked
    
    def to_function_schema(self) -> Dict[str, Any]:
        """转换为 OpenAI function calling 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }
```

### 3.2 Tool 注册

```python
# packages/hermes_tools/registry.py
from typing import Dict, Type, List

class ToolRegistry:
    """
    Tool 注册中心
    - 自动扫描并注册所有 Tool
    - 生成 Hermes Agent 所需的 tools 列表
    - 根据用户角色过滤可用 Tool
    """
    
    _tools: Dict[str, Type[BaseTool]] = {}
    
    @classmethod
    def register(cls, tool_class: Type[BaseTool]):
        """装饰器：注册 Tool"""
        cls._tools[tool_class.name] = tool_class
        return tool_class
    
    @classmethod
    def get_tools_for_role(cls, role: str) -> List[Dict]:
        """获取指定角色可用的 Tool 定义列表（传给 LLM）"""
        return [
            tool_cls({}).to_function_schema()  # 仅需 schema，不需实例化
            for tool_cls in cls._tools.values()
            if role in tool_cls.allowed_roles or not tool_cls.require_auth
        ]
    
    @classmethod
    def get_tool_class(cls, name: str) -> Type[BaseTool] | None:
        """根据名称获取 Tool 类"""
        return cls._tools.get(name)
    
    @classmethod
    def list_all(cls) -> List[str]:
        """列出所有已注册的 Tool 名称"""
        return list(cls._tools.keys())
```

---

## 4. Hermes Agent 执行流程

### 4.1 ReAct 循环

Hermes Agent 使用 ReAct（Reasoning + Acting）模式：

```
用户消息 → LLM 推理
              ↓
         需要调用 Tool?
         ├── 是 → 执行 tool_call → 获取结果 → 回到 LLM 推理（可能继续调用）
         └── 否 → 直接生成回复 → 返回用户
```

**完整流程**：

```python
# packages/hermes_agent/agent.py

class HermesAgent:
    """Hermes Agent — ReAct 循环执行器"""
    
    MAX_TOOL_CALLS = 5  # 单轮最多调用 5 次 Tool，防止无限循环
    
    async def run(self, user_message: str, context: AgentContext) -> AsyncIterator[SSEEvent]:
        """执行 Agent 主循环"""
        messages = context.build_messages(user_message)
        
        # 获取当前用户可用的 Tool 列表
        available_tools = ToolRegistry.get_tools_for_role(context.role)
        
        for iteration in range(self.MAX_TOOL_CALLS):
            # 1. 调用 LLM（百炼 API）
            response = await self.llm.chat_completions(
                model=context.tenant_config.bailian_app_id,
                messages=messages,
                tools=available_tools,
                stream=True
            )
            
            # 2. 处理响应
            if response.has_tool_calls:
                # LLM 决定调用 Tool
                for tool_call in response.tool_calls:
                    yield SSEEvent(type="loading", content=f"正在{tool_call.display_name}...")
                    
                    # 执行 Tool
                    result = await self._execute_tool(
                        tool_call.name, 
                        tool_call.arguments,
                        context
                    )
                    
                    # 将 Tool 结果加入消息历史
                    messages.append({
                        "role": "assistant",
                        "tool_calls": [tool_call.to_dict()]
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result.model_dump(), ensure_ascii=False)
                    })
                    
                    # 如果 Tool 有前端展示数据
                    if result.display:
                        yield SSEEvent(type="card", data=result.display)
                
                # 继续循环，让 LLM 基于 Tool 结果继续推理
                continue
            
            else:
                # LLM 直接生成文本回复（流式输出）
                async for chunk in response.stream_text():
                    yield SSEEvent(type="text", content=chunk)
                break
        
        yield SSEEvent(type="done", session_id=context.session_id)
    
    async def _execute_tool(self, name: str, arguments: dict, context: AgentContext) -> ToolResult:
        """安全执行 Tool"""
        tool_class = ToolRegistry.get_tool_class(name)
        if not tool_class:
            return ToolResult(success=False, error=f"Tool '{name}' 不存在")
        
        # 第 1 层：角色权限检查
        if tool_class.require_auth and context.role not in tool_class.allowed_roles:
            return ToolResult(success=False, error="权限不足")
        
        # 第 2 层：实例化并注入身份上下文
        tool = tool_class(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            db_session=context.db,
            redis_client=context.redis
        )
        
        # 第 3 层：注入角色用于字段脱敏
        arguments["context_role"] = context.role
        
        try:
            # 第 4 层：超时保护
            return await asyncio.wait_for(
                tool.execute(**arguments),
                timeout=30  # 30 秒超时
            )
        except asyncio.TimeoutError:
            return ToolResult(success=False, error="Tool 执行超时")
        except Exception as e:
            logger.error(f"Tool {name} 执行失败: {e}")
            return ToolResult(success=False, error="内部错误，请稍后重试")
```

### 4.2 AgentContext

```python
# packages/hermes_agent/context.py

class AgentContext:
    """Agent 执行上下文"""
    
    def __init__(
        self,
        tenant_id: str,
        user_id: str,
        session_id: str,
        role: str,
        tenant_config: TenantConfig,  # 含 bailian_app_id, system_prompt 等
        db: AsyncSession,
        redis: Redis
    ):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.session_id = session_id
        self.role = role
        self.tenant_config = tenant_config
        self.db = db
        self.redis = redis
    
    def build_messages(self, user_message: str) -> list[dict]:
        """构建 LLM 消息列表（含 system prompt + 历史消息）"""
        messages = [
            {"role": "system", "content": self.tenant_config.system_prompt}
        ]
        # 加载对话历史（从 Redis 或数据库）
        messages.extend(self._load_history())
        messages.append({"role": "user", "content": user_message})
        return messages
```

### 4.3 租户 Tool 配置加载

```python
# packages/hermes_agent/config.py

async def load_tenant_tools(tenant_id: str, service_type: str, db: AsyncSession) -> list[dict]:
    """
    加载租户的 Tool 配置
    - 每个租户可启用/禁用特定 Tool
    - 不同 service_type（chat/admin）加载不同 Tool 集
    """
    tenant_config = await db.execute(
        select(TenantConfig).where(
            TenantConfig.tenant_id == tenant_id,
            TenantConfig.service_type == service_type
        )
    )
    
    config = tenant_config.scalar_one_or_none()
    if not config:
        # 使用默认 Tool 集
        return ToolRegistry.get_tools_for_role("customer" if service_type == "chat" else "admin")
    
    # 按租户配置过滤
    enabled_tools = config.enabled_tools  # ["order_query", "product_search", ...]
    return [
        tool_cls({}).to_function_schema()
        for name, tool_cls in ToolRegistry._tools.items()
        if name in enabled_tools
    ]
```

---

## 5. Tool 示例实现

### 5.1 订单查询 Tool

```python
# ai-agent-service/app/tools/order_query.py

from packages.hermes_tools.base import BaseTool, ToolResult
from packages.hermes_tools.registry import ToolRegistry

@ToolRegistry.register
class OrderQueryTool(BaseTool):
    """订单查询 Tool"""
    
    name = "order_query"
    description = "查询订单状态、详情和物流信息。当用户询问订单相关问题时调用此工具。"
    parameters = {
        "type": "object",
        "properties": {
            "order_id": {
                "type": "string",
                "description": "订单号，例如 ORD12345"
            }
        },
        "required": ["order_id"]
    }
    require_auth = True
    allowed_roles = ["customer", "admin"]
    
    # C 端用户只能查自己的订单，管理员可查租户内全部订单
    data_scope = "self"
    
    # 字段脱敏：C 端用户不显示成本价，管理员不显示用户手机号
    field_masking = {
        "customer": ["cost_price"],
        "admin": ["user_phone"],
    }
    
    async def execute(self, order_id: str, context_role: str = "customer") -> ToolResult:
        # 查询数据库（自动带 tenant_id 和 user_id 过滤）
        query = select(Order).where(Order.id == order_id)
        query = self.apply_data_scope(query, Order)
        
        result = await self.db.execute(query)
        order = result.scalar_one_or_none()
        
        if not order:
            return ToolResult(
                success=False,
                error="订单不存在，请检查订单号是否正确"
            )
        
        # 构建返回数据
        data = {
            "order_id": order.id,
            "status": order.status,
            "status_text": ORDER_STATUS_MAP[order.status],
            "items": [
                {"name": item.product_name, "quantity": item.quantity, "price": float(item.price)}
                for item in order.items
            ],
            "total_amount": float(order.total_amount),
            "created_at": order.created_at.isoformat(),
            "logistics": {
                "company": order.logistics_company,
                "tracking_no": order.tracking_no
            } if order.tracking_no else None
        }
        
        # 按角色脱敏
        data = self.mask_fields(data, context_role)
        
        return ToolResult(
            success=True,
            data=data,
            display={
                "type": "card",
                "template": "order_detail"
            }
        )
```

### 5.2 商品搜索 Tool

```python
# ai-agent-service/app/tools/product_search.py

@ToolRegistry.register
class ProductSearchTool(BaseTool):
    """商品搜索 Tool"""
    
    name = "product_search"
    description = "搜索窗帘/布料商品。支持按关键词、分类、价格范围搜索。当用户想找商品或询问有什么产品时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "搜索关键词，如'遮光'、'棉麻'"
            },
            "category": {
                "type": "string",
                "enum": ["遮光", "纱帘", "棉麻", "绒布", "提花", "印花"],
                "description": "商品分类"
            },
            "min_price": {
                "type": "number",
                "description": "最低价格（元/米）"
            },
            "max_price": {
                "type": "number",
                "description": "最高价格（元/米）"
            },
            "sort_by": {
                "type": "string",
                "enum": ["price_asc", "price_desc", "sales", "newest"],
                "description": "排序方式"
            }
        },
        "required": []
    }
    allowed_roles = ["customer", "admin"]
    
    # 商品搜索是租户级别，不限制用户个人
    data_scope = "tenant"
    
    # 字段脱敏：C 端用户不显示成本价和库存
    field_masking = {
        "customer": ["cost_price", "stock"],
    }
    
    async def execute(
        self, 
        keyword: str = None, 
        category: str = None,
        min_price: float = None, 
        max_price: float = None,
        sort_by: str = "sales",
        context_role: str = "customer"
    ) -> ToolResult:
        query = select(Product)
        query = self.apply_data_scope(query, Product)
        
        if keyword:
            query = query.where(Product.name.ilike(f"%{keyword}%"))
        if category:
            query = query.where(Product.category == category)
        if min_price is not None:
            query = query.where(Product.base_price >= min_price)
        if max_price is not None:
            query = query.where(Product.base_price <= max_price)
        
        # 排序
        sort_map = {
            "price_asc": Product.base_price.asc(),
            "price_desc": Product.base_price.desc(),
            "sales": Product.sales_count.desc(),
            "newest": Product.created_at.desc()
        }
        query = query.order_by(sort_map.get(sort_by, Product.sales_count.desc()))
        query = query.limit(10)
        
        results = await self.db.execute(query)
        products = results.scalars().all()
        
        # 构建返回数据并脱敏
        product_list = []
        for p in products:
            item = {
                "id": p.id,
                "name": p.name,
                "category": p.category,
                "base_price": float(p.base_price),
                "description": p.short_description,
            }
            # stock 和 cost_price 会被 field_masking 处理
            if "stock" not in self.field_masking.get(context_role, []):
                item["in_stock"] = p.stock > 0
            product_list.append(item)
        
        return ToolResult(
            success=True,
            data={
                "total": len(product_list),
                "products": product_list
            },
            display={
                "type": "card",
                "template": "product_list"
            }
        )
```

### 5.3 知识库查询 Tool（自托管 RAG — DashVector + 混合检索）

```python
# ai-agent-service/app/tools/knowledge_search.py

from packages.hermes_tools.base import BaseTool, ToolResult
from packages.hermes_tools.registry import ToolRegistry

@ToolRegistry.register
class KnowledgeSearchTool(BaseTool):
    """面料知识库查询 Tool — 使用 DashVector + BM25 混合检索"""
    
    name = "knowledge_search"
    description = "查询面料/窗帘相关的专业知识。当用户咨询面料材质、保养方法、搭配建议等专业问题时调用。使用 DashVector 向量数据库 + BM25 混合检索。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "查询问题，如'遮光布和全遮光有什么区别'"
            }
        },
        "required": ["query"]
    }
    allowed_roles = ["customer", "admin"]
    
    async def execute(self, query: str) -> ToolResult:
        # 加载租户的 RAG 配置
        rag_config = await self._get_tenant_rag_config()
        if not rag_config or not rag_config.dashvector_collection:
            return ToolResult(
                success=False,
                error="知识库未配置"
            )
        
        # 使用 HybridRetriever 进行混合检索（向量 + BM25）
        from app.rag.retriever import HybridRetriever
        
        retriever = HybridRetriever(
            dashvector_collection=rag_config.dashvector_collection,
            bm25_index=rag_config.bm25_index,
            vector_weight=0.6,
            text_weight=0.4,
            top_k=3
        )
        
        results = await retriever.search(query)
        
        if not results:
            return ToolResult(
                success=True,
                data={"answer": "抱歉，暂未找到相关知识。建议联系客服人员获取专业解答。", "sources": []}
            )
        
        # 将检索结果组装为 LLM 可读的上下文
        contexts = []
        sources = []
        for r in results:
            contexts.append(f"[{r.metadata.get('title', '')}]\n{r.content}")
            sources.append({
                "title": r.metadata.get("title", ""),
                "relevance": r.score,
                "document_id": r.metadata.get("document_id", ""),
                "chunk_id": r.id
            })
        
        return ToolResult(
            success=True,
            data={
                "contexts": contexts,
                "sources": sources
            }
        )
```

**检索架构说明**：

| 组件 | 说明 |
|------|------|
| `DashVector` | 阿里云向量数据库，存储文档 chunk 的 embedding |
| `BM25` | 全文检索引擎，存储文档 chunk 的倒排索引 |
| `HybridRetriever` | 混合检索器，对向量检索和 BM25 结果加权融合 |
| `FabricChunker` | 文档分块器，针对面料/窗帘文档优化的分块策略（按段落、标题、表格边界分割） |

**文档管理 API**：
- `POST /api/admin/knowledge/documents` — 上传/更新文档（自动调用 FabricChunker 分块后写入 DashVector + BM25 索引）
- `GET /api/admin/knowledge/documents` — 查询已上传的文档列表
- `DELETE /api/admin/knowledge/documents/{doc_id}` — 删除文档及对应索引

### 5.4 转接人工 Tool

```python
# ai-agent-service/app/tools/human_handoff.py

@ToolRegistry.register
class HumanHandoffTool(BaseTool):
    """转接人工客服 Tool"""
    
    name = "human_handoff"
    description = "将对话转接给人工客服。当用户明确要求人工服务、或问题超出AI处理能力时调用。"
    parameters = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "转接原因，如'用户要求人工服务'、'退款金额纠纷'"
            },
            "priority": {
                "type": "string",
                "enum": ["low", "normal", "high", "urgent"],
                "description": "优先级"
            }
        },
        "required": ["reason"]
    }
    allowed_roles = ["customer"]
    
    async def execute(self, reason: str, priority: str = "normal") -> ToolResult:
        # 创建工单 / 推送到客服队列
        ticket = await self.db.execute(
            insert(ServiceTicket).values(
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                reason=reason,
                priority=priority,
                status="pending"
            )
        )
        
        return ToolResult(
            success=True,
            data={
                "ticket_id": ticket.inserted_primary_key[0],
                "message": "已为您转接人工客服，请稍候。",
                "estimated_wait": "约 2-5 分钟"
            }
        )
```

---

## 6. Tool 目录结构

```
ai-agent-service/
├── app/
│   ├── tools/                      # 客服 Tool 实现
│   │   ├── __init__.py             # 自动注册所有 Tool
│   │   ├── order_query.py
│   │   ├── order_list.py
│   │   ├── logistics_track.py
│   │   ├── product_search.py
│   │   ├── product_detail.py
│   │   ├── product_recommend.py
│   │   ├── after_sales_create.py
│   │   ├── after_sales_query.py
│   │   ├── knowledge_search.py
│   │   └── human_handoff.py
│   └── ...

ai-agent-service/
├── app/
│   ├── tools/                      # 管理助手 Tool 实现
│   │   ├── __init__.py
│   │   ├── stats_orders.py
│   │   ├── stats_products.py
│   │   ├── stats_customers.py
│   │   ├── report_generate.py
│   │   ├── inventory_alert.py
│   │   └── knowledge_manage.py
│   └── ...

packages/
├── hermes_agent/                   # 共享 Agent 框架
│   ├── agent.py                    # HermesAgent 主循环
│   ├── context.py                  # AgentContext
│   └── config.py                   # 租户配置加载
└── hermes_tools/                   # 共享 Tool 基础
    ├── base.py                     # BaseTool + ToolResult
    └── registry.py                 # ToolRegistry
```

**自动注册**：

```python
# ai-agent-service/app/tools/__init__.py

# 导入即注册（@ToolRegistry.register 装饰器）
from .order_query import OrderQueryTool
from .order_list import OrderListTool
from .logistics_track import LogisticsTrackTool
from .product_search import ProductSearchTool
from .product_detail import ProductDetailTool
from .product_recommend import ProductRecommendTool
from .after_sales_create import AfterSalesCreateTool
from .after_sales_query import AfterSalesQueryTool
from .knowledge_search import KnowledgeSearchTool
from .human_handoff import HumanHandoffTool
```

---

## 7. SSE 事件与 Tool 执行的映射

Tool 执行过程通过 SSE 事件流实时反馈给前端：

```
event: message
data: {"type": "loading", "content": "正在查询订单..."}      ← Tool 开始执行

event: message
data: {"type": "card", "template": "order_detail", "data": {...}}  ← Tool 返回 display

event: message
data: {"type": "text", "content": "您的订单 ORD12345 已发货..."}    ← LLM 基于 Tool 结果生成回复

event: done
data: {"session_id": "sess_abc123"}                            ← Agent 循环结束
```

**多 Tool 调用示例**（用户："帮我查下订单 12345 的物流"）：

```
event: message
data: {"type": "loading", "content": "正在查询订单..."}

event: message
data: {"type": "loading", "content": "正在查询物流信息..."}

event: message
data: {"type": "card", "template": "logistics_detail", "data": {"company": "顺丰", "tracking_no": "SF123..."}}

event: message
data: {"type": "text", "content": "您的订单 ORD12345 已由顺丰快递发出，当前包裹在杭州转运中，预计明天送达。"}

event: done
data: {"session_id": "sess_abc123"}
```

---

## 8. Tool 开发规范

### 8.1 必须遵守

| 规则 | 说明 |
|------|------|
| 租户隔离 | 所有数据库查询必须带 `self.tenant_id` 过滤 |
| 异常处理 | 不抛异常，返回 `ToolResult(success=False, error="...")` |
| 超时控制 | 框架层 30 秒超时，Tool 内部应更快返回 |
| 幂等性 | 同样的参数多次调用应产生相同结果（查询类 Tool） |
| 最小权限 | `allowed_roles` 只授予必要角色 |

### 8.2 description 编写指南

好的 description 直接影响 LLM 的 Tool 调用准确率：

```python
# 好的 description — 清晰说明「做什么」和「什么时候用」
description = "查询订单状态、详情和物流信息。当用户询问订单相关问题时调用此工具。"

# 差的 description — 模糊、没有调用时机
description = "订单查询"
```

### 8.3 添加新 Tool 的步骤

1. 在 `app/tools/` 下创建新文件（如 `coupon_query.py`）
2. 继承 `BaseTool`，定义 `name`, `description`, `parameters`
3. 实现 `execute()` 方法
4. 添加 `@ToolRegistry.register` 装饰器
5. 在 `__init__.py` 中 import
6. 重启服务 — Tool 自动注册到 Hermes Agent
