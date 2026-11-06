# 多租户微信小程序接入方案（每企业独立小程序）

> 版本 v1.0 ｜ 目标：多个企业各自有独立微信小程序（不同 appid/secret），共享同一后端 API 域名。

---

> # ⚠️ 2026-11-05 方向调整：本方案已降级（原文一字未删，作历史记录）
>
> **「每企业一个独立小程序」不再作为默认链路。**
> 调整依据 = 微信官方文档一手调研，底稿 [`docs/wechat-store-and-kefu-research.md`](../wechat-store-and-kefu-research.md)；
> 跟踪单 = issue #8744（**方向单：待评审**，尚未排期、代码零改动）。
>
> - **降级**：本文档的「每企业一个 appid/secret + 独立小程序」→ **旗舰版可选增值项**；
>   §三 的方案 C（泛域名 + 租户映射）同理只在旗舰版需要。
> - **替代**：默认改为 **1 个平台自营小程序**（单 appid）+ **微信客服**（对话面）+ **微信小店**（交易面）。
> - **保留**：§四 后端改造里「按租户查 `TenantApp` 的 appid/secret」的兜底逻辑仍有效（旗舰版走它），
>   但不再是主路径 —— 单 appid 之后，**租户判定改由显式上下文决定**
>   （小程序 path 参数 / 二维码场景值 / 微信客服 `open_kfid`），不再靠 appid 区分租户。
> - **支付**：原方案里的支付前提（`docs/design/tenant-miniapp-launch-and-payment.md` 的 **D2：服务商 + 特约商户**）**暂缓**；
>   交易改走**微信小店**（钱进商户自己的微信支付商户号，平台不经手资金、无二清问题）。
>
> **本文件 v1.0 的正文全部保留** —— 保留用于回溯「原链路为什么走不通」。

---

## 一、现状与缺口

| 层 | 现状 | 缺口 |
|---|---|---|
| 数据模型 | ✅ `tenant_apps` 表已支持 appType/appId/appSecret/token/encodingAesKey | — |
| 登录入口 | ✅ `miniProgramLogin(code, tenantId)` 已接收 tenantId | — |
| 微信换 openid | ❌ `wechatService.code2Session(code)` 用全局 `@Value` 单一 appid/secret | **未按租户查 TenantApp** |

## 二、微信技术约束（决定方案的前提）

1. `wx.login()` 的 code **只能用产生它的小程序的 appid/secret** 换 openid（用错 → `invalid appid`）
2. 不同小程序 openid 互相隔离（unionid 打通除外）
3. 约束 1 是天然安全屏障：前端传错 tenantId → 后端用错 appid → code2Session 失败 → 无法冒充

## 三、方案对比

| 方案 | 说明 | 优缺点 |
|---|---|---|
| A. 每企业独立子域名 | `tenant-a.migaozn.com` 每企业一条 | URL 清晰、域名隔离；但手动配 DNS+SSL 繁琐 |
| B. 单域名 + tenantId | 共用 `api.migaozn.com` | 部署简单；无域名隔离 |
| C. 泛域名 + 租户映射 ⭐ | `*.migaozn.com` 泛解析 + 泛 SSL + 子域名→tenantId | 兼顾隔离 + 省事 |

## 四、推荐方案 C 落地步骤

1. **DNS 泛解析**：`*.migaozn.com → 服务器IP`（一条记录，自动覆盖所有子域名）
2. **泛域名 SSL**：`*.migaozn.com` 通配符证书
3. **子域名 → tenantId 映射**：
   - nginx：`map $host $tenant_id { tenant-a.migaozn.com A; tenant-b.migaozn.com B; }`
   - 或后端中间件解析 Host 前缀
4. **后端改造（核心）**：
   ```java
   // WechatService：按 tenantId 查 TenantApp 的 appid/secret
   public Code2SessionResult code2Session(String code, Long tenantId) {
       TenantApp app = tenantAppMapper.selectByTenantAndType(tenantId, "mini_program");
       if (app == null || !StringUtils.hasText(app.getAppId())) {
           return mockCode2Session(code);  // 未配置则 mock
       }
       return realCode2Session(code, app.getAppId(), app.getAppSecret());
   }
   ```
5. **每企业小程序后台**：配置自己的子域名作为 request 合法域名

## 五、关键技术决策

- **openid 隔离**：`user_identities` 表已按 `(openid, tenant_id, identity_type)` 唯一，天然支持多租户 openid 隔离
- **unionid 打通（可选）**：如需跨企业识别同一用户，需开放平台绑定 + unionid 字段
- **mock 兜底**：企业未配置 appid/secret 时走 mock（`mock_openid_<sha256(code+tenantId)>`），保证开发/演示可用
- **域名与租户**：子域名是「入口标识」，租户数据隔离靠 tenant_id（数据库层），两者解耦

## 六、验收标准

- 企业A、B 各自小程序登录 → 各自 openid → 各自数据隔离
- 前端传错 tenantId → code2Session 失败（无法冒充）
- 未配置 appid 的企业 → mock 模式可演示
