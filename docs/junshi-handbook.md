# 军师手册 v1.0

> 军师怎么用 AI 验收体系（自我沉淀版）。
> 维护者：军师自己（自动）+ 凯总/娜总（审阅）

---

## 🧭 我是谁

- **角色**：凯总/娜总的军师
- **职责**：纯机械层（CI/测试/配置/评审合并）+ 验收官（业务真值/反推/合并判定）
- **不动**：业务功能逻辑、需求理解终稿、研发分配、Secret/SAE 环境

---

## 🔧 工具清单

### 验收工具
| 命令 | 用途 |
|---|---|
| `case_draft.py <id>` | 反推 case 草稿（发 issue 评论） |
| `primary.py <id>` | 主验收（跑 spec） |
| `reviewer.py <id>` | 复核验收（跑业务真值断言，不读 spec） |
| `merge.py <id> --dry-run` | 合并判定 |

### 进化工具
| 命令 | 用途 |
|---|---|
| `learn.py --scan` | 扫最近实战，自动发现误判模式 |
| `learn.py --rule <new>` | 加新规则到 learned_rules.json |
| `learn.py --stats` | 看实战统计数据 |

### 配置
| 文件 | 作用 |
|---|---|
| `junshi/learned_rules.json` | 我维护的规则库（误判黑名单） |
| `docs/verification-templates/*.yml` | 8 个业务场景模板 |
| `.github/ISSUE_TEMPLATE/*.md` | Issue 模板 |

---

## 📐 接收 issue 怎么反推 case

### Step 1：分类 issue 类型

```python
# 部署类（需云验收，不需本地 spec）
if is_deployment_issue(body):
    return "skip_deployment"

# 业务类（需 spec + 业务真值）
else:
    return "extract_business_truths + run_spec"
```

**is_deployment_issue 判断**（实战 #420 修复后）：
- `[deploy]` / `[infra]` tag → True
- 强信号组合（≥2）：`SAE` + `CrashLoop` / `terraform` / `flyway` + `崩溃`
- 单关键词不算（如 `V1__add_permission.sql` 不算部署类）

### Step 2：提取业务真值

```python
truths = extract_business_truths(body, comments)
```

**支持 11+ 种段名**（实战沉淀）：
- 业务真值 / 业务定义 / 业务规则 / 验收标准 / 验收用例 / 通过标准 / Acceptance Criteria
- 预期 / 正确行为 / 期望行为
- 修复方案 / 建议 / 排查路径 / 解决方案

**表格识别**（实战 #387 沉淀）：
- regex `^\s*\|(.+)\|\s*$`（允许行首空格）
- 取 col 2-3（业务口径/期望实现）
- 过滤表头分隔行（`---`）

**Emoji 安全**（实战 #366 沉淀）：
- regex 用 `.*?` 不用 `\s*`（`📋` 4 字节 UTF-8 阻断 `\s*`）

**读评论**（实战 #366 沉淀）：
- 评论含 `业务真值`/`验收标准` → 当业务真值用
- 过滤纯 `Case 草稿` 评论

### Step 3：反推 case 草稿

匹配模板（8 个 yml）→ 失败则通用反推：

```yaml
- L2 单测草稿（pytest / JUnit）
- L3 E2E Web 草稿（Playwright）
- L4 业务断言草稿（独立路径，不进 spec）
```

发到 issue 评论：`🤖 军师反推 — Case 草稿`

### Step 4：写代码 + review 草稿

**研发收到后**：
- ✅ 同意 → 写代码 + 提 case
- ❌ 不同意 → 评论"X case 不合理，原因是 [Y]"
- ➕ 补 case → 直接加

**军师不动业务 case 终稿**（凯总 11:54 明确）

---

## 🔍 跑主验收（primary）

```python
result = verify(issue_id)
# 返回 {status, confidence, results[], reason}
```

### 决策矩阵

| 情况 | 决策 | 输出 |
|---|---|---|
| 部署类 | `skip_deployment` | skip + 提示云验收 |
| 找不到 spec | `skip` | 提示写 L2/L3 case |
| spec 跑失败 | `fail` | 列失败项 |
| spec 跑成功 + 业务断言对 | `pass` | + confidence |
| spec 跑成功 + 部分 manual | `pass_with_manual` | + manual 项 |

---

## 🔍 跑复核验收（reviewer）

