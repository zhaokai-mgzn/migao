#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════
# 生产 5xx 计数窗口（**只读**；上线审计 P0-04，issue #8203）
#
# ## 病（逐条是审计读数，不是推断）
#
# `acceptance/2026-10-31-launch-audit/findings.md` 的 P0-04：仓库内**没有任何告警实现**
# （`.github/workflows/` 无 alert 腿、`deploy/` 无 metrics 配置），线上唯一可信探针是
# `GET /api/version` 200 —— 而 `docs/deployment/production-deployment.md` 的 §5 把
# 「SLS 采集 + 告警（CPU/内存/磁盘/**5xx**/健康检查）触达值班」列为**必须项**。
# ⇒ 5xx 涨了**不会主动惊动任何人**（同一份审计里 P0-02「红 8 次无人处置」、P1-04
# 「成功即红」都是这个缺口的实证）。
#
# ## 判据：一个**窗口**内的 5xx 计数（合成探针，不是 nginx 日志率）
#
# 逐轮（默认 4 轮，轮间 5s ⇒ 窗口 ≈ 15s）对每个面发一次 GET，按响应码分类计数：
#
#   · `2xx` / `3xx` ⇒ ok        （面在应答）
#   · `5xx`        ⇒ 5xx        （**本判据的主角**）
#   · `4xx`        ⇒ other      （面坏了但不是 5xx —— 不在本判据的归因面内，只计数）
#   · 连不上 / `000` ⇒ unknown  （**不得**被当成 5xx，也不得被当成 ok）
#
# 为什么**不**直接读宿主机 nginx access log：CI 在 GitHub 托管 runner 上跑，读
# `/var/log/nginx/access.log` 需要额外的 SSH 凭据（本仓的部署腿走 ACR + RunCommand，
# 探针位**没有** SSH）⇒ 用合成探针能拿到**稳定分母**（= 轮数 × 面数），不需要新凭据、
# 不需要新 schedule（铁律 10：挂在既有 `post-merge-verify` 腿上，见下游接线）。
# 代价（照实登记）：它证明的是**探针窗口内这些面回了多少 5xx**，不是全站 5xx 率
# —— 全站错误率的 SLS/nginx-log 面登记在 docs/deployment/observability-minimum.md 的「未覆盖」。
#
# ## 三态退出码（`3` **不得当 0 读**）
#
# | 码 | 含义 |
# |---|---|
# | 0 | 窗口内 5xx 计数 < 阈值，且每个面都至少回了一次 `2xx/3xx` |
# | 1 | 窗口内 5xx 计数 >= 阈值（**确定的告警**）|
# | 3 | **无法判定**：有面连不上（`000`）/ 没有任何面给出 `2xx`·`3xx` 应答 |
# | 2 | 入参非法（阈值 <= 0 / 轮数为 0 / 面清单为空）—— 配置写错不该长得像「正常」|
#
# `1` 优先于 `3`：**已经确定的 5xx 不该被「另一面探不到」稀释成「不可判定」**。
#
# ## 注入点（判据用；沿用 `PROD_HEADERS_*` / `TLS_*` 先例）
#
#   PROD_5XX_URLS        面清单（空白分隔；默认审计点名的四面）
#   PROD_5XX_THRESHOLD   窗口内 5xx 条数阈值（默认 3）
#   PROD_5XX_ROUNDS      轮数（默认 4）
#   PROD_5XX_INTERVAL    轮间秒数（默认 5；判据里设 0 ⇒ 不 sleep）
#   PROD_5XX_TIMEOUT     单次请求超时秒（默认 15）
#   PROD_5XX_CURL_BIN    curl 路径（默认 PATH 里的 curl；判据喂 stub）
#
# 判据 = tests/unit_ci_workflows/test_prod_alerting.py（三态 + 阈值注入 + 不泄密）
# 接线 = `.github/workflows/post-merge-verify.yml` 的「5xx 计数窗口」步（**不是**新 schedule）
# ══════════════════════════════════════════════════════════════════════════
set -uo pipefail

