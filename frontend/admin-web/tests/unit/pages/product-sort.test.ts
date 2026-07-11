import { describe, it, expect } from 'vitest'

/**
 * #1201: Product list sort state machine
 *
 * Three-state toggle for sortable columns:
 *   - Page loads with DEFAULT sort (createdAt DESC, no visual indicator)
 *   - First click on ANY column → asc (ascending) — column indicator shows ↑
 *   - Second click on same column → desc (descending) — column indicator shows ↓
 *   - Third click on same column → cancel (return to default: createdAt desc, no indicator)
 *   - Clicking a different column → start with asc for that column
 */

interface SortState {
  field: string
  order: 'asc' | 'desc'
  /** Whether the current sort is an active user-selected sort (false = default) */
  active: boolean
}

const DEFAULT_SORT: SortState = { field: 'createdAt', order: 'desc', active: false }

/**
 * Pure function implementing the #1201 sort state machine.
 */
function getNextSortState(current: SortState, clickedField: string): SortState {
  if (!current.active) {
    return { field: clickedField, order: 'asc', active: true }
  }
  if (current.field === clickedField) {
    if (current.order === 'asc') {
      return { field: clickedField, order: 'desc', active: true }
    }
    return { ...DEFAULT_SORT }
  }
  return { field: clickedField, order: 'asc', active: true }
}

describe('getNextSortState — Product sort state machine (#1201)', () => {
  it('Case 1: first click on stock → asc', () => {
    const next = getNextSortState(DEFAULT_SORT, 'stock')
    expect(next).toEqual({ field: 'stock', order: 'asc', active: true })
  })

  it('Case 2: second click on stock → desc', () => {
    const current: SortState = { field: 'stock', order: 'asc', active: true }
    const next = getNextSortState(current, 'stock')
    expect(next).toEqual({ field: 'stock', order: 'desc', active: true })
  })

  it('Case 3: third click on stock → cancel (return to default)', () => {
    const current: SortState = { field: 'stock', order: 'desc', active: true }
    const next = getNextSortState(current, 'stock')
    expect(next).toEqual({ field: 'createdAt', order: 'desc', active: false })
  })

  it('Case 4: after cancel, clicking stock → asc again', () => {
    const next = getNextSortState(DEFAULT_SORT, 'stock')
    expect(next).toEqual({ field: 'stock', order: 'asc', active: true })
  })

  it('Case 5: clicking createdAt from default → asc', () => {
    const next = getNextSortState(DEFAULT_SORT, 'createdAt')
    expect(next).toEqual({ field: 'createdAt', order: 'asc', active: true })
  })

  it('Case 6: createdAt full cycle: asc → desc → cancel → asc', () => {
    const s1 = getNextSortState(DEFAULT_SORT, 'createdAt')
    expect(s1).toEqual({ field: 'createdAt', order: 'asc', active: true })
    const s2 = getNextSortState(s1, 'createdAt')
    expect(s2).toEqual({ field: 'createdAt', order: 'desc', active: true })
    const s3 = getNextSortState(s2, 'createdAt')
    expect(s3).toEqual({ field: 'createdAt', order: 'desc', active: false })
    const s4 = getNextSortState(s3, 'createdAt')
    expect(s4).toEqual({ field: 'createdAt', order: 'asc', active: true })
  })

  it('Case 7: full 3-cycle on salesAmount', () => {
    const s1 = getNextSortState(DEFAULT_SORT, 'salesAmount')
    expect(s1).toEqual({ field: 'salesAmount', order: 'asc', active: true })
    const s2 = getNextSortState(s1, 'salesAmount')
    expect(s2).toEqual({ field: 'salesAmount', order: 'desc', active: true })
    const s3 = getNextSortState(s2, 'salesAmount')
    expect(s3).toEqual({ field: 'createdAt', order: 'desc', active: false })
    const s4 = getNextSortState(s3, 'salesAmount')
    expect(s4).toEqual({ field: 'salesAmount', order: 'asc', active: true })
  })

  it('Case 8: switching columns → asc for new column', () => {
    const current: SortState = { field: 'stock', order: 'desc', active: true }
    const next = getNextSortState(current, 'salesCount')
    expect(next).toEqual({ field: 'salesCount', order: 'asc', active: true })
  })

  it('Case 9: clicking non-active createdAt from stock sort → asc', () => {
    const current: SortState = { field: 'stock', order: 'desc', active: true }
    const next = getNextSortState(current, 'createdAt')
    expect(next).toEqual({ field: 'createdAt', order: 'asc', active: true })
  })
})
