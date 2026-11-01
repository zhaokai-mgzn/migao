# TLS 证书自动续期与到期判红（issue #8201）

> 四域（`api` / `ai-api` / `app` / `migaozn.com`）共用**同一张** Let's Encrypt 证书，
> `CN=migaozn.com`，SAN 含 `admin / ai-api / api / app / merchant / migaozn / ops / www`。
> 线上读数（2026-10-31 现取）：
>
> ```bash
> openssl s_client -connect api.migaozn.com:443 -servername api.migaozn.com </dev/null 2>/dev/null \
>   | openssl x509 -noout -dates -ext subjectAltName
> # notBefore=Aug 29 10:29:19 2026 GMT
> # notAfter=Nov 27 10:29:18 2026 GMT
> ```
>
> 到期时刻 **2026-11-27 10:29:18 GMT（= 18:29 +08）**。

## 0. 现状：机制在**宿主 cron**，不是「仓内零机制」，但它已连天失败且无告警

审计单 PR #8200 的 P0-01 写的是「仓内零续期机制」。**更准确的说法是**：

| 事实 | 读数 / 出处 |
|---|---|
| **宿主确实有 cron** | `crontab -l` 有一条 `0 3 * * * certbot renew --quiet --webroot -w /opt/migao-deploy/certbot-www --post-hook 'cd /opt/migao-deploy && docker compose restart nginx >/dev/null 2>&1' >> /var/log/certbot-renew.log 2>&1` |
| 宿主 certbot 版本 | `/usr/local/bin/certbot` → 1.23.0 |
| **它每天在失败** | `/var/log/certbot-renew.log` 每天重复两条：① `api.migaozn.com` lineage：`None of the preferred challenges are supported by the selected plugin`；② `migao` lineage：`Some challenges have failed.` |
| **失败没有告警** | 失败只写进上面那个日志文件，没有任何判红 / 值班面 —— 所以「没续上」这件事可以一直静默到证书过期 |
| 仓内**确实**没有到期判据 | `deploy/swas/deploy.sh` 无到期检查；`.github/workflows` 无续期腿（本单之前） |
| `admin.migaozn.com` **没有 A 记录** | `dig +short admin.migaozn.com` 空；其余 7 个 SAN 都解析到 `121.40.28.213` ⇒ 主证书的 HTTP-01 对 `admin` **必失败** ⇒ **整张证书续期失败**。✅ **2026-10-31 已按路径 ② 重签去掉**（证书只剩 7 个可解析 SAN，见 §3「执行记录」） |
| 陈旧 lineage `api.migaozn.com` | 到期 **2026-11-12**；renewal conf 是 `authenticator = manual` + `pref_challs = dns-01`（+ `/root/certbot-auth.sh`），与 cron 全局的 `--webroot` **冲突** ⇒ 每天一条必然失败；**nginx 并未使用它**（nginx 全站用 `live/migao/fullchain.pem`） |

⇒ 结论：**不是「没有机制」，是「机制坏了、而且坏了没人知道」**。本单交付 = 判据（把到期变成可见的红）
+ 一次性修复 runbook（把根因修掉）+ cron 加固（失败可归因、不整断）。
**下一轮不要再用「仓内零续期机制」这句话转述本单的背景** —— 它漏掉了「宿主 cron 已存在且在失败」这一半。

## 1. 交付物一览

| 交付物 | 作用 |
|---|---|
| `deploy/scripts/tls-expiry-check.sh` | **只读**到期检查（四域 + 可选 www；默认阈值 21 天；`0/1/3` 三态；额外解析 `certbot certificates` 的两条 lineage 并标出「未被 nginx 使用」） |
| `deploy/scripts/tls-renew.sh` | 续期（`--dry-run` / `--no-reload`）+ `--install-cron` 幂等安装宿主 cron（含「既有 crontab 条目不双跑」guard） |
| `.github/workflows/post-merge-verify.yml` 的 `TLS 证书到期判红` 步 | **判红接线**：main 侧每轮跑检查；临期 ⇒ 判红 ⇒ 走既有 P1 值班 issue 出口（**不新增 schedule**） |
| `deploy/swas/deploy.sh` 的 `2.6.1` | 每次部署幂等刷新 `/etc/cron.d/migao-tls-renew`（跳过 / 失败都出声，且**不拖垮部署**） |
| 判据 | `tests/unit_ci_workflows/test_tls_renewal.py`（`MC-121`；脚本行为 + 接线 + 摘掉接线必红） |

