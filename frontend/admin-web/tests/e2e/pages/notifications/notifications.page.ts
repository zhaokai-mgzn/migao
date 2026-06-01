import { type Page, type Locator } from '@playwright/test'
import { BasePage } from '../base.page'

export class NotificationsPage extends BasePage {
  readonly statusTabs: Locator
  readonly notificationList: Locator
  readonly markAllReadBtn: Locator
  readonly pagination: Locator

  constructor(page: Page) {
    super(page)
    this.statusTabs = page.locator('.bg-white.border.border-gray-200.rounded-t-lg')
    this.notificationList = page.locator('.divide-y.divide-gray-100')
    this.markAllReadBtn = page.getByRole('button', { name: /全部标记已读/ })
    this.pagination = page.locator('.bg-white.rounded-b-lg').last()
  }

  async goto(): Promise<void> {
    await this.page.goto('/notifications')
  }

  tabByName(name: string): Locator {
    return this.statusTabs.getByRole('button', { name })
  }

  markReadBtn(n: number): Locator {
    return this.notificationList.locator('> div').nth(n).getByRole('button', { name: /标记已读/ })
  }

  deleteBtn(n: number): Locator {
    return this.notificationList.locator('> div').nth(n).getByRole('button', { name: /删除/ })
  }
}
