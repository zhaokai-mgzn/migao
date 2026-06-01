/**
 * BasePage — Page Object Model for the shared dashboard layout.
 *
 * Selectors derived from:
 *   - src/app/(dashboard)/layout.tsx   (sidebar + header + main)
 *   - src/components/layout/Sidebar.tsx (navigation links)
 *   - src/components/layout/Header.tsx  (breadcrumbs, user menu)
 *   - src/components/ui/Modal.tsx       (modal dialog)
 *   - src/components/ui/Table.tsx       (data table)
 *   - src/components/ui/Pagination.tsx  (page controls)
 *   - src/components/ui/Loading.tsx     (loading spinner)
 *   - sonner toast library              ([data-sonner-toast])
 *
 * Dashboard layout structure:
 *   <div className="min-h-screen bg-gray-50">
 *     <aside>              ← Sidebar (fixed, bg-slate-900)
 *     <div className="ml-60|ml-16">
 *       <header>           ← Header (h-14, sticky)
 *       <main>             ← Main content (flex-1 p-6)
 *         <div>            ← White card wrapper (bg-white rounded-lg shadow-card)
 *           {children}     ← Page content
 *         </div>
 *       </main>
 *     </div>
 *   </div>
 *
 * This class is both:
 *   1. Extended by page-specific POMs (DashboardPage, ProductListPage, etc.)
 *   2. Instantiated directly in tests for generic layout interactions
 */
import { type Page, type Locator, expect } from '@playwright/test'
import {
  waitForLoadingComplete as _waitForLoadingComplete,
  waitForPageReady as _waitForPageReady,
  waitForToast as _waitForToast,
} from '../helpers/wait.helper'

/** Sidebar menu path → display name mapping (from Sidebar.tsx menuGroups) */
const SIDEBAR_MENU: Record<string, string> = {
  '/dashboard': '数据看板',
  '/products': '商品管理',
  '/processing': '加工项管理',
  '/orders': '订单管理',
  '/after-sales': '售后管理',
  '/customers': '客户管理',
  '/agent-workspace': '客服工作台',
  '/agent-workspace/sessions': '会话监控',
  '/agent-workspace/quick-replies': '快捷回复',
  '/employees': '客服团队',
  '/roles': '角色权限',
  '/notifications': '通知中心',
  '/settings': '系统设置',
}

export class BasePage {
  readonly page: Page

  // ════════════════════════════════════════
  // Layout Locators
  // ════════════════════════════════════════

  /** Sidebar: <aside> fixed left-0, bg-slate-900 */
  readonly sidebar: Locator

  /** Header: <header> h-14, sticky top-0, border-b */
  readonly header: Locator

  /** Main content area: <main> flex-1 p-6 */
  readonly mainContent: Locator

  constructor(page: Page) {
    this.page = page
    this.sidebar = page.locator('aside').first()
    this.header = page.locator('header').first()
    this.mainContent = page.locator('main').first()
  }

  // ════════════════════════════════════════
  // Navigation
  // ════════════════════════════════════════

  /**
   * Navigate to a path relative to baseURL.
   * Subclasses override this with page-specific paths and wait logic.
   */
  async goto(path?: string): Promise<void> {
    if (path) {
      await this.page.goto(path)
    }
  }

  /** Wait for the page to finish loading (networkidle). */
  async waitForLoad(): Promise<void> {
    await this.page.waitForLoadState('networkidle')
  }

  /** Return current URL pathname (e.g. "/dashboard"). */
  async pathname(): Promise<string> {
    return new URL(this.page.url()).pathname
  }

  /**
   * Click a sidebar navigation link by route path.
   *
   * Sidebar structure (Sidebar.tsx):
   *   <Link href={item.path} className="... flex items-center gap-3 ...">
   *     <Icon />
   *     <span>{item.name}</span>
   *   </Link>
   *
   * Active item has class `bg-primary-600 text-white`.
   */
  async navigateToSidebar(path: string): Promise<void> {
    const menuName = SIDEBAR_MENU[path]
    if (!menuName) {
      throw new Error(
        `Unknown sidebar path: ${path}. Known: ${Object.keys(SIDEBAR_MENU).join(', ')}`,
      )
    }

    // Sidebar links are rendered as <a> tags by Next.js <Link>
    const navLink = this.sidebar.getByRole('link', { name: menuName })
    await navLink.click()

    // Wait for navigation to complete
    await this.page.waitForLoadState('networkidle').catch(() => {})
    await this.waitForLoadingComplete()
  }

