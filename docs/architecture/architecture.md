# AI 智能客服系统 - 完整架构设计文档

> 版本：v8.0  
> 日期：2026-04-12  
> 状态：2 服务架构 + 租户自定义 AI 配置 + 公众号 OAuth + 自建 RAG（DashVector）+ 客服员工工作台

---

## 1. 项目概述

### 1.1 项目定位

一个面向通用行业的 AI 智能客服开源项目，以布艺行业（窗帘生产与家装）为示例场景。系统采用多租户 SaaS 架构，支持企业快速部署自己的 AI 客服和管理后台。

### 1.2 核心功能

| 模块 | 功能 | 用户 | 接入渠道 |
|------|------|------|---------|
| **AI 客服对话** | 订单查询、售前咨询、售后服务、物流查询 | 终端消费者 | 微信小程序 / 公众号 H5（测试）|
| **人工客服工作台** | 转人工会话处理、客户信息管理、快捷回复 | 企业客服员工 | 客服工作台小程序 / PC H5 |
| **管理后台** | 商品管理、订单管理、租户管理、AI 客服配置、客服团队管理 | 企业管理员 | 账号密码登录 |
| **AI 管理助手** | 数据查询、运营洞察、智能建议 | 企业管理员/员工 | 管理后台内嵌 |

### 1.3 学习目标

- Hermes Agent 智能体框架应用
- Tool/Skill 插件化架构设计
- LLM 应用开发（意图识别、参数提取、Tool Calling）
- RAG 知识库应用
- 多渠道 OAuth 认证与统一身份管理
- 多租户 SaaS 架构 + 租户自定义 AI 配置
- 微服务拆分与阿里云部署

---

## 2. 系统整体架构

### 2.1 架构概览

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            用户访问层                                            │
├──────────────────┬──────────────────┬──────────────────────┬───────────────────────┤
│   客服对话前端    │   管理后台前端    │   客服员工工作台    │   第三方渠道（未来扩展） │
│   (微信小程序)   │   (Next.js SSR)  │   (小程序+PC H5)  │                       │
│   - 对话界面      │   - 商品/订单管理 │   - 会话处理界面   │   - 微信公众号 H5     │
│   - 微信静默登录  │   - 数据统计      │   - 快捷回复       │     （测试）          │
│   - AI 推荐卡片   │   - AI 客服配置   │   - 客户信息       │   - 企业微信           │
│                  │   - 系统设置      │   - 在线/离线管理   │                       │
└────────┬─────────┘└────────┬─────────┘└────────┬─────────┘└──────────┬──────────┘
         │                   │                   │                     │
┌────────▼───────────────────▼───────────────────▼─────────────────────▼──────────┐
│                          阿里云 API Gateway                                     │
│                   (路由/限流/WAF/SSL/身份认证)                                   │
└──────┬────────────────────────┬────────────────────────┬────────────────────────┘
       │                        │                        │
┌──────▼──────────────┐  ┌─────▼─────────────────┐  ┌───▼──────────────┐
│ 管理后端（Java）     │  │ AI Agent 服务（Python）│  │ 管理前端（SSR）   │
│ Spring Boot 3       │  │ FastAPI + Hermes Agent│  │ Next.js          │
│                     │  │                       │  │ (SAE)            │
│ - 认证（小程序+     │  │ - C 端 Agent（客服）   │  │                  │
│   公众号+账号）      │  │ - 管理端 Agent（分析）  │  │                  │
│ - 商品/订单/租户 CRUD│  │ - Tool Registry       │  │                  │
│ - 租户 AI 配置管理   │  │ - 四层记忆系统        │  │                  │
│ - 会话分配引擎       │  │ - 自进化              │  │                  │
│ - WebSocket 网关     │  │                       │  │                  │
│ - RS256 JWT 签发    │  │                       │  │                  │
└──────┬──────────────┘  └──────┬────────────────┘  └──────────────────┘
       │                        │
