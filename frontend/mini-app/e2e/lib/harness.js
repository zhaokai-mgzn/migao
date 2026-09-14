// e2e/lib/harness.js — 小布小程序 E2E 验收公共工具（非测试文件，无需 case_ids）
/**
 * 依赖：微信开发者工具（已安装）+ 设置→安全设置→服务端口 已开启
 * 用法：见 e2e/run.js（npm run test:e2e）
 */
const path = require('path')
const fs = require('fs')
const crypto = require('crypto')
const { execFileSync } = require('child_process')
const automator = require('miniprogram-automator')
const { computeSourceHash } = require('./source-hash')

const PROJECT_PATH = path.resolve(__dirname, '../..') // mini-app 根目录（e2e/lib → 上两级，含 project.config.json）
const CLI_PATH = '/Applications/wechatwebdevtools.app/Contents/MacOS/cli'
const SCREENSHOT_DIR = path.resolve(__dirname, '../screenshots')
const DIST_APP_PATH = path.join(PROJECT_PATH, 'dist', 'app.js')

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * 陈旧构建护栏（失败关闭，issue #3696/#3705 结构性问题的直接对策）
 *
 * 背景（2026-09-14 实证）：`#2953` 输入条重设计后 `src/` 已更新，但 `dist/` 仍是 09-04 的旧产物 ——
 * 「旧脚本 + 旧构建」自洽，e2e 跑出 **35/36 全绿**，却完全没验证当前代码；重建后才暴露过期选择器。
 * 这正是 `migao-acceptance` v1.2 的「假绿」形态：验证对象与被测代码错配。
 *
 * 判据（两级，失败关闭）：
 *  ① **内容指纹（首选）**：`dist/.build-stamp.json`（由 `npm run build:weapp` 写入）里的
 *     src/+config/ sha256 指纹 ≠ 当前指纹 ⇒ 陈旧。与 mtime 无关，不惧 `git checkout`/换机/时钟偏差。
 *  ② **mtime 兜底（指纹缺失时）**：`dist/app.js` mtime < src/、config/ 最新文件 mtime ⇒ 陈旧。
 *  ③ `dist/app.js` 缺失 ⇒ 直接失败。
 * 一律报错退出，不做自动构建 —— 自动构建会掩盖「忘了构建」这一信号，且 `dist/` 是多流程
 * （build:h5 / 手动 dev 构建）共享产物目录，悄悄重建会替换别人正在用的产物。
 */
function assertDistFresh() {
  if (!fs.existsSync(DIST_APP_PATH)) {
    throw new Error(
      `未找到构建产物 ${path.relative(PROJECT_PATH, DIST_APP_PATH)}。\n` +
        '  ⇒ e2e 必须驱动真实构建产物，不能对着不存在的 dist 跑。\n' +
        '  请先执行：cd frontend/mini-app && npm run build:weapp'
    )
  }
  const built = computeSourceHash(PROJECT_PATH)

  // ① 内容指纹（首选）
  const stamp = readBuildStamp()
  if (stamp && stamp.hash) {
    if (stamp.hash !== built.hash) {
      throw new Error(
        `构建产物与源码不一致（内容指纹）：\n` +
          `  dist 构建于 ${stamp.builtAt}（指纹 ${String(stamp.hash).slice(0, 12)}…，${stamp.files} 个文件）\n` +
          `  当前源码指纹 ${built.hash.slice(0, 12)}…（${built.files} 个文件）\n` +
          '  ⇒ 继续跑等于「用旧构建验证新代码」：旧脚本配旧构建自洽，会跑出一片假绿（2026-09-14 实证 35/36 通过）。\n' +
          '  请先执行：cd frontend/mini-app && npm run build:weapp'
      )
    }
    return { mode: 'content-hash', hash: built.hash, stamp, newestSource: built.newest && built.newest.file, newestSourceMtimeMs: built.newest && built.newest.mtimeMs }
  }

  // ② mtime 兜底（无指纹：dist 由更早版本流程构建 / 指纹被删）
  const distMtimeMs = fs.statSync(DIST_APP_PATH).mtimeMs
  const newest = built.newest
  if (newest && newest.mtimeMs > distMtimeMs) {
    throw new Error(
      `构建产物陈旧：dist/app.js（${new Date(distMtimeMs).toLocaleString('zh-CN')}）` +
        `早于源码 ${path.relative(PROJECT_PATH, newest.file)}（${new Date(newest.mtimeMs).toLocaleString('zh-CN')}）。\n` +
        '  ⇒ 继续跑等于「用旧构建验证新代码」：旧脚本配旧构建自洽，会跑出一片假绿（2026-09-14 实证 35/36 通过）。\n' +
        '  请先执行：cd frontend/mini-app && npm run build:weapp'
    )
  }
  console.warn(
    '[harness] ⚠️ 未找到 dist/.build-stamp.json，本次退化为 mtime 判据（对 git checkout/时钟偏差不鲁棒）。' +
      '建议重跑 npm run build:weapp 以生成内容指纹。'
  )
  return { mode: 'mtime-fallback', distMtimeMs, newestSource: newest && newest.file, newestSourceMtimeMs: newest && newest.mtimeMs }
}

