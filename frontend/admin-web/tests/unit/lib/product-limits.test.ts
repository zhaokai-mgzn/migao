// case_ids: PR-008, PR-020
/**
 * 商品表单上限常量的**一处定义**守卫（issue #6354）。
 *
 * 为什么需要这个文件：`COLOR_NAME_MAX` / `MAX_COLORS` / `MAX_SKUS` 原先只写在
 * `components/products/SkuMatrix.tsx` 里；图片识别预填（`lib/image-recognize.ts`）是**第二个**
 * 消费点，它不 import 组件（那会把 React 拉进纯函数库）⇒ 上限被抽到 `lib/product-limits.ts`。
 * 抽出来之后必须钉住两件事，否则「一处定义」会退化成「三处各写一份」：
 *
 * ① **组件真的用这份常量**（不是在组件里重新写死 30/200/600）；
 * ② 常量的**值**不变（改小会让识别预填被输入框静默截断 —— 那正是 #6354 的病灶）。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { COLOR_NAME_MAX, MAX_COLORS, MAX_SKUS } from '@/lib/product-limits'

const read = (rel: string) => readFileSync(resolve(process.cwd(), rel), 'utf-8')

describe('商品表单上限常量 (#6354)', () => {
  it('值与表单既有口径一致（30 / 200 / 600）', () => {
    expect([COLOR_NAME_MAX, MAX_COLORS, MAX_SKUS]).toEqual([30, 200, 600])
  })

  it('SkuMatrix 消费这份常量，且不再写死数字', () => {
    const src = read('src/components/products/SkuMatrix.tsx')

    expect(src).toMatch(/import\s*\{[^}]*COLOR_NAME_MAX[^}]*\}\s*from\s*'@\/lib\/product-limits'/)
    // 颜色行名称框的上限必须挂常量（写死 30 ⇒ 本断言红）
    expect(src).toContain('maxLength={COLOR_NAME_MAX}')
    // 组件里不得再有 `const COLOR_NAME_MAX = 30` 之类的第二份定义
    expect(src).not.toMatch(/const\s+(COLOR_NAME_MAX|MAX_COLORS|MAX_SKUS)\s*=/)
  })

  it('图片识别预填侧也消费同一份上限（拆行后每格都得进得去）', () => {
    const src = read('src/lib/image-recognize.ts')

    expect(src).toMatch(/from\s*'\.\/product-limits'/)
  })
})
