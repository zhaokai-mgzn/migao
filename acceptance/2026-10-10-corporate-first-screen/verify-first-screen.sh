#!/usr/bin/env bash
# case_ids: UI-082
#
# 首屏实证：对**真实 HTTP** 读一遍六条匿名可见路由与静态资源（issue #6665）。
#
# 为什么还要这个脚本（判据已经覆盖了）：
#   `frontend/admin-web/tests/unit/pages/anonymous-first-screen-*.ssr.test.tsx` 跑的是 `renderToString`
#   —— 它证明「门控不拦公开面」，但**不证明真服务器吐出来的 HTML 长什么样**（Next 的 RSC 载荷、
#   `proxy.ts` 的 matcher、`public/` 的静态件都在这条链上）。本脚本 = 那次真机读数的可复算形态。
#
# 口径：**只读可见 DOM**（剥掉 `<script>` 与标签）并解码 `\uXXXX` —— 这正是 issue 里
# 「可见 DOM 恒 503 B / 正文全在 RSC 载荷里」那条读数的口径。
#
# 用法（在 frontend/admin-web 目录下）：
#   bash ../../acceptance/2026-10-10-corporate-first-screen/verify-first-screen.sh
# 前置：本机已 `npm ci`；脚本自己起 dev server 并在结束时关掉。
set -euo pipefail

PKG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../frontend/admin-web" && pwd)"
cd "$PKG_DIR"

# 取数环境（按顺序，每种**先探端口**取不到就换）：
#   ① 该 worktree 已有 dev server 在跑（Next 把地址写在自己的开发日志里）⇒ 复用，不杀别人的进程
#   ② 自己起 `next dev`（默认 3901，可用 PORT 覆盖）
# ⚠️ Next 的 dev server **同一目录只跑一个**：同目录已有实例时 ② 会立刻退出（日志里写明
#    「Another next dev server is already running … You can access the existing server at …」）。
#    那种情况下先停掉那个实例（或用 PORT 换端口）再跑本脚本 —— 本脚本**不**替你杀别人的进程。
SERVER_PID=""
PORT=""
probe() { curl -fsS -o /dev/null "http://localhost:$1/robots.txt" 2>/dev/null; }

existing_dev_port() {
  local log="${PKG_DIR}/.next/dev/logs/next-development.log"
  [ -f "$log" ] || return 0
  grep -oE "http://localhost:[0-9]+" "$log" 2>/dev/null | tail -1 | grep -oE "[0-9]+$" || true
}

if HINT=$(existing_dev_port) && [ -n "$HINT" ] && probe "$HINT"; then
  PORT="$HINT"
  echo "▶ 复用已在跑的 dev server（端口 ${PORT}）"
fi

if [ -z "$PORT" ]; then
  DEV_PORT="${PORT:-3901}"
  : > /tmp/next-dev-6665-acceptance.log
  # ⚠️ 变量名后面紧跟 CJK 时**必须**写 `${VAR}`：丢掉花括号，bash 会把多字节字节当成变量名的一部分
  # ⇒ `PKG_DIR<U+FF0C>: unbound variable`（本脚本实测踩过一次）。
  echo "▶ 启动 dev server（${PKG_DIR}，端口 ${DEV_PORT}）"
  npx next dev -p "$DEV_PORT" > /tmp/next-dev-6665-acceptance.log 2>&1 &
  SERVER_PID=$!
  # 只杀**自己起的**那个（含 npx 包出来的子进程）：复用时 SERVER_PID 为空 ⇒ 不碰别人的进程
  trap '[ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null; [ -n "$SERVER_PID" ] && pkill -P "$SERVER_PID" 2>/dev/null; true' EXIT
  for _ in $(seq 1 20); do
    HINT=$(grep -oE "http://localhost:[0-9]+" /tmp/next-dev-6665-acceptance.log 2>/dev/null | tail -1 | grep -oE "[0-9]+$" || true)
    if [ -n "$HINT" ] && probe "$HINT"; then PORT="$HINT"; break; fi
    sleep 1
  done
  echo "  就绪（PID ${SERVER_PID:-?}，端口 ${PORT:-未就绪}）"
fi

if [ -z "$PORT" ]; then
  echo "❌ dev server 没起来 —— 先看 /tmp/next-dev-6665-acceptance.log（同目录可能已有 dev server：先停掉它，或用 PORT=<别的端口> 重跑）" >&2
  exit 1
