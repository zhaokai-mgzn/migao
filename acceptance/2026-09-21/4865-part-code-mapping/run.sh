#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# #4865 验收剧本重放（闭合需求⑤ 的 U1 / U2 / U6）
#
#   U1 同一条 `generate → instantiate` ⇒ 取**真** short_code（不是 SQL 里造的行）
#   U2 `curl -D -` 该真短码 ⇒ **302** + `Location: /w/?t=<token>`
#   U6 `curl -L` ⇒ 最终 **200**，且**落地 body 的 sha256 == `origin/main` 的
#      frontend/worker-h5/index.html**（不只看 200 —— `/w/` 的 200 是恒真的，见
#      deploy/scripts/worker-h5-verify-served.sh 的注释）
#   另：对真短码做**只读枚举**，验字符集 = Crockford Base32 去 I/L/O/U、长度 = 8
#
# 环境（本机自建、跑完即拆，零残留）：
#   · 一次性 PostgreSQL 16（initdb + pg_ctl，随机端口）+ docs/sql/schema.sql（bootstrap 终态）
#   · 本仓 admin-api（:8081）—— 连上面这个库
#   · serve.py（:8080）= nginx 替身：`/w/**` 读 frontend/worker-h5，其余反代 :8081
#     （生产上两者同源，故 302 的 Location 是相对路径 `/w/?t=…`）
#
# 为什么不是打「测试环境」：本机到云 dev RDS **不可达**（实测 `timeout expired`；
# 与 acceptance/2026-09-20/4789-set-no-allocator/FINDINGS.md 记录的环境状况一致）⇒
# 本机自建等价栈。**受 #4864（工人端 401）阻断的部分**：本剧本不触碰 `/api/worker/**`。
#
# 用法：./run.sh            # 跑全剧本并打印证据
# 退出码：0 = U1/U2/U6 全绿；非零 = 逐条打印哪一条不成立
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
API_PORT=8081
WEB_PORT=8080
PG_PORT="${PG_PORT:-$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')}"
QTY_PORT="${QTY_PORT:-$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')}"
PHONE=13900004865
BYPASS_CODE=486501
FAIL=0

WORK="$(mktemp -d /tmp/acc4865.XXXXXX)"
PGDATA="$WORK/pgdata"
PGLOG="$WORK/pg.log"
API_LOG="$WORK/admin-api.log"
QTY_LOG="$WORK/qty-stub.log"
WEB_LOG="$WORK/serve.log"
LANDED="$WORK/landed.html"
APP_PID=""
WEB_PID=""
QTY_PID=""

