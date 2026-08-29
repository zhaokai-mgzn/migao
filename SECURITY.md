# 安全政策（Security Policy）

MIGAO（AI 智能客服系统）重视安全问题。感谢你帮助我们保护使用本系统的企业、商户与终端用户。

## 支持的版本

当前项目处于 **POC 阶段**，尚未发布语义化版本（v0.x 尚未打 tag）。此阶段安全修复将直接合入 `main` 分支，并尽快随下一次部署生效。

| 版本 | 安全修复支持 |
|------|------------|
| `main`（最新） | ✅ 支持 |
| 历史 tag | 未发布（无） |

## 报告漏洞（Reporting a Vulnerability）

请 **不要** 通过公开 Issue 或评论披露漏洞细节。请通过以下任一渠道报告：

1. **首选**：GitHub 私有漏洞报告（Security Advisories）——仓库主页 `Security` 页签 → `Report a vulnerability`（仅仓库维护者可见）
2. 备选：在本仓库新建 Issue 时选择 `bug` 模板，并在标题以 `[SECURITY]` 开头（请勿在正文附上可利用的完整攻击载荷）

### 响应承诺

| 时间 | 承诺 |
|------|------|
| 48 小时内 | 确认收到报告 |
| 7 天内 | 初步评估：影响面、严重性分级、修复计划 |
| 30 天内 | 对严重（Critical/High）问题发布修复并合入 `main` |

我们会与报告者保持沟通，并在修复合并后致谢（经报告者同意）。

## 已知限制（POC 阶段，接受的风险）

以下为当前阶段**已知且被接受**的安全限制，接入真实生产前必须处理（详见技术债 Issue #2616）：

- **SMS 万能验证码**：`sms.bypass-code` 默认值 123456（`application.yml`），任意手机号可完成登录校验；接入真实短信服务后必须移除。
- **AI 服务 DEBUG 直通**：ai-agent-service 在 `DEBUG=true` 时绕过安全配置校验，且无 token 可进入租户 1 管理员会话；生产必须 `DEBUG=false`。

## 通用安全实践

- 所有密钥（RDS/Redis/OSS/LLM/ACR 等）通过环境变量注入，**禁止**提交 `.env` 与真实密钥（CI 已设 `.env` 提交门禁）。
- 生产部署请遵循 `docs/wiki/Deployment.md` 与 `docs/deployment/deployment-checklist.md`。
- 报告漏洞时请尽量附上：影响组件、复现步骤、影响的租户/数据范围（如有）、建议修复方向。
