# admin-web OSS → SAE 迁移记录

> 日期：2026-06-24
> 状态：已完成，CI/CD 全链路通过

---

## 1. 迁移原因

OSS 静态托管方案的核心矛盾：Next.js App Router 动态路由（`[id]`）天然需要运行时，`output: "export"` 把运行时阉割掉后，靠一坨脚本补回来：

```
generateStaticParams → 占位页 → SPA fallback → OSS ErrorDocument → JS 路由匹配 → history.replaceState
```

这个链条任何一环断裂都会导致页面不可访问。实际踩过的坑：
- `generateStaticParams return []` → Next.js 编译失败
- `npx next build` 不触发 postbuild hook → `_spa-fallback.html` 缺失
- OSS NoSuchKey 回潮 → 发货按钮 404

换成 SAE `next start` 后，动态路由由服务端原生处理，以上全删。

---

## 2. 最终架构

```
用户 → merchant.migaozn.com (CDN) → CLB (公网) → SAE (next start -p 3001)
```

| 组件 | 资源 |
|------|------|
| SAE 应用 | `ai-customer-service-admin-web` (500mC/1GB, SAE v2, Image) |
| CLB | 公网 CLB，端口 3001 |
| CDN | `merchant.migaozn.com` 回源 → CLB:3001 |
| 镜像仓库 | ACR 个人版 `crpi-...personal.cr.aliyuncs.com/ai-customer-service/admin-web` |

---

## 3. 踩坑记录

### 坑 1：SAE 应用不能用 placeholder 镜像创建

**症状**：SAE 实例一直 `ImagePullBackOff`，所有部署全部失败。

**原因**：`aliyun sae CreateApplication --ImageUrl ...:placeholder` 时，SAE 尝试拉取 placeholder 镜像并永久缓存失败。后续即使改镜像，SAE 也不会重试。

**解决**：创建 SAE 应用时必须用**真实存在的 ACR 镜像**。先用 CI 构建一个初始镜像推送到 ACR，再用这个镜像创建应用。或者直接在 SAE 控制台创建（控制台会自动处理 ACR 凭证）。

**教训**：
- ❌ `--ImageUrl crpi-.../admin-web:placeholder`
- ✅ `--ImageUrl crpi-.../admin-web:v20260624151824`（先 CI 构建再创建）

### 坑 2：SAE CLI 创建的 SLB 绑定不生效

**症状**：`deployApplication --InternetSlbId xxx --Internet true --Port 3001` 调用成功，但 SLB 监听器的 VServer group 始终为空。

**原因**：SAE v2 的 SLB 绑定需要通过 SAE 控制台（或 SAE 内部 K8s 控制器）完成。CLI 的 `--InternetSlbId` 参数被静默忽略。

**解决**：在 SAE 控制台手动创建公网 CLB 绑定。SAE 会自动创建 VServer group 和健康检查。

### 坑 3：Dockerfile 端口和 SAE 端口不一致

**症状**：CLB 返回 502 Bad Gateway。

**原因**：Dockerfile `EXPOSE 80`，SAE 部署 `--Port 3001`，CLB 转发 3001 → 容器 3001，但容器只听 80。

**解决**：确保三者一致：
- Dockerfile：`EXPOSE 3001` + `CMD ["next", "start", "-p", "3001"]`
- SAE deploy：`--Port 3001` + `--Envs '[{"name":"PORT","value":"3001"}]'`
- CLB 监听器：端口 3001 → 后端 3001

### 坑 4：CDN 回源 OSS 残留

**症状**：CDN 域名返回 OSS 缓存内容（`.html` 扩展名、404）。

**原因**：CDN 源站改成 SAE 后，已有缓存不会自动失效。

**解决**：每次部署后调用 `aliyun cdn RefreshObjectCaches` 刷新目录缓存。

### 坑 5：E2E auth.setup.ts cookie domain 硬编码

**症状**：E2E 测试 auth setup 失败，dashboard 找不到 `aside` 元素。

**原因**：cookie domain 写死 `localhost`，云 dev 环境用 `merchant.migaozn.com`，cookie 不生效。

**解决**：从 `baseURL` 动态提取域名，对齐应用 `COOKIE_DOMAIN` 配置。

### 坑 6：同一 SLB 多端口共享问题

**症状**：想把 admin-web 绑到 admin-api 已有的 SLB 上新端口，但 SAE 不创建 VServer group，手动添加 ENI 后端也失败（SAE ENI 只能由 SAE 管理）。

**解决**：不要复用已有 SLB。通过 SAE 控制台创建独立公网 CLB，让 SAE 全权管理。

---

## 4. 删除的代码

| 文件/配置 | 行数 | 说明 |
|-----------|------|------|
| `generate-spa-fallback.js` | 163 | SPA fallback 路由匹配 |
| `generateStaticParams()` ×6 | 42 | 6 个 page.tsx 中的占位页生成 |
| `generateStaticParams.test.ts` | 76 | 对应的单测 |
| `postbuild` hook | 1 | package.json |
| `output: 'export'` | 1 | next.config.mjs |
| deploy lint guard | 19 | 防止 generateStaticParams 回退 |
| **合计** | **~300** | |

---

## 5. CI/CD 部署流程

每次 push `frontend/admin-web/**` 或手动触发：

```
1. Checkout + Setup Node.js
2. npm ci + tsc --noEmit + vitest run
3. docker build → tag + push ACR
4. aliyun sae deployApplication (ACR 镜像)
5. 等待 SAE 变更完成 (12 次轮询)
6. curl health check (CLB:3001/login/)
7. CDN 缓存刷新
```

---

## 6. 运维清单

**日常**：无需操作，Git push → CI 自动部署。

**紧急回滚**：SAE 控制台 → 应用 → 变更记录 → 回滚到上一个版本。

**新增页面**：直接创建 `page.tsx` 即可，不再需要 `generateStaticParams`。

**日志查看**：SAE 控制台 → 应用 → 日志（需先开启 SLS 日志采集）。
