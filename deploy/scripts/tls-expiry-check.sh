#!/usr/bin/env bash
# TLS 证书到期检查（**只读**；issue #8201）
#
# 为什么要它：四个域名共用一张 Let's Encrypt 证书（CN=migaozn.com，SAN 含
# admin/ai-api/api/app/merchant/migaozn/ops/www），而**仓内没有任何到期判据** ——
# 2026-11-27 到期这件事只能靠人去跑 openssl 才知道（本单的起点就是这么发现的）。
#
# 判据（三态，**3 不当 0 读**）：
#   0 = 全部域名的证书都读到了、且剩余天数 >= 阈值（默认 21 天，LE 的 30 天续期窗口之内）
#   1 = 有**确定的问题**：临期（<阈值）/ 已过期 / 证书 SAN 不覆盖该域名
#   3 = **无法判定**：取不到证书或解析不了（网络 / DNS / openssl 缺失）—— 绝不当成「通过」
#
# 输出（两条面）：
#   · 人读面：逐域的 notAfter + 剩余天数 + **可复制的复算命令**（结论必须能被复核）
#   · 机读面：`TLS_EXPIRY domain=… status=… days_left=…` / `TLS_EXPIRY_SUMMARY rc=…`
#     与 `TLS_LINEAGE …` / `TLS_LINEAGE_SUMMARY …`（certbot lineage 诊断，只在宿主机上读得到）
#
# 用法：
#   bash deploy/scripts/tls-expiry-check.sh                    # 默认四域
#   bash deploy/scripts/tls-expiry-check.sh --with-www         # 再加 www.migaozn.com
#   bash deploy/scripts/tls-expiry-check.sh --warn-days 30     # 改阈值
#   bash deploy/scripts/tls-expiry-check.sh api.example.com    # 指定域名（覆盖默认集）
#
# 注入点（判据用；沿用 `NCI_GH_BIN` / `TLS_*` 先例）：
#   TLS_WARN_DAYS   阈值（默认 21）
#   TLS_OPENSSL_BIN openssl 路径（默认 PATH 里的 openssl）
#   TLS_CERTBOT_BIN certbot 路径（默认 PATH 里的 certbot）
#   TLS_LE_DIR      letsencrypt 目录（默认 /etc/letsencrypt；不存在 ⇒ lineage 读数 skipped）
#   TLS_NGINX_CONF  nginx.conf（用来判「哪条 lineage 真被 nginx 使用」，默认仓内 deploy/swas/nginx.conf）
#   TLS_NOW_EPOCH   「现在」的 epoch（默认 `date -u +%s`；只判据用，生产不需要）
#
# ⚠️ 本脚本**只读**：不续期、不写证书目录、不改 nginx。
set -uo pipefail

WARN_DAYS=${TLS_WARN_DAYS:-21}
OPENSSL_BIN=${TLS_OPENSSL_BIN:-openssl}
CERTBOT_BIN=${TLS_CERTBOT_BIN:-certbot}
LE_DIR=${TLS_LE_DIR:-/etc/letsencrypt}
PORT=${TLS_PORT:-443}
NOW_EPOCH=${TLS_NOW_EPOCH:-}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
NGINX_CONF=${TLS_NGINX_CONF:-${SCRIPT_DIR}/../swas/nginx.conf}

DEFAULT_DOMAINS="api.migaozn.com ai-api.migaozn.com app.migaozn.com migaozn.com"
WITH_WWW=0
DOMAINS=""

usage() {
  sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --with-www)
      WITH_WWW=1
      shift
      ;;
    --warn-days)
      if [ "$#" -lt 2 ]; then
        echo "❌ --warn-days 缺少参数" >&2
        exit 2
      fi
      WARN_DAYS=$2
      shift 2
      ;;
    --warn-days=*)
      WARN_DAYS=${1#--warn-days=}
      shift
      ;;
    -*)
      echo "❌ 未知参数：${1}（--help 看用法）" >&2
      exit 2
      ;;
    *)
      DOMAINS="${DOMAINS} ${1}"
      shift
      ;;
  esac
done

if ! printf '%s' "$WARN_DAYS" | grep -Eq '^[0-9]+$'; then
  echo "❌ --warn-days 必须是正整数（实测：${WARN_DAYS}）" >&2
  exit 2
fi

if [ -z "$DOMAINS" ]; then
  DOMAINS=$DEFAULT_DOMAINS
  if [ "$WITH_WWW" = "1" ]; then
    DOMAINS="${DOMAINS} www.migaozn.com"
  fi
fi

