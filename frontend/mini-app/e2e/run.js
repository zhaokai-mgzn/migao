// e2e/run.js — 小布小程序 E2E 验收总入口（非测试文件，无需 case_ids）
/**
 * 前置条件：
 *   1. 微信开发者工具已安装并打开（登录账号）
 *   2. 设置 → 安全设置 → 服务端口 已开启（自动化连接必需）
 *   3. 已执行 npm run build:weapp（产物在 dist/）
 *      —— dist/app.js 比 src/ 或 config/ 旧时本入口**直接报错退出**（陈旧构建护栏，失败关闭）
 * 运行：npm run test:e2e
 * 产物：e2e/screenshots/<scenario>/*.png + e2e/report.md（均被 gitignore，不入库）
 *      留档请 copy 关键项到 acceptance/<日期>/mini-app-e2e/（issue #3696）
 */
const fs = require('fs')
const path = require('path')
const { launch, waitForPageReady, assertDistFresh, SCREENSHOT_DIR, SHOT_STATS,
        formatShotStats } = require('./lib/harness')
const { ensureLoggedIn, clearStorage } = require('./lib/login')

const SCENARIOS = [
  require('./scenarios/chat-scenario'),
  require('./scenarios/profile-scenario'),
  require('./scenarios/login-scenario'),
  require('./scenarios/multiturn-scenario'),
  require('./scenarios/aftersales-scenario'),
  require('./scenarios/handoff-scenario'),
]