┌──────▼────────────────────────▼───────────────────────────────┐
│                        VPC 内网                                 │
│  ┌──────────┐  ┌──────┐  ┌────────┐  ┌────────────────────┐  │
│  │ RDS PG   │  │Redis │  │ ACR    │  │ 阿里云百炼          │  │
│  │(主数据)  │  │(缓存) │  │(镜像)  │  │ - LLM API          │  │
│  └──────────┘  └──────┘  └────────┘  │ - Embedding API    │  │
│                                       └────────────────────┘  │
│  ┌────────────────────┐                                        │
│  │ DashVector         │                                        │
│  │ (向量数据库/RAG)   │                                        │
│  └────────────────────┘                                        │
└─────────────────────────────────────────────────────────────────┘
```


### 2.2 服务拆分

| 服务 | 技术栈 | 职责 | 部署 |
|------|--------|------|------|
| **admin-api** | Java/Spring Boot 3 | 认证 + 管理业务 + 租户 AI 配置 | SAE 独立部署 |
| **ai-agent-service** | Python/FastAPI + Hermes Agent | AI 对话引擎（C 端 + 管理端共用）| SAE 独立部署 |
| **admin-frontend** | Next.js (SSR) | 管理后台前端 | SAE 独立部署 |
| **wechat-mini** | 微信小程序 | 客服对话前端 | 微信开发者工具上传 |

**为什么合并 ai-chat-service 和 ai-admin-service？**

两个服务本质上是同一个 Hermes Agent 引擎，区别仅在于：
- 使用的 Tool 集合不同（客服 Tool vs 管理 Tool）
- System Prompt 不同（客服角色 vs 分析角色）

合并后通过 `agent_type` 参数动态加载不同的 Tool 和 Prompt，减少部署复杂度。

### 2.3 共享基础组件

```
packages/
├── hermes-tools/            # Hermes Tool 定义（AI 服务共用）
├── memory-config/           # 四层内存配置
├── rag-adapter/             # RAG 适配（DashVector + BM25 + 混合检索）
├── multi-tenant/            # 多租户适配（TenantConfigService）
└── middleware/              # 通用中间件（认证、CORS、日志）
```

---

## 3. 多渠道认证体系

### 3.1 用户身份类型

| 身份类型 | 来源 | 认证方式 | 权限范围 |
|---------|------|---------|---------|
| **wechat_mini** | 微信小程序登录 | wx.login() + code2Session | 只能查自己的数据 |
| **wechat_h5** | 微信公众号 OAuth 扫码 | 网页授权 code + access_token | 只能查自己的数据（测试用）|
| **account** | 企业账号登录 | 账号密码 + JWT | 租户内数据（受角色限制）|
| **agent_wechat** | 客服员工小程序 | 微信授权 + 手机号验证 | 客服工作台权限 |

### 3.1.1 角色体系映射

系统存在两套角色术语，分别用于不同场景：

**C 端身份（UserIdentity.role）**：用于区分用户来源和基础权限
| 角色代码 | 说明 | 登录方式 |
|---------|------|---------|
| customer | 终端消费者 | 微信小程序 / 公众号 H5 |
| agent | 客服员工 | 客服工作台小程序 / PC H5 |
| admin | 企业管理员 | 账号密码登录管理后台 |

**管理后台 RBAC 角色（JWT role Claim）**：用于管理后台菜单和数据权限控制
| 角色代码 | 对应 C 端 | 说明 |
|---------|----------|------|
| super_admin | admin | 超级管理员，全部菜单 + 本租户全部数据 |
| operation_manager | admin | 运营经理，数据看板 + AI 配置 + 业务管理 |
| support_supervisor | agent | 客服主管，客服团队管理 + 服务质量 |
| support_agent | agent | 客服员工，仅我的会话 + 快捷回复 |
| product_manager | admin | 商品管理员，商品管理 + 订单只读 |

> C 端 customer/agent/admin 是身份类型，管理后台 super_admin 等 5 个角色是 RBAC 权限角色。一个 C 端 admin 用户在管理后台可以被分配 5 个 RBAC 角色中的任意一个。

### 3.2 统一身份模型

```python
class UserIdentity:
    """统一用户身份"""
    user_id: str              # 系统内唯一用户 ID
    tenant_id: str            # 租户 ID
    identity_type: str        # wechat_mini / wechat_h5 / account / agent_wechat_mini
    identity_source: str      # 认证来源
    external_id: str          # 第三方平台用户 ID
    external_union_id: str    # 第三方平台 UnionID
    role: str                 # customer / agent / admin