now_epoch() {
  if [ -n "$NOW_EPOCH" ]; then
    printf '%s' "$NOW_EPOCH"
    return 0
  fi
  date -u +%s
}

# `Nov 27 10:29:18 2026 GMT`（openssl 的 notAfter）与 `2026-11-27 10:29:18` 两种形态都认。
# 只用 `date`（GNU `-d` / BSD `-j -f` 两条路），**不引入 python / perl 依赖**。
to_epoch() {
  local text="$1" out
  [ -n "$text" ] || return 1
  # openssl 的 notAfter 形如 `Nov 27 10:29:18 2026 GMT`（已是 UTC）⇒ 去掉尾部时区名再按 UTC 解析。
  text=${text% GMT}
  # ⚠️ `LC_ALL=C` 不是修饰：BSD date 在非 C locale 下解析月份名会失败（本机实测
  # `date -j -f '%b %d %T %Y' "Nov 27 …"` 报 illegal time format，加 LC_ALL=C 立刻成功）。
  out=$(LC_ALL=C date -u -d "$text" +%s 2>/dev/null) && { printf '%s' "$out"; return 0; }
  out=$(LC_ALL=C date -u -j -f '%b %d %T %Y' "$text" +%s 2>/dev/null) && { printf '%s' "$out"; return 0; }
  out=$(LC_ALL=C date -u -j -f '%Y-%m-%d %H:%M:%S' "$text" +%s 2>/dev/null) && { printf '%s' "$out"; return 0; }
  return 1
}

lc() {
  printf '%s' "$1" | tr 'A-Z' 'a-z'
}

CERT_NOT_AFTER=""
CERT_SAN=""

# 取一次 PEM，再问两次 openssl（dates / SAN）。任何一步取不到 ⇒ 返回 1（调用方判 3）。
read_cert() {
  local host="$1" pem dates san
  CERT_NOT_AFTER=""
  CERT_SAN=""
  pem=$("$OPENSSL_BIN" s_client -connect "${host}:${PORT}" -servername "$host" </dev/null 2>/dev/null) || true
  [ -n "$pem" ] || return 1
  dates=$("$OPENSSL_BIN" x509 -noout -dates <<<"$pem" 2>/dev/null) || true
  CERT_NOT_AFTER=$(printf '%s\n' "$dates" | sed -n 's/^notAfter=//p' | head -1)
  san=$("$OPENSSL_BIN" x509 -noout -ext subjectAltName <<<"$pem" 2>/dev/null) || true
  if [ -z "$san" ]; then
    # openssl 1.0 / LibreSSL 老版本没有 `-ext`：退回 `-text` 里抽 DNS 名。
    san=$("$OPENSSL_BIN" x509 -noout -text <<<"$pem" 2>/dev/null) || true
  fi
  CERT_SAN=$(printf '%s\n' "$san" | tr ',' '\n' \
    | sed -n 's/.*\(DNS:[A-Za-z0-9.*_-][A-Za-z0-9.*_-]*\).*/\1/p' | tr '\n' ' ')
  [ -n "$CERT_NOT_AFTER" ]
}

# `*.migaozn.com` 只覆盖**一级**标签：api.migaozn.com ✓ / migaozn.com ✗。
san_covers() {
  local host prefix token pat
  host=$(lc "$1")
  for token in $CERT_SAN; do
    token=$(lc "${token#DNS:}")
    if [ "$token" = "$host" ]; then
      return 0
    fi
    case "$token" in
      \*.*)
        pat=${token#\*.}
        case "$host" in
          *."${pat}")
            prefix=${host%.*}
            case "$prefix" in
              *.*) : ;;
              *) return 0 ;;
            esac
            ;;
        esac
        ;;
    esac
  done
  return 1
}

# 哪些 lineage 真被 nginx 使用（从 nginx.conf 的 `ssl_certificate .../live/<name>/fullchain.pem` 现取）
used_lineages() {
  [ -f "$NGINX_CONF" ] || return 1
  sed -n 's#.*/live/\([^/]*\)/fullchain\.pem.*#\1#p' "$NGINX_CONF" | sort -u | tr '\n' ' '
}

