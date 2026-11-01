# 生产最小可观测：三类事件**怎么真的响**（上线审计 P0-04，issue #8203）

> 这份文档回答一个问题：**5xx / 证书到期 / 发布失败**这三类事件发生时，**谁在判、判到什么程度、
> 响到哪个通道、怎么去重、怎么演练、还缺什么**。
> 审计原文（`acceptance/2026-10-31-launch-audit/findings.md` 的 P0-04 行）：
> 「三类事件必须能真的响，落到一个有人看的通道；当前只有腿本身红/绿，**无告警触达**」。
> 背景约束是 `docs/deployment/production-deployment.md` 的「5. 生产安全基线」——
> 它把「SLS 采集 + 告警（CPU/内存/磁盘/5xx/健康检查）触达值班」列为**必须项**。

## 1. 一眼看全（三类事件 × 判据 × 通道）

| 事件类 | 判据本体（只读、0/1/3 三态） | 在哪儿跑（既有腿，**不新增 schedule**） | 通道（谁看） | 去重键 |
|---|---|---|---|---|
| **5xx 计数** | `deploy/scripts/prod-5xx-window.sh` | `.github/workflows/post-merge-verify.yml` 的「5xx 计数窗口判红」步（`push: main` / 每日 03:17 / 手动） | `scripts/prod_alert.sh` ⇒ issue `[prod-alert] 生产 5xx 计数超阈值（合成探针窗口）` + `priority/P1`（可选再加 webhook） | `key=5xx-window` + 读数分级 `band` |
| **证书到期**（P0-01） | `deploy/scripts/tls-expiry-check.sh`（21 天阈值） | 同一腿的「TLS 证书到期判红」步（`push: main` / 每日 / 手动） | 同上 ⇒ issue `[prod-alert] TLS 证书临期 / 过期 / 域名不匹配（四域共用一张证书）` | `key=tls-expiry` + `TLS_EXPIRY_SUMMARY` 的分档计数 |
| **发布失败**（P0-02 / P1-04） | `scripts/deploy_leg_failure_reaction.sh`（既有，issue #6526 B） | `.github/workflows/deploy-reconcile.yml` 的腿级反应步（`workflow_run: completed` + 状态兜底） | issue `[deploy-leg] <腿名> 部署失败（合并后未上线）` + `priority/P1` | 腿的 workflow 名（标题） |
| （部署后回归失败） | `.github/workflows/post-deploy-eval.yml` 的判定步 | 同文件的 `report` job | issue `[Post-Deploy] 部署后回归失败 — <日期>` | 同日同标题（同日多次失败汇到一条线程） |

**判据本体与通道是两件事**（这正是审计说「只有腿本身红/绿」的病根）：判据本体只负责
「事件是否成立 + 读数是多少」；**投递**一律走 `scripts/prod_alert.sh`（一条实现、一条去重规则），
所以「红/绿」与「有没有人被告知」不再耦合。

## 2. 通道：默认 GitHub Issue，webhook 可选，缺配置**不静默**

| 通道 | 何时用 | 需要的配置 | 缺失时 |
|---|---|---|---|
| **GitHub Issue**（`priority/P1` + 标题去重） | 默认（Actions 里 `gh` 始终可用） | 无（`GITHUB_TOKEN` + 该腿的 `issues: write`） | `gh` 调不通 ⇒ `rc=3` + `::error::`（**不静默**） |
| **Webhook**（群机器人 / 邮件转发） | `MIGAO_ALERT_WEBHOOK_URL` 有值 ⇒ **附加**发一份；或 `MIGAO_ALERT_CHANNEL=webhook` ⇒ 只走它 | repo secret `MIGAO_ALERT_WEBHOOK_URL` | 显式选了 webhook 却没有 URL ⇒ `rc=3` + `::error::` |
| 短信 / 电话 / 邮件直发 | **未做** | —— | 见 §7（需外部账号，登记为未覆盖） |

