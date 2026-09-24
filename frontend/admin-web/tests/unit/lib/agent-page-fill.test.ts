// case_ids: CH-021, PR-008, OR-008
/**
 * Agent 深通道的**同页填充通道**（issue #5368 包 2）—— 前端半边（纯函数 + 事件通道）。
 *
 * ## 为什么是「内存事件通道」而不是 URL / 存储
 *
 * 商家站在建品页 / 建单页上跟米宝说话（浮动面板在表单上方，`(dashboard)/layout.tsx` 挂载），
 * 米宝识别完要把字段**推给当前页面表单**。最省事的写法是 `?prefill=<base64>` 或
 * `localStorage` —— 两者都把**订单侧收货信息**写进了会落盘的地方
 * （query 参数进 nginx access log 与 Referer；localStorage 留在磁盘上）。
 * 本仓已为「预填手机号把完整号码带进 `final_text`」吃过一次账（issue 的硬约束 1）。
 *
 * ⇒ 这里只用 `window.dispatchEvent(new CustomEvent(...))`：载荷活在**当前页面的内存**里，
 * 刷新即消失（而刷新后表单本来也是空的）。
 *
 * ## 判据（与 issue 的验收判据逐条对应）
 *
 * | # | 判据 | 断言 |
 * |---|---|---|
 * | 1 | **同页填充不改 URL、不落日志** | 静态扫描：`agent-page-fill.ts` 与 store 的 `page_fill` 分支里没有 `location` / `history` / `localStorage` / `sessionStorage` / `console.` / `URLSearchParams`（+ 扫描器判别力红证） |
 * | 2 | **来源标注可区分** | `[米宝解读]` ≠ `[图片识别]`；两侧各自只收自己来源的格子 |
 * | 3 | **歧义给候选不擅自填** | 歧义格（`value: null` + `candidates`）**两侧都不收** ⇒ 一个格子都填不进去 |
 * | 5 | 🔴 **页面快通道仍独立可用** | 快通道两个文件**零引用**深通道（防后人把两个入口耦合成一条） |
 */
import { describe, it, expect, vi } from 'vitest'
import fs from 'node:fs'

import {
  PAGE_FILL_COMPONENT,
  PAGE_FILL_EVENT,
  PAGE_FILL_SOURCE_INTERPRETED,
  emitPageFill,
  fieldsOfSource,
  isPageFillPlan,
  subscribePageFill,
  type PageFillPlan,
} from '@/lib/agent-page-fill'
import { RECOGNIZE_SOURCE_TAG } from '@/lib/image-recognize'

/**
 * **落盘面扫描器**（判据 1 的机械口径）—— 定义在测试里而不是产品代码里：
 * 扫描器自己的词表若活在 `agent-page-fill.ts` 里，它会把**自己的词表**扫成违规（自伤）。
 */
const LEAK_TOKENS = [
  'window.location',
  'location.href',
  'location.search',
  'history.pushState',
  'history.replaceState',
  'localStorage',
  'sessionStorage',
  'document.cookie',
  'console.',
  'URLSearchParams',
]

function leakScan(source: string): string[] {
  return LEAK_TOKENS.filter((token) => source.includes(token))
}

/**
 * **代码面**（剥掉注释与块注释后的正文）。
 *
 * 为什么必须先剥：判据只该判**代码**。注释里写「不要用 localStorage / 不要 console.log」
 * 是**说明**，不是违规 —— 直接扫原文会把判据自己的反面教材扫成红（「判据被自己的文案喂红」，
 * 本仓已多次踩到）。剥注释后，真正会落盘的调用仍然一个都跑不掉（见下面的注入式红证）。
 */
function codeFace(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .map((line) => line.replace(/\/\/.*$/, ''))
    .join('\n')
}

