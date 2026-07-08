# API 接口设计文档

> 版本：v8.0（2 服务架构 + 公众号 OAuth + 租户 AI 配置 + 客服员工工作台 + CRM 客户管理）  
> 日期：2026-04-12  
> 变更：ai-chat-service 与 ai-admin-service 合并为 ai-agent-service；admin-api 新增认证（小程序 + 公众号 H5 + 账号）+ 管理业务 + 租户 AI 配置

---

## 0. 通用约定

### 0.1 认证方式

所有需要认证的接口通过 **HttpOnly Cookie** 携带 JWT（非 Authorization header）。浏览器端使用 `credentials: 'include'` 自动携带。

> **重要**：`tenant_id` 始终从 JWT Claims 中提取，禁止通过 `X-Tenant-Code` 请求头传递（防止租户越权）。

### 0.2 统一响应信封

**成功响应**：

```json
{
  "success": true,
  "data": { ... },
  "request_id": "req_abc123"
}
```

**错误响应**：

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "参数校验失败",
    "details": [
      { "field": "price", "message": "价格必须大于 0" }
    ]
  },
  "request_id": "req_abc123"
}
```

> 所有服务（Python / Java）统一使用此信封格式。Java 管理后端的 `{"code": 200, "data": ...}` 格式已废弃。

---

## 1. 认证服务 API (admin-api 认证模块)

### 1.1 微信小程序登录

#### 小程序登录

```
POST /api/auth/mini/login
Content-Type: application/json

{
  "code": "wx_login_code",
  "tenant_id": "TENANT001"
}
```

**流程**：
1. 小程序调用 `wx.login()` 获取临时 code
2. 小程序调用 `POST /api/auth/mini/login`，传入 code 和 tenant_id
3. 后端调用微信 code2Session 接口，用 code 换取 openid
4. 后端创建或更新用户，返回 JWT token

**响应**（Set-Cookie: access_token=JWT; HttpOnly; Secure; SameSite=Lax）：

```json
{
  "success": true,
  "data": {
    "user": {
      "id": "user_abc123",
      "nickname": "张三",
      "avatar": "https://...",
      "role": "customer",
      "identity_type": "wechat_mini"
    }
  }
}
```

### 1.2 微信公众号 OAuth 登录

#### 发起 OAuth 授权

```
GET /api/auth/h5/authorize
Query: tenant_code, redirect_uri
```

**流程**：
1. 用户在 H5 页面点击"微信登录"
2. 前端跳转至 `/api/auth/h5/authorize?tenant_code=TENANT001&redirect_uri=https%3A%2F%2Fh5.migaozn.com%2Fcallback`
3. 后端 302 重定向到微信公众号 OAuth 授权页面
4. 用户授权后，微信回调 `/api/auth/h5/callback`
5. 后端验证 code，创建或更新用户，Set-Cookie 写入 access_token
6. 后端 302 重定向到 H5 页面

**响应**：302 Redirect to WeChat OAuth page

#### OAuth 回调

```
GET /api/auth/h5/callback
Query: code, state
```

**响应**：Set-Cookie (access_token) + 302 Redirect to H5 page

### 1.3 账号密码登录

#### 登录

```
POST /api/auth/account/login
Content-Type: application/json

{
  "phone": "13800138000",
  "password": "hashed_password",
  "tenant_code": "TENANT001"
}
```

**响应**（Set-Cookie: access_token=JWT）：

```json
{
  "success": true,
  "data": {
    "user": {
      "id": "user_001",
      "nickname": "管理员",
      "role": "admin",
      "identity_type": "account"
    }
  }
}
```

#### 登出

```
POST /api/auth/account/logout
Cookie: access_token=<JWT>
```

**行为**：吊销 JWT（加入 Redis 黑名单），清除 Cookie。

#### Token 刷新

```
POST /api/auth/account/refresh
Cookie: access_token=<JWT>
```

### 1.4 用户信息

#### 获取当前用户

```
GET /api/auth/me
Cookie: access_token=<JWT>
```

#### 更新当前用户

```
PUT /api/auth/me
Cookie: access_token=<JWT>
Content-Type: application/json

