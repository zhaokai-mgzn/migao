'use client'

import { useState } from 'react'
import { Search, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import Button from './Button'
import Input from './Input'
import Select from './Select'

export interface SearchField {
  key: string
  label: string
  type: 'input' | 'select'
  placeholder?: string
  options?: { value: string; label: string }[]
}

interface SearchBarProps {
  fields: SearchField[]
  onSearch: (values: Record<string, string>) => void
  onReset?: () => void
  loading?: boolean
  className?: string
}

const SearchBar = ({ fields, onSearch, onReset, loading, className }: SearchBarProps) => {
  const [values, setValues] = useState<Record<string, string>>({})

  const handleSearch = () => {
    onSearch(values)
  }

  const handleReset = () => {
    setValues({})
    onReset?.()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch()
    }
  }

  return (
    <div className={cn('bg-gray-50 p-4 rounded-lg', className)}>
      <div className="flex flex-wrap items-end gap-4">
        {fields.map((field) => (
          <div key={field.key} className="min-w-[200px]">
            {field.type === 'input' ? (
              <Input
                label={field.label}
                placeholder={field.placeholder}
                value={values[field.key] || ''}
                onChange={(e) => setValues({ ...values, [field.key]: e.target.value })}
                onKeyDown={handleKeyDown}
              />
            ) : (
              <Select
                label={field.label}
                placeholder={field.placeholder || '请选择'}
                options={field.options || []}
                value={values[field.key] || ''}
                onChange={(e) => setValues({ ...values, [field.key]: e.target.value })}
              />
            )}
          </div>
        ))}

        <div className="flex items-center gap-2 ml-auto">
          <Button
            variant="secondary"
            onClick={handleReset}
            disabled={loading}
          >
            <X className="w-4 h-4 mr-1" />
            重置
          </Button>
          <Button
            onClick={handleSearch}
            loading={loading}
          >
            <Search className="w-4 h-4 mr-1" />
            搜索
          </Button>
        </div>
      </div>
    </div>
  )
}

export default SearchBar