CURL_BIN=${PROD_5XX_CURL_BIN:-curl}
THRESHOLD=${PROD_5XX_THRESHOLD:-3}
ROUNDS=${PROD_5XX_ROUNDS:-4}
INTERVAL=${PROD_5XX_INTERVAL:-5}
TIMEOUT=${PROD_5XX_TIMEOUT:-15}

# 审计 P0-04 验收标准 1 点名的四面（都必须是线上**真的 200** 的面 —— P1-05 的教训：
# `/actuator/health` 公网 404，拿它当判据地址会永远命中「坏」）。
DEFAULT_URLS="https://api.migaozn.com/api/version
https://merchant.migaozn.com/login
https://app.migaozn.com/b/
https://app.migaozn.com/w/"
URLS=${PROD_5XX_URLS:-$DEFAULT_URLS}

say() { printf '   %s\n' "$*"; }

# ── 入参校验（fail-closed：配置写错不许长得像「正常」）────────────────────────────
is_pos_int() { printf '%s' "$1" | grep -Eq '^[1-9][0-9]*$'; }
is_nonneg_int() { printf '%s' "$1" | grep -Eq '^(0|[1-9][0-9]*)$'; }

if ! is_pos_int "$THRESHOLD"; then
  echo "::error::PROD_5XX_THRESHOLD 必须是正整数（实测：${THRESHOLD}）—— 0 会让「零 5xx」也触发告警"
  echo "PROD-5XX-SUMMARY rc=2 reason=bad_threshold threshold=${THRESHOLD}"
  exit 2
fi
if ! is_pos_int "$ROUNDS"; then
  echo "::error::PROD_5XX_ROUNDS 必须是正整数（实测：${ROUNDS}）"
  echo "PROD-5XX-SUMMARY rc=2 reason=bad_rounds rounds=${ROUNDS}"
  exit 2
fi
if ! is_nonneg_int "$INTERVAL"; then
  echo "::error::PROD_5XX_INTERVAL 必须是非负整数（实测：${INTERVAL}）"
  echo "PROD-5XX-SUMMARY rc=2 reason=bad_interval interval=${INTERVAL}"
  exit 2
fi
if [ -z "$(printf '%s' "$URLS" | tr -d '[:space:]')" ]; then
  echo "::error::面清单为空（PROD_5XX_URLS）—— 没有面可探不等于「没有 5xx」"
  echo "PROD-5XX-SUMMARY rc=2 reason=no_urls"
  exit 2
fi

# 窗口时长 = **轮间**间隔 × (轮数 − 1)：单轮（ROUNDS=1）没有轮间间隔 ⇒ 窗口 0s（不是 INTERVAL）。
# 读数必须与真实行为一致 —— 否则 README/告警里的「≈ Ns 窗口」会骗人。
WINDOW=0
[ "$ROUNDS" -gt 1 ] && WINDOW=$(((ROUNDS - 1) * INTERVAL))

echo '=============================================================='
echo "生产 5xx 计数窗口（只读；issue #8203 上线审计 P0-04）"
echo "阈值 ${THRESHOLD} 条 / 窗口 ${ROUNDS} 轮 × 轮间 ${INTERVAL}s（≈ ${WINDOW}s）· 超时 ${TIMEOUT}s"
echo "面清单（${URLS}）如下："
printf '%s\n' "$URLS" | grep -v '^[[:space:]]*$' | sed 's/^/   · /'
echo '=============================================================='

count_ok=0
count_5xx=0
count_other=0
count_unknown=0
requests=0
round=0

