# 多租户多端架构设计

> 版本：v8.0（2 服务架构 + 公众号 OAuth + CRM 客户管理）  
> 日期：2026-04-12  
> 核心原则：后端共用，前端可选，租户自行配置

---

## 一、为什么需要多端支持

作为 SaaS 平台，不同租户（企业）的微信生态资产不同：

| 租户类型 | 已有资产 | 需要的客服入口 |
|---------|---------|---------------|
| 初创企业 | 订阅号 | 公众号 H5 |
| 中型企业 | 服务号 | 服务号 H5 + 模板消息推送 |
| 成熟企业 | 服务号 + 小程序 | 小程序 + 公众号 H5 双端 |
| 企业微信用户 | 企业微信 | 企业微信应用 |

**不能替租户做选择**，只能提供多端能力，让租户在管理后台自行配置启用哪些端。

---

## 二、整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        SaaS 管理后台                             │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ 租户管理     │  │ 应用配置管理  │  │ 用量统计 & 计费         │ │
│  │ (开通/停用)  │  │ (小程序/H5)  │  │ (按调用量/租户计费)     │ │
│  └─────────────┘  └──────────────┘  └────────────────────────┘ │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                      阿里云 API Gateway                          │
│  /api/auth/mini/login    → admin-api (小程序登录)                │
│  /api/auth/h5/authorize  → admin-api (H5 OAuth 跳转)            │
│  /api/auth/h5/callback   → admin-api (H5 OAuth 回调)            │
│  /api/chat/*             → ai-agent-service (AI 客服)           │
│  /api/admin/*            → admin-api (管理后台)                  │
└────┬──────────────┬──────────────┬───────────────┬──────────────┘
     │              │              │               │
┌────▼───┐  ┌──────▼──────┐  ┌───▼────┐  ┌──────▼──────┐
│ 小程序  │  │ 公众号 H5   │  │ 管理   │  │ AI 代理服务  │
│ (微信)  │  │ (OSS+CDN)  │  │ 后端   │  │ (SAE)       │
│        │  │             │  │ (SAE)  │  │             │
│ 租户A  │  │ 租户A H5    │  │        │  │ 共用        │
│ 租户B  │  │ 租户B H5    │  │        │  │ 同一套代码   │
│ 租户C  │  │ 租户C H5    │  │        │  │             │
└────────┘  └─────────────┘  └────────┘  └─────────────┘
```

**核心设计**：后端服务完全不感知前端来源，只认 JWT 中的 tenant_id 和 user_id。

**服务说明**：
- `admin-api`：统一管理后台 API，负责租户管理、应用配置、用户认证（小程序登录 + 公众号 OAuth）
- `ai-agent-service`：统一的 AI 代理服务，整合了对话和智能体能力，所有前端渠道共用同一套代码

---

## 三、租户应用配置

### 3.1 数据模型

```sql
-- 租户应用配置表（每个租户可配置多个应用）
CREATE TABLE tenant_apps (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id),
    app_type VARCHAR(32) NOT NULL,       -- wechat_mini / wechat_h5 / web
    app_id VARCHAR(128) NOT NULL,         -- 微信 AppID
    app_secret VARCHAR(255),              -- 加密存储
    token VARCHAR(255),                   -- 微信公众号 Token
    encoding_aes_key VARCHAR(255),        -- 消息加密密钥
    msg_encrypt_mode VARCHAR(32) DEFAULT 'safe',  -- plaintext / compatible / safe
    server_url VARCHAR(512),              -- 回调服务器 URL
    status VARCHAR(32) DEFAULT 'active',  -- active / inactive
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(tenant_id, app_type)
);

-- 索引
CREATE INDEX idx_tenant_apps_tenant ON tenant_apps(tenant_id);
CREATE INDEX idx_tenant_apps_appid ON tenant_apps(appid);
```

### 3.2 配置示例

```
租户 A（成熟企业）配置：
├── tenant_apps:
│   ├── { tenant_id: A, app_type: mini_program, appid: "wx_mini_a_1", ... }
│   └── { tenant_id: A, app_type: h5, appid: "wx_h5_a_1", ... }

租户 B（只有服务号）配置：
├── tenant_apps:
│   └── { tenant_id: B, app_type: h5, appid: "wx_h5_b_1", ... }

租户 C（只有小程序）配置：
├── tenant_apps:
│   └── { tenant_id: C, app_type: mini_program, appid: "wx_mini_c_1", ... }
```

### 3.3 租户管理后台

在 SaaS 管理后台（admin-frontend）中，管理员可以为每个租户配置：

```
租户详情 > 应用配置

+------------------+--------+-------------------+--------+
| 应用类型          | 名称   | AppID            | 状态   | 操作
+------------------+--------+-------------------+--------+
| 微信小程序        | 客服小  | wx1234567890     | 启用   | 编辑/停用
| 公众号 H5         | 客服H5  | wx0987654321     | 启用   | 编辑/停用
+------------------+--------+-------------------+--------+

[+ 新增应用]
```

新增应用时选择类型（小程序/H5），填入 AppID 和 AppSecret，系统自动校验连通性后保存。

---

## 四、统一身份模型

### 4.1 核心问题：同一用户在不同端的 openid 不同

微信的机制：
- 同一用户对**不同小程序**的 openid 不同
- 同一用户对**不同公众号**的 openid 不同
- 但如果小程序和公众号都绑定到**同一个微信开放平台**，用户的 **unionid 是相同的**

### 4.2 设计方案

```sql
-- 用户主表
CREATE TABLE users (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id),
    phone VARCHAR(32),
    nickname VARCHAR(128),
    avatar VARCHAR(512),
    role VARCHAR(32) DEFAULT 'customer',  -- customer / agent / admin
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 用户身份表（一个用户可以有多个端身份）
CREATE TABLE user_identities (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id),
    user_id VARCHAR(64) NOT NULL REFERENCES users(id),
    identity_type VARCHAR(32) NOT NULL,    -- wechat_mini / wechat_h5 / account
    app_id VARCHAR(128),                   -- 来源 AppID
    openid VARCHAR(128) NOT NULL,          -- 该端的 openid
    unionid VARCHAR(128),                  -- 开放平台 unionid（可选）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- 同一租户内，同一 App 的 openid 唯一
    UNIQUE(tenant_id, app_id, openid),
    -- unionid 索引（用于跨端识别同一用户）
    UNIQUE(tenant_id, unionid) WHERE unionid IS NOT NULL
);

CREATE INDEX idx_user_identities_user ON user_identities(user_id);
CREATE INDEX idx_user_identities_unionid ON user_identities(tenant_id, unionid);
```

### 4.3 跨端识别流程

```
用户先用小程序登录：
  openid = "openid_mini_123", unionid = "unionid_X"
  → 创建 user_1
  → 创建 identity: { type: wechat_mini, openid: openid_mini_123, unionid: unionid_X }

同一用户后来从公众号 H5 登录：
  openid = "openid_h5_456", unionid = "unionid_X"
  → 查询 user_identities WHERE tenant_id = X AND unionid = unionid_X
  → 找到 user_1
  → 新增 identity: { type: wechat_h5, openid: openid_h5_456, unionid: unionid_X }
  → 用户仍然是同一个 user_1

结果：用户在小程序和 H5 中的对话历史、订单数据完全打通。
```

---

## 五、多端登录流程

### 5.1 微信小程序登录

```
小程序端                    admin-api                       微信服务器
  │                              │                              │
  │ 1. wx.login() → code         │                              │
  │ ────────────────────────────>│                              │
  │  POST /api/auth/mini/login   │                              │
  │  { code, tenant_id }         │                              │
  │                              │                              │
  │                              │ 2. code2Session              │
  │                              │ ────────────────────────────>│
  │                              │    返回 openid + session_key │
  │                              │    + unionid (如果绑定了开放) │
  │                              │ <────────────────────────────│
  │                              │                              │
  │                              │ 3. 按 unionid 查找已有用户    │
  │                              │    或按 openid 查找           │
  │                              │    都没有 → 创建新用户        │
  │                              │    已有 → 更新 identity       │
  │                              │                              │
  │ <────────────────────────────│                              │
  │  { token, user }             │                              │
  │                              │                              │
  │ 4. wx.setStorageSync(token)  │                              │
```

### 5.2 微信公众号 OAuth 扫码登录

```
H5 浏览器                    admin-api                       微信服务器
  │                              │                              │
  │ 1. 扫描二维码 → 跳转授权     │                              │
  │ ────────────────────────────>│                              │
  │  GET /api/auth/h5/authorize  │                              │
  │                              │                              │
  │ 2. 302 跳转微信 OAuth 页     │                              │
  │ <────────────────────────────│                              │
  │                              │                              │
  │ 3. 用户确认授权               │                              │
  │ ────────────────────────────────────────────────────────────>│
  │                              │                              │
  │ 4. 回调 /api/auth/h5/callback │                              │
  │ ────────────────────────────>│                              │
  │                              │ 5. OAuth access_token        │
  │                              │ ────────────────────────────>│
  │                              │    返回 openid + unionid     │
  │                              │ <────────────────────────────│
  │                              │                              │
  │                              │ 6. 按 unionid 查找已有用户    │
  │                              │    （关联小程序身份）         │
  │ <────────────────────────────│                              │
  │  Set-Cookie + 302 跳转       │                              │
```

### 5.3 公众号 H5 登录（网页授权 OAuth）

```
H5 浏览器                   admin-api                       微信服务器
  │                              │                              │
  │ 1. 点击"微信登录"            │                              │
  │ ────────────────────────────>│                              │
  │  GET /api/auth/h5/authorize  │                              │
  │  { tenant_code }             │                              │
  │                              │                              │
  │                              │ 2. 根据 tenant_code 查 AppID │
  │ <────────────────────────────│                              │
  │  302 跳转微信授权页           │                              │
  │  https://open.weixin.qq.com/ │                              │
  │  connect/oauth2/authorize    │                              │
  │                              │                              │
  │ 3. 用户确认授权                │                              │
  │ ────────────────────────────────────────────────────────────>│
  │                              │                              │
  │ 4. 回调 code + state         │                              │
  │ ────────────────────────────>│                              │
  │  GET /api/auth/h5/callback   │                              │
  │  { code, state, tenant_code }│                              │
  │                              │                              │
  │                              │ 5. 校验 state                │
  │                              │ 6. code → access_token       │
  │                              │    → openid + unionid        │
  │                              │ ────────────────────────────>│
  │                              │ <────────────────────────────│
  │                              │                              │
  │                              │ 7. 按 unionid 查找/创建用户  │
  │ <────────────────────────────│                              │
  │  Set-Cookie: access_token    │                              │
  │  302 跳转回 H5 对话页         │                              │
```

### 5.4 两种登录的统一处理

```java
// admin-api/src/main/java/com/ai_customer_service/auth/service/AuthenticationService.java

class AuthenticationService:
    async def _find_or_create_user(
        self, 
        tenant_id: str,
        identity_type: str,
        app_id: str,
        openid: str,
        unionid: str | None,
        defaults: dict
    ) -> User:
        """
        统一的查找/创建逻辑
        1. 优先按 unionid 查找（跨端识别同一用户：小程序和 H5 共享 unionid）
        2. 再按 openid + app_id 查找（同一端重复登录）
        3. 都不存在 → 创建新用户 + 新 identity
        
        跨平台身份关联：
        - 用户先用小程序登录，获得 unionid_X
        - 同一用户后来从公众号 H5 扫码登录，也拿到 unionid_X
        - 通过 unionid 自动关联为同一个 user，对话历史完全打通
        - 注意：unionid 依赖微信开放平台绑定，小程序和公众号必须关联到同一开放平台账号
        """
        # 1. 按 unionid 查找
        if unionid:
            identity = await self.db.query(UserIdentity).filter(
                UserIdentity.tenant_id == tenant_id,
                UserIdentity.unionid == unionid
            ).first()
            if identity:
                # 更新或新增 identity 记录
                await self._upsert_identity(identity.user_id, identity_type, app_id, openid, unionid)
                return await self.db.query(User).filter(User.id == identity.user_id).first()
        
        # 2. 按 openid + app_id 查找
        identity = await self.db.query(UserIdentity).filter(
            UserIdentity.tenant_id == tenant_id,
            UserIdentity.app_id == app_id,
            UserIdentity.openid == openid
        ).first()
        if identity:
            return await self.db.query(User).filter(User.id == identity.user_id).first()
        
        # 3. 创建新用户
        user = await self._create_user(tenant_id, defaults)
        await self._create_identity(user.id, tenant_id, identity_type, app_id, openid, unionid)
        return user
```

---

## 六、小程序多租户方案

### 6.1 两种模式

| 模式 | 说明 | 适合 |
|------|------|------|
| **模式 A：一租户一小程序** | 每个租户自己注册小程序，填入 AppID/AppSecret | 有品牌诉求的成熟企业 |
| **模式 B：SaaS 统一小程序** | 所有租户共用一个小程序，通过 tenant_code 区分 | 初创期、租户无小程序资质 |

### 6.2 模式 A：一租户一小程序

每个租户提供自己的小程序 AppID，代码是同一套，只是构建时注入不同的 appid：

```bash
# 为租户 A 构建小程序
cd mini-program
APPID=wx_tenant_a npm run build
# 上传到租户 A 的微信公众平台

# 为租户 B 构建小程序
APPID=wx_tenant_b npm run build
# 上传到租户 B 的微信公众平台
```

后端通过 `tenant_apps` 表管理每个租户的 AppID/AppSecret，登录时自动匹配。

### 6.3 模式 B：SaaS 统一小程序

一个小程序服务所有租户，用户进入后选择企业（或扫码自动识别）：

```
┌─────────────────────────┐
│   SaaS 统一小程序首页     │
│                         │
│  搜索或扫码识别企业       │
│  ┌───────────────────┐  │
│  │ 输入企业邀请码      │  │
│  │ [__________] 确认  │  │
│  └───────────────────┘  │
│                         │
│  或扫描企业专属二维码     │
│  → 自动跳转到该企业客服   │
└─────────────────────────┘
```

后端通过小程序传来的 tenant_code 或二维码中的参数确定租户。

### 6.4 推荐策略

- **Phase 1（当前）**：模式 B 统一小程序，降低租户接入门槛
- **Phase 2（有需求时）**：增加模式 A 支持，允许租户绑定自有小程序
- 两种模式后端共用同一套 admin-api 认证逻辑

### 6.5 公众号 H5 的定位

> **注意**：公众号 H5 渠道主要作为开发和测试用途使用，方便开发人员在浏览器中快速验证功能。
> **生产环境的主力渠道是微信小程序**，小程序提供更好的用户体验、原生能力和消息推送支持。
> H5 渠道保留是为了满足部分租户（如只有订阅号的初创企业）的轻量级接入需求。

---

## 七、API 设计

### 7.1 认证 API

| 端 | 端点 | 方法 | 说明 |
|----|------|------|------|
| 小程序 | `POST /api/auth/mini/login` | 公开 | { code, tenant_id } → { token, user } |
| H5 | `GET /api/auth/h5/authorize` | 公开 | { tenant_code } → 302 跳转微信 |
| H5 | `GET /api/auth/h5/callback` | 公开 | { code, state, tenant_code } → Set-Cookie + 302 |
| 管理后台 | `POST /api/auth/account/login` | 公开 | { phone, password, tenant_code } → Set-Cookie |

### 7.2 租户应用配置 API

| 端点 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `GET /api/admin/tenants/{id}/apps` | GET | 管理员 | 获取租户应用列表 |
| `POST /api/admin/tenants/{id}/apps` | POST | 管理员 | 新增应用配置 |
| `PUT /api/admin/tenants/{id}/apps/{app_id}` | PUT | 管理员 | 更新应用配置 |
| `DELETE /api/admin/tenants/{id}/apps/{app_id}` | DELETE | 管理员 | 停用应用配置 |

---

## 八、未来扩展

| 端 | 登录方式 | 后端新增 |
|----|---------|---------|
| 企业微信 | OAuth 2.0 + CorpID | /api/auth/work/login |
| 钉钉 | OAuth 2.0 | /api/auth/dingtalk/login |
| Web 独立登录 | 手机号 + 验证码 | /api/auth/sms/login |

所有新增端都通过 `_find_or_create_user` 统一方法接入，共享同一套 JWT 和业务服务。
