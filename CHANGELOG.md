# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，并采用语义化版本（[Semantic Versioning](https://semver.org/lang/zh-CN/)）。

> 当前处于 POC 阶段（v0.x），尚未发布首个公开版本。以下变更记录自 2026-08 起维护。

## [Unreleased]

### 图片消息崩溃修复（2026-09-05，#2884）

- `ai-agent-service`：C 端小布 pending_skill 存在时发图崩溃——`intent_router_node` 对多模态 list content 调 `.strip()` 抛 `AttributeError`（会话 sess_806703a2dcca4059 真实报错），改用 `_get_last_human_text` 提取纯文本后再判消息长度；回归测试锁定（case_ids: CH-021，#2884）

### C 端小布长期记忆系统（2026-09-04，#2815/#2818）

- `ai-agent-service`：C 端用户画像记忆 + 会话末聚合——agent_type 分流（xiaobu/mibao），受控词表 + PII 过滤（手机号/地址/邮箱类记忆不落库），提取提示词禁止 PII
- `ai-agent-service`：记忆注入接线（context_builder/context_manager），合规 API（/memories 查询/删除），会话状态持久化
- `ai-agent-service`：下单地址自动填充——customer_address_query 查历史收货信息预填表单（issue #2815）
- `admin-api`：customerAddress 相关接口；迁移/清理脚本（scripts/cleanup_user_memories.py，默认 dry-run 幂等）；docs/sql/migrations/V20260904__add_agent_type_to_user_memories.sql
- 行为用例 CH-024/CH-025/MC-013~015 与 C 端长期记忆测试补全（case_ids 全声明）

### 澄清轮护栏与图片澄清（2026-09-03，#2790/#2795/#2797/#2800/#2816/#2817）

- `ai-agent-service`：澄清轮次护栏真实生效——连续模糊意图 ≥2 轮转示例兜底（防低学历用户被无限追问，#2797/#2816/#2817）
- `ai-agent-service`：Phase 2 澄清卡承载——B 端 general 澄清卡 + C 端图片候选意图（低学历随手发图，#2790）
- `ai-agent-service`：Phase 2c 图片澄清候选 grounded——关键词检索命中真实商品，不编造（#2800）
- `tests/agent_eval`：agent-eval 图片消息支持——澄清用例可发真图（Phase 3 前置，#2795）

### GB/T 47746-2026 合规（2026-09-01~04，#2779/#2785/#2781/#2788/#2805/#2806/#2808/#2809）

- `docs`：合规差距分析与落地路线（四路审计结论，#2779）；差距矩阵收尾——GB-01~04 全部闭合（3.5/3.6 🟢，#2805）
- `ai-agent-service`：承诺边界工具层收口 M1/M2——确认闸/报价默认价/权限/教学语料（#2782→#2785）
- `xiaobu`：消息级 AI 助手/人工客服来源标识——转人工后人机可区分（#2780→#2781）
- `handoff`：转人工携带 AI 对话上下文快照——人工客服无需顾客复述（#2776→#2778）
- `admin-web`：官网主页 GB/T 47746-2026 遵循国家标准宣称区块（#2787→#2788）
- `admin-api`：M3 服务端取价校验——agent 下单 unitPrice 与 SKU 权威价严格一致（#2806→#2813）
- `admin-web`：B 端 agent 命名统一——米高=平台、agent=米宝（GB-05-B，#2807→#2809）
- `admin-web`：宣传真实性——移除「AI 自动学习/越用越懂/基于知识库精准应答」夸大表述（#2807→#2808）

### 全栈时区统一 UTC+8（2026-09-04，#2810/#2814）

- `ai-agent-service`：营业时间按租户时区判断 + 全栈统一 UTC+8（is_after_hours 时区缺陷，#2810）
- `deploy`：nginx 容器统一时区 UTC+8（补齐全栈时区合规，#2814）

### 财务/看板/RBAC 修复（2026-09-03，#2802/#2803/#2804）

- `admin-api`：operator 内置权限移除 system:manage——角色管理/系统设置归 admin 专属（越权修复，#2802）
- `admin-api`：应收对账差额文案区分应退/少收——已完成退款订单不再误导为少收（P2-1，#2803）
- `admin-web`：今日/昨日销售额舍入口径统一 HALF_UP（P2-3 看板金额舍入不一致，#2804）

### 小布 C 端功能增强（2026-08-31~09-03，#2684/#2686/#2689/#2692/#2729/#2730/#2731/#2733/#2738/#2741/#2746/#2747/#2753/#2756/#2760/#2801/#2812）