{
  "nickname": "新昵称",
  "avatar": "https://..."
}
```

### 1.5 内部接口

#### Token 验证（仅 VPC 内部服务调用）

```
POST /api/auth/internal/verify
Content-Type: application/json
X-Internal-Timestamp: 1704067200
X-Internal-Signature: hmac_sha256_signature

{
  "token": "jwt_token_to_verify"
}
```

**响应**：

```json
{
  "valid": true,
  "payload": {
    "sub": "user_abc123",
    "tenant_id": "TENANT001",
    "role": "customer",
    "exp": 1704153600
  }
}
```

---

## 2. AI 客服服务 API (ai-agent-service)

### 2.1 对话接口

#### 发送消息（SSE 流式）

```
POST /api/chat/messages
Content-Type: application/json
Cookie: access_token=<JWT>

{
  "session_id": "sess_abc123",
  "message": "我的订单到哪了"
}
```

> tenant_id 从 JWT 中自动提取，无需传递 X-Tenant-Code。

**响应（SSE 事件流）**：

```
event: message
data: {"type": "loading", "content": "正在识别意图..."}

event: message
data: {"type": "text", "content": "请提供您的订单号"}

event: done
data: {"session_id": "sess_abc123"}
```

#### 创建会话

```
POST /api/chat/sessions
Content-Type: application/json
Cookie: access_token=<JWT>

{
  "client_type": "chat"
}
```

**响应**：

```json
{
  "success": true,
  "data": {
    "session_id": "sess_abc123",
    "created_at": "2026-04-11T10:00:00Z"
  }
}
```

#### 获取会话历史

```
GET /api/chat/sessions/{session_id}/messages
```

### 2.2 快捷菜单

#### 获取快捷功能

```
GET /api/chat/quick-actions
Cookie: access_token=<JWT>
```

**响应**：

```json
{
  "actions": [
    {
      "id": "order_query",
      "name": "订单查询",
      "icon": "package",
      "prompt": "我想查询订单"
    },
    {
      "id": "pre_sales",
      "name": "售前咨询",
      "icon": "shopping-bag",
      "prompt": "我想了解产品"
    },
    {
      "id": "after_sales",
      "name": "售后服务",
      "icon": "refresh-cw",
      "prompt": "我需要售后服务"
    }
  ]
}
```

---

## 3. AI 管理助手服务 API (ai-agent-service)

### 3.1 对话接口

#### 发送消息（SSE 流式）

```
POST /api/admin/ai/chat/messages
Content-Type: application/json
Cookie: access_token=<JWT>

