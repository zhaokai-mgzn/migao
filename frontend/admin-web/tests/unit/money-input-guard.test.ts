// case_ids: MC-161
/**
 * 涉钱 / 涉数量数字输入面的**类级元守卫**（issue #8004）。
 *
 * 病：`<input type="number">` 会吞中间态（`12.`）与千分位（`1,234.56`），**涉钱面吞一次 =
 * 商家按错的价下单**；而这类缺陷**不会让任何既有判据变红**（jsdom 里 `type="number"` 也照收）。
 * 只改 issue 点名的几处 = 没修：下一处照旧会被写出来。
 *
 * 三条判据（每条都有红证，见最后一组）：① 已迁字段按**锚点**定位，必须是 `<DecimalInput>`
 * 且不带 `type="number"`；② 剩下的 `type="number"` 必须逐条登记在台账里（**未登记即红**、
 * 台账与现取**双向相等**）；③ 扫描面非空自证（零命中的绿是假绿）。
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { extname, join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  countByFile,
  findNumberTypeHits,
  jsxTags,
  ledgerDiff,
  migratedFieldViolations,
  MIGRATED_FIELDS,
  NUMBER_INPUT_LEDGER,
} from './lib/number-input-ledger'

/**
 * 扫描面 = `frontend/admin-web/src`。cwd 在两种跑法下不同（包内 `vitest` ⇒ `frontend/admin-web`；
 * 仓根跑 ⇒ 仓根），所以**两个候选都试**，取第一个存在的；同时给出与台账 / `git grep` 逐字一致的
 * 仓库根相对前缀（找不到该前缀时前缀留空，台账对账会当场报红 —— 不会静默跳过）。
 */
const CANDIDATES = [
  { dir: resolve(process.cwd(), 'src'), prefix: 'frontend/admin-web/src' },
  { dir: resolve(process.cwd(), 'frontend/admin-web/src'), prefix: 'frontend/admin-web/src' },
]
const SCAN = CANDIDATES.find((c) => {
  try {
    return statSync(c.dir).isDirectory()
  } catch {
    return false
  }
}) ?? CANDIDATES[0]
const SRC_DIR = SCAN.dir
const REL_PREFIX = SCAN.prefix

interface SourceFile {
  rel: string
  text: string
}

function walk(dir: string, out: SourceFile[]): void {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (['.tsx', '.ts'].includes(extname(name))) {
      out.push({ rel: `${REL_PREFIX}/${full.slice(SRC_DIR.length + 1).split('\\').join('/')}`, text: readFileSync(full, 'utf8') })
    }
  }
}

function realFiles(): SourceFile[] {
  const out: SourceFile[] = []
  walk(SRC_DIR, out)
  return out
}

describe('判据 ①：涉钱 / 带小数数量字段必须走共享原语（未迁 / 迁回 ⇒ 具名判红）', () => {
  it('真语料：全部已迁字段都在 `<DecimalInput>` 上，且零 `type="number"`', () => {
    expect(migratedFieldViolations(realFiles())).toEqual([])
  })

  it('锚点清单不是空转：涉钱面 ≥ 10 个字段、数量面 ≥ 5 个字段，且都真在台账里被点名', () => {
    const money = MIGRATED_FIELDS.filter((f) => f.kind === 'money')
    const quantity = MIGRATED_FIELDS.filter((f) => f.kind === 'quantity')
    expect(money.length).toBeGreaterThanOrEqual(10)
    expect(quantity.length).toBeGreaterThanOrEqual(5)
    // 去重：同一文件同一锚点只能登记一次（否则「命中 1 个标签」的判据会歧义）
    const keys = MIGRATED_FIELDS.map((f) => `${f.file}::${f.anchor}`)
    expect(new Set(keys).size).toBe(keys.length)
  })
})

describe('判据 ②：存量台账与现取**双向相等**（未登记即红 / 台账不许虚报）', () => {
  it('真语料：`type="number"` 只剩台账里那几处，条数逐文件相等', () => {
    const hits = findNumberTypeHits(realFiles())
    expect(ledgerDiff(hits, NUMBER_INPUT_LEDGER)).toEqual({
      unregistered: [],
      stale: [],
      countMismatch: [],
    })
    // 现取读数（负载无关）：4 处，全在台账里
    expect(hits).toHaveLength(4)
    expect(Object.keys(countByFile(hits)).sort()).toEqual(NUMBER_INPUT_LEDGER.map((e) => e.file).sort())
  })

  it('台账只许「非金额非数量」：任何条目把自己写成 money / quantity 都算红', () => {
    for (const entry of NUMBER_INPUT_LEDGER) {
      expect(entry.kind).toBe('non-money-non-quantity')
      expect(entry.why.length).toBeGreaterThan(20) // 理由必须具体，不许「无」/「暂不迁」
    }
  })
})

describe('判据 ③：扫描面非空自证（判据失明比漏报更坏）', () => {
  it('扫到 ≥ 80 个源文件、≥ 200 个 JSX 开标签（空扫描的绿是假绿）', () => {
    const files = realFiles()
    expect(files.length).toBeGreaterThanOrEqual(80)
    const tags = files.reduce((n, f) => n + jsxTags(f.text).length, 0)
    expect(tags).toBeGreaterThanOrEqual(200)
  })
})

