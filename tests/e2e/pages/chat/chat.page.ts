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
    // ── 定位 send / stop 按钮 ──────────────────────────────────────────
    // 注意：FloatingAssistant (全局浮动 widget) 也包含一个 lucide-send 按钮，
    // 位于 layout.tsx 中、DOM 顺序在主聊天区之后。
    // 旧写法 .last() 会错误选中 widget 的按钮 (始终 disabled)。
    // 修复：将搜索范围限定到主聊天 MessageInput 的 wrapper div，
    // 其 className 含 rounded-2xl (widget 面板不使用此 class)。
    const messageInputWrapper = page.locator(
      '.relative.flex.items-end.gap-2.bg-gray-50.rounded-2xl',
    )
    this.sendBtn = messageInputWrapper
      .locator('button')
      .filter({ has: page.locator('svg.lucide-send') })
      .first()
    this.stopBtn = messageInputWrapper
      .locator('button')
      .filter({ has: page.locator('svg.lucide-stop-circle') })
      .first()
    this.imageUploadBtn = page.locator('button').filter({ has: page.locator('svg.lucide-image-plus') })
    this.customerPanel = page.locator('.w-\\[280px\\]')
    this.quickActions = page.locator('text=快捷操作').first()
  }

  async goto(): Promise<void> {
    await this.page.goto('/chat')
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

  async waitForStreamEnd(): Promise<void> {
    // Wait for stop button to disappear (streaming ended)
    try {
      await this.stopBtn.waitFor({ state: 'hidden', timeout: 30_000 })
    } catch {
      // Not streaming
    }
  }
}
