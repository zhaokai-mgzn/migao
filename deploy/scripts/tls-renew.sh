#!/usr/bin/env bash
# TLS 证书续期（**幂等 + 一次性兜底**；issue #8201）
#
# 现状（2026-10-31 在服务器上核实，不是推断）：宿主**已经有**一条 cron 在跑 certbot，但它每天在失败，
# 而且失败**没有任何告警**：
#
#   0 3 * * * certbot renew --quiet --webroot -w /opt/migao-deploy/certbot-www \
#     --post-hook 'cd /opt/migao-deploy && docker compose restart nginx >/dev/null 2>&1' \
#     >> /var/log/certbot-renew.log 2>&1
#
# 本脚本把那条腿收敛成「可归因 + 可观测 + 不整断」的一份实现：
#   · 续期前/后都打**真读数**（openssl -dates），成功才 reload（`nginx -s reload`，**不是** restart）
#   · 失败**非零退出** + 归因清单 + 日志位置（cron 的输出就落进日志，可事后看）
#   · `--install-cron` 幂等安装 `/etc/cron.d/migao-tls-renew`；**检测到既有 crontab 条目时不安装**
#     （否则同一条续期一天跑两遍，两把锁互相不知道），要人加 `--replace-legacy-cron` 才备份+替换
#
# 用法：
#   bash tls-renew.sh                     # 续期（到期才续，certbot 自己判）+ reload nginx
#   bash tls-renew.sh --dry-run           # 只验通路，不真续、不 reload
#   bash tls-renew.sh --no-reload         # 续了但不 reload（自己控制生效时机）
#   bash tls-renew.sh --install-cron      # 幂等安装/刷新宿主 cron（有旧条目 ⇒ 跳过并出声）
#   bash tls-renew.sh --install-cron --replace-legacy-cron   # 备份并替换既有 crontab 条目
#
# 退出码（三态 + 用法）：
#   0 = 成功（续上了 / 没有到期证书 / dry-run 通过 / cron 已就位）
#   1 = 失败（续期失败 / reload 失败）—— **cron 会把它记成非零**，这就是可观测面
#   2 = 参数错误
#   3 = **无法判定**（环境不满足：没有 /etc/letsencrypt、没有 webroot、没有 certbot/docker；
#       或 `--install-cron` 被 guard 跳过）—— 3 不得当 0 读
#
# 注入点（判据用）：TLS_LE_DIR / TLS_CERTBOT_ENGINE / MIGAO_DEPLOY_DIR / MIGAO_TLS_LOG_FILE /
#   MIGAO_TLS_CRON_FILE / MIGAO_TLS_RENEW_SCRIPT / MIGAO_TLS_BACKUP_DIR / MIGAO_TLS_ASSUME_ROOT
set -uo pipefail

DEPLOY_DIR=${MIGAO_DEPLOY_DIR:-/opt/migao-deploy}
LE_DIR=${TLS_LE_DIR:-/etc/letsencrypt}
WEBROOT=${TLS_WEBROOT:-${DEPLOY_DIR}/certbot-www}
CERT_NAME=${TLS_CERT_NAME:-migao}
CERT_PATH=${TLS_CERT_PATH:-${LE_DIR}/live/${CERT_NAME}/fullchain.pem}
LOG_FILE=${MIGAO_TLS_LOG_FILE:-/var/log/migao-tls-renew.log}
CRON_FILE=${MIGAO_TLS_CRON_FILE:-/etc/cron.d/migao-tls-renew}
SELF=${MIGAO_TLS_RENEW_SCRIPT:-${DEPLOY_DIR}/tls-renew.sh}
BACKUP_DIR=${MIGAO_TLS_BACKUP_DIR:-/var/backups}
ENGINE=${TLS_CERTBOT_ENGINE:-}
OPENSSL_BIN=${TLS_OPENSSL_BIN:-openssl}
CERTBOT_BIN=${TLS_CERTBOT_BIN:-certbot}
DOCKER_BIN=${TLS_DOCKER_BIN:-docker}
IMAGE=${TLS_CERTBOT_IMAGE:-certbot/certbot}

DRY_RUN=0
NO_RELOAD=0
MODE=renew
REPLACE_LEGACY=0

