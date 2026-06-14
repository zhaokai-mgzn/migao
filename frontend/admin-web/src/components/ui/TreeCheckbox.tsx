'use client'

import React, { useMemo } from 'react'

export interface TreeNode {
  code: string
  label: string
  children?: TreeNode[]
}

interface TreeCheckboxProps {
  tree: TreeNode[]
  selected: string[]
  onChange: (selected: string[]) => void
}

export function TreeCheckbox({ tree, selected, onChange }: TreeCheckboxProps) {
  const allLeafCodes = useMemo(
    () => tree.flatMap(n => (n.children?.length ? n.children.map(c => c.code) : n.code)),
    [tree]
  )

  const allChecked = allLeafCodes.length > 0 && allLeafCodes.every(c => selected.includes(c))
  const someChecked = allLeafCodes.some(c => selected.includes(c))
  const allIndeterminate = someChecked && !allChecked

  return (
    <div className="space-y-1">
      {/* Master toggle */}
      <label className="flex items-center gap-2 py-1.5 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={allChecked}
          ref={el => { if (el) el.indeterminate = allIndeterminate }}
          onChange={() => {
            if (allChecked) onChange(selected.filter(c => !allLeafCodes.includes(c)))
            else onChange([...selected, ...allLeafCodes.filter(c => !selected.includes(c))])
          }}
          className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
        />
        <span className="text-sm font-semibold">全部权限</span>
      </label>

      {/* Tree */}
      <div className="ml-1 space-y-0.5">
        {tree.map(node => {
          const children = node.children?.length ? node.children : [node]
          const childCodes = children.map(c => c.code)
          const checkedCount = childCodes.filter(c => selected.includes(c)).length
          const isChecked = checkedCount === childCodes.length && childCodes.length > 0
          const isIndeterminate = checkedCount > 0 && checkedCount < childCodes.length

          return (
            <div key={node.code}>
              <label className="flex items-center gap-2 py-1 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={isChecked}
                  ref={el => { if (el) el.indeterminate = isIndeterminate }}
                  onChange={() => {
                    if (childCodes.every(c => selected.includes(c)))
                      onChange(selected.filter(c => !childCodes.includes(c)))
                    else
                      onChange([...selected, ...childCodes.filter(c => !selected.includes(c))])
                  }}
                  className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                />
                <span className="text-sm">{node.label}</span>
              </label>

              {node.children && node.children.length > 0 && (
                <div className="ml-6 space-y-0.5">
                  {node.children.map(child => (
                    <label key={child.code} className="flex items-center gap-2 py-0.5 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={selected.includes(child.code)}
                        onChange={() => {
                          if (selected.includes(child.code))
                            onChange(selected.filter(c => c !== child.code))
                          else
                            onChange([...selected, child.code])
                        }}
                        className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                      <span className="text-sm">{child.label}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