{
  "session_id": "sess_admin_123",
  "message": "今天有多少新订单？"
}
```

> 路由路径为 `/api/admin/ai/*`，API Gateway 按优先级匹配，不会被 `/api/admin/*`（Java 后端）截获。

### 3.2 内部 API（供 Java 管理后端调用）

#### 触发知识库同步

```
POST /api/admin/ai/internal/knowledge/sync
Content-Type: application/json
X-Internal-Timestamp: 1704067200
X-Internal-Signature: hmac_sha256_signature

{
  "tenant_id": "TENANT001",
  "type": "product_updated",
  "resource_id": "PROD001"
}
```

> 内部接口通过 HMAC 签名认证（参见 auth-and-deployment.md §3.4），不使用 JWT Cookie。

---

## 4. Java 管理后端 API (admin-api)

> admin-api 处理认证（小程序 + 公众号 H5 + 账号）+ 管理业务 + 租户 AI 配置。  
> 所有接口通过 HttpOnly Cookie 携带 JWT，tenant_id 从 JWT 自动提取。

### 4.1 商品管理

#### 商品列表

```
GET /api/admin/products?page=1&size=20&status=active&keyword=遮光
Cookie: access_token=<JWT>
```

**响应**：

```json
{
  "success": true,
  "data": {
    "total": 100,
    "page": 1,
    "size": 20,
    "items": [
      {
        "id": "PROD001",
        "name": "遮光窗帘布",
        "categoryId": "CAT-SHADE",
        "basePrice": 268.00,
        "status": "active",
        "stock": 500,
        "createdAt": "2026-04-11T10:00:00Z"
      }
    ]
  },
  "request_id": "req_abc123"
}
```

#### 创建商品

```
POST /api/admin/products
Content-Type: application/json
Cookie: access_token=<JWT>

{
  "name": "遮光窗帘布",
  "categoryId": "CAT-SHADE",
  "basePrice": 268.00,
  "description": "高遮光率窗帘布",
  "skus": [
    {
      "skuCode": "SKU-PROD001-BEIGE",
      "specifications": {
        "color": "米白色",
        "width": 3.0
      },
      "price": 268.00,
      "stock": 500
    }
  ]
}
```

#### 更新商品

```
PUT /api/admin/products/{id}
Content-Type: application/json

{
  "name": "遮光窗帘布 - 升级版",
  "basePrice": 298.00
}
```

#### 删除商品

```
DELETE /api/admin/products/{id}
```

### 4.2 订单管理

#### 订单列表

```
GET /api/admin/orders?page=1&size=20&status=shipped&startDate=2026-01-01&endDate=2026-01-31&keyword=ORD12345
Cookie: access_token=<JWT>
```

#### 订单详情

```
GET /api/admin/orders/{id}
```

**响应**：

```json
{
  "success": true,
  "data": {
    "id": "ORD12345",
    "userId": "user_001",
    "status": "shipped",
    "items": [
      {
        "productId": "PROD001",
        "name": "遮光窗帘布",
        "specifications": {"color": "米白色"},
        "quantity": 1,
        "price": 268.00
      }
    ],
    "totalAmount": 268.00,
    "shippingAddress": {...},
    "logistics": {
      "company": "顺丰",
      "trackingNo": "SF1234567890",
      "status": "in_transit"
    },
    "createdAt": "2026-01-01T10:00:00Z"
  },
  "request_id": "req_abc123"
}
```

#### 更新订单状态

```
PATCH /api/admin/orders/{id}/status
Content-Type: application/json

{
  "status": "shipped",
  "logistics": {
    "company": "顺丰",
    "trackingNo": "SF1234567890"
  }
}
```

### 4.3 数据统计

#### 订单统计

```
GET /api/admin/stats/orders?period=month&startDate=2024-01-01
```

**响应**：

```json
{
  "success": true,
  "data": {
    "totalOrders": 1280,
    "totalRevenue": 520000.00,
    "averageOrderValue": 406.25,
    "statusBreakdown": {
      "pending": 50,
      "confirmed": 80,
      "producing": 100,
      "shipped": 200,
      "completed": 900,
      "cancelled": 30
    },
    "trend": [
      {"date": "2026-01-01", "orders": 40, "revenue": 15000},
      {"date": "2026-01-02", "orders": 45, "revenue": 18000}
    ]
  },
  "request_id": "req_abc123"
}
```

---

## 5. 租户 AI 配置管理 API (admin-api)

### 5.1 获取租户 AI 配置

```
GET /api/admin/tenant/ai-config
Auth: Required (super_admin / operation_manager role)
Cookie: access_token=<JWT>
```

**响应**：

```json
{
  "success": true,
  "data": {
    "greeting_template": "您好，我是 {company_name} 的 AI 客服助手，请问有什么可以帮您？",
    "business_hours": {
      "workdays": "09:00-18:00",
      "weekend": "10:00-16:00"
    },
    "auto_handoff_keywords": ["人工", "投诉", "退款"],
    "after_hours_mode": "collect_message",
    "quick_replies": [
      {"id": "q1", "label": "查订单", "prompt": "我想查订单"},
      {"id": "q2", "label": "找产品", "prompt": "推荐产品"},
      {"id": "q3", "label": "退换货", "prompt": "我要退换货"}
    ],
    "recommend_strategy": "sales_based"
  },
  "request_id": "req_abc123"
}
```

### 5.2 更新租户 AI 配置

```
PUT /api/admin/tenant/ai-config
Auth: Required (super_admin / operation_manager role)
Cookie: access_token=<JWT>
Content-Type: application/json

{
  "greeting_template": "您好，我是 {company_name} 的 AI 客服助手...",
  "business_hours": {"workdays": "09:00-18:00", "weekend": "10:00-16:00"},
  "auto_handoff_keywords": ["人工", "投诉", "退款"],
  "after_hours_mode": "collect_message",
  "quick_replies": [
    {"id": "qr_001", "title": "营业时间", "content": "我们的工作时间为..."}
  ],
  "recommend_strategy": "sales_based"
}
```

**响应**：

```json
{
  "success": true,
  "data": { "message": "AI 配置已更新" },
  "request_id": "req_abc123"
}
```

---

## 5.5 知识库管理 API (admin-api)

> 完整 RAG 技术方案详见 [自建 RAG 知识库技术方案](../architecture/rag-architecture.md)。

### 5.5.1 创建/上传文档

```
POST /api/admin/knowledge/documents
Auth: Required (super_admin / operation_manager role)
Cookie: access_token=<JWT>
Content-Type: application/json

{
  "title": "遮光窗帘布 - 产品说明",
  "doc_type": "product_info",
  "category": "curtain",
  "content": "遮光窗帘布采用高精密织造工艺...",
  "product_id": "PROD001"
}
```

**响应**：

```json
{
  "success": true,
  "data": {
    "id": "doc_abc123",
    "title": "遮光窗帘布 - 产品说明",
    "embedding_status": "pending",
    "message": "文档已创建，向量化任务已加入队列"
  },
  "request_id": "req_abc123"
}
```

### 5.5.2 获取文档列表

```
GET /api/admin/knowledge/documents?page=1&size=20&doc_type=product_info&category=curtain
Auth: Required
Cookie: access_token=<JWT>
```

**响应**：

```json
{
  "success": true,
  "data": {
    "documents": [
      {
        "id": "doc_abc123",
        "title": "遮光窗帘布 - 产品说明",
        "doc_type": "product_info",
        "category": "curtain",
        "embedding_status": "completed",
        "chunk_count": 5,
        "created_at": "2026-04-12T10:00:00Z"
      }
    ],
    "total": 128,
    "page": 1,
    "size": 20
  },
  "request_id": "req_abc123"
}
```

### 5.5.3 查看文档分块

```
GET /api/admin/knowledge/documents/{id}/chunks
Auth: Required
Cookie: access_token=<JWT>
```

**响应**：

```json
{
  "success": true,
  "data": {
    "document_id": "doc_abc123",
    "total_chunks": 5,
    "chunks": [
      {
        "chunk_id": "chunk_doc_abc123_000",
        "content": "遮光窗帘布采用高精密织造工艺，遮光率可达 85%-95%...",
        "chunk_index": 0,
        "metadata": {"category": "curtain", "doc_type": "product_info"}
      }
    ]
  },
  "request_id": "req_abc123"
}
```

### 5.5.4 触发向量化

```
POST /api/admin/knowledge/documents/{id}/embed
Auth: Required
Cookie: access_token=<JWT>
```

**响应**：

```json
{
  "success": true,
  "data": {
    "task_id": "task_xyz789",
    "status": "pending",
    "message": "向量化任务已加入队列"
  },
  "request_id": "req_abc123"
}
```

### 5.5.5 测试检索

```
POST /api/admin/knowledge/test-search
Auth: Required
Cookie: access_token=<JWT>
Content-Type: application/json

{
  "query": "遮光窗帘布 打孔 多少钱",
  "top_k": 5
}
```

**响应**：

```json
{
  "success": true,
  "data": {
    "query": "遮光窗帘布 打孔 多少钱",
    "results": [
      {
        "chunk_id": "chunk_doc_abc123_001",
        "content": "加工方式可选：打孔加工（¥5/个）、挂钩加工（¥3/个）...",
        "score": 0.92,
        "source": {
          "document_id": "doc_abc123",
          "title": "遮光窗帘布 - 产品说明",
          "doc_type": "processing_guide"
        }
      }
    ]
  },
  "request_id": "req_abc123"
}
```

### 5.5.6 删除文档

```
DELETE /api/admin/knowledge/documents/{id}
Auth: Required
Cookie: access_token=<JWT>
```

**响应**：

```json
{
  "success": true,
  "data": { "message": "文档及对应向量索引已删除" },
  "request_id": "req_abc123"
}
```

### 5.5.7 批量同步知识库

```
POST /api/admin/knowledge/batch-sync
Auth: Required (super_admin / operation_manager role)
Cookie: access_token=<JWT>
Content-Type: application/json

{
  "sync_mode": "full",  // full / incremental
  "product_ids": ["PROD001", "PROD002"]  // 可选，指定商品
}
```

**响应**：

```json
{
  "success": true,
  "data": {
    "task_id": "batch_sync_001",
    "documents_created": 5,
    "documents_updated": 2,
    "documents_deleted": 1,
    "message": "批量同步完成"
  },
  "request_id": "req_abc123"
}
```

---

## 6. 客服员工工作台 API (admin-api)

> 完整交互协议（含 WebSocket）详见 [客服员工工作台产品设计](../design/agent-workspace-design.md#10-API-设计)。

### 6.1 客服员工认证

#### 员工邀请与注册

```
POST /api/auth/agent/invite
Auth: Required (super_admin / operation_manager / support_supervisor role)
Cookie: access_token=<JWT>
Content-Type: application/json

{
  "tenant_id": "TENANT001",
  "name": "张三",
  "phone": "13800008000",
  "role": "agent"  // agent | supervisor
}
```

**响应**：

```json
{
  "success": true,
  "data": {
    "invite_code": "INV_ABC123",
    "invite_qr_url": "https://migaozn.com/q/INV_ABC123",
    "employee_id": "emp_abc123"
  }
}
```

#### 员工扫码登录（小程序）

```
POST /api/auth/agent/login
Content-Type: application/json

{
  "invite_code": "INV_ABC123",
  "wechat_mini_code": "wx_login_code",
  "tenant_id": "TENANT001"
}
```

**流程**：
1. 员工使用微信扫描邀请二维码，打开客服工作台小程序
2. 小程序调用 `wx.login()` 获取 code
3. 小程序调用 `/api/auth/agent/login`，传入 invite_code + code
4. 后端验证 invite_code 有效性 → 绑定微信 openid → 签发 JWT
5. 返回 JWT（HttpOnly Cookie）

**响应**：

```json
{
  "success": true,
  "data": {
    "employee": {
      "id": "emp_abc123",
      "name": "张三",
      "role": "agent",
      "status": "offline"
    },
    "identity_type": "agent_wechat_mini"
  }
}
```

#### PC H5 扫码登录

```
GET /api/auth/agent/h5/authorize
Query: tenant_code, invite_code, redirect_uri
```

**流程**：同公众号 OAuth，员工在 PC 浏览器访问 H5 工作台面，通过微信扫码授权登录。

### 6.2 员工状态管理

#### 设置在线/离线状态

```
PUT /api/agent/status
Auth: Required (agent role)
Cookie: access_token=<JWT>
Content-Type: application/json

{
  "status": "online"  // online | busy | offline
}
```

**响应**：

```json
{
  "success": true,
  "data": { "message": "状态已更新" }
}
```

#### 获取当前状态

```
GET /api/agent/status
Auth: Required (agent role)
Cookie: access_token=<JWT>
```

**响应**：

```json
{
  "success": true,
  "data": {
    "status": "online",
    "active_sessions": 3,
    "max_concurrent_sessions": 5,
    "today_sessions": 12,
    "today_avg_response_time": 45
  }
}
```

### 6.3 会话管理

#### 获取当前会话列表

```
GET /api/agent/sessions
Auth: Required (agent role)
Cookie: access_token=<JWT>
Query: status=active  // active | queued | ended
```

**响应**：

```json
{
  "success": true,
  "data": {
    "sessions": [
      {
        "id": "as_xxx",
        "customer": {
          "nickname": "李**",
          "phone": "138****8000"
        },
        "ai_session_id": "sess_ai_xxx",
        "status": "active",
        "reason": "用户询问人工客服",
        "wait_time_seconds": 120,
        "total_messages": 5,
        "created_at": "2026-04-12T10:30:00Z"
      }
    ]
  }
}
```

#### 发送消息

```
POST /api/agent/sessions/{session_id}/messages
Auth: Required (agent role)
Cookie: access_token=<JWT>
Content-Type: application/json

{
  "content": "您好，我是人工客服，请问有什么可以帮您？",
  "content_type": "text"  // text | image | file
}
```

**响应**：

```json
{
  "success": true,
  "data": { "message_id": "msg_xxx", "created_at": "2026-04-12T10:31:00Z" }
}
```

#### 结束会话

```
POST /api/agent/sessions/{session_id}/end
Auth: Required (agent role)
Cookie: access_token=<JWT>
Content-Type: application/json

{
  "tags": ["售后咨询", "已解决"],
  "internal_note": "用户问题已解决"
}
```

### 6.4 快捷回复模板

#### 获取模板列表

```
GET /api/agent/quick-replies
Auth: Required (agent role)
Cookie: access_token=<JWT>
Query: category=common  // 可选，按分类过滤
```

#### 创建个人模板

```
POST /api/agent/quick-replies
Auth: Required (agent role)
Cookie: access_token=<JWT>
Content-Type: application/json

{
  "category": "售后",
  "title": "退换货流程",
  "content": "您好，退换货流程如下：1. 提交申请 2. 审核 3. 寄回商品 4. 退款到账"
}
```

### 6.5 管理端 API（管理员角色）

#### 获取员工列表

```
GET /api/admin/agents
Auth: Required (admin role)
Cookie: access_token=<JWT>
```

#### 修改员工最大并发数

```
PUT /api/admin/agents/{employee_id}
Auth: Required (admin role)
Cookie: access_token=<JWT>
Content-Type: application/json

{
  "max_concurrent_sessions": 8
}
```

#### 获取会话监控统计

```
GET /api/admin/sessions/stats
Auth: Required (admin role)
Cookie: access_token=<JWT>
```

**响应**：

```json
{
  "success": true,
  "data": {
    "total_active": 15,
    "total_queued": 3,
    "online_agents": 5,
    "avg_wait_time_seconds": 45,
    "avg_response_time_seconds": 60,
    "today_satisfaction_rate": 0.92
  }
}
```

### 6.6 WebSocket 实时通信协议（PC H5）

**连接端点**：

```
wss://api.migaozn.com/ws/agent?token=<JWT>
```

**服务端推送事件**：

```json
// 新会话分配
{
  "event": "new_session",
  "data": {
    "session_id": "as_xxx",
    "customer": { "nickname": "李**", "phone": "138****8000" },
    "reason": "转人工原因",
    "history": [
      {"sender": "customer", "content": "我要投诉"},
      {"sender": "ai", "content": "请问您要投诉什么问题？"}
    ]
  }
}

// 客户发送新消息
{
  "event": "customer_message",
  "data": {
    "session_id": "as_xxx",
    "content": "你们的产品质量有问题",
    "created_at": "2026-04-12T10:30:00Z"
  }
}

// 会话排队通知
{
  "event": "session_queued",
  "data": {
    "queue_position": 2,
    "estimated_wait_seconds": 60
  }
}

// 客户评价
{
  "event": "customer_rating",
  "data": {
    "session_id": "as_xxx",
    "rating": 5,
    "comment": "服务很好"
  }
}
```

**客户端发送事件**：

```json
// 发送消息
{
  "event": "send_message",
  "data": {
    "session_id": "as_xxx",
    "content": "员工回复",
    "content_type": "text"
  }
}

// 输入中状态
{
  "event": "typing",
  "data": {
    "session_id": "as_xxx"
  }
}

// 请求快捷回复模板
{
  "event": "request_quickreply",
  "data": {
    "category": "售后"
  }
}

// 结束会话
{
  "event": "end_session",
  "data": {
    "session_id": "as_xxx",
    "tags": ["售后咨询", "已解决"]
  }
}
```

---

## 7. 错误码规范

### 7.1 通用错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| AUTH_REQUIRED | 401 | 未认证（Cookie 缺失或 JWT 无效）|
| TENANT_INVALID | 401 | 租户无效 |
| PERMISSION_DENIED | 403 | 权限不足 |
| NOT_FOUND | 404 | 资源不存在 |
| VALIDATION_ERROR | 422 | 参数校验失败 |
| RATE_LIMIT_EXCEEDED | 429 | 请求过于频繁 |
| INTERNAL_ERROR | 500 | 服务器内部错误 |

### 7.2 AI 服务错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| INTENT_LOW_CONFIDENCE | 200 | 意图置信度低 |
| TOOL_NEED_PARAM | 200 | Tool 需要补充参数 |
| QUOTA_EXCEEDED | 429 | 租户配额用尽 |
| LLM_SERVICE_ERROR | 502 | LLM 服务异常 |

### 7.3 认证错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| OAUTH_STATE_INVALID | 400 | OAuth state 校验失败（CSRF）|
| REDIRECT_URI_INVALID | 400 | redirect_uri 不在白名单 |
| MISSING_TIMESTAMP | 400 | 缺少防重放时间戳 |
| MISSING_NONCE | 400 | 缺少防重放 nonce |
| REQUEST_EXPIRED | 400 | 请求已过期 |
| REPLAY_DETECTED | 400 | 检测到重放攻击 |
| TOKEN_REVOKED | 401 | Token 已吊销 |
| TOKEN_EXPIRED | 401 | Token 已过期 |

### 7.4 错误响应格式

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "参数校验失败",
    "details": [
      {
        "field": "price",
        "message": "价格必须大于 0"
      }
    ]
  },
  "request_id": "req_abc123"
}
```

---

## 8. SSE 事件格式

### 8.1 事件类型

| 事件类型 | 说明 | 数据格式 |
|---------|------|---------|
| message | 消息事件（含多种 type）| `{type: "loading|text|card|recommend|error", ...}` |
| done | 对话完成 | `{session_id: "..."}` |

**message 事件的 type 字段**：

| type | 说明 | 数据格式 |
|------|------|---------|
| loading | 加载状态 | `{type: "loading", content: "..."}` |
| text | 文本消息 | `{type: "text", content: "..."}` |
| card | 卡片消息 | `{type: "card", template: "...", data: {...}}` |
| recommend | 推荐功能 | `{type: "recommend", items: [...]}` |
| error | 错误消息 | `{type: "error", code: "...", message: "..."}` |

### 8.2 示例

```
event: message
data: {"type": "loading", "content": "正在查询订单..."}

event: message
data: {"type": "card", "template": "order_detail", "data": {"order_id": "ORD12345", "status": "shipped"}}

event: message
data: {"type": "recommend", "items": [{"id": "logistics", "name": "查看物流", "prompt": "查看物流信息"}]}

event: done
data: {"session_id": "sess_abc123"}
```

> **注意**：完成信号使用独立的 `event: done`（不是 `event: message` + `type: done`），便于前端 EventSource 分别监听。

---

## 10. 请求头规范

### 10.1 浏览器端请求头

| Header | 必填 | 说明 |
|--------|------|------|
| Cookie: access_token | 是 | HttpOnly JWT Cookie（自动携带）|
| Content-Type | 是 | application/json |
| X-Request-Timestamp | 条件 | 认证接口必填（防重放）|
| X-Request-Nonce | 条件 | 认证接口必填（防重放）|

> 不再使用 `Authorization: Bearer <token>` 和 `X-Tenant-Code` 头。tenant_id 从 JWT 自动提取。

### 10.2 内部服务请求头

| Header | 必填 | 说明 |
|--------|------|------|
| X-Internal-Timestamp | 是 | HMAC 签名时间戳（unix epoch） |
| X-Internal-Signature | 是 | HMAC-SHA256 签名（`timestamp:body`）|
| X-Request-Id | 否 | 请求追踪 ID（建议携带）|

> 内部服务不使用 JWT Cookie，通过 HMAC 共享密钥认证。详见 auth-and-deployment.md §3.4。
