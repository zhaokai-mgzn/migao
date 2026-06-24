#!/usr/bin/env node
/**
 * 构建后生成 SPA fallback：out/_spa-fallback.html
 *
 * 简化方案：
 *   直接复制 out/index.html → out/_spa-fallback.html。
 *   OSS/CDN ErrorDocument 指向 _spa-fallback.html。
 *
 * 原理：
 *   Next.js 客户端路由初始化时读取 window.location.pathname，
 *   自动匹配到正确的页面组件并加载对应 JS chunk。
 *   不需要 URL 重写、占位页跳转或路由匹配脚本。
 *
 * 该脚本通过 package.json 的 postbuild 钩子自动运行。
 */
'use strict'

const fs = require('fs')
const path = require('path')

const OUT_DIR = path.resolve(__dirname, '../out')
const SRC = path.join(OUT_DIR, 'index.html')
const DST = path.join(OUT_DIR, '_spa-fallback.html')

const GREEN = '\x1b[32m'
const YELLOW = '\x1b[33m'
const RED = '\x1b[31m'
const RESET = '\x1b[0m'

if (!fs.existsSync(OUT_DIR)) {
  console.log(`${YELLOW}[spa-fallback] out/ 不存在，跳过（非静态导出构建）${RESET}`)
  process.exit(0)
}

if (!fs.existsSync(SRC)) {
  console.log(`${RED}[spa-fallback] out/index.html 不存在，静态导出可能失败${RESET}`)
  process.exit(1)
}

fs.copyFileSync(SRC, DST)
console.log(`${GREEN}[spa-fallback] 已复制 ${path.relative(process.cwd(), SRC)} → ${path.relative(process.cwd(), DST)}${RESET}`)
