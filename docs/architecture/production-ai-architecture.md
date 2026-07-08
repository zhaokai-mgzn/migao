> **注意**: 本文档为备选技术方案，仅供参考。当前项目已采用 **LangGraph StateGraph** 工作流方案（详见 [`docs/wiki/AI-Agent.md`](../wiki/AI-Agent.md)）。本文档描述的 Hermes Agent 和确定性架构均为 v8.0 时期的历史方案对比，不代表当前实现。

---

# 生产级 AI 客服架构 (历史参考)

> 版本：v8.0（备选参考方案，已归档）  
> 日期：2026-04-12  
> 核心原则：确定性优先于灵活性，可预测 > 可进化

---

## 一、为什么不选纯 Agent 框架

基于 Hermes Agent 等纯 LLM Function Calling 框架存在以下生产环境风险：

| 风险 | 表现 | 影响 |
|------|------|------|
| Tool 选择不确定 | LLM 可能调错 Tool（10 个以上 Tool 时显著） | 用户查订单，AI 去搜商品 |
| 参数遗漏 | LLM 可能漏传必填参数 | Tool 执行失败，用户体验差 |
| 版本不稳定 | Hermes v0.8，未达 1.0 | API breaking change，维护成本高 |
| 自进化不可控 | 积累大量对话后才见效 | 初期无价值，增加调试难度 |
| 调试困难 | LLM 决策过程不透明 | 出问题难以定位是 prompt 问题还是 Tool 问题 |

**生产环境的底线要求**：
1. 每次请求调用了哪个 Tool、传了什么参数、返回了什么结果，必须可追溯
2. Tool 调用失败时必须有明确的降级路径，不能让用户看到一个"我不知道你在说什么"
3. 意图识别准确率必须 >95%，不能靠"大模型大概能猜到"

---

## 二、生产级架构设计

### 2.1 整体架构

```
用户消息
  │
  ▼
┌──────────────────────────────────────┐
│  第一层：意图分类（确定性路由）         │
│  规则匹配 → 关键词/正则（优先级最高）    │
│  ↓ 未命中                              │
│  LLM 分类 → 从预定义意图列表中选择      │
│  ↓ 置信度 < 阈值                       │
│  降级为自由对话                        │
└────────────────┬─────────────────────┘
                 │ 确定的意图：order_query
                 ▼
┌──────────────────────────────────────┐
│  第二层：参数提取与校验                │
│  LLM 提取参数 → Pydantic Schema 校验  │
│  参数缺失 → 追问用户                  │
│  参数完整 → 进入执行层                │
└────────────────┬─────────────────────┘
                 │ 已校验的参数
                 ▼
┌──────────────────────────────────────┐
│  第三层：Tool 执行（确定性调用）        │
│  意图 → Tool 一对一映射               │
│  执行超时 30s → 重试 1 次             │
│  执行失败 → 返回预定义错误提示         │
└────────────────┬─────────────────────┘
                 │ Tool 结果
                 ▼
┌──────────────────────────────────────┐
│  第四层：响应生成                      │
│  结构化结果 → LLM 生成自然语言回复    │
│  附带 display 数据（卡片/推荐）        │
│  流式 SSE 输出                       │
└────────────────┬─────────────────────┘
                 │
                 ▼
              用户收到回复
```

**与 Hermes Agent 的核心区别**：

| 维度 | Hermes Agent（纯 Function Calling） | 生产级架构（确定性路由） |
|------|-----------------------------------|------------------------|
| 意图识别 | LLM 自由选择 Tool | 规则优先 + LLM 分类 + 阈值兜底 |
| Tool 路由 | LLM 自主决定调哪个 | 意图 → Tool 一对一映射，固定 |
| 参数校验 | LLM 自己判断 | Pydantic Schema 强制校验 |
| 失败处理 | 依赖 LLM 重试 | 确定性的重试/降级/人工转接 |
| 可追溯性 | LLM 决策过程黑盒 | 每步都有明确的日志记录 |

### 2.2 意图分类层

