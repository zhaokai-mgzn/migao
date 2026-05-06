# Tool 执行流程文档

本文档说明 AI Agent 系统中 Tool 的完整执行流程。

## 概述

Tool 执行涉及多个组件的协作：
- **Tool 定义**: 业务逻辑实现
- **Tool Registry**: Tool 注册和管理
- **LangChain Adapter**: 框架适配层
- **Skill 执行器**: 调用 Tool 的入口

## 核心组件

### 1. BaseTool (工具基类)

**文件**: `app/tools/base.py`

所有 Tool 必须继承 `BaseTool` 并实现：
- `name`: Tool 名称
- `description`: Tool 描述
- `parameters`: JSON Schema 参数定义
- `execute()`: 执行逻辑

```python
class ProductSearchTool(BaseTool):
    name = "product_search"
    description = "搜索商品列表"
    parameters = {...}
    
    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        # 实现搜索逻辑
        return ToolResult(success=True, data={...})
```

### 2. ToolContext (执行上下文)

**文件**: `app/tools/base.py`

包含执行所需的环境信息：
- `tenant_id`: 租户 ID（用于多租户隔离）
- `user_id`: 用户 ID
- `session_id`: 会话 ID
- `role`: 用户角色

### 3. ToolRegistry (工具注册器)

**文件**: `app/tools/registry.py`

职责：
- 注册和管理所有 Tool
- 提供 Tool 查询接口
- 生成 LangChain 兼容的 Tool

关键方法：
```python
registry = ToolRegistry()
registry.register(ProductSearchTool())

# 获取 LangChain Tools
langchain_tools = registry.get_langchain_tools()
```

### 4. LangChainToolAdapter (框架适配器)

**文件**: `app/tools/langchain_adapter.py`

职责：
- 将 BaseTool 转换为 LangChain StructuredTool
- 处理参数 schema 转换
- 注入 ToolContext

关键流程：
```python
# 1. 从 JSON Schema 生成 Pydantic 模型
args_schema = LangChainToolAdapter.build_args_schema(tool)

# 2. 创建 LangChain Tool
lc_tool = LangChainToolAdapter.create_langchain_tool(
    tool=tool,
    get_context_func=get_tool_context,
)
```

### 5. ContextVars (上下文传递)

**文件**: `app/tools/registry.py`

使用 Python contextvars 在异步调用链中传递 ToolContext：

```python
# 设置上下文
set_tool_context(context)

# 在 LangChain Tool 中获取上下文
ctx = get_tool_context()
```

## 执行流程

### 完整调用链

```
1. Chat API 接收请求
   ↓
2. 构建 AgentGraph (builder.py)
   ↓
3. 执行 Skill (base_skill.py)
   ↓
4. 设置 ToolContext (registry.py)
   ↓
5. LangGraph 调用 LangChain Tool
   ↓
6. LangChainToolAdapter 拦截调用
   ↓
7. 从 contextvars 获取 ToolContext
   ↓
8. 调用真实的 BaseTool.execute()
   ↓
9. 返回 ToolResult（JSON 序列化）
```

### 详细步骤

#### 步骤 1: 构建 Agent 图

```python
# app/graph/builder.py
graph = build_agent_graph("xiaobu")
# 注册 Tool 到图中
tools = registry.get_langchain_tools()
```

#### 步骤 2: Skill 执行

```python
# app/graph/skills/base_skill.py
async def execute_skill(state: AgentState):
    # 从 state 构建 context
    context = build_tool_context(state)
    
    # 设置全局 context
    set_tool_context(context)
    
    # LangGraph 会调用 LangChain Tool
    # ...
```

#### 步骤 3: LangChain Tool 调用

```python
# app/tools/langchain_adapter.py
async def _execute(**kwargs):
    # 1. 获取上下文
    ctx = get_tool_context()
    if ctx is None:
        return {"success": False, "error": "No tool context"}
    
    # 2. 调用真实 Tool
    result = await tool.execute(ctx, **kwargs)
    
    # 3. 返回 JSON 结果
    return json.dumps({
        "success": result.success,
        "data": result.data,
        "error": result.error,
    })
```

#### 步骤 4: Tool 业务逻辑