const PRODUCT_PLAN: PageFillPlan = {
  component: 'page_fill',
  target_type: 'product',
  fields: [
    { key: 'name', label: '商品名称', value: '雪尼尔遮光窗帘', source: RECOGNIZE_SOURCE_TAG,
      reason: null, candidates: [], note: null, note_source: null },
    { key: 'color', label: '颜色', value: null, source: null,
      reason: '店铺目录里没有「雾霾蓝」⇒ 宁可不填：下面几个最接近，请商家挑一个',
      candidates: [{ value: '藏青', reason: '与「雾霾蓝」最接近（相似度 50%）' }],
      note: null, note_source: null },
    { key: 'material', label: '材质', value: '雪尼尔', source: PAGE_FILL_SOURCE_INTERPRETED,
      reason: null, candidates: [], note: '克重偏厚，适合客厅', note_source: PAGE_FILL_SOURCE_INTERPRETED },
    { key: 'price', label: '售价', value: null, source: null, reason: '图上没有价格',
      candidates: [], note: null, note_source: null },
  ],
}

describe('判据 2 · 来源标注可区分', () => {
  it('「解读」标记与「识别」标记是两个不同的串（同值 = 商家无从判断该信哪一格）', () => {
    expect(PAGE_FILL_SOURCE_INTERPRETED).toBe('[米宝解读]')
    expect(RECOGNIZE_SOURCE_TAG).toBe('[图片识别]')
    expect(PAGE_FILL_SOURCE_INTERPRETED).not.toBe(RECOGNIZE_SOURCE_TAG)
  })

  it('两侧各自只收自己来源的格子', () => {
    expect(fieldsOfSource(PRODUCT_PLAN, RECOGNIZE_SOURCE_TAG).map((f) => f.key)).toEqual(['name'])
    expect(fieldsOfSource(PRODUCT_PLAN, PAGE_FILL_SOURCE_INTERPRETED).map((f) => f.key)).toEqual(['material'])
  })

  it('值非空但来源不在两种之内 ⇒ 不收（有值必有来源，来源是硬要求）', () => {
    const odd: PageFillPlan = {
      component: 'page_fill',
      target_type: 'product',
      fields: [{ key: 'name', label: '商品名称', value: '甲', source: null,
        reason: null, candidates: [], note: null, note_source: null }],
    }
    expect(fieldsOfSource(odd, RECOGNIZE_SOURCE_TAG)).toEqual([])
    expect(fieldsOfSource(odd, PAGE_FILL_SOURCE_INTERPRETED)).toEqual([])
  })
})

describe('判据 3 · 歧义格给候选、绝不擅自填', () => {
  it('歧义格（value=null + candidates）两侧都不收 —— 一个格子都填不进去', () => {
    const fillable = [
      ...fieldsOfSource(PRODUCT_PLAN, RECOGNIZE_SOURCE_TAG),
      ...fieldsOfSource(PRODUCT_PLAN, PAGE_FILL_SOURCE_INTERPRETED),
    ].map((f) => f.key)
    expect(fillable).not.toContain('color')
    expect(fillable).not.toContain('price')
    expect(fillable).toEqual(['name', 'material'])
  })

  it('空值字段即使伪造了 source 也不填（判据看的是值，不是标注）', () => {
    const forged: PageFillPlan = {
      component: 'page_fill',
      target_type: 'order',
      fields: [{ key: 'customer_phone', label: '电话', value: null, source: RECOGNIZE_SOURCE_TAG,
        reason: '手机号不是 11 位有效号码', candidates: [], note: null, note_source: null }],
    }
    expect(fieldsOfSource(forged, RECOGNIZE_SOURCE_TAG)).toEqual([])
  })
})