fi

# 预热：dev server 是**按需编译**的，第一次请求某个路由时它还在编译 ⇒ 首个响应可能是半截
# （实测：直连路由的 JSON 读数已对，但 `fetch` 拿到的 HTML 里正文缺失、canonical 读不到）。
# 每个路由先打一遍（时间不参与判据），让真正的检查跑在**编译完成**之后。
echo "▶ 预热六条路由（dev server 按需编译）"
for _p in / /about /services /contact /login /register; do
  curl -fsS -o /dev/null "http://localhost:${PORT}${_p}" 2>/dev/null || true
done

node --input-type=module - "$PORT" <<'NODE'
const port = process.argv[2]
const decode = (s) => s.replace(/\\u([0-9a-fA-F]{4})/g, (_, h) => String.fromCharCode(parseInt(h, 16)))
const visible = (html) =>
  decode(decode(html).replace(/<script[\s\S]*?<\/script>/g, '').replace(/<[^>]+>/g, ' '))

let failed = 0
const check = (ok, label, reading) => {
  console.log(`${ok ? '✅' : '❌'} ${label} — ${reading}`)
  if (!ok) failed++
}

// ① 六条匿名可见路由：首屏要有 h1 与正文，且**不得**出现骨架
const ROUTES = [
  ['/', '立即入驻'],
  ['/about', '关于我们'],
  ['/services', '产品与服务'],
  ['/contact', '四类常见咨询'],
  ['/login', '观星台'],
  ['/register', '企业入驻申请'],
]
for (const [path, needle] of ROUTES) {
  const html = await (await fetch(`http://localhost:${port}${path}`)).text()
  const text = visible(html)
  check(
    text.includes(needle) && !text.includes('加载中...'),
    `${path} 首屏正文`,
    `正文命中「${needle}」=${text.includes(needle)}，骨架=${text.includes('加载中...')}，h1=${(html.match(/<h1/g) || []).length}`,
  )
}

// ② 负控：受保护业务页首屏仍不得吐正文（登录门控一条不放宽）
{
  const html = await (await fetch(`http://localhost:${port}/orders`)).text()
  const text = visible(html)
  check(text.includes('加载中...') && !/<h1/.test(html), '/orders 负控（首屏仍是门控）', `骨架=${text.includes('加载中...')}，h1=${(html.match(/<h1/g) || []).length}`)
}

// ③ 静态资源与抓取指引可达（不是 3xx 到 /）
for (const path of ['/robots.txt', '/sitemap.xml', '/favicon.svg', '/og-image.png']) {
  const res = await fetch(`http://localhost:${port}${path}`, { redirect: 'manual' })
  const ok = res.status === 200 && !(res.headers.get('location') || '').endsWith('/')
  check(ok, `${path} 可达`, `status=${res.status} type=${res.headers.get('content-type')}`)
}

// ④ 不存在的路径给 404 形态
{
  const res = await fetch(`http://localhost:${port}/this-path-does-not-exist-9f2c`, { redirect: 'manual' })
  check(res.status === 404, '未知路径 404（不是 307 回首页）', `status=${res.status}`)
}

// ⑤ 联系页：取不到表单控件，且没有假成功字面量
{
  const html = await (await fetch(`http://localhost:${port}/contact`)).text()
  const controls = (html.match(/<(input|textarea|select)\b/g) || []).length
  check(controls === 0 && !visible(html).includes('留言提交成功'), '联系页无留言表单', `控件=${controls}，假成功字面量=${visible(html).includes('留言提交成功')}`)
}

// ⑥ 分享元数据：canonical 与 og:image 指向唯一站点真值源
{
  const html = await (await fetch(`http://localhost:${port}/contact`)).text()
  const canonical = (html.match(/<link rel="canonical" href="([^"]+)"/) || [])[1]
  const ogImage = (html.match(/<meta property="og:image" content="([^"]+)"/) || [])[1]
  check(
    canonical === 'https://www.migaozn.com' && ogImage === 'https://www.migaozn.com/og-image.png',
    'canonical / og:image 单一真值源',
    `canonical=${canonical}，og:image=${ogImage}`,
  )
}

console.log(failed === 0 ? '\n✅ 全部通过（本读数 = 首屏真机形态）' : `\n❌ ${failed} 条不达标`)
process.exit(failed === 0 ? 0 : 1)
NODE
