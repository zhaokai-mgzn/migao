// case_ids: BM-040
/**
 * 时间口径收敛到**一处**（issue #6666 判据 8）
 *
 * ## 实测读数（读码，head 未改前）
 *
 * bmini 同族信息有**四份**互不相同的写法：
 * | 面 | 写法 | 出参 |
 * |---|---|---|
 * | 对话气泡 `MessageBubble` | `formatTime`（本文件内私有） | 今天 `09:30` / 非今天 `10-09 09:30` |
 * | 坐席会话详情气泡 | `createdAt.slice(11, 16)` | 恒 `09:30`（**跨天也不带日期**） |
 * | 坐席列表 | `createdAt.slice(5, 16)` | 恒 `10-10 09:30`（今天也带日期） |
 * | 「数据」页待办 | `createdAt.slice(0, 16)` | 恒 `2026-10-10 09:30` |
 *
 * ⇒ 审计说的「**同页**两种格式」不准确（四条各在不同面），但**跨面四份口径**是真的。
 * 本判据把口径收敛到 `src/utils/datetime.ts` 的 `formatMessageTime` 一处。
 *
 * | # | 判据 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | `formatMessageTime`：今天 `HH:MM` / 非今天 `MM-DD HH:MM` / 非法输入 `''` | 改口径 ⇒ 红 |
 * | 2 | 单一实现：`src` 内只有一处定义 | 又抄一份 ⇒ 红 |
 * | 3 | 四个面都改用它，且不再出现截字符串的时间渲染（`slice(0|5|11, 16)`） | 新写一处截串 ⇒ 具名红 |
 */
import fs from 'fs'
import path from 'path'
import { formatMessageTime } from '../src/utils/datetime'

const ROOT = path.resolve(__dirname, '..')
const SRC = path.join(ROOT, 'src')

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walk(p, out)
    else out.push(p)
  }
  return out
}

/** 时间渲染的截串写法（四份口径的历史形态） */
const SLICE_TIME = /slice\(\s*(0|5|11)\s*,\s*16\s*\)/

const SURFACES = [
  'src/components/chat/MessageBubble.tsx',
  'src/pages/sessions/detail/index.tsx',
  'src/pages/sessions/index/index.tsx',
  'src/pages/dashboard/index/index.tsx',
]

describe('formatMessageTime（issue #6666 判据 8）', () => {
  it('今天的消息 ⇒ 只给 HH:MM（与「今天」比较，不带日期）', () => {
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 9, 5).toISOString()
    expect(formatMessageTime(today)).toBe('09:05')
  })

  it('非今天 ⇒ MM-DD HH:MM', () => {
    const d = new Date(2026, 9, 3, 18, 7) // 2026-10-03 18:07 本地
    expect(formatMessageTime(d.toISOString())).toBe('10-03 18:07')
  })

  it('非法 / 空输入 ⇒ 空串（不编时间）', () => {
    expect(formatMessageTime('')).toBe('')
    expect(formatMessageTime('not-a-date')).toBe('')
  })
})

describe('时间口径单一真值（issue #6666 判据 8）', () => {
  const files = walk(SRC)

  it('src 内只有一处 formatMessageTime 定义', () => {
    const defs = files.filter((f) =>
      /export\s+function\s+formatMessageTime/.test(fs.readFileSync(f, 'utf-8')),
    )
    expect(defs.map((f) => path.relative(ROOT, f).split(path.sep).join('/'))).toEqual([
      'src/utils/datetime.ts',
    ])
  })

  it.each(SURFACES)('%s 改用了共享口径，且不再截字符串渲染时间', (surface) => {
    const src = fs.readFileSync(path.join(ROOT, surface), 'utf-8')
    expect(src).toContain('formatMessageTime')
    expect(SLICE_TIME.test(src)).toBe(false)
  })
})
