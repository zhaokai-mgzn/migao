// e2e/lib/source-hash.js — 源码内容指纹（无外部依赖，供构建指纹脚本与 e2e 新鲜度护栏共用）
/**
 * 为什么不用 mtime 单独判定：`git checkout` / 换机 / 解压 / 时区/时钟偏差都会改 mtime 而与内容无关，
 * mtime 只是「大概率对」。内容指纹（sha256 over src/ + config/ 的「相对路径 + 内容」）与时间无关：
 *   - 只改 mtime、内容不变 → 指纹不变（不再误报陈旧）
 *   - 内容真变了 → 指纹必变（不再漏报）
 */
const fs = require('fs')
const path = require('path')
const crypto = require('crypto')

/** 影响小程序构建产物的源码根目录 */
const SOURCE_ROOTS = ['src', 'config']

/** 递归列出文件（跳过 macOS 垃圾文件与构建产物目录） */
function listFiles(dir) {
  const acc = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === '.DS_Store') continue
    const p = path.join(dir, entry.name)
    if (entry.isDirectory()) acc.push(...listFiles(p))
    else acc.push(p)
  }
  return acc
}

/** 计算源码内容指纹：返回 { hash, files, newest: {file, mtimeMs} }（newest 供 mtime 兜底判据使用） */
function computeSourceHash(projectRoot) {
  const entries = []
  let newest = null
  for (const root of SOURCE_ROOTS) {
    const abs = path.join(projectRoot, root)
    if (!fs.existsSync(abs)) continue
    for (const file of listFiles(abs)) {
      const stat = fs.statSync(file)
      entries.push({ rel: path.relative(projectRoot, file), abs: file })
      if (!newest || stat.mtimeMs > newest.mtimeMs) newest = { file, mtimeMs: stat.mtimeMs }
    }
  }
  // 路径排序保证与文件系统返回顺序无关（同一份内容任何机器都算出同一指纹）
  entries.sort((a, b) => (a.rel < b.rel ? -1 : a.rel > b.rel ? 1 : 0))
  const hash = crypto.createHash('sha256')
  for (const e of entries) {
    hash.update(e.rel)
    hash.update('\0')
    hash.update(fs.readFileSync(e.abs))
    hash.update('\0')
  }
  return { hash: hash.digest('hex'), files: entries.length, newest }
}

module.exports = { computeSourceHash, SOURCE_ROOTS }