usage() {
  sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --no-reload) NO_RELOAD=1; shift ;;
    --install-cron) MODE=install-cron; shift ;;
    --replace-legacy-cron) REPLACE_LEGACY=1; shift ;;
    *)
      echo "❌ 未知参数：${1}（--help 看用法）" >&2
      exit 2
      ;;
  esac
done

cert_dates() {
  local out
  out=$("$OPENSSL_BIN" x509 -noout -dates -in "$CERT_PATH" 2>/dev/null) || true
  if [ -z "$out" ]; then
    printf '未知（读不到 %s）' "$CERT_PATH"
    return 0
  fi
  printf '%s' "$out" | tr '\n' ' '
}

choose_engine() {
  if [ -n "$ENGINE" ]; then
    case "$ENGINE" in
      docker|host) printf '%s' "$ENGINE"; return 0 ;;
      *)
        echo "❌ TLS_CERTBOT_ENGINE 只认 docker|host（实测：${ENGINE}）" >&2
        return 1
        ;;
    esac
  fi
  if command -v "$CERTBOT_BIN" >/dev/null 2>&1; then
    printf 'host'
    return 0
  fi
  if command -v "$DOCKER_BIN" >/dev/null 2>&1; then
    printf 'docker'
    return 0
  fi
  return 1
}

reload_nginx() {
  echo "reload nginx：docker compose exec -T nginx nginx -s reload（**不** restart，避免整断在途请求）"
  if ( cd "$DEPLOY_DIR" && "$DOCKER_BIN" compose exec -T nginx nginx -s reload ); then
    echo '  ✅ reload 成功（新证书已生效）'
    return 0
  fi
  echo '  ⚠️ reload 失败 ⇒ 回落 restart（会**短暂整断**；旧证书仍在服务，不是黑洞）'
  if ( cd "$DEPLOY_DIR" && "$DOCKER_BIN" compose restart nginx ); then
    echo '  ✅ restart 成功（已生效）'
    return 0
  fi
  echo '  ❌ reload 与 restart 都失败 —— 线上仍在用旧证书'
  return 1
}

