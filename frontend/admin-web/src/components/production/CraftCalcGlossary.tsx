/**
 * 「算料口径与术语说明」区块（issue #4975）—— 纯展示、无状态。
 *
 * 用户 2026-09-21：「……这些术语的说明和例子，告知用户我们系统是如何推算的，需要用到哪些参数，
 * 都可以在工序配置这个页面上说清楚」⇒ 与参数**同屏**（不新开 tab / 路由 / 组件库依赖）。
 *
 * ## 三条实现纪律
 *
 * 1. **不写死任何数字**：参数值取自 `config`（页面草稿）；算例的**判定依据**自 issue #5036 包 2a 起
 *    由**服务端**给（`POST /api/admin/orders/auto-features`，入参带**该租户配置**）⇒
 *    「改完参数保存后数字会跟着变」这句承诺才**成真**（迁移前读前端模块常量副本 = 假承诺）。
 * 2. **原生 `<details>`**：键盘可达、可打印、可被测试稳定断言（不引第三方折叠组件、不自绘开关）。
 * 3. **锚点由模块函数给**（`glossaryAnchorOf` / `glossaryTermAnchorOf`）：参数旁的「说明」链接与
 *    本区块的条目 id 同源，不会各写一份而对不上。
 */
import { useEffect, useState } from 'react'
import {
  AUTO_FEATURE_TERMS,
  CALC_PARAM_COPY,
  CALC_SCALAR_KEYS,
  GLOSSARY_EXAMPLE,
  GLOSSARY_FORMULAS,
  MANUAL_FEATURE_TERMS,
  SPECIAL_OPTION_TERMS,
  TERM_FAMILY,
  buildAutoFeatureExamples,
  glossaryAnchorOf,
  glossaryOptionAnchorOf,
  glossaryTermAnchorOf,
  type AutoFeatureExample,
  type GlossaryTerm,
} from '@/lib/craft-calc-glossary'
import { CUTTING_MODE_FIXED_HEIGHT, CUTTING_MODE_FIXED_WIDTH } from '@/lib/craft-auto-features'
import { autoFeaturesApi } from '@/lib/api'
import type { CraftCalcConfig } from '@/types'

/** 配置键当前值（标量渲染成文本；字典/档位在表单里各自成表，这里给占位） */
function valueOf(config: CraftCalcConfig, key: string): string {
  const value = (config as unknown as Record<string, unknown>)[key]
  if (typeof value === 'number' || typeof value === 'string') return String(value)
  return '—'
}

/** 一条术语（自动推算 / 手选 / 近义词族 / 特殊选项共用同一形态） */
function TermBlock({ term, anchor, meta }: { term: GlossaryTerm; anchor?: string; meta?: string }) {
  // 锚点与 testid 同源（`anchor` 缺省 = 术语组命名空间；特殊选项组传自己的命名空间）
  const id = anchor ?? glossaryTermAnchorOf(term.name)
  return (
    <div
      id={id}
      data-testid={id}
      className="space-y-0.5 border-b border-neutral-100 py-2 last:border-b-0"
    >
      <p className="font-medium text-neutral-800">{term.name}</p>
      <p className="text-neutral-600">{term.definition}</p>
      {meta !== undefined && <p className="text-neutral-500">{meta}</p>}
      {term.criterion !== undefined && (
        <p className="text-neutral-500">判定：{term.criterion}</p>
      )}
      <p className="text-neutral-600">{term.impact}</p>
      {term.boundary !== undefined && <p className="text-amber-700">{term.boundary}</p>}
    </div>
  )
}

