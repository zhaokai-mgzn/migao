import { Bot, Check, MessageSquare, PackageOpen, ShieldCheck, Sparkles } from 'lucide-react'

/**
 * 官网用的产品界面示意（纯 CSS/SVG，不接真实数据）。
 *
 * 口径：这是**示意**，不是线上读数 —— 每个画面都带「界面示意」标记；
 * 不写具体订单量 / 销售额 / 客户名，避免把演示数据当成经营事实。
 */

function Frame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-3xl border border-neutral-200 bg-white shadow-card">
      <div className="flex items-center justify-between border-b border-neutral-100 bg-neutral-50/80 px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-accent-400" />
          <span className="h-2.5 w-2.5 rounded-full bg-gold-400" />
          <span className="h-2.5 w-2.5 rounded-full bg-primary-400" />
          <span className="ml-2 text-xs font-medium text-neutral-500">{title}</span>
        </div>
        <span className="rounded-md bg-white px-2 py-0.5 text-xs text-neutral-400 ring-1 ring-neutral-200">
          界面示意
        </span>
      </div>
      {children}
    </div>
  )
}

/** Hero 工作台：经营概览 + 生产进度 + 黄金策问答 */
export function WorkbenchMock() {
  return (
    <Frame title="生意管家 · 工作台">
      <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-12 sm:p-5">
        <div className="space-y-4 sm:col-span-7">
          <div className="grid grid-cols-2 gap-3">
            {[
              ['订单进度', '待发货', 'bg-amber-50 text-amber-700 ring-amber-200'],
              ['生产报工', '后整', 'bg-primary-50 text-primary-700 ring-primary-200'],
              ['批次库存', '待盘', 'bg-neutral-50 text-neutral-600 ring-neutral-200'],
              ['待处理事项', '可跟进', 'bg-emerald-50 text-emerald-700 ring-emerald-200'],
            ].map(([label, value, tone]) => (
              <div key={label} className="rounded-2xl border border-neutral-200 bg-white p-3.5">
                <p className="text-xs text-neutral-500">{label}</p>
                <span className={`mt-2 inline-flex rounded-md px-2 py-0.5 text-xs font-medium ring-1 ${tone}`}>
                  {value}
                </span>
              </div>
            ))}
          </div>

          <div className="rounded-2xl border border-neutral-200 bg-white p-4">
            <div className="flex items-center justify-between">
              <p className="text-sm font-semibold text-neutral-900">订单趋势</p>
              <span className="text-xs text-neutral-400">按日</span>
            </div>
            <svg viewBox="0 0 320 80" className="mt-3 h-20 w-full" role="img" aria-label="订单趋势示意">
              <defs>
                <linearGradient id="mock-trend" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#48618f" stopOpacity="0.28" />
                  <stop offset="100%" stopColor="#48618f" stopOpacity="0" />
                </linearGradient>
              </defs>
              <path d="M0 62 L40 54 L80 58 L120 40 L160 46 L200 28 L240 34 L280 18 L320 24 V80 H0 Z" fill="url(#mock-trend)" />
              <path d="M0 62 L40 54 L80 58 L120 40 L160 46 L200 28 L240 34 L280 18 L320 24" fill="none" stroke="#48618f" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
        </div>

        <div className="sm:col-span-5">
          <div className="flex h-full flex-col rounded-2xl border border-neutral-200 bg-neutral-50/60 p-4">
            <div className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-primary-500 to-primary-700">
                <Bot className="h-4 w-4 text-white" />
              </span>
              <div>
                <p className="text-xs font-semibold text-neutral-900">黄金策</p>
                <p className="text-xs text-neutral-500">经营侧 AI</p>
              </div>
            </div>
            <div className="mt-4 space-y-2.5">
              <p className="ml-auto w-fit max-w-[90%] rounded-2xl rounded-br-sm bg-primary-600 px-3 py-2 text-xs leading-relaxed text-white">
                哪些订单进入后整了？
              </p>
              <div className="w-fit max-w-[95%] rounded-2xl rounded-bl-sm bg-white px-3 py-2 text-xs leading-relaxed text-neutral-700 ring-1 ring-neutral-200">
                已按工序汇总：裁剪与车位完成的订单，后整进度可在加工单里逐件查看。
              </div>
              <div className="rounded-xl bg-white p-2.5 ring-1 ring-neutral-200">
                <p className="text-xs font-medium text-neutral-500">回答依据</p>
                <p className="mt-1 text-xs leading-relaxed text-neutral-700">
                  订单、加工单与报工记录同源；只读查询，不改动单据。
                </p>
              </div>
            </div>
            <div className="mt-auto flex items-center gap-1.5 pt-4 text-xs text-neutral-400">
              <ShieldCheck className="h-3.5 w-3.5" />
              写操作需确认，关键动作留痕
            </div>
          </div>
        </div>
      </div>
    </Frame>
  )
}

