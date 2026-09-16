// case_ids: UI-041
// 开关几何完整性（issue #3924）：设置页开关按钮是 flex 行子项但缺 shrink-0，
// 说明文字过长时 44px 轨道被 flex 压缩，绝对定位圆钮不随缩 → 溢出轨道右缘。
// 断言效果层几何（boundingBox），非类名快照：轨道宽度 = 44px、圆钮不得超出轨道边界。
import { test, expect } from '../../fixtures'

test.describe('设置页开关几何完整性（issue #3924）', () => {
  test.beforeEach(async ({ page }) => {
    // Mock 设置相关 API（无需后端）：简报开关固定为开启态（复现截图中溢出的状态）
    await page.route('**/api/admin/settings', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: { companyName: '词元通达', logo: '', notificationEnabled: true } }),
      })
    })
    await page.route('**/api/admin/tenant/ai-config', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: { botName: '小布', greetingTemplate: '' } }),
      })
    })
    await page.route('**/api/admin/briefing/config', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: { enabled: true, generateTime: '07:30' } }),
      })
    })
    await page.goto('/settings')
  })

  // 几何断言：圆钮必须完整落在轨道内（允许 0.5px 渲染误差）
  async function expectToggleInsideTrack(page: import('@playwright/test').Page, ariaLabel: string) {
    const toggle = page.getByRole('button', { name: ariaLabel })
    await expect(toggle).toBeVisible()
    const track = await toggle.boundingBox()
    expect(track, '开关轨道应有非零包围盒').not.toBeNull()
    const knob = await toggle.locator('span').first().boundingBox()
    expect(knob, '开关圆钮应有非零包围盒').not.toBeNull()
    // 轨道保持 w-11 = 44px（不被 flex 压缩）
    expect(track!.width, '轨道宽度应保持 44px').toBeGreaterThanOrEqual(43.5)
    // 圆钮完整落在轨道内（左右上下都不溢出）
    expect(knob!.x, '圆钮左缘不得超出轨道左缘').toBeGreaterThanOrEqual(track!.x - 0.5)
    expect(knob!.x + knob!.width, '圆钮右缘不得溢出轨道右缘（issue #3924 症状）').toBeLessThanOrEqual(
      track!.x + track!.width + 0.5,
    )
    expect(knob!.y, '圆钮上缘不得超出轨道上缘').toBeGreaterThanOrEqual(track!.y - 0.5)
    expect(knob!.y + knob!.height, '圆钮下缘不得溢出轨道下缘').toBeLessThanOrEqual(track!.y + track!.height + 0.5)
  }

  test('基本设置：简报开关开启态圆钮不溢出轨道（issue #3924）', async ({ page }) => {
    await expectToggleInsideTrack(page, '启用智能每日经营简报开关')
  })

  test('通知设置：系统通知开关开启态圆钮不溢出轨道（issue #3924）', async ({ page }) => {
    await page.getByRole('button', { name: /通知设置/ }).click()
    await expectToggleInsideTrack(page, '启用系统通知开关')
  })

  test('点击简报开关 → PUT 保存成功且状态切换（组件交互链路不回归）', async ({ page }) => {
    const putBodies: string[] = []
    await page.route('**/api/admin/briefing/config', async (route) => {
      if (route.request().method() === 'PUT') {
        putBodies.push(route.request().postData() ?? '')
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, data: { enabled: false, generateTime: '07:30' } }),
        })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: { enabled: true, generateTime: '07:30' } }),
      })
    })
    const toggle = page.getByRole('button', { name: '启用智能每日经营简报开关' })
    await toggle.click()
    await expect(page.getByText('已关闭智能每日经营简报')).toBeVisible()
    expect(putBodies.length, '点击应触发一次 PUT 保存').toBe(1)
    expect(JSON.parse(putBodies[0]).enabled, 'PUT 应携带关闭后的 enabled=false').toBe(false)
  })
})
