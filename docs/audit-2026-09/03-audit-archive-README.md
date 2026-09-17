# 审计归档（2026-09-17）—— 索引与新鲜度契约

> **来源**：issue [#4041](https://github.com/zhaokai-mgzn/migao/issues/4041)（「三份报告 + 越修越多六机制 + 线上会话取证 + 研发模式评分卡（此前只在对话/`/tmp`）」）
> **锚定 SHA**：审计基线 `origin/main` @ `46c91d3c`；归档复算时点（分支基点）`8e03e5b3`；采集期间主线推进到 `da9d66e8`
> **采集时间**：2026-09-18 03:00 (+0800)
> **文件性质**：**混合 —— 索引页是活文档；03-1 ~ 03-5 是冻结快照（historical，不再随主线更新）**

> ⚠️ **SHA 的三层含义**（别混用，`migao-dev-flow` §18.1）：
> · `46c91d3c` = **审计基线**（issue 声明的那个），所有「@46c91d3c = N」的计数都锚在它上面；
> · `8e03e5b3` = 本次**归档复算时点**的分支基点（本分支从它开出）；
> · `da9d66e8` = 复算期间主线**又往前走了** 2 个提交后的当前 `origin/main`。
> ⇒ 涉及「main 上现在是什么样」的核验（如 [03-2](03-2-tool-layer-audit.md) 的「已修」列）
> 是按 `8e03e5b3` 读的；**它随时会再变**，以命令重跑为准。

---

## 0. 这批文件在治什么

issue #4041 的原话：

> 本次审计的结论此前**只活在对话与 `/tmp`**（`/tmp/migao_audit/TOOL_LAYER_AUDIT.md`、
> `/tmp/migao-b-order-eval-audit.md` 等），**`/tmp` 会被清掉**。冻结清单 #4009 只落了
> "缺陷条目"，未落"审计过程与证据"。

这正是本仓自认的病灶之一 —— **账本与真相源漂移**（`migao-dev-flow` §19.2③）。
本次归档把它落进 git，让「审计过程」和「缺陷条目」都有同一个可追溯的落点。

## 1. 文件清单与各自的新鲜度

| 文件 | 内容 | 性质 | 会过期的部分 | 怎么复算 |
|---|---|---|---|---|
| [03-1-skill-layer-audit.md](03-1-skill-layer-audit.md) | 报告① Skill 层审计（裁决 + 反证 + 量化） | **快照** | 全部计数（行数/fix 比/churn）—— 随 `base_skill.py` 演进立刻过期 | 文件内每条的「复算命令」 |
| [03-2-tool-layer-audit.md](03-2-tool-layer-audit.md) | 报告② Tool 层审计（D-01~D-11） | **快照 + 已修状态注记** | D-01/D-02/D-11/D-05 已在 main 上修（附核验命令） | 文件内每条的「复算命令」 |
| [03-3-eval-system-audit.md](03-3-eval-system-audit.md) | 报告③ 评测体系审计（M1~M16） | **快照** | 用例计数、效果层断言比例 | 文件内每条的「复算命令」 |
| [03-4-rework-mechanisms.md](03-4-rework-mechanisms.md) | 「越修越多」六机制 + 五组测量 | **快照**（机制部分是**活的分析框架**） | 五组测量的所有数字 | 文件内每条的「复算命令」；机制本身不随数字过期 |
| [03-5-live-session-forensics.md](03-5-live-session-forensics.md) | 线上会话取证（2026-09-17，B 端 5 会话）+ 研发模式评分卡 | **快照，多数不可复算** | 全部 | 见文件内「不可复算资产登记」 |

**只归档有证据的部分**。任何「对话里说过、但仓库里指不出代码/文件/命令」的结论，
一律标注 `未取证`，**不写成已核事实**。

## 2. 账本新鲜度契约（`migao-dev-flow` §18.5 / §19.2③）

读这批文件前请先读这一段，否则会把过期读数当真值。

1. **易变数字一律不写成真值**。本批文件里每个计数都满足二者之一：
   - 附**可复算命令**（`git show <sha>:<path>` / `git log` / 仓内扫描脚本）—— 你可以自己重跑；
   - 或显式标注 **`历史读数，不可复算`**（线上 DB 测量、对话里的口头结论）。
2. **计数一律锚定 SHA 写**（`@46c91d3c = N`），不写「当前是 N」。
3. **与 issue 正文数字不一致时，以本文件的实测值为准，并保留差异说明** ——
   本批文件多处与 issue 正文口径不同（issue 用的是另一套计数口径），差异已在各文件内逐条登记，
   **不静默覆盖**。
4. **本批文件不改**：`base_skill.py` 再演进、用例库再增长，这批快照**不会**跟着更新。
   要新读数 ⇒ 重跑命令，不要编辑本文件（编辑 = 制造第二个真相源）。

## 3. 采集时的环境读数（会立即过期，仅作取证上下文）

```bash
# 审计基线是否在主线（判据：是祖先）
$ git merge-base --is-ancestor 46c91d3c origin/main && echo YES
YES
$ git log --oneline -1 46c91d3c
46c91d3c fix(e2e): 小布 H5 视觉回归 spec 同步 M1-A 新空态（issue #4003） (#4004)
# 基线之后的提交数
$ git rev-list --count 46c91d3c..origin/main
40
```

> ⚠️ 上面的 `40` 在你看的时候**必然已经过期** —— 这正是「活环境测量快照」要写 SHA 的原因
> （`migao-dev-flow` §18.7）。复算命令本身就是判据，数字只是当时的读数。
> **本次采集期间就实测到它过期**：几个小时里主线从 `8e03e5b3` 推进到 `da9d66e8`（+2 提交）。

## 3.1 本次归档的复算环境（一条命令，可自己重跑）

```bash
# 复算必须在**独立 worktree**里做（§2.3 零共享写路径）+ 基线即分支基点
$ cd "/Users/guangzhen.zk/ai native/migao" && git fetch origin main
$ git branch docs/4041-archive origin/main && ./scripts/dev-worktree.sh add docs/4041-archive
$ cd "/Users/guangzhen.zk/ai native/migao-wt/4041-archive"
$ git rev-parse HEAD              # 分支基点（= 复算时点的 origin/main）
8e03e5b3ec336a80f7e934e512ea9f881eb81c35
$ git merge-base --is-ancestor 46c91d3c HEAD && echo "基线是祖先 ✓"
基线是祖先 ✓
```

**本批的净改动范围**（文档类，零行为改动）：

```bash
$ git status --short
 M docs/wiki/INDEX.md
?? docs/audit-2026-09/03-audit-archive-README.md
?? docs/audit-2026-09/03-1-skill-layer-audit.md
?? docs/audit-2026-09/03-2-tool-layer-audit.md
?? docs/audit-2026-09/03-3-eval-system-audit.md
?? docs/audit-2026-09/03-4-rework-mechanisms.md
?? docs/audit-2026-09/03-5-live-session-forensics.md
$ git status --short -- backend/ frontend/ tests/ .github/ scripts/ | wc -l
0        # ← 四类禁用路径零改动
```

## 4. 本批归档的验证记录（可重跑）

```bash
# ① 文档门禁（L0 依赖的守卫族；改动 docs/ 不得弄红它）
$ python3.11 -m pytest tests/unit_ci_workflows -q
1291 passed, 3 skipped in 155.63s

# ② QA Growth Gate 预检（CI 同规则；**必须在 git commit 之后跑**，§2.1）
$ ./verify-all.sh gate
变更集：7 个文件（origin/main...HEAD ∪ 工作区改动）
✅ QA Growth Gate 预检
========== 结果: 1 通过, 0 失败, 0 未就绪（真跑 1 项 / 共 1 项）==========

# ③ INDEX 与归档文件的相对链接全部可打开
$ python3.11 <linkcheck> docs/wiki/INDEX.md docs/audit-2026-09/03-*.md
[7 文件] 检查 44 条相对链接，断链 0 条
```

## 5. 与既有归档的关系

| 文件 | 内容 | 关系 |
|---|---|---|
| [01-undirected-audit.md](01-undirected-audit.md) | 2026-09-04 无方向审计 | 早一批，独立 |
| [02-self-consistency-scan.md](02-self-consistency-scan.md) | 2026-09-06 自洽性扫描 | 早一批，独立 |
| **本批 03** | 2026-09-17 三份报告 + 六机制 + 线上取证 + 评分卡 | 本批 |
| issue #4009 | 「缺陷冻结清单」（A1~A17 / B1~B6 / C1~C5 + 任务包 P1~P5） | **条目层**；本批是它的**过程与证据层** |

## 6. 本次归档**没能**落进仓库的资产（如实登记）

**完整登记见 [03-5-live-session-forensics.md](03-5-live-session-forensics.md) §5「不可复算资产登记（引用黑名单）」。**
摘要：线上 DB 取证（会话数/消息数/metadata 计数/当日订单）、审计时的
`gh api branches/main/protection` 读数、`R8 headRefOid` 的实测次数、
`/tmp/migao_audit/TOOL_LAYER_AUDIT.md` 与 `/tmp/migao-b-order-eval-audit.md` 的**原文**——
均**无仓库内可复现来源**，本批按 issue 正文重建结论、不重建数字。

另外三类**有内容、但不完整**的：

| 资产 | 归档到哪 | 缺口 |
|---|---|---|
| 报告③ 的 M6/M7/M9~M12/M14~M16（16 条里的 9 条） | **未归档** | issue #4041 正文只点名了 7 条（M1/M2/M3/M4/M5/M8/M13），其余**正文未展开** + 原报告已清理 ⇒ 不可重建，**不编造** |
| 报告① 的「9 类互不相干职责」 | 未归档 | 人工分类判断，**无机械判据** |
| 报告② 的 D-04/D-06~D-10 | 未归档（指向 #4009） | #4041 正文未列，条目在 **issue #4009 冻结清单**里 |