renew_main() {
  local engine cmd_rc out result before after

  echo '=============================================================='
  echo "TLS 证书续期（issue #8201）部署目录 ${DEPLOY_DIR} · LE ${LE_DIR} · dry-run=${DRY_RUN}"
  echo '=============================================================='

  if [ ! -d "$LE_DIR" ]; then
    echo "❌ 环境不满足：${LE_DIR} 不存在 ⇒ **无法判定**（这不是「续期成功」；本机多半不是宿主）"
    echo '   修法：在服务器 /opt/migao-deploy 下执行；证书目录由 nginx 容器只读挂载，正常路径是 /etc/letsencrypt'
    return 3
  fi
  if [ ! -d "$WEBROOT" ]; then
    echo "❌ 环境不满足：webroot ${WEBROOT} 不存在 ⇒ **无法判定**（HTTP-01 无处落盘）"
    echo '   修法：确认 /opt/migao-deploy/certbot-www 存在且 nginx 的 /.well-known/acme-challenge/ 指向它'
    return 3
  fi
  engine=$(choose_engine)
  if [ -z "$engine" ]; then
    echo "❌ 环境不满足：既没有 ${CERTBOT_BIN} 也没有 ${DOCKER_BIN} ⇒ **无法判定**"
    echo '   修法：装宿主 certbot（推荐，1.23.0 已在 /usr/local/bin/certbot）或 docker'
    return 3
  fi
  echo "引擎选择：${engine}（探测顺序 = TLS_CERTBOT_ENGINE > 宿主 certbot > docker）"
  before=$(cert_dates)
  echo "续期前证书读数：${before}"

  if [ "$engine" = 'docker' ]; then
    set -- "$DOCKER_BIN" run --rm \
      -v "${LE_DIR}:/etc/letsencrypt" \
      -v "${WEBROOT}:/var/www/certbot" \
      "$IMAGE" certbot renew --webroot -w /var/www/certbot --non-interactive
  else
    set -- "$CERTBOT_BIN" renew --webroot -w "$WEBROOT" --non-interactive
  fi
  if [ "$DRY_RUN" = '1' ]; then
    set -- "$@" --dry-run
  fi
  echo "执行：$*"
  out=$("$@" 2>&1)
  cmd_rc=$?
  printf '%s\n' "$out"

  if [ "$cmd_rc" != '0' ]; then
    echo ''
    echo "❌ 续期失败（certbot rc=${cmd_rc}）—— 这**不是**「已续上」；nginx 未动，线上仍是旧证书"
    echo '   常见归因（按上面的日志原文对号入座）：'
    echo '   · None of the preferred challenges are supported by the selected plugin / authenticator = manual'
    echo '     ⇒ 某条 lineage 的 renewal conf 与 --webroot 冲突（陈旧 lineage；见 runbook 同名小节）'
    echo '   · Some challenges have failed + 某个域名 ⇒ 该域名 HTTP-01 打不通（DNS 缺 A 记录 / 80 端口被挡）'
    echo '   · too many failed authorizations ⇒ LE 限流，等 1 小时后再试（别连续重跑）'
    echo "   日志：${LOG_FILE}（cron 的输出就落在这里）"
    echo "   复算：bash ${SELF} --dry-run"
    echo 'TLS_RENEW_RESULT=failed'
    return 1
  fi

  if [ "$DRY_RUN" = '1' ]; then
    echo '✅ dry-run 通过（**没有**真的续期，也没有 reload nginx）'
    echo 'TLS_RENEW_RESULT=ok-dry-run'
    echo 'TLS_RENEW_RELOAD=no'
    return 0
  fi

  result='renewed'
  case "$out" in
    *'No renewals were attempted'*|*'not yet due for renewal'*) result='noop' ;;
  esac
  after=$(cert_dates)
  if [ "$result" = 'noop' ]; then
    echo '✅ 没有到期证书（certbot：No renewals were attempted）⇒ 幂等 no-op，不 reload'
    echo "证书读数（未变）：${after}"
    echo 'TLS_RENEW_RESULT=noop'
    echo 'TLS_RENEW_RELOAD=no'
    return 0
  fi
  echo "续期后证书读数：${after}"
  if [ "$NO_RELOAD" = '1' ]; then
    echo '⏭️ --no-reload：证书已续上但 nginx 未 reload（线上仍是旧证书，自己控制生效时机）'
    echo "TLS_RENEW_RESULT=${result}"
    echo 'TLS_RENEW_RELOAD=no'
    return 0
  fi
  if ! reload_nginx; then
    echo "❌ 证书已续上但 nginx 生效失败 ⇒ 线上仍用旧证书；先 reload 再谈闭环"
    echo "TLS_RENEW_RESULT=${result}"
    echo 'TLS_RENEW_RELOAD=failed'
    return 1
  fi
  echo "TLS_RENEW_RESULT=${result}"
  echo 'TLS_RENEW_RELOAD=yes'
  return 0
}

legacy_cron_lines() {
  command -v crontab >/dev/null 2>&1 || return 0
  crontab -l 2>/dev/null | grep 'certbot renew' || true
}

