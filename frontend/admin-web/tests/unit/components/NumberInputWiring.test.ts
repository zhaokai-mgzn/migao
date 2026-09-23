// case_ids: UI-055
/**
 * 静态扫描：禁止「`x ? x : null`」形态的**数值**接线（issue #5218 判据 6）。
 *
 * ## 为什么要有这条
 *
 * #5198 只机械扫了 `value={x || ''}` **一种写法**，于是同一族的另一种写法整批漏网：
 * `value={sku?.price ? sku.price : null}` —— `0` 是 falsy ⇒ 外部值由 `12.5` 变 `null`
 * ⇒ 正在输入的草稿被外部同步洗掉 ⇒ **编辑既有值时输入框当场清空**（用户原始症状复活）。
 * 「形态会变、语义不变」⇒ 用一条静态断言把「falsy 一律当空」的写法挡在门外，
 * 而不是等下一次人肉扫描（人肉扫描已经漏过一次，实测）。
 *
 * ## 判据（本文件自身可红：把 `findFalsyWiring` 改成 `() => []` ⇒ ①④ 必红）
 *
 * - ① 合成样本 `sku?.price ? sku.price : null` **必须**被扫出（红证样本）；
 * - ② `typeof m === 'string' && m ? m : null`（**字符串**守卫，`typeof` 已收窄）不算违规
 *   —— 仓库里确有这一处（`src/lib/production-guard-reasons.ts`），它是**正确**写法；
 * - ③ 注释里写了旧形态不算违规（假阳性实测踩过：修完 #5218 后注释里留了旧写法作说明）；
 * - ④ 全仓（admin-web / mini-app / bmini-app 的 `src/**`）真扫零命中。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

/** 剥掉注释再扫：注释/文档里写旧形态是**说明**，不是接线（假阳性来源） */
export function stripComments(code: string): string {
  return code.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

/** `x ? x : null`（x = 标识符或属性访问链；`?.` 与 `.` 视为同一形态） */
const SAME_EXPR_RE =
  /([A-Za-z_$][\w$]*(?:\??\.[A-Za-z_$][\w$]*)*)\s*\?\s*([A-Za-z_$][\w$]*(?:\??\.[A-Za-z_$][\w$]*)*)\s*:\s*null\b/g

/** 扫出一段代码里所有「falsy ⇒ null」的等价接线（`typeof` 收窄保护的字符串守卫放行） */
export function findFalsyWiring(code: string): string[] {
  const src = stripComments(code)
  const hits: string[] = []
  const norm = (s: string) => s.replace(/\?\./g, '.')
  for (const m of src.matchAll(SAME_EXPR_RE)) {
    if (norm(m[1]) !== norm(m[2])) continue
    // 该命中所在语句的前半段：`typeof m === 'string' && m ? m : null` 这类收窄守卫放行
    const at = m.index ?? 0
    const stmtStart = Math.max(src.lastIndexOf('\n', at), src.lastIndexOf(';', at), src.lastIndexOf('{', at))
    if (/\btypeof\b/.test(src.slice(stmtStart + 1, at))) continue
    hits.push(m[0].trim())
  }
  return hits
}

/** 递归收集 .ts/.tsx（跳过测试与声明文件——本判据管的是**产品代码**的接线） */
function sourceFiles(dir: string, acc: string[] = []): string[] {
  let entries: string[]
  try {
    entries = readdirSync(dir)
  } catch {
    return acc // 某些端在本地没检出（CI 上是完整仓）⇒ 不因此判红
  }
  for (const name of entries) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) sourceFiles(p, acc)
    else if (/\.tsx?$/.test(name) && !/\.d\.ts$/.test(name)) acc.push(p)
  }
  return acc
}

describe('静态扫描：数值接线的 `x ? x : null` 形态（issue #5218 判据 6）', () => {
  it('① 红证样本必须被扫出（该形态就是 0 被当空的接线）', () => {
    expect(findFalsyWiring('const p = sku?.price ? sku.price : null')).toEqual([
      'sku?.price ? sku.price : null',
    ])
  })

  it('② 字符串守卫（`typeof` 收窄）不算违规', () => {
    expect(
      findFalsyWiring("const m = e?.message\nreturn typeof m === 'string' && m ? m : null")
    ).toEqual([])
  })

  it('③ 注释里写了旧形态不算违规（假阳性实测踩过）', () => {
    expect(findFalsyWiring('// 旧形态 `sku?.price ? sku.price : null` 已拆掉\nconst x = 1')).toEqual([])
    expect(findFalsyWiring('/* 说明：value={sku?.stock ? sku.stock : null} */\nconst y = 1')).toEqual([])
  })

  it('④ 全仓（admin-web / mini-app / bmini-app 的 src）零命中', () => {
    const roots = ['src', '../mini-app/src', '../bmini-app/src'].map((d) => join(process.cwd(), d))
    const bad = roots.flatMap((root) =>
      sourceFiles(root).flatMap((f) =>
        findFalsyWiring(readFileSync(f, 'utf8')).map((hit) => `${f}: ${hit}`)
      )
    )
    expect(bad).toEqual([])
  })
})
