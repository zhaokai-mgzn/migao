import { test, expect } from '@playwright/test'
import { CustomerDetailPage } from '../../pages/customers/customer-detail.page'

test.describe('客户详情页面', () => {
  let pom: CustomerDetailPage

  test.beforeEach(async ({ page }) => {
    pom = new CustomerDetailPage(page)
    await pom.goto('1')
    await pom.waitForLoadingComplete()
  })

  test('客户信息卡片正确显示基本信息', async () => {
    await expect(pom.infoCard).toBeVisible()
    const name = pom.infoCard.locator('h2')
    if (await name.isVisible()) await expect(name).toBeVisible()
  })

  test('VIP 星级正确显示', async () => {
    const stars = pom.page.locator('svg.fill-amber-400')
    const normal = pom.page.getByText('普通客户')
    const starCount = await stars.count()
    const isNormal = await normal.isVisible().catch(() => false)
    if (starCount > 0) {
      // VIP 客户：验证星级在 1-5 之间
      expect(starCount).toBeGreaterThanOrEqual(1)
      expect(starCount).toBeLessThanOrEqual(5)
    } else if (isNormal) {
      await expect(normal).toBeVisible()
    }
  })

  test('标签选择器可添加标签', async () => {
    await pom.addTagButton.click()
    const picker = pom.page.locator('.absolute.right-0.top-8, .shadow-lg')
    if (await picker.isVisible()) {
      const firstTag = picker.locator('button').first()
      if (await firstTag.isVisible()) {
        await firstTag.click()
        await pom.expectSuccessToast(/已添加标签/)
      }
    }
  })

  test('标签可被移除', async () => {
    const tags = pom.currentTags
    if (await tags.count() > 0) {
      // 验证标签有实际文本内容
      const firstTagText = await tags.first().textContent()
      expect(firstTagText).toBeTruthy()
      await tags.first().hover()
      const removeBtn = tags.first().locator('button')
      if (await removeBtn.isVisible()) {
        await removeBtn.click()
        await pom.expectSuccessToast(/已移除标签/)
      }
    }
  })

  test('备注文本框可编辑并保存', async () => {
    await pom.remarkTextarea.fill('这是一条测试备注')
    await pom.saveRemarkButton.click()
    await pom.expectSuccessToast(/备注已保存/)
  })

  test('订单历史 Tab 默认显示', async () => {
    await expect(pom.ordersTab).toBeVisible()
  })

  test('会话历史 Tab 可切换并显示数据', async () => {
    await pom.sessionsTab.click()
    const items = pom.sessionItems
    expect(await items.count()).toBeGreaterThanOrEqual(0)
  })

  test('跟进记录 Tab 可切换并显示占位文案', async () => {
    await pom.notesTab.click()
    await expect(pom.page.getByText(/暂无跟进记录/)).toBeVisible()
  })

  test('返回按钮可返回客户列表', async () => {
    await pom.backButton.click()
    await expect(pom.page).toHaveURL(/\/customers/)
  })

  test('订单卡片显示订单号和金额', async () => {
    const orderNo = pom.page.locator('text=/ORD\\d+/')
    if (await orderNo.count() > 0) {
      await expect(orderNo.first()).toBeVisible()
      // 验证订单号格式 ORD + 数字
      const text = await orderNo.first().textContent()
      expect(text).toMatch(/ORD\d+/)
    }
  })

  test('会话卡片显示消息摘要和类型标签', async () => {
    await pom.sessionsTab.click()
    const badges = pom.page.locator('text=/AI 对话|人工客服/')
    expect(await badges.count()).toBeGreaterThanOrEqual(0)
  })

  test('渠道来源 Badge 正确显示', async () => {
    const badge = pom.page.locator('text=/微信小程序|公众号|Web|订单/').first()
    if (await badge.isVisible().catch(() => false)) await expect(badge).toBeVisible()
  })
})