  /**
   * Click a sidebar navigation link by its display name text.
   */
  async navigateToSidebarByName(name: string): Promise<void> {
    const navLink = this.sidebar.getByRole('link', { name })
    await navLink.click()
    await this.page.waitForLoadState('networkidle').catch(() => {})
    await this.waitForLoadingComplete()
  }

  /**
   * Get the currently active sidebar menu item text.
   * Active links have `bg-primary-600 text-white` classes.
   */
  async getActiveMenuItem(): Promise<string | null> {
    const activeLink = this.sidebar.locator('a.bg-primary-600')
    const count = await activeLink.count()
    if (count === 0) return null
    return activeLink.textContent()
  }

  /**
   * Toggle the sidebar collapsed/expanded state.
   * Collapse button is the last button inside <aside>.
   */
  async toggleSidebar(): Promise<void> {
    const toggleBtn = this.sidebar.locator('button').last()
    await toggleBtn.click()
    // Wait for the transition animation (duration-300 = 300ms)
    await this.page.waitForTimeout(350)
  }

  /**
   * Check if the sidebar is currently collapsed.
   * Collapsed: w-16 (64px). Expanded: w-60 (240px).
   */
  async isSidebarCollapsed(): Promise<boolean> {
    const width = await this.sidebar.evaluate((el) => el.getBoundingClientRect().width)
    return width < 100
  }

  // ════════════════════════════════════════
  // Toast Notifications (sonner)
  // ════════════════════════════════════════

  /** Locate a sonner toast by its text. */
  toast(text?: string | RegExp): Locator {
    const toasts = this.page.locator('[data-sonner-toast]')
    return text ? toasts.filter({ hasText: text }) : toasts.first()
  }

  /** Assert that a success toast appears. */
  async expectSuccessToast(text?: string | RegExp): Promise<void> {
    const t = text
      ? this.toast(text)
      : this.page.locator('[data-sonner-toast][data-type="success"]')
    await expect(t).toBeVisible({ timeout: 10_000 })
  }

  /** Assert that an error toast appears. */
  async expectErrorToast(text?: string | RegExp): Promise<void> {
    const t = text
      ? this.toast(text)
      : this.page.locator('[data-sonner-toast][data-type="error"]')
    await expect(t).toBeVisible({ timeout: 10_000 })
  }

  /**
   * Expect a success toast — convenience alias using wait helper.
   * Waits for any toast to appear with optional text match.
   */
  async expectToastSuccess(text?: string): Promise<void> {
    await _waitForToast(this.page, text)
  }

  /**
   * Expect an error toast — convenience alias using wait helper.
   */
  async expectToastError(text?: string): Promise<void> {
    await _waitForToast(this.page, text)
  }

  /**
   * Get the text content of the currently visible toast.
   */
  async getToastText(): Promise<string | null> {
    const toast = this.page.locator('[data-sonner-toast]').first()
    if ((await toast.count()) === 0) return null
    return toast.textContent()
  }

  /**
   * Wait for all toasts to auto-dismiss (sonner ~4s default).
   */
  async waitForToastDismiss(): Promise<void> {
    const toast = this.page.locator('[data-sonner-toast]')
    await toast.waitFor({ state: 'hidden', timeout: 10_000 }).catch(() => {})
  }

  // ════════════════════════════════════════
  // Loading
  // ════════════════════════════════════════

  /**
   * Wait until no spinner element is visible on screen.
   * Selectors: `.animate-spin` (Loading.tsx, Table.tsx, Button.tsx)
   */
  async waitForLoadingComplete(): Promise<void> {
    await _waitForLoadingComplete(this.page)
  }

  /**
   * Wait until the page skeleton / animate-pulse loaders disappear.
   */
  async waitForSkeletonComplete(): Promise<void> {
    const skeleton = this.page.locator('.animate-pulse')
    try {
      await skeleton.first().waitFor({ state: 'hidden', timeout: 15_000 })
    } catch {
      // No skeleton was present — that's fine
    }
  }

