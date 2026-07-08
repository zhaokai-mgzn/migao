# RBAC 权限体系

## 5 角色

| 角色 | 编码 | 说明 |
|------|------|------|
| 企业管理员 | admin | 商家系统最高权限，全部菜单 + 本租户全部数据 |
| 运营经理 | operation_manager | 数据看板 + AI 配置 + 业务管理 |
| 客服主管 | support_supervisor | 客服团队管理 + 服务质量监控 |
| 客服员工 | support_agent | 仅我的会话 + 快捷回复 |
| 商品管理员 | product_manager | 商品管理 + 订单只读 |

## 权限模型

```
users ──< user_roles >── roles ──< role_permissions >── permissions
```

- **用户-角色**: 一个用户可分配多个角色 (user_roles 关联表)
- **角色-权限**: 角色关联权限列表
- **权限粒度**: 菜单权限 + 按钮级权限 + 数据范围权限

## JWT Claims

```json
{
  "sub": "user_id",
  "tenant_id": "TENANT001",
  "role": "admin",
  "permissions": ["product:write", "order:read", ...],
  "exp": 1704153600
}
```

- RS256 非对称签名 (admin-api 持私钥, 其他服务持公钥)
- `permissions` claim 供米宝 Tool 细粒度鉴权
- `tenant_id` 从 JWT 提取，禁止客户端 Header 传入

## 强制点

| 层 | 机制 |
|----|------|
| API 网关 | JWT 校验 + CORS 白名单 |
| Controller | `@RequirePermission` 注解 + `PermissionInterceptor` 切面 |
| Service | MyBatis 拦截器自动注入 `WHERE tenant_id = ?` |
| Database | PostgreSQL RLS Policy (每张业务表) |
| AI Tool | `required_permissions` 字段声明 → Tool 注册时校验 |

## 菜单过滤

前端侧边栏根据 `role` + `permissions` 动态渲染：
- admin → 全部菜单
- operation_manager → 看板/商品/订单/配置
- support_supervisor → 坐席/客服团队/快捷回复
- support_agent → 仅我的会话/快捷回复
- product_manager → 商品/分类/加工项 + 订单只读

## 登录方式

| 端 | 接口 | 认证方式 |
|----|------|---------|
| 小程序 | `/api/auth/mini/login` | wx.login() → code → JWT |
| 管理后台 | `/api/auth/account/login` | 手机号+密码/短信 → JWT |
| 公众号H5 | `/api/auth/h5/authorize` | OAuth 2.0 → code → JWT |
| 服务间 | X-Internal-Signature | HMAC-SHA256 共享密钥 |

---
详见: [认证部署](../deployment/auth-and-deployment.md) · [API 参考](../api/api-reference.md)
