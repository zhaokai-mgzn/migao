'use client'

import React, { useMemo, forwardRef } from 'react'

export interface TreeNode {
  code: string
  label: string
  children?: TreeNode[]
}

interface TreeCheckboxProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'onChange'> {
  tree: TreeNode[]
  selected: string[]
  onChange: (selected: string[]) => void
}

export const TreeCheckbox = forwardRef<HTMLDivElement, TreeCheckboxProps>(
  function TreeCheckbox({ tree, selected, onChange, ...rest }, ref) {
    // 收集所有叶子节点 code：如果节点有非空 children，取 children 的 code；否则取节点自身 code（独立叶子）
    const allLeafCodes = useMemo(
      () => tree.flatMap(n =>
        n.children && n.children.length > 0
          ? n.children.map(c => c.code)
          : n.code
      ),
      [tree]
    )

    const selectedSet = useMemo(() => new Set(selected), [selected])
    const allLeafSet = useMemo(() => new Set(allLeafCodes), [allLeafCodes])

    const allChecked = allLeafCodes.length > 0 && allLeafCodes.every(c => selectedSet.has(c))
    const someChecked = allLeafCodes.some(c => selectedSet.has(c))
    const allIndeterminate = someChecked && !allChecked

    return (
      <div ref={ref} {...rest} className="space-y-1">
        {/* Master toggle */}
        <label className="flex items-center gap-2 py-1.5 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={allChecked}
            ref={el => { if (el) el.indeterminate = allIndeterminate }}
            onChange={() => {
              if (allChecked) onChange(selected.filter(c => !allLeafSet.has(c)))
              else onChange([...selected, ...allLeafCodes.filter(c => !selectedSet.has(c))])
            }}
            className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
          />
          <span className="text-sm font-semibold">全部权限</span>
        </label>

        {/* Tree */}
        <div className="ml-1 space-y-0.5">
          {tree.map(node => {
            // 如果节点有子节点，取子节点；否则将自身作为叶子（用于没有子菜单的独立页面）
            const children = node.children && node.children.length > 0 ? node.children : [node]
            const childCodes = children.map(c => c.code)
            const checkedCount = childCodes.filter(c => selectedSet.has(c)).length
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
                      if (isChecked)
                        onChange(selected.filter(c => !childCodes.includes(c)))
                      else
                        onChange([...selected, ...childCodes.filter(c => !selectedSet.has(c))])
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
                          checked={selectedSet.has(child.code)}
                          onChange={() => {
                            if (selectedSet.has(child.code))
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
)
