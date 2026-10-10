import { createRoot } from 'react-dom/client'
import { useEffect, useRef } from 'react'
import { QRCodeCanvas } from 'qrcode.react'
import { washLabelRows } from '@/lib/wash-label-content'
import { canvasTextMeasure } from '@/lib/label-print/render'
import {
  layoutWashLabel,
  paintWashLabel,
  resolveLabelGeometry,
  type WashLabelInput,
} from '@/lib/label-print/wash-label'
import type { ProcessingOrderItem, ProductionPosition } from '@/types'

declare global {
  interface Window {
    __PNG?: string
    __ROWS?: string[]
    __GEOMETRY?: { widthPx: number; heightPx: number }
  }
}

const QR_VALUE = 'https://app.migaozn.com/s/HV4C6EKK'

// 与用户截图那条真单同形：加工单 JG-20261006-5289 / 订单 20261006239740146
const position = {
  position_name: 'SD07演示布814127 墨绿',
  position_kind: '纱帘',
  order_item_id: 'item-1',
  set_no: 'JG-20261006-5289-001',
  product_name: 'SD07演示布814127',
  width: 2.5,
  height: 1.5,
  scan_url: QR_VALUE,
  part_token: 'tok-1',
  part_short_code: 'HV4C6EKK',
} as unknown as ProductionPosition

const item = {
  itemId: 'item-1',
  colorName: '墨绿',
  fabric_meters: 5.8,
  craft: '打孔',
  cuttingMode: '定高买宽',
  remark: '加铅块',
} as unknown as ProcessingOrderItem

function App() {
  const boxRef = useRef<HTMLDivElement | null>(null)
  const outRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const tick = () => {
      if (window.__PNG) return
      // 与 `DirectLabelPrint.collectQrSources` 同一取法：从容器里取 QRCodeCanvas 画出来的真 canvas
      const qr = boxRef.current?.querySelector('canvas') ?? null
      const out = outRef.current
      if (!qr || !out) {
        requestAnimationFrame(tick)
        return
      }
      const rows = washLabelRows({
        position,
        item,
        setNo: 1,
        setCount: 1,
        customerName: 'SD07演示客814127-123',
        orderNo: '20261006239740146',
        expectedDeliveryDate: null,
      })
      const input: WashLabelInput = {
        qrValue: QR_VALUE,
        shortCode: 'HV4C6EKK',
        processingOrderNo: 'JG-20261006-5289',
        rows,
      }
      const geometry = resolveLabelGeometry(null)
      out.width = geometry.widthPx
      out.height = geometry.heightPx
      const ctx = out.getContext('2d')
      if (!ctx) return
      const layout = layoutWashLabel(input, geometry, canvasTextMeasure(ctx))
      paintWashLabel(ctx, layout, qr)
      window.__ROWS = rows.map((row) => row.text)
      window.__GEOMETRY = { widthPx: geometry.widthPx, heightPx: geometry.heightPx }
      window.__PNG = out.toDataURL('image/png')
    }
    requestAnimationFrame(tick)
  }, [])

  return (
    <div>
      <div ref={boxRef}>
        <QRCodeCanvas value={QR_VALUE} size={256} level="M" />
      </div>
      <canvas ref={outRef} />
    </div>
  )
}

const container = document.createElement('div')
document.body.appendChild(container)
createRoot(container).render(<App />)