```python
# app/intent/classifier.py

from typing import Optional
from pydantic import BaseModel

class IntentResult(BaseModel):
    intent: str          # 意图名称
    confidence: float    # 置信度 0-1
    source: str          # "rule" | "llm" | "fallback"

class IntentClassifier:
    """意图分类器 — 规则优先，LLM 兜底"""
    
    # 规则匹配（优先级最高，零延迟）
    RULES = {
        "order_query": {
            "keywords": ["订单", "快递", "物流", "到哪了", "发货", "快递单号"],
            "patterns": [r"ORD\d+", r"订单\s*[#号]?\s*\d+"]
        },
        "logistics_track": {
            "keywords": ["物流查询", "快递轨迹", "包裹位置", "到哪了", "运单"],
            "patterns": [r"SF\d+", r"YT\d+"]  # 顺丰/圆通单号
        },
        "product_search": {
            "keywords": ["产品", "商品", "有什么", "推荐", "价格", "多少钱"],
            "patterns": []
        },
        "after_sales": {
            "keywords": ["退货", "换货", "退款", "售后", "维修", "质量问题"],
            "patterns": []
        },
        "human_handoff": {
            "keywords": ["人工", "客服", "转人工", "投诉"],
            "patterns": []
        }
    }
    
    async def classify(self, user_input: str, context: dict = None) -> IntentResult:
        # 第一步：规则匹配
        rule_result = self._match_rules(user_input)
        if rule_result:
            return rule_result
        
        # 第二步：LLM 分类
        llm_result = await self._llm_classify(user_input)
        if llm_result.confidence >= 0.7:
            return llm_result
        
        # 第三步：低置信度 → 自由对话
        return IntentResult(
            intent="free_chat",
            confidence=0.0,
            source="fallback"
        )
    
    def _match_rules(self, user_input: str) -> Optional[IntentResult]:
        import re
        for intent, config in self.RULES.items():
            # 关键词匹配
            for kw in config["keywords"]:
                if kw in user_input.lower():
                    return IntentResult(
                        intent=intent,
                        confidence=0.95,  # 规则匹配置信度高
                        source="rule"
                    )
            # 正则匹配
            for pattern in config["patterns"]:
                if re.search(pattern, user_input, re.IGNORECASE):
                    return IntentResult(
                        intent=intent,
                        confidence=0.98,
                        source="rule"
                    )
        return None
    
    async def _llm_classify(self, user_input: str) -> IntentResult:
        """调用 LLM 做意图分类"""
        system_prompt = """你是一个意图分类器。请将用户输入分类到以下意图之一：
- order_query: 查询订单状态
- logistics_track: 查询物流轨迹
- product_search: 搜索商品
- after_sales: 售后相关
- human_handoff: 要求人工服务
- free_chat: 闲聊或无法分类

只返回 JSON: {"intent": "intent_name", "confidence": 0.9}"""
        
        response = await self.llm.chat(system_prompt, user_input)
        # 解析 JSON 响应
        ...
```

### 2.3 参数提取与校验层

