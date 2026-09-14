# 冷环境复跑 + 失败关闭红证（共用登录步骤）— 2026-09-14

- **被测代码**：`frontend/mini-app/e2e/lib/login.js` + `e2e/run.js`（本 follow-up，PR #3720）
- **被测源码 SHA**：`b53510f5`（origin/main，本分支基点）+ 本 PR 的 e2e 改动（只在 `e2e/**`，不含产品源码）
- **被测构建**：`dist/app.js` 内容指纹 `fc36841d9431…`（`dist/.build-stamp.json` 构建于 2026-09-14T13:05:58.349Z）
- **环境**：微信开发者工具模拟器 + `https://app.migaozn.com`（云端测试环境）
- **说明**：e2e 在主工作区跑（必须驱动真实 `dist/`），源码改动走 worktree + PR

---

## A. 冷环境复跑（清空 storage → 从零建立登录态）：**通过**

命令（仓库入口，无需手工敲 wx 调用）：

```bash
cd frontend/mini-app && E2E_COLD_LOGIN=1 npm run test:e2e
```

关键证据（`run-logs/cold-run1-clear-storage.txt`）：

```
✅ 构建新鲜度检查通过[content-hash]：内容指纹 fc36841d9431…（dist/.build-stamp.json 构建于 2026-09-14T13:05:58.349Z）
✅ 已连接模拟器
[harness] E2E_COLD_LOGIN=1 → 先清空模拟器 storage（去掉环境残留登录态），从零建立
[harness] 已注入登录态 → 重启模拟器会话，让 App 冷启动读取注入态…
[harness] 登录态：已登录（本 harness 经短信登录注入，…，期望 botName=光头强 / tenantName=词元通达）
```

⇒ **「环境残留绿」被消除**：storage 里的登录态是**本轮从零注入**的，报告头也写明了来源与期望身份。
依赖登录态的断言在同一轮全部通过（**证明租户数据来自注入的会话，不是残留**）：

```
✅ 导航栏客服名已渲染（botName 非空） — name=光头强
✅ 导航栏副标（租户名·智能购物助手） — text=词元通达 · 智能购物助手
✅ 导航名与空态问候语同源（同一 botName） — nav=光头强 empty=你好，我是光头强
✅ S5：订单卡片手机号脱敏 — 脱敏格式匹配（139****9000）
```

结果：**37 PASS / 1 FAIL**。唯一失败项与登录无关，归因见 §B。

> 注：`e2e/report.md` 是**单槽**产物（每次运行覆盖；前置失败时按设计删除，见 §C）。
> cold-run1 的 report.md 被随后的 cold-run2（前置失败）按设计清掉 —— 故本轮证据以**完整控制台日志**
> （`run-logs/cold-run1-clear-storage.txt`，含每条断言详情与稳定帧日志）为准。

## A′. 冷环境复跑（终局）：**38/38 PASS（EXIT=0）**

环境恢复后（admin-api 502 于 21:46 恢复）重跑同一命令：

```
[harness] E2E_COLD_LOGIN=1 → 先清空模拟器 storage（去掉环境残留登录态），从零建立
[harness] 已注入登录态 → 重启模拟器会话，让 App 冷启动读取注入态…
[harness] 登录态：已登录（本 harness 经短信登录注入，已登录）
✅ 导航名与空态问候语同源（同一 botName） — nav=光头强 empty=你好，我是光头强
✅ 键盘输入消息上屏（新气泡+新内容） — 你好，有什么热销的窗帘推荐？21:53
✅ AI 回复第二条（SSE 流式，新内容） — 🤖 AI 助手亲，为您找到几款在售的窗帘，先推荐这几款热门的~…(len=271)
✅ S5：订单卡片手机号脱敏 — 脱敏格式匹配
✅ PASS: 38 项 / ❌ FAIL: 0 项   EXIT=0
```

产物：`run-logs/cold-run4-COLD-GREEN.txt`、`e2e-report-cold-run4-green.md`、`screenshots-cold-run4/`。

## B. 归因链：唯一失败项 = **环境 502**（且它顺带抓出了我上一包断言的一个真缺陷）

cold-run1 失败步骤：

```
❌ AI 回复第二条（SSE 流式，新气泡） — 2 条 assistant 气泡，120s 内未新增
```

归因实验（`/tmp/e2e-probe4.js`，独立探针，同一模拟器 + 真实后端）：

```
登录态: ok=true source=storage
typeAndSend: ok=true idleWait=3ms
发送后起点 assistant 气泡数=0
+ 11s | assistant=1(起点0) 流式中=false | 末条AI(len=31)="🤖 AI 助手抱歉，发生错误: 请求失败: 502"
        | ⚠️错误横幅="请求失败: 502"
✅ 新回复出现于 +11s
```

⇒ 回复**11s 就回来了**，内容是**错误提示 `请求失败: 502`**，页面同时出现错误横幅。**不是 LLM 慢、不是超时不够**。

独立佐证（直接打网关，与模拟器无关）：

```
$ curl -X POST https://app.migaozn.com/api/auth/sms/login -d '{"phone":"13800138000","code":"123456"}'
attempt1: 502 (0.046s) / attempt2: 502 (0.052s) / attempt3: 502 (0.042s)
→ nginx/1.31.3 直接回 502 Bad Gateway（后端不可用）
```