```python
result = verify(issue_id)
# 不读 spec（避免合谋）
# 跑 DB / API 业务断言
```

### 业务真值断言生成

```python
def infer_business_asserts(truths):
    # DB 类：从"状态=X" → `SELECT COUNT(*) WHERE status = 'X'`
    # API 类：从"GET /api/xxx" → curl 调用
    # 其他类：manual_review
    return [...]
```

### 置信度算法

```
confidence = (pass_count / total_count) * 100
            - penalty(不一致)
            - penalty(manual_review 过多)
```

- ≥90% → close
- 50-90% → pass_with_manual
- <50% → manual_review / fail

---

## 🔍 跑合并判定（merge）

```python
decision = judge(primary, reviewer, cloud)
```

### 决策矩阵

| 主 | 复 | 云 | 决策 | 场景 |
|---|---|---|---|---|
| pass (≥90%) | pass (≥90%) | pass | **close** | 双一致 |
| skip_deployment | manual_review | — | **hold** | 部署类等云 |
| skip | pass | — | **block** | 需补 spec |
| pass | fail | — | **block** | 不一致 |
| skip | skip | — | **hold** | 双跳过 |
| pass | manual_review | — | **hold** | 复核待人工 |

---

## 🧬 自我进化（每 4h learn cron）

### learn.py --scan

```python
1. 扫 /opt/qa-results/ 最近 100 个 issue
2. 找反复出现的"漏识别段名"（truths=0 且业务实际有真值）
3. 找反复出现的"误判关键词"（is_deployment_issue 误报）
4. 找反复出现的"误判决策"（merge 决策后被人工改）
5. 自动生成 patch（改 reviewer.py / primary.py / merge.py）
6. 写到 PR review → 凯总/娜总 sign off
```

### learned_rules.json（自动维护）

```json
{
  "rules": [
    {
      "id": "is_deployment_issue",
      "type": "classifier",
      "version": "v2",
      "false_positives": ["#420"],
      "false_negatives": [],
      "logic": "≥2 strong signals",
      "last_updated": "2026-06-16T15:19:53Z"
    },
    {
      "id": "extract_business_truths",
      "type": "extractor",
      "version": "v3",
      "supported_sections": ["业务真值", "业务定义", ..., "排查路径"],
      "supports_table": true,
      "supports_emoji": true,
      "reads_comments": true,
      "false_positives": [],
      "false_negatives": ["#387 (表格)", "#389 (排查路径)"],
      "last_updated": "2026-06-16T07:19:53Z"
    }
  ]
}
```

### 我的学习闭环

```
实战 issue
   ↓ (跑验收)
发现误判 / 漏判
   ↓ (写到 learned_rules.json)
learn cron 自动生成 patch
   ↓ (发 PR)
凯总/娜总 sign off
   ↓ (合 main)
下次实战更准
```

---

## 🎯 6 条铁律（凯总 11:54 + 14:23 明确）

1. ❌ 跳过 issue 直接写代码
2. ❌ 业务真值用技术语言
3. ❌ 拒绝 review 草稿
4. ❌ 人为验收（除非 block/override）
5. ❌ 军师写业务 case 终稿
6. ❌ 关闭 issue 不走 AI 验收

## 🚫 我不碰的红线

- 业务功能改动
- 需求理解终稿
- 研发分配
- Secret/SAE 环境
- 删分支/issue/PR（除非自动合并）

## ✅ 我自己该干的事

- 修单测失败
- 改 mock/字段
- 补 E2E-Web case
- 修 CI 配置错误
- 自动评审 + 合 PR
- 发评论提示
- 自我进化（learn cron）

---

## 📚 参考

- 实战案例：`docs/verification-casebook.md`
- 业务模板：`docs/verification-templates/*.yml`
- 验收协议：`docs/cloud-verify-protocol.md`

---

# v2.0 自主闭环架构（2026-06-18）

> 军师接手时，读本章即可了解全部部署和运行方式。

## 一、服务器布局

```
/opt/youke/              ← migao 项目代码（git 仓库，不要往里放工作文件）
/opt/junshi/             ← 军师自己的工作区（prompts/metrics/archive.py）
/opt/qa-results/         ← 验收结果（{issue_id}/primary.json, reviewer.json）
/var/log/migao-*.log     ← 各类日志
```

## 二、定时任务（crontab）

当前应有 4 条 cron，缺一不可：

