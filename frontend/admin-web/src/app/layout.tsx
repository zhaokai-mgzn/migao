import type { Metadata } from 'next'
import { Toaster } from 'sonner'
import AuthProvider from '@/components/providers/AuthProvider'
import { AuthGuard } from '@/components/auth-guard'
import './globals.css'

export const metadata: Metadata = {
  title: '有客 - AI电商管理系统',
  description: '有客是米高智能旗下的AI电商管理系统，为企业提供一站式智能电商管理解决方案',
}

/**
 * 早期同步脚本：还原 SPA fallback 透传的原始 URL
 *
 * 静态导出 + OSS 部署下，访问动态路由（例如 /products/123/edit/）时，
 * OSS ErrorDocument 会先把请求改派到 /products/_/edit/?__spa_path=/products/123/edit/。
 * 此脚本在 Next.js bundle 与任何业务组件 hydrate 之前同步执行，
 * 用 history.replaceState 把地址栏 URL 还原成 /products/123/edit/，
 * 然后 useRouteId 等组件可以从 window.location.pathname 读取真实 ID。
 *
 * 限定条件：
 *   - 仅在 query 中存在 __spa_path 时生效；
 *   - 仅识别同源、以 / 开头的内部路径，避免开放重定向；
 *   - 仅在当前 pathname 含占位段 "/_" 或 "/_/" 时执行还原，避免误伤其它页面；
 *   - 还原后立即清理 query，避免污染历史栈。
 */
const SPA_PATH_RESTORE_SCRIPT = `(() => {
  try {
    var url = new URL(window.location.href);
    var sp = url.searchParams;
    var raw = sp.get('__spa_path');
    if (!raw) return;
    if (raw.charAt(0) !== '/' || raw.charAt(1) === '/') return;
    if (!/\/_(\/|$)/.test(url.pathname)) return;
    sp.delete('__spa_path');
    var rest = sp.toString();
    var sepIdx = raw.indexOf('?');
    var hashIdx = raw.indexOf('#');
    if (rest) {
      if (sepIdx === -1 && hashIdx === -1) raw = raw + '?' + rest;
      else if (sepIdx === -1) raw = raw.slice(0, hashIdx) + '?' + rest + raw.slice(hashIdx);
      else raw = raw + '&' + rest;
    }
    window.history.replaceState(null, '', raw);
  } catch (e) { /* swallow */ }
})();`

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-CN">
      <body>
        {/* 必须最先执行：在 Next.js 客户端 router 与任何组件 hydrate 之前还原 URL */}
        <script dangerouslySetInnerHTML={{ __html: SPA_PATH_RESTORE_SCRIPT }} />
        <AuthProvider>
          <AuthGuard>{children}</AuthGuard>
        </AuthProvider>
        <Toaster 
          position="top-center"
          toastOptions={{
            style: {
              background: '#fff',
              border: '1px solid #e5e7eb',
              padding: '12px 16px',
              borderRadius: '8px',
              fontSize: '14px',
            },
          }}
        />
      </body>
    </html>
  )
}
