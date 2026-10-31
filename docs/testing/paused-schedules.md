# 已停用的周期腿：登记、复查与重启条件（P1-03）

> **谁读**：CI / 测试值班、发布前复核人。
> **为什么有这一份**：夜间回归腿 `.github/workflows/nightly-verification.yml` 的 `schedule`
> 自 **2026-09-06** 起被注释停用（issue **#2957**），到 2026-10-31 上线审计时**停了 55 天** ——
> 而「停用」只写在一行注释里：**注释不会过期、不会报警，也没有任何东西会因此变红**。
> 这份文件把那行注释变成**可复查的登记**。
>
> - **台账（机器读）**：`tests/unit_ci_workflows/paused_schedule_ledger.json`
> - **判据（会红）**：`tests/unit_ci_workflows/test_paused_schedule_registry.py`
> - **前提**：⛔ 本文件**不新增 schedule / cron**，也**不恢复**任何调度（铁律 10）。

## 1. 现状（2026-10-31 读数，逐条可复算）

| 腿 | 停用起点 | 停用原因 | 当前兜底腿 | 未覆盖的缺口 |
|---|---|---|---|---|
| `nightly-verification.yml` | **2026-09-06** | issue **#2957**：nightly 多次 failure + 失败钩子自动开 issue 制造噪音 | `post-merge-verify.yml` / `post-deploy-eval.yml` / `smoke-test.yml` | **smoke p1 全量** 与 **fixture e2e 全量**（白天三腿只覆盖窄面） |
| `e2e-real.yml` | **2026-09-06** | issue **#2957**（同一根因，注释逐字同源）：连续 5+ 日 daily failure + 自动开 issue | `agent-eval.yml` / `agent-eval-adversarial.yml` / `post-deploy-eval.yml` | **真实环境零 Mock 的 E2E** 与 **4 个 integration 标记用例**（要真库真 key；替代腿都是评测栈/部署后窄面） |

> 🔴 第二条 `e2e-real.yml` **不在** 2026-10-31 审计的 P1-03 正文里（审计只点了 nightly）——
> 它是本判据落地时由「**未登记即红**」抓出来的同类（`scripts/drift_audit_baseline.json` 里早有
> `e2e-real.yml|paused`，但基线放行 ⇒ 没有人知道它停着）。⇒ 修一条不等于修一类（铁律 8）。

**复算（只读）**：

```bash
# ① 这两条腿最近跑了什么（审计读数：nightly 最后三次均 workflow_dispatch + failure，schedule 最后一次 2026-09-05）
gh run list --workflow=nightly-verification.yml --limit 5 --json createdAt,event,conclusion
gh run list --workflow=e2e-real.yml --limit 5 --json createdAt,event,conclusion
# ② 停用形态仍在（`on.schedule` 被注释）
sed -n '1,30p' .github/workflows/nightly-verification.yml
sed -n '1,30p' .github/workflows/e2e-real.yml
```

## 2. 逐条登记

### 2.1 `nightly-verification.yml`（停用 55 天）

**它承载什么**（两个 job）：

1. `Smoke p1 regression` —— 对**生产**环境（`api.migaozn.com` / `ai-api.migaozn.com`）跑 smoke **p1** 全量；
2. `E2E fixture specs (full, web project)` —— `--project=web` 的 **fixture e2e 全量**。

**当前谁在兜**：

| 兜底腿 | 覆盖什么 | 覆盖不到什么 |
|---|---|---|
| `post-merge-verify.yml` | 合并后主线的版本面 / 探针面 | 不跑 p1 冒烟、不跑 e2e 全量 |
| `post-deploy-eval.yml` | 部署后的运行时面 + 评测闭包 | 同上 |
| `smoke-test.yml` | 冒烟（p0 窄面） | p1 标记的用例与 e2e 全量 |

> ⚠️ 这三条腿**都不是** `nightly` 的等价替代：`smoke p1` 与全量 `fixture e2e` 在 CI 里**哪儿都不跑**
> （这条残余已逐条登记在 `tests/unit_ci_workflows/e2e_spec_inventory_ledger.json`）。

**重启条件**（三条**同时**成立才恢复；台账里也写着同样的三条）：

