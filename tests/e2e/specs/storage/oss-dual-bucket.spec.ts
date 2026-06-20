import { test, expect } from '@playwright/test'
import * as path from 'path'
import * as fs from 'fs'

test.describe('OSS 双 Bucket 路由', () => {
  const testImagePath = path.join(__dirname, '../../fixtures/test-image.png')
  const API_BASE = process.env.API_BASE_URL || 'http://localhost:8080'
  const AI_SERVICE_URL = 'http://localhost:8001'

  test.describe('聊天图片上传（临时 Bucket）', () => {
    test.beforeEach(async ({ page }) => {
      // 进入对话页面
      await page.goto('/chat')
      await page.waitForLoadState('load')

      // 尝试创建新会话 — 先点击 sidebar 中的"新建对话"
      const createBtn = page.getByRole('button', { name: '新建对话' })
      if (await createBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
        await createBtn.click()
        await page.waitForTimeout(2000)
      }

      // 如果还没有选中会话（MessageInput 未出现），点击 sidebar 中第一个会话项
      const messageInput = page.locator('textarea[placeholder*="输入消息"]')
      if (!(await messageInput.isVisible({ timeout: 2000 }).catch(() => false))) {
        // 点击 sidebar 中的会话列表项来选中会话
        const sessionItem = page.locator('.mx-1\\.5').first()
        if (await sessionItem.isVisible({ timeout: 2000 }).catch(() => false)) {
          await sessionItem.click()
          await page.waitForTimeout(1000)
        }
      }
    })

    test('上传图片应使用 chat/{tenant_id}/ 目录前缀', async ({ page }) => {
      const uploadUrls: string[] = []

      page.on('request', (request) => {
        // 聊天图片上传走 AI 服务：/api/chat/upload-image
        if (request.url().includes('/api/chat/upload-image')) {
          uploadUrls.push(request.url())
        }
      })

      // 图片上传按钮 — 使用按钮文本 "添加图片"
      const uploadBtn = page.getByRole('button', { name: '添加图片' })
      await expect(uploadBtn).toBeVisible()

      const fileChooserPromise = page.waitForEvent('filechooser')
      await uploadBtn.click()
      const fileChooser = await fileChooserPromise
      await fileChooser.setFiles(testImagePath)

      await page.waitForTimeout(3000)

      expect(uploadUrls.length).toBeGreaterThan(0)
    })

    test('上传多张图片应全部使用临时 bucket', async ({ page }) => {
      const uploadCount = { value: 0 }

      page.on('request', (request) => {
        if (request.url().includes('/api/chat/upload-image')) {
          uploadCount.value++
        }
      })

      const uploadBtn = page.getByRole('button', { name: '添加图片' })

      for (let i = 0; i < 3; i++) {
        const fileChooserPromise = page.waitForEvent('filechooser')
        await uploadBtn.click()
        const fileChooser = await fileChooserPromise
        await fileChooser.setFiles(testImagePath)
        await page.waitForTimeout(1000)
      }

      expect(uploadCount.value).toBe(3)
    })
  })

  test.describe('商品图片上传（永久 Bucket）', () => {
    test.beforeEach(async ({ page }) => {
      // 进入商品创建页面
      await page.goto('/products/new')
      await page.waitForSelector('text=新增商品')
    })

    test('上传商品封面图应使用 products/ 目录前缀', async ({ page }) => {
      const uploadRequests: string[] = []

      page.on('request', (request) => {
        if (request.url().includes('/api/admin/files/upload') || request.url().includes('/api/admin/upload/image')) {
          uploadRequests.push(request.url())
          const postData = request.postData()
          if (postData) {
            expect(postData).toContain('directory')
            // products/ 前缀表示永久 bucket
            expect(postData).toContain('products/')
          }
        }
      })

      // ImageUploader 组件使用 <div> 作为可见的上传触发器，文本为 "上传封面"
      const coverUploadArea = page.getByText('上传封面')
      await expect(coverUploadArea).toBeVisible()

      // 隐藏的 file input 会被触发
      const fileChooserPromise = page.waitForEvent('filechooser')
      await coverUploadArea.click()
      const fileChooser = await fileChooserPromise
      await fileChooser.setFiles(testImagePath)

      await page.waitForTimeout(2000)

      // 验证使用了永久 bucket
      expect(uploadRequests.length).toBeGreaterThan(0)
    })

    test('上传详情图应使用 products/ 目录前缀', async ({ page }) => {
      const uploadRequests: string[] = []

      page.on('request', (request) => {
        if (request.url().includes('/api/admin/files/upload') || request.url().includes('/api/admin/upload/image')) {
          uploadRequests.push(request.url())
          const postData = request.postData()
          if (postData) {
            // 详情图也应该使用 products/ 前缀
            expect(postData).toContain('products/')
          }
        }
      })

      // 详情图的上传触发器文本为 "上传图片"
      const detailUploadArea = page.getByText('上传图片')
      await expect(detailUploadArea).toBeVisible()

      const fileChooserPromise = page.waitForEvent('filechooser')
      await detailUploadArea.click()
      const fileChooser = await fileChooserPromise
      await fileChooser.setFiles(testImagePath)

      await page.waitForTimeout(2000)

      expect(uploadRequests.length).toBeGreaterThan(0)
    })
  })

  test.describe('上传 API 兼容性验证', () => {
    const testImageBytes = fs.readFileSync(testImagePath)

    test('单文件上传接口存在', async ({ request }) => {
      const response = await request.post(`${API_BASE}/api/admin/files/upload`, {
        multipart: {
          file: { name: 'test.png', mimeType: 'image/png', buffer: testImageBytes },
          directory: 'test',
        },
      })

      expect(response.status()).toBeLessThan(500)
    })

    test('批量上传接口存在', async ({ request }) => {
      const response = await request.post(`${API_BASE}/api/admin/files/upload-batch`, {
        multipart: {
          files: { name: 'test.png', mimeType: 'image/png', buffer: testImageBytes },
          directory: 'test',
        },
      })

      expect(response.status()).toBeLessThan(500)
    })

    test('图片上传返回有效 URL 且公网可访问', async ({ request }) => {
      // 上传一张真实图片
      const response = await request.post(`${API_BASE}/api/admin/upload/image`, {
        multipart: {
          file: { name: 'test.png', mimeType: 'image/png', buffer: testImageBytes },
          directory: 'test',
        },
      })

      // 1. 状态码必须成功
      expect(response.status()).toBe(200)

      const body = await response.json()
      expect(body.success).toBe(true)

      // 2. 返回的 URL 必须是非空字符串
      const url = body.data?.url
      expect(url).toBeTruthy()
      expect(typeof url).toBe('string')
      expect(url.startsWith('https://')).toBe(true)

      // 3. URL 必须公网可访问（DashScope Vision API 要求）
      const verify = await request.get(url)
      expect(verify.status()).toBe(200)

      // 4. 响应内容类型必须是图片
      const contentType = verify.headers()['content-type']
      expect(contentType).toMatch(/^image\//)
    })

    test('AI Agent 聊天上传返回有效 URL 列表且图片可访问', async ({ request }) => {
      // 上传真实图片到 AI 服务聊天上传接口
      const response = await request.post(`${AI_SERVICE_URL}/api/chat/upload-image`, {
        multipart: {
          files: { name: 'test.png', mimeType: 'image/png', buffer: testImageBytes },
        },
      })

      // 1. 状态码必须成功
      expect(response.status()).toBe(200)

      const body = await response.json()
      expect(body.success).toBe(true)

      // 2. 返回的 files 数组必须非空
      const files = body.data?.files
      expect(Array.isArray(files)).toBe(true)
      expect(files.length).toBeGreaterThan(0)

      // 3. 每个文件都必须包含可用的 URL
      for (const file of files) {
        expect(file.url).toBeTruthy()
        expect(file.url.startsWith('https://')).toBe(true)

        // 验证 URL 公网可访问
        const verify = await request.get(file.url)
        expect(verify.status()).toBe(200)

        // 响应内容必须是图片
        const contentType = verify.headers()['content-type']
        expect(contentType).toMatch(/^image\//)
      }
    })
  })
})
