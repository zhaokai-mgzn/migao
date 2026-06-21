import ShipOrder from './ShipOrder'

export const dynamicParams = true

export async function generateStaticParams() {
  // 静态导出占位，实际 ID 由客户端从 URL 解析
  return []
}

export default function Page() {
  return <ShipOrder />
}
