/**
 * 数字输入面的台账与扫描器（issue #8004 的**类级元守卫**承载体）。
 *
 * 病：`<input type="number">` 在**涉钱 / 涉数量**面会吞精度（中间态 `12.` / `0.`、千分位
 * `1,234.56` 都不被浏览器认），而这类缺陷**不会让任何既有判据变红** —— 它只会在商家手里
 * 变成「按错的价下单」。只改几处的修法留不住同类：第 N+1 处照旧会被写出来。
 *
 * 所以这里落三条**机械**判据（承载体 = `frontend/admin-web/tests/unit/money-input-guard.test.ts`）：
 * ① **已迁字段必须真在共享原语上**：每个涉钱 / 带小数数量字段按 **锚点**（`data-testid` / `id` /
 *    `aria-label` 的唯一片段）定位它的 JSX 开标签 ⇒ 该标签**必须**是 `<DecimalInput>`，
 *    且**不许**带 `type="number"`（未迁 / 迁回 ⇒ 具名判红）；
 * ② **存量逐条登记**：剩下的每一处 `type="number"` 必须在本台账里写明「为什么它不是涉钱/涉数量面」——
 *    **未登记即红**；台账与现取**双向相等**（只许缩短，不许悄悄放宽）；
 * ③ **扫描面非空自证**：一条命中也找不到 ⇒ 判红（空扫描的绿是假绿）。
 *
 * 扫描口径（如实登记的边界）：剥注释 + 按 **JSX 开标签**（花括号 / 圆括号配平）找
 * `type="number"`，**不做 AST、不追数据流** —— 经变量或 `{...props}` 传进去的 `type` 不在射程。
 */

/** 台账条目：一处**有意保留**的 `type="number"` */
export interface NumberInputLedgerEntry {
  /** 仓库根相对路径（与 `git grep` 的路径逐字一致） */
  file: string
  /** 现取：该文件（剥注释后）的 `type="number"` 次数 */
  count: number
  /** 语义分类 —— 只允许「非金额非数量」；`money` / `quantity` **禁止**出现在台账里 */
  kind: 'non-money-non-quantity'
  /** 字段名（人读） */
  field: string
  /** 为什么不迁（**必须具体**：值域 + 为什么没有精度可丢 + 重启条件） */
  why: string
}

/**
 * 已迁字段的**锚点清单**（判据 ①）。锚点不是行号 —— 行号几分钟就漂（`migao-dev-flow` §2.2），
 * 而 `data-testid` / `id` / `aria-label` 是**可检索文本**：改名 / 删掉都会让判据当场报「锚点找不到」。
 */
export interface MigratedField {
  file: string
  /** 必须是该 JSX 开标签里**逐字出现**的唯一片段 */
  anchor: string
  /** 口径名（人读 + 判红时点名用） */
  field: string
  /** money = 涉钱面（判据 ① 的硬面）；quantity = 带小数的数量面（同一原语，同类风险） */
  kind: 'money' | 'quantity'
}