- `mini-app`：小布 C 端全量功能合入主干（xiaobu 验收/深蓝金 UI/语音/wechat 修复，#2689）
- `mini-app`：语音输入——默认按住说话、松开发送，可切键盘模式（UI-007，#2686）；会话列表折叠（UI-008，#2692）；会话管理回归纯单列表（UI-006 修订，#2684）
- `mini-app`：C 端表单化交互——FormCard 组件 + __FORM__ 注入协议（CH-009，#2729）；多轮场景用例 + 手机号脱敏（CH-010~012，#2730）；E2E 多轮场景改「选品→下单」贴近真实路径（#2731）
- `mini-app`：C 端 agent 交互改版参考瑞幸——商品卡去下单/预计到手/规格 + 订单确认自提外送/支付方式（#2733）
- `xiaobu`：快捷入口转人工→查物流、退换货→售后咨询 + 物流查询两端收紧（禁物流号直查，#2738）
- `xiaobu`：微信授权手机号绑定——关联名下商户代录历史订单（#2741）
- `xiaobu`：下单流程价格铁律——单价/金额取商品与算料数据，严禁向顾客索要（#2747）；售后创建闭环 aftersale_create 订单号 404 修复（#2746）
- `xiaobu`：已发货订单售后被误转人工——few-shot/skill 补状态门禁认知（#2756）；售后 skill 误走 human_handoff 修复（#2753）
- `xiaobu`：AI 自动引导转人工——结构化信号判定 + 建议卡片 + 用户确认后转（#2760）
- `mini-app`：新增售后链路 E2E（售后咨询→真实后端 SSE 回复，#2801）；新增转人工链路 E2E（我要转人工→SSE human_handoff→C 端横幅，#2812）

### 商家入驻 AI 甄别与主页（2026-08-30，onboarding）

- `ai-agent-service`：商家入驻 AI 自动甄别 + 主页文案重设计（米高×小布）；甄别提示词明确「营业执照/选填字段缺失不构成驳回理由」；测试改用 settings.SERVICE_TOKEN 修复 CI 401
- `admin-api`：Tenant IdTypeAUTO 兼容 PG18 ALWAYS identity（#2658）
- `docs/deployment`：归档商家入驻 AI 自动甄别云验收脚本（20/20 场景可复用，#2660/#2667）

### 生产安全加固（2026-08-30，审计 07 遗留）

- `deploy`：生产安全加固——屏蔽敏感端点/端口绑 loopback/资源限制/readiness（#2662→#2663）
- `admin-api`：审计 07 遗留 P1 修复——登录租户校验/跨租户歧义/会话归属/refresh token 入 HttpOnly cookie（#2668）
- `admin-api`：入驻 IP 限流可被 X-Forwarded-For 伪造绕过修复（#2661→#2664）
- `test(smoke)`：适配审计 07 新契约——refresh token cookie + nginx 屏蔽 health（#2669）；修复 case_ids 注释语法（#2671）

### GitHub 安全基线（2026-08-30，#2659）

- `ci`：workflow 最小权限 + Danger Scan 破坏性变更门禁（#2659）
- `ci`：CI 失败报告去重守卫——6 个自动建 issue 的 workflow 加同标题查重（#2744）
- `ci`：冒烟前等待服务就绪，消除滚动重启瞬态 502 误报（greenlet 部署教训，#2701）
- `ci`：恢复 xiaobu H5 视觉回归 job（#2699）；pr-check E2E/admin-web 超时放宽（慢 runner 误报修复，#2811）

### 看板/数据（2026-08-31，#2677/#2768）

- `admin-web`：PD 精简改版——洞察条一句话经营解读 + 客单价卡 + 绿涨红跌语义色 + 修复 23.8 假数据（#2677）
- `ai-agent-service`：dashboard_stats 商品销量排行 action——米宝可答「哪个商品卖得最好」（DA-006，#2768）

### 下单链路修复（2026-08-29，#2611/#2613/#2615/#2607/#2608）

- `admin-api`：订单/商品/工单/跟进状态报错文案中文化（面向企业客户，#2611）
- `ai-agent-service`：下单漏加工费——order prompt 补强加工项数据来源/结构/金额计算（#2613）
- `admin-api`：订单列表含加工项筛选恒返回空——子查询投影补 processing_info（#2615）
- `admin-api`+`frontend`：SKU/颜色 Long id 精度丢失——序列化为字符串防 JS 失真（#2613）
- `ai-agent-service`：agent 回复中的售后工单英文枚举改为中文业务术语（#2607）；order 卡片载荷归一化，修复「订单」空盒子并支持点击跳转订单详情（#2608）
- `ai-agent-service`：补充 enum_labels 模块专属单测（QA Growth Gate G1 要求）

### 人工客服工作台（2026-08-29，POC xiaobu 增强）

- `admin-api`：转人工创建人工会话 + 消息收发 + 用户端查询
- `admin-web`：人工客服工作台页面（会话列表 + 对话 + 发消息）
- `mini-app`：用户端转人工支持——状态提示 + 人工会话消息 + 发消息分流
- `ai-agent-service`：customer_order 挂载 human_handoff（下单后转人工真正生效）

