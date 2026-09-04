// case_ids: OR-001, AS-001, UI-015
/**
 * 小布「我的」页 E2E 验收
 * 覆盖：tab 切换 → 用户信息区 → 订单/售后区块 → 设置项
 */
const { capture, sleep, waitForElement, makeReporter } = require('../lib/harness')

const SCENARIO = 'profile'

async function run(mp) {
  const rep = makeReporter('个人中心页验收')

  // ── 1. 切换到「我的」tab ──
  const page = await mp.switchTab('/pages/profile/index/index')
  await sleep(1500)
  rep.step('切换到「我的」tab', !!page && page.path === 'pages/profile/index/index',
    page ? `path=${page.path}` : '切换失败')
  await capture(mp, SCENARIO, '01-profile.png')

  // ── 2. 页面主体 ──
  const profileRoot = await waitForElement(page, '.profile-page', 10000)
  rep.step('个人中心页渲染', !!profileRoot, profileRoot ? 'profile-page 存在' : '未渲染')

  // ── 3. 用户信息区（已登录显示昵称；未登录显示引导）──
  const nickname = await waitForElement(page, '.user-nickname', 8000)
  const notLoggedIn = await page.$('.not-logged-text')
  if (nickname) {
    const t = (await nickname.text()) || ''
    rep.step('用户信息区展示', t.length > 0, `nickname=${t || '(空)'}`)
  } else if (notLoggedIn) {
    rep.step('用户信息区展示（未登录态）', true, '显示「请先登录」引导')
  } else {
    rep.step('用户信息区展示', false, '既无昵称也无未登录引导')
  }

  // ── 4. 订单/售后区块 ──
  const orderTitle = await waitForElement(page, '.section-card__title', 8000)
  const titles = orderTitle ? await page.$$('.section-card__title') : []
  let orderOk = false
  let afterOk = false
  if (titles && titles.length > 0) {
    for (const el of titles) {
      const t = (await el.text()) || ''
      if (t.includes('我的订单')) orderOk = true
      if (t.includes('我的售后')) afterOk = true
    }
  }
  rep.step('「我的订单」区块', orderOk, orderOk ? '存在' : '缺失')
  rep.step('「我的售后」区块', afterOk, afterOk ? '存在' : '缺失')

  // ── 5. 设置项 ──
  const settings = await page.$$('.setting-label')
  const labels = []
  if (settings && settings.length > 0) {
    for (const el of settings) labels.push((await el.text()) || '')
  }
  // UI-015 已移除「账号信息」占位入口（2026-09-04 #2851），设置项为 关于我们 + 隐私协议
  rep.step('设置项（关于我们/隐私协议）', labels.includes('关于我们') && labels.includes('隐私协议'),
    `labels=${labels.join(' / ') || '(空)'}`)

  await capture(mp, SCENARIO, '02-profile-full.png')
  rep.screenshot(SCENARIO, '01-profile.png')
  rep.screenshot(SCENARIO, '02-profile-full.png')

  return rep.result()
}

module.exports = { run }