```python
# app/param/extractor.py

from pydantic import BaseModel, Field, ValidationError

# 每个 Tool 定义自己的参数 Schema
class OrderQueryParams(BaseModel):
    order_id: str = Field(..., description="订单号", min_length=3)

class ProductSearchParams(BaseModel):
    keyword: str | None = Field(None, description="搜索关键词")
    category: str | None = Field(None, description="分类")
    min_price: float | None = Field(None, ge=0, description="最低价")
    max_price: float | None = Field(None, ge=0, description="最高价")

class AfterSalesParams(BaseModel):
    order_id: str | None = Field(None, description="关联订单号")
    type: str = Field(..., description="售后类型: refund/exchange/repair")
    reason: str = Field(..., description="原因描述", min_length=5)

class ParamExtractor:
    """参数提取器 — LLM 提取 + Pydantic 校验"""
    
    # 意图到参数 Schema 的映射
    PARAM_SCHEMAS = {
        "order_query": OrderQueryParams,
        "product_search": ProductSearchParams,
        "after_sales": AfterSalesParams,
    }
    
    async def extract_and_validate(
        self, 
        intent: str, 
        user_input: str, 
        context: dict
    ) -> tuple[BaseModel | None, str | None]:
        """
        返回: (校验通过的参数, 追问提示)
        如果参数完整，追问提示为 None
        如果参数缺失，参数为 None，追问提示为追问文案
        """
        schema = self.PARAM_SCHEMAS.get(intent)
        if not schema:
            return None, None  # 自由对话，不需要参数
        
        # LLM 提取参数
        raw_params = await self._llm_extract(intent, user_input, context)
        
        # Pydantic 校验
        try:
            params = schema(**raw_params)
            return params, None
        except ValidationError as e:
            # 必填字段缺失
            missing_fields = [err["loc"][0] for err in e.errors() if err["type"] == "missing"]
            if missing_fields:
                field = missing_fields[0]
                prompt = self._get_missing_param_prompt(field, intent)
                return None, prompt
            
            # 格式错误
            return None, "参数格式有误，请重新输入"
    
    async def _llm_extract(self, intent: str, user_input: str, context: dict) -> dict:
        """用 LLM 从对话中提取参数"""
        system_prompt = f"""从以下对话中提取 {intent} 所需的参数。
如果参数无法从对话中获取，设为 null。
只返回 JSON。"""
        
        # 如果上下文中有订单号等，一并传入
        context_info = f"上下文：{context}" if context else ""
        return await self.llm.extract_params(
            system_prompt,
            f"{context_info}\n用户说：{user_input}"
        )
    
    def _get_missing_param_prompt(self, field: str, intent: str) -> str:
        prompts = {
            ("order_query", "order_id"): "请提供您的订单号，通常在订单确认短信或邮件中可以找到（以 ORD 开头）",
            ("after_sales", "type"): "请问您需要退货、换货还是维修？",
            ("after_sales", "reason"): "请简单描述一下您遇到的问题",
        }
        return prompts.get((intent, field), f"请提供{field}")
```

### 2.4 Tool 执行层

```python
# app/tools/base.py

from abc import ABC, abstractmethod
from typing import Any
from pydantic import BaseModel
import asyncio

class ToolResult(BaseModel):
    success: bool
    data: Any = None
    error: str | None = None
    display: dict | None = None

class BaseTool(ABC):
    """Tool 基类"""
    
    name: str = ""
    description: str = ""
    timeout: int = 30  # 秒
    max_retries: int = 1
    
    async def execute_safe(self, **kwargs) -> ToolResult:
        """安全执行：带超时和重试"""
        for attempt in range(self.max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    self._execute(**kwargs),
                    timeout=self.timeout
                )
                return result
            except asyncio.TimeoutError:
                if attempt == self.max_retries:
                    return ToolResult(
                        success=False,
                        error="请求超时，请稍后重试"
                    )
            except Exception as e:
                import logging
                logging.error(f"Tool {self.name} 执行失败: {e}", exc_info=True)
                if attempt == self.max_retries:
                    return ToolResult(
                        success=False,
                        error="系统繁忙，请稍后重试"
                    )
    
    @abstractmethod
    async def _execute(self, **kwargs) -> ToolResult:
        pass


# app/tools/order_query.py

class OrderQueryTool(BaseTool):
    name = "order_query"
    description = "查询订单状态和详情"
    
    async def _execute(self, order_id: str, tenant_id: str, user_id: str) -> ToolResult:
        # 数据库查询（强制租户隔离 + 用户隔离）
        order = await self.db.execute(
            select(Order).where(
                Order.id == order_id,
                Order.tenant_id == tenant_id,
                Order.user_id == user_id  # C 端用户只能查自己的
            )
        ).scalar_one_or_none()
        
        if not order:
            return ToolResult(
                success=False,
                error="未找到该订单，请检查订单号是否正确"
            )
        
        return ToolResult(
            success=True,
            data={
                "order_id": order.id,
                "status": order.status,
                "status_text": STATUS_MAP.get(order.status, order.status),
                "items": order.items,
                "total_amount": float(order.total_amount),
                "created_at": order.created_at.isoformat()
            },
            display={
                "type": "card",
                "template": "order_detail"
            }
        )
```