/** 读取构建指纹（缺失/损坏返回 null → 走 mtime 兜底） */
function readBuildStamp() {
  try {
    return JSON.parse(fs.readFileSync(path.join(PROJECT_PATH, 'dist', '.build-stamp.json'), 'utf8'))
  } catch {
    return null
  }
}

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

/**
 * 全屏截图并保存到 e2e/screenshots/<scenario>/<name>，返回绝对路径
 *
 * **稳定帧等待**（2026-09-14 实测新增）：`mp.screenshot()` 在 UI 刚变化后可能返回
 * 过渡帧/滞后帧（探针实测：输入草稿后立即抓 → 与 1.5s 后抓的帧不同；点发送后连抓
 * 3 张帧各不同，约 3~4.5s 才稳定）。直接落盘会让**截图证据与被断言的 DOM 状态不一致**
 * —— 而截图正是验收报告里给人看的那一条证据链。故连抓直到「连续两帧完全一致」。
 */
async function capture(mp, scenario, name, maxAttempts = 5, intervalMs = 1500) {
  const dir = path.join(SCREENSHOT_DIR, scenario)
  fs.mkdirSync(dir, { recursive: true })
  const file = path.join(dir, name)
  let prevHash = null
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      await mp.screenshot({ path: file })
    } catch (e) {
      console.warn(`[harness] 截图失败 ${file}: ${e.message}`)
      return null
    }
    const hash = crypto.createHash('md5').update(fs.readFileSync(file)).digest('hex')
    if (hash === prevHash) {
      if (attempt > 2) console.log(`  [shot] ${name} 稳定帧（第 ${attempt - 1} 次抓取才稳定）`)
      return file
    }
    prevHash = hash
    if (attempt < maxAttempts) await sleep(intervalMs)
  }
  console.warn(`[harness] ${name} 连续 ${maxAttempts} 帧仍在变化（流式/动画中），落盘最后一帧`)
  return file
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

/**
 * 等待流式回复结束：助手气泡文本连续两次读取一致（含 tool_call 中间过程）
 *
 * ⚠️ 这是**启发式**，不是「可以再发送」的判据：工具调用间隙文本本就会停顿 >1s，
 * 会提前返回。2026-09-14 实测：R2 返回耗时 2043ms，而真实流式还要再跑 **66s**
 * （动作键仍是停止键）→ 此时发送键按设计不渲染。判"流式真的结束"请用 `waitForStreamIdle`。
 */
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

/**
 * 等待「本次发送触发的助手回复」（正确判据：**发送前的基线文本** → 之后出现**不同且非空**的助手文本）
 *
 * 两个都试过、都不对的写法（2026-09-14 实测，别再退回）：
 *  ① `aiReply2 !== prevAiText` 但 prevAiText 在**发送之后**才取：此刻新回复可能已开始/完成，
 *     快照到的「旧」文本就是新回复本身 → **假红**（run5 实测：回复 len=491 却判「无新内容」）。
 *  ② 按**气泡数量增加**判定：小程序的助手气泡在**流式一开始就被创建**（TypingIndicator 靠它显示），
 *     若快照晚于该创建时刻，数量永远不会增加 → **假红**（cold-run3 实测：`2→2`，而末条 AI 气泡
 *     正是本次问题的回复，len=324）。
 * ⇒ 唯一稳的判据 = **发送前**取基线文本，之后等「非空且 != 基线」。返回文本，超时返回 null。
 */
async function waitForAssistantReply(page, prevText, timeoutMs = 120000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const t = (await lastBubbleText(page, 'assistant')) || ''
      const meaningful = t.replace(/\|/g, '').replace(/\d{1,2}:\d{2}/g, '').trim()
      if (meaningful.length >= 2 && t !== prevText) return t
    } catch {}
    await sleep(1000)
  }
  return null
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

/**
 * 读取输入条真实状态（选择器依据 = src/components/chat/MessageInput.tsx，#2953 单容器双语义）
 * 历史坑：旧脚本用 `.message-input__hold-btn` / `.message-input__mode-btn` / `.message-input__btn`，
 * 这三个类在重设计后**源码与产物里都不存在** → 断言恒红（假红）。
 */
