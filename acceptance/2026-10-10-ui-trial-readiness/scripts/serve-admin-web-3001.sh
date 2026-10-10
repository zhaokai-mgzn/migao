#!/bin/bash
# 启一个"路由完备"的 admin-web dev server（:3001），并作为作业主进程守住它。
# 依据（今天实测）：dev server 冷启动时路由扫描会**非确定性残缺**（一次只有 /，一次有 /login 没 /dashboard）
# ⇒ 只看 /login 或 TCP 连接不算就绪，必须校验**多个业务路由**，不齐就清 .next 重来。
WEB="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --path-format=absolute --git-common-dir)/../frontend/admin-web"
LOG=/tmp/srv3001.log
ROUTES="/login /dashboard /products /about"
check() {
  for p in $ROUTES; do
    c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 "http://localhost:3001${p}" 2>/dev/null || true)
    [ "${c}" = "200" ] || return 1
  done
  return 0
}
for attempt in 1 2 3; do
  for pid in $(lsof -ti:3001 2>/dev/null || true); do kill "${pid}" 2>/dev/null || true; done
  sleep 4
  rm -rf "${WEB}/.next"
  echo "[尝试 ${attempt}] 已清 .next，启动服务端…（load: $(uptime | sed 's/.*load averages*: //')）"
  ( cd "${WEB}" && exec node node_modules/next/dist/bin/next dev -p 3001 ) > "${LOG}" 2>&1 &
  SRV=$!
  echo "  server pid=${SRV}"
  for i in $(seq 1 36); do
    sleep 5
    if check; then echo "  ✅ 路由完备（第 ${i} 次探测 / 第 ${attempt} 次尝试）：${ROUTES}"; echo "SERVER_READY attempt=${attempt}"; wait "${SRV}"; exit 0; fi
    kill -0 "${SRV}" 2>/dev/null || { echo "  ⚠️ server 进程已退出（日志见 ${LOG}）"; break; }
  done
  echo "  ⚠️ 路由不齐 ⇒ 重来（当前：$(for p in $ROUTES; do printf '%s=%s ' "$p" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://localhost:3001$p 2>/dev/null || true)"; done)）"
  kill "${SRV}" 2>/dev/null || true
  sleep 3
done
echo "❌ 三次尝试都未得到完备路由表"
exit 9