### H5 入口与部署（2026-08-29~30）

- `deploy`：app.migaozn.com C 端 H5 入口（nginx + compose）；mini-app 添加 H5 构建依赖（plugin-platform-h5/router/taro-h5，#2604）
- `deploy`：frontend 探测域名改 merchant.migaozn.com（#2672）

### 主模型切换（2026-09-01，#2678）

- `ai-agent-service`：主推理模型 deepseek-v4-pro → deepseek-v4-flash（成本/延迟优化）

### 依赖与工程（2026-08-30~09-02）

- `mini-app`：Taro 全家桶 3.6.40 → 4.2.1 整组升级工程级迁移（#2704）
- `ci`：actions/checkout 4→7、setup-java 4→6、setup-python 5→7、setup-node 4→7、upload-artifact 4→7、docker/setup-buildx-action 3→4、actions/github-script 7→9、gitleaks-action 2→3
- `admin-web`：axios 1.15→1.20、sonner 1.7.4→2.0.8、tailwind-merge、msw 2.13.6→2.15.0、@testing-library/*、@types/node 升级
- `ai-agent-service`：pydantic、pydantic-settings、uvicorn、greenlet、pyjwt、pytest-mock、python-dotenv 升级
- `admin-api`：jacoco、lombok、poi-ooxml、dysmsapi20170525、jjwt、mapstruct、maven-enforcer-plugin 升级
- `tests`：@playwright/test 1.60.0→1.62.1
- `gitignore`：Taro 本地私有配置 project.private.config.json（防真实 AppID 入库，#2698）
- `chore`：去除 junshi/军师/二郎神 内部代号命名（#2648）；仓库精简——删除 AI 标识/历史遗留/一次性产物（#2646→#2647）
- `scripts`：新增 git worktree 多分支工作区脚本 + 分支治理规范（#2725）；dev-flow 同步 Agent Eval 重试命令 + 部署验证端点修正（#2702）；Troubleshooting 增补 CI/本地环境差异（Taro dotenv 白屏 + Playwright 平台基线，#2700）

### 安全加固（POC 显式化）

- `admin-api`：SmsService 增加 `@PostConstruct` 启动警告——`sms.bypass-code` 非空时打印醒目 WARN（POC 模式万能验证码显式化，技术债 Issue #2616）
- `admin-api`：`verifyCode` 命中万能验证码的日志由 INFO 升级为 WARN（含 Issue #2616 指引）
- `ai-agent-service`：`.env.example` 的 `DEBUG` 默认值改为 `false`，并注释说明生产禁用与本地开发用法
- `ai-agent-service`：`[tool-exec]` 错误日志的 `tool_args` 经 `LogSanitizer.sanitize_tree` 递归脱敏（手机号/邮箱/敏感 key 打码）
- `ai-agent-service`：记忆提取增加 PII 过滤（`_filter_pii`）——手机号/地址/邮箱类记忆不落库，提取提示词禁止 PII

### 发布体系（2026-08-30）

- 镜像 tag 从时间戳改为 **git SHA 前 7 位**（不可变、可追溯）；`latest` 仅测试环境
- 新增 `release.yml`：手动触发打 semver tag（patch/minor/major）+ GitHub Release notes；tag 触发版本镜像构建（vX.Y.Z）
- deploy-* workflow 双模式：push/tag 自动部署**测试环境**（当前 SWAS）；workflow_dispatch 支持填 `image_tag` **回滚/指定版本**（跳过构建）
- 新增 `deploy-prod.yml`：未来**生产受控发布**入口（GitHub Environment 审批 + 指定版本），当前未启用
- 新增 `docs/deployment/production-deployment.md`（生产部署方案设计）与 `docs/deployment/rollback.md`（回滚 Runbook）
- deploy-frontend 补 concurrency group + 部署后域名 200 探测
- swas-deploy-ci.sh 支持传 IMAGE_TAG

### 开源治理

- 新增 `SECURITY.md`（安全漏洞报告政策与响应承诺）
- 新增 `CODE_OF_CONDUCT.md`（贡献者公约 2.1）
- 新增 `CHANGELOG.md`（本文件）
- 新增 `.github/dependabot.yml`（Maven / pip / npm / GitHub Actions 依赖自动更新）
- 新增 `.github/FUNDING.yml`（赞助入口占位）
- 新增 `CONTRIBUTING.md`（外部贡献者指南：Issue 先行 / 分支 / TDD / PR 门禁）
- `README.md` 全面修订：修正文档矛盾（工具 31、Controller 27、Service 23、Entity/Mapper 44、Boot 3.3.9、表 41 等）、RAG 按决策 D1 标注暂不开放、新增 CI/License badges
- `pr-check` 新增 Secret Scan (gitleaks) job
