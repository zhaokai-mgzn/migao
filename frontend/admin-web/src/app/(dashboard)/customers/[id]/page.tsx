import CustomerDetailPage from './CustomerDetail'

export async function generateStaticParams() {
  // 静态导出需要至少一个占位路径；实际 ID 由客户端路由 + OSS fallback 处理
  return [{ id: '_' }]
}

export default function Page() {
  return <CustomerDetailPage />
}
