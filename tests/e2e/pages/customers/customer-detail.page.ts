import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from '../base.page'

/**
 * CustomerDetailPage POM — src/app/(dashboard)/customers/[id]/CustomerDetail.tsx
 *
 * Left: info card (avatar, name, phone, channel, VIP), tag picker, remark.
 * Right: tabbed content (orders / sessions / notes).
 */
export class CustomerDetailPage extends BasePage {
  // ─── Header ──────────────────────────────────────────────────
  readonly backButton: Locator

  // ─── Info Card (left) ───────────────────────────────────────
  readonly infoCard: Locator
  readonly customerName: Locator
  readonly customerNickname: Locator
  readonly vipStars: Locator
  readonly phoneValue: Locator
  readonly channelBadge: Locator

  // ─── Tag Section (left) ─────────────────────────────────────
  readonly tagSection: Locator
  readonly addTagButton: Locator
  readonly tagPicker: Locator
  readonly tagPickerItems: Locator
  readonly currentTags: Locator

  // ─── Remark Section (left) ──────────────────────────────────
  readonly remarkSection: Locator
  readonly remarkTextarea: Locator
  readonly saveRemarkButton: Locator

  // ─── Tab Bar (right) ────────────────────────────────────────
  readonly ordersTab: Locator
  readonly sessionsTab: Locator
  readonly notesTab: Locator

  // ─── Orders Tab ─────────────────────────────────────────────
  readonly ordersList: Locator
  readonly orderItems: Locator

  // ─── Sessions Tab ───────────────────────────────────────────
  readonly sessionsList: Locator
  readonly sessionItems: Locator

  // ─── Notes Tab ──────────────────────────────────────────────
  readonly notesContent: Locator

  constructor(page: Page) {
    super(page)

    // Header
    this.backButton = page.getByRole('button', { name: /返回客户列表/ }).or(page.locator('button').filter({ hasText: /返回/ }).first())

    // Info card — scope to main to avoid hidden dropdowns with same classes
    this.infoCard = page.locator('main .bg-white.border').first()
    this.customerName = this.infoCard.locator('h2')
    this.customerNickname = this.infoCard.locator('p.text-sm.text-gray-500')
    this.vipStars = this.infoCard.locator('svg.fill-amber-400')
    this.phoneValue = this.infoCard.locator('span').filter({ hasText: /^1\d{10}$/ }).first()
    this.channelBadge = this.infoCard.locator('span').filter({ hasText: /微信小程序|公众号|Web|订单/ }).first()

    // Tags
    this.tagSection = page.locator('main .bg-white.border').filter({ hasText: /标签/ }).first()
    this.addTagButton = this.tagSection.locator('button').filter({ has: page.locator('svg') }).first()
    this.tagPicker = this.tagSection.locator('.absolute').first()
    this.tagPickerItems = this.tagPicker.locator('button')
    this.currentTags = this.tagSection.locator('span.inline-flex')

    // Remark
    this.remarkSection = page.locator('main .bg-white.border').filter({ hasText: /备注/ }).first()
    this.remarkTextarea = this.remarkSection.locator('textarea')
    this.saveRemarkButton = this.remarkSection.getByRole('button', { name: /保存/ })

    // Tabs
    this.ordersTab = page.getByRole('button', { name: /订单历史/ })
    this.sessionsTab = page.getByRole('button', { name: /会话历史/ })
    this.notesTab = page.getByRole('button', { name: /跟进记录/ })

    // Tab content
    this.ordersList = page.locator('.space-y-3').first()
    this.orderItems = this.ordersList.locator('.flex.items-center')
    this.sessionsList = page.locator('.space-y-3').first()
    this.sessionItems = this.sessionsList.locator('.flex.items-start')
    this.notesContent = page.getByText(/暂无跟进记录/)
  }

  // ─── Navigation ──────────────────────────────────────────────

  async goto(customerId: string): Promise<void> {
    await this.page.goto(`/customers/${customerId}`)
    await this.waitForLoadingComplete()
  }

  // ─── Actions ─────────────────────────────────────────────────

  async goBack(): Promise<void> {
    await this.backButton.click()
  }

  async openTagPicker(): Promise<void> {
    await this.addTagButton.click()
  }

  async addTag(tagName: string): Promise<void> {
    await this.openTagPicker()
    await this.tagPickerItems.filter({ hasText: tagName }).click()
  }

  async removeTag(tagName: string): Promise<void> {
    const tag = this.currentTags.filter({ hasText: tagName })
    // Hover to show the X button, then click it
    await tag.hover()
    await tag.locator('button').click()
  }

  async fillRemark(text: string): Promise<void> {
    await this.remarkTextarea.fill(text)
  }

  async saveRemark(): Promise<void> {
    await this.saveRemarkButton.click()
  }

  async switchTab(tab: 'orders' | 'sessions' | 'notes'): Promise<void> {
    const map = { orders: this.ordersTab, sessions: this.sessionsTab, notes: this.notesTab }
    await map[tab].click()
  }

  // ─── Assertions ──────────────────────────────────────────────

  async expectCustomerName(name: string): Promise<void> {
    await expect(this.customerName).toContainText(name)
  }

  async expectVipLevel(level: number): Promise<void> {
    if (level === 0) {
      await expect(this.infoCard).toContainText(/普通/)
    } else {
      await expect(this.vipStars).toHaveCount(level)
    }
  }

  async expectTagVisible(tagName: string): Promise<void> {
    await expect(this.currentTags.filter({ hasText: tagName })).toBeVisible()
  }

  async expectOrdersTabActive(): Promise<void> {
    await expect(this.ordersTab).toHaveClass(/border-primary-600/)
  }

  async expectOrderVisible(orderNo: string): Promise<void> {
    await expect(this.orderItems.filter({ hasText: orderNo })).toBeVisible()
  }

  async expectSessionVisible(message: string): Promise<void> {
    await expect(this.sessionItems.filter({ hasText: message })).toBeVisible()
  }

  async expectOnDetailPage(customerId?: string): Promise<void> {
    const pattern = customerId ? new RegExp(`/customers/${customerId}`) : /\/customers\/[^/]+$/
    await expect(this.page).toHaveURL(pattern)
  }
}
