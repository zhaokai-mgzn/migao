// case_ids: BM-019
/**
 * H5 产物 ES2020 门禁（issue #8302，真机取证：商米 V2s / WebView 83 / `/b/` 整屏白）
 *
 * 钉的是**构建产物**那一层，不是源码那一层：`node_modules` 里的依赖不进 babel，
 * 一句 ES2021 逻辑赋值（`x &&= y`）就能让老 WebView 整包 SyntaxError —— 页面全白，
 * 而桌面 / 新机型（支持 ES2021）**一切正常**，所以只靠"我这儿能打开"永远发现不了。
 *
 * 判据：
 *  1. 产物里有 ES2021 语法 ⇒ `--check` **非零退出**并具名（现状回归时会红）；
 *  2. 降级后**能按 ES2020 解析**，再 `--check` 通过（修法真的生效，不是"扫了一眼"）；
 *  3. 本来就能按 ES2020 解析的产物**逐字节不动**（不给正常产物制造 churn）；
 *  4. **接线**：`build:h5` 之后必须自动跑这道门禁（`postbuild:h5`），否则脚本再对也没人调用。
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const { parse } = require('acorn')

const APP_ROOT = resolve(__dirname, '..')
const SCRIPT = join(APP_ROOT, 'scripts/h5-es2020.mjs')

/** ES2021 逻辑赋值 —— 设备 WebView 83 解析不了的**最小样本**（正是 #8302 的形态）。 */
const ES2021_SAMPLE = 'var a = 1;\na &&= 2;\nconsole.log(a);\n'
/** ES2020 干净样本：降级器**不该动它**。 */
const ES2020_SAMPLE = 'var a = 1;\nif (a) { a = 2; }\nconsole.log(a);\n'

function run(args: string[]) {
  try {
    const out = execFileSync('node', [SCRIPT, ...args], {
      cwd: APP_ROOT,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    return { code: 0, out }
  } catch (e: any) {
    return { code: e.status ?? 1, out: `${e.stdout ?? ''}${e.stderr ?? ''}` }
  }
}

function dist(files: Record<string, string>) {
  const dir = mkdtempSync(join(tmpdir(), 'h5-es2020-'))
  mkdirSync(join(dir, 'js'), { recursive: true })
  for (const [name, body] of Object.entries(files)) writeFileSync(join(dir, name), body)
  return dir
}

describe('h5 产物 ES2020 门禁（issue #8302）', () => {
  it('ES2021 产物 --check ⇒ 非零退出且具名（红证）', () => {
    const dir = dist({ 'js/app.js': ES2021_SAMPLE })
    try {
      const r = run(['--dist=' + dir, '--check'])
      expect(r.code).not.toBe(0)
      expect(r.out).toContain('js/app.js')
      expect(r.out).toContain('ES2020')
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('降级后按 ES2020 可解析，再 --check 通过（修法生效）', () => {
    const dir = dist({ 'js/app.js': ES2021_SAMPLE })
    try {
      expect(run(['--dist=' + dir]).code).toBe(0)
      const code = readFileSync(join(dir, 'js/app.js'), 'utf8')
      expect(() => parse(code, { ecmaVersion: 2020, sourceType: 'script' })).not.toThrow()
      expect(run(['--dist=' + dir, '--check']).code).toBe(0)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('本来就能按 ES2020 解析的产物逐字节不动', () => {
    const dir = dist({ 'js/clean.js': ES2020_SAMPLE })
    try {
      expect(run(['--dist=' + dir]).code).toBe(0)
      expect(readFileSync(join(dir, 'js/clean.js'), 'utf8')).toBe(ES2020_SAMPLE)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('接线：build:h5 之后自动跑门禁（postbuild:h5）', () => {
    const pkg = JSON.parse(readFileSync(join(APP_ROOT, 'package.json'), 'utf8'))
    expect(pkg.scripts['postbuild:h5']).toContain('scripts/h5-es2020.mjs')
  })
})