`scripts/prod_alert.sh` 的退出码：`0` = 已投递或去重命中；`1` = 入参非法 / **正文命中疑似凭据**（拒绝发送）；
`3` = **无法投递**（通道不可用）。三态里 `3` **不得当 0 读**。

## 3. 幂等 / 去重：同一事件**不刷屏**

投递身份 = `--key`（事件类）+ `--bucket`（**读数分级**）。指纹写进正文的 HTML 注释：

```
<!-- migao-alert fp=5xx-window_rc1_1-5 -->
```

投递规则（判据 = `tests/unit_ci_workflows/test_prod_alerting.py` 的三条幂等用例）：

1. 同标题**没有** open issue ⇒ 开一条（带 `priority/P1`）；
2. 同标题**有** open issue 且正文/评论里已有同一指纹 ⇒ **什么都不写**（`delivered=deduped`）；
3. 同标题有 open issue 但指纹不同 ⇒ **评论追加一条**（分级变了 = 事件真的变重/变轻）。

🔴 **`--bucket` 只许放「分级」，不许放逐轮会抖的精确值** —— 5xx 的精确条数每轮都会变
（3 / 5 / 4 …），直接当指纹会让值班单被逐轮刷评论，那就又变回告警疲劳。本仓现在的分级：

| 事件 | 分级值 | 什么时候会再出声 |
|---|---|---|
| 5xx | `rc<0|1|3>_<band>`，`band ∈ none / 1-5 / 6-20 / 20+` | 量级跳档（1-5 ⇒ 6-20 ⇒ 20+）或从 1 变 3（无法判定） |
| 证书 | `rc<0|1|3>_<TLS_EXPIRY_SUMMARY 的分档计数>`（**不含**逐日递减的剩余天数） | 某个域从 `expiring` 变 `expired` / 受影响域名变多 / 变 3 |
| 发布失败 | 腿名（标题） | 同一条腿再次失败 ⇒ 评论追加；成功上线 ⇒ 由 `deploy-leg` 自己**清零关单** |

## 4. 设计选择（二选一，这里是**明确**选择）：告警投递失败**不改腿色**

审计要求「告警失败本身不得让部署腿变红（或明确设计成红，二选一并说明）」。本仓选**前者**：

- **事件 ⇒ 腿红**：5xx 超阈值 / 证书临期 / 发布失败**仍然**让对应的腿判红（判据语义不变，
  没有因为「反正会发告警」而放宽任何门禁）。
- **投递 ⇒ 只降级**：`scripts/prod_alert.sh` 在 workflow 里一律以
  `… || echo "::warning::告警投递失败（不改腿色）"` 调用。理由：腿的红/绿必须只由**事件判据**决定；
  一次 GitHub API 抖动 / 标签缺失 / webhook 超时**不该**制造第二套失败语义
  —— 那正是 P1-04「成功即红」那类告警疲劳的近亲。
- **代价（照实登记）**：如果事件成立**且**投递也失败，读者只能在**已经红的**那条腿上看到
  `::warning::` 与 `PROD-ALERT-SUMMARY rc=3`；这时没有第二条独立通道会再叫一次。
  重启条件：若出现「事件成立 + 投递失败 + 无人发现」的真实事故，改成投递失败也判红（一行 `exit 3`）。

## 5. 演练读数（本地可复算，零副作用）

三条都是**真跑本仓脚本**的读数，不是"应该会响"的推断。演练**不建真单**：5xx 那条用 stub `gh`
（只落盘调用与正文），证书那条用 `--dry-run`（只打印将要发送的正文）。

### 5.1 5xx：stub 502 ⇒ 判据 rc=1 ⇒ 通道收到 1 条（2026-10-31 15:53:03 CST）

