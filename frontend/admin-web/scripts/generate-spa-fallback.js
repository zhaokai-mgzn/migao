#!/usr/bin/env node
/**
 * 构建后生成 SPA 路由分派器：out/_spa-fallback.html
 *
 * 背景：
 *   Next.js App Router + output:'export' 对动态路由（如 /products/[id]/edit）
 *   只会按 generateStaticParams 返回的占位（'_'）生成占位 HTML，
 *   出口示例：out/products/_/edit/index.html。
 *   实际访问 /products/123/edit/ 时 OSS 找不到 key，会落到 ErrorDocument。
 *   若 ErrorDocument 指向根 /index.html（属于 (corporate) 路由组），
 *   浏览器会渲染营销首页内容并加载 (corporate)/page-*.js，
 *   导致前端业务路由完全错位。
 *
 * 解决：
 *   1) 扫描 out/ 中所有 “占位段为 _ ” 的目录，反推出动态路由模式与对应占位 HTML；
 *   2) 生成 out/_spa-fallback.html：内联脚本根据 location.pathname 匹配模式，
 *      将原始 URL 编码到 ?__spa_path= 后跳转到对应占位页；
 *   3) OSS ErrorDocument 指向 _spa-fallback.html（HTTP 200），
 *      由该分派器接管所有未命中的路径，匹配则跳占位页，未匹配则回首页；
 *   4) 占位页加载时，根 layout 中的早期脚本读取 ?__spa_path= 并通过
 *      history.replaceState 还原原始 URL，前端组件（useRouteId）即可读取真实 ID。
 *
 * 该脚本通过 package.json 的 postbuild 钩子自动运行，不需要手动调用。
 */
'use strict'

const fs = require('fs')
const path = require('path')

const OUT_DIR = path.resolve(__dirname, '../out')
const FALLBACK_FILE = path.join(OUT_DIR, '_spa-fallback.html')

const GREEN = '\x1b[32m'
const YELLOW = '\x1b[33m'
const RESET = '\x1b[0m'

if (!fs.existsSync(OUT_DIR)) {
  // 非静态导出构建（如 dev 或 next build 关闭 export），跳过
  console.log(`${YELLOW}[spa-fallback] out/ 不存在，跳过（非静态导出构建）${RESET}`)
  process.exit(0)
}

/**
 * 递归扫描 out/，找出所有包含占位段（'_'）且存在 index.html 的子路径。
 * 例如：
 *   out/products/_/index.html        → 模式 /products/[id]/
 *   out/products/_/edit/index.html   → 模式 /products/[id]/edit/
 *   out/orders/_/ship/index.html     → 模式 /orders/[id]/ship/
 *
 * 只要路径中出现过 '_' 且当前目录含 index.html，都视为一个占位路由。
 */
function collectPlaceholderRoutes(dir, segments, acc) {
  let entries
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true })
  } catch {
    return
  }
  // 当前目录本身：如果 segments 中含 '_' 且含 index.html，则是一个占位路由
  if (segments.length > 0 && segments.includes('_')) {
    const hasIndex = entries.some((e) => e.isFile() && e.name === 'index.html')
    if (hasIndex) {
      acc.push(segments.slice())
    }
  }
  for (const entry of entries) {
    if (!entry.isDirectory()) continue
    if (entry.name === '_next') continue
    const next = path.join(dir, entry.name)
    collectPlaceholderRoutes(next, [...segments, entry.name], acc)
  }
}

const placeholders = []
collectPlaceholderRoutes(OUT_DIR, [], placeholders)

/**
 * 把目录段数组转换为 (regex, placeholderPath) 对：
 *   ['products', '_', 'edit']  →  [/^\/products\/[^\/]+\/edit\/?$/, '/products/_/edit/']
 *
 * 仅替换 '_' 段为 [^\/]+，保持其它静态段原样。
 */
function buildRoute(segments) {
  const regexBody = segments
    .map((s) => (s === '_' ? '[^/]+' : escapeRegExp(s)))
    .join('\\/')
  const regex = `^\\/${regexBody}\\/?$`
  const placeholderPath = '/' + segments.join('/') + '/'
  return { regex, placeholderPath, segments: segments.slice() }
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

const routes = placeholders.map(buildRoute)

// 排序：嵌套更深的优先匹配（避免 /products/_/ 提前吃掉 /products/_/edit/）
routes.sort((a, b) => b.segments.length - a.segments.length)

if (routes.length === 0) {
  console.log(`${YELLOW}[spa-fallback] 未发现动态占位路由，跳过${RESET}`)
  process.exit(0)
}

const routesJs = routes
  .map((r) => `  [new RegExp(${JSON.stringify(r.regex)}), ${JSON.stringify(r.placeholderPath)}]`)
  .join(',\n')

const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>跳转中...</title>
<script>
/* 自动生成: scripts/generate-spa-fallback.js
 * 由 OSS ErrorDocument 指向，将动态路由请求改派到对应占位 HTML。
 * 切勿手动修改本文件。
 */
(function () {
  try {
    var p = window.location.pathname || '/';
    var s = window.location.search || '';
    var h = window.location.hash || '';
    var routes = [
${routesJs}
    ];
    for (var i = 0; i < routes.length; i++) {
      if (routes[i][0].test(p)) {
        var placeholder = routes[i][1];
        var sep = placeholder.indexOf('?') >= 0 ? '&' : '?';
        var target = placeholder + sep + '__spa_path=' + encodeURIComponent(p + s + h);
        window.location.replace(target);
        return;
      }
    }
    // 未命中任何动态路由模式，回到首页
    if (p !== '/') {
      window.location.replace('/');
    }
  } catch (e) {
    window.location.replace('/');
  }
})();
</script>
</head>
<body>
<noscript>页面跳转需要 JavaScript，请开启浏览器 JavaScript 后重试。</noscript>
</body>
</html>
`

fs.writeFileSync(FALLBACK_FILE, html, 'utf-8')

console.log(`${GREEN}[spa-fallback] 已生成 ${path.relative(process.cwd(), FALLBACK_FILE)}${RESET}`)
console.log(`${GREEN}[spa-fallback] 注入的动态路由模式：${RESET}`)
for (const r of routes) {
  console.log(`  - ${r.regex}  →  ${r.placeholderPath}`)
}
