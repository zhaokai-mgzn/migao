// e2e/run.js — 小布小程序 E2E 验收总入口（非测试文件，无需 case_ids）
/**
 * 前置条件：
 *   1. 微信开发者工具已安装并打开（登录账号）
 *   2. 设置 → 安全设置 → 服务端口 已开启（自动化连接必需）
 *   3. 已执行 npm run build:weapp（产物在 dist/）
 * 运行：npm run test:e2e
 * 产物：e2e/screenshots/<scenario>/*.png + e2e/report.md（均被 gitignore，不入库）
 */
const fs = require('fs')
const path = require('path')
const { launch, waitForPageReady, SCREENSHOT_DIR } = require('./lib/harness')

const SCENARIOS = [
  require('./scenarios/chat-scenario'),
  require('./scenarios/profile-scenario'),
  require('./scenarios/login-scenario'),
  require('./scenarios/multiturn-scenario'),
]

async function main() {
  console.log('🚀 启动小布小程序 E2E 验收（微信开发者工具模拟器）...')
  const mp = await launch(process.env.E2E_PORT ? Number(process.env.E2E_PORT) : 0)
  console.log('✅ 已连接模拟器')
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

  // ── 汇总报告 ──
  const lines = []
  let totalPass = 0
  let totalFail = 0
  lines.push('# 小布小程序 E2E 验收报告')
  lines.push('')
  lines.push(`- 时间: ${new Date().toLocaleString('zh-CN')}`)
  lines.push('- 环境: 微信开发者工具模拟器 + app.migaozn.com 测试环境')
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

  const reportPath = path.join(path.dirname(SCREENSHOT_DIR), 'report.md')
  fs.writeFileSync(reportPath, lines.join('\n'), 'utf8')

  console.log('\n\n📋 E2E 验收汇总:')
  console.log(`  ✅ PASS: ${totalPass} 项`)
  console.log(`  ❌ FAIL: ${totalFail} 项`)
  console.log(`  📄 报告: ${reportPath}`)
  console.log(`  🖼 截图: ${SCREENSHOT_DIR}/`)
  process.exit(totalFail === 0 ? 0 : 1)
}

main().catch((e) => {
  console.error('E2E 运行失败:', e)
  process.exit(1)
})
