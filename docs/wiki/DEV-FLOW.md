# MIGAO 开发提效流程（固化版）

> 本文档是 DSH 技能 `migao-dev-flow`（`migao/.agents/skills/migao-dev-flow/SKILL.md`）的仓库同步副本，供团队共享阅读。
> **修改流程规范时，两份文件需同步更新**（DSH 技能是机器本地、不进 git；本文档是版本化副本）。
> 当前版本：v1.3（2026-09-04）——新增多会话并发规范（一会话一 worktree + 会话锁 + 端口隔离 + 分支卫生）、CI 队列治理（concurrency/paths 门控/agent-eval 按变更触发省真实 LLM token）、验证分级降本。
> 内容源自历史全链路复盘（RETROSPECTIVE，未入库）的 P0/P1 改进，经实战固化。

## 1. 三把工具（开发自查用）

| 工具 | 用途 | 何时用 |
|---|---|---|
| `./verify-all.sh quick/full/gate` | 三模块一键测试 + QA gate 预检 | 每次改动后、提交前 |
| `./contract-check.sh` | 三端契约一致性（字段名/状态枚举/端点） | 并行改动、跨模块改动后 |
| `./check-ui-regression.sh` | UI 回退检测（neutral token vs origin/main） | **提交前必跑** |

运行（在 migao 仓库根目录）：`./verify-all.sh gate`

## 2. 提交流程（防 UI 回退 / 防 CI 返工）

### 2.1 提交前必查（按序）— 验证分级（2026-09-04 固化，省本地重复计算）
```bash
# 每次改动后：./verify-all.sh quick（~3-5 分钟）即可覆盖常规回归
# 提交前必查（按序）：
# ① UI 回退检测（最重要！防工作区旧 UI 覆盖验收版）
./check-ui-regression.sh

# ② QA gate 预检（本地跑 CI 规则，避免合并前爆 case_ids/缺测）
./verify-all.sh gate

# ③ 契约一致性（跨模块改动后）
./contract-check.sh

# ④ 全量单测（quick 即可，full 提交大 PR 前跑）
./verify-all.sh quick

# 合并前：以 CI 结果为准，不本地重复跑 gate —— CI 已排队跑过一遍，
# 本地再跑一遍 gate 是纯浪费（token+时间）。本地跑 gate 只在提交前的瞬间用。
```

### 2.2 红线（踩过的高频坑，禁止违反）
- **禁止 `git add -A` 盲目提交**：工作区长期积压的未提交改动（尤其旧版 UI）会覆盖 main 上已验收的版本。提交前先 `git status` 检查积压，**逐个确认** UI 文件不是旧版。
- **禁止长期不提交**：避免 142 个文件的大 PR。开发应小步提交 + 频繁 `git fetch origin main && git rebase origin/main`。
- **禁止分支滞留 + 无记录切换分支**（2026-09-01 实战教训：40+ 本地分支积压，切换旧分支 → 工作区被旧代码覆盖 + 未提交改动静默携带 → 「切换分支后功能退化」）：
  1. 分支开即关联 Issue，验证完即 PR，CI 绿即合并，**分支存活 < 1-2 天**；
  2. 切换分支前 `git status` 必须干净（有改动先 commit/stash）；
  3. 本地验证前先 `git fetch origin main && git rebase origin/main`，**验证必须基于最新主线**；
  4. 多分支并行验证用 `./scripts/dev-worktree.sh add <branch>`（独立工作区，切换零污染），**禁止反复 checkout 切分支**；
  5. 定期清理：`git branch --merged origin/main` 全删；`git cherry origin/main <branch>` 全 `-` 表示内容已落地可删；无独有提交的分支直接删。
- **新增/修改测试必须带 `# case_ids: OR-xxx`** 注释头（按域：OR 订单/AS 售后/PR 商品/FN 财务/CU 客户/DA 看板/UI 前端），否则 QA Growth Gate 会 block 合并。
- **测试文件路径**：前端组件测试放 `tests/unit/components/<Name>.test.tsx`（gate 模板不递归子目录，勿放 `orders/` 子目录）。

### 2.3 多会话并发规范（v1.3 新增，2026-09-04 实战固化：多 DSH 会话并行踩脚治理）

多会话并发（多 Agent / 多分支同时开发）时的铁律：**一个会话一个独立工作区，会话之间零共享写路径**。

1. **会话必须建在独立 worktree**：`./scripts/dev-worktree.sh add <branch>`（默认 `../migao-wt/<分支>`）。禁止多会话共用一个工作目录——同时改文件互相覆盖、`git add` 互带对方文件、同时跑 verify 抢资源。
2. **会话锁**：`dev-worktree.sh add` 自动登记 `.sessions/<branch>.lock`（含 PID+时间戳）；同一分支已有活跃锁时**禁止**重复建工作区/推分支。提交/推送前先 `./scripts/dev-worktree.sh list` 确认锁状态。
3. **端口隔离**：本地服务端口用环境变量覆盖（`API_PORT`/`AGENT_PORT`/`WEB_PORT`），会话各自 `.env.local`，杜绝 8080/8001/3001 互抢。
4. **主工作区只读**：主仓库（migao/）只做 `fetch/rebase/merge` 与 PR 管理，**不在主工作区直接改文件**（防止未提交改动静默携带）。
5. **分支卫生**：验证完即 PR，CI 绿即合并，分支存活 < 1-2 天；定期 `git branch --merged origin/main` 全删 + 清理 `origin gone` 的本地分支。
6. **开工前读契约**：`docs/wiki/CONTRACT-LEDGER.md`（状态枚举/字段名/端点签名）；跨模块改动后跑 `./contract-check.sh`。

