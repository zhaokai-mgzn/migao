#!/usr/bin/env node
/**
 * H5 产物 ES2020 门禁（issue #8302）
 *
 * 病（真机取证，2026-11-01）：Taro 只把 `src/` 交给 babel，`node_modules/` 原样进包 ——
 * `@tarojs/router` 的依赖 `query-string@9.5.0` 带 **ES2021 逻辑赋值**（`x &&= y`），
 * 于是 `/b/js/app.js` 在 **WebView 83（ES2020 上限）** 上整包 SyntaxError：
 * 商米手持机打 `/b/` 是**整屏白**（等 15 秒仍白），拍照入库 / 补打入库标签 / 拍照发货全部走不到。
 *
 * 法：构建结束后扫 `dist/**\/*.js` ——
 *   ① 已经能按 ES2020 解析的**逐字节不动**（不给正常产物制造 churn、不改引用名）；
 *   ② 解析不了的用 esbuild 降到 ES2020（保留 minify，体积不涨）；
 *   ③ 降完仍解析不了 ⇒ **非零退出** + 具名文件与报错（不许「降不了就放过」）。
 *
 * 用法：node scripts/h5-es2020.mjs [--dist=<目录>] [--check]
 *   `--check`：只判不写（发布后自证 / 排查线上产物用）。
 *
 * 为什么不用 browserslist 一行搞定：`package.json` 的 browserslist 是
 * `last 3 versions / Android >= 4.1`（看起来够老），但 webpack 对 `node_modules` 走的是
 * **依赖自带的那份构建产物**，babel 根本不进去 ⇒ 目标写在 browserslist 里等于没写。
 */
import { readFileSync, writeFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { parse } = require('acorn')
const esbuild = require('esbuild')

/** 设备 WebView 83 = ES2020 上限（真机读数：`com.android.webview 83.0.4103.120`）。 */
const EC_TARGET = 2020

const APP_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function argValue(name) {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`))
  return hit ? hit.slice(name.length + 3) : null
}

const DIST = resolve(argValue('dist') || join(APP_ROOT, 'dist'))
const CHECK_ONLY = process.argv.includes('--check')

function parseable(code) {
  for (const sourceType of ['script', 'module']) {
    try {
      parse(code, { ecmaVersion: EC_TARGET, sourceType, allowHashBang: true })
      return true
    } catch (e) {
      if (sourceType === 'module') return e.message
    }
  }
  return false
}

function walkJs(dir, out = []) {
  for (const name of readdirSync(dir).sort()) {
    const full = join(dir, name)
    const st = statSync(full)
    if (st.isDirectory()) walkJs(full, out)
    else if (name.endsWith('.js')) out.push(full)
  }
  return out
}

if (!statSync(DIST, { throwIfNoEntry: false })) {
  console.error(`❌ 没有产物目录：${DIST}（先跑 \`npm run build:h5\`）`)
  process.exit(1)
}

const files = walkJs(DIST)
const downleveled = []
const failed = []

for (const file of files) {
  const src = readFileSync(file, 'utf8')
  if (parseable(src) === true) continue

  const rel = file.slice(DIST.length + 1)
  if (CHECK_ONLY) {
    failed.push(`${rel}: 不是 ES${EC_TARGET} 语法（${parseable(src)}）`)
    continue
  }

  const out = esbuild.transformSync(src, { target: `es${EC_TARGET}`, loader: 'js', minify: true })
  writeFileSync(file, out.code)
  downleveled.push(rel)

  const after = parseable(out.code)
  if (after !== true) failed.push(`${rel}: 降级后仍解析失败（${after}）`)
}

if (failed.length) {
  console.error(`❌ h5 产物 ES${EC_TARGET} 门禁失败（${failed.length} 份）：`)
  for (const line of failed) console.error(`   - ${line}`)
  process.exit(1)
}

const verb = CHECK_ONLY ? '复核' : '降级'
console.log(
  `✅ h5 产物 ES${EC_TARGET} 门禁通过：扫描 ${files.length} 份 js，${verb} ${downleveled.length} 份` +
    (downleveled.length ? `（${downleveled.join(', ')}）` : ''),
)
