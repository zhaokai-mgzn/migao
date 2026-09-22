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
//   ── 后续包已收紧其中 3 条（见下面 REFS_PURITY_RULES）────────────────────────────
//   那 69 个 error 里，**9 个与 React Compiler 无关、是真实代码缺陷**（渲染期读写 ref 6 处 /
//   声明前访问 2 处 / 渲染期 `Date.now()` 1 处）。把真缺陷长期 `off` 掉 = 把它们重新藏起来，
//   故已逐条修好后把这 3 条**从 `off` 收紧为 `error`**（残留违规 0 才收紧）。其余 11 条仍 `off`。
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
  'globals',
  'set-state-in-effect',
  'error-boundaries',
  'set-state-in-render',
  'unsupported-syntax',
  'config',
  'gating',
]

/**
 * 原先与上面一起 `off`、现**收紧回 error** 的 3 条。
 * 它们命中的是**与 React Compiler 无关的真缺陷**（渲染期读写 ref / 声明前访问 / 渲染期 `Date.now()`），
 * 不是「编译器风格偏好」——把真缺陷长期 `off` 掉等于把它们藏起来（本仓把「豁免掩盖」列为要治的病）。
 * 收紧前实测：这 3 条在 `src/` 上报 **9 个 error / 5 个文件**；逐条修完后为 **0**，故收紧。
 * 残留的另外 11 条（如 `set-state-in-effect` 57 处）仍 `off`，见文件头与 PR body 的登记。
 */
const REFS_PURITY_RULES = ['refs', 'immutability', 'purity']

export default defineConfig([
  ...nextVitals,

  {
    rules: {
      // ── 与升级前逐条等价的 hooks 规则（显式写死，防止上游再扩集）──
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // ── React Compiler 规则：本包不采纳（见文件头）──
      ...Object.fromEntries(REACT_COMPILER_RULES.map((r) => [`react-hooks/${r}`, 'off'])),
      // ── 其中 3 条是「与编译器无关的真缺陷」⇒ 逐条修好后**收紧为 error**（残留 0 才收紧）──
      ...Object.fromEntries(REFS_PURITY_RULES.map((r) => [`react-hooks/${r}`, 'error'])),

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
