// 时钟自检（红证形态：会红的正对照）——
// 目的：把「harness 的 +08 口径」钉在**被测系统的同一时钟源**上，防止
// 「本地 getter + 手动偏移」这种双重换算再次静默发生（2026-10-03 实测踩过：cst 快 8h）。
//
// 判据：nowCST().cst 与 SQL `now() at time zone 'Asia/Shanghai'` 的**秒级差 ≤ 5s**，
//       且 nowCST().utc 与 nowCST().cst 互相自洽（差恰为 8 小时）。
import { nowCST, cstWall, psql, judge, log } from './lib.mjs'

export function familyT(R) {
  const n = nowCST()
  const sqlNow = psql(`select to_char(now() at time zone 'Asia/Shanghai','YYYY-MM-DD HH24:MI:SS') v`)[0].v
  const nodeWall = cstWall()
  const dCst = Math.abs(new Date(`${n.cst.slice(0, 19)}Z`).getTime() - new Date(`${sqlNow.replace(' ', 'T')}Z`).getTime()) / 1000
  judge(R, {
    id: 'T1',
    name: 'harness 时钟自检：nowCST().cst 与 SQL(+08) 一致（秒级 ≤5s）',
    expect: `与 SQL ${sqlNow} 相差 ≤5s`, actual: `harness=${n.cst} node本地=${nodeWall} 差=${dCst}s`,
    pass: dCst <= 5,
    expectSource: `独立时钟源：SQL \`now() at time zone 'Asia/Shanghai'\`（DB 侧）—— 与被测系统 BusinessClock 同一时区口径。` +
      `若 harness 用「本地 getter + 手动偏移」，此判据会立刻红（实测偏差恰 8h=28800s）。`,
    evidence: [`harness cst=${n.cst}`, `harness utc=${n.utc}`, `SQL +08=${sqlNow}`,
      `自洽性: cst − utc 应 = 8h`],
  })
  // 内部自洽（cst 与 utc 必须同刻）
  const selfConsistent = Math.abs(
    new Date(`${n.cst.slice(0, 19)}Z`).getTime() - new Date(n.utc).getTime()
  ) / 3600000
  judge(R, {
    id: 'T2',
    name: 'harness 时钟自洽：cst 与同结构的 utc 相差恰 8 小时（防"同文件自相矛盾"）',
    expect: '8.000h', actual: `${selfConsistent.toFixed(3)}h`,
    pass: Math.abs(selfConsistent - 8) < 0.01,
    expectSource: 'cst 是 +08 墙钟、utc 是 UTC ⇒ 同刻两者必差 8h。这一条正是原 bug 的现场（原实现差 16h：21:40 vs 05:40）。',
    evidence: [`cst=${n.cst}`, `utc=${n.utc}`],
  })
  log(`时钟自检: harness=${n.cst} / SQL(+08)=${sqlNow} / 差=${dCst}s`)
}