```
$ PROD_5XX_URLS=http://127.0.0.1:<stub>/boom PROD_5XX_THRESHOLD=1 PROD_5XX_ROUNDS=2 PROD_5XX_INTERVAL=0 \
    bash deploy/scripts/prod-5xx-window.sh
PROD-5XX-SUMMARY rc=1 reason=5xx>=threshold rounds=2 requests=2 fivexx=2 band=1-5 ok=0 other=0 unknown=0 threshold=1 window_s=0
❌ **告警**：窗口内 5xx=2 >= 阈值 1（2 次请求）

$ … | bash scripts/prod_alert.sh --key 5xx-window \
      --title '[prod-alert] 生产 5xx 计数超阈值（合成探针窗口）' --bucket 'rc1_1-5' --body-file -
🔴 已新建值班单（标题：…，标签：priority/P1）
PROD-ALERT-SUMMARY rc=0 delivered=created channels=issue, issue=- key=5xx-window fp=5xx-window_rc1_1-5
```

- **时间**：2026-10-31 15:53:03 CST
- **通道**：issue 通道（演练用 stub `gh` 承接：`gh issue list` → `gh issue create --label priority/P1`）
- **内容**：判据读数全文（含 `PROD-5XX-SUMMARY`、逐面 code、复算命令、处置三步）
- **线上现状读数**（同一脚本，真打生产四面）：`2026-10-31 15:53:18 CST`
  ⇒ `PROD-5XX-SUMMARY rc=0 rounds=4 requests=16 fivexx=0 band=none ok=16 unknown=0 threshold=3`
  （16 次请求全部 2xx ⇒ **现在没有 5xx**；这不等于"以后不会有"，所以判据才要常驻）

### 5.2 证书：把「现在」推后 20 天 ⇒ 判据 rc=1 ⇒ 投递 dry-run（2026-10-31 15:53:40 CST）

```
$ TLS_NOW_EPOCH=$(( $(date -u +%s) + 20*86400 )) bash deploy/scripts/tls-expiry-check.sh
TLS_EXPIRY domain=api.migaozn.com status=expiring days_left=7 not_after_epoch=1795775358
…（四域同形）
TLS_EXPIRY_SUMMARY rc=1 checked=4 ok=0 expiring=4 expired=0 mismatch=0 unknown=0 threshold_days=21

$ … | bash scripts/prod_alert.sh --key tls-expiry --title '[prod-alert] TLS 证书临期 / 过期 / 域名不匹配（四域共用一张证书）' \
      --bucket "rc1_checked=4 ok=0 expiring=4 …" --body-file - --dry-run
PROD-ALERT-SUMMARY rc=0 delivered=dry-run channel=auto key=tls-expiry fp=tls-expiry_rc1_checked-4-ok-0-expiring-4-…
```

- **真实当前读数**（`2026-10-31 15:53` CST）：四域 `status=ok days_left=27`（`notAfter=Nov 27 10:29:18 2026 GMT`）
  ⇒ `rc=0`。**阈值 21 天 ⇒ 约 2026-11-06 起会翻成 rc=1 并开始叫**（这就是 P0-01 的续期必须在到期前做完的原因：
  一次性兜底见 `docs/deployment/tls-renewal.md`）。

### 5.3 发布失败：通道**已经在线上叫过**（durable，不是演练）

- `2026-10-28T12:15:32Z` 由 `app/github-actions` 自动开出 **issue #8019**
  `[deploy-leg] Publish C-end H5 (app.migaozn.com 根) 部署失败（合并后未上线）`，标签 `priority/P1`
  ⇒ 这条通道不是"设计上会有"，而是**已经在响**（复核：`gh issue view 8019 --json title,author,labels`）。
- 覆盖面：六条腿在 `tests/unit_ci_workflows/deploy_leg_failure_reaction_ledger.json` 登记
  （admin-api / ai-agent-service / admin-web / worker-h5 / bmini-h5-hosting / c-end-h5），
  事件面（`workflow_run.completed`）+ 状态兜底（`.deploy-watchdog-state.tsv`）两条入口，
  成功上线后**自动关单**（清零声明只在关单成功后写，issue #7075）。

## 6. 复算与处置（一条一条复制就能跑）

