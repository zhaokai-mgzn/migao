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
      await onSubmit({ company: company.trim(), trackingNo: trackingNo.trim(), shippingMethod: 'logistics' })
      onClose()
    } catch {
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
      </div>
    </Modal>
  )
}
