# 验收剧本 BRIEF-001：智能每日经营简报用户旅程

- 被验收对象：商家后端「智能每日经营简报」MVP（企业开关 / 定时生成 / 四区块简报 / 菜单显隐 / 数据安全）
- 环境：admin-web(:3001) + admin-api(:8080)，本地 dev DB（云 dev），无 ai-agent（LLM 生成走降级路径，验证红线 4）
- 被测版本：`91e5fa17`（PR #3474 合并 commit）
- 执行者：验收 AI（独立视角，不拿开发自测结论）
- 验收时间：2026-09-14

## 场景 S1：企业开关全生命周期（商家运营 persona）
用户动作序列：
1. 打开设置页 → 看到「智能每日经营简报」区块（开关 + 生成时刻）
2. 确认开关初始为关闭（灰色）
3. 点击开关开启 → 开关变绿
4. 修改生成时刻为 07:30
5. 刷新页面 → 确认开关状态保持开启、时刻保持 07:30（持久化）
6. 回到首页 → 看到简报卡（今日简报尚未生成 或 未通过数字校验 状态——因为无 ai-agent）
7. 点击侧边栏「每日简报」→ 进入 /briefing 页
8. 回到设置页关闭开关 → 刷新首页 → 简报卡消失 + 侧边栏菜单消失

验收点：
- [ ] L1 设置页存在「智能每日经营简报」区块（DOM 断言）
- [ ] L1 开关初始关闭（className 无 bg-primary-600）
- [ ] L1 点击后开关变绿（className 含 bg-primary-600）
- [ ] L1 刷新后开关状态持久化（仍开启）
- [ ] L1 生成时刻持久化（07:30）
- [ ] L1 首页简报卡在开关开启时渲染（含「每日经营简报」标题）
- [ ] L1 /briefing 页可访问且渲染（h1「每日经营简报」）
- [ ] L1 关闭开关后：首页简报卡消失 + 侧边栏菜单消失（count=0）
- [ ] L2 简报卡状态合理（failed 降级 → 显示安全提示而非编造数据）
- [ ] UA 商家运营视角：设置页开关文案/说明清晰可懂，能理解开/关后果

## 场景 S2：API 链路与数据安全红线（L1 机器断言）
用户动作序列（API 直连，带 JWT）：
1. GET /api/admin/briefing/config → enabled=false（默认关）
2. PUT /api/admin/briefing/config {enabled:true, generateTime:"07:30"} → 200 + enabled=true
3. GET /api/admin/briefing/today → generated=true + verifyStatus（failed/verified）+ content
4. PUT /api/admin/briefing/config {enabled:false} → 关闭
5. GET /api/admin/briefing/today → generated（保持上次生成）——验证历史保留语义
6. POST /api/admin/briefing/generate → generated=false + reason=BRIEFING_DISABLED（熔断）

验收点：
- [ ] L1 默认关闭（enabled=false）
- [ ] L1 开关更新成功（PUT 200 + 返回新配置）
- [ ] L1 无 ai-agent 时生成 → verifyStatus=failed + content={}（红线 4：不展示假数据）
- [ ] L1 关闭后手动生成 → BRIEFING_DISABLED（红线 3：熔断）
- [ ] L1 DB 落库：daily_briefings 表有当日记录（tenant_id + biz_date 唯一）

## 场景 S3：复核 AI 留下的数据（协议 §2.2）
- 验收 agent 在 S2 中通过 API 创建的 daily_briefings 记录（failed 状态）
- 以产品视角复核：failed 记录是否被前端正确处理（显示安全提示，不展示空/假数据）
- 复核：开启瞬间立即生成是否真的触发（记录 generated_at 时间戳）
