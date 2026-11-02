'use strict'
/**
 * 仓库文本语料的**读面**（唯一实现）—— issue #6594
 *
 * ## 病（issue #6594，本机实测）
 *
 * 原先的 `readCorpus(['frontend', 'backend'])` **遍历工作树** ⇒ 会扫到**被 `.gitignore` 命中 / 未跟踪**的
 * 本地产物。实证：`backend/ai-agent-service/coverage.json`（python coverage 的输出，496KB，里面天然
 * 含大量数字字面量，**包括打印头宽的像素口径**）⇒ 本机判红、CI（干净检出里没有这个文件）判绿
 * = **本机红 / CI 绿的分裂**，人跑去修一个不存在的问题。
 *
 * ## 修法（选 A：读 git 索引；理由 = 结构性同口径，不是排除清单）
 *
 * 语料 = **git 索引里已跟踪的文件** = CI 干净检出的那一份。同口径是**构造出来的**：
 * CI 的检出里**只有**被跟踪的文件 ⇒ 「扫工作树」与「扫索引」在 CI 上恒等，在本机才分叉。
 * 替代方案（把已知产物名列进排除清单）必然漏 —— 任何新产物名都要人来补，漏的那天就复发。
 *
 * ## `source: 'worktree'` 是什么
 *
 * **旧读面**，只保留给判据做**单变量对照**（同一夹具、只换读面 ⇒ 必须红：证明夹具真的能红，
 * 而不是「两边都绿所以看着没问题」）。**生产守卫不使用它**。
 * 判据 = `tests/unit_ci_workflows/test_bmini_corpus_read_face.py`。
 *
 * ## 选项 A 的残余（**出声**，不静默）
 *
 * 索引读不到**还没 `git add`** 的新文件 ⇒ 本地把违规写进新文件时守卫会绿。故 `untrackedCodeFiles()`
 * 把「扫得到但没进索引」的代码文件列出来，由守卫 `console.warn` 打印（**不判红**：本地建文件未
 * `git add` 是常态，判红会把「本机红 / CI 绿」的分裂原样造回来，只是方向相反）。
 *
 * 读不到（不是 git 仓 / 缺 git / 参数错）⇒ **抛错**（fail-closed：不允许退化成「空语料 = 通过」）。
 */

const { execFileSync } = require('child_process')
const fs = require('fs')
const path = require('path')

/** 参与文本判定的扩展名（与旧 `walk()` 逐字相同） */
const CODE_EXT = /\.(ts|tsx|js|jsx|mjs|json)$/
/** 跳过产物目录（与旧 `walk()` 逐字相同；现取索引里 0 个文件落在这些段下，保留 = 口径不因本单漂移） */
const SKIP_DIRS = new Set(['node_modules', 'dist', 'coverage', '.next', 'build', '.git'])

/** 路径段级过滤（等价于旧 `walk()` 的「跳隐藏项（`.github` 除外）+ 跳产物目录 + 只收代码扩展名」） */
function keep(rel) {
  for (const seg of rel.split('/')) {
    if (SKIP_DIRS.has(seg)) return false
    if (seg.startsWith('.') && seg !== '.github') return false
  }
  return CODE_EXT.test(rel)
}

function git(repoRoot, args) {
  return execFileSync('git', args, {
    cwd: repoRoot,
    encoding: 'utf8',
    maxBuffer: 256 * 1024 * 1024,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
}

/** 索引读面：只读**已跟踪**文件（= CI 干净检出那一份） */
function trackedFiles(repoRoot, roots) {
  const raw = git(repoRoot, ['ls-files', '-z', '--', ...roots])
  return raw.split('\0').filter(Boolean).filter(keep).sort()
}

/** 未跟踪且**未被 ignore** 的代码文件（选项 A 的残余，供守卫出声；不参与判决） */
function untrackedCodeFiles({ repoRoot, roots } = {}) {
  if (!repoRoot || !Array.isArray(roots) || roots.length === 0) {
    throw new Error('untrackedCodeFiles 缺 repoRoot / roots（空射程 = 空断言）')
  }
  const raw = git(repoRoot, ['ls-files', '--others', '--exclude-standard', '-z', '--', ...roots])
  return raw.split('\0').filter(Boolean).filter(keep).sort()
}

/** 旧读面（工作树遍历）——**只给判据做单变量对照**，生产路径不要用 */
function worktreeFiles(repoRoot, roots) {
  const out = []
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name.startsWith('.') && entry.name !== '.github') continue
      if (SKIP_DIRS.has(entry.name)) continue
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) walk(full)
      else if (CODE_EXT.test(entry.name)) {
        out.push(path.relative(repoRoot, full).split(path.sep).join('/'))
      }
    }
  }
  for (const root of roots) {
    const abs = path.join(repoRoot, root)
    if (!fs.existsSync(abs)) continue
    if (fs.statSync(abs).isFile()) out.push(root.split(path.sep).join('/'))
    else walk(abs)
  }
  return out.sort()
}

/** 读面分派（默认 = 索引；未知读面 ⇒ 抛错，不静默退化成空） */
function listFiles(repoRoot, roots, source = 'index') {
  if (source === 'index') return trackedFiles(repoRoot, roots)
  if (source === 'worktree') return worktreeFiles(repoRoot, roots)
  throw new Error(`未知的语料读面：${source}（只接受 index / worktree）`)
}

/** 读语料正文：`[{ rel, code }]`，`rel` 是仓库相对路径（`/` 分隔） */
function readCorpus({ repoRoot, roots, source = 'index' } = {}) {
  if (!repoRoot) throw new Error('readCorpus 缺 repoRoot')
  if (!Array.isArray(roots) || roots.length === 0) throw new Error('readCorpus 缺 roots（空射程 = 空断言）')
  return listFiles(repoRoot, roots, source).map((rel) => ({
    rel,
    code: fs.readFileSync(path.join(repoRoot, rel), 'utf8'),
  }))
}

// ── CLI（给 Python 判据用：`node trackedCorpus.js --repo <dir> --roots a,b [--source index|worktree]`）──
if (require.main === module) {
  const argv = process.argv.slice(2)
  const arg = (name) => {
    const i = argv.indexOf(`--${name}`)
    return i >= 0 ? argv[i + 1] : undefined
  }
  const repoRoot = path.resolve(arg('repo') || '.')
  const roots = (arg('roots') || '').split(',').filter(Boolean)
  const source = arg('source') || 'index'
  if (roots.length === 0) {
    console.error('用法: node trackedCorpus.js --repo <dir> --roots a,b [--source index|worktree]')
    process.exit(2)
  }
  try {
    const out = { source, roots, files: listFiles(repoRoot, roots, source) }
    if (source === 'index') out.untracked = untrackedCodeFiles({ repoRoot, roots })
    process.stdout.write(JSON.stringify(out, null, 2) + '\n')
  } catch (err) {
    // 不可判定 ⇒ 非零退出（**不得**让调用方把「读不到」读成「空语料 = 通过」）
    console.error(`语料读面失败（不可判定 ⇒ 非零退出，不得当空语料读）：${err.message}`)
    process.exit(2)
  }
}

module.exports = {
  CODE_EXT,
  SKIP_DIRS,
  keep,
  listFiles,
  readCorpus,
  trackedFiles,
  untrackedCodeFiles,
  worktreeFiles,
}
