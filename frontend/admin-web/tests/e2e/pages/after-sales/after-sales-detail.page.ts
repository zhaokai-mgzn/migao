import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from '../base.page'

/**
 * AfterSalesDetailPage POM — src/app/(dashboard)/after-sales/[id]/AfterSalesDetail.tsx
 *
 * Ticket info, description, timeline, internal notes.
 * Right sidebar: related order link, customer info, ticket details.
 * Status action buttons (accept, reject, complete, close) + confirmation modal.
 */
export class AfterSalesDetailPage extends BasePage {
  // ─── Header ──────────────────────────────────────────────────
  readonly backButton: Locator
  readonly pageTitle: Locator
  readonly statusBadge: Locator
  readonly priorityBadge: Locator
  readonly ticketNoLabel: Locator
  readonly actionButtons: Locator

  // ─── Ticket Info Card ───────────────────────────────────────
  readonly ticketInfoCard: Locator
  readonly ticketType: Locator
  readonly createdAt: Locator
  readonly refundAmount: Locator

  // ─── Description Card ───────────────────────────────────────
  readonly descriptionCard: Locator
  readonly descriptionText: Locator

  // ─── Timeline Card ──────────────────────────────────────────
  readonly timelineCard: Locator
  readonly timelineItems: Locator

  // ─── Internal Notes ─────────────────────────────────────────
  readonly internalNotesCard: Locator
  readonly internalNotesText: Locator

  // ─── Right Sidebar ─────────────────────────────────────────
  readonly relatedOrderLink: Locator
  readonly customerInfoCard: Locator

  // ─── Status Confirmation Modal ─────────────────────────────
  readonly statusModal: Locator
  readonly statusModalRemark: Locator
  readonly statusModalConfirm: Locator
  readonly statusModalCancel: Locator

  constructor(page: Page) {
    super(page)

    // Header
    this.backButton = page.locator('button').filter({ has: page.locator('svg') }).first()
    this.pageTitle = page.locator('h1').filter({ hasText: /工单详情/ })
    this.statusBadge = page.locator('span').filter({ hasText: /待处理|处理中|已完成|已拒绝|已关闭/ }).first()
    this.priorityBadge = page.locator('span').filter({ hasText: /普通|紧急|严重/ }).first()
    this.ticketNoLabel = page.locator('p.font-mono').filter({ hasText: /工单号/ })
    this.actionButtons = page.locator('.flex.items-center.gap-2').last()

    // Ticket info
    this.ticketInfoCard = page.locator('h2').filter({ hasText: /工单信息/ }).locator('xpath=..')
    this.ticketType = this.ticketInfoCard.locator('p.text-sm.font-medium').first()
    this.createdAt = this.ticketInfoCard.locator('p.text-sm.font-medium').nth(1)
    this.refundAmount = this.ticketInfoCard.locator('p.text-red-600')

    // Description
    this.descriptionCard = page.locator('h2').filter({ hasText: /售后原因/ }).locator('xpath=..')
    this.descriptionText = this.descriptionCard.locator('.bg-gray-50, p.whitespace-pre-wrap')

    // Timeline
    this.timelineCard = page.locator('h2').filter({ hasText: /处理时间线/ }).locator('xpath=..')
    this.timelineItems = this.timelineCard.locator('.flex.items-start.gap-4')

    // Internal notes
    this.internalNotesCard = page.locator('h2').filter({ hasText: /内部备注/ }).locator('xpath=..')
    this.internalNotesText = this.internalNotesCard.locator('.bg-amber-50')

    // Right sidebar
    this.relatedOrderLink = page.locator('h2').filter({ hasText: /关联订单/ }).locator('xpath=..').locator('button, a')
    this.customerInfoCard = page.locator('h2').filter({ hasText: /客户信息/ }).locator('xpath=..')

    // Status modal
    this.statusModal = page.locator('[role="dialog"]').filter({ hasText: /确认操作/ })
    this.statusModalRemark = this.statusModal.locator('textarea')
    this.statusModalConfirm = this.statusModal.getByRole('button', { name: /确认/ })
    this.statusModalCancel = this.statusModal.getByRole('button', { name: /取消/ })
  }

  // ─── Navigation ──────────────────────────────────────────────

  async goto(ticketId: string): Promise<void> {
    await this.page.goto(`/after-sales/${ticketId}`)
    await this.waitForLoadingComplete()
  }

  // ─── Actions ─────────────────────────────────────────────────

  async goBack(): Promise<void> {
    await this.backButton.click()
  }

  async clickAction(label: string): Promise<void> {
    await this.actionButtons.getByRole('button', { name: label }).click()
  }

  async confirmStatusAction(remark?: string): Promise<void> {
    if (remark) await this.statusModalRemark.fill(remark)
    await this.statusModalConfirm.click()
  }

  async cancelStatusAction(): Promise<void> {
    await this.statusModalCancel.click()
  }

  async clickRelatedOrder(): Promise<void> {
    await this.relatedOrderLink.click()
  }

  // ─── Assertions ──────────────────────────────────────────────

  async expectStatus(status: string): Promise<void> {
    await expect(this.statusBadge).toContainText(status)
  }

  async expectTicketNo(ticketNo: string): Promise<void> {
    await expect(this.ticketNoLabel).toContainText(ticketNo)
  }

  async expectActionButtonVisible(label: string): Promise<void> {
    await expect(this.actionButtons.getByRole('button', { name: label })).toBeVisible()
  }

  async expectTimelineEntry(status: string): Promise<void> {
    await expect(this.timelineItems.filter({ hasText: status })).toBeVisible()
  }

  async expectDescription(text: string | RegExp): Promise<void> {
    await expect(this.descriptionText).toContainText(text)
  }

  async expectStatusModalVisible(): Promise<void> {
    await expect(this.statusModal).toBeVisible()
  }

  async expectOnDetailPage(ticketId?: string): Promise<void> {
    const pattern = ticketId ? new RegExp(`/after-sales/${ticketId}`) : /\/after-sales\/[^/]+$/
    await expect(this.page).toHaveURL(pattern)
  }
}
