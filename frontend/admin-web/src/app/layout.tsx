import type { Metadata } from 'next'
import { Toaster } from 'sonner'
import AuthProvider from '@/components/providers/AuthProvider'
import { AuthGuard } from '@/components/auth-guard'
import './globals.css'

export const metadata: Metadata = {
  title: '有客 - AI电商管理系统',
  description: '有客是米高智能旗下的AI电商管理系统，为企业提供一站式智能电商管理解决方案',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-CN">
      <body>
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
