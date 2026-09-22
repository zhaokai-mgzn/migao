/**
 * 「企业参数中心」的**参数清单与文案单一真值模块**（issue #5131）—— 纯数据，无副作用。
 *
 * ## 为什么需要它
 *
 * 商家可配的参数散在 **6 个页面 / 7 张表**（见 `docs/design/tenant-params-center.md` §1）。
 * 商家的真实痛点**不是「参数太多」**，而是 **找不到** 与 **不知道改这个会变什么**。
 * 本模块是那一页的**唯一清单**：有哪些参数、属于哪个域、文案是什么、去哪改。
 *
 * ## 三条纪律（`migao-dev-flow` §22 的基线，与 `craft-calc-glossary.ts` 同源）
 *
 * 1. **文案里不出现数字** —— 数值一律由**真值渲染**（配置对象 / 服务端返回）。
 *    写死一个数 = 造第二份口径；改了参数而说明不跟着变 ⇒ **说明变假话**。
 *    本条有**机械判据**：`tests/unit/lib/tenant-params.test.ts` 用 `/\\d/` 扫全部文案。
 * 2. **口径与引擎同源** —— 算料域的参数文案**不在这里抄第二份**，直接读
 *    `craft-calc-glossary.ts` 的 `CALC_PARAM_COPY` / `CALC_SCALAR_KEYS`
 *    （那一份有「键集必须覆盖引擎全部配置键」的守卫）。
 * 3. **清单必须覆盖「商家能配的东西」** —— 算料域的 `common ∪ advanced` 必须与
 *    `CALC_SCALAR_KEYS` **双向相等**（引擎加键而本模块漏挂 ⇒ 守卫红）。
 *
 * ⚠️ **行式配置与标量参数不是一类**（这是本页最容易做错的地方）：加工费组合 / 工序库 /
 * 工序路线 / 特殊选项价 / 计件都是**列表编辑**，而算料与 AI 客服是**标量表单**。
 * 把列表塞进参数表格 = 两套交互杂糅 ⇒ 本模块对行式配置**只给入口与一句话说明**。
 *
 * 🔴 **本模块不判任何口径、不算任何钱**（同 `craft-calc-glossary.ts` 的纪律）：
 * 它只描述「有哪些参数」。判定与取价一律在服务端。
 */
import { CALC_PARAM_COPY, CALC_SCALAR_KEYS } from '@/lib/craft-calc-glossary'

/** 一个参数的页面文案（与算料配置页同形：`label` 上标签、`hint` 一行口径、`impact` 影响什么） */
export interface ParamCopy {
  label: string
  hint: string
  impact: string
}

/** 域内一条**标量**参数 */
export interface ScalarParam {
  /** 配置键（= 后端列名 = 引擎配置键，**逐字同名**；AI 客服域为后端 camelCase 字段名） */
  key: string
  copy: ParamCopy
}

/** 域内一条**行式**配置（列表编辑 ⇒ 只给入口） */
export interface RowConfigLink {
  label: string
  /** 站内路径（必须以 `/` 开头；守卫判据之一） */
  href: string
  /** 这条配置管什么 */
  hint: string
  /** **它改的是什么钱** —— 一行说清（§22 P4 的文案形态；不含数字） */
  money: string
}

/** 一个域（页面第一层分组，§22 P1） */
export interface ParamDomain {
  key: string
  label: string
  /** 这个域管什么（一句话） */
  summary: string
  /** 标量参数 · 常用（默认展开） */
  common?: ScalarParam[]
  /** 标量参数 · 高级（默认收起） */
  advanced?: ScalarParam[]
  /** 行式配置入口（与标量参数可并存） */
  rows?: RowConfigLink[]
  /** 就地编辑入口（既有页面；本增量**不新建编辑器**） */
  edit?: { href: string; label: string }
}

/**
 * 算料域里**归入「高级」**的键 —— 其余一律进「常用」。
 *
 * ⚠️ 用**排除法**（而不是列出常用键）：引擎新增一个配置键时，它会**自动出现在「常用」**里
 * （可见 = 安全），而不会因为「忘了加进清单」而消失。反过来若要把它降级，必须显式加进来。
 */
