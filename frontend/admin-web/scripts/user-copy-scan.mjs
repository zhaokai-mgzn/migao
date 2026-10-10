#!/usr/bin/env node
// case_ids: UI-093
/**
 * 商家后台「用户可见文案」扫描器 + 「研发腔」判据单一源（issue #6488）。
 *
 * ## 为什么要有它
 *
 * 用户 2026-10-07 逐字：「我们系统中暴露了大量的这种研发过程产生的文字，适当的文档可以引导和
 * 教育用户如何使用我们的产品，但是这类文案明显不是一个好的引导文案」「最好是扫描下全部商家
 * 后台页面，目标是提高文案的真实价值和作用，去除这类看不懂的文字」。
 *
 * 病灶形态 = 写码时**对着 issue / 设计文档写的话**被原样搬上了屏：
 * 接口与参数细节（「端点没有关键词参数」）、内部机制名（「读面」「派生值」「真值源」「组合键」）、
 * 设计辩解（「本页宁可不查，也不做一次拉全量的假方便」）、研发过程编号（`issue #4886`）、
 * 代码标识符（`oversize_height_threshold`）。
 *
 * 单个页面改一次不解决复发（同族已结案：#5565 L2/L3、#5576「池」、#5860 无主语徽标、#6461 内部标签）
 * ⇒ 本文件是那条**类级收口**：判据（`RULES`）与扫描面（`candidateStrings`）都只有这一份，
 * 守卫 `tests/unit/user-copy-jargon-guard.test.ts` 与命令行**共用**它（不写第二份规则）。
 *
 * ## 口径（判的是「会不会被商家看到」，不是「源码里有没有这个词」）
 *
 * 只抽**三类会上屏的候选**（注释天然不在 AST 里 ⇒ 不误伤设计说明）：
 *   ① `JsxText` 文本节点
 *   ② JSX 属性里的字符串字面量（`className` / `style` / `data-*` 这类不上屏的属性排除）
 *   ③ 文件里**含中文**的字符串字面量 / 模板串（toast、错误提示、`lib/*-glossary.ts` 这类文案助手都在这）
 *
 * ## 用法
 *
 *   node scripts/user-copy-scan.mjs              # 汇总 + 命中清单（退出码 = 有没有命中）
 *   node scripts/user-copy-scan.mjs --json f.json  # 另存全量清单（含未命中的 6000+ 条候选）
 *   node scripts/user-copy-scan.mjs --rule R2      # 只看某条规则
 */