export function CraftCalcGlossary({ config }: { config: CraftCalcConfig }) {
  const [examples, setExamples] = useState<AutoFeatureExample[]>([])
  const [examplesError, setExamplesError] = useState<string | null>(null)

  // 🔴 issue #5036 包 2a：算例的**判定依据**由**服务端**给（读**该租户配置**）—— 本组件只**展示**。
  // 依赖用**入参签名**（不是 `config` 对象本身）：页面草稿每次渲染都是新对象 ⇒ 用对象当依赖会自激请求风暴。
  // 🔴 issue #5130 改判：判定面（超高 / 超宽）现在读**两个企业阈值** ⇒ 进签名的就是它们
  //（旧签名的 `hem_margin` / 标准档褶倍已离开判定面 —— 它们仍进几何层，但不影响本节的算例结果）。
  const examplesSignature = [
    config.oversize_width_threshold,
    config.oversize_height_threshold,
  ].join('|')

  useEffect(() => {
    let cancelled = false
    const base = {
      width: GLOSSARY_EXAMPLE.width,
      height: GLOSSARY_EXAMPLE.height,
      config,
    }
    // 两组示例几何：定高买宽 ⇒ 超高；定宽买高 ⇒ 超宽 / 倒幅
    // （⚠️ issue #5130 起「超高 / 超宽」与加工类型**无关** —— 两组都判得出来；分两组是为了
    //  让 `倒幅` 只在 `定宽买高` 那一组出现，与判定的真值一致）
    Promise.all([
      autoFeaturesApi.preview({ ...base, cutting_mode: CUTTING_MODE_FIXED_HEIGHT }),
      autoFeaturesApi.preview({ ...base, cutting_mode: CUTTING_MODE_FIXED_WIDTH }),
    ])
      .then(([fixedHeight, fixedWidth]) => {
        if (cancelled) return
        setExamples(
          buildAutoFeatureExamples(
            config,
            // 去重：`超宽` / `超高` 在两组里都会判出来 ⇒ 只在第一组（几何更大的一组无关）
            // 出现一次；`倒幅` 只在定宽买高那组。顺序与 `AUTO_FEATURE_NAMES` 同源。
            fixedHeight.data?.data?.auto_features ?? [],
            (fixedWidth.data?.data?.auto_features ?? []).filter(
              (f) => !(fixedHeight.data?.data?.auto_features ?? []).some((g) => g.name === f.name)
            )
          )
        )
        setExamplesError(null)
      })
      .catch(() => {
        if (cancelled) return
        setExamples([])
        setExamplesError('算例加载失败：服务端判定不可用（请稍后重试）')
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 依赖 = 入参签名（理由见上）
  }, [examplesSignature])

  return (
    <section
      data-testid="craft-calc-glossary"
      className="rounded-lg border border-neutral-200 bg-white p-5"
    >
      <h2 className="text-base font-medium text-neutral-900">算料口径与术语说明</h2>
      <p className="mt-1 text-sm text-neutral-500">
        上面的参数回答「我这家的口径是多少」；这里回答「系统怎么判、拿哪些参数判」。
        下面的数值都按当前配置渲染 —— 改完参数保存后，这里的数字会跟着变。
      </p>

      <details
        id="glossary-formula"
        data-testid="glossary-formula"
        open
        className="mt-3 border-t border-neutral-100 pt-3"
      >
        <summary className="cursor-pointer text-sm font-medium text-neutral-800">公式怎么算</summary>
        <ol className="mt-2 space-y-2 text-sm">
          {GLOSSARY_FORMULAS.map((f) => (
            <li key={f.name} data-testid={`glossary-formula-${f.name}`}>
              <p className="font-medium text-neutral-700">{f.name}</p>
              <p className="text-neutral-600">{f.formula}</p>
              <p className="text-xs text-neutral-500">{f.note}</p>
            </li>
          ))}
        </ol>

        <h3 className="mt-4 text-sm font-medium text-neutral-700">参数当前值</h3>
        <table className="mt-1 w-full text-sm">
          <tbody>
            {CALC_SCALAR_KEYS.map((key) => (
              <tr
                key={key}
                id={glossaryAnchorOf(key)}
                data-testid={`glossary-param-${key}`}
                className="border-b border-neutral-100 last:border-b-0"
              >
                <td className="py-1.5 pr-3 align-top text-neutral-700">{CALC_PARAM_COPY[key].label}</td>
                <td
                  className="py-1.5 pr-3 align-top text-neutral-900"
                  data-testid={`glossary-value-${key}`}
                >
                  {valueOf(config, key)}
                </td>
                <td className="py-1.5 align-top text-xs text-neutral-500">
                  {CALC_PARAM_COPY[key].impact}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      <details
        id="glossary-terms"
        data-testid="glossary-terms"
        className="mt-3 border-t border-neutral-100 pt-3"
      >
        <summary className="cursor-pointer text-sm font-medium text-neutral-800">术语怎么判</summary>

        <h3 className="mt-2 text-sm font-medium text-neutral-700">
          系统自动推算（会进加工费组合键）
        </h3>
        {examplesError !== null && (
          <p data-testid="glossary-examples-error" className="mt-1 text-xs text-amber-700">
            {examplesError}
          </p>
        )}
        <div className="mt-1">
          {AUTO_FEATURE_TERMS.map((term) => (
            <div key={term.name}>
              <TermBlock term={term} />
              {examples
                .filter((e) => e.name === term.name)
                .map((e) => (
                  <p
                    key={e.name}
                    data-testid={`glossary-example-${e.name}`}
                    className="mb-2 text-xs text-neutral-500"
                  >
                    {e.given} ⇒ 系统判：{e.reason}
                  </p>
                ))}
            </div>
          ))}
        </div>

        <h3 className="mt-4 text-sm font-medium text-neutral-700">手选特征（系统不推算）</h3>
        <div className="mt-1">
          {MANUAL_FEATURE_TERMS.map((term) => (
            <TermBlock key={term.name} term={term} />
          ))}
        </div>

        <h3 className="mt-4 text-sm font-medium text-neutral-700">
          近义词族（最容易搅在一起，其实不在同一层）
        </h3>
        <div className="mt-1">
          {TERM_FAMILY.map((term) => (
            <TermBlock key={term.name} term={term} />
          ))}
        </div>

        {/* 特殊选项（issue #4986）：下单页勾选区里被点名的那六项 —— 它们影响的层各不相同
            （用料 / 工序 / 对客价 / 计件），所以与上面三组分开列 */}
        <h3 className="mt-4 text-sm font-medium text-neutral-700">特殊选项（下单时勾选）</h3>
        <p className="mt-1 text-xs text-neutral-500">
          这六项影响的东西各不相同 —— 有的改用料、有的加一道工序、有的只影响计件历史口径。
          工序映射逐值取自生产真值源（不是这里自己编的）。
        </p>
        <div className="mt-1">
          {SPECIAL_OPTION_TERMS.map((term) => (
            <TermBlock
              key={term.name}
              term={term}
              anchor={glossaryOptionAnchorOf(term.name)}
              meta={
                term.operation === null
                  ? '不加工序'
                  : `插工序「${term.operation}」（在「${term.after}」之后）`
              }
            />
          ))}
        </div>
      </details>
    </section>
  )
}
