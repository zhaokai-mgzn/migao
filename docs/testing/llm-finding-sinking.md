# LLM 发现 → 确定性下沉（用户裁定 4′，承载 issue #4034）

> **一句话**：真实 LLM 只负责**发现**（低频、非自动），**拦截全部交给确定性层**（每 PR、免费）。
> 所以每条 LLM 红例**必须**下沉为 ≥1 条确定性断言；**没下沉的必须显式登记**。
> 判据与用法都在本文（下方有**可执行命令**，不是流程散文）。

## 1. 为什么这条链必须存在

2026-09-17 用户裁定（见 #4009「裁定补充（第二轮）」2′/4′）：

- **裁定 2′**：关闭 PR 时的真实 LLM 自动跑（`agent-behavior-eval.yml` 的评测 job 已**整体删除**；#4275 起该文件**整个删除**），
  代价（PR 阶段不再有 LLM 行为信号）**已知并接受**；
- **裁定 4′**：真实 LLM 评测只走**定时（既有档全保留）+ 手动**，PR / 合并 / 迭代一律不触发。

⇒ 行为层的"发现能力"变低频之后，**唯一的拦截面就是确定性层**。若红例只被修在 LLM 波形里、
没有固化成确定性断言，那么同一缺陷**下一次照样溜过 PR**（PR 层已经不跑 LLM 了）——
这是 `migao-acceptance`「假绿 / 空断言」的同族形态，只是漏得更彻底。
故本文要求的不是"记得补断言"，而是**一条能被机器判定有没有做的链**。

## 2. 流程（四步，每步都有落点）

| 步 | 做什么 | 落点（可机械核） |
|---|---|---|
| ① 发现 | LLM 低频道（定时/手动）跑出红例 → **自动开 issue** | issue 号 = **台账主键**。标题族：`[Post-Deploy] 部署后回归失败` / `[Xiaobu] … 验收失败` / `[Agent Eval] 米宝冒烟评测失败` / `[Agent Eval] 米宝对抗评测失败` |
| ② 归因 | 区分「**用例资产缺陷** / **产品缺陷** / LLM 波动」 | 只有前两类需要下沉；波动按 §14.3 波动台账治理，**不得**用它当"不下沉"的万能理由 |
| ③ 下沉 | 在红例涉及的用例上补 **≥1 条确定性断言**，并在用例 `merge_log` 写 `issue #<N>` | 断言形态见下；`merge_log` 回填 = **记入用例库**（`--selftest` 逐条核） |
| ④ 入账 + 回填 | 台账加条目（`sunk` 或 `unsunk`），并在**发现它的 issue** 上回填断言 ID / 台账评注 | `.github/llm-finding-ledger.json`；GitHub 侧回填用 `--check-backfill` 核 |

**下沉的五种确定性形态**（判据单一源 = `.github/assertion_taxonomy.py` 的 `EFFECT_FIELDS`，
本流程**不另列一份字段清单** —— 两份清单必然漂移）：

| 形态 | 回答什么问题 | 实证锚点 |
|---|---|---|
| `must_succeed` | 「调用了 ≠ 成了」：写操作真的 `success=true` 了吗 | #3361 / #3778 |
| `db_verify` | 落库真值：工具说成了、库里到底有没有 | #3056 |
| `amount_verify` | 金额：写成功 ≠ 钱算对了 | #3365 |
| `output_verify` | 产出 payload 对不对 | #3367 |
| **L0 不变式** | 该行为能不能被**静态/单测**钉死（无需 LLM） | DF-011 → `backend/ai-agent-service/tests/unit/test_circuit_breaker.py`（#3679） |

## 3. 机械检查（可执行，退出码三态）

```bash
python3 .github/llm_sink_check.py --selftest                      # 台账自检（离线、确定性；CI 跑这条）
python3 .github/llm_sink_check.py --issue 4014                    # 「这条 LLM 红例产出确定性断言了吗？」
python3 .github/llm_sink_check.py --issue 4014 --check-backfill   # 额外核 GitHub issue 侧的回填评注（需 gh+网络）
python3 .github/llm_sink_check.py --all                           # 盘点所有 open 的 LLM 来源 issue 与台账的差集
python3 .github/llm_sink_check.py --json                          # 机读输出（供 agent / CI 消费）
```