import { readdirSync, statSync, readFileSync, writeFileSync } from 'node:fs'
import { join, relative, dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import ts from 'typescript'

/** 用户可见面的三个目录（`src/app` 页面 / `src/components` 组件 / `src/lib` 文案助手） */
export const SCAN_DIRS = ['src/app', 'src/components', 'src/lib']
const SKIP_DIRS = new Set(['node_modules', '.next', 'dist', 'coverage', '__pycache__'])

/**
 * **只认这些 JSX 属性**里的值是文案（白名单，不是黑名单）。
 *
 * 反面清单（黑名单）不够用 —— 实测漏过 `value="pending_review"`、`fieldKey="door_width"`、
 * `stopColor="#6366f1"`：它们都是 JSX 属性值，却**不是给商家看的字**。
 */
const ATTR_COPY =
  /^(label|title|hint|impact|boundary|placeholder|description|desc|sub|subtitle|suffix|prefix|alt|tooltip|emptyText|empty|message|note|tip|text|content|confirmText|help|error|unit|aria-label)$/

/** 不是给商家看的串：CSS / 打印样式表（含中文注释）、正则、URL */
const NOT_COPY = /@media|display\s*:|<style|box-sizing|@page|^\s*[\w-]+\s*:\s*[^;]+;|^https?:\/\//

const CJK = /[\u4e00-\u9fff]/

/**
 * 取一条规则入参的**文案字符串**。
 *
 * 🔴 规则入参的两种形态都要吃：**候选对象** `{kind, text}`（扫描面的真实入参）与
 * **裸字符串**（判别力自证 `RULES[i].test('一句坏文案')` 的写法，也是本文件长期以来的调用口径）。
 * 不统一的话就会出「同一句话，自证能判红、真扫描却报 `t.trim is not a function`」——
 * 判据与自证**两套口径**正是本仓反复治的那个病（issue #4239 的教训同族）。
 */
export const textOf = (t) => (typeof t === 'string' ? t : t.text)

/**
 * 研发腔判据（单一源）。每条 = `{ id, name, test, 出口 }`：
 * - `test` 收**一条候选文案**，命中即返回 true；
 * - `出口` 是给改的人看的那句话（守卫判红时逐条打印，必须**真可行动**）。
 *
 * 🔴 只收**机械可判、误伤面可证**的形态；散文级的「防御式辩解」（「不是…而是」「宁可不…也不…」）
 * 属**纪律**（见 `docs/design/user-facing-copy-standard.md` §3），不进机械判据 —— 它判不了。
 *
 * R6~R8 是既有守卫（issue #5565 / #5576 / #6459）的三条规则，**原样搬进本表**（同一份单一源）。
 */
export const RULES = [
  {
    id: 'R1',
    name: '接口/协议细节',
    // 「端点 / 入参 / 返回体 / 分页参数 / 拉全量 / 读面 / 写面」这类是**开发者视角**的词
    test: (t) => /端点|入参|返回体|分页参数|拉全量|读面|写面|幂等|落库|数据库|服务端|内核/.test(textOf(t)),
    出口: '换成商家视角：「系统查不到 / 请先选中商品 / 这一列是只读的」；接口与参数细节留在注释里。',
  },
  {
    id: 'R2',
    name: '内部机制名',
    // 组合键 / 派生值 / 真值源 / 快照 / 状态机 / 兜底 / 插值 / 落账 —— 都是实现里的名词
    test: (t) => /组合键|派生值|真值源|单一源|快照|状态机|兜底|插值|落账|静默/.test(textOf(t)),
    出口: '换成它**对商家的后果**：「会走另一档加工费 / 这个数是算出来的 / 改完只影响之后的单」。',
  },
  {
    id: 'R3',
    name: '研发过程编号与判据语',
    test: (t) =>
      // ⚠️ 先排掉**十六进制颜色**（`#6366f1` 会被 `#\d{3,}` 误判成 issue 号，实测假红）
      !/^#[0-9a-fA-F]{3,8}$/.test(textOf(t).trim()) &&
      /issue\s*#?\s*\d+|#\d{3,}|PR\s*#?\s*\d+|\bV\d{2,}\b|判据|待查明|死亡条件|回归测试/.test(textOf(t)),
    出口: '整句删掉（商家不关心是哪张单哪条判据）；要留追溯就写进注释 / PR body。',
  },
  {
    id: 'R4',
    name: '代码标识符上屏',
    // snake_case / 点号字段名 / 后端产物名 —— 出现在给商家看的句子里就是泄漏
    test: (t) =>
      /(^|[^A-Za-z0-9_.])[a-z][a-z0-9]*(_[a-z0-9]+)+([^A-Za-z0-9_]|$)/.test(textOf(t)) ||
      /dotGeometry|scan_url|part_token|pending_review|materials_json|yyyyMMdd|PC-yyyyMM/.test(textOf(t)),
    出口: '用中文名（「超高阈值」而不是 `oversize_height_threshold`）；键名留给注释与文档。',
  },
  {
    id: 'R5',
    name: '行内代码片里塞标识符',
    // `` `x` `` 会被 InlineMarkdown 渲染成代码小片（issue #5194）；里面只该放**商家看得懂的名字**
    test: (t) => /`[^`]*[A-Za-z][^`]*`/.test(textOf(t)),
    出口: '代码片改成商家的说法（`超高阈值`），或整段去掉反引号。',
  },
  {
    // 以下三条由既有守卫（issue #5565 / #5576 / #6459）**原样搬来**（同一份规则表，不写第二份正则）
    id: 'R6',
    name: '度量分层代号（L1/L2/L3）',
    test: (t) => /[（(]\s*L[123]\s*[）)]/.test(textOf(t)) || /L[123][ 　](?=[\u4e00-\u9fff])/.test(textOf(t)),
    出口:
      '换成"这个数是什么"的人话（如「每批布用剩多少」「每平方米成品用掉多少米布」），'
      + '代号留在注释 / 文档里（issue #5565）。',
  },
  {
    id: 'R7',
    name: '机制隐喻「池」',
    test: (t) => /池/.test(textOf(t)),
    出口:
      '改成商家的话（待派订单 / 合并派单 / 可合并的待派订单 / 加急订单（不参与合并）…）；'
      + '机制名留在注释、字段名（`pooled` / `poolingEnabled`）与内部文档里（issue #5576）。',
  },
  {
    id: 'R8',
    name: '服务端分组标签（切换后 / 存量导入 / 来源未知）',
    test: (t) => /切换后|存量导入|来源未知/.test(textOf(t)),
    出口:
      '**口径不动、呈现改说人话** —— 分组照旧（历史导入不进趋势的分子分母），'
      + '但页面上用商家的话说（如「趋势只统计系统里采购入库的批次：开业时导入的老库存不算」）；'
      + '标签留在服务端口径、注释与文档里（issue #6459）。',
  },
  {
    id: 'R9',
    name: '占位符字母 / 模式代号上屏',
    // 「库存为什么从 X 变成 Y」「A 模式 · 只查…」—— 把 X/Y 当变量、把设计文档里的模式代号写进散文，
    // 商家读不懂（用户 2026-10-08 原话：「用户不理解这句话是啥"库存为什么从 X 变成 Y"」）。
    // ⚠️ 覆盖面（实测过误伤面）：只认**当变量用的 X/Y/Z** 与 **「<字母> 模式」**；
    //    `A4` / `GB/T 47746` / `W-1002`（与 `-` `/` 数字相邻）、`B 端`/`C 端`（行业就这么叫）、
    //    `拼N次`（**选项名 = 匹配键**，改了会动行为）**都不判**。
    test: (t) => {
      const stripped = textOf(t).replace(/[A-Z]\s?端/g, '')
      return (
        /(?:^|[^A-Za-z0-9\-/._])[XYZ](?![A-Za-z0-9\-/._])/.test(stripped) ||
        /[A-Z]\s?模式/.test(stripped)
      )
    },
    出口: '把变量换成商家的话（「库存为什么从 X 变成 Y」→「库存为什么变，按时间往下看」）；'
      + '模式代号（A 模式 / C 模式）留在类型定义与设计文档里，屏上只留商家语义。',
  },
  {
    id: 'R10',
    name: '「内部键兜底」表达式上屏',
    // `Label[key] || key` —— 映射表里没有这个键时，**把内部键本身端给商家**
    // （如 `CustomerChannelLabels[channel] || channel` 会漏出 `customer_service`）。
    // 这是 issue #6663 扩的网：改前 R1~R9 只扫**字面量**，表达式形态**永远不判红**。
    // ⚠️ 实测覆盖面：全量扫面里只有 7 处命中（keyed-by 映射的兜底），零假红。
    test: (t) => /^\s*[A-Za-z_$][\w$]*\s*\[[^\]]+\]\s*\|\|\s*[A-Za-z_$][\w$]*\s*$/.test(textOf(t)),
    出口: '兜底也要说人话：`LABELS[k] ?? 「其他」`（或用服务端下发的展示名）；'
      + '**绝不要**把键本身当兜底 —— 它与「不摆内部标识」（§31 P3）相抵。',
  },
  {
    id: 'R11',
    name: '直接渲染内部键 / 环境变量名',
    // ① `{param.key}`：把**引擎标量参数的键**（`per_fold_single` …）原样印在商家脸上；
    // ② `NEXT_PUBLIC_BMINI_H5_URL` 这类**环境变量名**（部署细节，商家改不了）。
    // 这是 issue #6663 扩的网的第二半：**表达式兜底 + 内部标识**（改前只扫字面量）。
    //
    // ⚠️ 判的是「**直接渲染位置**」—— 只看**裸成员访问**（`{x.key}`）与 **JsxText 里的 env 名**：
    //    `key={x.key}` / `data-testid={`x-${x.key}`}` / `valueOf(x.key)` 都是**控件属性或函数实参**，
    //    不是上屏文本（实测：放宽到属性面会从 3 条涨到 51 条**全假红**，见守卫的判别力自证）。
    //    只认属性名 **以 `key` 结尾**（`key` / `itemKey` / `fieldKey`）或 `ENV_NAME` 形态，
    //    不去追 `{item.title}` 这类**数据字段**（那是服务端内容，不是代码标识符）。
    test: (t) =>
      // ⚠️ 前面那个字符**不能是字母**（`pageKey` 这种整体驼峰名不算「读到键」），
      //    但可以是 `.`：`param.key` / `rec.itemKey` 都要命中（实测：写成 `[a-z]` 会漏掉 `param.key`）。
      (t.kind === 'jsx-member'
        && /(^|[^A-Za-z])[Kk]ey$/.test(textOf(t))
        && /^[A-Za-z_$][\w$]*(\??\.[A-Za-z_$][\w$]*)+$/.test(textOf(t)))
      || (t.kind === 'jsx-text' && /\b[A-Z][A-Z0-9]*(_[A-Z0-9]+){2,}\b/.test(textOf(t))),
    出口: '删掉它（商家不需要看键名）；要说明「这个参数是什么」就用人话标签 + 可就地查的口径说明。'
      + '环境变量名与构建指令改成商家可行动的话（「尚未开通手机版，请联系服务方」）。',
  },
]

