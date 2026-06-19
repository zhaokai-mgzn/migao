/**
 * Playwright Global Setup
 *
 * 在所有 E2E 测试运行前执行，清理上次测试可能遗留的脏数据。
 */
import { spawn } from 'node:child_process'
import * as path from 'node:path'

export default async function globalSetup(): Promise<void> {
  const scriptPath = path.join(__dirname, 'scripts', 'cleanup-e2e-data.ts')
  const cwd = path.join(__dirname, '..')

  try {
    console.log('[global-setup] 清理 E2E 测试脏数据...')
    await new Promise<void>((resolve, reject) => {
      const child = spawn('npx', ['tsx', scriptPath], {
        cwd,
        stdio: 'inherit',
        timeout: 30_000,
        env: {
          ...process.env,
          NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL || 'https://api.migaozn.com',
        },
      })
      child.on('close', (code) => {
        if (code === 0) resolve()
        else reject(new Error(`exit code ${code}`))
      })
      child.on('error', reject)
    })
    console.log('[global-setup] 清理完成')
  } catch (err) {
    // 清理失败不阻断测试（可能是网络问题等）
    console.warn('[global-setup] 清理失败（不阻断测试）:', String(err))
  }
}
