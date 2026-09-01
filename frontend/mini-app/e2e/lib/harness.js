// e2e/lib/harness.js — 小布小程序 E2E 验收公共工具（非测试文件，无需 case_ids）
/**
 * 依赖：微信开发者工具（已安装）+ 设置→安全设置→服务端口 已开启
 * 用法：见 e2e/run.js（npm run test:e2e）
 */
const path = require('path')
const fs = require('fs')
const { execFileSync } = require('child_process')
const automator = require('miniprogram-automator')

const PROJECT_PATH = path.resolve(__dirname, '../..') // mini-app 根目录（e2e/lib → 上两级，含 project.config.json）
const CLI_PATH = '/Applications/wechatwebdevtools.app/Contents/MacOS/cli'
const SCREENSHOT_DIR = path.resolve(__dirname, '../screenshots')

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function runCli(args) {
  try {
    return execFileSync(CLI_PATH, args, { encoding: 'utf8', timeout: 30000 }) || ''
  } catch (e) {
    return `ERR: ${e.message}`
  }
}

/**
 * 启动并连接模拟器。策略（微信开发者工具自动化已知坑）：
 *   - 窗口已开：cli auto 附加稳定 ✅（cli open 反而会报 ✖ preparing 冲突）
 *   - 窗口未开/坏窗口：cli auto 新开窗口命令会超时 → 先 cli close + cli open 重建窗口，再附加
 * 实现：先直接 launch + 短探测；失败则 close+open 重建窗口重试。
 */
async function launch(port = 0) {
  const finalPort = port || 9421 + Math.floor(Math.random() * 100)
  console.log(`[harness] launch 尝试（port=${finalPort}）`)
  for (let attempt = 1; attempt <= 3; attempt++) {
    let mp = null
    try {
      mp = await automator.launch({
        projectPath: PROJECT_PATH,
        cliPath: CLI_PATH,
        port: finalPort,
        timeout: 60000,
      })
    } catch (e) {
      console.warn(`[harness] launch 第 ${attempt} 次连接失败: ${e.message}`)
    }
    if (mp) {
      const page = await probePage(mp, 20000)
      if (page && page.path) return mp
      console.warn(`[harness] 第 ${attempt} 次窗口未就绪，尝试重建窗口`)
      try { await mp.close() } catch {}
    }
    runCli(['close', '--project', PROJECT_PATH])
    const out = runCli(['open', '--project', PROJECT_PATH])
    console.log(`[harness] 重建窗口: ${out.includes('✔ open') ? '✔ open' : out.split('\n').filter(l => l.trim()).slice(-2).join(' | ')}`)
    await sleep(10000)
  }
  throw new Error('连续 3 次 launch 失败，请检查微信开发者工具状态（是否登录、服务端口是否开启）')
}

/** 短探测：轮询 currentPage 直到拿到有效页面 */
async function probePage(mp, timeoutMs) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const page = await mp.currentPage()
      if (page && page.path) return page
      if (!page) console.log('[probe] currentPage 返回 null')
    } catch (e) {
      console.log(`[probe] currentPage 异常: ${e.message.slice(0, 120)}`)
    }
    await sleep(1000)
  }
  return null
}

/** 等待当前页面就绪（launch 后 IDE 可能仍在编译/加载，轮询直到拿到有效 page） */
async function waitForPageReady(mp, timeoutMs = 60000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const page = await mp.currentPage()
      if (page && page.path) return page
    } catch {}
    await sleep(1000)
  }
  return null
}

/** 全屏截图并保存到 e2e/screenshots/<scenario>/<name>，返回绝对路径 */
async function capture(mp, scenario, name) {
  const dir = path.join(SCREENSHOT_DIR, scenario)
  fs.mkdirSync(dir, { recursive: true })
  const file = path.join(dir, name)
  try {
    await mp.screenshot({ path: file })
    return file
  } catch (e) {
    console.warn(`[harness] 截图失败 ${file}: ${e.message}`)
    return null
  }
}

/** 轮询等待页面出现匹配 selector 的元素，超时返回 null */
async function waitForElement(page, selector, timeoutMs = 20000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    const el = await page.$(selector)
    if (el) return el
    await sleep(500)
  }
  return null
}

/** 轮询等待元素文本包含 text（el 缺失视为未满足） */
async function waitForText(page, selector, text, timeoutMs = 20000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const el = await page.$(selector)
      if (el) {
        const t = (await el.text()) || ''
        if (t.includes(text)) return t
      }
    } catch {}
    await sleep(500)
  }
  return null
}

/** 轮询等待用户/助手气泡出现并产出有效文本（剔除流式光标「|」，避免提前判定） */
async function waitForBubble(page, role, timeoutMs = 120000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const els = await page.$$(`.message-bubble--${role}`)
      if (els && els.length > 0) {
        const last = els[els.length - 1]
        const t = (await last.text()) || ''
        // 有效文本：去掉光标与时间戳后仍有内容（如「|16:53」→ 无效，继续等）
        const meaningful = t.replace(/\|/g, '').replace(/\d{1,2}:\d{2}/g, '').trim()
        if (meaningful.length >= 2) return t
      }
    } catch {}
    await sleep(1000)
  }
  return null
}

/** 等待流式回复结束：助手气泡文本连续两次读取一致（含 tool_call 中间过程） */
async function waitForStreamEnd(page, timeoutMs = 60000) {
  const start = Date.now()
  let prevText = null
  while (Date.now() - start < timeoutMs) {
    try {
      const els = await page.$$('.message-bubble--assistant')
      if (els && els.length > 0) {
        const t = (await els[els.length - 1].text()) || ''
        if (prevText !== null && t === prevText && t.trim()) return t
        prevText = t
      }
    } catch {}
    await sleep(1000)
  }
  return prevText
}

/** 轮询等待出现包含指定文本的气泡（用于精确断言新消息，避免匹配旧气泡） */
async function waitForBubbleText(page, role, text, timeoutMs = 30000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const els = await page.$$(`.message-bubble--${role}`)
      if (els && els.length > 0) {
        for (const el of els) {
          const t = (await el.text()) || ''
          if (t.includes(text)) return t
        }
      }
    } catch {}
    await sleep(500)
  }
  return null
}

/** 统计页面当前某种气泡数量 */
async function countBubbles(page, role) {
  try {
    const els = await page.$$(`.message-bubble--${role}`)
    return els ? els.length : 0
  } catch {
    return -1
  }
}

/** 读取某种气泡最后一条的文本（无则 null） */
async function lastBubbleText(page, role) {
  try {
    const els = await page.$$(`.message-bubble--${role}`)
    if (els && els.length > 0) return (await els[els.length - 1].text()) || ''
  } catch {}
  return null
}

/** 收集断言结果的小报告器 */
function makeReporter(scenarioName) {
  const steps = []
  const screenshots = []
  return {
    step(name, pass, detail = '') {
      steps.push({ name, pass, detail })
      const icon = pass ? '✅' : '❌'
      console.log(`  ${icon} ${name}${detail ? ` — ${detail}` : ''}`)
    },
    screenshot(scenario, name) {
      const p = path.join(scenario, name)
      screenshots.push(p)
      return p
    },
    result() {
      return { name: scenarioName, steps, screenshots }
    },
  }
}

module.exports = {
  PROJECT_PATH,
  CLI_PATH,
  SCREENSHOT_DIR,
  launch,
  waitForPageReady,
  capture,
  sleep,
  waitForElement,
  waitForText,
  waitForBubble,
  waitForBubbleText,
  waitForStreamEnd,
  countBubbles,
  lastBubbleText,
  makeReporter,
}
