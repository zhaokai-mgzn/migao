import { chromium } from '/Users/guangzhen.zk/ai native/migao/tests/node_modules/playwright/index.mjs'

const OUT = '/tmp/ui-acceptance-6432'
const NO = 'W-PIN6432-CHK'
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const result = { workerNo: NO }
try {
  await page.goto('http://localhost:3001/login', { waitUntil: 'domcontentloaded' })
  await page.getByText('管理员登录', { exact: false }).first().click()
  await page.getByPlaceholder(/手机号/).fill('13800138000')
  await page.getByText('获取验证码', { exact: false }).first().click()
  await page.getByPlaceholder(/验证码/).fill('123456')
  await page.getByRole('button', { name: /登\s*录/ }).click()
  await page.waitForURL(/dashboard/, { timeout: 30000 })

  await page.goto('http://localhost:3001/employees', { waitUntil: 'domcontentloaded' })
  await page.getByText('工人档案', { exact: true }).click()
  await page.getByPlaceholder(/输入工号或姓名搜索/).fill(NO)
  await page.getByText('查询', { exact: true }).click()
  await page.waitForTimeout(1500)

  const existsAlready = await page.getByText(NO, { exact: true }).count() > 0
  if (!existsAlready) {
    await page.getByText('新建工人档案').click()
    await page.getByPlaceholder(/W-1002/).fill(NO)
    await page.getByPlaceholder(/李四/).fill('PIN验收临时工')
    await page.getByPlaceholder(/位数字/).fill('111111')
    await page.getByText('创建', { exact: true }).click()
    await page.getByText(NO, { exact: true }).waitFor({ state: 'visible', timeout: 20000 })
    result.created = true
  } else {
    result.created = 'already-existed'
  }

  await page.getByText('重置 PIN').first().click()
  await page.getByText('确认重置').click()
  const pinBox = page.getByTestId('worker-new-pin')
  await pinBox.waitFor({ state: 'visible', timeout: 20000 })
  result.pin = (await pinBox.innerText()).replace(/[^0-9]/g, '')
  await page.screenshot({ path: `${OUT}/03-reset-pin-result.png` })
  await page.getByText('完成', { exact: true }).click()

  const rowText = await page.locator('tr, [class*="grid"]').filter({ hasText: NO }).first().innerText().catch(() => '')
  result.rowBefore = rowText.replace(/\s+/g, ' ').slice(0, 80)
  await page.getByText('停用').first().click()
  await page.waitForTimeout(1500)
  const after = await page.locator('tr, [class*="grid"]').filter({ hasText: NO }).first().innerText().catch(() => '')
  result.rowAfter = after.replace(/\s+/g, ' ').slice(0, 80)
  console.log(JSON.stringify(result))
} catch (e) {
  console.error('FAILED', e.message)
  await page.screenshot({ path: `${OUT}/99-failure.png` }).catch(() => {})
  console.log(JSON.stringify(result))
  process.exitCode = 1
} finally {
  await browser.close()
}
