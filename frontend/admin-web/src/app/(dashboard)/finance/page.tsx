'use client'

import { Construction } from 'lucide-react'

export default function FinancePage() {
  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-gray-900 mb-4">财务对账</h1>
      <div className="bg-white rounded-lg border border-gray-200 p-12 text-center">
        <Construction className="w-12 h-12 text-gray-300 mx-auto mb-4" />
        <p className="text-gray-500">财务对账功能开发中，敬请期待。</p>
      </div>
    </div>
  )
}
