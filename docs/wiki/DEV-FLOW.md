# MIGAO 开发提效流程（固化版）

> 本文档是 DSH 技能 `migao-dev-flow`（`migao/.agents/skills/migao-dev-flow/SKILL.md`）的仓库同步副本，供团队共享阅读。
> **修改流程规范时，两份文件需同步更新**（DSH 技能是机器本地、不进 git；本文档是版本化副本）。
> 内容源自历史全链路复盘（RETROSPECTIVE，未入库）的 P0/P1 改进，经实战固化。

## 1. 三把工具（开发自查用）

| 工具 | 用途 | 何时用 |
|---|---|---|
| `./verify-all.sh quick/full/gate` | 三模块一键测试 + QA gate 预检 | 每次改动后、提交前 |
| `./contract-check.sh` | 三端契约一致性（字段名/状态枚举/端点） | 并行改动、跨模块改动后 |
| `./check-ui-regression.sh` | UI 回退检测（neutral token vs origin/main） | **提交前必跑** |

运行：`cd <migao 仓库根> && ./verify-all.sh gate`

## 2. 提交流程（防 UI 回退 / 防 CI 返工）

### 2.1 提交前必查（按序）
```bash
# ① UI 回退检测（最重要！防工作区旧 UI 覆盖验收版）
./check-ui-regression.sh

# ② QA gate 预检（本地跑 CI 规则，避免合并前爆 case_ids/缺测）
./verify-all.sh gate

# ③ 契约一致性（跨模块改动后）
./contract-check.sh

# ④ 全量单测（quick 即可，full 提交大 PR 前跑）
./verify-all.sh quick
```

### 2.2 红线（踩过的高频坑，禁止违反）
- **禁止 `git add -A` 盲目提交**：工作区长期积压的未提交改动（尤其旧版 UI）会覆盖 main 上已验收的版本。提交前先 `git status` 检查积压，**逐个确认** UI 文件不是旧版。
- **禁止长期不提交**：避免大 PR。开发应小步提交 + 频繁 `git fetch origin main && git rebase origin/main`。
- **新增/修改测试必须带 `# case_ids: OR-xxx`** 注释头（按域：OR 订单/AS 售后/PR 商品/FN 财务/CU 客户/DA 看板/UI 前端），否则 QA Growth Gate 会 block 合并。
- **测试文件路径**：前端组件测试放 `tests/unit/components/<Name>.test.tsx`（gate 模板不递归子目录，勿放 `orders/` 子目录）。

### 2.3 并行开发（多任务/多 Agent）
- 开工前读 `docs/wiki/CONTRACT-LEDGER.md` 的契约清单（状态枚举/字段名/端点签名）。
- 跨模块改动后跑 `./contract-check.sh` 验证三端一致。
- 交付前跑 `./verify-all.sh gate`（本地预检 CI 规则）。

## 3. CI 关卡（合并前会自动跑）
| 检查 | 作用 | 失败常见原因 |
|---|---|---|
| UI Regression Check | 防 UI token 回退 | 工作区旧 UI 被提交 |
| QA Growth Gate | case_ids/测试覆盖/弱断言 | 测试忘带 case_ids、测试放错目录 |
| Case Contract | 用例引用完整性 | 改了 case yml 未重渲染 |
| Agent Eval (smoke) | 米宝真实 LLM 行为 | 偶发波动（已自动重试，无需干预） |
| admin-api/web/ai-agent 单测 | 三模块测试 | 并行改动契约不一致 |

## 4. 部署
- 合并到 main 自动触发 3 个部署（admin-api/ai-agent/frontend）+ post-deploy 冒烟。
- 部署后验证：`curl api.migaozn.com/actuator/health`、`merchant.migaozn.com/login` 200。
- 生产登录：13800138000 / 万能码 123456（短信网关仍 bypass，上线前需接入）。

## 5. 相关文档
- `docs/wiki/CONTRACT-LEDGER.md` — 并行开发契约清单
- 历史复盘文档（未入库）— 全链路复盘（本规范来源，已固化进本页与 DSH 技能）
- `verify-all.sh` / `contract-check.sh` / `check-ui-regression.sh` — 三把工具