```

### 3.3 认证流程

**微信小程序登录**：
```
小程序启动 → wx.login() 获取 code → 调用后端 /api/auth/mini/login
→ 后端用 code 调微信 code2Session → 获取 openid + unionid
→ 创建/更新用户 → 生成 JWT → 返回小程序
```

**微信公众号 OAuth 扫码登录（测试用）**：
```
用户扫描二维码 → 微信跳转到授权页 → 用户确认授权
→ 微信回调 /api/auth/h5/callback?code=xxx&state=xxx
→ 后端用 code 调微信 OAuth access_token → 获取 openid + unionid
→ 通过 unionid 关联小程序用户（同一用户识别）
→ 创建/更新用户 → 生成 JWT → Set-Cookie → 跳转 H5 客服页
```

**企业账号登录**：
```
输入账号密码 → 后端验证 → 生成 JWT（含 role/tenant_id）→ 返回前端
```

### 3.4 JWT Token 结构

```json
{
  "iss": "admin-api",
  "aud": "youke",
  "sub": "user_abc123",
  "tenant_id": "TENANT001",
  "identity_type": "wechat_mini",
  "role": "customer",
  "jti": "unique-jwt-id-for-revocation",
  "exp": 1704153600,
  "iat": 1704067200
}
```

> **租户隔离规则**：已认证请求的 `tenant_id` 必须从已验证的 JWT 中提取，不得使用客户端提供的 `X-Tenant-Code` 头。`X-Tenant-Code` 仅用于未认证端点（如小程序初始化配置接口），用于确定租户的小程序应用配置。

### 3.5 接口权限矩阵

| 接口 | 小程序用户 | 公众号 H5 用户 | 企业员工 | 管理员 |
|------|-----------|-------------|---------|--------|
| `POST /api/chat/messages` | ✅ | ✅ | ✅ | ✅ |
| `GET /api/chat/sessions/{id}` | ✅ (仅自己) | ✅ (仅自己) | ✅ (仅自己) | ✅ (全部) |
| `POST /api/admin/products` | ❌ | ❌ | ❌ | ✅ |
| `GET /api/admin/orders` | ❌ | ❌ | ✅ | ✅ |
| `PUT /api/admin/tenant/ai-config` | ❌ | ❌ | ❌ | ✅ |
| `POST /api/auth/account/login` | ❌ | ❌ | ✅ | ✅ |

### 3.6 安全加固措施

| 措施 | 说明 |
|------|------|
| **JWT 认证** | RS256 非对称签名，admin-api 持有私钥，其他服务使用公钥或调用 /verify 端点验证 |
| **JWT 存储（小程序/H5）** | 小程序端使用 wx.setStorageSync 存储 token，H5 使用 HttpOnly Cookie |
| **JWT 存储（管理后台）** | HttpOnly + Secure + SameSite=Lax Cookie |
| **小程序 code 一次性** | code 只能使用一次，5 分钟过期，后端调用 code2Session 后立即失效 |
| **防重放攻击** | 管理后台接口使用 X-Request-Timestamp + X-Request-Nonce 校验 |
| **租户隔离** | 已认证请求 tenant_id 从 JWT 提取，禁止使用客户端 Header |
| **CORS** | API Gateway 配置白名单域名，禁止 Access-Control-Allow-Origin: * |
| **速率限制** | 登录端点：5次/分钟/账号 + 10次/分钟/IP；API：租户级别 + 用户级别限流 |
| **服务间认证** | HMAC-SHA256 签名（X-Internal-Timestamp + X-Internal-Signature），共享密钥不在网络传输 |
| **未来审计** | 计划接入阿里云 ActionTrail + SLS 实现操作审计（本期不实现） |

---

## 4. Hermes Agent 核心架构

> 本系统采用 **Hermes Agent** 作为 AI 智能体核心框架。方案 B（生产级确定性架构）作为对比参考，详见 [生产级 AI 客服架构](./production-ai-architecture.md)。

### 4.1 为什么使用 Hermes Agent

| 原自研模块 | Hermes 替代 | 收益 |
|-----------|------------|------|
| 意图识别 + 路由 | 内置意图理解 | 代码减少 40% |
| 会话管理 | 四层内存系统 | 更智能的上下文管理 |
| Skill 框架 | 内置 Tool 机制 | 标准化插件系统 |
| 无 | 自进化能力 | 从实战中自动优化 |

### 4.2 Hermes Agent 配置

```python
from hermes import HermesAgent, Tool, MemoryConfig

# 创建 Agent（per-tenant 配置在运行时通过 TenantConfigService 注入）
# TenantConfigService 从 DB 加载 bailian_config 并缓存到 Redis（TTL 5min）
agent = HermesAgent(
    name="customer_service",
    model="qwen-turbo",  # 默认模型，运行时被 tenant.bailian_config.default_model 覆盖
    model_config={
        "api_key": settings.DASHSCOPE_API_KEY,  # 全局 fallback，per-tenant 有独立 key
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
    },
    tools=[
        order_query_tool,
        pre_sales_tool,
        after_sales_tool,
        logistics_tool
    ],
    memory=MemoryConfig(
        short_term={"max_turns": 20},
        long_term={"storage": "postgresql", "ttl": "30d"},
        semantic={"source": "self_hosted_rag"},  # DashVector 向量数据库 + 混合检索
        procedural={"auto_learn": True}  # 自进化
    ),
    tenant_context=True  # 启用多租户
)
```

### 4.3 Tool 定义（替代原 Skill）

```python
from hermes import Tool