/**
 * **页面副标题判据**（用户 2026-10-08 定的标准）：
 * 副标题要说清「**这个功能是干什么的**」（正例：「管理客户信息、标签和互动记录」；
 * 「待派订单按料（商品 × 颜色 × 门幅）合并 —— 同料合并领料，减少接头损耗；**加急单不参与合并**」也行），
 * 关键规则要 `**加粗**`。**不写**：机制链路（⇒ / →）、表达式（`每行 = 一次…`）、
 * 本企业各自的数值口径（`0.5 米级尾料` / `0.1 米粒度`）—— 各家企业标准不同，写了反而误导。
 *
 * 只扫**商家后台**（`src/app/(dashboard)/**`）的 `h1` **兄弟** `<p>`；官网不在射程（它有自己的一套口径）。
 * 判定面 = 静态文本（含三元各分支的字面量）。
 */
export const SUBTITLE_RULES = [
  {
    id: 'S1',
    name: '副标题里的箭头链路（⇒ / →）',
    test: (t) => /⇒|→/.test(t),
    出口: '把链路拆成一句「这个功能干什么」；链路图留给设计文档。',
  },
  {
    id: 'S2',
    name: '副标题里的表达式（每行 = 一次…）',
    test: (t) => /=/.test(t),
    出口: '改成陈述句（「这里记着每一次库存变动：时间、单据、变动前后各多少」）。',
  },
  {
    id: 'S3',
    name: '副标题里的本企业数值口径（0.5 米级 / 0.1 米粒度）',
    test: (t) => /\d+(?:\.\d+)?\s*(?:米级|米粒度|米一档|位小数)/.test(t),
    出口: '讲这个功能解决什么问题即可（「尾料不足整米也能如实登记」）；具体精度留给输入校验提示。',
  },
  {
    id: 'S4',
    name: '副标题里的占位符字母 / 模式代号',
    test: (t) => RULES.find((r) => r.id === 'R9').test(t),
    出口: '同 R9：把变量与模式代号换成商家的话。',
  },
]

