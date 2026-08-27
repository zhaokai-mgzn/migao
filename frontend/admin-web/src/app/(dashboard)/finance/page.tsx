'use client'

import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Plus, Search, RotateCcw, Wallet, ArrowDownCircle, ArrowUpCircle, TrendingUp } from 'lucide-react'
import { financeApi } from '@/lib/api'
import { Button, Input, Select, Pagination, Modal, Badge } from '@/components/ui'
import type {
  FinanceTransaction,
  FinanceTransactionType,
  FinancePaymentMethod,
  FinanceSummary,
  ReceivableReconciliationItem,
} from '@/types'
import {
  FinanceTransactionTypeLabels,
  FinancePaymentMethodLabels,
  FinanceTransactionStatusLabels,
} from '@/types'
import { cn } from '@/lib/utils'
import DateTimeCell from '@/components/common/DateTimeCell'

const fmtMoney = (n?: number) =>
  '¥' + (n ?? 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

// 后端订单状态 → 中文（避免与前端 OrderStatus 枚举混用）
const ORDER_STATUS_LABELS: Record<string, string> = {
  pending: '待付款',
  confirmed: '待发货',
  producing: '生产中',
  shipped: '已发货',
  completed: '已完成',
  cancelled: '已取消',
}

type TabKey = 'transactions' | 'summary' | 'reconciliation'

const tabs: { key: TabKey; label: string }[] = [
  { key: 'transactions', label: '资金流水' },
  { key: 'summary', label: '收支汇总' },
  { key: 'reconciliation', label: '应收对账' },
]

export default function FinancePage() {
  // ===== 时间范围（summary / 三个 tab 共用） =====
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [appliedRange, setAppliedRange] = useState<{ startDate: string; endDate: string }>({ startDate: '', endDate: '' })

  // ===== 收支汇总 =====
  const [summary, setSummary] = useState<FinanceSummary | null>(null)
  const [summaryLoading, setSummaryLoading] = useState(false)

  // ===== 当前 tab =====
  const [tab, setTab] = useState<TabKey>('transactions')

  // ===== 资金流水 =====
  const [txns, setTxns] = useState<FinanceTransaction[]>([])
  const [txnLoading, setTxnLoading] = useState(false)
  const [txnTotal, setTxnTotal] = useState(0)
  const [txnPage, setTxnPage] = useState(1)
  const [txnSize, setTxnSize] = useState(20)
  const [txnType, setTxnType] = useState<FinanceTransactionType | ''>('')
  const [txnMethod, setTxnMethod] = useState<FinancePaymentMethod | ''>('')
  const [txnKeyword, setTxnKeyword] = useState('')
  const [txnSearch, setTxnSearch] = useState<{ type: string; method: string; keyword: string }>({ type: '', method: '', keyword: '' })

  // ===== 应收对账 =====
  const [recs, setRecs] = useState<ReceivableReconciliationItem[]>([])
  const [recLoading, setRecLoading] = useState(false)
  const [recTotal, setRecTotal] = useState(0)
  const [recPage, setRecPage] = useState(1)
  const [recSize, setRecSize] = useState(20)
  const [recKeyword, setRecKeyword] = useState('')
  const [recSearch, setRecSearch] = useState('')
  const [onlyDiff, setOnlyDiff] = useState(false)

  // ===== 登记收支弹窗 =====
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({
    type: 'income' as FinanceTransactionType,
    amount: '',
    paymentMethod: 'wechat' as FinancePaymentMethod,
    orderId: '',
    remark: '',
    occurredAt: '',
  })

  const loadSummary = useCallback(async () => {
    setSummaryLoading(true)
    try {
      const hasRange = appliedRange.startDate || appliedRange.endDate
      const res = await financeApi.getSummary(hasRange ? appliedRange : undefined)
      setSummary(res.data?.data ?? null)
    } catch {
      toast.error('加载收支汇总失败')
    } finally {
      setSummaryLoading(false)
    }
  }, [appliedRange])

  const loadTxns = useCallback(async () => {
    setTxnLoading(true)
    try {
      const params: Record<string, unknown> = {
        page: txnPage,
        size: txnSize,
        startDate: appliedRange.startDate || undefined,
        endDate: appliedRange.endDate || undefined,
      }
      if (txnSearch.type) params.type = txnSearch.type
      if (txnSearch.method) params.paymentMethod = txnSearch.method
      if (txnSearch.keyword) params.keyword = txnSearch.keyword
      const res = await financeApi.getTransactions(params as never)
      setTxns(res.data?.data?.items ?? [])
      setTxnTotal(res.data?.data?.total ?? 0)
    } catch {
      toast.error('加载资金流水失败')
    } finally {
      setTxnLoading(false)
    }
  }, [txnPage, txnSize, txnSearch, appliedRange])

  const loadRecs = useCallback(async () => {
    setRecLoading(true)
    try {
      const res = await financeApi.getReconciliation({
        page: recPage,
        size: recSize,
        startDate: appliedRange.startDate || undefined,
        endDate: appliedRange.endDate || undefined,
        keyword: recSearch || undefined,
      })
      setRecs(res.data?.data?.items ?? [])
      setRecTotal(res.data?.data?.total ?? 0)
    } catch {
      toast.error('加载应收对账失败')
    } finally {
      setRecLoading(false)
    }
  }, [recPage, recSize, recSearch, appliedRange])

  useEffect(() => { loadSummary() }, [loadSummary])
  useEffect(() => { loadTxns() }, [loadTxns])
  useEffect(() => { loadRecs() }, [loadRecs])

  const applyRange = () => {
    setAppliedRange({ startDate, endDate })
    setTxnPage(1)
    setRecPage(1)
  }

  const resetRange = () => {
    setStartDate('')
    setEndDate('')
    setAppliedRange({ startDate: '', endDate: '' })
    setTxnPage(1)
    setRecPage(1)
  }

  const handleTxnSearch = () => {
    setTxnPage(1)
    setTxnSearch({ type: txnType, method: txnMethod, keyword: txnKeyword })
  }

  const handleRecSearch = () => {
    setRecPage(1)
    setRecSearch(recKeyword)
  }

  const handleCreate = async () => {
    const amount = Number(form.amount)
    if (!form.amount || Number.isNaN(amount) || amount <= 0) {
      toast.error('请输入正确的金额')
      return
    }
    setCreating(true)
    try {
      await financeApi.createTransaction({
        type: form.type,
        amount,
        paymentMethod: form.paymentMethod,
        orderId: form.orderId || undefined,
        remark: form.remark || undefined,
        occurredAt: form.occurredAt ? new Date(form.occurredAt).toISOString() : undefined,
      })
      toast.success('登记成功')
      setCreateOpen(false)
      setForm({ type: 'income', amount: '', paymentMethod: 'wechat', orderId: '', remark: '', occurredAt: '' })
      loadTxns()
      loadSummary()
    } catch {
      toast.error('登记失败')
    } finally {
      setCreating(false)
    }
  }

  const diffVariant = (d: number) => (d === 0 ? 'success' : d > 0 ? 'warning' : 'error')
  const diffLabel = (d: number) => (d === 0 ? '已对平' : d > 0 ? '多收' : '少收')

  const visibleRecs = onlyDiff ? recs.filter((r) => r.difference !== 0) : recs

  return (
    <div className="p-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">财务对账</h1>
          <p className="text-sm text-neutral-500 mt-1">资金流水、收支汇总与应收对账</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="w-4 h-4 mr-1.5" />
          登记收支
        </Button>
      </div>

      {/* 时间范围筛选 */}
      <div className="bg-white border border-neutral-200 rounded-lg p-4 mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[160px]">
            <Input
              label="开始日期"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </div>
          <div className="min-w-[160px]">
            <Input
              label="结束日期"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={resetRange}>
              <RotateCcw className="w-4 h-4 mr-1" />
              重置
            </Button>
            <Button onClick={applyRange}>
              <Search className="w-4 h-4 mr-1" />
              查询
            </Button>
          </div>
        </div>
      </div>

      {/* 汇总卡片 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <SummaryCard
          title="本期收入"
          icon={<ArrowDownCircle className="w-5 h-5 text-green-600" />}
          value={summaryLoading ? null : summary?.totalIncome}
          hint={`${summary?.incomeCount ?? 0} 笔`}
          accent="text-green-600"
        />
        <SummaryCard
          title="本期退款"
          icon={<ArrowUpCircle className="w-5 h-5 text-red-500" />}
          value={summaryLoading ? null : summary?.totalRefund}
          hint={`${summary?.refundCount ?? 0} 笔`}
          accent="text-red-600"
        />
        <SummaryCard
          title="净收入"
          icon={<TrendingUp className="w-5 h-5 text-primary-600" />}
          value={summaryLoading ? null : summary?.netIncome}
          hint="收入 - 退款"
          accent="text-primary-600"
        />
        <SummaryCard
          title="待收款"
          icon={<Wallet className="w-5 h-5 text-amber-500" />}
          value={summaryLoading ? null : summary?.pendingReceivable}
          hint="累计未收差额"
          accent="text-amber-600"
        />
      </div>

      {/* Tab 栏 */}
      <div className="flex items-center gap-0 bg-white border border-neutral-200 rounded-t-lg overflow-x-auto">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              'relative px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2',
              tab === t.key
                ? 'text-primary-600 border-primary-600 bg-primary-50/50'
                : 'text-neutral-500 border-transparent hover:text-neutral-700 hover:bg-neutral-50'
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ===== 资金流水 ===== */}
      {tab === 'transactions' && (
        <div className="bg-white rounded-b-lg border border-t-0 border-neutral-200">
          <div className="flex flex-wrap items-end gap-3 p-4 border-b border-neutral-100">
            <div className="min-w-[140px]">
              <Select
                label="收支类型"
                value={txnType}
                onChange={(e) => setTxnType(e.target.value as FinanceTransactionType | '')}
                options={[
                  { value: '', label: '全部' },
                  { value: 'income', label: '收款' },
                  { value: 'refund', label: '退款' },
                ]}
              />
            </div>
            <div className="min-w-[140px]">
              <Select
                label="支付方式"
                value={txnMethod}
                onChange={(e) => setTxnMethod(e.target.value as FinancePaymentMethod | '')}
                options={[
                  { value: '', label: '全部' },
                  ...Object.entries(FinancePaymentMethodLabels).map(([value, label]) => ({ value, label })),
                ]}
              />
            </div>
            <div className="min-w-[220px]">
              <Input
                label="关键词"
                placeholder="流水号 / 订单号"
                value={txnKeyword}
                onChange={(e) => setTxnKeyword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleTxnSearch()}
              />
            </div>
            <Button variant="secondary" onClick={handleTxnSearch}>查询</Button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-neutral-200 bg-neutral-50/50">
                  <th className="text-left px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">流水号</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">类型</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">金额</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">支付方式</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">关联订单</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">状态</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">操作人</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">交易时间</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">备注</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {txnLoading ? (
                  <tr><td colSpan={9} className="px-4 py-12 text-center text-neutral-400">加载中...</td></tr>
                ) : txns.length === 0 ? (
                  <tr><td colSpan={9} className="px-4 py-12 text-center text-neutral-400">暂无资金流水</td></tr>
                ) : (
                  txns.map((t) => (
                    <tr key={t.id} className="hover:bg-neutral-50/50 transition-colors">
                      <td className="px-4 py-3"><span className="font-mono text-sm text-neutral-900">{t.transactionNo}</span></td>
                      <td className="px-4 py-3">
                        <Badge variant={t.type === 'income' ? 'success' : 'error'}>
                          {FinanceTransactionTypeLabels[t.type] || t.type}
                        </Badge>
                      </td>
                      <td className={cn('px-4 py-3 text-right font-medium', t.type === 'income' ? 'text-green-600' : 'text-red-600')}>
                        {t.type === 'income' ? '+' : '-'}{fmtMoney(t.amount)}
                      </td>
                      <td className="px-4 py-3 text-sm text-neutral-700">
                        {t.paymentMethod ? FinancePaymentMethodLabels[t.paymentMethod as FinancePaymentMethod] || t.paymentMethod : '-'}
                      </td>
                      <td className="px-4 py-3"><span className="font-mono text-sm text-neutral-600">{t.orderNo || '-'}</span></td>
                      <td className="px-4 py-3">
                        <Badge variant={t.status === 'success' ? 'success' : t.status === 'failed' ? 'error' : 'default'}>
                          {FinanceTransactionStatusLabels[t.status] || t.status}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-sm text-neutral-600">{t.operator || '-'}</td>
                      <td className="px-4 py-3 text-sm text-neutral-500"><DateTimeCell value={t.occurredAt || t.createdAt} /></td>
                      <td className="px-4 py-3 text-sm text-neutral-500 max-w-[200px] truncate">{t.remark || '-'}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          <Pagination
            current={txnPage}
            pageSize={txnSize}
            total={txnTotal}
            onChange={setTxnPage}
            onPageSizeChange={(size) => { setTxnSize(size); setTxnPage(1) }}
          />
        </div>
      )}

      {/* ===== 收支汇总 ===== */}
      {tab === 'summary' && (
        <div className="bg-white rounded-b-lg border border-t-0 border-neutral-200 p-6">
          <h3 className="text-sm font-semibold text-neutral-900 mb-3">按支付方式</h3>
          <div className="overflow-x-auto mb-6">
            <table className="w-full">
              <thead>
                <tr className="border-b border-neutral-200 bg-neutral-50/50">
                  <th className="text-left px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider">支付方式</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider">收入</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider">退款</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider">净额</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {(summary?.byPaymentMethod ?? []).length === 0 ? (
                  <tr><td colSpan={4} className="px-4 py-8 text-center text-neutral-400">暂无数据</td></tr>
                ) : (
                  (summary?.byPaymentMethod ?? []).map((m) => (
                    <tr key={m.paymentMethod} className="hover:bg-neutral-50/50">
                      <td className="px-4 py-3 text-sm text-neutral-900">{FinancePaymentMethodLabels[m.paymentMethod as FinancePaymentMethod] || m.paymentMethod}</td>
                      <td className="px-4 py-3 text-right text-sm text-green-600">{fmtMoney(m.income)}</td>
                      <td className="px-4 py-3 text-right text-sm text-red-600">{fmtMoney(m.refund)}</td>
                      <td className="px-4 py-3 text-right text-sm font-medium text-neutral-900">{fmtMoney(m.net)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <h3 className="text-sm font-semibold text-neutral-900 mb-3">按日趋势</h3>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-neutral-200 bg-neutral-50/50">
                  <th className="text-left px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider">日期</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider">收入</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider">退款</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider">净额</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {(summary?.dailyTrend ?? []).length === 0 ? (
                  <tr><td colSpan={4} className="px-4 py-8 text-center text-neutral-400">暂无数据</td></tr>
                ) : (
                  (summary?.dailyTrend ?? []).map((d) => (
                    <tr key={d.date} className="hover:bg-neutral-50/50">
                      <td className="px-4 py-3 text-sm text-neutral-900">{d.date || '-'}</td>
                      <td className="px-4 py-3 text-right text-sm text-green-600">{fmtMoney(d.income)}</td>
                      <td className="px-4 py-3 text-right text-sm text-red-600">{fmtMoney(d.refund)}</td>
                      <td className="px-4 py-3 text-right text-sm font-medium text-neutral-900">{fmtMoney(d.net)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ===== 应收对账 ===== */}
      {tab === 'reconciliation' && (
        <div className="bg-white rounded-b-lg border border-t-0 border-neutral-200">
          <div className="flex flex-wrap items-end gap-3 p-4 border-b border-neutral-100">
            <div className="min-w-[220px]">
              <Input
                label="关键词"
                placeholder="订单号 / 客户名 / 手机号"
                value={recKeyword}
                onChange={(e) => setRecKeyword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleRecSearch()}
              />
            </div>
            <Button variant="secondary" onClick={handleRecSearch}>查询</Button>
            <label className="flex items-center gap-2 ml-auto text-sm text-neutral-700 cursor-pointer">
              <input
                type="checkbox"
                checked={onlyDiff}
                onChange={(e) => setOnlyDiff(e.target.checked)}
                className="w-4 h-4 rounded border-neutral-300 text-primary-600"
              />
              仅看异常（差额 ≠ 0）
            </label>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-neutral-200 bg-neutral-50/50">
                  <th className="text-left px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">订单号</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">客户</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">状态</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">应收</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">实收</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">已退</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">差额</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">对账</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider whitespace-nowrap">下单时间</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {recLoading ? (
                  <tr><td colSpan={9} className="px-4 py-12 text-center text-neutral-400">加载中...</td></tr>
                ) : visibleRecs.length === 0 ? (
                  <tr><td colSpan={9} className="px-4 py-12 text-center text-neutral-400">暂无对账数据</td></tr>
                ) : (
                  visibleRecs.map((r) => (
                    <tr key={r.orderId} className="hover:bg-neutral-50/50 transition-colors">
                      <td className="px-4 py-3"><span className="font-mono text-sm text-neutral-900">{r.orderNo}</span></td>
                      <td className="px-4 py-3 text-sm text-neutral-700">{r.customerName || '-'}</td>
                      <td className="px-4 py-3">
                        <Badge variant="default">{ORDER_STATUS_LABELS[r.status] || r.status}</Badge>
                      </td>
                      <td className="px-4 py-3 text-right text-sm text-neutral-700">{fmtMoney(r.receivableAmount)}</td>
                      <td className="px-4 py-3 text-right text-sm text-neutral-700">{fmtMoney(r.receivedAmount)}</td>
                      <td className="px-4 py-3 text-right text-sm text-red-600">{r.refundAmount > 0 ? fmtMoney(r.refundAmount) : '-'}</td>
                      <td className={cn('px-4 py-3 text-right text-sm font-medium', r.difference === 0 ? 'text-neutral-500' : r.difference > 0 ? 'text-amber-600' : 'text-red-600')}>
                        {r.difference === 0 ? '0.00' : (r.difference > 0 ? '+' : '') + fmtMoney(r.difference)}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={diffVariant(r.difference)}>{diffLabel(r.difference)}</Badge>
                      </td>
                      <td className="px-4 py-3 text-sm text-neutral-500"><DateTimeCell value={r.createdAt} /></td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          <Pagination
            current={recPage}
            pageSize={recSize}
            total={recTotal}
            onChange={setRecPage}
            onPageSizeChange={(size) => { setRecSize(size); setRecPage(1) }}
          />
        </div>
      )}

      {/* 登记收支弹窗 */}
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="登记收支"
        footer={
          <>
            <Button variant="secondary" onClick={() => setCreateOpen(false)}>取消</Button>
            <Button onClick={handleCreate} loading={creating}>提交</Button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-neutral-700 mb-1.5">收支类型 *</label>
            <div className="flex gap-2">
              {(['income', 'refund'] as FinanceTransactionType[]).map((t) => (
                <button
                  key={t}
                  onClick={() => setForm((f) => ({ ...f, type: t }))}
                  className={cn(
                    'px-4 py-1.5 rounded-lg border text-sm font-medium transition-all',
                    form.type === t
                      ? t === 'income' ? 'border-green-500 bg-green-50 text-green-700' : 'border-red-500 bg-red-50 text-red-700'
                      : 'border-neutral-200 hover:border-neutral-300 text-neutral-700'
                  )}
                >
                  {FinanceTransactionTypeLabels[t]}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-neutral-700 mb-1.5">金额 *</label>
            <Input
              type="number"
              min="0.01"
              step="0.01"
              placeholder="0.00"
              value={form.amount}
              onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-neutral-700 mb-1.5">支付方式</label>
            <Select
              value={form.paymentMethod}
              onChange={(e) => setForm((f) => ({ ...f, paymentMethod: e.target.value as FinancePaymentMethod }))}
              options={Object.entries(FinancePaymentMethodLabels).map(([value, label]) => ({ value, label }))}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-neutral-700 mb-1.5">关联订单号（可选）</label>
            <Input
              placeholder="输入订单号或订单 UUID"
              value={form.orderId}
              onChange={(e) => setForm((f) => ({ ...f, orderId: e.target.value }))}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-neutral-700 mb-1.5">交易时间（可选）</label>
            <Input
              type="datetime-local"
              value={form.occurredAt}
              onChange={(e) => setForm((f) => ({ ...f, occurredAt: e.target.value }))}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-neutral-700 mb-1.5">备注</label>
            <textarea
              value={form.remark}
              onChange={(e) => setForm((f) => ({ ...f, remark: e.target.value }))}
              rows={3}
              className="w-full px-3 py-2 rounded border border-neutral-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
            />
          </div>
        </div>
      </Modal>
    </div>
  )
}

function SummaryCard({ title, icon, value, hint, accent }: {
  title: string
  icon: React.ReactNode
  value: number | null | undefined
  hint?: string
  accent?: string
}) {
  return (
    <div className="bg-white rounded-lg border border-neutral-200 p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-neutral-500">{title}</span>
        {icon}
      </div>
      <div className={cn('text-2xl font-semibold', accent ?? 'text-neutral-900')}>
        {value === null ? '...' : fmtMoney(value ?? 0)}
      </div>
      {hint && <div className="text-xs text-neutral-400 mt-1">{hint}</div>}
    </div>
  )
}
