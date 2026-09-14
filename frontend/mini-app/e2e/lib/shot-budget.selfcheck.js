// e2e/lib/shot-budget.selfcheck.js — 取证预算的**无模拟器**自检（issue #3761）
/**
 * 为什么需要它：本改动砍掉了 5 次"终态重拍"（绿路径 16 → 11 张）。但"省成本"必须证明
 * **判定能力没被削弱**，否则就是拿证据换钱。这里用**桩 mp**（不启微信开发者工具、不联网、
 * 零 LLM）把两条红线钉成红证：
 *
 *   ① 稳定性判据仍然有效：喂"永远在变的过渡帧" ⇒ 仍判「不稳定」（落最后一帧 + 告警），
 *      而不是静默当成证据；
 *   ② `maxAttempts` **不得**收紧：喂"第 4 帧才稳定"（验收报告 §5-2 实测：点发送后
 *      3~4.5s 才稳定）⇒ 若把上限降到 2，落盘的就是过渡帧（正是本机制要防的假绿）。
 *      本自检断言"需要 4 帧时确实抓了 4 次"—— 谁把上限改小，这里立刻红；
 *   ③ `captureFinal` 的失败门仍然有效：全绿 ⇒ **0 次**抓取（省成本）；
 *      有失败步骤 ⇒ **照常抓**（`migao-acceptance` v1.4「失败即丢证据」不被破坏）。
 *
 * 运行：node frontend/mini-app/e2e/lib/shot-budget.selfcheck.js
 *   （无需 node_modules：`miniprogram-automator` 被桩掉；CI 由
 *    tests/unit_ci_workflows/test_e2e_shot_budget.py 锁同一批不变式）
 */
const fs = require('fs')
const path = require('path')
const Module = require('module')

// 桩掉 miniprogram-automator：本自检不启动模拟器（也不会因为没装依赖而失败）
const _origLoad = Module._load
Module._load = function (request, ...rest) {
  if (request === 'miniprogram-automator') {
    return { launch: async () => { throw new Error('selfcheck: 不应启动模拟器') } }
  }
  return _origLoad.call(this, request, ...rest)
}

const harness = require('./harness')
const { capture, makeReporter, resetShotStats, SHOT_STATS, SCREENSHOT_DIR } = harness

const SCENARIO = '_selfcheck'
const DIR = path.join(SCREENSHOT_DIR, SCENARIO)

/**
 * 造一个桩 mp：`frames` 是逐帧的字节序列（不足时重复最后一帧）。
 * 稳定性判据是"连续两帧一致"，故 `stableAt=2` ⇒ frames[0] === frames[1]；
 * `stableAt=4` ⇒ 前 3 帧各不相同、第 4 帧与第 3 帧相同。
 */
function stubMp(frames) {
  let i = 0
  const calls = []
  return {
    calls,
    async screenshot({ path: file }) {
      const body = frames[Math.min(i, frames.length - 1)]
      i += 1
      calls.push(body)
      fs.writeFileSync(file, Buffer.from(body))
    },
  }
}

function stableFrames(stableAt) {
  // 稳定性判据 = "连续两帧一致" ⇒ 要在**第 stableAt 次**抓取时判稳定，
  // 需要前 stableAt-1 帧互不相同、第 stableAt 帧与它前一帧相同。
  const frames = []
  for (let k = 1; k <= stableAt - 1; k++) frames.push(`frame-${k}`)
  frames.push(`frame-${stableAt - 1}`)
  return frames
}

const results = []
function check(name, ok, detail) {
  results.push({ name, ok, detail })
  console.log(`${ok ? '✅' : '❌'} ${name}${detail ? ` — ${detail}` : ''}`)
}

async function main() {
  fs.mkdirSync(DIR, { recursive: true })

  // ── ① 过渡帧仍被识别为"不稳定"（红证：机制没被删） ──
  resetShotStats()
  let mp = stubMp(['a', 'b', 'c', 'd', 'e', 'f', 'g'])
  const file = await capture(mp, SCENARIO, 'never-stable.png', 5, 10)
  check('① 永远在变的帧 ⇒ 仍判「不稳定」（抓满 maxAttempts=5 次 + 落盘最后一帧）',
    mp.calls.length === 5 && SHOT_STATS.calls === 5 && fs.existsSync(file),
    `screenshot 调用 ${mp.calls.length} 次，落盘=${!!file}`)
  check('①′ 计数与真实调用一致（不虚报预算）', SHOT_STATS.calls === mp.calls.length,
    `SHOT_STATS.calls=${SHOT_STATS.calls} vs 实际 ${mp.calls.length}`)

  // ── ② maxAttempts 不得收紧：第 4 帧才稳定时必须抓 4 次 ──
  resetShotStats()
  mp = stubMp(stableFrames(4))
  await capture(mp, SCENARIO, 'stable-at-4.png', 5, 10)
  check('② 第 4 帧才稳定 ⇒ 抓 4 次（把 maxAttempts 改成 2 会落过渡帧 → 本断言必红）',
    mp.calls.length === 4, `screenshot 调用 ${mp.calls.length} 次`)

  // ── ②′ 对照：第 2 帧就稳定 ⇒ 2 次（下限也是 2 帧，不可能更省） ──
  resetShotStats()
  mp = stubMp(stableFrames(2))
  await capture(mp, SCENARIO, 'stable-at-2.png', 5, 10)
  check('②′ 第 2 帧即稳定 ⇒ 抓 2 次（稳定帧的**下限**，每次 capture ≥2 次 mp.screenshot()）',
    mp.calls.length === 2, `screenshot 调用 ${mp.calls.length} 次`)

  // ── ③ captureFinal 的失败门 ──
  resetShotStats()
  mp = stubMp(stableFrames(2))
  const greenRep = makeReporter('全绿场景')
  greenRep.step('步骤 A', true, '')
  const greenFile = await greenRep.captureFinal(mp, SCENARIO, 'green-final.png')
  check('③ 全绿 ⇒ 终态补拍 0 次抓取、不登记进报告（省的就是这 5 张）',
    mp.calls.length === 0 && greenFile === null && greenRep.result().screenshots.length === 0,
    `screenshot 调用 ${mp.calls.length} 次，screenshots=${JSON.stringify(greenRep.result().screenshots)}`)

  resetShotStats()
  mp = stubMp(stableFrames(2))
  const redRep = makeReporter('有失败场景')
  redRep.step('步骤 A', true, '')
  redRep.step('步骤 B', false, '故意失败')
  const redFile = await redRep.captureFinal(mp, SCENARIO, 'red-final.png')
  check('③′ 有失败步骤 ⇒ 照常补抓（≥2 次）且登记进报告（失败即丢证据的反面）',
    mp.calls.length >= 2 && !!redFile && redRep.result().screenshots.includes(path.join(SCENARIO, 'red-final.png')),
    `screenshot 调用 ${mp.calls.length} 次，screenshots=${JSON.stringify(redRep.result().screenshots)}`)

  // ── 汇总 ──
  const failed = results.filter((r) => !r.ok)
  console.log('')
  console.log(`取证预算自检: ${results.length - failed.length}/${results.length} 通过`)
  try {
    fs.rmSync(DIR, { recursive: true, force: true })
  } catch {}
  process.exit(failed.length === 0 ? 0 : 1)
}

main().catch((e) => {
  console.error('自检异常:', e)
  try { fs.rmSync(DIR, { recursive: true, force: true }) } catch {}
  process.exit(1)
})