order_query_tool = Tool(
    name="order_query",
    description="查询订单状态、详情和历史订单",
    parameters={
        "order_id": {
            "type": "string",
            "required": False,
            "description": "订单号，如果用户未提供则追问"
        }
    },
    permissions={
        "require_auth": True,
        "data_scope": "self"  # 只能查询自己的订单
    },
    execute=handle_order_query
)

async def handle_order_query(params: dict, context: ToolContext) -> dict:
    """订单查询处理函数"""
    # 参数校验
    order_id = params.get("order_id")
    if not order_id:
        return {"status": "need_param", "prompt": "请提供您的订单号"}
    
    # 查询数据库（自动加上 tenant_id 和 user_id 过滤）
    order = await context.db.query_order(
        order_id, 
        tenant_id=context.tenant_id,
        user_id=context.user_id  # C 端用户只能查自己的
    )
    
    if not order:
        return {"status": "error", "message": "订单不存在"}
    
    # 返回结构化数据
    return {
        "status": "success",
        "data": {
            "order_id": order.id,
            "status": order.status,
            "items": order.items,
            "total_amount": order.total_amount
        },
        "display": {"type": "card", "template": "order_detail"}
    }
```

### 4.4 四层内存系统

| 内存类型 | 用途 | 存储 | TTL |
|---------|------|------|-----|
| **Short-term** | 当前对话上下文 | Redis | 30 分钟 |
| **Long-term** | 用户画像/历史偏好 | PostgreSQL | 30 天 |
| **Semantic** | 领域知识（产品信息、FAQ）| DashVector 向量数据库（自建 RAG） | 永久 |
| **Procedural** | Tool 执行经验/优化策略 | PostgreSQL | 永久（自进化）|

### 4.5 自进化机制

```
用户对话 → Agent 执行 → 记录结果
    ↓
成功 → 强化该执行策略
失败 → 分析原因 → 优化 Prompt/参数 → 更新 Procedural Memory
    ↓
定期回顾 → 自动优化 Tool 调用策略
```

### 4.6 方案对比（可选参考）

> 以下为 Hermes Agent（本系统方案）与生产级确定性架构的对比，仅供技术选型参考。

| 维度 | Hermes Agent（本系统） | 生产级确定性架构 |
|------|------|------|
| 意图识别 | LLM 自动理解 | 规则匹配优先，LLM 兜底 |
| Tool 调用 | LLM 动态选择 | 意图 → Tool 一对一映射 |
| 参数校验 | LLM 自行判断 | Pydantic Schema 强制校验 |
| 降级能力 | 依赖 LLM 可用 | LLM 不可用仍可部分服务 |
| 可调试性 | 决策过程不透明 | 每步确定，日志可追溯 |
| 适用阶段 | 原型验证 / 学习 / 早期迭代 | 生产上线 / 高稳定性要求 |

---

## 5. 数据模型

### 5.1 核心表

| 表名 | 说明 | 关键字段 |
|------|------|---------|
| tenants | 租户 | id, name, code, industry, status, auth_config, bailian_config, created_at |
| users | 用户主表 | id, tenant_id, phone, password_hash, nickname, avatar, role, session_ttl, status, created_at |
| user_identities | 用户身份（多对一关联 users）| id, tenant_id, user_id, identity_type, external_id, external_union_id |
| products | 商品 | id, tenant_id, name, knowledge_base_id |
| product_skus | 商品 SKU | id, tenant_id, product_id, specifications, stock |
| categories | 商品分类 | id, tenant_id, name, parent_id |
| orders | 订单 | id, tenant_id, user_id, status, items |
| after_sales_tickets | 售后工单 | id, tenant_id, order_id, type, status |
| sessions | 会话 | id, tenant_id, user_id, context |
| tenant_apps | 租户应用配置 | id, tenant_id, app_type, appid, appsecret, status |
| tenant_ai_configs | 租户 AI 客服配置 | id, tenant_id, greeting_template, business_hours, auto_handoff_keywords, after_hours_mode, quick_replies |
| **agent_employees** | **客服员工信息** | **id, tenant_id, user_id, name, phone, role, status, max_concurrent_sessions, invite_code** |
| **agent_sessions** | **人工会话记录** | **id, tenant_id, user_id, employee_id, ai_session_id, status, queue_position, rating** |
| **agent_messages** | **人工会话消息** | **id, tenant_id, agent_session_id, sender_type, sender_id, content_type, content** |
| **quick_reply_templates** | **快捷回复模板** | **id, tenant_id, category, title, content, usage_count, is_public** |

> **users 与 user_identities 的关系**：一个 user 可以有多个 identity（微信小程序、公众号 H5、账号密码），通过 `user_identities.user_id` 外键关联到 `users.id`。同一用户在不同端的 openid 不同，但通过 unionid 跨端识别为同一用户。详见 [多租户多端架构](./multi-tenant-multi-platform.md)。

### 5.1.1 tenant_ai_configs 表详解

企业管理员通过管理后台修改 AI 客服的自我介绍和业务规则，配置存储在 `tenant_ai_configs` 表中：

```sql
CREATE TABLE tenant_ai_configs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id) UNIQUE,
    
    -- 自我介绍模板
    greeting_template TEXT DEFAULT '您好，我是 {company_name} 的 AI 客服助手，有什么可以帮您？',
    
    -- 营业时间配置
    business_hours JSONB DEFAULT '{"workdays": "09:00-18:00", "weekend": "10:00-16:00"}',
    timezone VARCHAR(64) DEFAULT 'Asia/Shanghai',
    
    -- 转人工关键词
    auto_handoff_keywords JSONB DEFAULT '["人工", "投诉", "退款", "找客服"]',
    
    -- 情绪检测转人工
    emotion_handoff BOOLEAN DEFAULT true,
    
    -- AI 无法解决时转人工
    ai_fallback_handoff BOOLEAN DEFAULT true,
    ai_fallback_threshold INTEGER DEFAULT 3,
    
    -- 非营业时间策略
    after_hours_mode VARCHAR(32) DEFAULT 'collect_message',  -- collect_message | ai_only | handoff_if_online
    after_hours_message TEXT DEFAULT '当前非营业时间，请留言，我们会在营业时间回复您。',
    
    -- 快捷回复模板
    quick_replies JSONB DEFAULT '[
        {"id": "q1", "label": "查订单", "prompt": "我想查订单"},
        {"id": "q2", "label": "找产品", "prompt": "推荐产品"},
        {"id": "q3", "label": "退换货", "prompt": "我要退换货"}
    ]',
    
    -- 产品推荐策略
    recommend_strategy VARCHAR(32) DEFAULT 'sales_based',  -- sales_based | random | category_match | none
    recommend_count INTEGER DEFAULT 3,
    recommend_trigger VARCHAR(32) DEFAULT 'on_query',  -- on_query | on_conversation_end
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

