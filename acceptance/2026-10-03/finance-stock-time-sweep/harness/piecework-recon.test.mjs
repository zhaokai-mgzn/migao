// case_ids: MC-142
//
// 计件 A0b「逐人比对」假红（issue #7030）的**夹具级**判据 —— 纯函数，零网络 / 零 DB / 零时钟。
// 复算：node --test acceptance/2026-10-03/finance-stock-time-sweep/harness/piecework-recon.test.mjs
//
// 夹具逐字取 issue #7030 的实测读数（`out/summary-raw.json` 的 A0a/A0b 两行）：
//   独立 SQL 逐人:  甲 20.70(59) / 乙 5.00(4) / 冒烟工人 0.80(2) / **null** 0.80(2)   ← 无署名那组
//   接口 per_worker: 甲 20.70 / 乙 5.00 / **未分配** 0.80 / 冒烟工人 0.80
//   两侧金额逐行一致（20.70+5.00+0.80+0.80 = 27.30 = total），**只有归集那行的名字不同**
//   ⇒ 旧 A0b 必假红。本文件把「假红消失」与「判别力没被削弱」钉在一起 —— 少一条都算没修。
import test from 'node:test'
import assert from 'node:assert/strict'
import { judgePiecework, classifyPerWorker, isUnassignedWorker, UNASSIGNED } from './piecework-recon.mjs'

const fixture = () => ({
  expectRows: [
    { worker_name: '工资验收工人甲', amount: '20.70', qty: '59' },
    { worker_name: '工资验收工人乙', amount: '5.00', qty: '4' },
    { worker_name: null, amount: '0.80', qty: '2' },
    { worker_name: '冒烟工人', amount: '0.80', qty: '2' },
  ],
  perWorker: [
    { worker_name: '工资验收工人甲', amount: 20.7 },
    { worker_name: '工资验收工人乙', amount: 5 },
    { worker_name: '未分配', amount: 0.8 },
    { worker_name: '冒烟工人', amount: 0.8 },
  ],
  total: 27.3,
})

const verdict = (input, id) => judgePiecework(input).find((v) => v.id === id)
const diffLine = (v) => v.evidence.find((e) => e.startsWith('逐人差异')) || ''

// ── 判据 ①：有未分配行 ⇒ A0b 不判红（issue #7030 的假红消失）──────────────
test('判据① 夹具含无署名归集行 ⇒ A0b 不判红（当前假红消失）', () => {
  const v = verdict(fixture(), 'A0b')
  assert.equal(v.pass, true, `A0b 仍然假红：${v.actual}｜${diffLine(v)}`)
  // 只有 3 个**真实工人**参与逐人比 —— 无署名归集不进来（不是靠"跳过"混过去，A0c 单独判它）
  assert.match(v.expect, /3 人/)
  assert.match(v.actual, /逐人一致/)
  assert.equal(diffLine(v).includes('未分配'), false, '归集行不该出现在逐人差异里')
})

// ── 判据 ②：判别力没被削弱（这条最重要）────────────────────────────────
test('判据② 同夹具把真实工人的金额改错 ⇒ A0b 必红（判别力没被削弱）', () => {
  const off = fixture()
  off.perWorker.find((r) => r.worker_name === '工资验收工人甲').amount = 20.71
  const v = verdict(off, 'A0b')
  assert.equal(v.pass, false, '真实工人错 1 分却没判红 ⇒ 判据已退化')
  assert.match(v.actual, /1 人不一致/)
  assert.match(diffLine(v), /工资验收工人甲/)
  assert.match(diffLine(v), /amount-mismatch/)
  assert.equal(diffLine(v).includes('未分配'), false, '红必须红在真因（真实工人）上，不是归集行')
})

// ── 判据 ③：未分配金额与总额的勾稽被断言（不是跳过就完事）──────────────
test('判据③ 无署名金额与总额的勾稽被断言（不是跳过）', () => {
  const [a0b, a0c] = judgePiecework(fixture())
  assert.equal(a0b.pass, true)
  assert.equal(a0c.pass, true, `勾稽没成立：${a0c.actual}`)
  const ev = a0c.evidence.join('\n')
  assert.match(ev, /Σ per_worker: 27\.30 \/ total: 27\.30/)
  assert.match(ev, /逐人合计（真实工人，接口侧）: 26\.50/)
  assert.match(ev, /无署名归集: 独立 SQL 0\.80 \/ 接口 0\.80/)
  assert.match(ev, /未分配/, '服务端文案必须进证据（读的人要能一眼看出"名不同、钱相同"）')
  assert.match(a0c.actual, /26\.50 \+ 无署名 0\.80 = 27\.30/)
})