/** 只扫商家后台的页面头（官网有一整套自己的对外口径，不在本判据射程内） */
export const SUBTITLE_SCOPE = 'src/app/(dashboard)'

/** 豁免台账（**只许缩短**）：确有必要写长的页面头（错误态要给出下一步动作）。
 *  ⚠️ 条目按 **`文件:行号`** 键控 ⇒ **在同文件上方增删行会把条目顶失效**（失效即红，
 *  逼着你回来改准 —— 这是有意为之：宁可红一次，也不要一个指向别处的静默豁免）。
 *  issue #6573 在 `layout.tsx` 的 `ROUTE_PERMISSION_MAP` 上方插了一行（`/settings/params`
 *  守卫）⇒ 本条随之 151 → 156。 */
export const SUBTITLE_EXEMPT = [
  // 「无权访问」是**错误态**：必须写清「缺什么权限 + 去哪儿开」——短不了，且这正是用户要的引导。
  // ⚠️ 本台账按 `文件:行` 索引 ⇒ **同一文件任何加删行都要同批更新这里**（issue #6580 的
  // `ROUTE_PERMISSION_MAP` 新增两条前缀把该行从 156 推到 167 ⇒ 本条同步改号）。
  'src/app/(dashboard)/layout.tsx:168',
]

/** 抽「页面头 = h1 + 紧跟的兄弟 p」的静态文本（含三元各分支字面量） */
export function pageSubtitles(root) {
  const dir = join(root, SUBTITLE_SCOPE)
  const files = walk(dir)
  const out = []
  for (const file of files) {
    const rel = relative(root, file)
    const source = readFileSync(file, 'utf8')
    const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
    const lineOf = (node) => sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1
    const texts = (node) => {
      const parts = []
      const dig = (n) => {
        if (ts.isJsxAttribute(n)) return // ⚠️ className 等**属性**不是上屏文本（实测会被当成标题打印）
        if (ts.isJsxText(n)) { const t = n.text.trim(); if (t) parts.push(t); return }
        if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) { parts.push(n.text); return }
        ts.forEachChild(n, dig)
      }
      dig(node)
      return parts.join(' ').replace(/\s+/g, ' ').trim()
    }
    const visit = (node) => {
      if (ts.isJsxElement(node)) {
        const kids = node.children
        for (let i = 0; i < kids.length; i++) {
          const el = kids[i]
          if (!ts.isJsxElement(el)) continue
          if (el.openingElement.tagName.getText(sf) !== 'h1') continue
          for (let j = i + 1; j < kids.length; j++) {
            const sib = kids[j]
            if (!ts.isJsxElement(sib)) continue
            if (sib.openingElement.tagName.getText(sf) !== 'p') continue
            const text = texts(sib)
            if (text) out.push({ file: rel, line: lineOf(sib), title: texts(el), text })
            break
          }
        }
      }
      ts.forEachChild(node, visit)
    }
    ts.forEachChild(sf, visit)
  }
  return out
}

