#!/usr/bin/env bash
# 复位 admin-web dev server —— 一条命令，顺序即安全顺序（铁律 10：一晚做过 ≥3 次的动作串要收敛成命令）
#
# 为什么需要它（两个各自独立、叠加起来最难查的坑，实证见 issue #6692）：
#   ① **Turbopack 持久缓存**：只删 `.next` **不够** —— `.turbo` / `node_modules/.cache` 里仍留着旧
#      编译产物与**旧路由清单**，会被喂回来 ⇒ 表现为「改了文件但页面没变」，甚至「`(dashboard)` 组
#      整组 404 而顶层路由正常」。
#   ② **多实例并发**：同一份 `.next` 上跑两个 `next dev` ⇒ 路由清单互相覆盖，症状同上。
#   ⇒ 三者必须一起处理：杀光实例 → 三类缓存一起删 → 只起一个。
#
# 用法：
#   ./scripts/dev-web-reset.sh                 # 复位 :3001 并等到就绪
#   ./scripts/dev-web-reset.sh 3002            # 换端口
#   NO_START=1 ./scripts/dev-web-reset.sh      # 只清理不起服务
#
# 退出码：0 = 已就绪；1 = 等不到就绪（日志尾部会打出来，**不静默**）
set -euo pipefail

PORT="${1:-3001}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="${WEB_DIR:-$ROOT/frontend/admin-web}"   # 可用 WEB_DIR 指定别的工作树（便于从任意 worktree 复位主工作树的服务）
LOG="${TMPDIR:-/tmp}/admin-web-dev-$PORT.log"
WAIT_SECS="${WAIT_SECS:-180}"

[ -d "$WEB" ] || { echo "✗ 找不到 $WEB" >&2; exit 1; }

echo "== ① 杀掉全部 next dev / next-server 实例"
pkill -f "next-server" 2>/dev/null || true
pkill -f "next dev" 2>/dev/null || true
for _ in $(seq 1 20); do
  lsof -ti:"$PORT" >/dev/null 2>&1 || break
  sleep 0.5
done
if lsof -ti:"$PORT" >/dev/null 2>&1; then
  echo "  :$PORT 仍被占用，强杀：$(lsof -ti:"$PORT" | tr '\n' ' ')"
  lsof -ti:"$PORT" | xargs kill -9 2>/dev/null || true
  sleep 2
fi

echo "== ② 三类缓存一起删（只删 .next 不够）"
# ⚠️ 实测：紧跟 kill 之后的 `rm -rf` 会失败（`Directory not empty` —— 退场中的进程仍在写/重建）
# ⇒ 必须**重试 + 断言真的没了**，否则重置静默不完整（这就是「服务端不是 HEAD」的温床）
caches_gone() {
  [ ! -e "$WEB/.next" ] && [ ! -e "$WEB/node_modules/.cache" ] && [ ! -e "$WEB/.turbo" ]
}
rm_ok=0
for _ in $(seq 1 10); do
  if pgrep -f "next-server" >/dev/null 2>&1 || pgrep -f "next dev" >/dev/null 2>&1; then
    pkill -9 -f "next-server" 2>/dev/null || true
    pkill -9 -f "next dev" 2>/dev/null || true
  fi
  rm -rf "$WEB/.next" "$WEB/node_modules/.cache" "$WEB/.turbo" 2>/dev/null || true
  if caches_gone; then rm_ok=1; break; fi
  sleep 1
done
if [ "$rm_ok" != "1" ]; then
  echo "✗ 缓存没清干净（仍有实例在写？）。残留：" >&2
  for d in "$WEB/.next" "$WEB/node_modules/.cache" "$WEB/.turbo"; do [ -e "$d" ] && echo "   $d" >&2; done
  exit 1
fi
echo "   ✓ 三类缓存已确认清空"

if [ "${NO_START:-0}" = "1" ]; then
  echo "== NO_START=1 ⇒ 只清理，不起服务"; exit 0
fi

echo "== ③ 只起一个实例（日志：${LOG}）"
# setsid：脱离调用方的**进程组** —— 否则调用方被 SIGTERM（或 shell 退出）时会把 dev server 一起带走
if command -v setsid >/dev/null 2>&1; then
  ( cd "$WEB" && setsid nohup npm run dev -- --port "$PORT" >"$LOG" 2>&1 < /dev/null & )
else
  ( cd "$WEB" && nohup npm run dev -- --port "$PORT" >"$LOG" 2>&1 < /dev/null & disown )
fi

echo "== ④ 等就绪（最多 ${WAIT_SECS}s；首请求要现编译，慢是正常的）"
for _ in $(seq 1 "$((WAIT_SECS / 3))"); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost:$PORT/login" 2>/dev/null || echo 000)"
  if [ "$code" = "200" ]; then
    # 顶层路由通不代表 (dashboard) 组通 —— 后者是上面两个坑的典型症状，必须一起探
    dash="$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "http://localhost:$PORT/dashboard" 2>/dev/null || echo 000)"
    if [ "$dash" = "200" ]; then
      echo "✓ 就绪：:${PORT} /login=200 /dashboard=200（服务的就是当前工作树）"
      exit 0
    fi
    echo "  /login=200 但 /dashboard=$dash —— 疑似 ①/② 未清干净，继续等"
  fi
  sleep 3
done

echo "✗ 等不到就绪（:${PORT}）。日志尾部：" >&2
tail -20 "$LOG" >&2 || true
exit 1
