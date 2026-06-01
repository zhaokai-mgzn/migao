/**
 * Base Test Fixture — Extended Playwright test with POM instances and helpers.
 *
 * Usage in spec files:
 *   import { test, expect } from '../fixtures/base'
 *
 *   test('example', async ({ page, basePage, dashboardPage, apiHelper }) => {
 *     await basePage.goto('/dashboard')
 *     await dashboardPage.expectStatCardsVisible()
 *     // ...
 *   })
 *
 * Every POM class is instantiated per-test and shares the same browser page.
 * Helper instances (ApiHelper, SSEHelper) are created per-test with
 * auto-teardown via fixture cleanup.
 */
import { test as base, type Page } from '@playwright/test'
import { ApiHelper } from '../helpers/api.helper'
import { SSEHelper } from '../helpers/sse.helper'
import {
  waitForToast,
  waitForLoadingComplete,
  waitForPageReady,
  waitForApiResponse,
} from '../helpers/wait.helper'

// ── POM imports ────────────────────────────────────────────
import { BasePage } from '../pages/base.page'
import { DashboardPage } from '../pages/dashboard.page'
import { LoginPage } from '../pages/login.page'
import { RegisterPage } from '../pages/register.page'
import { ProductListPage } from '../pages/products/product-list.page'
import { ProductDetailPage } from '../pages/products/product-detail.page'
import { ProductFormPage } from '../pages/products/product-form.page'
import { OrderListPage } from '../pages/orders/order-list.page'
import { OrderDetailPage } from '../pages/orders/order-detail.page'
import { OrderNewPage } from '../pages/orders/order-new.page'
import { OrderShipPage } from '../pages/orders/order-ship.page'
import { CustomerListPage } from '../pages/customers/customer-list.page'
import { CustomerDetailPage } from '../pages/customers/customer-detail.page'
import { AfterSalesListPage } from '../pages/after-sales/after-sales-list.page'
import { AfterSalesDetailPage } from '../pages/after-sales/after-sales-detail.page'
import { CategoriesPage } from '../pages/categories.page'
import { ProcessingPage } from '../pages/processing.page'
import { EmployeesPage } from '../pages/admin/employees.page'
import { RolesPage } from '../pages/admin/roles.page'
import { ChatPage } from '../pages/chat/chat.page'
import { KnowledgePage } from '../pages/knowledge/knowledge.page'
import { NotificationsPage } from '../pages/notifications/notifications.page'
import { SettingsPage } from '../pages/settings/settings.page'
import { RegistrationsPage } from '../pages/platform/registrations.page'
// ────────────────────────────────────────────────────────────

/** Fixtures provided by the extended test */
export interface TestFixtures {
  /** Base page object with shared layout/nav/toast/table/pagination utilities */
  basePage: BasePage

  /** Dashboard (数据看板) */
  dashboardPage: DashboardPage

  /** Login page */
  loginPage: LoginPage

  /** Registration page */
  registerPage: RegisterPage

  /** Product list (商品管理) */
  productListPage: ProductListPage

  /** Product detail */
  productDetailPage: ProductDetailPage

  /** Product create/edit form */
  productFormPage: ProductFormPage

  /** Order list (订单管理) */
  orderListPage: OrderListPage

  /** Order detail */
  orderDetailPage: OrderDetailPage

  /** New order form */
  orderNewPage: OrderNewPage

  /** Ship order form */
  orderShipPage: OrderShipPage

  /** Customer list (客户管理) */
  customerListPage: CustomerListPage

  /** Customer detail */
  customerDetailPage: CustomerDetailPage

  /** After-sales list (售后管理) */
  afterSalesListPage: AfterSalesListPage

  /** After-sales detail */
  afterSalesDetailPage: AfterSalesDetailPage

  /** Categories management */
  categoriesPage: CategoriesPage

  /** Processing items management (加工项管理) */
  processingPage: ProcessingPage

  /** Employee management (客服团队) */
  employeesPage: EmployeesPage

  /** Role & permission management (角色权限) */
  rolesPage: RolesPage

  /** AI chat page */
  chatPage: ChatPage

  /** Knowledge base management */
  knowledgePage: KnowledgePage

  /** Notification center (通知中心) */
  notificationsPage: NotificationsPage

  /** System settings (系统设置) */
  settingsPage: SettingsPage

  /** Platform registrations (企业入驻审批 — super-admin) */
  registrationsPage: RegistrationsPage

  /** Direct API client (auto-disposed after test) */
  apiHelper: ApiHelper