cleanup() {
  [ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null
  [ -n "$WEB_PID" ] && kill "$WEB_PID" 2>/dev/null
  [ -n "$QTY_PID" ] && kill "$QTY_PID" 2>/dev/null
  pkill -f "spring-boot:run.*$API_PORT" 2>/dev/null
  pg_ctl -D "$PGDATA" -m immediate stop >/dev/null 2>&1
  sleep 1
  # 残留复查（临时集群与进程都不许留）
  echo "── 残留复查（本剧本留下的东西）──"
  echo "临时工作目录（含一次性 PG 数据目录、日志）：$WORK —— 删除"
  rm -rf "$WORK"
  if pg_isready -h 127.0.0.1 -p "$PG_PORT" >/dev/null 2>&1; then
    echo "❌ PG 仍在 :$PG_PORT"; else echo "✅ PG :$PG_PORT 已停"; fi
  for p in "$API_PORT" "$WEB_PORT" "$QTY_PORT"; do
    if lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then echo "❌ 端口 $p 仍被占用"; else echo "✅ 端口 $p 已释放"; fi
  done
  echo "✅ 库内 acc-fix4865-* 实体随临时集群一并消失（从未写入共享/生产库）"
}
trap cleanup EXIT

psql_run() { psql "host=127.0.0.1 port=$PG_PORT user=postgres dbname=postgres connect_timeout=5" -X -q "$@"; }

# 证据脱敏：`qr_token`（以及 Location 里的 `t=`）是**凭据等价物**（持码即可报工/换发短码）
# ⇒ 日志只留前 8 位。这也是 CI 的硬要求：gitleaks 的 `generic-api-key` 会把 32 位 token
# 判成密钥（实测：commit 78af39065 的 replay-output.txt 第 19 行被判红）⇒ 修法不是加豁免，
# 而是**别把它提交进仓库**。
mask_secrets() {
  python3 -c 'import re,sys; print(re.sub(r"[0-9a-f]{32}", lambda m: m.group(0)[:8] + "…(masked)", sys.stdin.read()), end="")'
}

echo "═══ ① 一次性 PostgreSQL 16（端口 ${PG_PORT}）+ docs/sql/schema.sql（bootstrap 终态）═══"
initdb -D "$PGDATA" -U postgres -A trust >/dev/null 2>&1 || { echo "❌ initdb 失败"; exit 1; }
pg_ctl -D "$PGDATA" -l "$PGLOG" -o "-p $PG_PORT -c listen_addresses=127.0.0.1 -k $WORK" start >/dev/null 2>&1 \
  || { echo "❌ pg_ctl start 失败"; cat "$PGLOG"; exit 1; }
psql_run -v ON_ERROR_STOP=1 -f "$ROOT/docs/sql/schema.sql" >/dev/null || { echo "❌ schema.sql 建库失败"; exit 1; }
psql_run -v ON_ERROR_STOP=1 -f "$HERE/fixtures.sql" >/dev/null || { echo "❌ 夹具失败"; exit 1; }
echo "   ✅ 建库 + 夹具完成（用户 $PHONE / 订单 acc-fix4865-order / 3 个部位行）"

echo
echo "═══ ② 起 admin-api（:${API_PORT}，连这个一次性库）+ nginx 替身（:${WEB_PORT}）═══"
python3 "$HERE/qty_stub.py" "$QTY_PORT" "$ROOT" >"$QTY_LOG" 2>&1 &
QTY_PID=$!
echo "   · 算料引擎端点桩（:${QTY_PORT}）= 直接加载本仓 routing.py::qty_and_source（非第二份算料逻辑）"

cd "$ROOT/backend/admin-api" || exit 1
# ⚠️ 注释不能夹在 `\` 续行的环境变量赋值里（会截断赋值 ⇒ 回落默认值 localhost:5432）
# JWT 用**仓内测试密钥**（backend/admin-api/src/test/resources/rsa/*，非任何环境的生产密钥）
RDS_HOST=127.0.0.1 RDS_PORT="$PG_PORT" RDS_DB=postgres RDS_USER=postgres RDS_PASSWORD= \
SERVER_PORT="$API_PORT" SMS_BYPASS_CODE="$BYPASS_CODE" \
JWT_PRIVATE_KEY="file:$ROOT/backend/admin-api/src/test/resources/rsa/private.pem" \
JWT_PUBLIC_KEY="file:$ROOT/backend/admin-api/src/test/resources/rsa/public.pem" \
SPRING_APPLICATION_JSON="{\"ai-agent\":{\"base-url\":\"http://127.0.0.1:$QTY_PORT\",\"service-token\":\"acc4865stub\"}}" \
  ./mvnw -q spring-boot:run >"$API_LOG" 2>&1 &
APP_PID=$!
for _ in $(seq 1 90); do
  curl -s -o /dev/null "http://127.0.0.1:$API_PORT/api/auth/me" && break
  kill -0 "$APP_PID" 2>/dev/null || { echo "❌ admin-api 退出，日志尾部："; tail -30 "$API_LOG"; exit 1; }
  sleep 2
done
curl -s -o /dev/null "http://127.0.0.1:$API_PORT/api/auth/me" || { echo "❌ admin-api 未就绪"; tail -30 "$API_LOG"; exit 1; }
python3 "$HERE/serve.py" "$WEB_PORT" "$API_PORT" "$ROOT/frontend/worker-h5" >"$WEB_LOG" 2>&1 &
WEB_PID=$!
sleep 1
echo "   ✅ admin-api 就绪（:${API_PORT}）；nginx 替身就绪（:${WEB_PORT}）"

echo
echo "═══ ③ 真实登录（POST /api/auth/sms/login；不手搓 JWT）═══"
LOGIN=$(curl -s -X POST "http://127.0.0.1:$WEB_PORT/api/auth/sms/login" \
  -H 'Content-Type: application/json' \
  -d "{\"phone\":\"$PHONE\",\"code\":\"$BYPASS_CODE\",\"tenantId\":1}")
TOKEN=$(printf '%s' "$LOGIN" | python3 -c 'import json,sys;d=json.load(sys.stdin);print((d.get("data") or {}).get("accessToken") or "")')
if [ -z "$TOKEN" ]; then echo "❌ 登录失败：$LOGIN"; exit 1; fi
echo "   ✅ 登录成功（accessToken 长度 ${#TOKEN}，tenantId=1）"

echo
echo "═══ ④ U1：generate → instantiate ⇒ 真 short_code ═══"
GEN=$(curl -s -X POST "http://127.0.0.1:$WEB_PORT/api/admin/processing-orders/generate" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"orderIds":["acc-fix4865-order"]}')
echo "   generate 响应：$GEN"
INST=$(curl -s -X POST "http://127.0.0.1:$WEB_PORT/api/admin/production/orders/acc-fix4865-order/instantiate" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}')
echo "   instantiate 响应：$(printf '%s' "$INST" | mask_secrets)"
echo "   ── 算料桩收到的请求（形状核对）──"
grep -m3 '^REQ' "$QTY_LOG" | cut -c1-600 | sed 's/^/   /'
tail -5 "$QTY_LOG" | sed 's/^/   /'

echo "   ── 失败 SQL 原文（若有）──"
grep -A4 "### SQL:" "$API_LOG" | tail -30 | sed "s/^/   /"
echo "   ── admin-api 日志里的异常（若有）──"
grep -nE "ERROR|Exception|Caused by" "$API_LOG" | tail -25 | sed "s/^/   /"
echo "   ── 库内实况（部位码 / 短码）──"
psql_run -c "SELECT count(*) AS token_rows, count(short_code) AS with_short_code
               FROM processing_set_part_tokens WHERE processing_order_id IN
               (SELECT id FROM processing_orders WHERE order_id = 'acc-fix4865-order') AND deleted = 0"
SHORT_CODE=$(psql_run -tAc "SELECT t.short_code FROM processing_set_part_tokens t
                             JOIN processing_orders po ON po.id = t.processing_order_id
                            WHERE po.order_id = 'acc-fix4865-order' AND t.deleted = 0
                              AND t.short_code IS NOT NULL ORDER BY t.order_item_id LIMIT 1")
TOKEN_VALUE=$(psql_run -tAc "SELECT t.token FROM processing_set_part_tokens t
                              JOIN processing_orders po ON po.id = t.processing_order_id
                             WHERE po.order_id = 'acc-fix4865-order' AND t.deleted = 0
                               AND t.short_code IS NOT NULL ORDER BY t.order_item_id LIMIT 1")
if [ -z "$SHORT_CODE" ]; then echo "❌ U1 红：实例化没有产出任何 short_code"; FAIL=1; else
  echo "   ✅ U1 绿：真 short_code = ${SHORT_CODE}（对应 token = $(printf '%s' "${TOKEN_VALUE}" | mask_secrets)）"; fi

echo
echo "═══ ⑤ U2：curl -D - /s/<真短码> ⇒ 302 + Location ═══"
if [ -n "$SHORT_CODE" ]; then
  HEADERS_RAW=$(curl -s -D - -o /dev/null "http://127.0.0.1:$WEB_PORT/s/$SHORT_CODE")
  HEADERS=$(printf '%s' "$HEADERS_RAW" | mask_secrets)
  echo "$HEADERS" | sed 's/^/   /'
  STATUS=$(printf '%s' "$HEADERS" | head -1 | awk '{print $2}')
  LOCATION=$(printf '%s' "$HEADERS" | grep -i '^location:' | tr -d '\r' | awk '{print $2}')
  if [ "$STATUS" = "302" ] && [ -n "$LOCATION" ]; then
    echo "   ✅ U2 绿：$STATUS + Location: $LOCATION"
    case "$LOCATION" in /w/?t=*) echo "   ✅ Location 形态 = /w/?t=<token>（相对路径，同源落地）";;
      *) echo "   ❌ Location 形态不符：$LOCATION"; FAIL=1;; esac
  else echo "   ❌ U2 红：status=$STATUS location=$LOCATION"; FAIL=1; fi
else echo "   ⏭  U2 跳过（U1 已红）"; fi

echo
echo "═══ ⑥ U6：curl -L ⇒ 200 且落地 body 哈希 == origin/main 的 frontend/worker-h5/index.html ═══"
if [ -n "$SHORT_CODE" ]; then
  LANDED_STATUS=$(curl -sL -o "$LANDED" -w '%{http_code}' "http://127.0.0.1:$WEB_PORT/s/$SHORT_CODE")
  LANDED_HASH=$(shasum -a 256 "$LANDED" | awk '{print $1}')
  ORIGIN_HASH=$(cd "$ROOT" && git show origin/main:frontend/worker-h5/index.html | shasum -a 256 | awk '{print $1}')
  echo "   落地 status = $LANDED_STATUS"
  echo "   落地 body sha256      = $LANDED_HASH"
  echo "   origin/main 同名文件  = $ORIGIN_HASH"
  if [ "$LANDED_STATUS" = "200" ] && [ "$LANDED_HASH" = "$ORIGIN_HASH" ]; then
    echo "   ✅ U6 绿：落地页 == origin/main 的 frontend/worker-h5/index.html（逐字节）"
  else echo "   ❌ U6 红：status=${LANDED_STATUS}，哈希 $LANDED_HASH vs $ORIGIN_HASH"; FAIL=1; fi
else echo "   ⏭  U6 跳过（U1 已红）"; fi

echo
echo "═══ ⑦ 真短码的**只读枚举**：字符集 + 长度 ═══"
if [ -n "$SHORT_CODE" ]; then
  python3 - "$SHORT_CODE" <<'PY'
import re, sys
code = sys.argv[1]
alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"   # Crockford Base32 去 I/L/O/U
bad = sorted({c for c in code if c not in alphabet})
print(f"   短码 = {code}；长度 = {len(code)}；非法字符 = {bad or '（无）'}")
ok = len(code) == 8 and not bad and re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{8}", code) is not None
print("   ✅ 长度 8 + 字符集 = Crockford Base32 去 I/L/O/U" if ok else "   ❌ 形态不符")
sys.exit(0 if ok else 1)
PY
  [ $? -ne 0 ] && FAIL=1
else echo "   ⏭  跳过（U1 已红）"; fi

echo
echo "═══ ⑧ 临时实体清点（跑完随一次性库消失；此处为**离开前**的实况）═══"
psql_run -c "SELECT 'users' AS t, count(*) FROM users WHERE id LIKE 'acc-fix4865%'
             UNION ALL SELECT 'orders', count(*) FROM orders WHERE id LIKE 'acc-fix4865%'
             UNION ALL SELECT 'order_items', count(*) FROM order_items WHERE id LIKE 'acc-fix4865%'
             UNION ALL SELECT 'processing_orders', count(*) FROM processing_orders WHERE order_id LIKE 'acc-fix4865%'"

echo
if [ "$FAIL" -eq 0 ]; then echo "════ 结论：U1 / U2 / U6 全绿 ════"; else echo "════ 结论：有判据红（见上）════"; fi
exit "$FAIL"