async function probeInputBar(page) {
  const textarea = await page.$('.message-input__textarea')
  const sendBtn = await page.$('.message-input__icon-btn--send')
  const sendClass = sendBtn ? (await sendBtn.attribute('class')) || '' : ''
  return {
    textarea: !!textarea,
    value: textarea ? await textarea.attribute('value') : null,
    placeholder: textarea ? await textarea.attribute('placeholder') : null,
    disabled: textarea ? (await textarea.attribute('disabled')) === 'true' : null,
    container: !!(await page.$('.message-input__container')),
    /** 已作废契约的残留探针：模式切换键/独立"按住说话"按钮不应存在（UI-007 单容器） */
    modeSwitch: !!(await page.$('.message-input__mode-btn')),
    holdBtn: !!(await page.$('.message-input__hold-btn')),
    voiceBtn: !!(await page.$('.message-input__icon-btn--voice')),
    sendBtn: !!sendBtn,
    sendDisabled: sendClass.includes('--disabled'),
    sendClass,
    /** 流式中 = 动作键为停止键（`src/components/chat/MessageInput.tsx` isStreaming 分支） */
    stopBtn: !!(await page.$('.message-input__icon-btn--stop')),
  }
}

/**
 * 等待流式真正结束：直接以 DOM 判据为准 —— 动作键不再是停止键（`.message-input__icon-btn--stop`）。
 * 不用「气泡文本 1s 内不变」的启发式（`waitForStreamEnd`）：工具调用间隙文本本就会停顿 >1s，
 * 会误判为已结束 → 此时动作键仍是停止键，发送键不渲染（2026-09-14 实测）。
 */
async function waitForStreamIdle(page, timeoutMs = 90000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    if (!(await page.$('.message-input__icon-btn--stop'))) return Date.now() - start
    await sleep(1000)
  }
  return null
}

/**
 * 单容器语义下"输入并发送"（#2953）：textarea 常驻 → 输入 → 右下自适应键变发送 → 点发送。
 * 发送键**查找失败/禁用态一律返回 ok=false**（旧脚本 `if (sendBtn) tap()` 会静默跳过 → 假绿：
 * 消息根本没发出，后续"无回复"被记成后端问题）。
 * 发送前先等流式结束（动作键从停止键变回语音键）—— 流式中发送键按设计不渲染，不是"放宽断言"。
 */
async function typeAndSend(page, text, sendTimeoutMs = 10000, onDraftReady = null) {
  const textarea = await waitForElement(page, '.message-input__textarea', 15000)
  if (!textarea) return { ok: false, reason: '未找到输入框 .message-input__textarea' }
  const idleMs = await waitForStreamIdle(page)
  if (idleMs === null) {
    const stuck = await probeInputBar(page)
    return { ok: false, reason: `90s 内流式未结束（动作键仍为停止键 stopBtn=${stuck.stopBtn}），发送键按设计不渲染` }
  }
  const before = await probeInputBar(page)
  await textarea.input(text)
  const sendBtn = await waitForElement(page, '.message-input__icon-btn--send', sendTimeoutMs)
  if (!sendBtn) {
    const now = await probeInputBar(page)
    return {
      ok: false,
      voiceBefore: before.voiceBtn,
      reason:
        `输入草稿后未渲染发送键：value=${JSON.stringify(now.value)} disabled=${now.disabled} ` +
        `stopBtn=${now.stopBtn} voice=${now.voiceBtn} send=${now.sendBtn}`,
    }
  }
  const sendClass = (await sendBtn.attribute('class')) || ''
  if (sendClass.includes('--disabled')) {
    const now = await probeInputBar(page)
    return {
      ok: false,
      voiceBefore: before.voiceBtn,
      sendClass,
      reason: `发送键为禁用态（${sendClass}）value=${JSON.stringify(now.value)} disabled=${now.disabled} stopBtn=${now.stopBtn}`,
    }
  }
  const after = await probeInputBar(page)
  // 草稿就绪、尚未点发送 —— 需要「有草稿=发送键」的视觉证据时在此回调里截图
  // （踩过的坑：在 tap() 之后截图，草稿已被清空 → 截出来的图与文件名/断言状态不符）
  if (onDraftReady) await onDraftReady()
  await sendBtn.tap()
  return { ok: true, idleMs, voiceBefore: before.voiceBtn, voiceAfter: after.voiceBtn, sendClass }
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
  waitForAssistantReply,
  waitForStreamEnd,
  waitForStreamIdle,
  countBubbles,
  lastBubbleText,
  probeInputBar,
  typeAndSend,
  assertDistFresh,
  makeReporter,
}
