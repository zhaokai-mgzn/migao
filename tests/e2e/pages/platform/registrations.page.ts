import { type Page, type Locator } from '@playwright/test'
import { BasePage } from '../base.page'

export class RegistrationsPage extends BasePage {
  readonly statusTabs: Locator
  readonly table: Locator
  readonly approveModal: Locator
  readonly rejectModal: Locator
  readonly detailModal: Locator

  constructor(page: Page) {
    super(page)
    this.statusTabs = page.locator('.bg-white.border.border-gray-200.rounded-t-lg')
    this.table = page.locator('table')
    this.approveModal = page.locator('[role="dialog"]').filter({ hasText: '确认审批通过' })
    this.rejectModal = page.locator('[role="dialog"]').filter({ hasText: '驳回申请' })
    this.detailModal = page.locator('[role="dialog"]').filter({ hasText: '申请详情' })
  }

  async goto(): Promise<void> {
    await this.page.goto('/registrations')
  }

  tabByName(name: string): Locator {
    return this.statusTabs.getByRole('button', { name })
  }

  approveBtn(n: number): Locator {
    return this.page.locator('tbody tr').nth(n).getByRole('button', { name: /审批通过/ })
  }

  rejectBtn(n: number): Locator {
    return this.page.locator('tbody tr').nth(n).getByRole('button', { name: /驳回/ })
  }

  detailBtn(n: number): Locator {
    return this.page.locator('tbody tr').nth(n).getByRole('button', { name: /查看详情/ })
  }

  get rejectReasonInput() { return this.rejectModal.locator('textarea[placeholder="请填写驳回原因..."]') }
}
