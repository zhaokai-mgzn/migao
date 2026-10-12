/**
 * 工人**拍照发货**（issue #6761；#5648 的 UI 面收口）
 *
 * 一条链：**拍照 / 选图 → 识别候选 → 工人核对（不确定的格子留空、绝不预填）→ 用单号定位订单
 * → 生成发货单（实发明细 + 运单号）→ 实发读面（套 / 件 / 卷说人话）**。
 *
 * ## 为什么这一页现在才存在
 *
 * #5648 把**后端**（`WorkerShipmentController` 的 `/api/worker/shipment/**`）与**纯逻辑**都落了码，
 * 而 `gh pr view 5664` §9 逐字登记「**页面装配…未做**」⇒ 这是个半成品：商家端
 * `WorkerPageConfigPanel` 对商家承诺的「发货（工人拍照发货的那一面）」没有对应的页面。
 * 本页是那个缺口，**零后端改动**。
 *
 * ## 页面上的四条纪律（都来自 #5648 已落码的口径）
 *
 * 1. **身份只由服务端解**：`X-Worker-Session-Id`；请求体里 `worker_id` / `worker_name` 一个字节都不进
 *    （发货留痕是**责任凭证** ⇒ 构造式白名单在 `src/utils/inbound/shipment.ts` 的 `buildShipBody`）；
 * 2. **识别只是候选**：`value` 为 null / 空串的格子**留空**，并逐格说清「这一格要手输」
 *    —— **绝不**预填 0 / 猜测值（服务端也会拒非正数，但前端不该先把脏值递上去）；
 * 3. **实发由人给**：识别只认得出一个总数、**不是**订单行的实发明细 ⇒ 数量/单位由工人填，
 *    缺了在提交前拦住（不白跑一次 422）；
 * 4. **幂等**：一次发货动作生成一把 `X-Client-Request-Id`，超时重发**复用同一把**
 *    ⇒ 服务端不重复发货（发货不可逆，重试必须安全）。
 *
 * 身份分流照既有范式（入库页 / 工人首页）：**没有工人 session 就只渲染引导 + 去登录的按钮**，
 * 一个写入口都不渲染 —— 一台商家设备看到「发货」按钮只会 401。
 */
import { useCallback, useRef, useState } from 'react'
import Taro from '@tarojs/taro'
import { Button, Image, Input, ScrollView, Text, View } from '@tarojs/components'
import { hasWorkerSession } from '../../../utils/workerSession'
import {
  buildShipBody,
  buildShipmentItem,
  formatShippedTotals,
  prefillFromRecognition,
  recognizeShipment,
  postWorkerShipment,
  readWorkerShipment,
  newShipmentRequestId,
  type ShipmentDraft,
  type ShipmentRecognition,
  type ShipmentView,
  type UncertainCell,
} from '../../../services/workerShipmentService'
import { uploadInboundPhoto } from '../../../services/workerInboundService'
import { scanResolve } from '../../../services/productionService'
import { SHIPMENT_WORKER_LOGIN_REQUIRED, WORKER_TAB_LOGIN_ROUTE } from '../../../utils/inbound/gaps'
import { MAX_INBOUND_PHOTOS } from '../../../utils/inbound/recognizeFlow'
import type { PendingPhoto } from '../../../utils/inbound/barcodeDecode'
import '../../../styles/admin-surfaces.scss'
import './index.scss'

/** 物流单位三选一（与后端 `parseDetails` 的话术同名：米 / 套 / 件）。 */
const SHIPMENT_UNITS = ['米', '套', '件']

type Phase = 'photo' | 'review' | 'summary'

/**
 * 识别候选里 `value` 为 null / 空串的格子 —— **逐格**说清要手输（键 + 中文名 + 为什么）。
 *
 * 页面上要有一处能断言「这一格是空的、且说明了要手输」的落点（`data-testid` 逐格带上键）。
 */
function UncertainHints({ cells }: { cells: UncertainCell[] }) {
  if (cells.length === 0) return null
  return (
    <View className='shipment-uncertain' data-testid='shipment-uncertain'>
      <Text className='shipment-uncertain__title'>这几格识别不确定，请手工填写：</Text>
      {cells.map((cell) => (
        <Text
          className='shipment-uncertain__item'
          key={`uncertain-${cell.key}`}
          data-testid={`shipment-uncertain-${cell.key}`}
        >
          {cell.label}：{cell.reason}
        </Text>
      ))}
    </View>
  )
}