1. issue **#2957** 的失败根因修复 —— 两条 job 能连续多轮稳定绿（不再「一跑就红 + 自动开 issue」）；
2. **本地验证提速**落地 —— 单轮 `./verify-all.sh gate` 不再是小时级，停摆时才有余力接手排查；
3. **修复后复启**的口径：只把 `on.schedule` 的 `#` 去掉，并在 PR body 声明；若按铁律 10 的窄例外口径
   被视为**新增** `schedule`，则同批登记 `tests/unit_ci_workflows/schedule_scope_ledger.json`（未登记即红）。

### 2.2 `e2e-real.yml`（同一根因、同一停用日）

**它承载什么**：`pytest backend/ai-agent-service/tests/e2e/real/` + `test_business_verification.py` /
`test_cross_service_tenant.py` / `test_e2e_full_chain.py` / `test_performance_isolation.py` ——
**真实环境、零 Mock、真 LLM** 的能力回归（`E2E_REAL_ENABLED=true` + 真 `DATABASE_URL` / 真 key）。

**当前谁在兜**：`agent-eval.yml`（PR 侧能力评测）、`agent-eval-adversarial.yml`（对抗评测）、
`post-deploy-eval.yml`（部署后评测）。它们是**评测栈**的窄面，**不覆盖**「生产形态的真实环境 +
`integration` 标记」那一族。

**重启条件**：与 §2.1 同源（#2957 根因修复 / 本地验证提速 / 按铁律 10 销账口径复启）。

**责任人 / 复查日期（两条相同）**：CI / 测试值班（承接单 #2957）；**下次复查日期 = 2026-12-31**。

## 3. 复查步骤（到期必做；平时每周一次即可）

1. 跑 §1 的复算命令，确认「停用形态仍在」+「兜底腿最近是绿的」；
2. 看 issue **#2957**：修复了吗？—— 修复 ⇒ 按 §2 的重启条件第 3 条**恢复并销账**；
   没修复 ⇒ 把台账的 `reviewed_at` 改成当天、`review_due` **顺延**（并把新读数写回本节）；
3. 恢复后**必须**删掉台账条目 + 本节相应段落（判据 3：恢复即销账，陈旧登记会红）。

## 4. 判据（会红 —— 不依赖「记得去看」）

| # | 判据 | 怎么红 |
|---|---|---|
| 2 | **未登记即红**：任何 workflow 的 `schedule` 被注释停用却没进台账 | 下一个人再「注释里停一条腿」⇒ 当场红并具名（`e2e-real.yml` 就是这样被抓出来的） |
| 3 | **陈旧登记即红**：台账条目的腿已恢复 / 已删 / 已改名 | 恢复后忘销账 ⇒ 红 |
| 5 | **复查新鲜度**：`review_due` 早于今天 ⇒ 红 | **过了 2026-12-31 没人复查 ⇒ 每个 PR 都会红**（停用不许永久静默） |
| 8 | **文档接线**：本文件的锚（原因 / 替代腿 / 复查日期）与停用腿注释里的指针 | 删掉本节或删掉注释指针 ⇒ 红（否则又回到「注释里停了、无人知道」） |

判据 = `tests/unit_ci_workflows/test_paused_schedule_registry.py`（`case_ids: MC-012`）；
`tests/unit_ci_workflows/` 全量在 `./verify-all.sh gate` 里跑 ⇒ 「过期」在**下一次 PR** 就红。

## 5. 覆盖面（照实登记，别读成「停用这件事已经解决」）

- 本文件**不恢复**调度、也**不判定**「该不该恢复」；重启条件是否达成由 #2957 的承接方裁决。
- 判不了「兜底腿真的覆盖了原腿的能力」—— 台账只证明替代腿**文件存在**（运行期覆盖度见
  `tests/unit_ci_workflows/e2e_spec_inventory_ledger.json`）。
- 判不了「值班真的按 §3 复算了」—— 复查是**人的动作**；判据只把「过了复查日期没人复查」变成红。
- 停用形态只认 `# schedule:` / `# - cron:`（唯一出处 = `scripts/drift_audit.py` 的 `PAUSED_SCHED`）；
  把 workflow 改名成 `.yml.disabled` 这类停用不在射程内（`drift_audit` 也看不见，两边口径一致）。
