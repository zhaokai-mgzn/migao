# 军师验收实战案例集

> 5 个 issue 跑通完整 AI 验收流程的实战教科书。
> 维护者：军师（自动汇总实战）+ 凯总/娜总（审阅）

---

## Case 1: #387（数据看板卡片跳转 — 业务真值在表格）

### Issue 类型
红牌 — enhancement（业务规则变更）

### Issue Body 格式
- `## 业务定义` 段（不是 `## 业务真值`）
- 业务真值**在 markdown 表格**里（不是列表）

### 学到的规则
1. **业务真值识别必须支持 11 种段名**：
   `业务真值` / `业务定义` / `业务规则` / `验收标准` / `验收用例` / `通过标准` / `Acceptance Criteria` / `预期` / `正确行为` / `期望行为` / `修复方案` / `建议` / `排查路径` / `解决方案`

2. **表格识别**：regex `^\s*\|(.+)\|\s*$`（允许行首空格），取 col 2-3（业务口径/期望实现）

3. **过滤表头分隔行**（`|---|---|`）：用 `re.match(r"^[-:]+$", cell)` 过滤

### 验收结果
| 指标 | 数值 |
|---|---|
| 业务真值 | 4 |
| 主验收 | skip（无 spec） |
| 复核验收 | pass_with_manual |
| 决策 | **block**（需补 spec） |

### 复现命令
```bash
python3 scripts/dual_verify/case_draft.py 387
# v3.0: verify-agent LLM 自主验收替代
# python3 scripts/dual_verify/reviewer.py 387 --out /opt/qa-results/387/reviewer.json
# python3 scripts/dual_verify/merge.py 387 --dry-run
```

---

## Case 2: #366（Flyway 部署崩溃 — 部署类 issue + 业务真值在评论）

### Issue 类型
部署/基础设施 — bug（CRASH）

### Issue Body 格式
- `## 现象 / 环境 / 配置 / 临时方案 / 排查路径`（Bug 类格式）
- **无业务真值段**

### 学到的规则
1. **识别部署类 issue**：`is_deployment_issue(body)`：
   - `[deploy]` / `[infra]` tag → 强匹配
   - 强信号组合（≥2 命中）→ `SAE`/`CrashLoop`/`启动崩溃`/`terraform`/`flyway`
   - 单关键词不算（避免误判，如 `V1__add_permission.sql` 不算部署类）

2. **读评论**：comment 含 `业务真值`/`验收标准` 关键词 → 当业务真值用
   - 过滤逻辑：跳过纯 `Case 草稿` 评论（含业务真值/验收标准的保留）

3. **emoji 安全**：regex 用 `.*?` 不用 `\s*`（`📋` 是 4 字节 UTF-8）

4. **部署类决策**：`skip_deployment` → `hold` + 等云验收

### 验收结果
| 指标 | 数值 |
|---|---|
| 业务真值 | 0（issue body）→ **19**（从评论反推） |
| 主验收 | `skip_deployment` |
| 复核验收 | manual_review（19 个） |
| 决策 | **hold**（等云验收） |

### 复现命令
```bash
# 触发反推 + 看决策
python3 scripts/dual_verify/case_draft.py 366
# v3.0: verify-agent LLM 自主验收替代
# python3 scripts/dual_verify/reviewer.py 366 --out /opt/qa-results/366/reviewer.json
# python3 scripts/dual_verify/merge.py 366 --dry-run
```

---

## Case 3: #420（.env 不允许提交 — Security 类误判修复）

### Issue 类型
security — bug

### Issue Body 格式
- `## 背景 / 当前规则 / 风险 / 修复方案`
- 含真实文件名（如 `V1__add_permissions_to_users.sql` 触发误判）

### 学到的规则
1. **误判案例**：`V1__` / `V2__` 关键词**单匹配不算部署类**
   - 原版：`V1__` 命中即判定部署类 → #420 误判
   - 修复：≥2 强信号才判定
   - 单测：`test_is_deployment_issue` 改写

2. **Security 类验收**：业务真值是"git tracked .env 是 bug"，无法 DB/API 自动断言 → manual_review

### 验收结果
| 指标 | 数值 |
|---|---|
| 业务真值 | 6 |
| 主验收 | skip（无 spec） |
| 复核验收 | manual_review |
| 决策 | **hold**（等人工复核） |

---

## Case 4: #382（库存字段显示 0 — Bug 类"预期"段）

### Issue 类型
红牌 — bug

### Issue Body 格式
- `## 现象 / 预期 / 排查路径`（标准 Bug 类）
- 业务真值在 `## 预期` 段

### 学到的规则
1. **业务真值段名扩展**：加 `预期` / `正确行为` / `期望行为`

### 验收结果
| 指标 | 数值 |
|---|---|
| 业务真值 | 0 → **34**（修复后） |
| 主验收 | skip |
| 复核验收 | pass_with_manual |
| 决策 | **block** |

---

## Case 5: #389（看板排行"暂无数据" — 排查路径段当业务真值）

### Issue 类型
红牌 — bug

### Issue Body 格式
- `## 现象 / 可能根因 / 排查路径`
- 业务真值在 `## 排查路径` 段

### 学到的规则
1. **业务真值段名再扩展**：加 `排查路径` / `修复方案` / `解决方案` / `建议`

### 验收结果
| 指标 | 数值 |
|---|---|
| 业务真值 | 0 → **71**（修复后） |
| 主验收 | skip |
| 复核验收 | pass_with_manual |
| 决策 | **block** |

---

## 📊 5 个 Case 综合表

| Case | 类型 | 业务真值（修前→修后） | 决策 | 关键 bug |
|---|---|---|---|---|
| #387 | 红牌 enhancement | 0→4 | block | 表格识别 |
| #366 | 部署 bug | 0→19 | hold | 评论补完 + emoji |
| #420 | security | 6 | hold | 部署类误判修复 |
| #382 | 红牌 bug | 0→34 | block | "预期"段 |
| #389 | 红牌 bug | 0→71 | block | "排查路径"段 |

**累计修 10+ 个 bug**（PR #458/#459/#460）

## 🎓 5 个核心规律

1. **业务真值永远在 body 某段里**，但段名千变万化 → 用宽泛 regex
2. **issue body 不够，评论补**（军师反推草稿 + 凯总/娜总补完）
3. **表格行 = 业务真值**，抓 col 2-3（业务口径）
4. **emoji 阻断 regex**：用 `.*?` 不用 `\s*`
5. **决策多样性**：block/hold/close 三态都对，看 issue 类型

## 🚀 复制案例

任何新 issue 想跑新验收流程：
```bash
# 1. 反推 case
python3 scripts/dual_verify/case_draft.py <id>

# 2. 跑主验收（自动）
# v3.0: verify-agent LLM 自主验收替代
# python3 scripts/dual_verify/primary.py <id>

# 3. 跑复核验收（自动）
python3 scripts/dual_verify/reviewer.py <id>

# 4. 决策（自动）
python3 scripts/dual_verify/merge.py <id> --dry-run

# 5. 看报告
cat /opt/qa-results/<id>/{primary,reviewer}.json
```

——军师（实战总结 2026-06-16）