/** 副标题命中（豁免后） */
export function findSubtitleOffenses(root) {
  const subtitles = pageSubtitles(root)
  const offenses = []
  for (const item of subtitles) {
    const where = `${item.file}:${item.line}`
    if (SUBTITLE_EXEMPT.includes(where)) continue
    for (const rule of SUBTITLE_RULES) {
      if (rule.test(item.text)) offenses.push({ ...item, rule: rule.id, ruleName: rule.name, where })
    }
  }
  return { subtitles, offenses }
}

/**
 * 豁免台账（**只许缩短**）：登记「命中规则但确有必要」的 `仓库相对路径:行` 或 `仓库相对路径`（整文件）。
 * 守卫 `tests/unit/user-copy-jargon-guard.test.ts` 会逐条复算：**失效的豁免当场判红**（逼着删干净）。
 * 当前只有一条（`git log -p` 可见来由）。
 */
export const EXEMPT = [
  // 岗位编码输入框的 placeholder —— 这里的 `admin、customer_service` **就是内容本身**
  // （商家要照着填的编码），不是把代码标识符写进了散文里。
  // ⚠️ 本台账按 `文件:行` 索引 ⇒ 同一文件任何加删行都要同批改号（issue #6663 在 `loadRoles`
  // 里加了失败态，把本行从 360 推到 395 ⇒ 本条同步改号。失效即红，不会静默漂走）。
  'src/app/(dashboard)/roles/page.tsx:395',
]

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry)) continue
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.(tsx|ts)$/.test(entry)) out.push(full)
  }
  return out
}

