// case_ids: UI-133
/**
 * 类级元守卫（issue #7526）：**「点开关才出现的浮层」不得被「列表非空」门控**。
 *
 * ## 病灶（用户 2026-10-23 客户详情截图 + 逐字「当系统没有标签时，点击+号无反应，应该引导客户去添加标签」）
 *
 * 客户详情「标签」卡片写成：
 *
 * ```tsx
 * {showTagPicker && availableTags.length > 0 && ( <浮层/> )}
 * ```
 *
 * 点「+」只翻转了 `showTagPicker`，而 `availableTags` 为空时浮层**永不渲染** ⇒ 触发器
 * 「可点但零反馈」，用户以为按钮坏了。本仓当时恰有 **1 处**这种形态（= 本单病灶），
 * 其余 `.length > 0 &&` 的用法都不是「state 开合的浮层」，因此本条判据可以要求**零容忍**。
 *
 * ## 判据（都会红）
 *
 * 1. `src/**` 里**不得**出现「`{showXxx && 某处.length > 0 && ...}`」这一形态
 *    —— 修前 1 处（`frontend/admin-web/src/app/(dashboard)/customers/[id]/CustomerDetail.tsx`），修后 0 处；
 * 2. **判别力自证**：把修前那一行原样注入内存语料 ⇒ 必须命中；`{showX && (`、`{list.length > 0 && (`
 *    两种良性写法 ⇒ 必须不命中（不制造假红）；
 * 3. 扫描面非空（`scanned > 100`）：空集比空集的「绿」是假绿（同 `preset-anchor-check` 的空集教训）。
 *
 * ## 正确形态（修后可抄）
 *
 * 浮层**每次**都渲染；没有内容可放时给**空态 + 可点去处**，例如客户详情里的
 * `data-testid="customer-tag-empty"` +「去添加标签」→ `/customers?manageTags=1`。
 *
 * ## 边界（如实登记，§19.1）
 *
 * - 只认这一种表达式形态（`&&` 串联 + `.length > 0`）。三元、早返回、抽到子组件里再判空等
 *   写法**不在射程内** —— 这是边界，不是豁免：判不到的部分仍由评审 + 行为判据（
 *   `tests/unit/pages/customer-detail-tags-empty.test.tsx`）承担。
 * - 不判「浮层样式 / 文案好不好」；那是 §31 / §15.7 的读图与人裁定。
 */
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const ROOT = join(__dirname, '..', '..')
const SRC = join(ROOT, 'src')

/**
 * 病灶形态：`{showXxx && ...某处.length > 0 && (`。
 *
 * 收得**很紧**（`show` 前缀 + `&&` + `.length > 0` + `&&`），是因为全仓恰好只有本单这一处；
 * 放得越宽（比如允许任意 state 名）假红越多，守卫就会被加白名单加死。
 */
const EMPTY_GATE = /\{show[A-Za-z0-9_]*\s*&&\s*[A-Za-z0-9_$.\[\]()]*\.length\s*>\s*0\s*&&/g

/**
 * 剥掉**整行注释**（行首双斜杠、块注释起始行、JSDoc 续行 ` * `）—— 注释是文档，可以在里面写反例；
 * 不剥的话「举例说明禁忌」= 自己犯禁忌（§2.2「引用即实例」的同族坑）。
 * 行号不受影响（整行内容换成空串、换行保留）。
 *
 * 边界（如实登记）：**行尾内联注释**不剥 ⇒ 仍会命中；那属极少数，且改法就是把它挪到独立整行。
 */
function stripLineComments(content: string): string {
  return content.replace(/^[ \t]*(\/\/|\/\*|\*).*$/gm, '')
}

function collect(abs: string): string[] {
  const st = statSync(abs)
  if (st.isFile()) return [abs]
  return readdirSync(abs).flatMap((name) => {
    const child = join(abs, name)
    return statSync(child).isDirectory() ? collect(child) : [child]
  })
}

function sourceFiles(): string[] {
  return collect(SRC)
    .filter((f) => /\.(ts|tsx)$/.test(f) && !f.endsWith('.d.ts'))
    .sort()
}

/** 在**整个文件内容**上找命中（JSX 常跨行 ⇒ 不许逐行扫），返回 `相对路径:行号`（行号只进报错信息） */
function findEmptyGatedPopovers(contents: Array<{ file: string; content: string }>): string[] {
  const hits: string[] = []
  for (const { file, content } of contents) {
    const code = stripLineComments(content)
    for (const m of code.matchAll(EMPTY_GATE)) {
      const line = code.slice(0, m.index ?? 0).split('\n').length
      hits.push(`${relative(ROOT, file)}:${line} ${m[0].replace(/\s+/g, ' ')}`)
    }
  }
  return hits
}

describe('类级守卫：state 开合的浮层不得被「列表非空」门控（issue #7526）', () => {
  it('判据 1：src/** 里 0 处「{showX && list.length > 0 && …}」（修前 1 处 = 本单病灶）', () => {
    const files = sourceFiles()
    // 判据 3：扫描面非空 —— 目录写错 / 收集器坏了不许假绿
    expect(files.length).toBeGreaterThan(100)

    const hits = findEmptyGatedPopovers(files.map((f) => ({ file: f, content: readFileSync(f, 'utf8') })))
    expect(
      hits,
      `这些浮层被「列表非空」门控 ⇒ 列表为空时触发器点了没反应（issue #7526 同族）。` +
        `正确形态：浮层每次都渲染，没有内容时给空态 + 可点去处。命中：\n${hits.join('\n')}`,
    ).toEqual([])
  })

  it('判据 2：判别力自证 —— 修前那一行原样注入必须命中，良性写法必须放行', () => {
    const bad = [
      {
        file: join(SRC, 'app/(dashboard)/customers/[id]/CustomerDetail.tsx'),
        content: `
          {showTagPicker && availableTags.length > 0 && (
            <div className="floating">…</div>
          )}
        `,
      },
      {
        // 变体：带对象链 / 空格变化，仍属同族
        file: join(SRC, 'app/(dashboard)/demo/page.tsx'),
        content: `{showMenu && rows.value.length  >  0 && (<div />)}`,
      },
    ]
    expect(findEmptyGatedPopovers(bad)).toHaveLength(2)

    const benign = [
      // 浮层只被 state 门控（修后形态：内容里再分支）
      { file: join(SRC, 'a.tsx'), content: `{showPicker && (<div>{list.length > 0 ? 'x' : '空态'}</div>)}` },
      // 无 state 门控的常规空集判断
      { file: join(SRC, 'b.tsx'), content: `{list.length > 0 && (<ul />)}` },
      // 注释里提到这个形态不算（禁的是代码形态；注释是文档）
      { file: join(SRC, 'c.tsx'), content: `// 反例：{showX && list.length > 0 && (…)} 是病态` },
    ]
    expect(findEmptyGatedPopovers(benign)).toEqual([])
  })
})