  /**
   * Wait for the page to be fully ready:
   *   1. Network is idle (no pending requests)
   *   2. No loading spinners are visible
   */
  async waitForPageReady(): Promise<void> {
    await _waitForPageReady(this.page)
  }

  // ════════════════════════════════════════
  // Modal (src/components/ui/Modal.tsx)
  // ════════════════════════════════════════

  /**
   * Get the currently open modal dialog.
   * Modal renders: <div className="fixed inset-0 z-50">
   *   <div className="bg-black/45">       ← backdrop
   *   <div className="bg-white rounded-lg shadow-xl">  ← dialog box
   */
  get modal(): Locator {
    return this.page
      .locator('.fixed.inset-0.z-50 .bg-white.rounded-lg.shadow-xl')
      .first()
  }

  /** Alias for backward compatibility — locate modal by role="dialog" */
  get openModal(): Locator {
    return this.page.locator('[role="dialog"]').last()
  }

  /**
   * Modal title (h3 inside the modal header).
   * Defined as a method to avoid TS2610 conflicts with subclasses
   * that assign `readonly modalTitle: Locator` in their constructor.
   */
  getModalTitle(): Locator {
    return this.modal.locator('h3')
  }

  /** Modal backdrop (clicking closes if maskClosable=true) */
  get modalBackdrop(): Locator {
    return this.page.locator('.fixed.inset-0.z-50 > div').first()
  }

  /** Wait until a modal is visible. */
  async waitForModal(title?: string): Promise<Locator> {
    const modal = title
      ? this.page.locator('[role="dialog"]').filter({ hasText: title })
      : this.openModal
    await expect(modal).toBeVisible()
    return modal
  }

  /**
   * Expect the modal to be visible, optionally matching a title.
   */
  async expectModalVisible(title?: string): Promise<void> {
    await expect(this.modal).toBeVisible()
    if (title) {
      await expect(this.getModalTitle()).toHaveText(title)
    }
  }

  /** Expect the modal to be hidden. */
  async expectModalHidden(): Promise<void> {
    await expect(this.modal).toBeHidden()
  }

  /**
   * Close the modal by clicking the X button.
   * The close button is inside the modal header:
   *   <div className="flex items-center justify-between px-6 py-4 border-b">
   *     <h3>title</h3>
   *     <button> <X /> </button>
   *   </div>
   *
   * Named `closeDialog` to avoid TS2416 conflict with subclasses that
   * define `readonly closeModal: Locator` (a Locator, not a method).
   */
  async closeDialog(): Promise<void> {
    const closeBtn = this.modal
      .locator('.flex.items-center.justify-between button')
      .first()
    await closeBtn.click()
    await expect(this.modal).toBeHidden({ timeout: 3_000 }).catch(() => {})
  }

  /**
   * Close the currently open modal by pressing Escape.
   * Fallback for when the X button is not accessible.
   */
  async closeModalByMask(): Promise<void> {
    await this.page.keyboard.press('Escape')
  }

  /**
   * Click the "取消" (Cancel) button in the modal footer.
   * Footer: <Button variant="secondary">取消</Button>
   */
  async cancelModal(): Promise<void> {
    const cancelBtn = this.modal.getByRole('button', { name: '取消' })
    await cancelBtn.click()
    await expect(this.modal).toBeHidden({ timeout: 3_000 }).catch(() => {})
  }

  /**
   * Click the "确定" (Confirm/OK) button in the modal footer.
   * Footer: <Button>确定</Button>
   *
   * Named `confirmDialog` to avoid TS2416 conflict with subclasses that
   * define `readonly confirmModal: Locator` (a Locator, not a method).
   */
  async confirmDialog(): Promise<void> {
    const confirmBtn = this.modal.getByRole('button', { name: '确定' })
    await confirmBtn.click()
  }

  /** Modal footer container */
  get modalFooter(): Locator {
    return this.modal
      .locator('.flex.items-center.justify-end.gap-3')
      .last()
  }

  // ════════════════════════════════════════
  // Table (src/components/ui/Table.tsx)
  // ════════════════════════════════════════

  /**
   * The data table element.
   * Renders: <table className="w-full border-collapse">
   *
   * Defined as a method (not getter) to avoid TS2610 conflicts with
   * subclasses that assign `readonly table: Locator` in their constructor.
   */
  getTable(): Locator {
    return this.page.locator('table').first()
  }