# renewal conf 会不会让 `certbot renew --webroot` 当场失败（issue #8201 的真因之一：
# `authenticator=manual` + `pref_challs=dns-01` 与 cron 全局的 `--webroot` 冲突）。
renew_hazard_of() {
  local name="$1" conf auth chall problems
  conf="${LE_DIR}/renewal/${name}.conf"
  if [ ! -f "$conf" ]; then
    printf 'none'
    return 0
  fi
  auth=$(sed -n 's/^[[:space:]]*authenticator[[:space:]]*=[[:space:]]*\([A-Za-z0-9_-]*\).*/\1/p' "$conf" | head -1)
  chall=$(sed -n 's/^[[:space:]]*pref_challs[[:space:]]*=[[:space:]]*\(.*\)/\1/p' "$conf" | head -1)
  problems=""
  case "$auth" in
    ''|webroot) : ;;
    *) problems="${problems}authenticator=${auth} " ;;
  esac
  case "$chall" in
    ''|*http-01*) : ;;
    *) problems="${problems}pref_challs=${chall} " ;;
  esac
  if [ -z "$problems" ]; then
    printf 'none'
  else
    printf '%s' "$problems"
  fi
}

lineage_report() {
  local out rc name expiry days used hazards names used_names total=0 hazards_n=0
  echo ''
  echo '── certbot lineage（宿主机诊断；issue #8201）──'
  if [ ! -d "$LE_DIR" ]; then
    echo "TLS_LINEAGE_SUMMARY status=skipped reason=no_letsencrypt_dir path=${LE_DIR}"
    echo "   ⏭️ lineage 读数**缺失**：本机没有 ${LE_DIR}（多半不是宿主机）—— 这不等于「证书没问题」"
    return 0
  fi
  out=$("$CERTBOT_BIN" certificates 2>/dev/null)
  rc=$?
  if [ "$rc" != '0' ] || [ -z "$out" ]; then
    echo "TLS_LINEAGE_SUMMARY status=skipped reason=certbot_unavailable"
    echo "   ⏭️ lineage 读数**缺失**：${CERTBOT_BIN} certificates 取不到（rc=${rc}）—— 这不等于「证书没问题」"
    return 0
  fi
  used_names=$(used_lineages || true)
  if [ -z "$used_names" ]; then
    echo "   ℹ️ 未取到 nginx.conf 的 ssl_certificate（used=unknown）—— 不影响域名面判据：${NGINX_CONF}"
  fi
  name=""
  days=""
  while IFS= read -r line; do
    case "$line" in
      *'Certificate Name: '*)
        if [ -n "$name" ]; then
          print_lineage "$name" "$days" "$used_names" || hazards_n=$((hazards_n + 1))
          total=$((total + 1))
        fi
        name=${line##*Certificate Name: }
        name=${name%% *}
        days="unknown"
        ;;
      *'Expiry Date: '*)
        case "$line" in
          *'INVALID: EXPIRED'*) days='expired' ;;
          *'VALID: '*)
            days=${line##*VALID: }
            days=${days%% day*}
            ;;
        esac
        ;;
      *) : ;;
    esac
  done <<<"$out"
  if [ -n "$name" ]; then
    total=$((total + 1))
    if ! print_lineage "$name" "$days" "$used_names"; then
      hazards_n=$((hazards_n + 1))
    fi
  fi
  echo "TLS_LINEAGE_SUMMARY status=ok total=${total} used=${used_names:-unknown} hazards=${hazards_n}"
  return 0
}

# 逐 lineage 一行机读 + 一行人读。返回 1 表示该 lineage 有需要人看的红线（hazard）。
print_lineage() {
  local name="$1" days="$2" used_names="$3" status used hazard
  hazard=$(renew_hazard_of "$name")
  case "$days" in
    expired) status='expired' ;;
    unknown) status='unknown' ;;
    *) if [ "$days" -lt "$WARN_DAYS" ] 2>/dev/null; then status='expiring'; else status='ok'; fi ;;
  esac
  if [ -z "$used_names" ]; then
    used='unknown'
  else
    case " ${used_names} " in
      *" ${name} "*) used='yes' ;;
      *) used='no' ;;
    esac
  fi
  echo "TLS_LINEAGE name=${name} status=${status} days_left=${days} used=${used} renew_hazard=${hazard%% }"
  echo "   剩余天数=${days}（阈值 ${WARN_DAYS}）· nginx 在用=${used} · renewal conf 冲突=${hazard:-none}"
  case "$used" in
    no)
      echo "   ⚠️ 这条 lineage **未被 nginx 使用**（nginx 用的是 live/${used_names:-?}）—— 它到期不影响四域 HTTPS，"
      echo "      但它会让每天的 \`certbot renew\` 整条跑失败 ⇒ 处置见 docs/deployment/tls-renewal.md 的「陈旧 lineage」"
      ;;
    *) : ;;
  esac
  if [ "$hazard" != 'none' ] && [ -n "$hazard" ]; then
    echo "   ⚠️ renewal conf 与 webroot 续期**冲突**（${hazard% }）⇒ 该 lineage 每天必失败（日志原文："
    echo "      None of the preferred challenges are supported by the selected plugin）"
    return 1
  fi
  return 0
}

