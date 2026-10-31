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
| `admin.migaozn.com` **没有 A 记录** | `dig +short admin.migaozn.com` 空；其余 7 个 SAN 都解析到 `121.40.28.213` ⇒ 主证书的 HTTP-01 对 `admin` **必失败** ⇒ **整张证书续期失败** |
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

## 3. 一次性修复：两条可选路径（**都要人执行；本单未执行**）

> 根因 = `migao` 证书的 SAN 里有 `admin.migaozn.com`，而该域名**没有 A 记录** ⇒ HTTP-01 必失败。
> 两条路都能修，代价不同，**必须人选**。

### 路径 ①（推荐，不动 SAN）：给 `admin.migaozn.com` 补 A 记录

```bash
# 在权威 DNS 上加一条：admin.migaozn.com.  A  121.40.28.213（与其余 7 个 SAN 同 IP）
dig +short admin.migaozn.com          # 期望 121.40.28.213；先等 TTL 生效
# 然后用同一张证书原样续期（webroot 已由 nginx 提供 /.well-known/acme-challenge/）：
cd /opt/migao-deploy && bash /opt/migao-deploy/tls-renew.sh --dry-run   # 先验通路，不真续
cd /opt/migao-deploy && bash /opt/migao-deploy/tls-renew.sh             # 真续 + reload nginx
```

代价：**依赖外部输入**（DNS 是第三方面，本仓改不了）；好处：**SAN 集合不变**，`admin` 站点将来要上线时不需要再动证书。

### 路径 ②（不补 DNS）：重签，**显式只带 7 个可解析 SAN**（去掉 `admin`）

```bash
# ⚠️ 这会**改变证书的 SAN 集合**（少一个 admin.migaozn.com）—— 本单的边界是「不改域名集合」，
#    所以这条路是**需人裁定的例外**，不默认执行；裁定人：技术负责人。
cd /opt/migao-deploy
certbot certonly --cert-name migao \
  -d migaozn.com -d www.migaozn.com -d api.migaozn.com -d ai-api.migaozn.com \
  -d app.migaozn.com -d merchant.migaozn.com -d ops.migaozn.com \
  --webroot -w /opt/migao-deploy/certbot-www --expand --non-interactive
docker compose exec -T nginx nginx -s reload
```

代价：`admin.migaozn.com` **不再在证书里** —— 将来要用该子域，必须再加 DNS 后重新 `--expand`；
好处：不再依赖 DNS 变更，当天即可闭环。
（`--expand` 的作用：`cert-name` 已存在且域名集合变化时**扩/改同一个 lineage**，不新建第二张证书。）

### 落地后自证（两条路都要跑）

```bash
openssl s_client -connect api.migaozn.com:443 -servername api.migaozn.com </dev/null 2>/dev/null \
  | openssl x509 -noout -dates -subject
bash /opt/migao-deploy/tls-renew.sh --dry-run    # 期望 rc=0 且无 challenge 失败
bash deploy/scripts/tls-expiry-check.sh          # 期望 rc=0、四个域 status=ok
```

## 4. cron 加固（把「整断」换成 reload + 可观测）

现状那条 crontab 用 `docker compose restart nginx`（**整断**在途请求），且失败没有任何非零信号被谁消费。
本单把它收敛成 `deploy/scripts/tls-renew.sh`（日志 `/var/log/migao-tls-renew.log`，失败**非零退出**）：

```bash
# ① 先看会不会双跑（既有 crontab 条目会让同一条续期一天跑两遍）
crontab -l | grep 'certbot renew'

# ② 备份并替换：把旧条目移出 crontab（备份到 /var/backups），装 /etc/cron.d/migao-tls-renew
bash /opt/migao-deploy/tls-renew.sh --install-cron --replace-legacy-cron

# ③ 复核（三段读数都要看）
cat /etc/cron.d/migao-tls-renew          # 每天 03:00，调用 tls-renew.sh，日志落 /var/log/migao-tls-renew.log
crontab -l                               # 旧的那条 certbot renew 应该已不在
ls -l /var/backups/crontab-*.bak         # 被移出的原条目留档
systemctl is-active cron                 # 宿主没 cron 守护进程 ⇒ 文件就位也不会跑（脚本会打 ⚠️）
```

