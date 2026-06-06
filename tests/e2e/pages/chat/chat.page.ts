import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from '../base.page'

export class ChatPage extends BasePage {
  readonly sessionList: Locator
  readonly createSessionBtn: Locator
  readonly sessionSearchInput: Locator
  readonly messageList: Locator
  readonly messageInput: Locator
  readonly sendBtn: Locator
  readonly stopBtn: Locator
  readonly imageUploadBtn: Locator
  readonly customerPanel: Locator
  readonly quickActions: Locator

  constructor(page: Page) {
    super(page)
    this.sessionList = page.locator('.w-60.bg-white.border-r')
    this.createSessionBtn = page.getByRole('button', { name: /新建对话/ })
    this.sessionSearchInput = page.locator('input[placeholder="搜索会话..."]')
    this.messageList = page.locator('.flex-1.overflow-y-auto').first()
    this.messageInput = page.locator('textarea[placeholder*="输入消息"]')
    this.sendBtn = page.locator('button').filter({ has: page.locator('svg.lucide-send') }).last()
    this.stopBtn = page.locator('button').filter({ has: page.locator('svg.lucide-stop-circle') })
    this.imageUploadBtn = page.locator('button').filter({ has: page.locator('svg.lucide-image-plus') })
    this.customerPanel = page.locator('.w-\\[280px\\]')
    this.quickActions = page.locator('text=快捷操作').first()
  }

  async goto(): Promise<void> {
    await this.page.goto('/chat')
  }

  /**
   * 等待 zustand persist 从 localStorage 中完成 hydration。
   * 否则 getToken() 返回空字符串，导致 createSession API 401。
   */
  async waitForAuth(): Promise<void> {
    await this.page.waitForFunction(
      () => {
        const raw = localStorage.getItem('auth-storage')
        if (!raw) return false
        try {
          return !!(JSON.parse(raw)?.state?.accessToken)
        } catch {
          return false
        }
      },
      { timeout: 10_000 },
    )
  }

  sessionItem(n: number): Locator {
    return this.sessionList.locator('.mx-1\\.5').nth(n)
  }

  closeSessionBtn(n: number): Locator {
    return this.sessionItem(n).locator('button').filter({ has: this.page.locator('svg.lucide-more-horizontal') })
  }

  deleteSessionBtn(n: number): Locator {
    return this.page.locator('button').filter({ hasText: /结束会话/ }).first()
  }

  async fillMessage(text: string): Promise<void> {
    // Playwright fill() 在现代 React 中已正确触发 onChange
    await this.messageInput.click()
    await this.messageInput.fill(text)
  }

  async waitForStreamEnd(): Promise<void> {
    // Wait for stop button to disappear (streaming ended)
    try {
      await this.stopBtn.waitFor({ state: 'hidden', timeout: 30_000 })
    } catch {
      // Not streaming
    }
  }
}