// ── 判据 ③-补：勾稽不成立 ⇒ A0c 必红（三种坏形态）─────────────────────
test('判据③-补 勾稽不成立 ⇒ A0c 必红（漏掉 / 算错 / 接口内部不自洽）', () => {
  // ① 无署名那笔钱被接口漏掉
  const dropped = fixture()
  dropped.perWorker = dropped.perWorker.filter((r) => r.worker_name !== '未分配')
  const c1 = verdict(dropped, 'A0c')
  assert.equal(c1.pass, false, '无署名归集消失了却没判红 ⇒ 勾稽是空断言')
  assert.match(c1.actual, /无署名归集对不上|差额无法解释/)

  // ② 接口把无署名金额算错 1 分
  const off = fixture()
  off.perWorker.find((r) => r.worker_name === '未分配').amount = 0.81
  const c2 = verdict(off, 'A0c')
  assert.equal(c2.pass, false)
  assert.match(c2.actual, /无署名归集对不上/)

  // ③ 接口内部不自洽：per_worker 合计 ≠ total
  const inconsistent = fixture()
  inconsistent.total = 27.31
  const c3 = verdict(inconsistent, 'A0c')
  assert.equal(c3.pass, false)
  assert.match(c3.actual, /接口内部不自洽/)
})

// ── 文案无关性：服务端换文案不影响判定（不写死那 4 个字）───────────────
test('归集标签换文案（未署名 / — / 任意串 / 空串）⇒ 判定逐值不变', () => {
  const base = judgePiecework(fixture()).map((v) => v.pass)
  for (const label of ['未署名', '—', '(未署名工人)', 'UNASSIGNED', '']) {
    const f = fixture()
    f.perWorker.find((r) => r.worker_name === '未分配').worker_name = label
    assert.deepEqual(judgePiecework(f).map((v) => v.pass), base, `文案「${label}」改变了判定结果`)
  }
})

// ── 显式的一类：无署名 ≠ 工人（结构判定，不靠字符串巧合）──────────────
test('无署名是独立的一类：空文本组归入 UNASSIGNED，而"叫未分配的工人"仍是工人', () => {
  assert.equal(typeof UNASSIGNED, 'symbol')
  assert.equal(isUnassignedWorker(null), true)
  assert.equal(isUnassignedWorker(undefined), true)
  assert.equal(isUnassignedWorker(''), true)
  assert.equal(isUnassignedWorker('   '), true)
  // 🔴 反向：真实工人**就叫**这个文案时仍是工人（判定看结构，不看名字）
  assert.equal(isUnassignedWorker('未分配'), false)
  const c = classifyPerWorker(fixture())
  assert.equal(c.unassigned.kind, UNASSIGNED)
  assert.equal(c.assigned.length, 3)
  assert.deepEqual(c.residual.map((r) => r.worker_name), ['未分配'])
})

// ── 漏一组必红（接口少一个人不能靠"跳过"掩盖）────────────────────────
test('接口漏掉一个真实工人 ⇒ A0b 必红（missing-in-api）', () => {
  const f = fixture()
  f.perWorker = f.perWorker.filter((r) => r.worker_name !== '冒烟工人')
  const v = verdict(f, 'A0b')
  assert.equal(v.pass, false)
  assert.match(diffLine(v), /missing-in-api/)
  assert.match(diffLine(v), /冒烟工人/)
})

// ── 多行无法归因 ⇒ A0c 红（不许猜哪一行才是归集）────────────────────
test('两行都无法归因到真实工人 ⇒ A0c 红（不猜哪一行才是归集）', () => {
  const f = fixture()
  f.perWorker.push({ worker_name: '多出来的人', amount: 0 })
  const v = verdict(f, 'A0c')
  assert.equal(v.pass, false)
  assert.match(v.actual, /2 行不属于任何真实工人/)
})
