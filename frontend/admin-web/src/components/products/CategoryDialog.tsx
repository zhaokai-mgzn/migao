'use client'

import { useState, useEffect } from 'react'
import { Button, Input, Select, Modal } from '@/components/ui'
import type { Category, CategoryFormData } from '@/types'

interface CategoryDialogProps {
  open: boolean
  onClose: () => void
  onSubmit: (data: CategoryFormData) => Promise<void>
  category?: Category | null
  categories: Category[]
  presetParentId?: string
}

// Flatten category tree for parent selection
function flattenCategories(categories: Category[], level = 0): { value: string; label: string }[] {
  const result: { value: string; label: string }[] = []
  for (const cat of categories) {
    const prefix = '\u00A0\u00A0'.repeat(level)
    result.push({ value: cat.id, label: `${prefix}${level > 0 ? '└ ' : ''}${cat.name}` })
    if (cat.children && cat.children.length > 0) {
      result.push(...flattenCategories(cat.children, level + 1))
    }
  }
  return result
}

export default function CategoryDialog({
  open,
  onClose,
  onSubmit,
  category,
  categories,
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
    } catch {
      // Error handled by API layer
    } finally {
      setSubmitting(false)
    }
  }

  // 仅一级分类可作为父级（限制最多二级分类）
  const parentOptions = [
    { value: '', label: '无（顶级分类）' },
    ...categories
      .filter((c) => c.id !== category?.id)
      .map((c) => ({ value: c.id, label: c.name })),
  ]

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

        <Select
          label="父级分类"
          options={parentOptions}
          value={form.parentId || ''}
          onChange={(e) => setForm({ ...form, parentId: e.target.value })}
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
