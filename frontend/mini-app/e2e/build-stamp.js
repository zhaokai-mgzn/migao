// e2e/build-stamp.js — 构建指纹落盘（由 `npm run build:weapp` 的 && 链在 taro build 之后调用）
/**
 * 写 `dist/.build-stamp.json` = { hash, files, builtAt }，hash 为 src/ + config/ 的内容指纹。
 * e2e 的新鲜度护栏（e2e/lib/harness.js: assertDistFresh）优先比对指纹，指纹缺失时才退回 mtime。
 *
 * 位置说明：本脚本放在 e2e/ 下而非 scripts/ —— 它是**新鲜度护栏的配套设施**，
 * 与护栏同生命周期、同归属（frontend/mini-app/e2e/**）。
 */
const fs = require('fs')
const path = require('path')
const { computeSourceHash } = require('./lib/source-hash')

const PROJECT_ROOT = path.resolve(__dirname, '..')
const DIST_DIR = path.join(PROJECT_ROOT, 'dist')
const STAMP_PATH = path.join(DIST_DIR, '.build-stamp.json')

function main() {
  if (!fs.existsSync(DIST_DIR)) {
    // 构建失败/产物目录缺失时不写指纹 —— 否则会凭空造出一个「看起来已构建」的 dist
    console.error('[build-stamp] ✖ 未找到 dist/ —— 构建未成功，拒绝写入构建指纹')
    process.exit(1)
  }
  const { hash, files } = computeSourceHash(PROJECT_ROOT)
  const stamp = {
    hash,
    files,
    sourceRoots: ['src', 'config'],
    builtAt: new Date().toISOString(),
    builder: 'e2e/build-stamp.js',
  }
  fs.writeFileSync(STAMP_PATH, `${JSON.stringify(stamp, null, 2)}\n`, 'utf8')
  console.log(`[build-stamp] ✔ 已写入 dist/.build-stamp.json（源码指纹 ${hash.slice(0, 12)}… / ${files} 个文件 / ${stamp.builtAt}）`)
}

main()