**配置字段说明**：

| 字段 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| greeting_template | TEXT | AI 自我介绍文案，支持 `{company_name}` 占位符 | 通用欢迎语 |
| business_hours | JSONB | 营业时间，格式 `{"workdays": "09:00-18:00", "weekend": "10:00-16:00"}` | 9:00-18:00 |
| timezone | VARCHAR | 时区 | Asia/Shanghai |
| auto_handoff_keywords | JSONB | 触发转人工的关键词列表 | 常见客服关键词 |
| emotion_handoff | BOOLEAN | 是否启用情绪检测转人工 | 启用 |
| ai_fallback_handoff | BOOLEAN | AI 无法解决时是否转人工 | 启用 |
| ai_fallback_threshold | INTEGER | AI 连续失败几次后转人工 | 3 |
| after_hours_mode | VARCHAR | 非营业时间策略：collect_message（收集留言）/ ai_only（仅 AI 响应）/ handoff_if_online（有在线客服则转人工） | 收集留言 |
| after_hours_message | TEXT | 非营业时间提示语 | 默认提示 |
| quick_replies | JSONB | 快捷回复按钮列表，格式 `[{id, label, prompt}]` | 3 个常见场景 |
| recommend_strategy | VARCHAR | 产品推荐策略：sales_based（按销量）/ random（随机）/ category_match（按分类）/ none（不推荐） | 按销量推荐 |
| recommend_count | INTEGER | 每次推荐数量 | 3 |
| recommend_trigger | VARCHAR | 推荐触发时机：on_query（用户询问产品时）/ on_conversation_end（对话结束时） | 用户询问时 |

**配置加载流程**：
```
用户发起对话 → ai-agent-service 收到请求
→ 调用 admin-api /api/admin/tenant/ai-config?tenant_id=xxx
→ 获取 tenant_ai_configs 配置
→ 注入 Hermes Agent System Prompt
→ Agent 按配置的规则执行（自我介绍、转人工、非营业时间处理）
```

### 5.1.2 客服工作台数据表