describe('判别力自证（注入式红证）：判据会红，且**具名**', () => {
  const read = (rel: string) => readFileSync(join(SRC_DIR, rel.replace(`${REL_PREFIX}/`, '')), 'utf8')
  const refundRel = 'frontend/admin-web/src/components/orders/RefundOrderModal.tsx'
  /** 全量语料里只替换一个文件的文本（其余保持真实，避免「文件不在扫描面」的噪声） */
  const withFile = (rel: string, text: string) =>
    realFiles().map((f) => (f.rel === rel ? { rel, text } : f))

  it('红证 A：把退款金额改回 `type="number"` ⇒ 判据 ① 判红并点名「退款金额」', () => {
    const text = read(refundRel).replace('<DecimalInput', '<input type="number"')
    const bad = migratedFieldViolations(withFile(refundRel, text))
    expect(bad).toHaveLength(1)
    expect(bad[0]).toContain('退款金额')
    expect(bad[0]).toContain('type="number"')
  })

  it('红证 B：把共享原语换成普通 `<Input>`（不带 number）⇒ 判据 ① 仍红（走的是非共享原语）', () => {
    const text = read(refundRel).replace('<DecimalInput', '<Input')
    const bad = migratedFieldViolations(withFile(refundRel, text))
    expect(bad).toHaveLength(1)
    expect(bad[0]).toContain('不是共享原语')
  })

  it('红证 C：锚点被改名 ⇒ 判据 ① 报「锚点找不到」（判据失明也要红，不许静默通过）', () => {
    const text = read(refundRel).replace('data-testid="refund-amount"', 'data-testid="refund-amount-v2"')
    const bad = migratedFieldViolations(withFile(refundRel, text))
    expect(bad).toHaveLength(1)
    expect(bad[0]).toContain('锚点')
  })

  it('红证 D：台账删掉一行 ⇒ 该文件的 `type="number"` 变成「未登记」', () => {
    const hits = findNumberTypeHits(realFiles())
    const withoutSuppliers = NUMBER_INPUT_LEDGER.filter((e) => !e.file.includes('suppliers'))
    expect(ledgerDiff(hits, withoutSuppliers).unregistered).toContain(
      'frontend/admin-web/src/app/(dashboard)/suppliers/page.tsx'
    )
  })

  it('红证 E：台账多写一行（迁移了却没删行）⇒ stale 判红', () => {
    const hits = findNumberTypeHits(realFiles())
    const extra = [
      ...NUMBER_INPUT_LEDGER,
      {
        file: 'frontend/admin-web/src/components/orders/RefundOrderModal.tsx',
        count: 1,
        kind: 'non-money-non-quantity' as const,
        field: '（假条目）',
        why: '这是判别力自证的假条目，真语料里不许出现（否则台账虚报）',
      },
    ]
    expect(ledgerDiff(hits, extra).stale).toEqual([
      'frontend/admin-web/src/components/orders/RefundOrderModal.tsx',
    ])
  })

  it('红证 F：凭空多出一处 `type="number"` ⇒ unregistered 判红并点名文件', () => {
    const hits = findNumberTypeHits([{ rel: 'frontend/admin-web/src/app/x.tsx', text: '<input type="number" />' }])
    expect(hits).toHaveLength(1)
    expect(ledgerDiff(hits, NUMBER_INPUT_LEDGER).unregistered).toEqual(['frontend/admin-web/src/app/x.tsx'])
  })
})

describe('负控：非涉钱 / 非数量处不被误判（判据不许变成假红机器）', () => {
  it('`type="text"` / `inputMode="decimal"` / 注释里的 `type="number"` 都不算命中', () => {
    const text = [
      '<input type="text" inputMode="decimal" />',
      '// 旧形态 type="number" 会吞中间态（注释不是代码）',
      '{/* 同上：type="number" */}',
      '<input type="number" />',
    ].join('\n')
    const hits = findNumberTypeHits([{ rel: 'frontend/admin-web/src/app/y.tsx', text }])
    expect(hits).toHaveLength(1) // 只有真正那一处
    expect(hits[0].line).toBe(4)
  })

  it('台账里的「账期天数 / 仓位编号」这几处**不被**判据 ① 误判（它们不在已迁清单里）', () => {
    const ledgerFiles = new Set(NUMBER_INPUT_LEDGER.map((e) => e.file))
    const migratedMoneyFiles = new Set(MIGRATED_FIELDS.filter((f) => f.kind === 'money').map((f) => f.file))
    for (const file of ledgerFiles) {
      expect(migratedMoneyFiles.has(file)).toBe(
        // `CustomerDetail.tsx` 同时有涉钱格（授信额度）与账期天数（非数量）⇒ 它在两个集合里都出现是**有意**的
        file.includes('customers/[id]/CustomerDetail.tsx')
      )
    }
    // 反证：`suppliers/page.tsx` 只有账期天数 ⇒ 不在涉钱面
    expect(migratedMoneyFiles.has('frontend/admin-web/src/app/(dashboard)/suppliers/page.tsx')).toBe(false)
  })
})
