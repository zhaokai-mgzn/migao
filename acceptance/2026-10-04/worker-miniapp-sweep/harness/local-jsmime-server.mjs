// local-jsmime-server.mjs — **只读**静态服务（装置级，不改产品代码 / 不改 nginx / 不碰任何既有服务）
//
// 为什么需要它（BRIEF §3.9「不得用『页面能打开』冒充写面验证」的反面用法）：
//   部署面 `https://app.migaozn.com/w/` 的 `.mjs` 被 nginx 以 `application/octet-stream` 发出
//   ⇒ 浏览器**拒绝执行** module script（HTML 规范强制的 MIME 检查）⇒ 整页白屏。
//   为了把「MIME 头」这一个自变量单独拎出来做**对照实验**，本服务把**同一份静态文件**
//   （`frontend/worker-h5/**`）以**正确的** JS MIME 发出：
//     · 若这样页面就能起来 ⇒ 归因＝MIME 头（不是页面代码）；
//     · 若仍起不来 ⇒ 归因不成立，必须改判。
//   ⇒ 这是一次**单变量对照**，不是"换环境让它绿"。
//
// ⚠️ 本服务按 README 的「不新增常驻服务」纪律用**后台 job**跑，收尾即 kill。
import { createServer } from 'node:http'
import { readFile, stat } from 'node:fs/promises'
import { join, extname, normalize } from 'node:path'

const ROOT = process.env.STATIC_ROOT || '/Users/guangzhen.zk/migao-wt/main-live/frontend'
const PORT = Number(process.env.PORT || 3170)
const API_ORIGIN = process.env.API_ORIGIN || 'https://api.migaozn.com'

// 显式 MIME 表：`.mjs` 必须是 JS MIME（对照实验的**唯一自变量**）
const MIME = {
  '.mjs': 'text/javascript; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
}

const server = createServer(async (req, res) => {
  // /api/** ⇒ Node 侧代理到**被测已部署 API**（同源假设由部署 nginx 提供；本装置只补齐它）
  if (req.url.startsWith('/api/')) {
    const chunks = []
    for await (const c of req) chunks.push(c)
    const body = Buffer.concat(chunks)
    try {
      const r = await fetch(API_ORIGIN + req.url, {
        method: req.method,
        headers: { 'content-type': req.headers['content-type'] ?? 'application/json', ...(req.headers['x-worker-session-id'] ? { 'x-worker-session-id': req.headers['x-worker-session-id'] } : {}) },
        body: ['GET', 'HEAD'].includes(req.method) ? undefined : body,
      })
      const buf = Buffer.from(await r.arrayBuffer())
      res.writeHead(r.status, { 'content-type': r.headers.get('content-type') ?? 'application/json' })
      res.end(buf)
    } catch (e) {
      res.writeHead(502, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ success: false, error: { code: 'PROXY_ERROR', message: String(e).slice(0, 120) } }))
    }
    return
  }
  const url = new URL(req.url, 'http://x')
  let p = normalize(decodeURIComponent(url.pathname))
  if (p.endsWith('/')) p += 'index.html'
  const file = join(ROOT, p)
  if (!file.startsWith(ROOT)) { res.writeHead(403).end('forbidden'); return }
  try {
    const st = await stat(file)
    if (st.isDirectory()) { res.writeHead(302, { location: p + '/' }).end(); return }
    const buf = await readFile(file)
    res.writeHead(200, { 'content-type': MIME[extname(file).toLowerCase()] ?? 'application/octet-stream', 'content-length': buf.length })
    res.end(buf)
  } catch {
    res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' }).end('404 ' + p)
  }
})
server.listen(PORT, '127.0.0.1', () => console.log(`local-jsmime-server listening http://127.0.0.1:${PORT} root=${ROOT} api=${API_ORIGIN}`))