describe('判据 1 · 同页填充走内存事件通道（不改 URL / 不落日志）', () => {
  it('emit ⇒ 只有目标页面的订阅者收到', () => {
    const onProduct = vi.fn()
    const onOrder = vi.fn()
    const offProduct = subscribePageFill('product', onProduct)
    const offOrder = subscribePageFill('order', onOrder)

    emitPageFill(PRODUCT_PLAN)

    expect(onProduct).toHaveBeenCalledTimes(1)
    expect(onProduct.mock.calls[0][0].target_type).toBe('product')
    expect(onOrder).not.toHaveBeenCalled()

    offProduct()
    offOrder()
    emitPageFill(PRODUCT_PLAN)
    expect(onProduct).toHaveBeenCalledTimes(1)
    expect(onOrder).not.toHaveBeenCalled()
  })

  it('事件名是内存事件（不是 URL / 存储键）', () => {
    expect(PAGE_FILL_EVENT).toBe('mibao:page-fill')
    expect(PAGE_FILL_COMPONENT).toBe('page_fill')
  })

  it('通道实现里没有 URL / 历史 / 存储 / 控制台任何一处落盘面（**代码面**）', () => {
    const src = fs.readFileSync('src/lib/agent-page-fill.ts', 'utf8')
    const code = codeFace(src)
    expect(leakScan(code)).toEqual([])
    // 正向对照：它**确实**用了内存事件（否则上面的扫描会因为「什么都没做」而恒绿）
    expect(code).toContain('CustomEvent')
    expect(code).toContain('dispatchEvent')
    expect(code).toContain('addEventListener')
  })

  it('store 的 page_fill 分支里同样没有任何落盘面', () => {
    const src = fs.readFileSync('src/store/chat.ts', 'utf8')
    const lines = src.split('\n')
    const start = lines.findIndex((line) => line.includes("case 'page_fill'"))
    expect(start, 'store 里没有 page_fill 分支 ⇒ 后端事件到不了页面').toBeGreaterThan(-1)
    const block = codeFace(lines.slice(start, start + 8).join('\n'))
    expect(block).toContain('emitPageFill')
    expect(leakScan(block)).toEqual([])
  })

  it('落盘面扫描器有判别力（注入式红证：真调用了就必须认出来）', () => {
    expect(leakScan(codeFace("window.location.href = '/x?prefill=1'"))).toEqual(['window.location', 'location.href'])
    expect(leakScan(codeFace("localStorage.setItem('mibao_prefill', json)"))).toEqual(['localStorage'])
    expect(leakScan(codeFace("history.replaceState({}, '', '?prefill=1')"))).toEqual(['history.replaceState'])
    expect(leakScan(codeFace('console.log(plan)'))).toEqual(['console.'])
    expect(leakScan(codeFace('const p = new URLSearchParams(plan)'))).toEqual(['URLSearchParams'])
    expect(leakScan(codeFace('window.dispatchEvent(new CustomEvent(EVENT, { detail: plan }))'))).toEqual([])
    // 剥注释口径自证：说明性文字不算违规，而它旁边那行真实调用照样被抓到
    expect(leakScan(codeFace('// 这里不能用 localStorage 落盘'))).toEqual([])
    expect(leakScan(codeFace("// 这里不能用 localStorage 落盘\nlocalStorage.setItem('k', v)"))).toEqual(['localStorage'])
  })

  it('isPageFillPlan 认得出计划、挡得住别的东西（错误事件不填表）', () => {
    expect(isPageFillPlan(PRODUCT_PLAN)).toBe(true)
    expect(isPageFillPlan({ component: 'choice', title: '选一个' })).toBe(false)
    expect(isPageFillPlan(null)).toBe(false)
    expect(isPageFillPlan({ component: 'page_fill', target_type: 'invoice', fields: [] })).toBe(false)
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 5：页面快通道仍独立可用（**不依赖 Agent**）—— 防后人把两个入口耦合成一条
// ══════════════════════════════════════════════════════════════════════════════
/**
 * **快通道入口**的两个文件（判据 5 的射程 = 「图 → 字段 → 填表」这条**入口链**）。
 *
 * `InterpretedBadge.tsx` / `ProductForm.tsx` **不在**射程内：前者是深通道自己的徽标、
 * 后者是两条入口共用的**渲染**容器 —— 它们知道深通道的存在是**设计**（共用渲染），
 * 而「没有 LLM 就用不了识别」这件事由**入口链**决定，故射程钉在入口链上。
 */
const FAST_LANE_FILES = [
  'src/lib/image-recognize.ts',
  'src/components/image-recognize/ImageRecognizeButton.tsx',
]

/** 快通道文件里**不得**出现的深通道符号（出现即「两个入口耦合」） */
const DEEP_CHANNEL_TOKENS = [
  'agent-page-fill',
  'PAGE_FILL_EVENT',
  'PAGE_FILL_SOURCE_INTERPRETED',
  'emitPageFill',
  'subscribePageFill',
  'store/chat',
  '米宝解读',
]

function deepRefs(src: string): string[] {
  return DEEP_CHANNEL_TOKENS.filter((token) => src.includes(token))
}

describe('判据 5 · 页面快通道仍独立可用（不依赖 Agent）', () => {
  it('快通道文件零引用深通道（防「必须有 LLM 才能用」）', () => {
    for (const file of FAST_LANE_FILES) {
      expect(deepRefs(fs.readFileSync(file, 'utf8')), `${file} 引用了深通道`).toEqual([])
    }
  })

  it('正向对照：快通道自带「上传 → 页面识别端点」整条链路（不看 Agent 也能填表）', () => {
    const src = fs.readFileSync('src/components/image-recognize/ImageRecognizeButton.tsx', 'utf8')
    expect(src).toContain('uploadApi.uploadImage')
    expect(src).toContain('imageRecognizeApi.recognize')
    const lib = fs.readFileSync('src/lib/image-recognize.ts', 'utf8')
    expect(lib).toContain('buildProductPrefill')
    expect(lib).toContain('buildOrderPrefill')
  })

  it('耦合扫描器有判别力（红证：注入一行深通道引用必须被抓到）', () => {
    expect(deepRefs("import { emitPageFill } from '@/lib/agent-page-fill'")).toEqual(['agent-page-fill', 'emitPageFill'])
    expect(deepRefs('const badge = RECOGNIZE_SOURCE_TAG')).toEqual([])
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 最后一公里：计划到了浏览器，**有没有人接**
// ══════════════════════════════════════════════════════════════════════════════
describe('两个建对象页都订阅了同页填充（接线判据）', () => {
  /**
   * ⚠️ **这是接线判据，不是行为判据**（如实登记）：它证明「页面挂上了订阅」，
   * 行为面由三处覆盖 —— `chat-page-fill.test.ts`（SSE → store → 事件）、
   * 本文件（事件 → 订阅者 → 可填字段）、`ImageRecognizePrefill.test.tsx`（字段 → 表单）。
   * 三道接起来才是完整链路；单看任何一道都不够（少一道 = 计划到了浏览器没人接，
   * 而构建绿、类型绿、其余测试全绿 —— 没有任何东西会变红）。
   */
  const PAGES: Array<[string, string]> = [
    ['src/app/(dashboard)/products/new/page.tsx', 'product'],
    ['src/app/(dashboard)/orders/new/page.tsx', 'order'],
  ]

  it('每个页面用**自己的 target** 订阅（张冠李戴 = 订单页收商品计划）', () => {
    for (const [file, target] of PAGES) {
      const src = fs.readFileSync(file, 'utf8')
      expect(src, `${file} 没有订阅同页填充`).toContain(`subscribePageFill('${target}'`)
    }
    expect(PAGES.map(([, target]) => target)).toEqual(['product', 'order'])
  })

  it('接线扫描器有判别力（红证：锚点换成另一个 target 就抓不到）', () => {
    const productPage = fs.readFileSync(PAGES[0][0], 'utf8')
    expect(productPage).toContain("subscribePageFill('product'")
    expect(productPage).not.toContain("subscribePageFill('order'")
  })
})