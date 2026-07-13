'use client'

import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { createPortal } from 'react-dom'
import type { OrderRemark } from '@/types'
import dayjs from 'dayjs'

interface ParsedEntry {
  timestamp: string
  content: string
  operator?: string
}

/**
 * Parse remark string into entry array.
 * Format: [YYYY-MM-DD HH:mm] content [operator: name]
 * Multiple remarks are newline-separated.
 */
function parseRemarksFromString(remark: string | null | undefined): ParsedEntry[] {
  if (!remark || !remark.trim()) return []
  const lines = remark.split('\n')
  const entries: ParsedEntry[] = []
  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed) continue
    const match = trimmed.match(/^\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\]\s*([\s\S]*)$/)
    if (match) {
      let content = match[2]
      let operator: string | undefined
      const opMatch = content.match(/\s*\[操作人:\s*([^\]]+)\]\s*$/)
      if (opMatch) {
        operator = opMatch[1].trim()
        content = content.replace(/\s*\[操作人:\s*[^\]]+\]\s*$/, '')
      }
      entries.push({ timestamp: match[1], content, operator })
    } else {
      entries.push({ timestamp: '', content: trimmed })
    }
  }
  return entries.reverse()
}

function parseRemarksFromArray(remarks: OrderRemark[]): ParsedEntry[] {
  return [...remarks]
    .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
    .map(r => ({
      timestamp: r.createdAt ? dayjs(r.createdAt).format('YYYY-MM-DD HH:mm') : '',
      content: r.content,
      operator: r.operator,
    }))
}

export interface RemarkPopoverProps {
  remark?: string | null
  remarks?: OrderRemark[] | null
  children: React.ReactNode
}

export default function RemarkPopover({ remark, remarks, children }: RemarkPopoverProps) {
  const [visible, setVisible] = useState(false)
  const [position, setPosition] = useState({ top: 0, left: 0 })
  const triggerRef = useRef<HTMLSpanElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const lastScrollYRef = useRef(0)

  const entries = useMemo<ParsedEntry[]>(() => {
    if (remarks && remarks.length > 0) {
      return parseRemarksFromArray(remarks)
    }
    return parseRemarksFromString(remark)
  }, [remark, remarks])

  const updatePosition = useCallback(() => {
    if (!triggerRef.current || !popoverRef.current) return
    const triggerRect = triggerRef.current.getBoundingClientRect()
    const popoverWidth = popoverRef.current.offsetWidth
    const popoverHeight = popoverRef.current.offsetHeight
    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight

    let left = triggerRect.left
    let top = triggerRect.bottom + 8

    if (left < 8) left = 8
    if (left + popoverWidth > viewportWidth - 8) {
      left = viewportWidth - popoverWidth - 8
    }
    if (top + popoverHeight > viewportHeight - 8) {
      top = triggerRect.top - popoverHeight - 8
    }
    if (top < 8) top = 8

    setPosition({ top, left })
  }, [])

  const handleMouseEnter = () => {
    setVisible(true)
  }

  const handleMouseLeave = () => {
    setVisible(false)
  }

  useEffect(() => {
    if (visible) {
      lastScrollYRef.current = window.scrollY
      requestAnimationFrame(() => {
        updatePosition()
      })
    }
  }, [visible, updatePosition])

  useEffect(() => {
    if (!visible) return

    const handleScroll = () => {
      const delta = Math.abs(window.scrollY - lastScrollYRef.current)
      if (delta > 5) {
        setVisible(false)
      }
    }

    const handleResize = () => setVisible(false)
    window.addEventListener('scroll', handleScroll, true)
    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('scroll', handleScroll, true)
      window.removeEventListener('resize', handleResize)
    }
  }, [visible])

  const popover = visible ? (
    <div
      ref={popoverRef}
      role="tooltip"
      style={{
        position: 'fixed',
        top: position.top,
        left: position.left,
        zIndex: 9999,
      }}
      className="min-w-[320px] max-w-[600px] max-h-[400px] overflow-y-auto
        bg-[#1F1F1F] text-white text-xs leading-5
        rounded-lg shadow-[0_6px_16px_0_rgba(0,0,0,0.12)]
        pointer-events-auto"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <div
        className="absolute w-0 h-0"
        style={{
          top: -6,
          left: 16,
          borderLeft: '6px solid transparent',
          borderRight: '6px solid transparent',
          borderBottom: '6px solid #1F1F1F',
        }}
      />

      <div className="p-3">
        {entries.length === 0 ? (
          <span className="text-gray-400">暂无备注</span>
        ) : (
          <ul className="space-y-2.5">
            {entries.map((entry, index) => (
              <li key={index} className="border-b border-gray-700 last:border-b-0 pb-2 last:pb-0">
                <div className="flex items-center gap-2 mb-1">
                  {entry.timestamp && (
                    <span className="text-gray-400 text-[11px]">
                      {entry.timestamp}
                    </span>
                  )}
                  {entry.operator && (
                    <span
                      data-operator={entry.operator}
                      className="text-blue-300 text-[11px]"
                    >
                      — {entry.operator}
                    </span>
                  )}
                </div>
                <div className="whitespace-pre-wrap break-words text-white">
                  {entry.content}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  ) : null

  return (
    <span
      ref={triggerRef}
      className="block w-full cursor-default"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {children}
      {createPortal(popover, document.body)}
    </span>
  )
}
