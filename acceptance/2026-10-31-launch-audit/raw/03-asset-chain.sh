#!/usr/bin/env bash
# 只读：抓首页 HTML，抽出静态资产 URL，逐个 GET 状态码（白屏/产物不完整的第一现场）
set -uo pipefail
probe() {
  local url="$1"; local page="$2"
  html=$(curl -sS --max-time 20 "$url")
  echo "### $page  ($url)  html_bytes=${#html}"
  assets=$(printf '%s' "$html" | grep -oE '(src|href)="[^"]+"' | sed 's/^[a-z]*="//; s/"$//' | grep -E '\.(js|css|mjs|woff2?|png|svg|ico)' | sort -u)
  n=0; bad=0
  for a in $assets; do
    case "$a" in
      http*) u="$a" ;;
      /*) u="$(printf '%s' "$url" | sed -E 's#(^https?://[^/]+).*#\1#')$a" ;;
      *) u="$(printf '%s' "$url" | sed -E 's#[^/]*$##')$a" ;;
    esac
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$u")
    n=$((n+1)); [ "$code" = "200" ] || { bad=$((bad+1)); echo "  FAIL $code $u"; }
  done
  echo "  assets=$n non200=$bad"
}
probe "https://merchant.migaozn.com/login" "admin-web /login"
probe "https://app.migaozn.com/" "C端元元 H5 /"
probe "https://app.migaozn.com/b/" "bmini H5 /b/"
probe "https://app.migaozn.com/w/" "worker-h5 /w/"