## 2. 判红怎么读（`0 / 1 / 3`）

```bash
bash deploy/scripts/tls-expiry-check.sh              # 四域
bash deploy/scripts/tls-expiry-check.sh --with-www   # 再加 www.migaozn.com
bash deploy/scripts/tls-expiry-check.sh --warn-days 30
```

| 退出码 | 含义 | 处置 |
|---|---|---|
| `0` | 全部域名证书都读到、剩余 ≥ 阈值、SAN 覆盖 | 无 |
| `1` | **确定有问题**：临期（< 21 天）/ 已过期 / 证书 SAN 不覆盖该域名 | 按 §3 修；临期先按 §4 手工续一次 |
| `3` | **无法判定**：取不到证书 / `notAfter` 解析不了 | **不是「通过」**。先修网络 / DNS / 443，再判 |

`certbot` 的两条 lineage 读数（`TLS_LINEAGE …`）**只做诊断，不改变退出码** —— 未被 nginx 使用的
lineage 到期不影响四域 HTTPS，但它会让每天的 `certbot renew` 整条跑失败（见 §5）。

## 3. 一次性修复：**已裁定走路径 ②**（2026-10-31）**并已执行完毕**，路径 ① 保留给「以后 admin 要用时」

> 根因 = `migao` 证书的 SAN 里有 `admin.migaozn.com`，而该域名**没有 A 记录** ⇒ HTTP-01 必失败。
> **用户已于 2026-10-31 裁定：走路径 ②**（重签、去掉 `admin`、保留 7 个可解析 SAN）。
> 本单的边界原本是「不改域名集合」⇒ 这条被登记为**需人裁定的例外**，现已由用户裁定**执行**。

### 路径 ②（**已裁定、已执行**）：重签，只带可解析 SAN（先去掉无 A 记录的 `admin`，同日晚些再移除已废弃的 `ops` ⇒ 现为 6 个）

```bash
# 在服务器上、/opt/migao-deploy 目录下执行（一次性动作；**2026-10-31 已由用户授权、经 aliyun CLI 在宿主执行完毕**，结果见下方「执行记录」）
cd /opt/migao-deploy
certbot certonly --cert-name migao \
  --webroot -w /opt/migao-deploy/certbot-www \
  --expand --force-renewal --non-interactive \
  -d migaozn.com -d www.migaozn.com -d api.migaozn.com -d ai-api.migaozn.com \
  -d app.migaozn.com -d merchant.migaozn.com
# （2026-10-31 第一刀保留过 ops.migaozn.com = 7 SAN；同日用户裁定把已废弃的 ops 一并移除，
#   第二刀收窄到 6 个 —— `-d ops` 已删。admin 与 ops 都没有 DNS 记录，留在 SAN 里会让下一次续期必失败。）
# 然后由用户执行 reload（不重启，避免整断在途请求）：
cd /opt/migao-deploy && docker compose exec -T nginx nginx -s reload
```

两个开关的作用（别省、也别乱加）：

- `--expand`：`--cert-name migao` 这条 lineage **已存在**且域名集合变化时，**扩/改同一个 lineage**，
  不会新建第二张证书（否则 `live/migao/` 与 nginx 里写死的路径就对不上了）。
- `--force-renewal`：证书**还没到 30 天窗口时 certbot 默认跳过续期**；加上它才会**按新 SAN 集合重新签发**。
  ⚠️ 这是**一次性动作**：**不要**把它写进 cron / `tls-renew.sh` —— 写进去等于每次 tick 都强制签发，
  会直接撞 Let's Encrypt 的限流（`too many failed authorizations` / duplicate certificate）。

### 路径 ①（**不再是默认推荐**，保留给「以后要用 `admin` 子域时」）：补 A 记录后原样续

```bash
# 权威 DNS 加一条：admin.migaozn.com.  A  121.40.28.213（与其余 7 个 SAN 同 IP）
dig +short admin.migaozn.com            # 期望 121.40.28.213；先等 TTL 生效
cd /opt/migao-deploy && bash /opt/migao-deploy/tls-renew.sh --dry-run   # 验通路，不真续
cd /opt/migao-deploy && bash /opt/migao-deploy/tls-renew.sh             # 真续 + reload
```

代价：**依赖外部输入**（DNS 是第三方面）。好处：SAN 集合不变 —— 但要先做一次
`certbot certonly --cert-name migao --expand ... -d admin.migaozn.com ...` 才能把 `admin` 加回来
（路径 ② 执行后证书里已没有 `admin`）。