## 3. CI 关卡（合并前会自动跑）
| 检查 | 作用 | 失败常见原因 |
|---|---|---|
| UI Regression Check | 防 UI token 回退 | 工作区旧 UI 被提交 |
| QA Growth Gate | case_ids/测试覆盖/弱断言 | 测试忘带 case_ids、测试放错目录 |
| Case Contract | 用例引用完整性 | 改了 case yml 未重渲染 |
| Agent Eval (smoke) | 米宝真实 LLM 行为 | **偶发 LLM 波动**（JSONDecodeError 等，CI 内部已自动重试 1 次） |
| admin-api/web/ai-agent 单测 | 三模块测试 | 并行改动契约不一致 |

### 3.1 Agent Eval 偶发失败的处理（v1.1 修正）
- CI 内部 `local_runner` 已自动重试 1 次（日志可见「第 1 次失败，重试…」）；**2 次均失败才报 FAILURE**。
- **`gh pr checks <PR> --rerun-failed` 实测不生效**（不会触发重跑），必须用 run 级重跑：
```bash
# 取失败 check 的 run id，对 failed job 重跑（等待 ~5 分钟）
run=$(gh pr checks <PR> --json name,link --jq '.[] | select(.name | contains("Agent Eval")) | .link' | grep -oE 'runs/[0-9]+' | cut -d/ -f2 | head -1)
gh run rerun $run --failed
# 重跑后多数会转绿（dependabot PR 批量处理时 6/6 转绿）
```
- 若重跑后仍失败，才按真实失败排查（看 `gh run view --job <job> --log` 中的用例得分）。

### 3.2 真实 LLM 成本治理（v1.3 新增：哪些环节烧真实 token，如何门控）

CI 里调用**真实 LLM**（生产 `ai-api.migaozn.com` + `SERVICE_TOKEN`）的环节只有 2 个必须留意：

| 环节 | 触发 | 规模 | 治理 |
|---|---|---|---|
| **Agent Eval (smoke)** | **每次 PR**（已加门控） | smoke tier ~7 条真实 LLM 多轮 | **已加 changed-files 门控**：仅当 `backend/ai-agent-service/`、`tests/agent_eval/`、`.github/cases/`、`tests/e2e/real/` 有变更才跑；dependabot/前端/Java 纯依赖升级 PR 跳过（skipped 不阻塞 required check）→ 单次 dependabot 潮可省 150+ 次 LLM 调用 |
| E2E Real | 每日 00:00 定时 | 135+ integration 真实 LLM | 频率已合理（低峰回归），保持 |

- 其余环节不烧真实 token：`nightly-verification` 是 fixture e2e + smoke p1（HTTP 层）；`xiaobu-acceptance` 是本地 mock 栈；`agent-eval.yml`(normal 47 条) 与 `adversarial` 已降频为手动/每周。
- **观察指标**：`gh run list --status queued` 排队 >20 即需治理（先清 dependabot 潮，见 §7）。

## 4. 部署
- 合并到 main 自动触发 3 个部署（admin-api/ai-agent/frontend）+ post-deploy 冒烟。
- **部署后验证（2026-09-01 修正：`/actuator/health` 公网 404 是 nginx 屏蔽的预期行为，勿当成故障）**：
  ```bash
  curl -s https://ai-api.migaozn.com/health          # ai-agent → {"status":"healthy"}
  curl -s -o /dev/null -w "%{http_code}\n" https://merchant.migaozn.com/login   # frontend → 200
  curl -s -o /dev/null -w "%{http_code}\n" -X POST https://api.migaozn.com/api/auth/sms-code -H 'Content-Type: application/json' -d '{}'  # admin-api → 401（存活+鉴权）
  ```
- 冒烟失败若为全量 502/Connection refused 且后续部署已覆盖 → 多为**部署滚动重启瞬态**，以最新一次部署结论为准（见 §7.3 的 mergeStateStatus 思路）。
- 生产登录：13800138000 / 万能码 123456（短信网关仍 bypass，上线前需接入）。

## 5. 相关文档
- `docs/wiki/CONTRACT-LEDGER.md` — 并行开发契约清单
- `walkthrough/RETROSPECTIVE.md` — 全链路复盘（本技能来源）
- `verify-all.sh` / `contract-check.sh` / `check-ui-regression.sh` — 三把工具

## 6. 提交前体检一键命令（2026-08-28 固化）

