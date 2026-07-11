'use client'
import { useState, useRef, useCallback, useEffect } from 'react'
import { createPortal } from 'react-dom'

interface RemarkEntry { timestamp: string; content: string }
export interface RemarkPopoverProps { remark: string | null | undefined; children: React.ReactNode }

function parseRemarks(remark: string | null | undefined): RemarkEntry[] {
  if (!remark || !remark.trim()) return []
  const entries: RemarkEntry[] = []
  const parts = remark.split(/\n(?=\[)/)
  for (const part of parts) {
    const match = part.match(/^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]\s*(.*)$/s)
    if (match) entries.push({ timestamp: match[1], content: match[2].trim() })
  }
  return entries
}

export default function RemarkPopover({ remark, children }: RemarkPopoverProps) {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState({ top: 0, left: 0 })
  const triggerRef = useRef<HTMLSpanElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const openTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const entries = parseRemarks(remark)

  const clearTimers = useCallback(() => {
    if (openTimerRef.current) { clearTimeout(openTimerRef.current); openTimerRef.current = null }
    if (closeTimerRef.current) { clearTimeout(closeTimerRef.current); closeTimerRef.current = null }
  }, [])

  const updatePosition = useCallback(() => {
    if (!triggerRef.current || !popoverRef.current) return
    const tr = triggerRef.current.getBoundingClientRect()
    const pr = popoverRef.current.getBoundingClientRect()
    const gap = 8
    let left = tr.right - pr.width
    let top = tr.bottom + gap
    if (left + pr.width > window.innerWidth - 16) left = window.innerWidth - pr.width - 16
    if (left < 16) left = 16
    if (top + pr.height > window.innerHeight - 16) top = tr.top - pr.height - gap
    if (top < 16) top = 16
    setPosition({ top, left })
  }, [])

  const handleMouseEnter = useCallback(() => {
    clearTimers()
    openTimerRef.current = setTimeout(() => setOpen(true), 200)
  }, [clearTimers])
  const handleMouseLeave = useCallback(() => {
    clearTimers()
    closeTimerRef.current = setTimeout(() => setOpen(false), 200)
  }, [clearTimers])

  useEffect(() => { if (open) requestAnimationFrame(() => updatePosition()) }, [open, updatePosition])
  useEffect(() => {
    if (!open) return
    const h = () => setOpen(false)
    window.addEventListener('scroll', h, true)
    window.addEventListener('resize', h)
    return () => { window.removeEventListener('scroll', h, true); window.removeEventListener('resize', h) }
  }, [open])
  useEffect(() => { return () => clearTimers() }, [clearTimers])

  const popover = open ? (
    <div ref={popoverRef} data-testid="remark-popover" role="tooltip" className="fixed z-[1000]"
      style={{ top: position.top, left: position.left, minWidth: 320, maxWidth: 600,
        maxHeight: 400, overflowY: 'auto', background: '#1F1F1F', color: '#FFFFFF',
        fontSize: 12, lineHeight: '20px', borderRadius: 6, padding: 12,
        boxShadow: '0 6px 16px 0 rgba(0,0,0,0.12)' }}
      onMouseEnter={() => { if (closeTimerRef.current) { clearTimeout(closeTimerRef.current); closeTimerRef.current = null } }}
      onMouseLeave={handleMouseLeave}>
      <div data-testid="remark-popover-arrow" style={{ position: 'absolute', top: -6, right: 16,
        width: 0, height: 0, borderLeft: '6px solid transparent', borderRight: '6px solid transparent',
        borderBottom: '6px solid #1F1F1F' }} />
      <div data-testid="remark-popover-content">
        {entries.length === 0 ? (
          <span className="text-gray-400 italic">暂无备注</span>
        ) : (
          <div className="space-y-2.5">
            {entries.map((entry, idx) => (
              <div key={idx} data-testid="remark-popover-item"
                className="border-b border-white/10 pb-2 last:border-b-0 last:pb-0">
                <div className="text-gray-400 text-[11px] mb-1">{entry.timestamp}</div>
                <div className="text-white whitespace-pre-wrap break-words">{entry.content}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  ) : null
  return (
    <span ref={triggerRef} className="relative group inline-block max-w-full cursor-pointer"
      onMouseEnter={handleMouseEnter} onMouseLeave={handleMouseLeave}>
      {children}
      {typeof window !== 'undefined' ? createPortal(popover, document.body) : null}
    </span>
  )
}