客服员工工作台（Agent Workspace）相关的 4 张核心表：`agent_employees`、`agent_sessions`、`agent_messages`、`quick_reply_templates`，完整 schema 和字段说明详见 [客服员工工作台产品设计](./agent-workspace-design.md#9-数据模型)。

**核心流程**：
```
AI 客服无法处理 → 触发转人工 → 创建 agent_sessions（status=waiting）
→ 会话分配引擎查询在线员工 → 按最少当前会话轮询分配
→ 分配给 employee → agent_sessions.status=active
→ 员工通过小程序或 PC H5 处理会话
→ 会话结束 → agent_sessions.status=ended，记录满意度评分
```

### 5.2 多租户安全设计

本系统采用五层数据隔离机制，确保租户之间、用户之间的数据严格隔离：

| 层级 | 机制 | 说明 |
|------|------|------|
| **L1 租户隔离** | JWT 强制 tenant_id | 所有已认证请求的 tenant_id 从 JWT 提取，禁止使用客户端 Header |
| **L2 数据库隔离** | 所有业务表含 tenant_id | 数据库触发器强制 tenant_id 不为空，PostgreSQL 行级安全策略（RLS） |
| **L3 向量库隔离** | DashVector Collection 级别隔离 | 每个租户独立的 Collection（tenant_{tenant_id}） |
| **L4 用户隔离** | Tool 层 data_scope 控制 | `self`：仅查自己的数据（C 端用户）；`tenant`：租户内全部数据（管理员） |
| **L5 字段脱敏** | Tool 层 field_masking 控制 | 按角色隐藏敏感字段（如 C 端用户不显示成本价，管理员不显示用户手机号） |

**多租户多端架构**：

作为 SaaS 平台，系统支持租户自行配置多种前端入口（微信小程序、公众号 H5、未来可扩展企业微信/钉钉）。详见 [多租户多端架构设计](./multi-tenant-multi-platform.md)。

核心设计：
- `tenant_apps` 表：每个租户可配置多个应用（小程序 AppID、H5 AppID 等）
- `user_identities` 表：同一用户在不同端有不同 openid，通过 unionid 跨端识别
- 后端完全共用，所有业务服务不感知前端来源
- 统一 `_find_or_create_user` 方法：优先按 unionid 查找（跨端识别），再按 openid 查找，最后创建新用户

**Tool 安全控制矩阵**：

| Tool | require_auth | allowed_roles | data_scope | 脱敏字段（按角色） |
|------|-------------|---------------|------------|-------------------|
| order_query | ✅ | customer, admin | self（C 端）/ tenant（管理员） | customer: cost_price |
| product_search | ✅ | customer, admin | tenant | customer: cost_price, stock |
| knowledge_search | ✅ | customer, admin | tenant | 无 |
| after_sales | ✅ | customer, admin | self | customer: 内部处理备注 |
| logistics_query | ✅ | customer, admin | self | 无 |

### 5.3 JSON vs 关系表

| 字段 | 存储方式 | 原因 |
|------|---------|------|
| order.items | JSON | 订单快照，不需要复杂查询 |
| order.shipping_address | JSON | 地址快照 |
| product.specifications | JSON | SKU 规格灵活 |
| order.logistics | 独立表 | 需要按运单号查询 |

---

## 6. 前端交互

### 6.1 SSE 事件流格式

> **格式约定**：所有数据事件使用 `event: message`，通过 `data.type` 区分消息类型。流结束信号使用独立的 `event: done` 事件类型。

```
event: message
data: {"type": "loading", "content": "正在查询..."}

event: message
data: {"type": "text", "content": "请提供您的订单号"}

event: message
data: {"type": "card", "template": "order_detail", "data": {...}}

event: message
data: {"type": "recommend", "items": ["查看历史订单", "申请售后"]}

event: done
data: {"session_id": "sess_abc123"}
```

### 6.2 交互组件

| 组件 | 用途 |
|------|------|
| 微信静默登录 | 小程序启动时自动 wx.login() 获取 code 并登录 |
| 快捷菜单 | 固定功能入口 |
| 对话消息区 | 文本/卡片消息 |
| AI 推荐卡片 | 智能推荐功能 |
| 输入框 | 用户输入 |

---

## 7. 百炼集成与自建 RAG

### 7.1 模型选择

| 场景 | 模型 | 原因 |
|------|------|------|
| 意图识别 | qwen-turbo | 简单分类，成本低 |
| 通用对话 | qwen-turbo | 闲聊、简单问答 |
| 复杂推理 | qwen-plus | 需要强推理能力 |
| Embedding 向量化 | text-embedding-v3 | 中文效果好，支持多粒度 |

### 7.2 自建 RAG 知识库

**为什么不用百炼知识库而自建？**
- 布艺行业需要定制化分块策略（按面料、工艺、安装方式分块）
- 需要混合检索（BM25 关键词 + 向量语义）提升检索精度
- 需要与业务数据联动（商品上下架自动同步知识库）
- 多租户隔离更灵活（DashVector collection 级别隔离）

**技术架构**：
- 向量数据库：阿里云 DashVector（托管服务，按量付费）
- Embedding 模型：text-embedding-v3（百炼 API 调用）
- 分块策略：FabricChunker（布艺行业定制）
- 检索策略：混合检索（BM25 + 向量 + 重排序）

详见 [自建 RAG 知识库技术方案](./rag-architecture.md)。

### 7.3 静态 vs 动态数据

| 数据类型 | 存储 | 示例 |
|---------|------|------|
| 静态 | DashVector 向量数据库 | 产品介绍、FAQ、安装指南、加工工艺 |
| 动态 | 数据库 | 价格、库存、订单状态 |

---

## 8. 阿里云部署方案

### 8.1 部署架构

```
┌─────────────────────────────────────────────────────────────┐
│                      阿里云环境                              │
│                                                              │
│  ┌─────────────────────┐          ┌─────────────────────┐  │
│  │  客服前端 (微信小程序)│          │ 管理前端 (SSR/SAE)   │  │
│  │  + 公众号 H5 (测试)  │          └─────────┬───────────┘  │
│  └─────────┬───────────┘                    │               │
│            │                                │               │
│  ┌─────────▼────────────────────────────────▼───────────┐  │
│  │                 API Gateway                           │  │
│  │         (路由/限流/WAF/SSL/OAuth 回调)                │  │
│  └────┬──────────────────┬──────────────────┬───────────┘  │
│       │                  │                  │              │
│  ┌────▼──────────┐  ┌───▼────────────┐  ┌──▼──────────┐  │
│  │ 管理后端       │  │ AI Agent 服务  │  │ 管理前端    │  │
│  │ (Java SAE)    │  │ (Python SAE)   │  │ (SSR SAE)   │  │
│  │               │  │                │  │             │  │
│  │ - 认证        │  │ - Hermes Agent │  │             │  │
│  │ - 管理业务    │  │ - C 端/管理端  │  │             │  │
│  │ - AI 配置管理 │  │ - Tool 执行    │  │             │  │
│  └────┬──────────┘  └───┬────────────┘  └─────────────┘  │
│       │                  │                                │
│  ┌────▼──────────────────▼────────────────────────────┐  │
│  │                    VPC 内网                          │  │
│  │  ┌──────────┐  ┌──────┐  ┌────────────────────┐   │  │
│  │  │ RDS PG   │  │Redis │  │ 阿里云百炼          │   │  │
│  │  │(主数据)  │  │(缓存) │  │ - LLM + 知识库     │   │  │
│  │  └──────────┘  └──────┘  └────────────────────┘   │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  ┌──────────────────────────────────────┐                │
│  │         可观测性                      │                │
│  │  ┌──────────┐  ┌──────────────────┐ │                │
│  │  │ SLS 日志 │  │ ARMS 监控        │ │                │
│  │  └──────────┘  └──────────────────┘ │                │
│  └──────────────────────────────────────┘                │
└──────────────────────────────────────────────────────────┘
```

### 8.2 阿里云产品清单

| 产品 | 用途 | 规格（开发环境）| 月成本预估 |
|------|------|----------------|-----------|
| **SAE** | 应用托管（2 个后端服务 + 1 个前端 SSR）| 按量付费 | ~170 元 |
| **RDS PostgreSQL** | 业务数据库 | pg.n2.small.1 (1C2G, 20GB) | ~100 元 |
| **Redis** | 缓存/会话/code 防重放 | redis.master.small.default (1G) | ~50 元 |
| **OSS** | 静态资源存储（管理前端构建产物备用）| 按量 | ~5 元 |
| **CDN** | 静态资源加速 | 按量 | ~10 元 |
| **API Gateway** | API 路由/限流 | 按量 | ~20 元 |
| **ACR** | 容器镜像仓库 | 个人版（免费）| 0 元 |
| **SLS** | 日志服务 | 免费额度内 | 0 元 |
| **ARMS** | 应用监控 | 基础版（免费）| 0 元 |
| **百炼** | LLM API（qwen-turbo/plus + text-embedding-v3） | 免费额度内 | 0 元 |
| **DashVector** | 向量数据库（自建 RAG） | 按量付费 | ~¥50/月 |
| **合计** | - | - | **~355 元/月** |

### 8.3 Terraform 基础设施

详见 [阿里云部署方案](./deployment-aliyun.md)

核心资源：
- VPC + 安全组
- RDS PostgreSQL + Redis
- 2 个 SAE 应用（admin-api 含认证 + ai-agent-service 含 Hermes Agent）
- ACR 镜像仓库
- OSS Bucket

### 8.4 Docker 镜像构建

```bash
# 管理后端（Java，含认证 + 租户 AI 配置管理）
cd admin-api
./mvnw clean package -DskipTests
docker build -t registry.cn-hangzhou.aliyuncs.com/youke/admin-api:latest .
docker push registry.cn-hangzhou.aliyuncs.com/youke/admin-api:latest

# AI Agent 服务（Python，C 端 + 管理端共用）
cd ai-agent-service
docker build -t registry.cn-hangzhou.aliyuncs.com/youke/ai-agent-service:latest .
docker push registry.cn-hangzhou.aliyuncs.com/youke/ai-agent-service:latest
```

### 8.5 前端部署

```bash
# 客服前端（微信小程序，通过微信开发者工具上传）
# 小程序代码包由微信审核发布，不经过 OSS/CDN

# 公众号 H5（测试用，可选）
# 在微信公众平台配置网页授权域名 → 指向 API Gateway
# H5 页面可部署到 admin-api 的静态资源目录或独立 OSS

# 管理前端
cd web/admin
npm run build
# SSR 部署到 SAE，无需 OSS
```

### 8.6 环境变量配置

**SAE 应用环境变量**：

| 变量名 | 说明 | 示例值 |
|--------|------|--------|
| DATABASE_URL | 数据库连接 | postgresql+asyncpg://user:pass@pgm-xxx:5432/db |
| REDIS_URL | Redis 连接 | redis://r-xxx:6379/0 |
| DASHSCOPE_API_KEY | 百炼 API Key | sk-xxx |
| JWT_PRIVATE_KEY_PATH | RS256 私钥文件路径（仅 admin-api） | `/app/keys/private.pem` |
| JWT_PUBLIC_KEY_PATH | RS256 公钥文件路径（所有服务可持有） | `/app/keys/public.pem` |
| WECHAT_MINI_APPID | 小程序 AppID | wx-xxx |
| WECHAT_MINI_APPSECRET | 小程序 AppSecret | wx-secret-xxx |
| SERVICE_TYPE | 服务类型 | chat / admin |

### 8.7 安全配置

| 配置项 | 说明 |
|--------|------|
| VPC 隔离 | 所有服务在同一 VPC 内网通信 |
| 安全组 | 仅开放必要端口（8000/8080）|
| API Gateway WAF | 防护常见 Web 攻击 |
| RDS 白名单 | 仅允许 VPC 内 IP 访问 |
| Redis 密码 | 启用密码认证 |
| JWT 签名 | RS256 非对称签名，admin-api 持私钥，其他服务用公钥验证 |
| 敏感字段加密 | 用户手机号等字段加密存储 |

### 8.8 可观测性

**SLS 日志采集**：
- 应用日志：INFO/WARN/ERROR
- 访问日志：请求/响应
- Tool 执行日志：tool_name、input_params、success、execution_time_ms

**ARMS 监控指标**：
- QPS、响应时间、错误率
- CPU/内存使用率
- 数据库连接池状态

**告警规则**：
| 指标 | 阈值 | 通知方式 |
|------|------|---------|
| 错误率 | > 5% 持续 5 分钟 | 短信 + 邮件 |
| 平均响应时间 | > 2s 持续 5 分钟 | 短信 + 邮件 |
| CPU 使用率 | > 80% 持续 10 分钟 | 短信 |

---

## 9. 开发阶段

| 阶段 | 内容 | 学习目标 |
|------|------|---------|
| **Phase 1** | Hermes Agent 接入 + 订单查询 Tool | Agent 框架、Tool 定义 |
| **Phase 2** | 售前咨询 Tool + 自建 RAG 知识库（DashVector） | RAG 应用、混合检索 |
| **Phase 3** | 售后服务 Tool + 四层内存 | 会话状态管理 |
| **Phase 4** | 统一认证服务 + 微信小程序登录 | 小程序 code2Session、JWT |
| **Phase 5** | 前端对话界面 + SSE | 实时通信、富文本 |
| **Phase 6** | AI 管理助手 + 内部 API | 服务间通信 |
| **Phase 7** | Java 管理后台 | Spring Boot 开发 |
| **Phase 8** | 多租户安全 + 阿里云部署 | SaaS 架构、云原生 |

---

## 10. 技术栈总结

| 层级 | 技术 |
|------|------|
| **前端** | Next.js 14 / React / Tailwind CSS |
| **AI 服务** | Python 3.11+ / FastAPI / Hermes Agent |
| **管理后端** | Java 17+ / Spring Boot 3 / MyBatis（含认证服务）|
| **数据库** | PostgreSQL 14 |
| **缓存** | Redis 7 |
| **LLM** | 阿里云百炼 DashScope |
| **部署** | Docker / 阿里云 SAE |
| **IaC** | Terraform |
| **CI/CD** | 阿里云云效 |