/** 抽一个源文件里**会上屏**的字符串候选 */
export function candidateStrings(source, fileName = 'x.tsx') {
  const sf = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const lineOf = (node) => sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1
  const found = []
  const push = (node, text, kind) => {
    const t = text.replace(/\s+/g, ' ').trim()
    if (!t || NOT_COPY.test(t)) return
    found.push({ line: lineOf(node), kind, text: t })
  }
  const attrText = (node) => {
    const init = node.initializer
    if (!init) return null
    if (ts.isStringLiteral(init)) return init.text
    if (ts.isJsxExpression(init) && init.expression && ts.isStringLiteral(init.expression)) return init.expression.text
    return null
  }
  /** 这个字面量是不是 JSX 属性的值（不管上不上屏）—— 用于**避免重复抽**（属性分支已按白名单处理过了） */
  const isAttrValue = (node) => {
    const parent = node.parent
    if (!parent) return false
    const attr = ts.isJsxAttribute(parent) ? parent : ts.isJsxExpression(parent) ? parent.parent : null
    return !!attr && ts.isJsxAttribute(attr)
  }
  const visit = (node) => {
    if (ts.isJsxText(node)) {
      if (CJK.test(node.text) || node.text.trim().length > 2) push(node, node.text, 'jsx-text')
    } else if (ts.isJsxAttribute(node)) {
      const name = node.name.getText(sf)
      const text = attrText(node)
      if (text !== null && ATTR_COPY.test(name)) push(node, text, `attr:${name}`)
    } else if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      // ⚠️ 属性白名单要在这里**再判一次**：`className='端点 读面'` 既是 JSX 属性值、也是一个含中文的
      //    字符串字面量 —— 只在上面那个分支排除是不够的（漏了就假红）。
      if (CJK.test(node.text) && !isAttrValue(node)) push(node, node.text, 'string')
    } else if (ts.isTemplateExpression(node)) {
      // ⚠️ 只取**字面块**（`head` + 各 `templateSpans` 的 literal），把 `${…}` 插值整个丢掉：
      //    ① 插值里是表达式（`s.messageCount`），不是给商家看的字；
      //    ② 模板串的**外框**反引号更不是行内代码片（R5 判的是文案里手写的 `` `x` ``）。
      const chunks = [node.head, ...node.templateSpans.map((s) => s.literal)].map((l) => l.text)
      const inner = chunks.join(' ')
      if (CJK.test(inner)) push(node, inner, 'template')
    } else if (ts.isJsxExpression(node) && node.expression) {
      // 🔴 issue #6663 扩网：**表达式兜底**。改前只抽字面量 ⇒ `{param.key}` 这类
      //    「内部键当文案渲染」的形态**永远不判红**（判据射程外）。
      //    口径 = **直接渲染位置**：`{x.key}` 的父必须是 JSX 子内容，**不是**属性值
      //    （`key={x.key}` / `data-testid={`x-${x.key}`}` 里的成员访问是**控件属性**，
      //     不该判红 —— 实测放宽到属性面会从 3 条涨到 51 条全假红）。
      const e = stripParens(node.expression)
      const isAttrValueExpr = ts.isJsxAttribute(node.parent)
      // ⚠️ 模板串已被上面 `ts.isTemplateExpression` 分支按**字面块**抽过（R5 判的是它）；
      //    这里再抽一次会让同一个插值算两条规则 ⇒ 显式排除。
      if (!isAttrValueExpr && !ts.isTemplateExpression(e) && ts.isPropertyAccessExpression(e)) {
        push(node, e.getText(sf), 'jsx-member')
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(sf)
  return found
}

/** 剥掉括号 / 非空断言（`{(x.key)}` / `{x.key!}` 也是同一个形态） */
function stripParens(node) {
  let cur = node
  while (cur && (ts.isParenthesizedExpression(cur) || ts.isNonNullExpression(cur))) cur = cur.expression
  return cur
}

/** 全量候选（含未命中的） */
export function scanProject(root) {
  const files = SCAN_DIRS.flatMap((d) => walk(join(root, d))).sort()
  const all = []
  for (const f of files) {
    for (const item of candidateStrings(readFileSync(f, 'utf-8'), f)) {
      all.push({ file: relative(root, f), ...item })
    }
  }
  return { files: files.map((f) => relative(root, f)), candidates: all }
}

/**
 * 候选 → `{kind, text}`。**两条入口都走它**（守卫与命令行 / 扫描面与判别力自证），
 * 保证「传字符串」的旧用法（`RULES[i].test('一句文案')`）与「传候选对象」的新用法同一口径。
 */
export function toCandidate(item) {
  return typeof item === 'string' ? { kind: 'string', text: item } : item
}

/**
 * 命中清单（按规则 × 文件排序）。
 * `raw` = **豁免前**的全部命中（守卫用它判「豁免台账有没有空转」），`offenders` = 豁免后的。
 */
export function findViolations(root) {
  const { files, candidates } = scanProject(root)
  const raw = []
  for (const item of candidates) {
    for (const rule of RULES) {
      // 🔴 规则收**候选对象** `{kind, text}`：R1~R9 只用 `text`，
      //    R10/R11（issue #6663 扩网）还要按 `kind` 区分「直接渲染」与「控件属性」。
      //    ⚠️ 曾经只传 `item.text`（裸字符串）⇒ 带 `kind` 的规则**永远不判红**
      //    （实测踩过：加了规则却零命中，而全绿看起来像「没问题」）。
      if (!rule.test(item)) continue
      raw.push({ ...item, rule: rule.id, ruleName: rule.name, where: `${item.file}:${item.line}` })
    }
  }
  const offenders = raw.filter((o) => !EXEMPT.includes(o.where) && !EXEMPT.includes(o.file))
  return { files, candidates, raw, offenders }
}

export function isExempt(file, line) {
  return EXEMPT.includes(`${file}:${line}`) || EXEMPT.includes(file)
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href
if (isMain) {
  // 🔴 根按**脚本自身位置**解析（`<root>/frontend/admin-web/scripts/...` 的上两级）：
  //    这样 `node frontend/admin-web/scripts/user-copy-scan.mjs` 在**仓库根**也能直接跑
  //    —— 可复算命令必须指涉**存在**的路径（tests/unit_ci_workflows/test_recomputable_command_paths.py）。
  const root = process.env.MIGAO_COPY_ROOT || resolve(dirname(fileURLToPath(import.meta.url)), '..')
  const { files, candidates, offenders } = findViolations(root)
  const jsonAt = process.argv.indexOf('--json')
  if (jsonAt !== -1 && process.argv[jsonAt + 1]) {
    writeFileSync(process.argv[jsonAt + 1], JSON.stringify({ files, candidates, offenders }, null, 1))
    console.log(`全量清单已写入 ${process.argv[jsonAt + 1]}（候选 ${candidates.length} 条）`)
  }
  const only = process.argv.indexOf('--rule')
  const shown = only !== -1 ? offenders.filter((o) => o.rule === process.argv[only + 1]) : offenders

  console.log(`扫描 ${files.length} 个文件 · 上屏候选 ${candidates.length} 条 · 命中 ${offenders.length} 条\n`)
  const byRule = new Map()
  for (const o of offenders) byRule.set(o.rule, (byRule.get(o.rule) || 0) + 1)
  for (const r of RULES) console.log(`  ${r.id} ${r.name.padEnd(16)} ${byRule.get(r.id) || 0}`)

  const byFile = new Map()
  for (const o of shown) {
    if (!byFile.has(o.file)) byFile.set(o.file, [])
    byFile.get(o.file).push(o)
  }
  for (const [file, items] of [...byFile.entries()].sort((a, b) => b[1].length - a[1].length)) {
    console.log(`\n## ${file}  (${items.length})`)
    for (const o of items) console.log(`  L${o.line} [${o.rule}] ${o.text.slice(0, 130)}`)
  }
  // 页面副标题（结构性判据，用户 2026-10-08 定的标准）
  const { subtitles, offenses: subOffenses } = findSubtitleOffenses(root)
  console.log(`\n页面副标题（商家后台 ${subtitles.length} 个）：命中 ${subOffenses.length}`)
  for (const r of SUBTITLE_RULES) {
    console.log(`  ${r.id} ${r.name.padEnd(30)} ${subOffenses.filter((o) => o.rule === r.id).length}`)
  }
  for (const o of subOffenses) {
    console.log(`  · ${o.where} [${o.rule}] 【${o.title}】${o.text.slice(0, 110)}`)
    console.log(`    出口：${SUBTITLE_RULES.find((r) => r.id === o.rule).出口}`)
  }

  process.exit(offenders.length || subOffenses.length ? 1 : 0)
}