  /** SSE stream interceptor for chat/AI tests */
  sseHelper: SSEHelper

  /** Convenience wait utilities bound to the current page */
  waits: {
    waitForToast: (text?: string | RegExp, options?: { timeout?: number }) => Promise<void>
    waitForLoadingComplete: (options?: { timeout?: number }) => Promise<void>
    waitForPageReady: (options?: { timeout?: number }) => Promise<void>
    waitForApiResponse: (
      urlPattern: string | RegExp,
      options?: { timeout?: number; method?: string },
    ) => Promise<{ status: number; json: () => Promise<unknown> }>
  }
}

/**
 * Extract the access token from the browser's localStorage (auth-storage).
 * The zustand persist middleware stores state under key 'auth-storage'.
 */
async function extractTokenFromPage(page: Page): Promise<string> {
  const token = await page.evaluate(() => {
    try {
      const raw = localStorage.getItem('auth-storage')
      if (!raw) return ''
      const parsed = JSON.parse(raw)
      return parsed?.state?.accessToken || ''
    } catch {
      return ''
    }
  })
  return token
}

export const test = base.extend<TestFixtures>({
  // ── POM fixtures (one instance per test, sharing the same page) ──

  basePage: async ({ page }, use) => {
    await use(new BasePage(page))
  },

  dashboardPage: async ({ page }, use) => {
    await use(new DashboardPage(page))
  },

  loginPage: async ({ page }, use) => {
    await use(new LoginPage(page))
  },

  registerPage: async ({ page }, use) => {
    await use(new RegisterPage(page))
  },

  productListPage: async ({ page }, use) => {
    await use(new ProductListPage(page))
  },

  productDetailPage: async ({ page }, use) => {
    await use(new ProductDetailPage(page))
  },

  productFormPage: async ({ page }, use) => {
    await use(new ProductFormPage(page))
  },

  orderListPage: async ({ page }, use) => {
    await use(new OrderListPage(page))
  },

  orderDetailPage: async ({ page }, use) => {
    await use(new OrderDetailPage(page))
  },

  orderNewPage: async ({ page }, use) => {
    await use(new OrderNewPage(page))
  },

  orderShipPage: async ({ page }, use) => {
    await use(new OrderShipPage(page))
  },

  customerListPage: async ({ page }, use) => {
    await use(new CustomerListPage(page))
  },

  customerDetailPage: async ({ page }, use) => {
    await use(new CustomerDetailPage(page))
  },

  afterSalesListPage: async ({ page }, use) => {
    await use(new AfterSalesListPage(page))
  },

  afterSalesDetailPage: async ({ page }, use) => {
    await use(new AfterSalesDetailPage(page))
  },

  categoriesPage: async ({ page }, use) => {
    await use(new CategoriesPage(page))
  },

  processingPage: async ({ page }, use) => {
    await use(new ProcessingPage(page))
  },

  employeesPage: async ({ page }, use) => {
    await use(new EmployeesPage(page))
  },

  rolesPage: async ({ page }, use) => {
    await use(new RolesPage(page))
  },

  chatPage: async ({ page }, use) => {
    await use(new ChatPage(page))
  },

  knowledgePage: async ({ page }, use) => {
    await use(new KnowledgePage(page))
  },

  notificationsPage: async ({ page }, use) => {
    await use(new NotificationsPage(page))
  },

  settingsPage: async ({ page }, use) => {
    await use(new SettingsPage(page))
  },

  registrationsPage: async ({ page }, use) => {
    await use(new RegistrationsPage(page))
  },

  // ── Helper fixtures ────────────────────────────────────────

  apiHelper: async ({ page }, use) => {
    const token = await extractTokenFromPage(page)
    const helper = await ApiHelper.create(token || '')
    await use(helper)
    await helper.dispose()
  },

  sseHelper: async ({ page }, use) => {
    const helper = new SSEHelper(page)
    await use(helper)
    // Auto-cleanup: stop intercepting after test
    await helper.stopIntercept().catch(() => {})
  },

  waits: async ({ page }, use) => {
    await use({
      waitForToast: (text, options) => waitForToast(page, text, options),
      waitForLoadingComplete: (options) => waitForLoadingComplete(page, options),
      waitForPageReady: (options) => waitForPageReady(page, options),
      waitForApiResponse: (urlPattern, options) =>
        waitForApiResponse(page, urlPattern, options),
    })
  },
})

export { expect } from '@playwright/test'