/** 顾客经营：微信对话框 + 估算报价卡 */
export function CustomerChatMock() {
  return (
    <Frame title="微信客服 · 米宝">
      <div className="space-y-3 bg-neutral-50/60 p-4 sm:p-5">
        <div className="flex justify-end">
          <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary-600 px-3.5 py-2 text-xs leading-relaxed text-white">
            客厅窗宽 3.2 米，想用遮光布，做韩褶，大概多少？
          </p>
        </div>
        <div className="flex gap-2">
          <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary-500 to-primary-700">
            <MessageSquare className="h-3.5 w-3.5 text-white" />
          </span>
          <div className="max-w-[88%] space-y-2">
            <p className="rounded-2xl rounded-bl-sm bg-white px-3.5 py-2 text-xs leading-relaxed text-neutral-700 ring-1 ring-neutral-200">
              按 3.2 米窗宽、2 倍褶皱与韩褶工艺估算，用料约 6.4 米；加工项可一起勾选。
            </p>
            <div className="rounded-xl bg-white p-3 ring-1 ring-neutral-200">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold text-neutral-900">估算报价</p>
                <span className="rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700">估算</span>
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-neutral-500">
                成交单价以商品库权威价为准；加工费按所选组合计算。
              </p>
              <div className="mt-2 flex items-center gap-1.5 text-xs text-neutral-400">
                <Check className="h-3 w-3 text-emerald-600" />
                可继续选门幅、颜色与安装方式
              </div>
            </div>
          </div>
        </div>
        <div className="flex justify-end">
          <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary-600 px-3.5 py-2 text-xs leading-relaxed text-white">
            帮我下单，手机号稍后填。
          </p>
        </div>
        <div className="ml-9 flex items-center gap-1.5 text-xs text-neutral-400">
          <Sparkles className="h-3.5 w-3.5" />
          7×24 接待；复杂诉求按规则交人工
        </div>
      </div>
    </Frame>
  )
}

/** 经营决策：看板 + 每日简报 + 数据问答 */
export function DashboardMock() {
  return (
    <Frame title="管理后台 · 经营报表">
      <div className="space-y-3 p-4 sm:p-5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-lg bg-primary-600 px-2.5 py-1 text-xs font-medium text-white">经营报表</span>
          <span className="rounded-lg bg-neutral-100 px-2.5 py-1 text-xs text-neutral-600">每日简报</span>
          <span className="rounded-lg bg-neutral-100 px-2.5 py-1 text-xs text-neutral-600">数据问答</span>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {['订单量', '销售额', '待发货', '待收款'].map((label) => (
            <div key={label} className="rounded-xl border border-neutral-200 bg-white p-3">
              <p className="text-xs text-neutral-500">{label}</p>
              <div className="mt-2 h-2 w-10 rounded-full bg-neutral-100" />
              <p className="mt-1 text-xs text-neutral-400">以实际开通版本为准</p>
            </div>
          ))}
        </div>
        <div className="rounded-xl border border-neutral-200 bg-white p-3.5">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-neutral-900">今日简报</p>
            <span className="text-xs text-neutral-400">按日生成</span>
          </div>
          <ul className="mt-2.5 space-y-2 text-xs leading-relaxed text-neutral-600">
            <li className="flex gap-2">
              <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-accent-500" />
              订单与生产进度按工序汇总，异常单可下钻到明细。
            </li>
            <li className="flex gap-2">
              <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-accent-500" />
              库存与批次变动逐笔记录，差异可追溯。
            </li>
            <li className="flex gap-2">
              <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-accent-500" />
              计件与收支按人、工序与期间汇总。
            </li>
          </ul>
        </div>
      </div>
    </Frame>
  )
}

