# 上线审计收口状态（issue #8197 · 2026-10-31）

> 基线 = `origin/main` @ `42784b824` + 在飞（#8271 / #8214 / #8278）。
> 标记口径：**已合** = 已在 `origin/main`；**在飞** = PR open、CI 绿或近绿；**待用户** = 只能由人执行的仓库外动作；
> **未覆盖** = 审计明确接受「本轮不做」。
> 铁律 11a：本表每条状态都能用 `git log --oneline origin/main` / `gh pr view <N>` 复算；不能复算的一律标「待用户/未覆盖」。

## P0（4 条）

| # | 事项 | 容器 | 状态 | 复算 / 下一步 |
|---|---|---|---|---|
| **P0-01** | TLS 证书临期 + 续期必失败（SAN 含无 A 记录的 `admin`） | #8201 / #8278 | **已修复（2026-10-31 执行）**：判据 `tls-expiry-check.sh` 已合；用户授权后经 **aliyun CLI 云助手**在宿主重签 —— 7-SAN、`notAfter=2027-01-29`、`rc=0 checked=7 ok=7 days_left=89`、`certbot renew --dry-run`（`DRYRUN_RC=0`）；备份 `/root/letsencrypt-backup-20261031T112340Z.tar.gz`，陈旧 `api` lineage 已移入 `renewal-disabled/` | **待用户**：宿主 cron 仍是旧条目（`restart nginx` + 无失败告警）⇒ runbook §4 的 cron 加固未执行（改生产 cron 需显式授权） |
| **P0-02** | C 端 H5 线上产物落后 5.0 天 | #8197 | **根因已定位**（2026-10-31 复算）：近 5 次 `c-end-h5-publish` 运行 `Resolve mode` 全部输出 `mode=notify` ⇒ **从未带 `publish=true` 跑过 publish 分支**；不是发布腿坏了 | **待用户**：`gh workflow run c-end-h5-publish.yml --ref main -f publish=true`（写生产静态根，首次发布由人手动触发 = issue #4184 用户裁定 B） |
| **P0-03** | admin-web 无全局错误边界 + 四端零错误上报 | #8203 / #8214 | **在飞**：#8214 已 rebase 到 `824361510`（7 处冲突已解）、用例重渲染 945 条、RBAC 台账 `UNANNOTATED_ENDPOINTS` 25→26 显式放宽；CI 中 | 合并后真机复探白屏出口 + `POST /api/client-errors` 端点 |
| **P0-04** | 上线可观测性缺位（5xx / 证书 / 发布失败不会叫人） | #8203 / #8269 | **已合** `55fdb5eee`：`deploy/scripts/prod-5xx-window.sh` + `scripts/prod_alert.sh`（issue `priority/P1` 标题+分档指纹去重），挂在既有 `post-merge-verify` / `deploy-reconcile` 腿上，**不新增 schedule**；发布失败通道已有 #8019 实证 | **待用户**：可选 `MIGAO_ALERT_WEBHOOK_URL`（群机器人/邮件转发）；短信/电话/邮件直发与全站 5xx 率**未覆盖**（登记在 `docs/deployment/observability-minimum.md`） |

## P1（12 条）

| # | 事项 | 容器 / PR | 状态 |
|---|---|---|---|
| P1-01 | 唯一可信探针 `/api/version`、`/actuator/health` 公网 404 | #8214 | **在飞**：补 `/version` 构建身份（三态语义）+ `synthetic_probe.py` |
| P1-02 | 容器日志无上限 / 磁盘水位无人看 | #8257 | **已合** `d13749420`：4 服务 `logging` 50m×3 + `MIGAO-DISK-WATERMARK` 读数 |
| P1-03 | 夜间回归停摆（两条腿静默停用） | #8265 | **已合** `824361510`：`paused_schedule_ledger.json` 登记 + `drift_audit` C6 改接台账 |
| P1-04 | 发布腿假红（`stale-report-reaper` rc=2 被当失败） | #8257 | **已合** `d13749420` |
| P1-05 | 回滚判据不可用（`/actuator/health` 恒 404） | #8257 / #8214 | **已合**（#8257 `d13749420`）**+ 在飞增强**（#8214）：`rollback.md` 判据地址改成 `/api/version` + `/b/` `/w/`，`/actuator` 明写为什么不能用 |
| P1-06 | 37 页无读失败出口 | #8263 | **已合** `21b2abebf`：复核后确认真实缺口只有 `/categories`（其余四页早已可区分），已补常驻失败面 + `EmptyState` 类级守卫 |
| P1-07 | RDS 备份窗口 ≥14 天未证 | #8265 | **已合** `824361510`：`scripts/rds_backup_window_readout.py`（rc=0/1/3）；**恢复演练仍待用户** |
| P1-08 | 反向代理后协议还原缺失 | #8257 | **已合** `d13749420`（`forward-headers-strategy: native`） |
| P1-09 | 静态域无安全头 | #8257 | **已合** `d13749420`：`prod-security-headers.sh` 判据 + nginx nosniff/HSTS/CSP；线上 7/7 rc=0 |
| P1-10 | 访问日志可能泄露 token | #8257 | **已合** `d13749420`：`log_format migao_no_token`（只记 `$uri`） |
| P1-11 | 审计表只增（`audit_logs`/`notifications`） | #8265 | **已合** `824361510`：`scripts/db_growth_readout.py`（rc=0/1/3） |
| P1-12 | 容器无健康检查（假活） | #8257 | **已合** `d13749420`：admin-api / admin-web / nginx 三处 healthcheck |

## 仓库外动作清单（全部待用户）

1. ~~TLS 7-SAN 重签~~ **已于 2026-10-31 执行完毕**（#8278 记录读数）；剩下 **宿主 cron 加固**（runbook §4，未授权不动）
2. **C 端手动发布**（P0-02，`-f publish=true`）
3. **终端发布链**：终端仓出包 `v1.0.1` + tag、`TERMINAL_REPO_TOKEN` secret（P0-02 / B1）
4. **微信小程序**：appid/私钥、后台「扫普通链接二维码打开小程序」规则、校验文件、服务器域名白名单、提审发布（B4）
5. **1~2 家试用客户**开通（runbook 已就绪：`docs/deployment/trial-onboarding.md`，现场实读 `rc=3 passed=8 failed=0 unknown=4`）
6. **云侧**：RDS 备份保留 ≥14 天确认 + 恢复演练记录
7. **可选**：`MIGAO_ALERT_WEBHOOK_URL`

## 两处审计口径订正（本轮发现）

- main 上原把审计误标为 `issue #8218`（实为 dependabot PR）⇒ 已订正 44 处 / 20 文件，并加类级判据 `test_audit_ref_containers.py`（#8271）。
- `docs/deployment/observability-minimum.md` 曾被两个包写成两份不同内容（P0-04 与 P0-03）⇒ 已拆分为 `observability-minimum.md`（P0-04）与 `observability-client-errors.md`（P0-03，随 #8214）。