  /**
   * All data rows in the table body (excludes header row).
   * Renders: <tbody> > <tr>
   *
   * Defined as a method (not getter) for same reason as getTable().
   */
  getTableRows(): Locator {
    return this.page.locator('table tbody tr')
  }

  /**
   * Get a specific cell by row index and column index.
   * @param rowIndex - 0-based row index
   * @param colIndex - 0-based column index
   */
  tableCell(rowIndex: number, colIndex: number): Locator {
    return this.getTableRows().nth(rowIndex).locator('td').nth(colIndex)
  }

  /**
   * Get the text of a specific cell.
   */
  async getCellText(rowIndex: number, colIndex: number): Promise<string> {
    return (await this.tableCell(rowIndex, colIndex).textContent()) || ''
  }

  /**
   * Get the total number of data rows.
   */
  async getRowCount(): Promise<number> {
    return this.getTableRows().count()
  }

  /**
   * Select all rows via the header checkbox (if present).
   * Table.tsx doesn't have built-in select, but ProductTable does:
   *   <thead> > <input type="checkbox">
   */
  async selectAllRows(): Promise<void> {
    const checkbox = this.page.locator('thead input[type="checkbox"]')
    if ((await checkbox.count()) > 0) {
      await checkbox.click()
    }
  }

  /**
   * Check if the table is in loading state.
   * Loading: <td colSpan>...<div className="animate-spin">...加载中...</div></td>
   */
  async isTableLoading(): Promise<boolean> {
    return this.page.getByText('加载中...').isVisible()
  }

  /**
   * Check if the table shows the empty state.
   * Empty: <td colSpan>暂无数据</td>
   */
  async isTableEmpty(): Promise<boolean> {
    return this.page.getByText('暂无数据').isVisible()
  }

  /**
   * Wait for table data to load (loading spinner disappears, rows visible).
   */
  async waitForTableData(timeout = 10_000): Promise<void> {
    await this.waitForLoadingComplete()
    const rows = this.getTableRows()
    await expect(rows.first()).toBeVisible({ timeout: Math.min(timeout, 5_000) }).catch(
      () => {},
    )
  }

  /** Click on a table row by index. */
  async clickRow(rowIndex: number): Promise<void> {
    await this.getTableRows().nth(rowIndex).click()
  }

  /** Locate a table row by text content. */
  tableRow(text: string | RegExp): Locator {
    return this.page.locator('tbody tr').filter({ hasText: text })
  }

  // ════════════════════════════════════════
  // URL Assertions
  // ════════════════════════════════════════

  /** Assert the page has navigated to a URL matching a pattern. */
  async expectUrl(pattern: string | RegExp): Promise<void> {
    await expect(this.page).toHaveURL(pattern)
  }

