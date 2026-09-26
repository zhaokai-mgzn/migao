/**
 * h5 平台能力两张清单的**唯一抽取实现**（issue #5650 原实现；issue #5654 起被两个守卫共用）。
 *
 * 为什么抽成共享 helper：`tests/h5-platform-api-guard.test.ts`（#5650，射程 = 全 `src/**`）
 * 与 `tests/admin-surfaces-guard.test.ts`（#5654，射程 = 管理面 4 项）都要问同一个问题
 * ——「这个 Taro API 在 h5 上究竟能不能用」。**两处各抄一份抽取逻辑 = 第二份会漂的口径**
 * （本仓明令禁止；#5346 的「同一真值两处投影」正是这一族）。
 *
 * 权威源 = 实现包 `node_modules/@tarojs/taro-h5/dist`，两张清单：
 *   ① **明确不实现** = `temporarilyNotSupport('<api>')`；
 *   ② **只在微信内置浏览器可用** = `processOpenApi({…})` 且**无 `standardMethod`**。
 * 读不到实现包 / 抽不出清单 ⇒ 抛错（fail-closed：**不允许**退化成「0 命中 = 通过」）。
 */
import fs from 'fs'
import path from 'path'

/** `<repo>/frontend/bmini-app`（本文件在 `tests/helpers/`） */
export const BMINI_ROOT = path.join(__dirname, '..', '..')
export const SRC_DIR = path.join(BMINI_ROOT, 'src')
export const TARO_H5_DIST = path.join(BMINI_ROOT, 'node_modules', '@tarojs', 'taro-h5', 'dist')

export const SOURCE_EXT = /\.(ts|tsx)$/

export function walk(
  dir: string,
  keep: (name: string) => boolean,
  out: string[] = [],
): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(full, keep, out)
    else if (keep(entry.name)) out.push(full)
  }
  return out
}

/** Taro h5 实现包的全部 `.js`（唯一权威清单的来源） */
export function distJsFiles(): string[] {
  if (!fs.existsSync(TARO_H5_DIST)) {
    throw new Error(
      `找不到 Taro h5 实现包：${TARO_H5_DIST}（守卫 fail-closed：读不到权威清单的「绿」不算绿 —— 先 npm ci）`,
    )
  }
  const files = walk(TARO_H5_DIST, (name) => name.endsWith('.js'))
  if (files.length === 0) throw new Error(`实现包里一个 .js 都没有：${TARO_H5_DIST}`)
  return files
}

/** 清单 A：Taro h5「明确不实现」的 API 名 */
export function unsupportedApis(): Set<string> {
  const out = new Set<string>()
  for (const file of distJsFiles()) {
    const text = fs.readFileSync(file, 'utf8')
    for (const match of text.matchAll(/temporarilyNotSupport\('([A-Za-z_$][\w$]*)'\)/g)) {
      out.add(match[1])
    }
  }
  if (out.size < 100) {
    throw new Error(`清单 A 只抽到 ${out.size} 条（预期数百条）⇒ 抽取口径已漂移，判红而不是判绿`)
  }
  return out
}

/** 清单 B：h5 实现**只**走微信 JS-SDK 的 API 名（`processOpenApi` 且无 `standardMethod`） */
export function jsSdkOnlyApis(): Set<string> {
  const out = new Set<string>()
  const re =
    /(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*\/\* @__PURE__ \*\/\s*processOpenApi\(\{([\s\S]*?)\n\}\);/g
  for (const file of distJsFiles()) {
    const text = fs.readFileSync(file, 'utf8')
    for (const match of text.matchAll(re)) {
      if (!/standardMethod/.test(match[2])) out.add(match[1])
    }
  }
  // 机制存活读数：抽取口径一漂移就会连扫描码都抽不到 ⇒ 当场判红（而不是「面变窄了但没人知道」）
  if (!out.has('scanCode')) {
    throw new Error('清单 B 抽取失效：连 scanCode 都没抽到 ⇒ 判红而不是判绿')
  }
  return out
}

/**
 * 去掉注释后再扫用法 —— 否则**说明文字里的引用会被当成使用**
 * （`migao-dev-flow` §17.3：内容扫描式机制分不清「引用」与「使用」；
 *  实证：`src/utils/platform.ts` 的 JSDoc 里写了 `Taro.scanCode` 就被算成一处命中）。
 * 只处理 `//` 与块注释；`https://` 里的 `//` 用 `[^:]` 前缀排除。
 */
export function stripComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

export interface TaroUsage {
  api: string
  file: string
}

/** 本仓 `src/**` 里全部 `Taro.<api>` 用法（含类型引用如 `Taro.RequestTask`，无害） */
export function taroUsages(): TaroUsage[] {
  const out: TaroUsage[] = []
  for (const file of walk(SRC_DIR, (name) => SOURCE_EXT.test(name))) {
    const rel = path.relative(BMINI_ROOT, file)
    const text = stripComments(fs.readFileSync(file, 'utf8'))
    for (const match of text.matchAll(/\bTaro\.([A-Za-z_$][\w$]*)/g)) {
      out.push({ api: match[1], file: rel })
    }
  }
  return out
}

/** 指定文件里的 `Taro.<api>` 用法（去掉注释后扫） */
export function taroApisInFile(absFile: string): string[] {
  const text = stripComments(fs.readFileSync(absFile, 'utf8'))
  return Array.from(text.matchAll(/\bTaro\.([A-Za-z_$][\w$]*)/g)).map((match) => match[1])
}

/** 该文件是否引入了平台判别模块（= 有显式平台分支的机械可判形态） */
export function hasPlatformBranch(relFile: string): boolean {
  const text = fs.readFileSync(path.join(BMINI_ROOT, relFile), 'utf8')
  return /from\s+['"][^'"]*\/platform['"]/.test(text) || /from\s+['"]\.\/platform['"]/.test(text)
}