```python
# app/tools/product_search.py
async def execute(self, context: ToolContext, keyword: str = "") -> ToolResult:
    # 1. 权限检查
    if not self.check_permission(context):
        return ToolResult(success=False, error="Permission denied")
    
    # 2. 调用 admin-api
    client = get_admin_api_client()
    response = await client.get("/api/admin/products", params={
        "keyword": keyword,
        "tenantId": context.tenant_id,
    })
    
    # 3. 格式化结果
    products = self._format_products(response["data"]["items"])
    
    # 4. 返回结果
    return ToolResult(success=True, data={"products": products})
```

## 数据流

### 请求参数流

```
用户输入 → LLM 解析 → Tool 参数 → LangChain Tool
                                      ↓
                              LangChainToolAdapter
                                      ↓
                              get_tool_context()
                                      ↓
                              BaseTool.execute(context, **kwargs)
```

### 响应数据流

```
BaseTool.execute() → ToolResult
                        ↓
                json.dumps() (序列化)
                        ↓
                LangChain Tool 返回字符串
                        ↓
                Skill 解析结果
                        ↓
                更新 AgentState
```

## 多租户隔离

所有 Tool 执行都必须携带 `tenant_id`：

1. **设置上下文时**:
   ```python
   context = ToolContext(
       tenant_id=user.tenant_id,
       user_id=user.id,
       session_id=session.id,
   )
   set_tool_context(context)
   ```

2. **Tool 执行时**:
   ```python
   # 调用 admin-api 时传递 tenant_id
   response = await client.get("/api/products", params={
       "tenantId": context.tenant_id,
   })
   
   # 验证返回数据属于当前租户
   for item in response["data"]:
       if item.get("tenantId") != context.tenant_id:
           raise SecurityError("Tenant isolation violated")
   ```

## 错误处理

### 统一错误格式

所有 Tool 返回 `ToolResult`：

```python
ToolResult(
    success=True/False,
    data={...},           # 成功时的数据
    error="error_code",   # 错误代码（机器可读）
    message="提示信息",    # 用户可读的提示
)
```

### 异常处理层级

1. **Tool 内部异常**: Tool 自己捕获并返回 ToolResult
2. **Adapter 层异常**: LangChainToolAdapter 捕获并返回 JSON 错误
3. **Registry 层异常**: execute_tool() 方法处理

## 最佳实践

### 1. Tool 实现规范

```python
class MyTool(BaseTool):
    name = "my_tool"
    description = "清晰的描述"
    parameters = {
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "参数说明"}
        },
        "required": ["param1"]
    }
    
    async def execute(self, context: ToolContext, param1: str) -> ToolResult:
        try:
            # 业务逻辑
            return ToolResult(success=True, data={...})
        except SpecificError as e:
            return ToolResult(
                success=False,
                error="specific_error",
                message=f"操作失败：{str(e)}"
            )
        except Exception as e:
            logger.error(f"Tool failed: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="internal_error",
                message="系统错误，请稍后重试"
            )
```

### 2. 字段映射规范

使用 `FieldMapper` 处理不同服务间的字段差异：

```python
from app.utils.field_mapper import FieldMapper

# Java -> Python
product = {
    "price": FieldMapper.get_price(record),
    "main_image": FieldMapper.get_main_image(record),
    "category_id": FieldMapper.get_category_id(record),
}
```

### 3. 日志规范

```python
# Tool 执行开始
logger.info(f"[tool-registry] Executing: {tool.name} | tenant={ctx.tenant_id}")

# Tool 执行完成
logger.info(f"[tool-registry] Completed: {tool.name} | success={result.success} duration={duration_ms:.1f}ms")

# Tool 执行失败
logger.error(f"[tool-registry] Failed: {tool.name} | tenant={tenant_id} error={type(e).__name__}: {e}", exc_info=True)
```

## 测试要点

### 单元测试

```python
@patch("app.tools.product_search.get_admin_api_client")
async def test_product_search_success(self, mock_get_client, tool, sample_tool_context):
    # Mock API 响应
    mock_client.get = AsyncMock(return_value={...})
    
    # 执行 Tool
    result = await tool.execute(
        context=sample_tool_context,
        keyword="窗帘",
    )
    
    # 验证结果
    assert result.success is True
    assert len(result.data["products"]) == 2
```

### 集成测试

- 测试 ToolContext 正确传递
- 测试多租户隔离
- 测试错误处理

## 相关文档

- [Tool 基类定义](../app/tools/base.py)
- [Tool 注册器](../app/tools/registry.py)
- [LangChain 适配器](../app/tools/langchain_adapter.py)
- [字段映射工具](../app/utils/field_mapper.py)