const CALC_ADVANCED_KEYS: readonly string[] = ['min_fullness', 'meters_rounding_step']

/**
 * **AI 客服 / 会话**域的参数文案（本模块持有 —— 那一侧没有既有的说明真值模块）。
 *
 * ⚠️ 只登记**页面上真的能改**的字段（`frontend/admin-web/src/types/index.ts` 的 `AiConfig`）。
 * `tenant_ai_configs` 表里还有别的列（营业时间 / 自动转人工关键词 / 推荐策略 …），
 * 但它们**今天没有编辑入口** ⇒ **不在此列**（列一个商家改不了的参数 = 假清单）。
 */
export const AI_PARAM_COPY: Record<string, ParamCopy> = {
  botName: {
    label: 'AI 助手名称',
    hint: '顾客在对话里看到的名字',
    impact: '只改称呼 —— 不参与任何算料与报价口径',
  },
  greetingTemplate: {
    label: '欢迎语',
    hint: '会话开场自动发出的第一句',
    impact: '只影响开场文案 —— 不参与任何算料与报价口径',
  },
}

/** 域清单（页面按此渲染；顺序即页面顺序） */
export const PARAM_DOMAINS: readonly ParamDomain[] = [
  {
    key: 'calc',
    label: '算料',
    summary: '用布量公式与余量口径 —— 本域**每一项都直接改米数 = 改钱**',
    common: CALC_SCALAR_KEYS.filter((k) => !CALC_ADVANCED_KEYS.includes(k)).map((key) => ({
      key,
      copy: CALC_PARAM_COPY[key],
    })),
    advanced: CALC_ADVANCED_KEYS.filter((k) => CALC_SCALAR_KEYS.includes(k)).map((key) => ({
      key,
      copy: CALC_PARAM_COPY[key],
    })),
    edit: { href: '/production/routings?tab=calc', label: '去算料配置' },
  },
  {
    key: 'ai',
    label: 'AI 客服',
    summary: '顾客在对话里看到的称呼与开场文案',
    common: Object.keys(AI_PARAM_COPY).map((key) => ({ key, copy: AI_PARAM_COPY[key] })),
    edit: { href: '/settings?tab=ai', label: '去 AI 客服设置' },
  },
  {
    key: 'fee',
    label: '加工费',
    summary: '加工费按「工艺 + 特征」的组合定价 —— 组合命中不到，该行加工费就收不到价',
    rows: [
      {
        label: '加工费组合',
        href: '/production/processing-fees',
        hint: '按「工艺 + 自动识别特征」的组合配单价（元/米）',
        money: '直接定加工费单价 —— 改它即改钱',
      },
      {
        label: '特殊选项价',
        href: '/production/processing',
        hint: '拼次 / 接高 / 铅块一类特殊选项的对客价',
        money: '对客按套计价 —— 改它即改钱',
      },
    ],
  },
  {
    key: 'craft',
    label: '工艺',
    summary: '工序库、工序路线与计件单价 —— 决定车间要做哪些活、每道活多少钱',
    rows: [
      {
        label: '工序库',
        href: '/production/operations',
        hint: '工序名 / 单位 / 分组 / 必完 / 停用 / 计件单价',
        money: '计件单价进车间工资 —— 改它即改钱',
      },
      {
        label: '工序管理',
        href: '/production/routings',
        hint: '工艺与特殊选项会插哪些工序、插在哪一道之后',
        money: '不改对客价，但改车间实际要做的活',
      },
      {
        label: '计件',
        href: '/production/piecework',
        hint: '按工序与部位的计件口径',
        money: '进车间工资 —— 改它即改钱',
      },
    ],
  },
]

/**
 * 文案合规扫描（§22 基线 ①「文案里**不出现数字**」的可执行判据）—— **纯函数，供守卫与红证共用**。
 *
 * @returns 违规描述列表；**空 = 合规**。
 *
 * ⚠️ 之所以做成**接收任意映射的纯函数**、而不是直接扫本模块常量：守卫必须能**注入一份坏文案**
 * 并断言它被判出来 —— 否则「扫了但扫不出」与「根本没扫」在测试里长得一模一样（空断言）。
 */