  /**
   * Assert that the current URL contains the expected path substring.
   */
  async expectUrlContains(path: string): Promise<void> {
    await expect(this.page).toHaveURL(
      new RegExp(path.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')),
    )
  }

  // ════════════════════════════════════════
  // Pagination (src/components/ui/Pagination.tsx)
  // ════════════════════════════════════════

  /**
   * Pagination container.
   * Renders: <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200">
   *   Left: "共 <span>{total}</span> 条记录 (第 X-Y 条)"
   *   Right: <select> page size + <button> page numbers + prev/next
   *
   * Defined as a method (not getter) to avoid TS2610 conflicts with
   * subclasses that assign `readonly pagination: Locator` in their constructor.
   */
  getPagination(): Locator {
    return this.page
      .locator(
        '.flex.items-center.justify-between.px-4.py-3.border-t',
      )
      .first()
  }

  /**
   * Navigate to a specific page number.
   * Page buttons: <button>1</button>, <button>2</button>, ...
   * Active: <button className="bg-primary-600 text-white border-primary-600">
   */
  async goToPage(pageNumber: number): Promise<void> {
    const pageButton = this.getPagination().getByRole('button', {
      name: String(pageNumber),
      exact: true,
    })
    await pageButton.click()
    await this.waitForLoadingComplete()
  }

  /**
   * Click the "previous page" button (first button in pagination).
   * Prev button: <button><ChevronLeft /></button>
   */
  async goToPreviousPage(): Promise<void> {
    const prevBtn = this.getPagination().locator('button').first()
    await prevBtn.click()
    await this.waitForLoadingComplete()
  }

  /**
   * Click the "next page" button (last button in pagination).
   * Next button: <button><ChevronRight /></button>
   */
  async goToNextPage(): Promise<void> {
    const nextBtn = this.getPagination().locator('button').last()
    await nextBtn.click()
    await this.waitForLoadingComplete()
  }

  /**
   * Change the page size via the <select> dropdown.
   * Options: 10, 20, 50, 100
   */
  async changePageSize(size: number): Promise<void> {
    const select = this.getPagination().locator('select')
    await select.selectOption(String(size))
    await this.waitForLoadingComplete()
  }

  /**
   * Get the current page number (the active page button).
   */
  async getCurrentPage(): Promise<number> {
    const activeBtn = this.getPagination().locator('button.bg-primary-600')
    const text = await activeBtn.textContent()
    return parseInt(text || '1', 10)
  }

  /**
   * Get the total record count from the pagination info.
   * Renders: "共 <span className="font-medium">{total}</span> 条记录"
   */
  async getTotalRecords(): Promise<number> {
    const totalSpan = this.getPagination().locator('span.font-medium')
    const text = await totalSpan.textContent()
    return parseInt(text || '0', 10)
  }

  // ════════════════════════════════════════
  // Header / Breadcrumbs (Header.tsx)
  // ════════════════════════════════════════

  /**
   * Get the current breadcrumb text from the header.
   * Header renders: <nav> > <span>text</span>
   * Or fallback: <h1>title</h1>
   */
  async getBreadcrumbText(): Promise<string> {
    const nav = this.header.locator('nav')
    if ((await nav.count()) === 0) {
      const h1 = this.header.locator('h1')
      return (await h1.textContent()) || ''
    }
    return (await nav.textContent()) || ''
  }

  /**
   * Click the user menu dropdown in the header.
   * User button: <button className="flex items-center gap-2 ...">
   * Contains avatar + name + ChevronDown icon
   */
  async openUserMenu(): Promise<void> {
    const userBtn = this.header.locator('.group button').last()
    await userBtn.click()
  }

  /**
   * Click "退出登录" in the user dropdown to log out.
   */
  async logout(): Promise<void> {
    await this.openUserMenu()
    await this.page.getByRole('button', { name: /退出登录/ }).click()
    await this.page.waitForURL(/\/login/)
  }

  // ════════════════════════════════════════
  // Search Bar (SearchBar.tsx)
  // ════════════════════════════════════════

  /** Search bar container: <div className="bg-gray-50 p-4 rounded-lg"> */
  get searchBar(): Locator {
    return this.page.locator('.bg-gray-50.p-4.rounded-lg').first()
  }

  /** Click the "搜索" button in the search bar. */
  async clickSearch(): Promise<void> {
    await this.searchBar.getByRole('button', { name: /搜索/ }).click()
    await this.waitForLoadingComplete()
  }

  /** Click the "重置" button in the search bar. */
  async clickReset(): Promise<void> {
    await this.searchBar.getByRole('button', { name: /重置/ }).click()
    await this.waitForLoadingComplete()
  }

  // ════════════════════════════════════════
  // Common UI patterns
  // ════════════════════════════════════════

  /** Locate a <Button> by its visible text. */
  button(text: string | RegExp): Locator {
    return this.page.getByRole('button', { name: text })
  }

  /** Click a text-link or button that looks like a link. */
  async clickLink(text: string | RegExp): Promise<void> {
    await this.page
      .getByRole('link', { name: text })
      .or(this.button(text))
      .click()
  }

  // ════════════════════════════════════════
  // Utility
  // ════════════════════════════════════════

  /** Take a screenshot of the current page. */
  async screenshot(name: string): Promise<Buffer> {
    return this.page.screenshot({
      path: `tests/e2e/screenshots/${name}.png`,
    })
  }

  /** Scroll to the bottom of the main content area. */
  async scrollToBottom(): Promise<void> {
    await this.mainContent.evaluate((el) =>
      el.scrollTo(0, el.scrollHeight),
    )
  }

  /** Scroll to the top of the main content area. */
  async scrollToTop(): Promise<void> {
    await this.mainContent.evaluate((el) => el.scrollTo(0, 0))
  }
}
