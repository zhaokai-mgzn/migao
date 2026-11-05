// case_ids: MC-222
/**
 * 工人端**读面**的两块共享件（issue #7813 P2b）——「等一张码」与「旧码选套 + 部位」。
 *
 * ## 为什么要抽出来
 *
 * 三个读面（裁高计算 / 精裁清单 / 质检）都以同一件事开场：**先扫到一张码**。三页各写一份
 * ⇒ 一份改了「扫一扫」只在小程序可用、另一份忘了 ⇒ 同一个工人在三页上遇到三种行为
 * （本仓反复复发的形态：同一真值两处推导）。旧码选择块同理 —— `/w/` 的 `selectView`
 * 只有一份，读面也不许各写一份。
 *
 * ## 三条纪律
 *
 * 1. 🔴 **旧码绝不默认取第 1 套**：套号清单只**列出候选**，点哪套由工人决定；
 *    没选中套 ⇒ 部位一个都不渲染（{@link WorkerReadLegacyPicker} 的 `state.selection.setId` 判据）。
 * 2. 🔴 **不发起任何请求**：本组件只回调（`onPickSet` / `onPickPosition` / `onResolve`），
 *    解析与取数都在页面里 —— 组件不可测出第二套口径。
 * 3. 🔴 **没有扫码能力时不留死路**：h5 里 `Taro.scanCode` 只在微信内可用（`canUseNativeScan()`），
 *    用不了就**不摆**扫一扫按钮，只留手输码（不是把页面弄死，也不是点了没反应）。
 */
import { Button, Input, Text, View } from '@tarojs/components'
import {
  MISSING,
  readSelection,
  readSetChoices,
  type ReadFaceState,
} from '../utils/workerReadFaces'
import { canUseNativeScan } from '../utils/platform'
import './WorkerReadEntry.scss'

/** 手输提示（三个读面同一句）。 */
export const READ_MANUAL_HINT = '输码（加工单号 / 订单号 / 短码）'

/** 扫码提示（原生扫码不可用时的那一句）。 */
export const READ_SCAN_ENTRY_HINT = '请用微信「扫一扫」或手机相机扫码，或在下面输入单号'

export interface WorkerReadScanEntryProps {
  /** testID 前缀（如 `worker-cut-plan` ⇒ `worker-cut-plan-scan`） */
  prefix: string
  manual: string
  onManualChange: (value: string) => void
  onScan: () => void
  onResolve: () => void
  busy: boolean
}

/** 「等一张码」：扫一扫（仅原生可用时）+ 手输码 + 确定。 */
export function WorkerReadScanEntry({
  prefix,
  manual,
  onManualChange,
  onScan,
  onResolve,
  busy,
}: WorkerReadScanEntryProps) {
  const nativeScan = canUseNativeScan()
  return (
    <View className='worker-read' data-testid={`${prefix}-scan`}>
      {nativeScan ? (
        <Button
          className='worker-read__primary'
          data-testid={`${prefix}-scan-button`}
          disabled={busy}
          onClick={onScan}
        >
          {busy ? '读取中…' : '扫一扫'}
        </Button>
      ) : (
        <Text className='worker-read__hint' data-testid={`${prefix}-scan-entry-hint`}>
          {READ_SCAN_ENTRY_HINT}
        </Text>
      )}
      <Text className='worker-read__hint'>{READ_MANUAL_HINT}</Text>
      <Input
        className='worker-read__input'
        data-testid={`${prefix}-manual`}
        value={manual}
        placeholder={READ_MANUAL_HINT}
        onInput={(event) => onManualChange((event as any)?.detail?.value ?? '')}
      />
      <Button
        className='worker-read__ghost'
        data-testid={`${prefix}-manual-submit`}
        disabled={busy || manual.trim() === ''}
        onClick={onResolve}
      >
        确定
      </Button>
    </View>
  )
}

export interface WorkerReadLegacyPickerProps {
  prefix: string
  state: ReadFaceState
  onPickSet: (setId: string, setNo?: number | string | null) => void
  onPickPosition: (orderItemId: string, positionName?: string | null) => void
}

/**
 * 旧码降级选择块（`/w/` 的 `selectView` 同语义）：先选套，再选部位。
 *
 * 🔴 没选套 ⇒ **部位一个都不渲染**（"先点第 1 套看看"是前端替工人做的决定，正是要治的那条）。
 */
export function WorkerReadLegacyPicker({
  prefix,
  state,
  onPickSet,
  onPickPosition,
}: WorkerReadLegacyPickerProps) {
  const sets = readSetChoices(state)
  const currentSet = sets.find((set) => set.set_id === state.selection.setId)
  return (
    <View className='worker-read__legacy' data-testid={`${prefix}-legacy`}>
      <Text className='worker-read__notice' data-testid={`${prefix}-legacy-notice`}>
        {state.notice || '这是一张旧码：请先选择套号与部位'}
      </Text>
      {!state.selection.setId ? (
        <View className='worker-read__choices' data-testid={`${prefix}-sets`}>
          {sets.map((set, index) => (
            <Button
              key={set.set_id}
              className='worker-read__choice'
              data-testid={`${prefix}-set-${index}`}
              onClick={() => onPickSet(set.set_id, set.set_no)}
            >
              第 {set.set_no ?? index + 1} 套
            </Button>
          ))}
        </View>
      ) : (
        <View className='worker-read__choices' data-testid={`${prefix}-positions`}>
          {(currentSet?.positions ?? []).map((position, index) => (
            <Button
              key={position.order_item_id}
              className='worker-read__choice'
              data-testid={`${prefix}-position-${index}`}
              onClick={() => onPickPosition(position.order_item_id, position.position_name)}
            >
              {position.position_name || position.position_kind || MISSING}
            </Button>
          ))}
        </View>
      )}
      {readSelection(state) ? null : (
        <Text className='worker-read__hint'>选完套号和部位才会显示内容</Text>
      )}
    </View>
  )
}