export function findCopyViolations(copies: Record<string, ParamCopy>): string[] {
  const bad: string[] = []
  for (const [key, copy] of Object.entries(copies)) {
    for (const field of ['label', 'hint', 'impact'] as const) {
      const text = copy?.[field]
      if (!text || !text.trim()) bad.push(`${key}.${field} 为空`)
      else if (/\d/.test(text)) bad.push(`${key}.${field} 含数字：${text}`)
    }
  }
  return bad
}

/** 域清单的结构与文案扫描（同上：**可注入的纯函数**，供守卫与红证共用） */
export function findDomainViolations(domains: readonly ParamDomain[]): string[] {
  const bad: string[] = []
  const seen = new Set<string>()
  for (const d of domains) {
    if (!d.key || !d.label || !d.summary) bad.push(`域 ${d.key || '(缺 key)'} 的 key/label/summary 必须非空`)
    if (seen.has(d.key)) bad.push(`域 key 重复：${d.key}`)
    seen.add(d.key)
    for (const field of ['label', 'summary'] as const) {
      if (d[field] && /\d/.test(d[field])) bad.push(`域 ${d.key}.${field} 含数字：${d[field]}`)
    }
    for (const r of d.rows ?? []) {
      if (!r.href.startsWith('/')) bad.push(`域 ${d.key} 的入口 ${r.label} 的 href 必须以 / 开头`)
      if (!r.money?.trim()) bad.push(`域 ${d.key} 的入口 ${r.label} 缺「钱在哪」说明`)
      else if (/\d/.test(r.money)) bad.push(`域 ${d.key} 的入口 ${r.label} 的 money 含数字`)
      if (!r.hint?.trim()) bad.push(`域 ${d.key} 的入口 ${r.label} 缺 hint`)
    }
    if (d.edit && !d.edit.href.startsWith('/')) bad.push(`域 ${d.key} 的编辑入口 href 必须以 / 开头`)
    bad.push(...findCopyViolations(Object.fromEntries((d.common ?? []).map((p) => [p.key, p.copy]))))
    bad.push(...findCopyViolations(Object.fromEntries((d.advanced ?? []).map((p) => [p.key, p.copy]))))
  }
  return bad
}

/**
 * 「算料域必须覆盖引擎全部配置键」的**双向差集**（§22 基线 ③）—— 同上，可注入。
 *
 * @returns `{missing, extra}`：`missing` = 引擎有而本模块没挂（商家看不见）；`extra` = 本模块挂了引擎没有的。
 */
export function calcKeySetDiff(
  domains: readonly ParamDomain[],
  scalarKeys: readonly string[]
): { missing: string[]; extra: string[] } {
  const calc = domains.find((d) => d.key === 'calc')
  const shown = new Set([
    ...(calc?.common ?? []).map((p) => p.key),
    ...(calc?.advanced ?? []).map((p) => p.key),
  ])
  const engine = new Set(scalarKeys)
  return {
    missing: [...engine].filter((k) => !shown.has(k)),
    extra: [...shown].filter((k) => !engine.has(k)),
  }
}

/**
 * 读面 `source` ⇒ 该租户**是否配置过**算料口径。
 *
 * `'default'` = 本租户**没有**配置行，表里的值**全部**是算料引擎默认值；
 * `'stored'` = 商家配置行。⚠️ 逐键「我改过没有」需要读面补 `defaults` 字段
 * （见 `docs/design/tenant-params-center.md` §6 未实装登记），**本增量只到租户级**。
 */
export function isUsingEngineDefault(source: string | undefined | null): boolean {
  return source !== 'stored'
}

/** 取某域的标量参数总数（页面与守卫共用，避免两处各数一遍） */
export function scalarCountOf(domain: ParamDomain): number {
  return (domain.common?.length ?? 0) + (domain.advanced?.length ?? 0)
}
