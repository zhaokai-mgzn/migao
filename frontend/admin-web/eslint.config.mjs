// ESLint flat config。
//
// ── 为什么必须迁移（Next 16 / eslint 8→9）────────────────────────────────────────
//   · Next 16 移除了 `next lint`（连带 `next.config` 的 `eslint` 选项）⇒ `npm run lint`
//     改走 ESLint CLI（见 package.json 的 `lint` 脚本）。
//   · eslint 9+ 只读 flat config；`.eslintrc.json` 在 flat 模式下**不再被加载**。
//     原 `extends: next/core-web-vitals` 因此必须改写为本文件，否则 lint **静默失效**
//     （eslint 找不到配置会报错，但若误配成空配置则是一路绿 —— 属于「空跑」形态）。
//   · `eslint-config-next@16` 只导出 flat config：`./core-web-vitals`、`./typescript`。
//
// ── 规则面：与升级前**逐条等价**，未放宽任何既有规则 ────────────────────────────
//   升级前 lint 面 = `.eslintrc.json` 的 `extends: next/core-web-vitals` + 两条自定义规则。
//   实测（把 eslint-config-next@14.2.35 + eslint@8.57.1 装在独立目录里跑同一份 `src/`）：
//   该配置的规则集合 = `plugin:react/recommended` + `plugin:react-hooks/recommended`
//   + `plugin:@next/next/recommended` + `core-web-vitals` 增量，
//   其中 `react-hooks/recommended` 在 eslint-plugin-react-hooks@5 下**只有两条**：
//   `rules-of-hooks: error` 与 `exhaustive-deps: warn`。
//
//   eslint-config-next@16 把 eslint-plugin-react-hooks 升到 v7，其 `recommended`
//   从 2 条涨到 **16 条** —— 新增的 14 条是 **React Compiler 规则**
//   （`set-state-in-effect` / `refs` / `immutability` / `purity` / `preserve-manual-memoization`
//   / `static-components` / `globals` / `error-boundaries` / `set-state-in-render`
//   / `unsupported-syntax` / `config` / `gating` / `use-memo` / `incompatible-library`）。
//   实测这些新规则在当前 `src/` 上报 **69 个 error**（见 PR body 的「剩余清单」）——
//   那是**一次独立的 React Compiler 采纳专项**（需要逐处行为分析 + 重跑 E2E），
//   不属于「Next 14→16 工具链升级」的范围。因此下面把它们**显式关闭**，
//   使 lint 门禁保持**升级前口径**（既不新增、也不放宽），而不是借升级之名
//   悄悄把关卡从「2 条 hooks 规则」扩成「16 条」、或反过来把 69 条真错当噪音忽略。
//
//   ⚠️ 未引入 `eslint-config-next/typescript`（= typescript-eslint `recommended`）：
//   它与 `core-web-vitals` 是**并列**的两个 config，升级前并未启用；引入它会新增一整套
//   `@typescript-eslint/*` 规则（`no-explicit-any` 等），同属独立专项，不混进本包。
import { defineConfig, globalIgnores } from 'eslint/config'
import nextVitals from 'eslint-config-next/core-web-vitals'

/** React Compiler 规则（eslint-plugin-react-hooks v7 新增）—— 本包不采纳，理由见文件头。 */
const REACT_COMPILER_RULES = [
  'static-components',
  'use-memo',
  'preserve-manual-memoization',
  'incompatible-library',
  'immutability',
  'globals',
  'refs',
  'set-state-in-effect',
  'error-boundaries',
  'purity',
  'set-state-in-render',
  'unsupported-syntax',
  'config',
  'gating',
]

export default defineConfig([
  ...nextVitals,

  {
    rules: {
      // ── 与升级前逐条等价的 hooks 规则（显式写死，防止上游再扩集）──
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // ── React Compiler 规则：本包不采纳（见文件头）──
      ...Object.fromEntries(REACT_COMPILER_RULES.map((r) => [`react-hooks/${r}`, 'off'])),

      // ── 原有自定义规则，等级不变 ──
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      'no-debugger': 'error',
    },
  },

  // 覆盖 eslint-config-next 的默认 ignore：`.next/**` 是构建产物，`next-env.d.ts` 由 Next 生成。
  // `tests/**` 沿用升级前的 lint 面 —— 旧 `next lint` 默认只覆盖 app/pages/components/lib/src，
  // 测试目录本就不在 lint 面内；本次是**工具链迁移**，不借机扩大或缩小覆盖面。
  globalIgnores(['.next/**', 'out/**', 'build/**', 'next-env.d.ts', 'tests/**']),
])