export const MIGRATED_FIELDS: readonly MigratedField[] = [
  // ── 涉钱面
  { file: 'frontend/admin-web/src/components/orders/RefundOrderModal.tsx', anchor: 'data-testid="refund-amount"', field: '退款金额', kind: 'money' },
  { file: 'frontend/admin-web/src/components/orders/EditOrderContentModal.tsx', anchor: 'edit-line-price-', field: '明细单价', kind: 'money' },
  { file: 'frontend/admin-web/src/components/orders/EditOrderContentModal.tsx', anchor: 'data-testid="edit-discount"', field: '优惠金额', kind: 'money' },
  { file: 'frontend/admin-web/src/components/orders/EditOrderContentModal.tsx', anchor: 'data-testid="edit-actual"', field: '实收款', kind: 'money' },
  { file: 'frontend/admin-web/src/app/(dashboard)/finance/page.tsx', anchor: 'data-testid="finance-form-amount"', field: '财务登记金额', kind: 'money' },
  { file: 'frontend/admin-web/src/app/(dashboard)/purchase-orders/page.tsx', anchor: 'purchase-form-price-', field: '采购单价', kind: 'money' },
  { file: 'frontend/admin-web/src/app/(dashboard)/inbound-orders/new/page.tsx', anchor: '单价`}', field: '入库单价', kind: 'money' },
  { file: 'frontend/admin-web/src/app/(dashboard)/customers/[id]/CustomerDetail.tsx', anchor: 'data-testid="credit-limit"', field: '授信额度', kind: 'money' },
  { file: 'frontend/admin-web/src/app/(dashboard)/products/[id]/ProductDetail.tsx', anchor: 'id="sku-price-editor"', field: 'SKU 行内改价', kind: 'money' },
  { file: 'frontend/admin-web/src/components/approvals/RequestApprovalModal.tsx', anchor: 'data-testid="approval-request-amount"', field: '审批金额', kind: 'money' },
  { file: 'frontend/admin-web/src/components/products/SkuMatrix.tsx', anchor: 'data-testid="sku-batch-price"', field: 'SKU 批量单价', kind: 'money' },
  // ── 涉数量面（**text 形态**：去掉 `type="number"`，口径与话术仍由各页既有校验承担）
  { file: 'frontend/admin-web/src/app/(dashboard)/purchase-orders/page.tsx', anchor: 'purchase-form-qty-', field: '采购数量（米）', kind: 'quantity' },
  { file: 'frontend/admin-web/src/app/(dashboard)/inbound-orders/new/page.tsx', anchor: '卷长`}', field: '入库卷长（米）', kind: 'quantity' },
  { file: 'frontend/admin-web/src/app/(dashboard)/inbound-orders/new/page.tsx', anchor: '数量（米）`}', field: '入库数量（米）', kind: 'quantity' },
  { file: 'frontend/admin-web/src/app/(dashboard)/inbound-orders/new/page.tsx', anchor: '卷数`}', field: '入库卷数（整数）', kind: 'quantity' },
  { file: 'frontend/admin-web/src/app/(dashboard)/outbound-orders/page.tsx', anchor: 'placeholder="如 12.5"', field: '出库数量（米）', kind: 'quantity' },
  { file: 'frontend/admin-web/src/components/orders/EditOrderContentModal.tsx', anchor: 'edit-line-quantity-', field: '明细数量（整数）', kind: 'quantity' },
  { file: 'frontend/admin-web/src/components/stock/WarehouseLocationPanel.tsx', anchor: 'data-testid="warehouse-capacity-input"', field: '每仓容量（件）', kind: 'quantity' },
  { file: 'frontend/admin-web/src/components/stock/WarehouseLocationPanel.tsx', anchor: 'data-testid="warehouse-batch-capacity"', field: '批量每仓容量（件）', kind: 'quantity' },
  { file: 'frontend/admin-web/src/components/products/BatchStocktakeForm.tsx', anchor: '实盘米数`}', field: '实盘米数（0.1 米刻度）', kind: 'quantity' },
]

/**
 * 台账（**只许缩短**）：剩下的 `type="number"` 全是「非金额非数量」的整数口径字段。
 *
 * 三条共同理由（逐条写在 `why` 里）：① 值域是**整数**（天数 / 编号），没有小数位可丢；
 * ② 受控状态是**字符串原文**，没有 `Number(e.target.value)` 往返（没有那个往返就没有中间态被吞）；
 * ③ `type="number"` 对纯整数输入只会丢 `"12."` 这类**小数**中间态 —— 整数格不产生该中间态。
 * **重启条件**：一旦该字段的值域出现小数 / 千分位输入 / 变成金额，就必须迁 `DecimalInput` 并从这里删行。
 */
export const NUMBER_INPUT_LEDGER: readonly NumberInputLedgerEntry[] = [
  {
    file: 'frontend/admin-web/src/app/(dashboard)/customers/[id]/CustomerDetail.tsx',
    count: 1,
    kind: 'non-money-non-quantity',
    field: '账期天数（0 = 现结，0~365 整数）',
    why: '整数天数，无小数位可丢；状态是字符串原文，无 Number() 往返；上限由入参 max 兜住（保存前另有 0~365 校验）',
  },
  {
    file: 'frontend/admin-web/src/app/(dashboard)/suppliers/page.tsx',
    count: 1,
    kind: 'non-money-non-quantity',
    field: '账期天数（0 = 现结，0~365 整数）',
    why: '同客户档案的账期天数：整数天数、字符串状态、无小数位可丢',
  },
  {
    file: 'frontend/admin-web/src/components/stock/WarehouseLocationPanel.tsx',
    count: 2,
    kind: 'non-money-non-quantity',
    field: '批量新建仓位的起始 / 结束编号（整数序号，1~9999）',
    why: '整数序号（生成 A-01…A-20），既非金额也非数量；无小数位可丢，状态是字符串原文',
  },
]