### 落地后自证（裁定路径跑完必须做）

```bash
# ① 新 SAN 集合里应该没有 admin / ops，且 6 个域名都在
openssl s_client -connect api.migaozn.com:443 -servername api.migaozn.com </dev/null 2>/dev/null \
  | openssl x509 -noout -dates -ext subjectAltName
# ② 通路：dry-run 应该不再报 challenge 失败
bash /opt/migao-deploy/tls-renew.sh --dry-run
# ③ 判据：四域应该都 status=ok
bash deploy/scripts/tls-expiry-check.sh; echo "rc=$?"
```

> ⚠️ 服务器上**没有** `/opt/migao-deploy/tls-renew.sh`（本仓脚本未同步到宿主）时，② 改用
> `certbot renew --dry-run`（语义等价：走 staging、不换生产证书）。

### 执行记录（2026-10-31 已跑完 · 直接读数）

| 项 | 读数 |
|---|---|
| 宿主 | SWAS `b23c69e599524b1da719734f72e6a0e3`（`iZbp1421ocyirzm131owhyZ`，`121.40.28.213`），certbot 1.23.0 |
| 执行通道 | 用户 2026-10-31 授权「通过 aliyun CLI 去操作」⇒ `aliyun swas-open run-command`（云助手），非 SSH |
| 备份 | `/root/letsencrypt-backup-20261031T112340Z.tar.gz`（59,453 B，整份 `/etc/letsencrypt`） |
| 陈旧 lineage | `/etc/letsencrypt/renewal/api.migaozn.com.conf` → `/etc/letsencrypt/renewal-disabled/api.migaozn.com.conf.20261031T112340Z`（**只停续期，不删证书**；nginx 从未用它） |
| 重签 | `certbot certonly --cert-name migao --webroot ... --expand --force-renewal -d`（7 域）⇒ `CERTBOT_RC=0` |
| 新证书 | `notAfter=Jan 29 10:25:18 2027 GMT`（90 天）；SAN = `ai-api/api/app/merchant/migaozn/ops/www` ⇒ **7 个，无 `admin`** |
| reload | `docker compose exec -T nginx nginx -t` 通过 → `nginx -s reload`（`signal process started`；**未 restart**） |
| 判据 | `TLS_EXPIRY_SUMMARY rc=0 checked=7 ok=7 expiring=0 expired=0 mismatch=0 unknown=0 threshold_days=21`（`days_left=89`） |
| 外部复探 | 7 个域名 `openssl s_client` 全部返回新证书；`api/api/version`、`ai-api/health`、`/b/`、`/w/`、`merchant/login`、`/`、`/download` 全 200 |
| 安全头回归 | `PROD-HEADERS-SUMMARY rc=0 failed=0 unknown=0 probed=7` |
| 第二刀（移除 `ops`） | 用户 2026-10-31 裁定「这个也可以移除」⇒ 证书收窄到 **6 SAN**：`notAfter=Jan 29 10:42:46 2027 GMT`；`nginx -t` + `-s reload` OK；`TLS_EXPIRY_SUMMARY rc=0 checked=6 ok=6` |
| `ops` DNS | `ops.migaozn.com A 121.40.28.213`（RecordId `2088230894053550080`）已删除；权威 NS `dns11/dns12.hichina.com` 均返回空 |
| cron 加固 | `/opt/migao-deploy/tls-renew.sh`（sha256 `29d00953…`；宿主到 `raw.githubusercontent.com` 被墙，经 jsDelivr 取回）→ `--install-cron --replace-legacy-cron` ⇒ 旧条目备份 `/var/backups/crontab-20261031T114052Z.bak`，新 `/etc/cron.d/migao-tls-renew`（每天 03:00，日志 `/var/log/migao-tls-renew.log`），`crond` active |
| 续期通路证明 | `certbot renew --dry-run`（后台跑，2026-10-31 19:32→19:34 CST）⇒ `DRYRUN_RC=0` + `Congratulations, all simulated renewals succeeded` ⇒ **7-SAN + webroot 的续期通路真的能过**，不是只看配置猜 |
| dry-run（cron 脚本） | `bash /opt/migao-deploy/tls-renew.sh --dry-run` ⇒ `TLS_RENEW_RESULT=ok-dry-run` + `DRYRUN_RC=0`（`all simulated renewals succeeded`，6-SAN + webroot 通路成立） |
| 仍未做 | **无**（P0-01 的仓内判据 + 宿主重签 + 陈旧 lineage + cron 加固都已执行）；剩余仅观察项：等 2026-12-30 前后 cron 真续一次，看 `/var/log/migao-tls-renew.log` 与每日 TLS 判据 |