| 退出码 | 含义 |
|---|---|
| `0` | **已下沉**：用例/测试存在、声明的效果层字段**至少一个非空**、`has_effect_assertion` 为真、`merge_log` 回填 `#<issue>` |
| `1` | 违规：**未登记** / 声称已下沉但断言是**空壳** / 回填缺失 / `unsunk` 缺 `reason`·`follow_up` |
| `3` | **无法判定**（需要 `gh` 的事核不了）—— **不谎报通过**（同 `.github/scripts/eval_slot_status.sh` 的三态口径） |

- CI 落点：pr-check 的 **`LLM Sink Ledger (红例→确定性下沉)`** job（纯静态、零 LLM、零网络，
  只跑 `--selftest` + L0 退化守卫）；判据自身的红证在
  `tests/unit_ci_workflows/test_llm_finding_sink.py`（注入"断言空壳/用例不存在/回填缺失/unsunk 缺字段"
  的变异样本**必须被判红**）。
- ⚠️ 该 job **不是独立 required check**（是否 required 以分支保护现场为准）——别读成"有硬门禁"。

## 4. 范例：P5 的标准下沉形态（证流程可操作）

**issue #4014（P5）/ PR #4021** 把三条 B 端下单用例从「工具被**调用过**」升级为**效果层断言**：

| 用例 | 原来（看不到失败） | 下沉后 |
|---|---|---|
| `OR-009` | 只有裸工具名 `expectations`（`order_create` 出现过即 100%） | `must_succeed: [order_create]` |
| `OR-010` | 同上（真实 run 的首跑红指纹里就有 `no_success(order_create)`，**断言看不见**） | `must_succeed: [order_create]` |
| `OR-011` | 同上 | `must_succeed: [order_create]` + `db_verify`（`order_items` 明细/数量、`order_phone` 落库号） |

三条用例的 `merge_log` 均回填 `issue #4014` ⇒ `python3 .github/llm_sink_check.py --issue 4014`
返回 **0**（台账里 `status=sunk`，`evidence` 指向 PR #4021）。**这就是新红例应照抄的形态。**

## 5. 未机械化 / 边界（照实登记，不写恒真判据凑数）

完整清单在 `.github/llm-finding-ledger.json` 的 `unimplemented`（台账是单一源，本文只摘要点）：

1. **新红例的自动入账未实装**：评测 workflow 建 issue 时**不会**自动写一条 `status: unsunk` 占位；
   `--all` 只能把「缺失」**查出来**（且要求 `gh` 可用），**查到 ≠ 补上**。
2. **GitHub 侧回填的核验未接入 CI**：核它需要 `gh` + 网络 ⇒ 只在 `--issue N --check-backfill` /
   `--all` 里做，核不了返回 **3**；**没有任何机制保证回填一定会发生**（目前靠人/agent 自觉）。
3. **`[行为映射门禁] 规则命中用例失败` 族默认不在 `--all` 的枚举范围内**（默认只认 §2 那 4 条标题族）。
   其**生产者**（PR 层 LLM 的自动开 issue）已随裁定 2′ 删除，故不会新增成员；存量成员需人工核
   （`#3679` 就是其中一条，已作为 `sunk` 入账）。
4. **「断言真的会红吗」不在本层能力范围内**：本检查只回答「断言非空 + 属效果层 + 回填链在」，
   不回答「这个断言有判别力」。后者属 runner / 红证层（`migao-acceptance`：不会红的断言 = 空断言）。

## 6. 相关文档（分工，不重复表述）

| 关注点 | 去哪 |
|---|---|
| 单一入口 / 档位矩阵 / 触发口径（谁能自动跑） | `docs/testing/eval-environments.md` §3.7（+ `post-deploy-eval.yml` 文件头） |
| 验收与评测协议（L1/L2/UA、证据分层、红证） | `docs/testing/acceptance-protocol.md` |
| 用例库单一源与生成物 | `.github/cases/`（改后必须跑 `render_cases.py` 并提交生成物） |
| 断言可信度静态门禁 | `.github/assertion_taxonomy.py` + `.github/case_trust_gate.py` |