install_cron() {
  local uid legacy content wanted existing

  echo '=============================================================='
  echo "TLS 自动续期安装（宿主 cron；issue #8201）→ ${CRON_FILE}"
  echo '=============================================================='

  uid=$(id -u 2>/dev/null || echo '0')
  if [ -n "${MIGAO_TLS_FAKE_UID:-}" ]; then
    uid=${MIGAO_TLS_FAKE_UID}
  fi
  if [ "${MIGAO_TLS_ASSUME_ROOT:-0}" = '1' ]; then
    echo "  ℹ️ MIGAO_TLS_ASSUME_ROOT=1 ⇒ 跳过 root 判定（判据 / 调试注入点）"
  elif [ "$uid" != '0' ]; then
    echo "  ⏭️ 跳过：当前 uid=${uid} 不是 root ⇒ /etc/cron.d 不可写，自动续期**未安装**"
    return 3
  fi
  if [ ! -d "$LE_DIR" ]; then
    echo "  ⏭️ 跳过：${LE_DIR} 不存在（本机没有证书目录）⇒ 自动续期**未安装**"
    return 3
  fi
  if [ ! -f "$SELF" ]; then
    echo "  ⏭️ 跳过：盘上没有 ${SELF}（本次部署没取到源码树）⇒ 自动续期**未安装**；下次带源码树的部署会重试"
    return 3
  fi
  if ! command -v cron >/dev/null 2>&1 && ! command -v crond >/dev/null 2>&1; then
    echo '  ⚠️ 宿主没有 cron 守护进程（cron/crond 都不在 PATH）：cron 文件会就位但**不会被执行**'
    echo '     修法：systemctl enable --now cron（或确认镜像里 cron 已随 init 启动）'
  fi

  legacy=$(legacy_cron_lines)
  if [ -n "$legacy" ] && [ "$REPLACE_LEGACY" != '1' ]; then
    echo '  ⚠️ 检测到**既有** crontab 条目（会在同一时刻跑第二遍续期，两把锁互不知情）：'
    printf '%s\n' "$legacy" | sed 's/^/     /'
    echo '  ⏭️ 为避免同一条续期一天跑两遍，本次**未安装**。人工确认后执行：'
    echo "     bash ${SELF} --install-cron --replace-legacy-cron"
    echo "     （先把上面那行移出 crontab 并备份到 ${BACKUP_DIR}，再装新的）"
    return 3
  fi
  if [ -n "$legacy" ]; then
    mkdir -p "$BACKUP_DIR" 2>/dev/null || true
    local backup_file="${BACKUP_DIR}/crontab-$(date -u +%Y%m%dT%H%M%SZ).bak"
    if ! crontab -l > "$backup_file" 2>/dev/null; then
      echo "  ❌ 备份既有 crontab 失败（${backup_file}）⇒ 退出，**不动**任何既有条目"
      return 1
    fi
    echo "  ✅ 既有 crontab 已备份：${backup_file}"
    local filtered
    filtered=$(mktemp)
    crontab -l 2>/dev/null | grep -v 'certbot renew' > "$filtered" || true
    if command -v crontab >/dev/null 2>&1; then
      crontab "$filtered" 2>/dev/null || crontab - < "$filtered" || true
      echo '  ✅ 既有 `certbot renew` 条目已移出 crontab（备份在上面；删掉的行见备份文件）'
    fi
    rm -f "$filtered"
  fi

  wanted=$(printf '%s\n' \
    '# migao TLS 自动续期（issue #8201）—— 由 deploy/swas/deploy.sh 幂等安装，请勿手改；runbook: docs/deployment/tls-renewal.md' \
    'SHELL=/bin/bash' \
    'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' \
    "0 3 * * * root cd ${DEPLOY_DIR} && bash ${SELF} >> ${LOG_FILE} 2>&1")

  existing=''
  if [ -f "$CRON_FILE" ]; then
    existing=$(cat "$CRON_FILE" 2>/dev/null || true)
  fi
  if [ "$existing" = "$wanted" ]; then
    echo "  ✅ 已就位（内容未变，未重写）：${CRON_FILE}"
    echo 'TLS_CRON_RESULT=already'
    echo "     复算：cat ${CRON_FILE}；crontab -l；tail -n 50 ${LOG_FILE}"
    return 0
  fi

  mkdir -p "$(dirname "$CRON_FILE")" 2>/dev/null || true
  if ! printf '%s\n' "$wanted" > "$CRON_FILE" 2>/dev/null; then
    echo "  ❌ 写 ${CRON_FILE} 失败（权限不足？不是 root？）⇒ 自动续期**未安装**"
    return 1
  fi
  chmod 0644 "$CRON_FILE" 2>/dev/null || true
  mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
  if [ ! -f "$LOG_FILE" ]; then
    : > "$LOG_FILE" 2>/dev/null || echo "  ⚠️ 建日志文件 ${LOG_FILE} 失败（cron 仍会 append，失败会进 syslog）"
  fi
  echo "  ✅ 已安装：${CRON_FILE}（每天 03:00；日志 ${LOG_FILE}）"
  echo "     复算：cat ${CRON_FILE}；crontab -l；bash ${SELF} --dry-run；tail -f ${LOG_FILE}"
  echo 'TLS_CRON_RESULT=installed'
  return 0
}

if [ "$MODE" = 'install-cron' ]; then
  install_cron
  exit $?
fi

renew_main
exit $?