NOW=$(now_epoch)
echo '=============================================================='
echo "TLS 证书到期检查（只读；issue #8201）阈值 ${WARN_DAYS} 天 · now_epoch=${NOW} · port=${PORT}"
echo '=============================================================='

count_ok=0
count_expiring=0
count_expired=0
count_mismatch=0
count_unknown=0

for domain in $DOMAINS; do
  echo ''
  echo "── ${domain} ──"
  if ! read_cert "$domain"; then
    count_unknown=$((count_unknown + 1))
    echo "TLS_EXPIRY domain=${domain} status=unknown days_left=unknown not_after_epoch=unknown"
    echo "   ❌ **无法判定**：取不到证书（DNS / 网络 / 443 / 证书链）—— 3 不当 0 读"
    echo "   复算：openssl s_client -connect ${domain}:${PORT} -servername ${domain} </dev/null 2>/dev/null | openssl x509 -noout -dates"
    continue
  fi
  end=$(to_epoch "$CERT_NOT_AFTER" || true)
  if [ -z "$end" ]; then
    count_unknown=$((count_unknown + 1))
    echo "TLS_EXPIRY domain=${domain} status=unknown days_left=unknown not_after_epoch=unknown"
    echo "   ❌ **无法判定**：notAfter 解析不了（原文：${CERT_NOT_AFTER}）—— 3 不当 0 读"
    echo "   复算：openssl s_client -connect ${domain}:${PORT} -servername ${domain} </dev/null 2>/dev/null | openssl x509 -noout -dates"
    continue
  fi
  days=$(( (end - NOW) / 86400 ))
  status='ok'
  if [ "$end" -le "$NOW" ]; then
    status='expired'
    count_expired=$((count_expired + 1))
  elif ! san_covers "$domain"; then
    status='mismatch'
    count_mismatch=$((count_mismatch + 1))
  elif [ "$days" -lt "$WARN_DAYS" ]; then
    status='expiring'
    count_expiring=$((count_expiring + 1))
  else
    count_ok=$((count_ok + 1))
  fi
  echo "TLS_EXPIRY domain=${domain} status=${status} days_left=${days} not_after_epoch=${end}"
  echo "   notAfter=${CERT_NOT_AFTER}（UTC）"
  echo "   剩余天数=${days}（阈值 ${WARN_DAYS} 天）· SAN=${CERT_SAN:-（空）}"
  case "$status" in
    expired)
      echo "   ❌ **已过期**：该域名的 HTTPS 已经不受信任（浏览器/客户端会直接报错）"
      ;;
    mismatch)
      echo "   ❌ **证书域名不匹配**：这张证书的 SAN 不含 ${domain}（配错证书 / 域名迁移没跟上）"
      ;;
    expiring)
      echo "   ❌ **临期**：剩余 ${days} 天 < 阈值 ${WARN_DAYS} 天 —— LE 的 30 天续期窗口早该续上了，"
      echo "      说明自动续期**在失败**（处置：docs/deployment/tls-renewal.md）"
      ;;
    *) : ;;
  esac
  echo "   复算：openssl s_client -connect ${domain}:${PORT} -servername ${domain} </dev/null 2>/dev/null | openssl x509 -noout -dates"
done

lineage_report

if [ "$count_expiring" -gt 0 ] || [ "$count_expired" -gt 0 ] || [ "$count_mismatch" -gt 0 ]; then
  RC=1
elif [ "$count_unknown" -gt 0 ]; then
  RC=3
else
  RC=0
fi

echo ''
echo "TLS_EXPIRY_SUMMARY rc=${RC} checked=$((count_ok + count_expiring + count_expired + count_mismatch + count_unknown)) ok=${count_ok} expiring=${count_expiring} expired=${count_expired} mismatch=${count_mismatch} unknown=${count_unknown} threshold_days=${WARN_DAYS}"
if [ "$RC" = '1' ]; then
  echo '❌ 判红：证书临期 / 过期 / 域名不匹配 ⇒ 处置 runbook：docs/deployment/tls-renewal.md'
elif [ "$RC" = '3' ]; then
  echo '⚠️ **无法判定**（rc=3）：取不到或解析不了 —— 这不是「通过」，先修环境/网络再判'
else
  echo "✅ 全部域名剩余 >= ${WARN_DAYS} 天且 SAN 覆盖"
fi
exit "$RC"