> 续期窗口：新证书 2027-01-29 到期 ⇒ 宿主 cron 会在 **2026-12-30 前后**开始真续（`renew_before_expiry = 30 days`）。
> 在那之前，P0-04 的每日 TLS 判据（21 天阈值）不会再误报；若那时 cron 仍失败，`post-merge-verify` 的告警会自己开单。

## 4. cron 加固（把「整断」换成 reload + 可观测）——**2026-10-31 已执行**

现状那条 crontab 用 `docker compose restart nginx`（**整断**在途请求），且失败没有任何非零信号被谁消费。
本单把它收敛成 `deploy/scripts/tls-renew.sh`（日志 `/var/log/migao-tls-renew.log`，失败**非零退出**）：

```bash
# ① 先看会不会双跑（既有 crontab 条目会让同一条续期一天跑两遍）
crontab -l | grep 'certbot renew'

# ② 真正切换：备份并替换（把旧条目移出 crontab，备份到 /var/backups），装 /etc/cron.d/migao-tls-renew
bash /opt/migao-deploy/tls-renew.sh --install-cron --replace-legacy-cron

# ③ 复核（三段读数都要看）
cat /etc/cron.d/migao-tls-renew          # 每天 03:00，调用 tls-renew.sh，日志落 /var/log/migao-tls-renew.log
crontab -l                               # 旧的那条 certbot renew 应该已不在
ls -l /var/backups/crontab-*.bak         # 被移出的原条目留档
systemctl is-active cron                 # 宿主没 cron 守护进程 ⇒ 文件就位也不会跑（脚本会打 ⚠️）
```

**时序（已裁定口径）**：

- **`--replace-legacy-cron` 等本 PR 合并 + 部署之后再跑** —— 部署时 `deploy/swas/deploy.sh` 的 `2.6.1`
  会幂等地尝试 `--install-cron`；因为检测到既有 root crontab 条目，它会**拒绝安装并退 3**（避免双跑），
  这是**有意的安全 guard**，只出声、**不拖垮部署**。
- **「先手工把旧 cron 的 `restart` 改成 `reload`」是可选、不强制**：路径 ② 重签成功后，旧 cron 下一次
  03:00 的 `certbot renew` 本来就会成功（SAN 里已没有解析不了的域名），代价只是那一次会**短暂 restart**。
  想让这段窗口也优雅，就顺手把旧条目的 `--post-hook` 改成
  `docker compose exec -T nginx nginx -s reload`；不改也行。

> 脚本里 reload 一律用 `docker compose exec -T nginx nginx -s reload`，只有 reload 失败才回落 `restart`
> （回落路径会打印「短暂整断」，不静默）。

## 5. 陈旧 lineage：**已裁定执行**（移出 renewal 目录，**不删证书**）

`api.migaozn.com` 这条 lineage 未被 nginx 使用，但它的 renewal conf 与 `--webroot` 冲突，
会让每天的 `certbot renew` **整条**跑失败（即使主证书本来能续）。**用户已裁定：移出 renewal 目录（不删证书）。**

```bash
# 唯一口径：/etc/letsencrypt/renewal-disabled/（本文件只留这一种路径，避免执行时两处）
mkdir -p /etc/letsencrypt/renewal-disabled
mv /etc/letsencrypt/renewal/api.migaozn.com.conf /etc/letsencrypt/renewal-disabled/
ls /etc/letsencrypt/live/api.migaozn.com/    # 证书文件仍在（不删）
```

- **不许**直接 `certbot delete`（会删证书文件）—— 移出即可，随时可以 `mv` 回来。
- 想让这条 lineage 也自动续期（而不是停用）才需要改：`authenticator = webroot` +
  `pref_challs = http-01,` + `webroot_path = /opt/migao-deploy/certbot-www`；**默认不做**（它不是 nginx 在用的那张）。
- 改完复算：`certbot renew --dry-run` 不应再出现那条
  `None of the preferred challenges are supported by the selected plugin`。

## 6. 失败排查（按日志原文对号入座）