async function main() {
  console.log('🚀 启动小布小程序 E2E 验收（微信开发者工具模拟器）...')
  const reportPath = path.join(path.dirname(SCREENSHOT_DIR), 'report.md')

  /**
   * 前置失败时**必须清掉上一轮的报告**：否则「本轮 exit 1」与「目录里那份旧报告」会同时存在，
   * 下游完全可能把旧报告当成本轮结论（2026-09-14 固化：失败必须连证据一起失效）。
   */
  const abortBeforeRun = (title, detail) => {
    console.error(`\n⛔ ${title}（e2e 已中止，未跑任何场景）：\n`)
    console.error(`   ${detail}\n`)
    try {
      if (fs.existsSync(reportPath)) {
        fs.rmSync(reportPath, { force: true })
        console.error(`   已删除上一轮的陈旧报告 ${path.relative(process.cwd(), reportPath)}（避免被误当本轮结论）\n`)
      }
    } catch (e) {
      console.error(`   ⚠️ 陈旧报告删除失败：${e.message}\n`)
    }
    process.exit(1)
  }

  // ── 陈旧构建护栏（失败关闭）：dist 与 src/config 不一致时直接退出，不进模拟器 ──
  let freshnessLine = ''
  let freshMode = ''
  let loginLine = ''
  try {
    const fresh = assertDistFresh()
    freshnessLine =
      fresh.mode === 'content-hash'
        ? `内容指纹 ${String(fresh.hash).slice(0, 12)}…（dist/.build-stamp.json 构建于 ${fresh.stamp.builtAt}）`
        : `mtime 判据（无构建指纹）：dist/app.js ${new Date(fresh.distMtimeMs).toLocaleString('zh-CN')}`
    freshMode = fresh.mode
    console.log(`✅ 构建新鲜度检查通过[${fresh.mode}]：${freshnessLine}`)
  } catch (e) {
    abortBeforeRun('陈旧构建护栏拦截', e.message)
  }

  let mp = await launch(process.env.E2E_PORT ? Number(process.env.E2E_PORT) : 0)
  console.log('✅ 已连接模拟器')

  // ── 登录前置步骤（失败关闭，单一事实源 e2e/lib/login.js）──
  // 为什么要它：C 端 checkAuth() 只看 storage（authStore.ts:137），而模拟器里 wx.login 的 code
  // 被后端判 WECHAT_API_ERROR: code 无效（环境限制）⇒ 不建立登录态就只能「吃环境残留」，
  // 冷环境跑不出证据（migao-acceptance v1.4「环境残留给的绿」）。缺失/注入失败 ⇒ 直接失败退出。
  if (process.env.E2E_COLD_LOGIN === '1') {
    console.log('[harness] E2E_COLD_LOGIN=1 → 先清空模拟器 storage（去掉环境残留登录态），从零建立')
    await clearStorage(mp)
  }
  let login = await ensureLoggedIn(mp)
  if (login.ok && login.source === 'injected') {
    // 注入后必须让 App **冷启动**才能读到注入的 user（导航名/副标题的数据源）：
    // app.tsx:20 的 initialize() 每次 App 装载只跑一次，光 reLaunch 不会重跑。
    console.log('[harness] 已注入登录态 → 重启模拟器会话，让 App 冷启动读取注入态…')
    try {
      await mp.close()
    } catch {}
    mp = await launch(0)
    const recheck = await ensureLoggedIn(mp)
    login = { ...recheck, source: recheck.ok ? 'injected' : recheck.source }
  }
  if (!login.ok) {
    abortBeforeRun(
      `${login.marker}`,
      `${login.reason}\n` +
        '   ⇒ 无登录态时断言依赖的租户数据（botName/租户副标/订单脱敏）会缺失或降级，' +
        '那种「绿」是环境残留给的，不是代码给的 —— 故直接失败，不产出不可复现的证据。'
    )
  }
  const expect = login.user
    ? `，期望 botName=${login.user.botName ?? '(未配置→兜底小布)'} / tenantName=${login.user.tenantName ?? '(空)'}`
    : ''
  loginLine =
    login.source === 'storage'
      ? `已登录（**来自模拟器 storage 残留**，非本 harness 建立 ⇒ 本机证据仅在登录态可复现时有效）`
      : `已登录（本 harness 经短信登录注入，${login.reason}${expect}）`
  console.log(`[harness] 登录态：${loginLine}`)
  const readyPage = await waitForPageReady(mp)
  console.log(readyPage ? `✅ 页面就绪: ${readyPage.path}` : '⚠️ 30s 内页面未就绪（继续尝试，步骤级会重试）')
  console.log('')

  const reports = []
  for (const scenario of SCENARIOS) {
    console.log(`\n━━━ ${scenario.run.name} ━━━`)
    try {
      reports.push(await scenario.run(mp))
    } catch (e) {
      console.error(`  💥 场景异常: ${e.message}`)
      reports.push({ name: scenario.run.name, steps: [{ name: '场景执行', pass: false, detail: e.message }], screenshots: [] })
    }
  }

  await mp.close()

  // ── 取证预算（#3761）：把「这一轮到底抓了多少次、等了多久」打出来 ──
  // 为什么必须在入口打印：`capture()` 一次调用实际抓几帧只有运行时才知道，不打印就只能
  // 拿「调用点数量 × 猜」当成本。数字同时写进 report.md（结论档可回看）。
  console.log(`\n${formatShotStats()}`)
  const shotStatsLine = formatShotStats().replace(/\n\s+/g, ' ')

  // ── 汇总报告 ──
  const lines = []
  let totalPass = 0
  let totalFail = 0
  lines.push('# 小布小程序 E2E 验收报告')
  lines.push('')
  lines.push(`- 时间: ${new Date().toLocaleString('zh-CN')}`)
  lines.push('- 环境: 微信开发者工具模拟器 + app.migaozn.com 测试环境')
  lines.push(`- 被测构建（新鲜度护栏）: [${freshMode}] ${freshnessLine}`)
  lines.push(`- 登录态: ${loginLine}`)
  lines.push(`- 取证预算（mp.screenshot() 实际调用）: ${shotStatsLine}`)
  lines.push('')
  for (const r of reports) {
    const pass = r.steps.filter((s) => s.pass).length
    const fail = r.steps.filter((s) => !s.pass).length
    totalPass += pass
    totalFail += fail
    lines.push(`## ${r.name} — ${fail === 0 ? '✅ PASS' : `❌ ${fail} 项失败`}`)
    lines.push('')
    lines.push('| # | 步骤 | 结果 | 详情 |')
    lines.push('|---|------|------|------|')
    r.steps.forEach((s, i) => {
      lines.push(`| ${i + 1} | ${s.name} | ${s.pass ? '✅' : '❌'} | ${s.detail || '-'} |`)
    })
    if (r.screenshots.length > 0) {
      lines.push('')
      lines.push('截图：')
      for (const s of r.screenshots) lines.push(`- \`${s}\``)
    }
    lines.push('')
  }
  lines.push(`## 汇总`)
  lines.push('')
  lines.push(`| 结果 | 数量 |`)
  lines.push(`|------|------|`)
  lines.push(`| ✅ PASS | ${totalPass} |`)
  lines.push(`| ❌ FAIL | ${totalFail} |`)
  lines.push(`| 判定 | ${totalFail === 0 ? '**全部通过，验收通过**' : '**存在失败项，需修复**'} |`)
  lines.push('')
  // 取证预算落到报告里（#3761）：成本可见才可管理；`SHOT_STATS.perName` 的逐图帧数
  // 是「能否收紧 maxAttempts」的唯一实测依据（>2 帧的图必须先看这份清单）。
  lines.push('## 取证预算（#3761）')
  lines.push('')
  lines.push(`- mp.screenshot() 实际调用: **${SHOT_STATS.calls}** 次`)
  lines.push(`- 稳定帧图数: ${Object.keys(SHOT_STATS.perName).length} 张`)
  lines.push(`- 稳定等待: ${SHOT_STATS.waits} 次 × 1.5s = **${(SHOT_STATS.waitMs / 1000).toFixed(1)}s**`)
  const multiFrame = Object.keys(SHOT_STATS.perName).filter((n) => SHOT_STATS.perName[n] > 2)
  lines.push(`- 需 >2 帧才稳定的图: ${multiFrame.length ? multiFrame.map((n) => `${n}(${SHOT_STATS.perName[n]}帧)`).join(', ') : '（无）'}`)
  lines.push('')

  fs.writeFileSync(reportPath, lines.join('\n'), 'utf8')

  console.log('\n\n📋 E2E 验收汇总:')
  console.log(`  ✅ PASS: ${totalPass} 项`)
  console.log(`  ❌ FAIL: ${totalFail} 项`)
  console.log(`  📄 报告: ${reportPath}`)
  console.log(`  🖼 截图: ${SCREENSHOT_DIR}/`)
  console.log(`  📸 mp.screenshot(): ${SHOT_STATS.calls} 次（${Object.keys(SHOT_STATS.perName).length} 张图）`)
  process.exit(totalFail === 0 ? 0 : 1)
}

main().catch((e) => {
  console.error('E2E 运行失败:', e)
  process.exit(1)
})