> 不带 `--replace-legacy-cron` 时，`--install-cron` 检测到既有条目会**拒绝安装**并退 `3`（避免双跑）。
> 部署时 `deploy/swas/deploy.sh` 的 `2.6.1` 会幂等地跑一次 `--install-cron`：**内容未变不重写**；
> 被 guard 跳过时只打 `⚠️`，**不拖垮部署**。
> 脚本里 reload 用 `docker compose exec -T nginx nginx -s reload`，只有 reload 失败才回落 `restart`。

## 5. 陈旧 lineage：**不删证书**的禁用方式

`api.migaozn.com` 这条 lineage 未被 nginx 使用，但它的 renewal conf 与 `--webroot` 冲突，
会让每天的 `certbot renew` **整条**跑失败（即使主证书本来能续）。

```bash
# 方式 A（推荐，可逆、不删任何证书）：把 conf 移出 renewal 目录并留档
mkdir -p /etc/letsencrypt/renewal-disabled
mv /etc/letsencrypt/renewal/api.migaozn.com.conf /etc/letsencrypt/renewal-disabled/
ls /etc/letsencrypt/live/api.migaozn.com/    # 证书文件仍在（不删）

# 方式 B（保留自动续期，但改成 webroot）：把 authenticator/pref_challs 改对
grep -E 'authenticator|pref_challs' /etc/letsencrypt/renewal/api.migaozn.com.conf
# 期望（改后）：authenticator = webroot / pref_challs = http-01,
# 同时补 webroot_path = /opt/migao-deploy/certbot-www
```

**不许**直接 `certbot delete`（会删证书文件）—— 两种方式都保留文件，可随时恢复。
改完复算：`certbot renew --dry-run` 不应再出现那条 `None of the preferred challenges are supported`。

## 6. 失败排查（按日志原文对号入座）

| 日志原文 | 真因 | 处置 |
|---|---|---|
| `None of the preferred challenges are supported by the selected plugin` | 某 lineage 的 `authenticator` / `pref_challs` 与 `--webroot` 冲突 | §5 方式 A 或 B |
| `Some challenges have failed` + 某域名 | 该域名的 HTTP-01 打不通（DNS 缺 A 记录 / 80 被挡 / 网关没放通） | 路径 ①（补 DNS）；`dig +short <域名>` 先自证 |
| `too many failed authorizations` | Let's Encrypt 限流（同域名失败过多） | **停手 1 小时**，别连续重跑 |
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
| 回滚判红接线 | 把 `.github/workflows/post-merge-verify.yml` 的 `TLS 证书到期判红` 步移除 —— **注意**：`tests/unit_ci_workflows/test_tls_renewal.py` 会当场判红（「摘掉接线 ⇒ 红」），这是有意的 |
| 回滚部署脚本改动 | `deploy/swas/deploy.sh` 的两处改动都是**增量**：`2.6.1` 段与配置同步里的 `[ -f src/deploy/scripts/tls-renew.sh ]` 守卫。回滚到更早的 tag 时该文件不存在，守卫会跳过（**不会**让回滚部署 abort） |

## 8. 影响面（写清楚，避免误判）

- **四个域名（`api` / `ai-api` / `app` / `migaozn.com`）的 HTTPS 全部受影响**：证书过期后浏览器、
  curl、以及任何走 HTTPS 的客户端（含 admin-web / H5 / 小程序后端调用）都会直接报证书错误。
- **Windows / Android 客户端与终端不受影响** —— 它们的通信是「App/浏览器 → 四域 HTTPS」，
  证书过期伤的是**服务端到客户端这一段握手**，不是操作系统或设备本身；
  桌面端 / 移动端要做的只有一件事：**不要**在过期后「继续访问」并忽略证书告警。
- 未被 nginx 使用的 `api.migaozn.com` lineage **不影响**四域 HTTPS（它只是污染 `certbot renew` 的退出码）。
- 本单**不改**证书域名集合 / 不换 CA / 不动 TLS 协议档；路径 ② 是**需人裁定**的例外（见 §3）。

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
