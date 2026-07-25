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
  presetParentId?: string
}

export default function CategoryDialog({
  open,
  onClose,
  onSubmit,
  category,
  categories: _categories,
  presetParentId,
}: CategoryDialogProps) {
  const [form, setForm] = useState<CategoryFormData>({
    name: '',
    parentId: '',
    sort: 0,
  })
  const [submitting, setSubmitting] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const isEdit = !!category

  useEffect(() => {
    if (category) {
      setForm({
        name: category.name,
        parentId: category.parentId || '',
        sort: category.sort || 0,
      })
    } else {
      setForm({ name: '', parentId: presetParentId || '', sort: 0 })
    }
    setErrors({})
  }, [category, open, presetParentId])

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
        ...form,
        parentId: form.parentId || undefined,
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

        <Input
          label="排序"
          type="number"
          placeholder="数值越小越靠前"
          value={String(form.sort || 0)}
          onChange={(e) => setForm({ ...form, sort: Number(e.target.value) })}
        />
      </div>
    </Modal>
  )
}
