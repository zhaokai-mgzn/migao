#!/usr/bin/env node
/**
 * H5 产物「老 WebView 可跑」门禁（issue #8302）
 *
 * 病（真机取证，2026-11-01）：Taro 只把 `src/` 交给 babel，`node_modules/` 原样进包 ——
 * `@tarojs/router` 的依赖 `query-string@9.5.0` 同时用了两样 WebView 83 没有的东西：
 *   ① **ES2021 语法** `x &&= y` ⇒ 整包 SyntaxError（连一行业务代码都跑不到）；
 *   ② **ES2021 API** `String.prototype.replaceAll`（Chrome 85+）⇒ 路由解析时 TypeError。
 * 商米手持机的系统 WebView 是 **Chrome 83（ES2020 上限）**，于是 `/b/` **整屏白**
 * （等 15 秒仍白），拍照入库 / 补打入库标签 / 拍照发货全部走不到。
 *
 * 法（构建后处理，逐条都对着一个真机事实）：
 *   ① 语法：已经能按 ES2020 解析的**逐字节不动**；解析不了的用 esbuild 降到 ES2020（minify）后复核；
 *   ② API：产物里出现 `replaceAll(` 且还没垫片 ⇒ **在文件最前面**注入 ES5 写的 `replaceAll` 垫片
 *      （WebView 83 上原样补上规范语义；新浏览器走原实现，一行不执行）；
 *   ③ 降完 / 垫完仍不合格 ⇒ **非零退出** + 具名（不许「降不了就放过」）。
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

/** 垫片标记：出现即「这份产物已经处理过」，保证重复跑幂等。 */
export const COMPAT_MARK = '/*migao-compat:replaceAll*/'

/**
 * `String.prototype.replaceAll` 的 ES5 垫片（WebView 83 没有它）。
 * 规范语义里两处容易写错的地方都照着做了：字符串 pattern 的替换串**不解析 `$&`**；
 * 非全局正则直接 TypeError（与原生一致）。
 */
export const COMPAT_PRELUDE = String.raw`/*migao-compat:replaceAll*/
(function () {
  if (typeof String.prototype.replaceAll === 'function') return;
  String.prototype.replaceAll = function (search, replacement) {
    var src = String(this);
    if (search instanceof RegExp) {
      if (!search.global) throw new TypeError('replaceAll must be called with a global RegExp');
      return src.replace(search, replacement);
    }
    var needle = String(search).replace(/[.*+?^$()|[\]{}\\]/g, '\\$&');
    var pattern = new RegExp(needle, 'g');
    return src.replace(pattern, typeof replacement === 'function' ? replacement : function () { return replacement; });
  };
})();
`

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

/** 需要垫片的产物：用了 `replaceAll(` 且还没注入过。 */
function needsReplaceAllShim(code) {
  return /\.replaceAll\s*\(/.test(code) && !code.includes(COMPAT_MARK)
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
const shimmed = []
const failed = []

for (const file of files) {
  const rel = file.slice(DIST.length + 1)
  let code = readFileSync(file, 'utf8')
  let changed = false

  if (parseable(code) !== true) {
    if (CHECK_ONLY) {
      failed.push(`${rel}: 不是 ES${EC_TARGET} 语法（${parseable(code)}）`)
      continue
    }
    code = esbuild.transformSync(code, { target: `es${EC_TARGET}`, loader: 'js', minify: true }).code
    downleveled.push(rel)
    changed = true
  }

  if (needsReplaceAllShim(code)) {
    if (CHECK_ONLY) {
      failed.push(`${rel}: 用了 String.prototype.replaceAll（Chrome 85+，WebView 83 没有）且无垫片`)
      continue
    }
    code = COMPAT_PRELUDE + code
    shimmed.push(rel)
    changed = true
  }

  if (!changed) continue
  writeFileSync(file, code)

  const after = parseable(code)
  if (after !== true) failed.push(`${rel}: 处理后仍解析失败（${after}）`)
}

if (failed.length) {
  console.error(`❌ h5 产物「老 WebView 可跑」门禁失败（${failed.length} 份）：`)
  for (const line of failed) console.error(`   - ${line}`)
  process.exit(1)
}

const verb = CHECK_ONLY ? '复核' : '处理'
console.log(
  `✅ h5 产物 ES${EC_TARGET} 门禁通过：扫描 ${files.length} 份 js，${verb} ${downleveled.length + shimmed.length} 份` +
    `（降级 ${downleveled.length}${downleveled.length ? '：' + downleveled.join(', ') : ''}；` +
    `垫片 ${shimmed.length}${shimmed.length ? '：' + shimmed.join(', ') : ''}）`,
)