```bash
# 5xx（只读；退出码 0=未超阈值 / 1=超阈值 / 3=无法判定）
bash deploy/scripts/prod-5xx-window.sh
PROD_5XX_THRESHOLD=3 PROD_5XX_ROUNDS=4 PROD_5XX_INTERVAL=5 bash deploy/scripts/prod-5xx-window.sh   # 显式参数

# 证书（只读；21 天阈值）
bash deploy/scripts/tls-expiry-check.sh            # 0=充足 / 1=临期·过期·域名不匹配 / 3=无法判定
bash deploy/scripts/tls-expiry-check.sh --warn-days 30

# 投递（演练；不建单）
printf '演练正文\n' | bash scripts/prod_alert.sh --key drill --title '[prod-alert] 演练' --bucket manual --body-file - --dry-run

# 发布失败通道（读，不改）
gh issue list --state open --search '[deploy-leg] in:title' --json number,title,labels
```

处置去向：5xx ⇒ `docker ps` + `docker logs --tail 200 migao-nginx`（502/504 指向哪个上游）⇒ 该上游容器日志；
证书 ⇒ `docs/deployment/tls-renewal.md`；发布失败 ⇒ 对应腿的 run 日志 + `docs/deployment/rollback.md`。

## 7. 仍未覆盖 / 仍需人工配置（照实登记，§19.1）

| 项 | 状态 | 重启条件 |
|---|---|---|
| **全站 5xx 率**（nginx access log 口径） | **未覆盖**：CI 在 GitHub 托管 runner 上，读 `/var/log/nginx/access.log` 要额外 SSH 凭据（探针位没有）⇒ 现用**合成探针窗口**（面 × 轮次）代替 | 接上 SLS / 日志服务，或给探针位一条只读的宿主机执行通道 |
| **30s / 1min 级外部合成监控** | **未覆盖**：本仓不新增 schedule（铁律 10）⇒ 探针挂在既有腿的 `push: main` / 每日 / 手动三个面上，最坏间隔 = 一天 | 用户批准一条「只读 · 幂等 · 失败可见」的心跳 schedule（四条前置见 AGENTS.md 铁律 10） |
| **短信 / 电话 / 邮件直发** | **未做**：需外部账号（SMTP / 短信签名 / 电话网关） | 用户提供账号后，在 `scripts/prod_alert.sh` 加第三条通道（或把 webhook 接到群里） |
| **webhook 接收侧** | **等你配**：repo secret `MIGAO_ALERT_WEBHOOK_URL`（群机器人 URL 即可，POST JSON：`source/key/bucket/fp/title/run_url`） | 配上即生效，无需改代码；缺失时 issue 通道照旧工作 |
| **值班轮值表**（谁在什么时候看） | **未做**：`priority/P1` 标签 + issue 列表是"有人看"的最低形态 | 有明确值班人后加 assignee / 值班表（本仓尚无轮值数据） |
| **客户端错误上报**（P0-03 白屏面） | **不在本包**：由 issue #8203 的前端包承接 | —— |

## 8. 为什么这不是"新增定时器"（铁律 10 的证明）

- 判据只挂在**已存在**的触发面上：`.github/workflows/post-merge-verify.yml` 的
  `push: main` / `schedule: 17 19 * * *`（= 每日 03:17 CST）/ `workflow_dispatch`；发布失败那条挂在
  `.github/workflows/deploy-reconcile.yml` 的 `workflow_run: completed`（既有）。
- 本包**没有**新增任何 `schedule:` 条目 —— 判据 =
  `tests/unit_ci_workflows/test_iron_rule_10_schedule_scope.py`（存量 schedule 只许缩短）+ 本包
  `tests/unit_ci_workflows/test_prod_alerting.py` 的接线判据（探针/投递必须在既有腿里、且在 `if: failure()` 之前）。
- 探针**只读**：`GET` 状态码 + `openssl s_client`，不写盘、不改配置、不删除任何东西。
- 投递侧唯一的写动作 = **开/评论 issue**（幂等、可人工关闭），没有远端删除/破坏性动作。