export default function WorkerShipmentPage() {
  const workerReady = hasWorkerSession()
  const [phase, setPhase] = useState<Phase>('photo')
  const [photos, setPhotos] = useState<PendingPhoto[]>([])
  const [photoUrls, setPhotoUrls] = useState<string[]>([])
  const [recognition, setRecognition] = useState<ShipmentRecognition | null>(null)
  const [draft, setDraft] = useState<ShipmentDraft | null>(null)
  const [orderId, setOrderId] = useState('')
  const [trackingNo, setTrackingNo] = useState('')
  const [company, setCompany] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [view, setView] = useState<ShipmentView | null>(null)
  /** 幂等键：一次发货动作一把，重试**复用**（在 page 层持有 ⇒ 重渲染不换键）。 */
  const requestIdRef = useRef('')
  const hasShipment = (view?.shipments ?? []).length > 0

  const onPick = useCallback(async () => {
    setError('')
    try {
      const res: any = await Taro.chooseImage({
        count: MAX_INBOUND_PHOTOS,
        sizeType: ['compressed'],
        sourceType: ['camera', 'album'],
      })
      const paths: string[] = res?.tempFilePaths || []
      const files: any[] = res?.tempFiles || []
      const picked: PendingPhoto[] = paths.map((path, index) => ({
        tempFilePath: path,
        file: files[index]?.originalFileObj || path,
      }))
      if (picked.length === 0) {
        setError('没能拿到照片（可能没授权相册/相机权限），请重试或换用手机浏览器打开。')
        return
      }
      setPhotos(picked.slice(0, MAX_INBOUND_PHOTOS))
      setPhotoUrls([])
    } catch {
      setError('没能拿到照片（可能没授权相册/相机权限），请重试或换用手机浏览器打开。')
    }
  }, [])

  /** 上传照片（**复用既有通道** `POST /api/worker/inbound/upload`，不新造第二条上传链）+ 识别 */
  const onRecognize = useCallback(async () => {
    setError('')
    setBusy(true)
    try {
      const urls: string[] = []
      for (const photo of photos) {
        const uploaded = await uploadInboundPhoto(String(photo.tempFilePath || photo.file || ''))
        if (!uploaded.success || !uploaded.data?.url) {
          throw new Error(uploaded.message || '照片上传失败')
        }
        urls.push(uploaded.data.url)
      }
      const res = await recognizeShipment(urls)
      if (!res.success || !res.data) throw new Error(res.message || '识别失败')
      setPhotoUrls(urls)
      setRecognition(res.data)
      setDraft(prefillFromRecognition(res.data.fields))
      setPhase('review')
    } catch (e: any) {
      setError(e?.message || '识别失败，请重试或手工录入')
    } finally {
      setBusy(false)
    }
  }, [photos])

  /** 用识别出的单号（或工人手输）走**既有读面**定位订单 —— 拿 `order_id`，不新造后端端点 */
  const onLocate = useCallback(async () => {
    setError('')
    const token = String(draft?.orderNo || '').trim()
    if (!token) {
      setError('请先填写订单号（识别不到就照标签手输）。')
      return
    }
    setBusy(true)
    try {
      const res = await scanResolve(token)
      if (!res.success || !res.data?.order_id) {
        throw new Error(res.message || '没能定位到订单，请核对单号')
      }
      setOrderId(String(res.data.order_id))
    } catch (e: any) {
      setOrderId('')
      setError(e?.message || '没能定位到订单，请核对单号')
    } finally {
      setBusy(false)
    }
  }, [draft])

  const onSubmit = useCallback(async () => {
    setError('')
    if (!orderId) {
      setError('请先「定位订单」—— 拿不到订单就不知道该发给谁。')
      return
    }
    const quantity = String(draft?.quantity || '').trim()
    const unit = String(draft?.unit || '').trim()
    if (!quantity || Number(quantity) <= 0) {
      setError('请填写**实发**数量（识别不确定时手输，系统不替你猜）。')
      return
    }
    if (!unit) {
      setError('请选择实发单位（米 / 套 / 件）—— 单位不从订单行推算，推错就是记错单位。')
      return
    }
    if (!trackingNo.trim()) {
      setError('请填写货运单号（没有单号的"发货"在车间不可核对）。')
      return
    }
    // 一次发货动作一把键：首次生成，重试复用（超时重发不许重复发货）
    if (!requestIdRef.current) requestIdRef.current = newShipmentRequestId()
    const body = buildShipBody({
      trackingNo: trackingNo.trim(),
      logisticsCompany: company.trim(),
      photoRefs: photoUrls,
      // 识别留痕**原样**随发货请求提交（识别本身不落库，服务端只存不算）
      recognition,
      items: [
        buildShipmentItem({
          productName: String(draft?.productName || '').trim() || null,
          shippedQuantity: quantity,
          unit,
        }),
      ],
    })
    setBusy(true)
    try {
      const res = await postWorkerShipment(orderId, body, requestIdRef.current)
      if (!res.success) throw new Error(res.message || '发货失败，请重试')
      const detail = await readWorkerShipment(orderId)
      setView(detail.success && detail.data ? detail.data : { status: 'shipped' })
      setPhase('summary')
    } catch (e: any) {
      setError(e?.message || '发货失败，请重试')
    } finally {
      setBusy(false)
    }
  }, [orderId, draft, trackingNo, company, photoUrls, recognition])

  if (!workerReady) {
    return (
      <View className='admin-surface' data-testid='worker-shipment-page'>
        <View className='admin-surface__header'>
          <Text className='admin-surface__title'>拍照发货</Text>
          <Text className='admin-surface__subtitle'>{SHIPMENT_WORKER_LOGIN_REQUIRED}</Text>
        </View>
        <View className='admin-surface__body' data-testid='shipment-login-required'>
          <View
            className='admin-action admin-action--gold'
            data-testid='shipment-go-worker-login'
            onClick={() => Taro.navigateTo({ url: WORKER_TAB_LOGIN_ROUTE })}
          >
            <Text>去登录工人身份</Text>
          </View>
        </View>
      </View>
    )
  }

  return (
    <ScrollView scrollY className='admin-surface' data-testid='worker-shipment-page'>
      <View className='admin-surface__header'>
        <Text className='admin-surface__title'>拍照发货</Text>
        <Text className='admin-surface__subtitle'>
          拍订单行 / 商品标签 → 核对 → 定位订单 → 生成发货单（实发多少由你填）
        </Text>
      </View>

      <View className='admin-surface__body'>
        {error !== '' && (
          <View className='admin-notice' data-testid='shipment-error'>
            <Text className='admin-notice__text'>{error}</Text>
          </View>
        )}

        {phase === 'photo' && (
          <View className='admin-card' data-testid='shipment-step-photo'>
            <View className='admin-action' data-testid='shipment-pick' onClick={onPick}>
              <Text>拍照 / 选图（最多 {MAX_INBOUND_PHOTOS} 张）</Text>
            </View>
            <Text className='admin-card__meta' data-testid='shipment-photo-count'>
              已选 {photos.length} 张 · 照片清楚、单号完整时识别更准
            </Text>
            <View
              className={`admin-action admin-action--gold${busy || photos.length === 0 ? ' admin-action--disabled' : ''}`}
              data-testid='shipment-recognize'
              onClick={() => {
                if (busy || photos.length === 0) return
                onRecognize()
              }}
            >
              <Text>识别</Text>
            </View>
          </View>
        )}

        {phase === 'review' && draft && (
          <View className='admin-card' data-testid='shipment-review'>
            <Text className='admin-card__title'>识别完成，请核对</Text>
            <UncertainHints cells={draft.uncertain} />

            <Text className='admin-card__label'>订单号（定位订单用）</Text>
            <Input
              className='admin-input'
              data-testid='shipment-order-no'
              placeholder='订单号（识别不到就照标签抄）'
              value={draft.orderNo}
              onInput={(e: any) =>
                setDraft((prev) => (prev ? { ...prev, orderNo: e?.detail?.value ?? '' } : prev))
              }
            />
            <Text className='admin-card__label'>商品名称</Text>
            <Input
              className='admin-input'
              data-testid='shipment-product-name'
              placeholder='商品名称'
              value={draft.productName}
              onInput={(e: any) =>
                setDraft((prev) => (prev ? { ...prev, productName: e?.detail?.value ?? '' } : prev))
              }
            />
            <View className='shipment-pair'>
              <Text className='admin-card__label'>宽</Text>
              <Input
                className='admin-input'
                data-testid='shipment-width'
                placeholder='宽（米）'
                value={draft.width}
                onInput={(e: any) =>
                  setDraft((prev) => (prev ? { ...prev, width: e?.detail?.value ?? '' } : prev))
                }
              />
              <Text className='admin-card__label'>高</Text>
              <Input
                className='admin-input'
                data-testid='shipment-height'
                placeholder='高（米）'
                value={draft.height}
                onInput={(e: any) =>
                  setDraft((prev) => (prev ? { ...prev, height: e?.detail?.value ?? '' } : prev))
                }
              />
            </View>

            <View
              className='admin-action'
              data-testid='shipment-locate'
              onClick={() => {
                if (!busy) onLocate()
              }}
            >
              <Text>定位订单</Text>
            </View>
            {orderId !== '' && (
              <Text className='admin-card__meta' data-testid='shipment-located'>
                已定位订单 {orderId}
              </Text>
            )}

            <Text className='admin-card__label'>实发数量（识别给的是总数，实发由你填）</Text>
            <Input
              className='admin-input'
              data-testid='shipment-quantity'
              type='digit'
              placeholder='实发数量（大于 0，识别不确定就手输）'
              value={draft.quantity}
              onInput={(e: any) =>
                setDraft((prev) => (prev ? { ...prev, quantity: e?.detail?.value ?? '' } : prev))
              }
            />
            <View className='shipment-units'>
              {SHIPMENT_UNITS.map((unit) => (
                <View
                  className={`admin-action${draft.unit === unit ? ' admin-action--gold' : ''}`}
                  data-testid={`shipment-unit-${unit}`}
                  key={`unit-${unit}`}
                  onClick={() => setDraft((prev) => (prev ? { ...prev, unit } : prev))}
                >
                  <Text>{unit}</Text>
                </View>
              ))}
            </View>
            {/* 单位也有一个输入落点：工人可以照标签写别的单位（识别面不认单位，端侧也不推） */}
            <Input
              className='admin-input'
              data-testid='shipment-unit'
              placeholder='实发单位（米 / 套 / 件）'
              value={draft.unit}
              onInput={(e: any) =>
                setDraft((prev) => (prev ? { ...prev, unit: e?.detail?.value ?? '' } : prev))
              }
            />

            <Text className='admin-card__label'>货运单号（必填）</Text>
            <Input
              className='admin-input'
              data-testid='shipment-tracking'
              placeholder='货运单号'
              value={trackingNo}
              onInput={(e: any) => setTrackingNo(e?.detail?.value ?? '')}
            />
            <Input
              className='admin-input'
              data-testid='shipment-company'
              placeholder='承运商（可空）'
              value={company}
              onInput={(e: any) => setCompany(e?.detail?.value ?? '')}
            />

            <View
              className={`admin-action admin-action--gold${busy ? ' admin-action--disabled' : ''}`}
              data-testid='shipment-submit'
              onClick={() => {
                if (!busy) onSubmit()
              }}
            >
              <Text>生成发货单</Text>
            </View>
          </View>
        )}

        {phase === 'summary' && (
          <View className='admin-card' data-testid='shipment-summary'>
            <Text className='admin-card__title'>已提交发货</Text>
            <Text className='admin-card__meta'>订单状态：{view?.status || '—'}</Text>
            {hasShipment ? (
              <>
                <Text className='admin-card__totals' data-testid='shipment-totals'>
                  实发：{formatShippedTotals(view?.shipped_totals)}
                </Text>
                {(view?.shipments ?? []).map((row, index) => (
                  <View className='shipment-row' key={`shipment-${row.shipment_no || index}`}>
                    <Text className='shipment-row__title'>发货单 {row.shipment_no || '—'}</Text>
                    {(row.items ?? []).map((item, itemIndex) => (
                      <Text className='shipment-row__item' key={`item-${itemIndex}`}>
                        {item.product_name || '—'}：{item.shipped_quantity ?? '—'}
                        {item.unit || ''}
                      </Text>
                    ))}
                    <Text className='admin-card__meta'>
                      运单号：{row.tracking_no || '—'}　承运商：{row.logistics_company || '—'}
                    </Text>
                    <Text className='admin-card__meta'>
                      经手：{row.shipped_by || row.packed_by || '—'}　照片：
                      {(row.photo_refs ?? []).length} 张
                    </Text>
                    {row.unpacked_at ? (
                      <Text className='admin-card__meta'>
                        已撤销打包：{row.unpack_reason || '—'}（{row.unpacked_by || '—'}）
                      </Text>
                    ) : null}
                  </View>
                ))}
              </>
            ) : (
              // 读面没有发货单 ⇒ **不渲染空壳**（一块「实发：—」的面板只会让工人以为出错了）
              <Text className='admin-card__meta' data-testid='shipment-empty'>
                这次没有读到发货单，请让管理员在电脑端核对。
              </Text>
            )}
            {photoUrls.length > 0 && (
              <Image className='shipment-photo' src={photoUrls[0]} mode='widthFix' />
            )}
            <Button
              className='admin-action'
              data-testid='shipment-again'
              onClick={() => {
                setPhase('photo')
                setPhotos([])
                setPhotoUrls([])
                setRecognition(null)
                setDraft(null)
                setOrderId('')
                setTrackingNo('')
                setCompany('')
                setView(null)
                setError('')
                requestIdRef.current = ''
              }}
            >
              再发一单
            </Button>
          </View>
        )}
      </View>
    </ScrollView>
  )
}
