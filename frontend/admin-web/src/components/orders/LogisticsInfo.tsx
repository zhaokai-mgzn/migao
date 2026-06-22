'use client'

import { Truck, Package, MapPin } from 'lucide-react'
import type { LogisticsInfo as LogisticsInfoType } from '@/types'
import dayjs from 'dayjs'

interface LogisticsInfoProps {
  logistics?: LogisticsInfoType
  className?: string
  onEdit?: () => void
}

export default function LogisticsInfo({ logistics, className, onEdit }: LogisticsInfoProps) {
  if (!logistics || (!logistics.logisticsCompany && !logistics.trackingNo)) {
    return (
      <div className={className}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Truck className="w-5 h-5 text-gray-400" />
            <h3 className="text-base font-semibold text-gray-900">物流信息</h3>
          </div>
          {onEdit && (
            <button
              onClick={onEdit}
              className="text-sm text-primary-600 hover:text-primary-700 font-medium"
            >
              录入物流
            </button>
          )}
        </div>
        <div className="text-center py-6 text-gray-400 text-sm">
          暂无物流信息
        </div>
      </div>
    )
  }

  return (
    <div className={className}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Truck className="w-5 h-5 text-gray-500" />
          <h3 className="text-base font-semibold text-gray-900">物流信息</h3>
        </div>
        {onEdit && (
          <button
            onClick={onEdit}
            className="text-sm text-primary-600 hover:text-primary-700 font-medium"
          >
            更新物流
          </button>
        )}
      </div>

      {/* 基本信息 */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        {logistics.logisticsCompany && (
          <div className="flex items-start gap-2">
            <Package className="w-4 h-4 text-gray-400 mt-0.5" />
            <div>
              <p className="text-xs text-gray-500">物流公司</p>
              <p className="text-sm font-medium text-gray-900">{logistics.logisticsCompany}</p>
            </div>
          </div>
        )}
        {logistics.trackingNo && (
          <div className="flex items-start gap-2">
            <MapPin className="w-4 h-4 text-gray-400 mt-0.5" />
            <div>
              <p className="text-xs text-gray-500">运单号</p>
              <p className="text-sm font-medium text-gray-900 font-mono">{logistics.trackingNo}</p>
            </div>
          </div>
        )}
      </div>

      {logistics.status && (
        <div className="mb-4 px-3 py-2 bg-blue-50 text-blue-700 rounded text-sm">
          当前状态: {logistics.status}
        </div>
      )}

      {/* 物流轨迹 */}
      {logistics.tracks && logistics.tracks.length > 0 && (
        <div className="border-t border-gray-100 pt-4">
          <h4 className="text-sm font-medium text-gray-700 mb-3">物流轨迹</h4>
          <div className="space-y-3">
            {logistics.tracks.map((track, index) => (
              <div key={index} className="flex items-start gap-3">
                <div className="flex flex-col items-center">
                  <div className={`w-2 h-2 rounded-full mt-1.5 ${index === 0 ? 'bg-blue-500' : 'bg-gray-300'}`} />
                  {index < logistics.tracks!.length - 1 && (
                    <div className="w-px h-6 bg-gray-200 mt-1" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className={`text-sm ${index === 0 ? 'text-gray-900 font-medium' : 'text-gray-600'}`}>
                    {track.description}
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {dayjs(track.time).format('YYYY-MM-DD HH:mm:ss')}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