### 2.5 响应生成层

```python
# app/chat/response_generator.py

class ResponseGenerator:
    """根据 Tool 执行结果生成用户可读的回复"""
    
    async def generate(self, intent: str, tool_result: ToolResult, context: dict) -> str:
        if not tool_result.success:
            return self._handle_error(intent, tool_result.error, context)
        
        return await self._llm_generate(intent, tool_result.data, context)
    
    def _handle_error(self, intent: str, error: str, context: dict) -> str:
        """错误回复 — 使用预定义模板，不依赖 LLM"""
        error_templates = {
            "order_query": "抱歉，{error}。您可以检查订单号是否正确，或在「我的订单」页面查看。",
            "product_search": "抱歉，暂时没有找到匹配的商品。您可以换个关键词试试。",
            "after_sales": "抱歉，售后申请暂时失败，{error}。您可以转接人工客服处理。",
            "default": "抱歉，{error}。请稍后重试或转接人工客服。"
        }
        template = error_templates.get(intent, error_templates["default"])
        return template.format(error=error)
    
    async def _llm_generate(self, intent: str, data: dict, context: dict) -> str:
        """用 LLM 将结构化数据转为自然语言"""
        system_prompt = f"""你是一个客服助手。根据以下数据生成简洁友好的回复。
不要添加数据中没有的信息。如果数据中有物流信息，提醒用户注意查收。"""
        
        user_prompt = f"意图：{intent}\n数据：{json.dumps(data, ensure_ascii=False)}"
        return await self.llm.chat(system_prompt, user_prompt)
```

### 2.6 主流程编排

```python
# app/chat/engine.py

class ChatEngine:
    """客服对话引擎 — 确定性流程"""
    
    def __init__(self):
        self.classifier = IntentClassifier()
        self.extractor = ParamExtractor()
        self.response_gen = ResponseGenerator()
        self.tools = {
            "order_query": OrderQueryTool(),
            "logistics_track": LogisticsTrackTool(),
            "product_search": ProductSearchTool(),
            "product_detail": ProductDetailTool(),
            "after_sales": AfterSalesTool(),
            "human_handoff": HumanHandoffTool(),
        }
    
    async def process_message(
        self, 
        user_input: str, 
        context: ChatContext
    ) -> AsyncIterator[SSEEvent]:
        """处理用户消息，SSE 流式输出"""
        
        # 第一层：意图分类
        intent_result = await self.classifier.classify(user_input)
        context.log(f"意图识别: {intent_result.intent} ({intent_result.confidence:.2f}, {intent_result.source})")
        
        # 自由对话 → 直接 LLM 回复
        if intent_result.intent == "free_chat":
            yield SSEEvent(type="loading", content="正在思考...")
            async for chunk in await self._free_chat(user_input, context):
                yield SSEEvent(type="text", content=chunk)
            yield SSEEvent(type="done", session_id=context.session_id)
            return
        
        # 第二层：参数提取
        tool = self.tools.get(intent_result.intent)
        if not tool:
            # 识别到意图但没有对应 Tool → 降级为自由对话
            yield SSEEvent(type="loading", content="正在处理...")
            async for chunk in await self._free_chat(user_input, context):
                yield SSEEvent(type="text", content=chunk)
            yield SSEEvent(type="done", session_id=context.session_id)
            return
        
        params, missing_prompt = await self.extractor.extract_and_validate(
            intent_result.intent, user_input, context.variables
        )
        
        if missing_prompt:
            # 参数缺失 → 追问
            yield SSEEvent(type="text", content=missing_prompt)
            yield SSEEvent(type="done", session_id=context.session_id)
            return
        
        # 第三层：Tool 执行
        yield SSEEvent(type="loading", content=f"正在查询{tool.description}...")
        
        tool_result = await tool.execute_safe(
            **params.model_dump(),
            tenant_id=context.tenant_id,
            user_id=context.user_id
        )
        
        # 记录 Tool 执行日志（用于监控和优化）
        await self._log_tool_execution(context, intent_result.intent, params, tool_result)
        
        if not tool_result.success:
            # Tool 执行失败 → 使用预定义错误模板
            error_reply = self.response_gen._handle_error(
                intent_result.intent, tool_result.error, context.variables
            )
            yield SSEEvent(type="text", content=error_reply)
            # 提供转人工入口
            yield SSEEvent(
                type="recommend", 
                items=[{"id": "human", "name": "转人工客服", "prompt": "转人工"}]
            )
            yield SSEEvent(type="done", session_id=context.session_id)
            return
        
        # Tool 有卡片展示
        if tool_result.display:
            yield SSEEvent(type="card", data=tool_result.display)
        
        # 第四层：生成自然语言回复
        reply = await self.response_gen.generate(
            intent_result.intent, tool_result, context.variables
        )
        yield SSEEvent(type="text", content=reply)
        
        # 推荐后续操作
        recommendations = self._get_recommendations(intent_result.intent, tool_result.data)
        if recommendations:
            yield SSEEvent(type="recommend", items=recommendations)
        
        yield SSEEvent(type="done", session_id=context.session_id)
    
    async def _free_chat(self, user_input: str, context: ChatContext) -> AsyncIterator[str]:
        """自由对话 — LLM 直接回复"""
        system_prompt = context.tenant_config.system_prompt
        messages = context.build_messages(user_input)
        
        response = await self.llm.chat_completions(
            model="qwen-turbo",
            messages=messages,
            stream=True
        )
        async for chunk in response.stream_text():
            yield chunk
```