/** 生产与交付：工序看板 */
export function ProductionMock() {
  return (
    <Frame title="加工单 · 生产进度">
      <div className="grid grid-cols-3 gap-2.5 p-4 sm:p-5">
        {[
          ['裁剪', '裁床', '待报工'],
          ['车位', '缝制', '进行中'],
          ['后整', '烫工', '待开始'],
        ].map(([stage, role, state], index) => (
          <div key={stage} className="rounded-xl border border-neutral-200 bg-neutral-50/60 p-2.5">
            <p className="text-xs font-semibold text-neutral-900">{stage}</p>
            <p className="mt-0.5 text-xs text-neutral-400">{role}</p>
            <div className="mt-2.5 space-y-2">
              <div className="rounded-lg bg-white p-2 ring-1 ring-neutral-200">
                <p className="text-xs font-medium text-neutral-700">加工单 · 窗帘</p>
                <p className="mt-0.5 text-xs text-neutral-400">按件报工</p>
              </div>
              <span
                className={`inline-flex rounded-md px-1.5 py-0.5 text-xs ring-1 ${
                  index === 1
                    ? 'bg-primary-50 text-primary-700 ring-primary-200'
                    : 'bg-white text-neutral-500 ring-neutral-200'
                }`}
              >
                {state}
              </span>
            </div>
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between border-t border-neutral-100 px-4 py-2.5 text-xs text-neutral-400 sm:px-5">
        <span>扫码报工 · 合格 / 返工 / 报废</span>
        <span className="inline-flex items-center gap-1">
          <PackageOpen className="h-3 w-3" />
          进度与发货同源
        </span>
      </div>
    </Frame>
  )
}

/** 库存与对账：批次台账 + 计件 */
export function StockMock() {
  return (
    <Frame title="库存台账 · 批次">
      <div className="p-4 sm:p-5">
        <div className="overflow-hidden rounded-xl border border-neutral-200">
          <div className="grid grid-cols-4 bg-neutral-50 px-3 py-2 text-xs font-medium text-neutral-500">
            <span>批次</span>
            <span>门幅</span>
            <span>库存</span>
            <span>成本</span>
          </div>
          {[0, 1, 2].map((row) => (
            <div key={row} className="grid grid-cols-4 border-t border-neutral-100 px-3 py-2.5 text-xs text-neutral-600">
              <span className="font-medium text-neutral-800">批次 {String.fromCharCode(65 + row)}</span>
              <span>—</span>
              <span>—</span>
              <span>—</span>
            </div>
          ))}
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2.5">
          <div className="rounded-xl border border-neutral-200 bg-white p-3">
            <p className="text-xs text-neutral-500">库存变动</p>
            <p className="mt-1.5 text-xs leading-relaxed text-neutral-600">入库、出库、盘点与余料逐笔记录。</p>
          </div>
          <div className="rounded-xl border border-neutral-200 bg-white p-3">
            <p className="text-xs text-neutral-500">计件明细</p>
            <p className="mt-1.5 text-xs leading-relaxed text-neutral-600">按人、工序、部位与套汇总。</p>
          </div>
        </div>
      </div>
    </Frame>
  )
}

export const featureVisuals = {
  customer: CustomerChatMock,
  decision: DashboardMock,
  production: ProductionMock,
  inventory: StockMock,
} as const
