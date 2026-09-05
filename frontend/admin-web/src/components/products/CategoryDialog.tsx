'use client'

import { useState, useEffect } from 'react'
import { Button, Input, Modal } from '@/components/ui'
import type { Category, CategoryFormData } from '@/types'

interface CategoryDialogProps {
  open: boolean
  onClose: () => void
  onSubmit: (data: CategoryFormData) => Promise<void>
  category?: Category | null
  categories: Category[]
}

export default function CategoryDialog({
  open,
  onClose,
  onSubmit,
  category,
  categories: _categories,
}: CategoryDialogProps) {
  const [form, setForm] = useState<CategoryFormData>({
    name: '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const isEdit = !!category

  useEffect(() => {
    if (category) {
      setForm({
        name: category.name,
      })
    } else {
      setForm({ name: '' })
    }
    setErrors({})
  }, [category, open])

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {}
    if (!form.name.trim()) {
      newErrors.name = '请输入分类名称'
    }
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async () => {
    if (!validate()) return
    setSubmitting(true)
    try {
      await onSubmit({
        name: form.name.trim(),
      })
      onClose()
    } catch (e) {
      // Error handled by API layer
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? '编辑分类' : '添加分类'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button onClick={handleSubmit} loading={submitting}>
            {isEdit ? '保存' : '添加'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Input
          label="分类名称"
          required
          placeholder="请输入分类名称"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          error={errors.name}
        />
        <p className="text-xs text-neutral-400">分类顺序可通过列表中的上移/下移按钮调整。</p>
      </div>
    </Modal>
  )
}