```bash
# 一次命令检查：case 生成物与 .github/cases/ 单一源是否同步（CI 会 block 分叉）
cd .github && python3 render_cases.py --cases cases --out-eval /tmp/ec.py --out-md /tmp/cb.md >/dev/null 2>&1 \
  && diff -q /tmp/ec.py ../tests/agent_eval/eval_cases.py >/dev/null 2>&1 \
  && diff -q /tmp/cb.md ../docs/testing/mibao-verification-cases.md >/dev/null 2>&1 \
  && echo "生成物 SYNC ✓" || echo "生成物 DIVERGED ⚠️（需重渲染并提交）"
```

## 7. dependabot PR 批量处理 SOP（v1.1 新增，2026-09-01 实战固化）

一次 27 个 dependabot PR 的实战结论：**分类处理，不要全部合并或全部关闭**。

### 7.1 分类标准
| 类别 | 判断 | 处理 |
|---|---|---|
| ✅ 合并 | CI 全绿；或仅 Agent Eval 偶发失败（§3.1 重跑后转绿） | squash 合并 + 删分支 |
| ❌ 关闭 | 依赖解析冲突（npm ERESOLVE / pip ResolutionImpossible）或大版本破坏性升级 | 关闭 + comment 注明原因 |
| ⏸ 保留 | 修改 `.github/workflows/` 的 PR 需要 gh token 的 `workflow` scope（默认 OAuth token 没有） | 保持 open，留给有权限者 |

### 7.2 高频关闭模式（实战 9/27）
- **「半套升级」**：只升子包不升核心 → peer 冲突。例：`@vitest/coverage-v8@4` 配 `vitest@3`；`@tarojs/react@4` 或 `@tarojs/plugin-platform-*@4` 配 tarojs 3.6.40 全家桶；`@babel/core@8` 配 ts-jest 29。
- **pip 冲突**：`pytest-asyncio@1.4` 与 `pytest==8.3.4`、`langchain-openai@1.6` 与 `langchain-core==1.4.8` 不共存。
- **框架破坏**：tailwindcss 4（PostCSS 插件拆分需 `@tailwindcss/postcss`）、mybatis-plus 3.5.9+（extension 拆独立模块）。
- 以上统一回复：关闭原因 + 需要「工程级整组升级」结论，避免 dependabot 半套升级反复打扰。

### 7.3 操作要点
- **同文件组串行合并**：多个 PR 改同一文件（requirements.txt / pom.xml / package.json）时逐个合并，避免同时合并互相冲突；可用后台循环脚本轮询 `mergeStateStatus`，CLEAN/UNSTABLE 才合并。
- `mergeStateStatus` 含义：`UNKNOWN`=GitHub 重算中（main 刚更新），等 30~60s；`BLOCKED`=CI 重跑中或有 pending check；`UNSTABLE`=有 failed check 但非 required，通常可合并；`CLEAN`=直接可合并。
- **分支落后（DIRTY/CONFLICTING）**：`gh pr update-branch <PR>` 触发 rebase；若 update 报冲突，本地 fetch PR 分支 merge origin/main 解决后 push（dependabot 分支同名推送即可）。
- 合并前先 `gh pr checks <PR>` 确认无 required check 失败；改 workflow 文件的 PR 若报 `without workflow scope` 即属 §7.1 保留类。

## 8. CI/本地环境差异已知坑（v1.1 新增，issue #2693 全量教训）

| 坑 | 现象 | 修复 |
|---|---|---|
| **Taro dotenv 只认 .env 文件** | mini-app 构建产物残留 `process.env.TARO_APP_*` → 浏览器抛 `process is not defined` → H5 整页白屏、不请求路由 chunk | `config/index.ts` 的 `defineConstants` 显式替换：`'process.env.TARO_APP_API_URL': JSON.stringify(process.env.TARO_APP_API_URL \|\| '')`（不依赖 .env 文件）；验证：构建后 `grep -c "process\.env" dist/js/app.js` 应为 0 |
| **Playwright 截图按平台找基线** | `toHaveScreenshot` 找 `xxx-{platform}.png`（mac→darwin，CI→linux）；只提交 darwin 基线 → CI 报 "A snapshot doesn't exist ...-linux.png" | 新基线在 CI 用 `--update-snapshots` 生成，或从失败 actual 截图采纳为 `-linux.png` 提交（页面渲染稳定时）；修改 UI 后**双平台基线都要更新** |
| **生成物冲突要重渲染** | `eval_cases.py` / `mibao-verification-cases.md` 合并冲突 | 不要手改——以合并后 `.github/cases/` 为源跑 `python3 .github/render_cases.py --cases .github/cases --out-eval tests/agent_eval/eval_cases.py --out-md docs/testing/mibao-verification-cases.md`，再提交 |
| **shallow clone 无共同祖先** | `git merge-base` 失败、merge 报 unrelated histories | `git fetch --deepen=300 origin main` 后重试 |
| **UI 视觉问题排查** | 页面白屏/不渲染 | 三步定位：① spec 加 `page.on('pageerror')`/`console` 打印重跑 ② 下载 `xiaobu-visual-diffs` artifact 看 trace/截图（像素分析判断纯白）③ 对比本地构建产物（`grep process` 等） |