/** 扫描根（只裁 admin-web；小程序 / H5 的数字键盘口径由各自包的既有一级判据承担） */
export const SCAN_ROOTS: readonly string[] = ['frontend/admin-web/src']

/** 剥注释：`//`、块注释 / JSX 注释；**保留字符串原文**（`type="number"` 就活在那里） */
export function stripComments(src: string): string {
  let out = ''
  let i = 0
  while (i < src.length) {
    const c = src[i]
    const n = src[i + 1]
    if (c === '/' && n === '/') {
      while (i < src.length && src[i] !== '\n') i += 1
      continue
    }
    if (c === '/' && n === '*') {
      i += 2
      while (i < src.length && !(src[i] === '*' && src[i + 1] === '/')) {
        if (src[i] === '\n') out += '\n'
        i += 1
      }
      i += 2
      continue
    }
    if (c === '"' || c === "'" || c === '`') {
      const quote = c
      out += c
      i += 1
      while (i < src.length) {
        out += src[i]
        if (src[i] === '\\') {
          i += 1
          if (i < src.length) out += src[i]
          i += 1
          continue
        }
        if (src[i] === quote) {
          i += 1
          break
        }
        i += 1
      }
      continue
    }
    out += c
    i += 1
  }
  return out
}

/** 一个 JSX 开标签（`name` = 标签名，`raw` = 原文，`line` = 起始行） */
export interface JsxTag {
  name: string
  raw: string
  line: number
}

/**
 * 收集 JSX **开标签**：`<` + 字母起头，按花括号 / 圆括号 / 引号配平找收尾的 `>`。
 * 这样 `onChange={(e) => …}` 里的 `>`、`{'x>y'}` 这类内容不会把标签截断。
 */
export function jsxTags(src: string): JsxTag[] {
  const stripped = stripComments(src)
  const out: JsxTag[] = []
  let i = 0
  while (i < stripped.length) {
    if (stripped[i] !== '<') {
      i += 1
      continue
    }
    // 名字后面必须紧跟空白 / `/` / `>`：这样 `a <b)` / `useState<Record<…>>` 这类比较与泛型不会被当成标签
    const nameMatch = /^<([A-Za-z][\w.]*)(?=[\s/>])/.exec(stripped.slice(i))
    if (!nameMatch) {
      i += 1
      continue
    }
    let j = i + nameMatch[0].length
    let brace = 0
    let paren = 0
    let done = false
    while (j < stripped.length) {
      const c = stripped[j]
      if (c === '"' || c === "'" || c === '`') {
        const quote = c
        j += 1
        while (j < stripped.length) {
          if (stripped[j] === '\\') {
            j += 2
            continue
          }
          if (stripped[j] === quote) break
          j += 1
        }
        j += 1
        continue
      }
      if (c === '{') brace += 1
      else if (c === '}') brace -= 1
      else if (c === '(') paren += 1
      else if (c === ')') paren -= 1
      else if (c === '>' && brace <= 0 && paren <= 0) {
        done = true
        break
      }
      j += 1
    }
    if (!done) break
    const raw = stripped.slice(i, j + 1)
    const line = stripped.slice(0, i).split('\n').length
    out.push({ name: nameMatch[1], raw, line })
    i = j + 1
  }
  return out
}

/** 命中：文件 + 行号（1 起） */
export interface NumberTypeHit {
  file: string
  line: number
}

