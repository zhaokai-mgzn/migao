# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，并采用语义化版本（[Semantic Versioning](https://semver.org/lang/zh-CN/)）。

> 当前处于 POC 阶段（v0.x），尚未发布首个公开版本。以下变更记录自 2026-08 起维护。

## [Unreleased]

### 安全加固（POC 显式化）

- `admin-api`：SmsService 增加 `@PostConstruct` 启动警告——`sms.bypass-code` 非空时打印醒目 WARN（POC 模式万能验证码显式化，技术债 Issue #2616）
- `admin-api`：`verifyCode` 命中万能验证码的日志由 INFO 升级为 WARN（含 Issue #2616 指引）
- `ai-agent-service`：`.env.example` 的 `DEBUG` 默认值改为 `false`，并注释说明生产禁用与本地开发用法
- `ai-agent-service`：`[tool-exec]` 错误日志的 `tool_args` 经 `LogSanitizer.sanitize_tree` 递归脱敏（手机号/邮箱/敏感 key 打码）
- `ai-agent-service`：记忆提取增加 PII 过滤（`_filter_pii`）——手机号/地址/邮箱类记忆不落库，提取提示词禁止 PII

### 开源治理

- 新增 `SECURITY.md`（安全漏洞报告政策与响应承诺）
- 新增 `CODE_OF_CONDUCT.md`（贡献者公约 2.1）
- 新增 `CHANGELOG.md`（本文件）
- 新增 `.github/dependabot.yml`（Maven / pip / npm / GitHub Actions 依赖自动更新）
- 新增 `.github/FUNDING.yml`（赞助入口占位）
- 新增 `CONTRIBUTING.md`（外部贡献者指南：Issue 先行 / 分支 / TDD / PR 门禁）
- `README.md` 全面修订：修正文档矛盾（工具 31、Controller 27、Service 23、Entity/Mapper 44、Boot 3.3.9、表 41 等）、RAG 按决策 D1 标注暂不开放、新增 CI/License badges
- `pr-check` 新增 Secret Scan (gitleaks) job
