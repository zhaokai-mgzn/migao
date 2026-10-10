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

PORT="${PORT:-3901}"
PKG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../frontend/admin-web" && pwd)"
cd "$PKG_DIR"

echo "▶ 启动 dev server（$PKG_DIR，端口 $PORT）"
npx next dev -p "$PORT" > /tmp/next-dev-6665-acceptance.log 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null "http://localhost:$PORT/robots.txt" 2>/dev/null; then break; fi
  sleep 1
done
echo "  就绪（PID $SERVER_PID），日志 /tmp/next-dev-6665-acceptance.log"

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
