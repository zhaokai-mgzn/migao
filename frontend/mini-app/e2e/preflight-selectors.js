// e2e/preflight-selectors.js — 小程序 e2e「harness ↔ 当前源码」静态契约预检（无需微信开发者工具）
//
// 为什么需要它（issue #3696）：
//   小程序 e2e（miniprogram-automator + 微信开发者工具模拟器）**跑不进 GitHub CI**
//   （需要 macOS 上的开发者工具 + 已登录 + 安全设置里开服务端口），于是真实形态验证只能由人触发
//   ⇒ 「harness 依赖的选择器/注入键是否还匹配当前源码」在跑到模拟器之前**没有任何信号**。
//   而这类漂移的代价 README 已写明：旧类名 ⇒ 断言恒红或恒绿（假红/假绿，migao-acceptance）。
//   本脚本把这份契约变成**秒级、可红、可在 CI 跑**的静态检查。
//
// 它**不是**旅程证据（不渲染、不点按、不调后端）—— 只回答「harness 硬依赖的类名与 storage 键
// 是否仍被源码产出」。真实形态证据仍需人工跑 `npm run test:e2e`（UA 级，见
// docs/testing/demo-readiness.md 的 runbook）。
//
// 判据来源（唯一事实源 = harness 自己的代码，不维护第二份清单，避免"清单漂移"变成新的假绿）：
//   · **硬依赖** = `waitForElement(page, '<sel>'` 的参数 —— 找不到即以 ok=false 结束该步骤；
//   · **探针**   = `page.$('<sel>')` —— 只读状态，其中 `__mode-btn`/`__hold-btn`/`__btn` 是
//     **有意保留的作废契约探针**（probeInputBar 注释：「不应存在」）⇒ 缺失是预期，不是红。
//     ⚠️ 首版把探针也当硬依赖 ⇒ 那三个类名"缺失"直接判红 = 本守卫自己的**假红**（已修）。
//
// 双向红证（不需要模拟器/网络）：
//   node e2e/preflight-selectors.js             # 退出码 0 = 通过
//   node e2e/preflight-selectors.js --redproof  # 退出码 0 = 双向红证通过（改名 ⇒ 必红）
//   首版守卫正是因为没跑红证才恒绿（见 stillProduced 注释）——「我以为它会红」不算红证。
//
// 用法：node e2e/preflight-selectors.js [--redproof]

const fs = require('fs')
const path = require('path')
const os = require('os')
const { execFileSync } = require('child_process')

const SRC_DIR = process.env.MIGAO_MINIAPP_SRC
  ? path.resolve(process.env.MIGAO_MINIAPP_SRC)
  : path.resolve(__dirname, '../src')
const HARNESS = path.resolve(__dirname, 'lib/harness.js')
const LOGIN = path.resolve(__dirname, 'lib/login.js')

const EXTS = new Set(['.ts', '.tsx', '.js', '.jsx', '.scss', '.css'])

/** 递归收集 src 下所有源码/样式文本（拼接为一个大字符串，够用于子串判据） */
function readSrc(dir) {
  const chunks = []
  const walk = (d) => {
    for (const name of fs.readdirSync(d)) {
      const full = path.join(d, name)
      const st = fs.statSync(full)
      if (st.isDirectory()) walk(full)
      else if (EXTS.has(path.extname(name))) chunks.push(fs.readFileSync(full, 'utf8'))
    }
  }
  walk(dir)
  return chunks.join('\n')
}

