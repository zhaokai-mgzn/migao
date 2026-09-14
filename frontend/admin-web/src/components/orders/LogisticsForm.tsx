'use client'

import { useState } from 'react'
import { Button, Input, Modal } from '@/components/ui'
import type { LogisticsFormData } from '@/types'

interface LogisticsFormProps {
  open: boolean
  onClose: () => void
  onSubmit: (data: LogisticsFormData) => Promise<void>
  initialData?: Partial<LogisticsFormData>
}

export default function LogisticsForm({ open, onClose, onSubmit, initialData }: LogisticsFormProps) {
  const [company, setCompany] = useState(initialData?.company || '')
  const [trackingNo, setTrackingNo] = useState(initialData?.trackingNo || '')
  // 发货人（发货单「经手人」，issue #3768）：回填已有值供纠正；留空则下发时省略，
  // 后端保留原发货人（不会被本次编辑人顶替）—— 存量订单为空时也可在此手工补齐
  const [shipperName, setShipperName] = useState(initialData?.shipperName || '')
  const [loading, setLoading] = useState(false)
  const [errors, setErrors] = useState<{ company?: string; trackingNo?: string }>({})

  const validate = (): boolean => {
    const newErrors: { company?: string; trackingNo?: string } = {}
    if (!company.trim()) newErrors.company = '请输入物流公司'
    if (!trackingNo.trim()) newErrors.trackingNo = '请输入运单号'
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async () => {
    if (!validate()) return
    setLoading(true)
    try {
      await onSubmit({
        company: company.trim(),
        trackingNo: trackingNo.trim(),
        shippingMethod: 'logistics',
        shipperName: shipperName.trim(),
      })
      onClose()
    } catch (e) {
      // error handled by parent
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="物流信息"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={loading}>
            取消
          </Button>
          <Button onClick={handleSubmit} loading={loading}>
            确认保存
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Input
          label="物流公司"
          placeholder="如：顺丰、中通、韵达"
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          error={errors.company}
          required
        />
        <Input
          label="运单号"
          placeholder="请输入运单号"
          value={trackingNo}
          onChange={(e) => setTrackingNo(e.target.value)}
          error={errors.trackingNo}
          required
        />
        <Input
          label="发货人"
          placeholder="发货单「经手人」；留空则保留原发货人"
          value={shipperName}
          onChange={(e) => setShipperName(e.target.value)}
        />
      </div>
    </Modal>
  )
}
