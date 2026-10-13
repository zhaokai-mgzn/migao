// case_ids: UI-097
// SSR→hydrate 见证器：把「块级元素落在 <p> 里」这一族在 **React 运行期**判红（issue #6799 判据 ②）。
//
// ## 为什么不能只做静态扫描
// `<p>{<SomeComponent/>}</p>` 这种**运行期组合**在源码面上看不见：`<p>` 的子节点是一个被引用的
// 组件，而这个组件渲染出 `<div>` / `<ul>` / `<table>` 还是 `<span>`，字面扫描判不了。真栈读数里
// 的宿主是 `components/common/DateTimeCell`（两行日期，根节点是 `<div>`）—— `AfterSalesDetail.tsx`
// 把它挂在 `<p>` 里，源码里一个字面 `<div>` 都没有（静态扫描 0 命中，见
// `frontend/admin-web/tests/unit/p-tag-block-nesting-guard.test.ts` 的说明）。
//
// ## 判据为什么可信（同一条件、同一读数）
// 真栈（真浏览器 `/after-sales/[id]`）逐字打的是 React 的两条 `console.error`：
//   `In HTML, <div> cannot be a descendant of <p>.\nThis will cause a hydration error.` +
//   `<p> cannot contain a nested <div>.`
// React 的 `validateDOMNesting` 只看**元素形状**（不看浏览器），所以同一形态在 jsdom 里**同样打这两条**
// （实测：`poc` 诊断里客户端渲染 `<p><div/></p>` ⇒ 两条都在；`<p><span/></p>` ⇒ 0 条）。
// 本见证器做的就是：`renderToString`（服务端） → 浏览器式解析 → `hydrateRoot`（客户端），
// 收集 `console.error`，**要求"块级落在 `<p>` 里"这一类一条都不出现**。
//
// ## 边界（照实登记，§19.1）
// - 判的是**这一族**（React 的 DOM 嵌套校验），不是"整页没有 console.error"——其它来源的 console
//   噪音不归本判据管（那在真栈冒烟 `scripts/ui-smoke-merchant/spec.mjs` 的 `19-` 旅程上）；
// - jsdom 的 HTML 解析器**同样**会就地闭合 `<p>`（实测 `jsdom@30.1.1`：
//   `<p><div>x</div></p>` ⇒ `<p></p><div>x</div><p></p>`）⇒ 与真浏览器同条件；
// - 判不了"版式好不好看"（那是 §15.7 截图读图的事）。

import React from 'react'
import { renderToString } from 'react-dom/server'
import { hydrateRoot, type Root } from 'react-dom/client'
import { act } from 'react'
import { vi } from 'vitest'

/** React 在 DOM 嵌套非法时打的两条 error 的**特征串**（逐字取自真栈读数）。 */
export const NESTING_ERROR_PATTERNS = [
  /cannot be a descendant of/i,
  /cannot contain a nested/i,
  /Hydration failed because/i,
]

/** 判定一条 console.error 是不是"块级落在 <p> 里"这一族。 */
export function isNestingError(text: string): boolean {
  return NESTING_ERROR_PATTERNS.some((re) => re.test(text))
}

export interface HydrationWitnessResult {
  /** 服务端渲染出的 HTML（逐字） */
  serverHtml: string
  /** 浏览器式解析后的 DOM（`<p>` 已被就地闭合，与真浏览器同形状） */
  parsedHtml: string
  /** 客户端 hydrate 之后的 DOM */
  hydratedHtml: string
  /** hydrate 期间收到的 console.error（逐字） */
  errors: string[]
  /** 其中属于"块级落在 <p> 里"这一族的（逐字） */
  nestingErrors: string[]
  root: Root
  container: HTMLElement
}

/** 把 SSR HTML 挂到 detached 容器上（不污染 `document.body`，避免 cleanup 互相踩）。 */
function mountServerHtml(html: string): HTMLElement {
  const container = document.createElement('div')
  container.innerHTML = html
  return container
}

/**
 * 跑一轮 SSR → 浏览器式解析 → hydrate，收集 console.error。
 *
 * `element` 必须是**稳定的**元素树（同一份 JSX 两次渲染，语义相同）——
 * 传函数会在服务端与客户端各调用一次，别在里面写 `Date.now()` 之类的不稳定输入。
 */
export function witnessHydration(element: React.ReactElement): HydrationWitnessResult {
  const serverHtml = renderToString(element)
  const container = mountServerHtml(serverHtml)
  const parsedHtml = container.innerHTML

  const errors: string[] = []
  const spy = vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
    errors.push(args.map((a) => String(a)).join(' '))
  })
  let root!: Root
  try {
    act(() => {
      // `onRecoverableError`：React 在 hydration 失配时把错误同时**抛**给宿主 —— 不给这个钩子，
      // vitest 会把它记成 "Unhandled Errors"（判据照旧通过，但报告里多一条噪声，且"错误被吞"
      // 与"错误被收下"在读数上分不清）。这里**收下并逐字保留**，让判据读的是同一份证据。
      root = hydrateRoot(container, element, {
        onRecoverableError: (error) => {
          errors.push(`[recoverable] ${error instanceof Error ? `${error.name}: ${error.message}` : String(error)}`)
        },
      })
    })
  } catch (error) {
    // React 在 hydration 失配时会 throw；**照实收下**（它不是"测试坏了"，正是被测缺陷本身）
    errors.push(String(error))
  } finally {
    spy.mockRestore()
  }
  return {
    serverHtml,
    parsedHtml,
    hydratedHtml: container.innerHTML,
    errors,
    nestingErrors: errors.filter(isNestingError),
    root,
    container,
  }
}

/**
 * 判别力自证用：一个**故意坏**的形态（`<p>` 里塞 `<div>`）。
 * 见证器对它必须报红 —— 否则见证器自身退化成恒绿（"不会红的判据 = 空断言"）。
 */
export function BadNestingProbe(): React.ReactElement {
  return (
    <p className="witness-probe">
      <div className="witness-probe-inner">块级内容</div>
    </p>
  )
}

/** 判别力自证用的**好**形态（同结构、只把 `<div>` 换成 `<span>`）。 */
export function GoodNestingProbe(): React.ReactElement {
  return (
    <p className="witness-probe">
      <span className="witness-probe-inner">行内内容</span>
    </p>
  )
}
