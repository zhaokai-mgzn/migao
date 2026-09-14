# 验收报告：智能每日经营简报 MVP 2026-09-14 被测版本 91e5fa17 + 3d45234e

## 结论
**✅ 通过（无 P0/P1 遗留）**。主验收（S1/S2/S3）+ 独立复核 AI 交叉验证一致通过；
复核 AI 独立发现 5 个 P2，已全部修复并重放验证（PR #3479）。

## 验收矩阵
| 场景 | L1 | L2 | UA | 结果 | 证据引用 |
|---|---|---|---|---|---|
| S1 开关全生命周期（设置页开/关/持久化/熔断） | ✅ | ✅ | ✅ | 通过 | UI 旅程 10/10；开关初始关→点击开（className bg-neutral-300→bg-primary-600）→刷新保持→关闭后首页卡+菜单消失 |
| S2 API 链路（默认关/开启/生成/熔断） | ✅ | — | — | 通过 | config 默认 enabled=false；PUT 开启 200；today generated=true+verifyStatus=failed+content={}；关闭后 generate→BRIEFING_DISABLED |
| S3 复核 AI 留下的数据（DB 落库） | ✅ | — | — | 通过 | daily_briefings 表 1 条（tenant 1 / biz_date 2026-09-14 / failed / generated_at 07:51）；failed 被前端正确显示安全提示 |
| 数据安全红线 1（PII 不进 prompt） | ✅ | — | — | 通过 | DailyBriefingServiceTest 快照 JSON 断言无 phone/手机号/nickname/地址；generator 签名仅 snapshot |
| 数据安全红线 2（RLS 隔离） | ✅ | — | — | 通过 | V44 ENABLE ROW LEVEL SECURITY + tenant_isolation_daily_briefings policy；应用层 TenantLineInnerInterceptor 注入为主（P2-3 措辞已修正） |
| 数据安全红线 3（开关即熔断） | ✅ | — | — | 通过 | generateForTenant 开关关闭返回 null + verify never() LLM 调用；UI 关闭后卡/菜单消失 |
| 数据安全红线 4（校验兜底） | ✅ | — | — | 通过 | verifyAndFilter 5 例（编造 key/value/无引用丢弃、partial、verified）+ LLM 失败落 failed + summary 快照外数字降级（P2-2） |
| 前端体验（商家运营 persona） | — | — | ✅ | 通过 | UA 判定：开关文案双向后果明确、给默认值、安全承诺、空态出口；视觉模型 4/4 |

## 问题清单（复核 AI 独立发现，已全部闭环）
| # | 级别 | 问题 | 证据 | 对应 case | 修复 PR |
|---|---|---|---|---|---|
| P2-1 | P2 | 开关变更未写审计日志（设计 §8.4 要求） | BriefingController 原无 AuditLogService 调用 | DA-008 已补 audit 断言 | #3479：注入 AuditLogService，E2E 验证 audit_logs 落库（update/briefing_config/开关状态） |
| P2-2 | P2 | summary 自由文本数字不经机器校验 | 校验层只对 metrics 引用对账 | DA-009 覆盖层扩展 | #3479：summary 提取数字对账，快照外数字→降级为空（+2 测试） |
| P2-3 | P2 | RLS GUC 无注入点，DA-010 声称「跨租户返回空」无法独立验证 | 全仓库无 SET app.current_tenant_id | DA-010 措辞修正 | #3479：改为「fail-closed 兜底 + 应用层拦截器为主」 |
| P2-4 | P2 | 开启 toast 无条件宣称「已生成」与实际不符 | settings toast 原文 | —（前端行为） | #3479：改为「将尽快生成」+ 以响应回填 |
| P2-5 | P2 | 文案未说明「开启后立即生成一次」 | settings 说明原文 | —（前端文案） | #3479：补充说明 |

## 复核验收抽验（独立 AI 视角，零人工）
| 抽验项 | 证据位置 | 复核结论 | 与主验收一致性 |
|---|---|---|---|
| 开关熔断（a） | DailyBriefingService.java:144-148 + V44:11 + Sidebar.tsx:115 | 通过（L1） | 一致 |
| 数字回填校验（b） | DailyBriefingService.java:324-347,375-408 + generator.py:28-57 | 通过（L1），附 P2-2 | 一致（P2-2 已修） |
| PII 隔离（c） | DailyBriefingService.java:213-297 + generator.py:168 + test:332-351 | 通过（L1） | 一致 |
| 前端 failed/空态安全（d） | BriefingCard.tsx:166-187 + test:98-115 | 通过（L2） | 一致 |
| 开关语义可懂度（e） | settings/page.tsx 文案原文 | 通过（UA，persona=布艺店运营负责人） | 一致 |

## 沉淀记录
| 问题 | 新增/修改 case | case 有效性验证 |
|---|---|---|
| 简报卡空 content 崩溃（开发期 UI 旅程实证） | BriefingCard.test.tsx「content 空对象不崩溃」 | ✅ 修复前 content={} 渲染崩溃（UI 走查实证）→ 修复后 6 例全绿 |
| P2-1 审计缺失 | DA-008 补 audit_logs 断言 | ✅ 修复后 E2E 验证 audit_logs 落库 |
| P2-2 summary 编数字 | DA-009 覆盖 summary 对账 + 2 个单测 | ✅ 修复后测试通过（快照外数字→降级） |
| 功能行为 | DA-008/009/010（开关熔断/数字校验/PII+RLS） | ✅ traces 指向对应测试，CI 全绿 |

## 交付物
- PR #3474（主功能，已合并）+ PR #3479（P2 修复，已合并）
- 设计文档 docs/design/daily-briefing-design.md（v0.2）
- 验收剧本 acceptance/2026-09-14/BRIEF-001/playbook.md
- 生产已部署，冒烟通过（ai-agent healthy / frontend 200 / admin-api 401）
