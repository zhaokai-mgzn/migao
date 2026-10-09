// case_ids: UI-095
/**
 * 打印单据**表格列数不变量**（issue #6595）。
 *
 * 为什么单独一个文件：判据是「**任意**一张打印单据的表格，逐行的 `Σ(colSpan)` 必须等于该表列数」，
 * 它要能被**每份单据的测试**复用（加工单 / 报价单 / 销售单 / 发货单 / 任务卡）——
 * 写在某一个测试文件里就只守得住那一份（「只修一处 = 没修」）。
 *
 * 缺陷标本（issue #6595，实测）：加工单主体行原先只渲染 7 格，而表头是 8 列
 * ⇒ 第 8 列（备注）在**数据行**没有任何单元格 ⇒ **整列没有边框**，纸面右侧缺一块。
 * 该形态在 jsdom 里照样可判：少一格时 `Σ(colSpan) = 7 < 8`。
 *
 * 放 `src/` 的前提：只导出纯函数、**零运行时副作用**（不被任何生产代码 import ⇒ 不进包）。
 */
export interface TableIntegrityResult {
  /** 表头列数（多行表头取第一行；`colSpan` 计入） */
  columns: number
  /** 逐行的 `Σ(colSpan)` */
  rows: number[]
}

/** 一行占几列：`Σ(colSpan)`（缺省 `colSpan` 记 1） */
function spanningColumns(row: Element): number {
  return Array.from(row.children).reduce((sum, cell) => {
    const span = Number(cell.getAttribute('colspan') ?? '1')
    return sum + (Number.isFinite(span) && span > 0 ? span : 1)
  }, 0)
}

/** 逐表校验：表头列数必须是个正数，且**每一行**都与它相等 */
export function collectTableIntegrity(tables: readonly Element[]): TableIntegrityResult[] {
  return tables.map((table, index) => {
    const headRow = table.querySelector('thead tr') ?? table.querySelector('tr')
    if (!headRow) throw new Error(`表格 ${index} 没有任何行`)
    const columns = spanningColumns(headRow)
    if (columns === 0) throw new Error(`表格 ${index} 的表头一行占 0 列`)
    const rows = Array.from(table.querySelectorAll('tr')).map(spanningColumns)
    for (const [rowIndex, rowColumns] of rows.entries()) {
      if (rowColumns !== columns) {
        throw new Error(
          `表格 ${index} 第 ${rowIndex + 1} 行占 ${rowColumns} 列，表头是 ${columns} 列` +
            `（该行少了一格 ⇒ 那一列在数据行没有单元格、也就没有边框）`
        )
      }
    }
    return { columns, rows }
  })
}

/**
 * 断言容器里**每一张**表的行/列自洽；返回逐表读数（测试里可复算）。
 * 找不到任何表 ⇒ 抛错（没渲染出来的单据不该被读成通过）。
 */
export function assertDocTableIntegrity(root: ParentNode | null): TableIntegrityResult[] {
  const tables = Array.from(root?.querySelectorAll('table') ?? [])
  if (tables.length === 0) throw new Error('没有找到任何表格：单据没有渲染出来')
  return collectTableIntegrity(tables)
}

/**
 * 单据的**正文明细表**（带 `<thead>` 的多列表）—— 缺陷 #6595 就出在这一族上。
 *
 * 表头信息表（`Order` 抬头那几栏）是 `tbody`-only，且它的行**本来就不等列**（`地址` / `货运` 两行是
 * `label + colspan=3`，其余行是两对 label/value；实测 4+4+6+4+6 列 ⇒ 表格是 6 列宽）
 * ⇒ 把它放进「逐行等列」这条不变量会**假红**。判别依据用 `<thead>`：纸面**正文**明细表都有，
 * 抬头信息表没有 —— 见 `frontend/admin-web/src/components/orders/ProcessingDoc.tsx` 的 `SetBlock`。
 */
export function dataTables(root: ParentNode | null): HTMLTableElement[] {
  return Array.from(root?.querySelectorAll<HTMLTableElement>('table') ?? []).filter(
    (table) => table.querySelector('thead') !== null
  )
}