---

## 三、降级机制设计

### 3.1 降级链路

```
LLM 服务不可用
  │
  ▼
检查意图是否通过规则匹配
  │
  ├── 规则命中 → 直接执行 Tool（不经过 LLM）
  │              │
  │              ├── Tool 成功 → 使用预定义模板回复
  │              └── Tool 失败 → 返回预定义错误提示
  │
  └── 规则未命中 → 返回「系统繁忙，请稍后重试」
                    + 转人工入口
```

### 3.2 各层降级策略

| 层级 | 正常流程 | 降级方案 |
|------|---------|---------|
| 意图分类 | 规则 → LLM 分类 | 自由对话 / 系统繁忙提示 |
| 参数提取 | LLM 提取 → Pydantic 校验 | 追问用户补充信息 |
| Tool 执行 | 直接调用 | 超时重试 1 次 → 错误提示 + 转人工 |
| 响应生成 | LLM 自然语言 | 预定义模板（不依赖 LLM） |
| LLM 全挂 | 正常服务 | 规则匹配 + 模板回复 + 转人工 |

### 3.3 熔断机制

```python
# app/core/circuit_breaker.py

class CircuitBreaker:
    """LLM 服务熔断器"""
    
    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.failure_count = 0
        self.threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time = None
        self.state = "closed"  # closed → open → half-open
    
    def can_execute(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
                return True
            return False
        # half-open
        return True
    
    def record_success(self):
        self.failure_count = 0
        self.state = "closed"
    
    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.threshold:
            self.state = "open"
```

---

## 四、监控与告警

### 4.1 关键指标

| 指标 | 计算方式 | 告警阈值 | 说明 |
|------|---------|---------|------|
| 意图识别准确率 | 规则+LLM 命中 / 总请求 | < 90% | 低于此值需检查关键词库 |
| Tool 执行成功率 | 成功次数 / 总调用次数 | < 95% | 数据库或外部 API 异常 |
| LLM 调用失败率 | 失败次数 / 总调用次数 | > 5% | 百炼服务异常 |
| 平均响应时间 | 从用户输入到回复完成 | > 3s | 用户体验下降 |
| 降级触发率 | 降级次数 / 总请求 | > 10% | 系统不稳定 |
| 人工转接率 | 转人工次数 / 总对话 | > 15% | AI 能力不足 |