**结论**：`app.migaozn.com` 的 admin-api 在 2026-09-14 21:40~21:46 期间不可用（nginx 502）；
cold-run1 的那 1 项失败与 `login.js` 无关。**未通过调大超时/放宽断言来"修绿"**（任务要求：环境问题如实标注）。

### B′. 顺带抓出的**真缺陷**：上一包（PR #3716）那条「气泡数量判定」断言**本身是假红发生器**

你（协调者）要求重放这条「已改未重放」的断言 —— 正是它把问题抓出来的。三次冷跑的证据链：

| 轮次 | 输出 | 说明 |
|---|---|---|
| cold-run1 | `❌ AI 回复第二条 — 2 条 assistant 气泡，120s 内未新增` | 当时归因不明（环境 502 期间） |
| cold-run3（诊断加强后） | `❌ … 2→2 条 assistant 气泡，120s 内未出现新回复；流式中=false；末条AI气泡="🤖 AI 助手亲，为您挑了几款店里比较受欢迎的窗帘～…"(len=324)；错误横幅=无` | **回复到了**（末条 AI 就是本次问题的答复），但**气泡数没涨** |
| cold-run4（修正判据后） | `✅ AI 回复第二条（SSE 流式，新内容） — 🤖 AI 助手亲，为您找到几款在售的窗帘…(len=271)` | 38/38 |

**根因**：小程序的助手气泡在**流式一开始就被创建**（`TypingIndicator` 依赖它显示）。把 `prevAiCount`
快照取在「用户气泡上屏之后」，此刻新助手气泡**可能已经建好** ⇒ 数量永不增加 ⇒ **假红**。
而原写法（`aiReply2 !== prevAiText`）假红是因为 **`prevAiText` 取在发送之后** —— 快照到的「旧文本」就是新回复本身。

⇒ 两种写法**错在同一件事：基线快照晚于被测事件**。唯一稳的判据 = **发送前**取基线，
之后等「非空且 != 基线」（`e2e/lib/harness.js` `waitForAssistantReply()`，注释里保留两种踩坑写法防退回）。

**可迁移形态（建议收进 `migao-acceptance` 假绿/假红清单）**：*基线快照晚于被测事件* ——
同一断言可以既用「比较文本」又用「比较数量」的方式假红；判据必须锚在**动作发生之前**的状态上。

## C. run 级 `LOGIN_MISSING` 失败关闭红证：**两半都成立（两组证据）**

判据三条：① exit code = 1 ② 输出含 `LOGIN_MISSING` ③ `e2e/report.md` **不存在**。

### C-1 人工构造（API base 指向不可达地址）

```bash
cd frontend/mini-app && rm -f e2e/report.md
E2E_COLD_LOGIN=1 E2E_LOGIN_API_BASE=http://127.0.0.1:1 npm run test:e2e
```
```
[harness] E2E_COLD_LOGIN=1 → 先清空模拟器 storage（去掉环境残留登录态），从零建立
⛔ LOGIN_MISSING（e2e 已中止，未跑任何场景）：
   建立登录态失败（短信登录 http://127.0.0.1:1）：fetch failed
   ⇒ 无登录态时断言依赖的租户数据（botName/租户副标/订单脱敏）会缺失或降级，那种「绿」是环境残留给的，不是代码给的 —— 故直接失败，不产出不可复现的证据。
=== EXIT=1 ===
跑后 report.md: 不存在 ✓
```

### C-2 **真实环境故障**触发（比人工构造更有说服力）

```bash
cd frontend/mini-app && rm -f e2e/report.md
E2E_COLD_LOGIN=1 npm run test:e2e      # 此时云端 admin-api 恰好 502
```
```
⛔ LOGIN_MISSING（e2e 已中止，未跑任何场景）：
   建立登录态失败（短信登录 https://app.migaozn.com）：HTTP 502：<html>…502 Bad Gateway…nginx/1.31.3…</html>
=== EXIT=1 ===
跑后 report.md: 不存在 ✓
```

⇒ 三判据（exit 1 / `LOGIN_MISSING` / 无报告）在**人工**与**真实**两种触发下均成立。
`run-logs/cold-run2-LOGIN_MISSING-502.txt` 为原始输出。

## D. 「前置失败必须连陈旧报告一起失效」的加固（本轮新增）

`run.js` 在任何前置失败（陈旧构建 / `LOGIN_MISSING`）时：打印原因 → **删除 `e2e/report.md`** → exit 1。
理由：只做到"不产出**新**报告"不够 —— 目录里**上一轮的旧报告**同样会被下游当成本轮结论
（"陈旧产物被当结论"的假绿形态）。C-1/C-2 两次都验证了「跑后 `report.md` 不存在」。

## E. 未闭环项（如实登记，不谎报）

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| 1 | 「AI 回复第二条」断言 | ✅ **已闭环** | 判据已从「发送后取基线的文本比对 / 气泡计数」改为「**发送前**基线 → 等非空且 != 基线」；红线（不恒绿）与绿线（真实回复 len=271 判过）双向都有证据（§A′ / §B′）。 |
| 2 | 「顾客本人数据隔离」类断言 | ❌ 不由本会话背书 | 短信登录 `identityType=sms`（非微信顾客身份），见 PR #3720 body「能复现/不能复现」边界。属 #3696 的另一半。 |
| 3 | 输入条 `__row` 三者同行 / placeholder 断言 | ⏸ 不做 | 另一工作包的输入条布局仍在改（且将再改一轮），现在加必红；待其最终 class/testID/placeholder 清单。 |