const NUMBER_TYPE_RE = /\btype\s*=\s*(["'])number\1/

/** 现取：`files` 里带 `type="number"` 的 JSX 开标签（行号用于**具名报红**，不进台账） */
export function findNumberTypeHits(files: { rel: string; text: string }[]): NumberTypeHit[] {
  const hits: NumberTypeHit[] = []
  for (const f of files) {
    for (const tag of jsxTags(f.text)) {
      if (NUMBER_TYPE_RE.test(tag.raw)) hits.push({ file: f.rel, line: tag.line })
    }
  }
  return hits
}

/** 按文件聚合（台账对账用） */
export function countByFile(hits: NumberTypeHit[]): Record<string, number> {
  const out: Record<string, number> = {}
  for (const h of hits) out[h.file] = (out[h.file] ?? 0) + 1
  return out
}

/**
 * 台账双向对账：
 * - `unregistered`：现取有、台账没写 ⇒ **新增的 `type="number"`**（类级病复发）
 * - `stale`：台账写了、现取没有 ⇒ 台账虚报（迁移了却没删行 = 台账失去意义）
 * - `countMismatch`：同文件条数变了（多一处 / 少一处都要人重新登记）
 */
export function ledgerDiff(
  hits: NumberTypeHit[],
  ledger: readonly NumberInputLedgerEntry[]
): { unregistered: string[]; stale: string[]; countMismatch: string[] } {
  const actual = countByFile(hits)
  const registered = new Map(ledger.map((e) => [e.file, e]))
  const unregistered = Object.keys(actual).filter((f) => !registered.has(f)).sort()
  const stale = ledger.map((e) => e.file).filter((f) => actual[f] === undefined).sort()
  const countMismatch = ledger
    .filter((e) => actual[e.file] !== undefined && actual[e.file] !== e.count)
    .map((e) => `${e.file}（台账 ${e.count} / 现取 ${actual[e.file]}）`)
    .sort()
  return { unregistered, stale, countMismatch }
}

/**
 * 判据 ① 的读数：每个已迁字段必须能找到**恰好一个** JSX 开标签，且该标签
 * (a) 是 `<DecimalInput>`；(b) 不带 `type="number"`。
 * 找不到锚点也判红 —— 那说明字段被改名/搬走而判据**失明**了（比漏报更坏）。
 */
export function migratedFieldViolations(
  files: { rel: string; text: string }[],
  fields: readonly MigratedField[] = MIGRATED_FIELDS
): string[] {
  const byFile = new Map(files.map((f) => [f.rel, f.text]))
  const bad: string[] = []
  for (const f of fields) {
    const text = byFile.get(f.file)
    if (text === undefined) {
      bad.push(`${f.file}::${f.field} —— 文件不在扫描面（判据失明）`)
      continue
    }
    const owners = jsxTags(text).filter((t) => t.raw.includes(f.anchor))
    if (owners.length === 0) {
      bad.push(`${f.file}::${f.field} —— 锚点 \`${f.anchor}\` 找不到（改名 / 搬走？重锚后再判）`)
      continue
    }
    if (owners.length > 1) {
      bad.push(`${f.file}::${f.field} —— 锚点 \`${f.anchor}\` 命中 ${owners.length} 个标签，无法判定`)
      continue
    }
    const tag = owners[0]
    if (NUMBER_TYPE_RE.test(tag.raw)) {
      bad.push(`${f.file}:${tag.line}::${f.field} —— 仍是 type="number"（未迁或迁回）`)
      continue
    }
    if (f.kind === 'money' && tag.name !== 'DecimalInput') {
      // 涉钱面**必须**走共享原语（一处解析 + 一处校验 + 一处话术），不许各页自己写一套
      bad.push(`${f.file}:${tag.line}::${f.field} —— 走的是 <${tag.name}>，不是共享原语 <DecimalInput>`)
    } else if (f.kind === 'quantity') {
      // 数量面允许保留各页既有的精确口径（0.1 米粒度 / 正整数…），但控件必须是 **text 形态**
      if (!/inputMode\s*=/.test(tag.raw)) {
        bad.push(`${f.file}:${tag.line}::${f.field} —— 缺 inputMode（手机端会弹错键盘）`)
      } else if (tag.name === 'input' && !/type\s*=\s*(["'])text\1/.test(tag.raw)) {
        bad.push(`${f.file}:${tag.line}::${f.field} —— 裸 <input> 必须显式 type="text"（不许只靠默认值）`)
      }
    }
  }
  return bad
}