while [ "$round" -lt "$ROUNDS" ]; do
  round=$((round + 1))
  for url in $URLS; do
    [ -n "$url" ] || continue
    # 一次请求只取状态码：`-o /dev/null` 不落盘，`2>/dev/null` 不吃正文 ⇒ 日志里不会有响应内容。
    code=$("$CURL_BIN" -sS -o /dev/null -m "$TIMEOUT" -w '%{http_code}' "$url" 2>/dev/null || true)
    code=$(printf '%s' "$code" | tr -d '[:space:]')
    # curl 失败时 `-w` 可能一个字符都不输出（或留给下次调用）⇒ 统一成 000（= unknown）。
    printf '%s' "$code" | grep -Eq '^[0-9]{3}$' || code='000'
    requests=$((requests + 1))
    case "$code" in
      5[0-9][0-9])
        count_5xx=$((count_5xx + 1))
        class='5xx'
        ;;
      [23][0-9][0-9])
        count_ok=$((count_ok + 1))
        class='ok'
        ;;
      000)
        count_unknown=$((count_unknown + 1))
        class='unknown'
        ;;
      *)
        count_other=$((count_other + 1))
        class='other'
        ;;
    esac
    echo "PROD-5XX round=${round} url=${url} code=${code} class=${class}"
    case "$class" in
      ok) : ;;
      5xx) say "❌ ${url} ⇒ HTTP ${code}（5xx，第 ${count_5xx} 次）" ;;
      unknown) say "⚠️ ${url} ⇒ 取不到应答（DNS / 连接 / 超时）—— 记 unknown，**不**算 5xx 也不算 ok" ;;
      *) say "ℹ️ ${url} ⇒ HTTP ${code}（4xx：面坏了但不是 5xx，只计数）" ;;
    esac
  done
  if [ "$round" -lt "$ROUNDS" ] && [ "$INTERVAL" -gt 0 ]; then
    sleep "$INTERVAL"
  fi
done

# 读数**分级**（给告警去重用）：精确条数每轮都会抖 ⇒ 直接当指纹会让值班单被逐轮刷评论。
# 分级只表达「量级」，量级变了才值得再出声一次（判据见 test_prod_alerting.py 的幂等用例）。
case "$count_5xx" in
  0) BAND='none' ;;
  1|2|3|4|5) BAND='1-5' ;;
  6|7|8|9|10|11|12|13|14|15|16|17|18|19|20) BAND='6-20' ;;
  *) BAND='20+' ;;
esac

RC=0
REASON='below_threshold'
if [ "$count_5xx" -ge "$THRESHOLD" ]; then
  RC=1
  REASON="5xx>=threshold"
elif [ "$count_unknown" -gt 0 ]; then
  RC=3
  REASON='unreachable'
elif [ "$count_ok" -eq 0 ]; then
  # 所有面都回 4xx（或全是 000）⇒ 没有一个面证明「服务在正常应答」。
  # 这与「5xx 为零」不是同一件事 —— 3 不当 0 读。
  RC=3
  REASON='no_ok_face'
fi

echo ''
echo "PROD-5XX-SUMMARY rc=${RC} reason=${REASON} rounds=${ROUNDS} requests=${requests} fivexx=${count_5xx} band=${BAND} ok=${count_ok} other=${count_other} unknown=${count_unknown} threshold=${THRESHOLD} window_s=${WINDOW}"
case "$RC" in
  0) echo "✅ 窗口内 5xx=${count_5xx} < 阈值 ${THRESHOLD}（${requests} 次请求，ok=${count_ok}）" ;;
  1)
    echo "❌ **告警**：窗口内 5xx=${count_5xx} >= 阈值 ${THRESHOLD}（${requests} 次请求）"
    echo "   处置：① \`docker ps\` + \`docker logs --tail 200 migao-nginx\` 看 502/504 指向哪个上游；"
    echo "        ② 该上游的容器日志（admin-api / ai-agent / admin-web）；③ 回滚判据见 docs/deployment/rollback.md"
    ;;

  *)
    echo "⚠️ **无法判定**（rc=3，reason=${REASON}）：有面连不上或没有任何面给出 2xx/3xx —— 这不是「通过」；"
    echo "   复算：bash deploy/scripts/prod-5xx-window.sh"
    ;;
esac
exit "$RC"