| 日志原文 | 真因 | 处置 |
|---|---|---|
| `None of the preferred challenges are supported by the selected plugin` | 某 lineage 的 `authenticator` / `pref_challs` 与 `--webroot` 冲突 | §5 移出 renewal 目录（已裁定） |
| `Some challenges have failed` + 某域名 | 该域名的 HTTP-01 打不通（DNS 缺 A 记录 / 80 被挡 / 网关没放通） | 路径 ② 重签去掉解析不了的域名；先 `dig +short <域名>` 自证 |
| `too many failed authorizations` | Let's Encrypt 限流（同域名失败过多） | **停手 1 小时**，别连续重跑（也别把 `--force-renewal` 塞进 cron） |
| `No renewals were attempted` | 没有到期证书（**正常**幂等路径） | 无需动作；`TLS_RENEW_RESULT=noop` |
| remote 80 返回 404 / 301 | `/.well-known/acme-challenge/` 没落到 `certbot-www` | 核对 `deploy/swas/nginx.conf` 的 webroot location 与 compose 的 `./certbot-www:/var/www/certbot` 挂载 |

排查时**先复算再改**（零成本）：

```bash
tail -n 200 /var/log/migao-tls-renew.log
bash /opt/migao-deploy/tls-renew.sh --dry-run
bash /opt/migao-deploy/tls-expiry-check.sh
```

## 7. 回滚

| 想回滚什么 | 怎么做 |
|---|---|
| 回滚 cron 调度到旧行为 | `mv /etc/cron.d/migao-tls-renew /etc/cron.d/migao-tls-renew.disabled`（或删掉该文件），再按 §4 把 `--replace-legacy-cron` 备份的 `/var/backups/crontab-*.bak` 用 `crontab <文件>` 恢复 |
| 回滚证书（重签出问题） | 证书文件不删：`ls /etc/letsencrypt/live/migao/`；`archive/` 下保留历史版本。确认后可把 `live/migao/` 指回之前的 `archive/<时间戳>/`（`live` 是软链），再 `docker compose exec -T nginx nginx -s reload` |
| 回滚被移出的陈旧 lineage | `mv /etc/letsencrypt/renewal-disabled/api.migaozn.com.conf /etc/letsencrypt/renewal/`（文件一直在） |
| 回滚判红接线 | 把 `.github/workflows/post-merge-verify.yml` 的 `TLS 证书到期判红` 步移除 —— **注意**：`tests/unit_ci_workflows/test_tls_renewal.py` 会当场判红（「摘掉接线 ⇒ 红」），这是有意的 |
| 回滚部署脚本改动 | `deploy/swas/deploy.sh` 的两处改动都是**增量**：`2.6.1` 段与配置同步里的 `[ -f src/deploy/scripts/tls-renew.sh ]` 守卫。回滚到更早的 tag 时该文件不存在，守卫会跳过（**不会**让回滚部署 abort） |

## 8. 影响面（写清楚，避免误判）

- **四个域名（`api` / `ai-api` / `app` / `migaozn.com`）的 HTTPS 全部受影响**：证书过期后浏览器、
  curl、以及任何走 HTTPS 的客户端（含 admin-web / H5 / 小程序后端调用）都会直接报证书错误。
- **Windows / Android 客户端与终端不受影响** —— 它们的通信是「App/浏览器 → 四域 HTTPS」，
  证书过期伤的是**服务端到客户端这一段握手**，不是操作系统或设备本身；
  桌面端 / 移动端要做的只有一件事：**不要**在过期后「继续访问」并忽略证书告警。
- 未被 nginx 使用的 `api.migaozn.com` lineage **不影响**四域 HTTPS（它只是污染 `certbot renew` 的退出码）。
- 本单**不改** CA / 不动 TLS 协议档；**SAN 集合的变更（去掉 `admin`）是已裁定的例外**，见 §3。

## 9. 复算与验证清单（交付时逐条跑）

```bash
# ① 判据本体（零网络；PATH 垫片伪造 openssl / certbot / docker / crontab）
python3 -m pytest tests/unit_ci_workflows/test_tls_renewal.py -q

# ② 现网到期读数（真网络；每域 notAfter + 剩余天数 + 复算命令）
bash deploy/scripts/tls-expiry-check.sh; echo "rc=$?"

# ③ 续期通路（**只验通路，不真续**）
bash deploy/scripts/tls-renew.sh --dry-run; echo "rc=$?"

# ④ cron 就位与不双跑
cat /etc/cron.d/migao-tls-renew; crontab -l | grep -c 'certbot renew'

# ⑤ 接线在（main 侧，摘掉该步 ⇒ 本条判红）
python3 -m pytest tests/unit_ci_workflows/test_tls_renewal.py -q -k wiring
```