### 4.2 日志结构

```json
{
  "timestamp": "2026-04-11T10:30:00Z",
  "session_id": "sess_abc123",
  "tenant_id": "TENANT001",
  "user_id": "user_001",
  "user_input": "我的订单到哪了",
  "intent": {
    "name": "order_query",
    "confidence": 0.95,
    "source": "rule"
  },
  "params": {"order_id": "ORD12345"},
  "tool": {
    "name": "order_query",
    "success": true,
    "execution_time_ms": 230
  },
  "response": {
    "type": "card+text",
    "generation_time_ms": 1500
  },
  "total_time_ms": 2100,
  "fallback_used": false
}
```

---

## 五、与原 Hermes Agent 方案的对比

| 维度 | Hermes Agent（原方案） | 生产级架构（新方案） |
|------|----------------------|---------------------|
| 意图识别 | LLM 自由选择 Tool | 规则优先 + LLM 分类 + 阈值兜底 |
| Tool 路由 | 框架自动 | 意图 → Tool 一对一映射 |
| 参数校验 | 依赖 LLM | Pydantic 强制校验 |
| 失败处理 | 框架重试 | 确定性的降级链路 |
| 可追溯性 | LLM 决策黑盒 | 每步都有日志和指标 |
| 调试难度 | 高（需要理解 LLM 决策） | 低（规则/参数/Tool 分层排查） |
| LLM 依赖度 | 高（核心流程全靠 LLM） | 低（规则可覆盖大部分场景） |
| LLM 挂掉 | 服务完全不可用 | 规则匹配 + 模板回复，部分可用 |
| 新增 Tool | 注册即可，LLM 自动发现 | 需同时添加意图规则和参数 Schema |
| 灵活性 | 高（支持动态 Tool 链） | 中（每个意图对应一个 Tool） |
| 生产稳定性 | 中（v0.8，不确定） | 高（确定性流程） |

---

## 六、部署影响

现有部署架构完全不受影响。只需要将 ai-agent-service 中的 Hermes Agent 替换为上述确定性引擎。

```
packages/
├── intent/                    # 意图分类模块
│   ├── classifier.py          # 规则 + LLM 分类
│   └── config.py              # 意图规则配置
├── param/                     # 参数提取模块
│   ├── extractor.py           # LLM 提取 + Pydantic 校验
│   └── schemas.py             # 各 Tool 的参数 Schema
├── tools/                     # Tool 实现（保持不变）
│   ├── base.py
│   ├── order_query.py
│   └── ...
├── chat/                      # 对话引擎
│   ├── engine.py              # 主流程编排
│   ├── response_generator.py  # 响应生成
│   └── circuit_breaker.py     # 熔断器
└── middleware/                # 中间件（保持不变）
```

**迁移成本**：
- 已有 Tool 实现不需要改，只需确保 `execute_safe()` 方法存在
- 新增意图时需要在 `IntentClassifier.RULES` 中添加规则和关键词
- 新增 Tool 时需要在 `PARAM_SCHEMAS` 中添加对应的 Pydantic Schema
- 总体代码量与原方案相当，但可预测性和可控性大幅提升

---

## 七、渐进式迁移建议

如果之前已经开始基于 Hermes Agent 开发，可以按以下步骤迁移：

| 阶段 | 内容 | 验证标准 |
|------|------|---------|
| **Phase 1** | 实现 IntentClassifier 和关键词规则 | 规则覆盖 Top 5 意图，准确率 > 95% |
| **Phase 2** | 实现 ParamExtractor + Pydantic Schema | 参数校验 100% 通过，缺失参数能正确追问 |
| **Phase 3** | 实现 ChatEngine 替代 HermesAgent | 端到端对话测试通过，日志完整 |
| **Phase 4** | 实现熔断器和降级机制 | 模拟 LLM 宕机，系统仍可部分响应 |
| **Phase 5** | 下线 Hermes 依赖 | 移除 hermes 包，确认无残留 |
