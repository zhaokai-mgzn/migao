import CustomerDetailPage from './CustomerDetail'

export const dynamicParams = true

export async function generateStaticParams() {
  // 不预生成特定 ID 的静态页，所有动态 ID 由客户端 SPA + OSS fallback 接管
  return [{ id: "_" }]
}

export default function Page() {
  return <CustomerDetailPage />
}