/** 硬依赖：`waitForElement(page, '<sel>'` 的实参（缺失 ⇒ 该步骤直接 ok=false） */
function requiredSelectors(harnessSrc) {
  const found = new Set()
  for (const m of harnessSrc.matchAll(/waitForElement\(\s*page\s*,\s*'(\.[^']+)'/g)) found.add(m[1])
  return [...found].sort()
}

/** 探针：`page.$('<sel>')` 的实参（只读状态；其中作废契约探针的缺失是预期） */
function probeSelectors(harnessSrc) {
  const found = new Set()
  for (const m of harnessSrc.matchAll(/page\.\$\(\s*'(\.[^']+)'\s*\)/g)) found.add(m[1])
  return [...found].sort()
}

/** storage 注入键：login.js 真正写进模拟器的键（产品侧改名 ⇒ 注入静默失效） */
function storageKeys(loginSrc) {
  const keys = new Set()
  for (const m of loginSrc.matchAll(/'(auth_token|auth_user|tenant_id|auth-store)'/g)) keys.add(m[1])
  return [...keys].sort()
}

/**
 * 类名/键是否仍被源码产出。
 * ⚠️ 必须带**边界**：首版用裸 `src.includes(name)` ⇒ 把 `message-input__textarea` 改名成
 * `message-input__textarea-RENAMED`（改名后仍以原名开头）照样判"存在" ⇒ 守卫**恒绿**（空断言）。
 * 红证（改名副本 ⇒ 必红）当场抓出这一条，故边界不能省。
 * 排除字符：`[\w-]` —— 类名/键都是 `[A-Za-z0-9_-]` 构成，后面跟这些字符即视为"不是同一个名字"。
 */
function stillProduced(src, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(escaped + '(?![\\w-])').test(src)
}

function main() {
  const src = readSrc(SRC_DIR)
  const harnessSrc = fs.readFileSync(HARNESS, 'utf8')
  const loginSrc = fs.readFileSync(LOGIN, 'utf8')

  const required = requiredSelectors(harnessSrc)
  const probes = probeSelectors(harnessSrc)
  const keys = storageKeys(loginSrc)

  const problems = []

  // 空集守卫：抽取正则失效时本预检会「静默全绿」（假绿），必须红。
  if (required.length === 0) {
    problems.push('未能从 e2e/lib/harness.js 抽出任何 waitForElement 选择器 —— 抽取逻辑失效，本预检会静默空跑')
  }
  if (keys.length === 0) {
    problems.push('未能从 e2e/lib/login.js 抽出任何 storage 注入键 —— 抽取逻辑失效，本预检会静默空跑')
  }

  console.log(`[preflight] 源码目录：${SRC_DIR}`)
  console.log(`[preflight] 硬依赖选择器 ${required.length} 个：${required.join(' ')}`)
  console.log(`[preflight] 只读探针 ${probes.length} 个（作废契约探针缺失是预期）：${probes.join(' ')}`)
  console.log(`[preflight] storage 注入键 ${keys.length} 个：${keys.join(' ')}`)

  for (const sel of required) {
    if (!stillProduced(src, sel.slice(1))) {
      problems.push(`源码里已找不到硬依赖选择器 ${sel}（harness 的 typeAndSend/waitForElement 会直接 ok=false）`)
    }
  }
  for (const k of keys) {
    if (!stillProduced(src, k)) {
      problems.push(`源码里已找不到 storage 键 ${k}（login.js 注入它建立登录态 ⇒ 注入会静默失效）`)
    }
  }

  const missingProbes = probes.filter((sel) => !stillProduced(src, sel.slice(1)))
  if (missingProbes.length) {
    console.log(`[preflight] ℹ️ 只读探针在源码里不存在（不判红，仅登记）：${missingProbes.join(' ')}`)
  }

  if (problems.length) {
    console.error('\n⛔ 小程序 e2e 静态契约预检失败：')
    for (const p of problems) console.error('   - ' + p)
    console.error('\n   处置：同步 e2e/lib/harness.js 或 e2e/lib/login.js（不要为了让它变绿而删选择器/放宽断言）。')
    process.exit(1)
  }

  console.log('\n✅ 小程序 e2e 静态契约预检通过（harness 硬依赖的选择器与 storage 注入键在 src 中都还在）')
  console.log('   ⚠️ 这**不是**旅程证据：真实形态验证仍需微信开发者工具跑 `npm run test:e2e`（UA 级，见 docs/testing/demo-readiness.md）。')
}

/**
 * 红证：把 src 复制到临时目录、改名一个硬依赖类名与一个 storage 键，断言预检**真的会红**。
 * 不跑红证的守卫 = 可能恒绿（本文件首版实证）⇒ 红证必须由仓库里可复跑的命令产出，而不是"我记得它红过"。
 */
function redproof() {
  const cases = [
    { name: '硬依赖类名改名', from: 'message-input__textarea', to: 'message-input__textarea-x', ext: '.tsx' },
    { name: 'storage 键改名', from: "'auth_token'", to: "'auth_token_v2'", ext: '.ts' },
  ]
  let failed = 0
  for (const c of cases) {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'preflight-redproof-'))
    const copy = path.join(dir, 'src')
    fs.cpSync(path.resolve(__dirname, '../src'), copy, { recursive: true })
    let touched = 0
    const walk = (d) => {
      for (const n of fs.readdirSync(d)) {
        const full = path.join(d, n)
        if (fs.statSync(full).isDirectory()) walk(full)
        else if (full.endsWith(c.ext)) {
          const before = fs.readFileSync(full, 'utf8')
          const after = before.split(c.from).join(c.to)
          if (after !== before) { fs.writeFileSync(full, after); touched++ }
        }
      }
    }
    walk(copy)
    let red = false
    try {
      execFileSync(process.execPath, [__filename], {
        env: { ...process.env, MIGAO_MINIAPP_SRC: copy },
        stdio: 'pipe',
      })
    } catch (e) {
      red = e.status === 1
    }
    if (touched === 0) {
      console.error(`⛔ 红证无效（${c.name}）：副本里一处都没改到 —— 夹具本身失效，本红证不构成证据`)
      failed++
    } else if (red) {
      console.log(`✓ 红证通过：${c.name}（改动 ${touched} 处）⇒ 预检红（exit 1）`)
    } else {
      console.error(`⛔ 红证失败：${c.name}（改动 ${touched} 处）改动后预检**仍然绿** ⇒ 该判据是空断言`)
      failed++
    }
    fs.rmSync(dir, { recursive: true, force: true })
  }
  if (failed) {
    console.error(`\n⛔ 红证 ${failed}/${cases.length} 项未通过`)
    process.exit(1)
  }
  console.log(`\n✅ 红证全部通过（${cases.length}/${cases.length}）—— 预检的双向判据都活着`)
}

if (process.argv.includes('--redproof')) redproof()
else main()