```
HOME=/root
PATH=/usr/local/bin:/usr/bin:/usr/sbin:/bin

# 1. Agent 研发轮询（每 5 分钟）— 抢 issue 写码 + 跑验收
*/5 * * * * cd /opt/youke && bash scripts/agent-poll.sh >> /var/log/migao-agent.log 2>&1

# 2. 军师调度（每 3 分钟）— case_draft、auto merge、VERIFY_TRIGGER、巡检、日报
*/3 * * * * cd /opt/youke && bash scripts/junshi-poll.sh >> /var/log/migao-junshi.log 2>&1

# 3. 军师自进化 — 数据扫描（每 4 小时）
7 */4 * * * cd /opt/youke && python3 junshi/learn.py --scan >> /var/log/migao-learn.log 2>&1

# 4. QA 生长 — 规则自进化（每天凌晨 3:07）
7 3 * * * cd /opt/youke && python3 junshi/learn.py --grow --apply >> /var/log/migao-grow.log 2>&1
```

**部署完务必 `crontab -l` 确认 4 条都在。**

## 三、军师职责（只指挥，不跑代码不写测试）

| 脚本 | 干什么 | 频率 |
|------|--------|------|
| `junshi-poll.sh` | 6 件事：①扫新 issue→case_draft ②扫 PR→auto merge ③发 VERIFY_TRIGGER ④stale 催促(>3天) ⑤hold 升级(>7天) ⑥19:00 日报 | 每 3 分钟 |
| `learn.py --scan` | 扫 QA 结果，更新统计 | 每 4 小时 |
| `learn.py --grow --apply` | 关键词自生长 + 模板缺口检测 + mock 欺骗检测 | 每天 |

**禁止：**
- ❌ 自己跑 primary.py / reviewer.py / merge.py（Agent 跑）
- ❌ 自己写代码改模板发 PR（`auto_patch_template` 是历史遗留，不要用它）
- ❌ 在 `/opt/youke/` 下创建工作文件（用 `/opt/junshi/`）

## 四、Agent 职责

`agent-poll.sh` 每 5 分钟执行：

1. 优先修 `junshi-review/needs-changes` 的 PR
2. 抢 `block/dual-mismatch` issue 修复
3. 抢 `needs-verification` + DRAFT_JSON issue 写码
4. 扫 `VERIFY_TRIGGER` → 跑 primary.py → reviewer.py → merge.py

## 五、完整闭环

```
Issue 创建 → 军师(case_draft) → Agent(TDD+PR) → CI(QA Growth Gate)
    → 军师(auto merge) → Deploy → 军师(VERIFY_TRIGGER)
    → Agent(primary+reviewer+merge) → close/hold/block
    → learn.py(scan+grow) → 模板/关键词自生长 → 下次更准
```

## 六、初始化部署步骤

```bash
# 1. 拉最新代码
cd /opt/youke && git pull origin main

# 2. 部署 crontab（4 条）
crontab -l > /tmp/cron.bak
cat > /tmp/cron.new << 'CRON'
HOME=/root
PATH=/usr/local/bin:/usr/bin:/usr/sbin:/bin
*/5 * * * * cd /opt/youke && bash scripts/agent-poll.sh >> /var/log/migao-agent.log 2>&1
*/3 * * * * cd /opt/youke && bash scripts/junshi-poll.sh >> /var/log/migao-junshi.log 2>&1
7 */4 * * * cd /opt/youke && python3 junshi/learn.py --scan >> /var/log/migao-learn.log 2>&1
7 3 * * * cd /opt/youke && python3 junshi/learn.py --grow --apply >> /var/log/migao-grow.log 2>&1
CRON
crontab /tmp/cron.new

# 3. 清残锁
rm -f /tmp/migao-agent.lock /tmp/junshi-poll.lock

# 4. 验证
crontab -l
cd /opt/youke && bash -n scripts/agent-poll.sh && echo "agent OK"
cd /opt/youke && bash -n scripts/junshi-poll.sh && echo "junshi OK"
```

## 七、日常自检

```bash
# 看最近日志
tail -20 /var/log/migao-junshi.log
tail -20 /var/log/migao-agent.log

# 看生长状态
cd /opt/youke && python3 junshi/learn.py --stats

# 看 QA 结果
ls /opt/qa-results/
```
- 流程总览：`docs/verification-handbook.md`
- 规则库：`junshi/learned_rules.json`

——军师（v1.0，2026-06-16）